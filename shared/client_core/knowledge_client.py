"""Client-side knowledge marketplace operations.

Provides functions for:
- Publishing a knowledge listing on a smart node
- Searching the marketplace
- Querying a marketplace listing (cross-wallet RAG)
- Purchasing knowledge ownership
- Building and signing knowledge_publish/query/purchase transactions

Usage:
    from shared.client_core.knowledge_client import KnowledgeMarketplaceClient

    client = KnowledgeMarketplaceClient(smart_node_url="http://smart1:5000")
    listings = client.search_marketplace(query="finance")
    answer = client.query_listing(listing_id, query_text, buyer_address, ...)
"""

import base64
import hashlib
import json
import time
import uuid
import requests
from typing import Dict, List, Optional


class KnowledgeMarketplaceClient:
    """Client for the knowledge marketplace on BeezSmart nodes."""

    def __init__(self, smart_node_url: str, timeout: int = 30):
        """Initialize the marketplace client.

        Args:
            smart_node_url: Base URL of the smart node.
            timeout: Request timeout in seconds.
        """
        self.smart_node_url = smart_node_url.rstrip("/")
        self.timeout = timeout

    def publish_listing(
        self,
        seller_address: str,
        title: str,
        description: str,
        tags: List[str],
        price_per_query: float,
        purchase_price: float,
        file_ids: List[str],
        marketplace_key: bytes,
    ) -> Dict:
        """Publish a knowledge listing on the smart node.

        Args:
            seller_address: Seller wallet address.
            title: Listing title.
            description: Listing description.
            tags: Searchable tags.
            price_per_query: BZT per marketplace query.
            purchase_price: BZT for full ownership (0 = not for sale).
            file_ids: UUIDs of indexed files to include.
            marketplace_key: AES key for marketplace decryption (raw bytes).

        Returns:
            Dict with listing_id, total_files, total_chunks, status.
        """
        listing_id = str(uuid.uuid4())
        key_b64 = base64.b64encode(marketplace_key).decode()

        response = requests.post(
            f"{self.smart_node_url}/marketplace/publish",
            json={
                "listing_id": listing_id,
                "seller_address": seller_address,
                "title": title,
                "description": description,
                "tags": tags,
                "price_per_query": price_per_query,
                "purchase_price": purchase_price,
                "file_ids": file_ids,
                "marketplace_key": key_b64,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def search_marketplace(
        self,
        query: str = "",
        tags: Optional[List[str]] = None,
        min_price: float = 0,
        max_price: float = 0,
        limit: int = 20,
        offset: int = 0,
    ) -> List[Dict]:
        """Search the knowledge marketplace.

        Args:
            query: Text search term.
            tags: Filter by tags.
            min_price: Min price per query.
            max_price: Max price per query (0 = no limit).
            limit: Max results.
            offset: Pagination offset.

        Returns:
            List of listing dicts.
        """
        params = {"q": query, "limit": limit, "offset": offset}
        if tags:
            params["tags"] = ",".join(tags)
        if min_price > 0:
            params["min_price"] = min_price
        if max_price > 0:
            params["max_price"] = max_price

        response = requests.get(
            f"{self.smart_node_url}/marketplace/search",
            params=params,
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        return data.get("listings", [])

    def get_listing(self, listing_id: str) -> Optional[Dict]:
        """Get details for a specific listing.

        Args:
            listing_id: UUID of the listing.

        Returns:
            Listing dict or None.
        """
        response = requests.get(
            f"{self.smart_node_url}/marketplace/listing/{listing_id}",
            timeout=self.timeout,
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()

    def get_my_listings(self, seller_address: str) -> List[Dict]:
        """Get all listings by the seller.

        Args:
            seller_address: Seller wallet address.

        Returns:
            List of listing dicts.
        """
        response = requests.get(
            f"{self.smart_node_url}/marketplace/my",
            params={"seller_address": seller_address},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json().get("listings", [])

    def query_listing(
        self,
        listing_id: str,
        query_text: str,
        query_vector: List[float],
        buyer_address: str,
        top_k: int = 5,
    ) -> Dict:
        """Query a marketplace listing (cross-wallet RAG, answers only).

        Args:
            listing_id: UUID of the listing to query.
            query_text: The question to ask.
            query_vector: 384-dim embedding of the query.
            buyer_address: Buyer wallet address.
            top_k: Number of chunks to retrieve.

        Returns:
            Dict with answer, cost, query_hash, answer_hash, etc.
        """
        response = requests.post(
            f"{self.smart_node_url}/marketplace/query",
            json={
                "listing_id": listing_id,
                "query_text": query_text,
                "query_vector": query_vector,
                "buyer_address": buyer_address,
                "top_k": top_k,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def update_listing(
        self,
        listing_id: str,
        seller_address: str,
        **kwargs,
    ) -> bool:
        """Update a listing (seller only).

        Args:
            listing_id: UUID of the listing.
            seller_address: Seller wallet.
            **kwargs: Fields to update.

        Returns:
            True if updated.
        """
        body = {"seller_address": seller_address, **kwargs}
        response = requests.put(
            f"{self.smart_node_url}/marketplace/listing/{listing_id}",
            json=body,
            timeout=self.timeout,
        )
        return response.status_code == 200

    def delete_listing(self, listing_id: str, seller_address: str) -> bool:
        """Delete/unpublish a listing.

        Args:
            listing_id: UUID of the listing.
            seller_address: Seller wallet.

        Returns:
            True if deleted.
        """
        response = requests.delete(
            f"{self.smart_node_url}/marketplace/listing/{listing_id}",
            params={"seller_address": seller_address},
            timeout=self.timeout,
        )
        return response.status_code == 200

    def purchase_listing(self, listing_id: str, buyer_address: str) -> Dict:
        """Initiate purchase of a listing on the smart node.

        Args:
            listing_id: UUID of the listing.
            buyer_address: Buyer wallet.

        Returns:
            Dict with success, purchase_price, seller_address.
        """
        response = requests.post(
            f"{self.smart_node_url}/marketplace/purchase",
            json={
                "listing_id": listing_id,
                "buyer_address": buyer_address,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()


# ============================================================================
# Transaction builders (signed, ready for broadcast)
# ============================================================================

def _canonicalize_and_sign(tx: Dict, private_key_hex: str, public_key_hex: str, canon_keys: List[str]) -> Dict:
    """Canonicalize a transaction and sign it (DER-encoded, matching chain verification).

    Args:
        tx: Transaction dict (must already contain tx_hash).
        private_key_hex: Hex-encoded private key.
        public_key_hex: Hex-encoded public key.
        canon_keys: Ordered list of keys for canonicalization.

    Returns:
        The tx dict with sig and pub fields added.
    """
    from ecdsa import SigningKey, SECP256k1
    from ecdsa.util import sigencode_der

    canonical = {}
    for k in canon_keys:
        if k in tx and tx[k] not in (None, "", []):
            canonical[k] = tx[k]

    message = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()

    sk = SigningKey.from_string(bytes.fromhex(private_key_hex), curve=SECP256k1)
    sig_bytes = sk.sign(message, sigencode=sigencode_der)

    tx["sig"] = sig_bytes.hex()
    tx["pub"] = public_key_hex
    return tx


def build_knowledge_publish_tx(
    seller_address: str,
    listing_id: str,
    smart_node_id: str,
    title: str,
    file_count: int,
    chunk_count: int,
    price_per_query: float,
    purchase_price: float,
    private_key_hex: str,
    public_key_hex: str,
) -> Dict:
    """Build and sign a knowledge_publish transaction.

    Args:
        seller_address: Seller wallet address.
        listing_id: UUID of the listing.
        smart_node_id: ID of the smart node hosting the listing.
        title: Listing title (hashed for on-chain storage).
        file_count: Number of files in the listing.
        chunk_count: Total embedding chunks.
        price_per_query: BZT per query.
        purchase_price: BZT for full purchase (0 = not for sale).
        private_key_hex: Seller's private key.
        public_key_hex: Seller's public key.

    Returns:
        Signed transaction dict.
    """
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    nonce = str(uuid.uuid4())
    title_hash = hashlib.sha256(title.encode()).hexdigest()

    payload = (f"{seller_address}|{listing_id}|{smart_node_id}|"
               f"{title_hash}|{file_count}|{chunk_count}|"
               f"{price_per_query}|{purchase_price}|{timestamp}")
    tx_hash = hashlib.sha256(payload.encode()).hexdigest()

    tx = {
        "type": "knowledge_publish",
        "nonce": nonce,
        "seller_address": seller_address,
        "listing_id": listing_id,
        "smart_node_id": smart_node_id,
        "title_hash": title_hash,
        "file_count": file_count,
        "chunk_count": chunk_count,
        "price_per_query": price_per_query,
        "purchase_price": purchase_price,
        "timestamp": timestamp,
        "tx_hash": tx_hash,
    }

    canon_keys = [
        "type", "nonce", "seller_address", "listing_id", "smart_node_id",
        "title_hash", "file_count", "chunk_count", "price_per_query",
        "purchase_price", "timestamp", "tx_hash",
    ]
    return _canonicalize_and_sign(tx, private_key_hex, public_key_hex, canon_keys)


def build_knowledge_query_tx(
    buyer_address: str,
    seller_address: str,
    listing_id: str,
    query_hash: str,
    answer_hash: str,
    cost: float,
    smart_node_id: str,
    smart_node_wallet: str,
    private_key_hex: str,
    public_key_hex: str,
) -> Dict:
    """Build and sign a knowledge_query transaction.

    Args:
        buyer_address: Buyer wallet address (payer).
        seller_address: Seller wallet address (receives revenue).
        listing_id: UUID of the listing queried.
        query_hash: SHA256 of the query text.
        answer_hash: SHA256 of the answer.
        cost: Total cost in BZT (price_per_query).
        smart_node_id: ID of the smart node.
        smart_node_wallet: Smart node wallet (receives fee).
        private_key_hex: Buyer's private key.
        public_key_hex: Buyer's public key.

    Returns:
        Signed transaction dict.
    """
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    nonce = str(uuid.uuid4())

    payload = (f"{buyer_address}|{seller_address}|{listing_id}|"
               f"{query_hash}|{answer_hash}|{cost}|"
               f"{smart_node_id}|{smart_node_wallet}|{timestamp}")
    tx_hash = hashlib.sha256(payload.encode()).hexdigest()

    tx = {
        "type": "knowledge_query",
        "nonce": nonce,
        "buyer_address": buyer_address,
        "seller_address": seller_address,
        "listing_id": listing_id,
        "query_hash": query_hash,
        "answer_hash": answer_hash,
        "cost": cost,
        "smart_node_id": smart_node_id,
        "smart_node_wallet": smart_node_wallet,
        "timestamp": timestamp,
        "tx_hash": tx_hash,
    }

    canon_keys = [
        "type", "nonce", "buyer_address", "seller_address", "listing_id",
        "query_hash", "answer_hash", "cost", "smart_node_id", "smart_node_wallet",
        "timestamp", "tx_hash",
    ]
    return _canonicalize_and_sign(tx, private_key_hex, public_key_hex, canon_keys)


def build_knowledge_purchase_tx(
    buyer_address: str,
    seller_address: str,
    listing_id: str,
    purchase_price: float,
    file_ids: List[str],
    private_key_hex: str,
    public_key_hex: str,
) -> Dict:
    """Build and sign a knowledge_purchase transaction.

    Args:
        buyer_address: Buyer wallet address (payer).
        seller_address: Seller wallet address (receives payment).
        listing_id: UUID of the listing being purchased.
        purchase_price: Full purchase price in BZT.
        file_ids: List of file IDs in the listing.
        private_key_hex: Buyer's private key.
        public_key_hex: Buyer's public key.

    Returns:
        Signed transaction dict.
    """
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    nonce = str(uuid.uuid4())

    file_ids_str = ",".join(sorted(file_ids))
    payload = (f"{buyer_address}|{seller_address}|{listing_id}|"
               f"{purchase_price}|{file_ids_str}|{timestamp}")
    tx_hash = hashlib.sha256(payload.encode()).hexdigest()

    tx = {
        "type": "knowledge_purchase",
        "nonce": nonce,
        "buyer_address": buyer_address,
        "seller_address": seller_address,
        "listing_id": listing_id,
        "purchase_price": purchase_price,
        "file_ids": file_ids,
        "timestamp": timestamp,
        "tx_hash": tx_hash,
    }

    canon_keys = [
        "type", "nonce", "buyer_address", "seller_address", "listing_id",
        "purchase_price", "file_ids", "timestamp", "tx_hash",
    ]
    return _canonicalize_and_sign(tx, private_key_hex, public_key_hex, canon_keys)
