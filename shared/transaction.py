"""
BeezMaster Shared Transaction Module

Contains the Transaction dataclass used by all node types.
This ensures consistent transaction format across the network.

Usage:
    from shared.transaction import Transaction
    
    # Create a normal transaction
    tx = Transaction.make_normal(sender, recipient, amount, wallet)
    
    # Create a penalty transaction (DAM only)
    tx = Transaction.make_penalty(target_node_id, ..., dam_wallet)
"""

from dataclasses import dataclass, asdict, field
from typing import List, Optional, Dict, Any, TYPE_CHECKING
import time
import json
import hashlib

# Type hint for Wallet without requiring the import at runtime
if TYPE_CHECKING:
    from client_network.common.wallet_utils import Wallet


def get_timestamp() -> str:
    """Generate a timestamp in ISO format with timezone."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%d %H:%M:%S UTC+00:00")


def serialize_tx(tx_dict: dict) -> bytes:
    """Serialize transaction dict to bytes for signing."""
    return json.dumps(tx_dict, sort_keys=True, separators=(',', ':')).encode('utf-8')


@dataclass
class Transaction:
    """
    Universal transaction dataclass for the Beez Network.
    
    Transaction Types:
    - normal: Standard BZT transfer between wallets
    - upload: Register file upload on blockchain
    - freeze: Magister-initiated wallet freeze (4/5 multisig)
    - rollback: Magister-initiated transaction reversal (4/5 multisig)
    - penalty: DAM-generated reputation penalty (single sig)
    - escrow: DAM-generated storage reward (single sig)
    - update_chunk_location: DAM-generated chunk migration record (single sig)
    - ownership_request: Initiate ownership transfer of digital asset
    - ownership_accept: Accept ownership transfer (triggers payment)
    - ownership_reject: Reject ownership transfer request
    - ownership_cancel: Cancel ownership request (by current owner)
    - update_digital_asset_price: Owner updates asset marketplace price
    - update_digital_asset_visibility: Owner toggles asset public/private
    """
    
    # ---- common fields -------------------------------------------------
    type: str                       # Transaction type
    nonce: int                       # Unique number for TX
    sender: Optional[str] = None
    recipient: Optional[str] = None
    amount: Optional[str] = None
  
    # ---- freeze transaction fields ----------------------------------------
    target_address: Optional[str] = None
    duration_blocks: Optional[int] = None

    # ---- rollback transaction fields --------------------------------------
    target_tx_hash: Optional[str] = None
    from_address: Optional[str] = None
    to_address: Optional[str] = None

    # ---- governance fields (freeze & rollback) ----------------------------
    reason: Optional[str] = None
    magister_signatures: Optional[List[Dict]] = None

    # ---- upload transaction fields ----------------------------------------
    uploader: Optional[str] = None
    file_id: Optional[str] = None
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    num_chunks: Optional[int] = None
    chunk_locations: Optional[Dict] = None
    backup_chunk_locations: Optional[Dict] = None
    storage_duration: Optional[int] = None
    query_hash: Optional[str] = None
    encryption_nonce: Optional[str] = None
    extension: Optional[str] = None          # Original file extension (e.g., "pdf", "jpg")
    guardian_dam_id: Optional[str] = None
    blur: Optional[str] = None  # Preview blur: "none" or "blur"
    preview_data: Optional[str] = None  # Base64-encoded blurred preview image
    preview_hash: Optional[str] = None  # SHA256 hash of preview image
    preview_width: Optional[int] = None  # Preview image width
    preview_height: Optional[int] = None  # Preview image height
    tags: Optional[List[str]] = None     # Asset tags (stored in PostgreSQL during sync)
    marketplace_price: Optional[str] = None  # Explicit marketplace price (mirrors new_price for uploads)

    # ---- penalty transaction fields (DAM-generated) -----------------------
    target_node_id: Optional[str] = None
    target_node_address: Optional[str] = None
    penalty_score: Optional[int] = None
    evidence_hash: Optional[str] = None
    verification_type: Optional[str] = None
    dam_address: Optional[str] = None

    # ---- escrow transaction fields (DAM-generated) ------------------------
    storage_node_id: Optional[str] = None
    storage_node_address: Optional[str] = None
    escrow_amount: Optional[str] = None
    verification_period: Optional[int] = None
    chunks_verified: Optional[int] = None

    # ---- update_chunk_location transaction fields (DAM-generated) ---------
    old_node_id: Optional[str] = None
    new_node_id: Optional[str] = None
    migrated_chunks: Optional[List[str]] = None
    migration_reason: Optional[str] = None

    # ---- ownership transaction fields -------------------------------------
    # Used by: ownership_request, ownership_accept, ownership_reject, ownership_cancel
    request_id: Optional[str] = None           # UUID of the ownership request
    current_owner: Optional[str] = None        # Current owner's wallet address
    new_owner: Optional[str] = None            # Proposed new owner's wallet address
    asking_price: Optional[str] = None         # Price in BZT (e.g., "10.5 BZT")
    ownership_message: Optional[str] = None    # Optional message
    wrapped_file_key: Optional[str] = None     # Base64 ECDH-wrapped encryption key
    wrap_nonce: Optional[str] = None           # Base64 nonce for key wrapping
    file_encryption_nonce: Optional[str] = None # Base64 original file encryption nonce
    seller_pubkey: Optional[str] = None        # Hex seller public key for ECDH

    # ---- asset update transaction fields -------------------------------------
    # Used by: update_digital_asset_price, update_digital_asset_visibility
    owner_address: Optional[str] = None        # Asset owner's wallet address
    new_price: Optional[str] = None            # New price in BZT (e.g., "25.0 BZT")
    old_price: Optional[str] = None            # Previous price (for history)
    visibility: Optional[str] = None           # "public" or "private"
    update_reason: Optional[str] = None        # Optional reason for update

    # ---- signature fields -------------------------------------------------
    sig: str = ""
    pub: str = ""
    sigs: List[str] = field(default_factory=list)
    pubkeys: List[str] = field(default_factory=list)
    timestamp: str = field(default_factory=get_timestamp)
    tx_hash: str = ""
    signature: str = ""

    def compute_hash(self):
        """Compute transaction hash based on type."""
        if self.type == "upload":
            guardian = self.guardian_dam_id if self.guardian_dam_id else ""
            payload = f"{self.uploader}|{self.file_id}|{self.file_name}|{self.amount}|{self.storage_duration}|{guardian}|{self.timestamp}"
        elif self.type in ["freeze", "rollback"]:
            tx_dict = self.to_dict()
            for k in ["tx_hash", "sig", "pub", "sigs", "pubkeys", "signature"]:
                tx_dict.pop(k, None)
            tx_json = json.dumps(tx_dict, sort_keys=True)
            self.tx_hash = hashlib.sha256(tx_json.encode()).hexdigest()
            return
        elif self.type == "penalty":
            payload = f"{self.dam_address}|{self.target_node_id}|{self.target_node_address}|{self.penalty_score}|{self.evidence_hash}|{self.verification_type}|{self.timestamp}"
        elif self.type == "escrow":
            payload = f"{self.dam_address}|{self.storage_node_id}|{self.storage_node_address}|{self.escrow_amount}|{self.verification_period}|{self.chunks_verified}|{self.timestamp}"
        elif self.type == "update_chunk_location":
            chunks_str = ",".join(sorted(self.migrated_chunks or []))
            payload = f"{self.dam_address}|{self.file_id}|{self.old_node_id}|{self.new_node_id}|{chunks_str}|{self.migration_reason}|{self.timestamp}"
        elif self.type == "ownership_request":
            # Ownership transfer request from current owner
            payload = f"{self.current_owner}|{self.new_owner}|{self.file_id}|{self.asking_price}|{self.timestamp}"
        elif self.type == "ownership_accept":
            # Accept ownership transfer (new owner pays asking_price)
            payload = f"{self.new_owner}|{self.request_id}|{self.file_id}|{self.asking_price}|{self.timestamp}"
        elif self.type == "ownership_reject":
            # Reject ownership transfer request
            payload = f"{self.new_owner}|{self.request_id}|{self.file_id}|{self.timestamp}"
        elif self.type == "ownership_cancel":
            # Cancel ownership request (by current owner)
            payload = f"{self.current_owner}|{self.request_id}|{self.file_id}|{self.timestamp}"
        elif self.type == "update_digital_asset_price":
            # Update asset price (owner only)
            payload = f"{self.owner_address}|{self.file_id}|{self.new_price}|{self.timestamp}"
        elif self.type == "update_digital_asset_visibility":
            # Update asset visibility (owner only)
            payload = f"{self.owner_address}|{self.file_id}|{self.visibility}|{self.timestamp}"
        else:
            # Normal transactions
            payload = f"{self.sender}|{self.recipient}|{self.amount}|{self.timestamp}"
        
        self.tx_hash = hashlib.sha256(payload.encode()).hexdigest()

    def to_dict(self) -> dict:
        """Convert to dictionary, filtering out None values."""
        return {k: v for k, v in asdict(self).items() if v is not None and v != "" and v != []}

    def _canonical_dict(self) -> dict:
        """
        Returns only relevant fields for signature, matching chain's canonicalize_for_signature.
        
        Must match BeezChain/chain_network/utils/validation.py:canonicalize_for_signature()
        """
        t = self.type
        
        # Define keys per transaction type - must match chain validation
        if t == "upload":
            keys = [
                "type","nonce","amount","uploader","file_id","file_name",
                "file_size","num_chunks","chunk_locations","backup_chunk_locations",
                "storage_duration","query_hash","encryption_nonce","guardian_dam_id",
                "timestamp","tx_hash"
            ]
        elif t == "storage_payment":
            keys = [
                "type","nonce","uploader_address","file_id","query_hash",
                "storage_cost_BZT","storage_duration","beneficiary_nodes",
                "timestamp","tx_hash"
            ]
        elif t == "penalty":
            keys = [
                "type","nonce","target_node_id","target_node_address","penalty_score",
                "evidence_hash","verification_type","reason","dam_address",
                "timestamp","tx_hash"
            ]
        elif t == "escrow":
            keys = [
                "type","nonce","storage_node_id","storage_node_address","escrow_amount",
                "verification_period","chunks_verified","dam_address","file_id",
                "timestamp","tx_hash"
            ]
        elif t == "escrow_release":
            keys = [
                "type","nonce","escrow_tx_hash","storage_node_id","storage_node_address",
                "release_amount","chunks_verified","verified_chunk_ids","dam_address","file_id",
                "timestamp","tx_hash"
            ]
        elif t == "escrow_unlock":
            keys = [
                "type","nonce","escrow_tx_hash","storage_node_id","storage_node_address",
                "dam_address","file_id","unlock_reason","verified_beneficiaries",
                "timestamp","tx_hash"
            ]
        elif t == "update_chunk_location":
            keys = [
                "type","nonce","file_id","old_node_id","new_node_id",
                "migrated_chunks","migration_reason","dam_address",
                "timestamp","tx_hash"
            ]
        elif t == "ownership_request":
            # Note: sig and pub are NOT included - signature computed BEFORE those fields exist
            keys = [
                "type","nonce","file_id","current_owner","new_owner","asking_price",
                "ownership_message","timestamp","tx_hash"
            ]
        elif t == "ownership_accept":
            # Note: sig and pub are NOT included - signature computed BEFORE those fields exist
            keys = [
                "type","nonce","request_id","file_id","new_owner",
                "asking_price","ownership_message","timestamp","tx_hash"
            ]
        elif t == "ownership_reject":
            # Note: sig and pub are NOT included - signature computed BEFORE those fields exist
            keys = [
                "type","nonce","request_id","file_id","new_owner",
                "ownership_message","timestamp","tx_hash"
            ]
        elif t == "ownership_cancel":
            # Note: sig and pub are NOT included - signature computed BEFORE those fields exist
            keys = [
                "type","nonce","request_id","file_id","current_owner",
                "timestamp","tx_hash"
            ]
        elif t == "update_digital_asset_price":
            # Note: sig and pub are NOT included - they're added after signing
            keys = [
                "type","nonce","file_id","owner_address","new_price",
                "old_price","update_reason","timestamp","tx_hash"
            ]
        elif t == "update_digital_asset_visibility":
            # Note: sig and pub are NOT included - they're added after signing
            keys = [
                "type","nonce","file_id","owner_address","visibility",
                "update_reason","timestamp","tx_hash"
            ]
        else:
            # normal transactions
            keys = ["type","nonce","sender","recipient","amount","timestamp","tx_hash"]
        
        # Build dict with only specified keys that have values
        d = asdict(self)
        out = {}
        for k in keys:
            if k in d and d[k] not in (None, "", []):
                out[k] = d[k]
        
        # Normalize chunk_locations for deterministic serialization
        if out.get("chunk_locations") and isinstance(out["chunk_locations"], dict):
            out["chunk_locations"] = {sk: sorted(v) for sk, v in sorted(out["chunk_locations"].items())}
        if out.get("backup_chunk_locations") and isinstance(out["backup_chunk_locations"], dict):
            out["backup_chunk_locations"] = {sk: sorted(v) for sk, v in sorted(out["backup_chunk_locations"].items())}
        if out.get("beneficiary_nodes") and isinstance(out["beneficiary_nodes"], list):
            out["beneficiary_nodes"] = sorted(out["beneficiary_nodes"], key=lambda x: x.get("node_id", ""))
        
        return out

    def sign_with_wallet(self, wallet: Any) -> None:
        """
        Sign the transaction with a wallet.
        
        Args:
            wallet: Wallet object with privkey and vk attributes.
                    privkey can be bytes or an ecdsa.SigningKey instance.
        """
        from ecdsa import SigningKey as _SK, SECP256k1
        from ecdsa.util import sigencode_der
        
        if not self.timestamp:
            self.timestamp = get_timestamp()
        
        self.compute_hash()
        canonical = self._canonical_dict()
        msg = serialize_tx(canonical)
        
        # wallet.privkey may be raw bytes or an ecdsa.SigningKey
        privkey = wallet.privkey
        if isinstance(privkey, _SK):
            sig_bytes = privkey.sign(msg, sigencode=sigencode_der)
        elif isinstance(privkey, bytes):
            sk = _SK.from_string(privkey, curve=SECP256k1)
            sig_bytes = sk.sign(msg, sigencode=sigencode_der)
        else:
            raise TypeError(f"wallet.privkey has unexpected type: {type(privkey)}")
        
        self.sig = sig_bytes.hex()
        self.pub = wallet.vk.to_string().hex()
        self.signature = self.sig

    # =========================================================================
    # Factory Methods for DAM-generated transactions
    # =========================================================================
    
    @classmethod
    def make_penalty(cls, target_node_id: str, target_node_address: str,
                     penalty_score: int, evidence_hash: str,
                     verification_type: str, reason: str,
                     dam_wallet: Any) -> "Transaction":
        """
        Create a signed penalty transaction.
        
        Generated by DAM when a storage node fails chunk verification.
        
        Args:
            target_node_id: Storage node ID being penalized
            target_node_address: Storage node wallet address
            penalty_score: Negative reputation impact (-1 to -100)
            evidence_hash: SHA256 hash of verification evidence
            verification_type: Type of failed verification ("chunk_integrity", "availability", "latency")
            reason: Human-readable explanation
            dam_wallet: DAM wallet object for signing
            
        Returns:
            Signed penalty transaction
        """
        tx = cls(
            type="penalty",
            nonce=int(time.time()),
            target_node_id=target_node_id,
            target_node_address=target_node_address,
            penalty_score=penalty_score,
            evidence_hash=evidence_hash,
            verification_type=verification_type,
            reason=reason,
            dam_address=dam_wallet.address,
        )
        tx.sign_with_wallet(dam_wallet)
        return tx

    @classmethod
    def make_escrow(cls, storage_node_id: str, storage_node_address: str,
                    escrow_amount: str, verification_period: int,
                    chunks_verified: int, file_id: str,
                    dam_wallet: Any) -> "Transaction":
        """
        Create a signed escrow transaction.
        
        Generated by DAM to reward storage node after successful verification.
        
        Args:
            storage_node_id: Storage node ID being rewarded
            storage_node_address: Storage node wallet address
            escrow_amount: Amount to release (e.g., "1.5 BZT")
            verification_period: Hours of successful verification
            chunks_verified: Number of chunks verified
            file_id: Associated file ID
            dam_wallet: DAM wallet object for signing
            
        Returns:
            Signed escrow transaction
        """
        tx = cls(
            type="escrow",
            nonce=int(time.time()),
            storage_node_id=storage_node_id,
            storage_node_address=storage_node_address,
            escrow_amount=escrow_amount,
            verification_period=verification_period,
            chunks_verified=chunks_verified,
            file_id=file_id,
            dam_address=dam_wallet.address,
        )
        tx.sign_with_wallet(dam_wallet)
        return tx

    @classmethod
    def make_update_chunk_location(cls, file_id: str, old_node_id: str,
                                   new_node_id: str, migrated_chunks: List[str],
                                   migration_reason: str,
                                   dam_wallet: Any) -> "Transaction":
        """
        Create a signed chunk location update transaction.
        
        Generated by DAM when chunks are migrated to a new storage node.
        
        Args:
            file_id: File ID whose chunks are migrated
            old_node_id: Failed/banned storage node ID
            new_node_id: Replacement storage node ID
            migrated_chunks: List of migrated chunk IDs
            migration_reason: "ban", "failure", or "rebalance"
            dam_wallet: DAM wallet object for signing
            
        Returns:
            Signed update_chunk_location transaction
        """
        tx = cls(
            type="update_chunk_location",
            nonce=int(time.time()),
            file_id=file_id,
            old_node_id=old_node_id,
            new_node_id=new_node_id,
            migrated_chunks=migrated_chunks,
            migration_reason=migration_reason,
            dam_address=dam_wallet.address,
        )
        tx.sign_with_wallet(dam_wallet)
        return tx

    # =========================================================================
    # Factory Methods for Ownership Transactions (Client-generated)
    # =========================================================================

    @classmethod
    def make_ownership_request(cls, file_id: str, current_owner: str,
                               new_owner: str, asking_price: str,
                               wallet: Any, message: Optional[str] = None,
                               wrapped_file_key: Optional[str] = None,
                               wrap_nonce: Optional[str] = None,
                               encryption_nonce: Optional[str] = None,
                               seller_pubkey: Optional[str] = None) -> "Transaction":
        """
        Create a signed ownership transfer request.
        
        Initiated by current owner to offer asset to a new owner.
        Includes ECDH-wrapped encryption key so new owner can decrypt the file.
        
        Args:
            file_id: UUID of the digital asset
            current_owner: Current owner's wallet address (must match wallet)
            new_owner: Proposed new owner's wallet address
            asking_price: Price in BZT (e.g., "10.5 BZT")
            wallet: Current owner's wallet object for signing
            message: Optional message to new owner
            wrapped_file_key: Base64-encoded ECDH-wrapped encryption key
            wrap_nonce: Base64-encoded nonce for the key wrapping
            encryption_nonce: Base64-encoded nonce for file decryption
            seller_pubkey: Hex-encoded seller public key for ECDH
            
        Returns:
            Signed ownership_request transaction
        """
        kwargs = dict(
            type="ownership_request",
            nonce=int(time.time()),
            file_id=file_id,
            current_owner=current_owner,
            new_owner=new_owner,
            asking_price=asking_price,
            ownership_message=message,
        )
        
        # Add encryption key wrapping data if file is encrypted
        if wrapped_file_key:
            kwargs["wrapped_file_key"] = wrapped_file_key
        if wrap_nonce:
            kwargs["wrap_nonce"] = wrap_nonce
        if encryption_nonce:
            kwargs["file_encryption_nonce"] = encryption_nonce
        if seller_pubkey:
            kwargs["seller_pubkey"] = seller_pubkey
        
        tx = cls(**kwargs)
        tx.sign_with_wallet(wallet)
        return tx

    @classmethod
    def make_ownership_accept(cls, request_id: str, file_id: str,
                              new_owner: str, asking_price: str,
                              wallet: Any, message: Optional[str] = None,
                              current_owner: Optional[str] = None) -> "Transaction":
        """
        Create a signed ownership acceptance.
        
        Can be signed by either party:
        - NEW OWNER signs when accepting a seller-initiated offer (buyer pays)
        - CURRENT OWNER signs when approving a buyer-initiated request
        
        Args:
            request_id: UUID/tx_hash of the ownership request
            file_id: UUID of the digital asset
            new_owner: Buyer's wallet address
            asking_price: Price in BZT (must match request)
            wallet: Signer's wallet (buyer or seller)
            message: Optional response message
            current_owner: If set, indicates seller is signing (buyer-initiated flow)
            
        Returns:
            Signed ownership_accept transaction
        """
        kwargs = dict(
            type="ownership_accept",
            nonce=int(time.time()),
            request_id=request_id,
            file_id=file_id,
            new_owner=new_owner,
            asking_price=asking_price,
            ownership_message=message,
        )
        if current_owner:
            kwargs["current_owner"] = current_owner
        tx = cls(**kwargs)
        tx.sign_with_wallet(wallet)
        return tx

    @classmethod
    def make_ownership_reject(cls, request_id: str, file_id: str,
                              new_owner: str, wallet: Any,
                              message: Optional[str] = None) -> "Transaction":
        """
        Create a signed ownership rejection.
        
        New owner rejects the transfer request.
        
        Args:
            request_id: UUID of the ownership request
            file_id: UUID of the digital asset
            new_owner: New owner's wallet address (must match wallet)
            wallet: New owner's wallet object for signing
            message: Optional reason for rejection
            
        Returns:
            Signed ownership_reject transaction
        """
        tx = cls(
            type="ownership_reject",
            nonce=int(time.time()),
            request_id=request_id,
            file_id=file_id,
            new_owner=new_owner,
            ownership_message=message,
        )
        tx.sign_with_wallet(wallet)
        return tx

    @classmethod
    def make_ownership_cancel(cls, request_id: str, file_id: str,
                              current_owner: str, wallet: Any) -> "Transaction":
        """
        Create a signed ownership request cancellation.
        
        Current owner cancels their transfer request.
        
        Args:
            request_id: UUID of the ownership request
            file_id: UUID of the digital asset
            current_owner: Current owner's wallet address (must match wallet)
            wallet: Current owner's wallet object for signing
            
        Returns:
            Signed ownership_cancel transaction
        """
        tx = cls(
            type="ownership_cancel",
            nonce=int(time.time()),
            request_id=request_id,
            file_id=file_id,
            current_owner=current_owner,
        )
        tx.sign_with_wallet(wallet)
        return tx

    # =========================================================================
    # Factory Methods for Asset Update Transactions (Client-generated)
    # =========================================================================

    @classmethod
    def make_update_price(cls, file_id: str, owner_address: str,
                          new_price: str, wallet: Any,
                          old_price: Optional[str] = None,
                          reason: Optional[str] = None) -> "Transaction":
        """
        Create a signed asset price update transaction.
        
        Only the asset owner can update the price.
        
        Args:
            file_id: UUID of the digital asset
            owner_address: Asset owner's wallet address (must match wallet)
            new_price: New price in BZT (e.g., "25.0 BZT")
            wallet: Owner's wallet object for signing
            old_price: Optional previous price for history
            reason: Optional reason for price change
            
        Returns:
            Signed update_digital_asset_price transaction
        """
        tx = cls(
            type="update_digital_asset_price",
            nonce=int(time.time()),
            file_id=file_id,
            owner_address=owner_address,
            new_price=new_price,
            old_price=old_price,
            update_reason=reason,
        )
        tx.sign_with_wallet(wallet)
        return tx

    @classmethod
    def make_update_visibility(cls, file_id: str, owner_address: str,
                               visibility: str, wallet: Any,
                               reason: Optional[str] = None) -> "Transaction":
        """
        Create a signed asset visibility update transaction.
        
        Only the asset owner can toggle visibility.
        
        Args:
            file_id: UUID of the digital asset
            owner_address: Asset owner's wallet address (must match wallet)
            visibility: "public" or "private"
            wallet: Owner's wallet object for signing
            reason: Optional reason for visibility change
            
        Returns:
            Signed update_digital_asset_visibility transaction
        """
        if visibility not in ("public", "private"):
            raise ValueError(f"visibility must be 'public' or 'private', got: {visibility}")
        
        tx = cls(
            type="update_digital_asset_visibility",
            nonce=int(time.time()),
            file_id=file_id,
            owner_address=owner_address,
            visibility=visibility,
            update_reason=reason,
        )
        tx.sign_with_wallet(wallet)
        return tx


# ============================================================================
# Factory methods for DAM-generated transactions
# These should ONLY be called from BeezDAM nodes
# ============================================================================

def make_penalty_tx(target_node_id: str, target_node_address: str,
                    penalty_score: int, evidence_hash: str,
                    verification_type: str, reason: str,
                    dam_address: str) -> Transaction:
    """
    Create a penalty transaction (DAM only).
    
    Args:
        target_node_id: Storage node ID being penalized
        target_node_address: Storage node wallet address
        penalty_score: Negative reputation impact (-1 to -100)
        evidence_hash: SHA256 hash of verification evidence
        verification_type: Type of failed verification
        reason: Human-readable explanation
        dam_address: DAM wallet address
    
    Returns:
        Transaction (unsigned - caller must sign)
    """
    tx = Transaction(
        type="penalty",
        nonce=int(time.time()),
        target_node_id=target_node_id,
        target_node_address=target_node_address,
        penalty_score=penalty_score,
        evidence_hash=evidence_hash,
        verification_type=verification_type,
        reason=reason,
        dam_address=dam_address,
    )
    tx.compute_hash()
    return tx


def make_escrow_tx(storage_node_id: str, storage_node_address: str,
                   escrow_amount: str, verification_period: int,
                   chunks_verified: int, file_id: str,
                   dam_address: str) -> Transaction:
    """
    Create an escrow transaction (DAM only).
    
    Args:
        storage_node_id: Storage node ID being rewarded
        storage_node_address: Storage node wallet address
        escrow_amount: Amount to release (e.g., "1.5 BZT")
        verification_period: Hours of successful verification
        chunks_verified: Number of chunks verified
        file_id: Associated file ID
        dam_address: DAM wallet address
    
    Returns:
        Transaction (unsigned - caller must sign)
    """
    tx = Transaction(
        type="escrow",
        nonce=int(time.time()),
        storage_node_id=storage_node_id,
        storage_node_address=storage_node_address,
        escrow_amount=escrow_amount,
        verification_period=verification_period,
        chunks_verified=chunks_verified,
        file_id=file_id,
        dam_address=dam_address,
    )
    tx.compute_hash()
    return tx


def make_update_chunk_location_tx(file_id: str, old_node_id: str,
                                  new_node_id: str, migrated_chunks: List[str],
                                  migration_reason: str,
                                  dam_address: str) -> Transaction:
    """
    Create a chunk location update transaction (DAM only).
    
    Args:
        file_id: File ID whose chunks are migrated
        old_node_id: Failed/banned storage node ID
        new_node_id: Replacement storage node ID
        migrated_chunks: List of migrated chunk IDs
        migration_reason: "ban", "failure", or "rebalance"
        dam_address: DAM wallet address
    
    Returns:
        Transaction (unsigned - caller must sign)
    """
    tx = Transaction(
        type="update_chunk_location",
        nonce=int(time.time()),
        file_id=file_id,
        old_node_id=old_node_id,
        new_node_id=new_node_id,
        migrated_chunks=migrated_chunks,
        migration_reason=migration_reason,
        dam_address=dam_address,
    )
    tx.compute_hash()
    return tx
