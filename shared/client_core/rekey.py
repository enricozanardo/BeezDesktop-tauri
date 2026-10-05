"""
BeezClient Re-encryption Service

Handles secure re-encryption of digital assets during ownership transfer.

Re-encryption Flow:
1. Current owner initiates ownership transfer
2. New owner accepts (payment transferred)
3. Current owner's client downloads encrypted chunks
4. Client decrypts with current owner's key
5. Client re-encrypts with shared key (via ECDH)
6. Re-encrypted chunks uploaded to storage nodes
7. Chunk hashes updated in PostgreSQL

Security Model:
- Uses ECDH (Elliptic Curve Diffie-Hellman) for key agreement
- Current owner derives shared key from: own_privkey + new_owner_pubkey
- New owner derives same shared key from: own_privkey + old_owner_pubkey
"""

import os
import hashlib
import base64
import zmq
from typing import Optional, Dict, List, Tuple, Any
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

DOMAIN_ECDH_WRAP = b"beez-ecdh-wrap-v1"

# ECDSA/ECDH imports
try:
    from ecdsa import SECP256k1, VerifyingKey, SigningKey
    ECDSA_AVAILABLE = True
except ImportError:
    ECDSA_AVAILABLE = False
    print("[REKEY] WARNING: ecdsa library not available", flush=True)


@dataclass
class RekeyResult:
    """Result of a re-encryption operation."""
    success: bool
    file_id: str
    chunks_rekeyed: int
    new_nonce: Optional[str] = None  # Base64 encoded
    error: Optional[str] = None


def derive_shared_key_ecdh(own_privkey: bytes, other_pubkey: bytes) -> bytes:
    """Derive a shared encryption key using ECDH + HKDF-SHA256.

    Both parties derive the same key:
    - Party A: own_privkey_A + pubkey_B -> shared_key
    - Party B: own_privkey_B + pubkey_A -> shared_key

    The raw ECDH x-coordinate is passed through HKDF with a domain-
    separation label to produce the final 32-byte key.

    Args:
        own_privkey: Own private key (32 bytes).
        other_pubkey: Other party's public key (64 bytes, uncompressed x||y).

    Returns:
        32-byte shared encryption key.
    """
    if not ECDSA_AVAILABLE:
        raise ImportError("ecdsa library required for ECDH key derivation")

    sk = SigningKey.from_string(own_privkey, curve=SECP256k1)
    vk = VerifyingKey.from_string(other_pubkey, curve=SECP256k1)

    shared_point = vk.pubkey.point * sk.privkey.secret_multiplier
    shared_bytes = shared_point.x().to_bytes(32, byteorder='big')

    hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=DOMAIN_ECDH_WRAP)
    return hkdf.derive(shared_bytes)


def derive_shared_key_ecdh_legacy(own_privkey: bytes, other_pubkey: bytes) -> bytes:
    """Legacy ECDH shared key derivation (SHA-256 only, no HKDF).

    Retained for backward compatibility with ownership transfers that
    used the pre-HKDF key wrapping.

    Args:
        own_privkey: Own private key (32 bytes).
        other_pubkey: Other party's public key (64 bytes).

    Returns:
        32-byte shared encryption key.
    """
    if not ECDSA_AVAILABLE:
        raise ImportError("ecdsa library required for ECDH key derivation")

    sk = SigningKey.from_string(own_privkey, curve=SECP256k1)
    vk = VerifyingKey.from_string(other_pubkey, curve=SECP256k1)

    shared_point = vk.pubkey.point * sk.privkey.secret_multiplier
    shared_bytes = shared_point.x().to_bytes(32, byteorder='big')
    return hashlib.sha256(shared_bytes).digest()


def encrypt_with_key(plaintext: bytes, key: bytes) -> Tuple[bytes, bytes]:
    """
    Encrypt data with AES-256-GCM using provided key.
    
    Args:
        plaintext: Data to encrypt
        key: 32-byte encryption key
        
    Returns:
        Tuple of (ciphertext_with_tag, nonce)
    """
    nonce = os.urandom(12)  # 96-bit nonce for GCM
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return ciphertext, nonce


def decrypt_with_key(ciphertext: bytes, nonce: bytes, key: bytes) -> bytes:
    """
    Decrypt data with AES-256-GCM using provided key.
    
    Args:
        ciphertext: Encrypted data with auth tag
        nonce: 12-byte nonce
        key: 32-byte encryption key
        
    Returns:
        Decrypted plaintext
    """
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None)


class RekeyService:
    """
    Service for re-encrypting digital assets during ownership transfer.
    
    This service runs on the current owner's client and handles:
    1. Downloading encrypted chunks from storage nodes
    2. Decrypting with current owner's wallet key
    3. Re-encrypting with shared key (ECDH with new owner)
    4. Uploading re-encrypted chunks
    5. Updating chunk hashes in blockchain
    """
    
    def __init__(self, wallet: Any, chain_nodes: List[Dict], dam_nodes: List[Dict] = None):
        """
        Initialize re-key service.
        
        Args:
            wallet: Current owner's wallet object
            chain_nodes: List of chain node dicts with 'ip' key
            dam_nodes: List of DAM node dicts (for storage node discovery)
        """
        self.wallet = wallet
        self.chain_nodes = chain_nodes
        self.dam_nodes = dam_nodes or []
        self.context = zmq.Context()
        self.timeout_ms = 30000  # 30 second timeout
    
    def _get_chain_socket(self) -> Optional[zmq.Socket]:
        """Get a ZMQ socket connected to a chain node."""
        if not self.chain_nodes:
            return None
        
        chain_node = self.chain_nodes[0]
        socket = self.context.socket(zmq.REQ)
        socket.setsockopt(zmq.RCVTIMEO, self.timeout_ms)
        socket.setsockopt(zmq.SNDTIMEO, self.timeout_ms)
        socket.setsockopt(zmq.LINGER, 0)
        socket.connect(f"tcp://{chain_node['ip']}:5555")
        return socket
    
    def _get_asset_info(self, file_id: str) -> Optional[Dict]:
        """Get asset metadata including encryption nonce and chunk locations."""
        socket = self._get_chain_socket()
        if not socket:
            return None
        
        try:
            socket.send_json({
                "type": "GET_ASSET_INFO",
                "file_id": file_id
            })
            response = socket.recv_json()
            
            if response.get("status_code") == 200:
                return response.get("asset")
            return None
        except Exception as e:
            print(f"[REKEY] Error getting asset info: {e}", flush=True)
            return None
        finally:
            socket.close()
    
    def _get_chunk_locations(self, file_id: str) -> Dict:
        """Get chunk locations from chain."""
        socket = self._get_chain_socket()
        if not socket:
            return {}
        
        try:
            socket.send_json({
                "type": "GET_CHUNK_LOCATIONS",
                "file_id": file_id
            })
            response = socket.recv_json()
            
            if response.get("status_code") == 200:
                return response.get("data", {})
            return {}
        except Exception as e:
            print(f"[REKEY] Error getting chunk locations: {e}", flush=True)
            return {}
        finally:
            socket.close()
    
    def _download_chunk(self, storage_ip: str, file_id: str, chunk_id: str) -> Optional[bytes]:
        """Download encrypted chunk from storage node."""
        socket = None
        try:
            socket = self.context.socket(zmq.REQ)
            socket.setsockopt(zmq.RCVTIMEO, self.timeout_ms)
            socket.setsockopt(zmq.LINGER, 0)
            socket.connect(f"tcp://{storage_ip}:5559")
            
            socket.send_json({
                "action": "verify_chunk",
                "file_id": file_id,
                "chunk_id": chunk_id
            })
            
            response = socket.recv_json()
            
            if response.get("success"):
                chunk_content = response.get("chunk_content")
                if chunk_content:
                    return chunk_content.encode("latin1")
            return None
        except Exception as e:
            print(f"[REKEY] Error downloading chunk: {e}", flush=True)
            return None
        finally:
            if socket:
                socket.close()
    
    def _upload_rekeyed_chunk(
        self,
        storage_ip: str,
        file_id: str,
        chunk_id: str,
        encrypted_data: bytes,
        new_hash: str
    ) -> bool:
        """Upload re-encrypted chunk to storage node."""
        socket = None
        try:
            socket = self.context.socket(zmq.REQ)
            socket.setsockopt(zmq.RCVTIMEO, self.timeout_ms)
            socket.setsockopt(zmq.LINGER, 0)
            socket.connect(f"tcp://{storage_ip}:5556")
            
            socket.send_json({
                "action": "store_rekeyed_chunk",
                "file_id": file_id,
                "chunk_id": chunk_id,
                "chunk_data": encrypted_data.decode("latin1"),
                "chunk_hash": new_hash,
                "rekey_operation": True
            })
            
            response = socket.recv_json()
            return response.get("success", False)
        except Exception as e:
            print(f"[REKEY] Error uploading rekeyed chunk: {e}", flush=True)
            return False
        finally:
            if socket:
                socket.close()
    
    def _update_chunk_hash(self, file_id: str, chunk_id: str, new_hash: str) -> bool:
        """Update chunk hash in PostgreSQL via chain."""
        socket = self._get_chain_socket()
        if not socket:
            return False
        
        try:
            socket.send_json({
                "type": "UPDATE_CHUNK_HASH",
                "file_id": file_id,
                "chunk_id": chunk_id,
                "new_hash": new_hash,
                "rekey_operation": True
            })
            response = socket.recv_json()
            return response.get("status_code") == 200
        except Exception as e:
            print(f"[REKEY] Error updating chunk hash: {e}", flush=True)
            return False
        finally:
            socket.close()
    
    def _derive_current_owner_key(self) -> bytes:
        """Derive encryption key from current owner's wallet via HKDF."""
        from shared.client_core.encryption import derive_encryption_key
        return derive_encryption_key(self.wallet)
    
    def rekey_asset(
        self,
        file_id: str,
        new_owner_pubkey: bytes,
        request_id: Optional[str] = None
    ) -> RekeyResult:
        """
        Re-encrypt a digital asset for a new owner.
        
        Args:
            file_id: UUID of the digital asset
            new_owner_pubkey: New owner's public key (64 bytes)
            request_id: Optional ownership request ID for status tracking
            
        Returns:
            RekeyResult with success status and details
        """
        print(f"[REKEY] Starting re-encryption for {file_id[:16]}...", flush=True)
        
        try:
            # Step 1: Get asset info and chunk locations
            asset_info = self._get_asset_info(file_id)
            if not asset_info:
                return RekeyResult(
                    success=False,
                    file_id=file_id,
                    chunks_rekeyed=0,
                    error="Asset not found"
                )
            
            # Verify ownership
            if asset_info.get("owner_address") != self.wallet.address:
                return RekeyResult(
                    success=False,
                    file_id=file_id,
                    chunks_rekeyed=0,
                    error="Not the asset owner"
                )
            
            old_nonce_b64 = asset_info.get("encryption_nonce")
            if not old_nonce_b64:
                return RekeyResult(
                    success=False,
                    file_id=file_id,
                    chunks_rekeyed=0,
                    error="Asset not encrypted (no nonce)"
                )
            
            old_nonce = base64.b64decode(old_nonce_b64)
            
            # Get chunk locations
            chunk_data = self._get_chunk_locations(file_id)
            if not chunk_data:
                return RekeyResult(
                    success=False,
                    file_id=file_id,
                    chunks_rekeyed=0,
                    error="No chunk locations found"
                )
            
            chunk_locations = chunk_data.get("chunk_locations", {})
            storage_nodes = chunk_data.get("storage_nodes", {})
            
            # Step 2: Derive keys
            current_owner_key = self._derive_current_owner_key()
            shared_key = derive_shared_key_ecdh(self.wallet.privkey, new_owner_pubkey)
            
            # Step 3: Generate new nonce for re-encrypted data
            new_nonce = os.urandom(12)
            new_nonce_b64 = base64.b64encode(new_nonce).decode('utf-8')
            
            # Step 4: Process each chunk
            chunks_rekeyed = 0
            total_chunks = len(chunk_locations)
            
            for chunk_id, node_ids in chunk_locations.items():
                if not node_ids:
                    continue
                
                node_id = node_ids[0]
                node_info = storage_nodes.get(node_id, {})
                storage_ip = node_info.get("ip")
                
                if not storage_ip:
                    continue
                
                # Download encrypted chunk
                encrypted_chunk = self._download_chunk(storage_ip, file_id, chunk_id)
                if not encrypted_chunk:
                    continue
                
                # Decrypt with current owner's key
                try:
                    decrypted_chunk = decrypt_with_key(encrypted_chunk, old_nonce, current_owner_key)
                except Exception as e:
                    print(f"[REKEY] Failed to decrypt chunk {chunk_id[:12]}...: {e}", flush=True)
                    continue
                
                # Re-encrypt with shared key
                rekeyed_chunk, _ = encrypt_with_key(decrypted_chunk, shared_key)
                
                # Calculate new hash
                new_hash = hashlib.sha256(rekeyed_chunk).hexdigest()
                
                # Upload re-encrypted chunk
                if not self._upload_rekeyed_chunk(storage_ip, file_id, chunk_id, rekeyed_chunk, new_hash):
                    continue
                
                # Update chunk hash in PostgreSQL
                if not self._update_chunk_hash(file_id, chunk_id, new_hash):
                    continue
                
                chunks_rekeyed += 1
                print(f"[REKEY] Chunk {chunk_id[:12]}... re-encrypted", flush=True)
            
            success = chunks_rekeyed == total_chunks
            print(f"[REKEY] Re-encryption {'completed' if success else 'partially completed'}: {chunks_rekeyed}/{total_chunks}", flush=True)
            
            return RekeyResult(
                success=success,
                file_id=file_id,
                chunks_rekeyed=chunks_rekeyed,
                new_nonce=new_nonce_b64,
                error=None if success else f"Only {chunks_rekeyed}/{total_chunks} chunks processed"
            )
            
        except Exception as e:
            print(f"[REKEY] Error during re-encryption: {e}", flush=True)
            return RekeyResult(
                success=False,
                file_id=file_id,
                chunks_rekeyed=0,
                error=str(e)
            )


def get_pubkey_from_address(chain_nodes: List[Dict], address: str) -> Optional[bytes]:
    """
    Get public key for a wallet address from chain.
    
    Args:
        chain_nodes: List of chain node dicts
        address: Wallet address (bez...)
        
    Returns:
        64-byte public key or None
    """
    if not chain_nodes:
        return None
    
    context = zmq.Context()
    socket = context.socket(zmq.REQ)
    socket.setsockopt(zmq.RCVTIMEO, 10000)
    socket.setsockopt(zmq.LINGER, 0)
    
    try:
        socket.connect(f"tcp://{chain_nodes[0]['ip']}:5555")
        socket.send_json({
            "type": "GET_WALLET_PUBKEY",
            "address": address
        })
        response = socket.recv_json()
        
        if response.get("status_code") == 200:
            pubkey_hex = response.get("pubkey")
            if pubkey_hex:
                return bytes.fromhex(pubkey_hex)
        return None
    except Exception as e:
        print(f"[REKEY] Error getting pubkey: {e}", flush=True)
        return None
    finally:
        socket.close()
