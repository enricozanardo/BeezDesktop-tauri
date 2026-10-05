"""
BeezClient Wallet Utilities

Provides wallet creation, key derivation, and signing functionality.
This is the core cryptographic wallet implementation shared across all clients.
"""

import hashlib
import json
import base58
from typing import Optional

from mnemonic import Mnemonic
from ecdsa import SigningKey, VerifyingKey, SECP256k1, BadSignatureError
from ecdsa.util import sigencode_der, sigdecode_der


def serialize(obj) -> bytes:
    """Deterministic JSON encoding - matches Directory/Chain node serialization."""
    return json.dumps(obj, sort_keys=True).encode()


# ---------- Keys & Mnemonic ----------

def generate_mnemonic(strength: int = 128) -> str:
    """
    Generate a BIP39 mnemonic phrase.
    
    Args:
        strength: Entropy strength in bits (128 = 12 words, 256 = 24 words)
        
    Returns:
        Space-separated mnemonic phrase
    """
    return Mnemonic("english").generate(strength)


def mnemonic_to_privkey(mnemonic: str, passphrase: str = "") -> bytes:
    """
    Derive a 32-byte private key from a mnemonic phrase.
    
    Args:
        mnemonic: BIP39 mnemonic phrase
        passphrase: Optional passphrase for key derivation
        
    Returns:
        32-byte private key
    """
    seed = Mnemonic("english").to_seed(mnemonic, passphrase)
    return hashlib.sha256(seed).digest()


def privkey_to_address(privkey: bytes) -> str:
    """
    Derive a "bez..." address from a private key.
    
    Args:
        privkey: 32-byte private key
        
    Returns:
        Beez address string (e.g., "bez1abc...")
    """
    vk_bytes = SigningKey.from_string(privkey, curve=SECP256k1).verifying_key.to_string()
    h = hashlib.sha256(vk_bytes).digest()
    return "bez" + base58.b58encode(h[:20]).decode()


def pubkey_hex_to_address(pubkey_hex: str) -> str:
    """
    Derive a "bez..." address from a public key hex string.
    
    Args:
        pubkey_hex: Hex-encoded public key (64 bytes / 128 hex chars)
        
    Returns:
        Beez address string
    """
    vk_bytes = bytes.fromhex(pubkey_hex)
    h = hashlib.sha256(vk_bytes).digest()
    return "bez" + base58.b58encode(h[:20]).decode()


# ---------- Signing ----------

def sign_message(privkey: bytes, message: bytes) -> bytes:
    """
    Sign a message using ECDSA with secp256k1.
    
    Args:
        privkey: 32-byte private key
        message: Message bytes to sign
        
    Returns:
        DER-encoded signature
    """
    sk = SigningKey.from_string(privkey, curve=SECP256k1)
    return sk.sign(message, sigencode=sigencode_der)


def verify_signature(message: bytes, signature: bytes, pubkey: VerifyingKey) -> bool:
    """
    Verify an ECDSA signature.
    
    Args:
        message: Original message bytes
        signature: DER-encoded signature
        pubkey: ECDSA verifying key
        
    Returns:
        True if signature is valid
    """
    try:
        return pubkey.verify(signature, message, sigdecode=sigdecode_der)
    except BadSignatureError:
        return False


# ---------- Wallet Class ----------

class Wallet:
    """
    Beez wallet for key management and transaction signing.
    
    Attributes:
        mnemonic: BIP39 mnemonic phrase
        privkey: 32-byte private key
        sk: ECDSA signing key
        vk: ECDSA verifying key (public key)
        address: Beez address ("bez...")
    """
    
    def __init__(self, mnemonic: Optional[str] = None):
        """
        Create or restore a wallet.
        
        Args:
            mnemonic: Optional mnemonic to restore from. If None, generates new wallet.
        """
        self.mnemonic = mnemonic or generate_mnemonic()
        self.privkey = mnemonic_to_privkey(self.mnemonic)
        self.sk = SigningKey.from_string(self.privkey, curve=SECP256k1)
        self.vk: VerifyingKey = self.sk.verifying_key
        self.address = privkey_to_address(self.privkey)
    
    def sign(self, obj) -> bytes:
        """
        Sign a dictionary object (deterministically serialized).
        
        Args:
            obj: Dictionary to sign
            
        Returns:
            DER-encoded signature
        """
        return sign_message(self.privkey, serialize(obj))
    
    def verify(self, obj, signature: bytes) -> bool:
        """
        Verify a signature against a dictionary object.
        
        Args:
            obj: Dictionary that was signed
            signature: Signature to verify
            
        Returns:
            True if signature is valid
        """
        return verify_signature(serialize(obj), signature, self.vk)
    
    def get_pubkey_bytes(self) -> bytes:
        """
        Get the public key as raw bytes (64 bytes, uncompressed x||y).
        
        Returns:
            64-byte public key
        """
        return self.vk.to_string()
    
    def get_pubkey_hex(self) -> str:
        """
        Get the public key as a hex string.
        
        Returns:
            Hex-encoded public key
        """
        return self.vk.to_string().hex()
    
    def __repr__(self) -> str:
        return f"Wallet(address={self.address})"
