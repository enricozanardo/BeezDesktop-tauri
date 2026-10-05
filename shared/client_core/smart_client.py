"""Client-side smart node communication for RAG indexing and querying.

Provides functions for:
- Indexing a file on a smart node (embeddings + encrypted text)
- Querying a smart node (RAG with ephemeral decryption key)
- Getting workspace statistics
- Building and signing smart_index / smart_query transactions

Usage:
    from shared.client_core.smart_client import SmartNodeClient

    client = SmartNodeClient(smart_node_url="http://smart1:5000")
    result = client.index_file(file_id, plaintext, encryption_key, wallet)
    answer = client.query(query_text, decryption_key, wallet)
"""

import base64
import hashlib
import json
import time
import uuid
import requests
from typing import Dict, List, Optional, Tuple

from shared.client_core.embedding import generate_embeddings, embed_query
from shared.client_core.rag_chunking import split_into_rag_chunks


class SmartNodeClient:
    """Client for communicating with BeezSmart nodes."""

    def __init__(self, smart_node_url: str, timeout: int = 120):
        """Initialize the smart node client.

        Args:
            smart_node_url: Base URL of the smart node (e.g., "http://smart1:5000").
            timeout: Request timeout in seconds.
        """
        self.smart_node_url = smart_node_url.rstrip("/")
        self.timeout = timeout

    def get_info(self) -> Dict:
        """Get smart node information and pricing.

        Returns:
            Dict with node_id, pricing, model info.
        """
        response = requests.get(
            f"{self.smart_node_url}/info",
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def index_file(
        self,
        file_id: str,
        file_name: str,
        plaintext_content: str,
        encryption_key: bytes,
        wallet_address: str,
        chunk_size: int = 800,
        chunk_overlap: int = 100,
    ) -> Dict:
        """Index a file for RAG on the smart node.

        Splits the plaintext into RAG chunks, generates embeddings locally,
        encrypts the text chunks, and sends everything to the smart node.

        Args:
            file_id: UUID of the file.
            file_name: Original filename.
            plaintext_content: Decrypted file content as text.
            encryption_key: AES-256 key (32 bytes) for encrypting text chunks.
            wallet_address: Owner wallet address.
            chunk_size: RAG chunk size in characters.
            chunk_overlap: Overlap between chunks.

        Returns:
            Dict with: success, chunks_indexed, total_cost, smart_node_id
        """
        # 1. Split into RAG chunks
        rag_chunks = split_into_rag_chunks(
            plaintext_content,
            chunk_size=chunk_size,
            overlap=chunk_overlap,
        )

        if not rag_chunks:
            return {"success": False, "error": "No text content to index"}

        print(f"[SMART CLIENT] Split into {len(rag_chunks)} RAG chunks", flush=True)

        # 2. Generate embeddings locally
        embeddings = generate_embeddings(rag_chunks)
        print(f"[SMART CLIENT] Generated {len(embeddings)} embeddings", flush=True)

        # 3. Encrypt text chunks
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        import os as _os

        aesgcm = AESGCM(encryption_key)
        encrypted_chunks = []

        for i, (chunk_text, embedding) in enumerate(zip(rag_chunks, embeddings)):
            nonce = _os.urandom(12)
            plaintext_bytes = chunk_text.encode("utf-8")
            ciphertext = aesgcm.encrypt(nonce, plaintext_bytes, None)
            # Prepend nonce to ciphertext
            encrypted_data = nonce + ciphertext
            text_hash = hashlib.sha256(plaintext_bytes).hexdigest()

            encrypted_chunks.append({
                "chunk_index": i,
                "embedding": embedding,
                "encrypted_text": base64.b64encode(encrypted_data).decode("ascii"),
                "text_hash": text_hash,
            })

        # 4. Send to smart node
        payload = {
            "file_id": file_id,
            "file_name": file_name,
            "wallet_address": wallet_address,
            "chunks": encrypted_chunks,
        }

        response = requests.post(
            f"{self.smart_node_url}/index",
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        result = response.json()

        print(f"[SMART CLIENT] Indexed {result.get('chunks_indexed', 0)} chunks, "
              f"cost={result.get('total_cost', 0)} BZT", flush=True)

        return result

    def query(
        self,
        query_text: str,
        decryption_key: bytes,
        wallet_address: str,
        file_ids: Optional[List[str]] = None,
        top_k: int = 5,
    ) -> Dict:
        """Execute a RAG query against the smart node.

        Generates query embedding locally, sends it along with the ephemeral
        decryption key for the smart node to decrypt relevant context chunks.

        Args:
            query_text: The question to ask.
            decryption_key: AES-256 key (32 bytes) for decrypting text chunks.
            wallet_address: Owner wallet address.
            file_ids: Optional list of file IDs to restrict search.
            top_k: Number of most relevant chunks to retrieve.

        Returns:
            Dict with: answer, sources, query_hash, answer_hash, no_relevant_data, cost
        """
        # 1. Generate query embedding locally
        query_vector = embed_query(query_text)

        # 2. Send query to smart node
        payload = {
            "query_text": query_text,
            "query_vector": query_vector,
            "wallet_address": wallet_address,
            "decryption_key": base64.b64encode(decryption_key).decode("ascii"),
            "top_k": top_k,
        }
        if file_ids:
            payload["file_ids"] = file_ids

        response = requests.post(
            f"{self.smart_node_url}/query",
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        result = response.json()

        print(f"[SMART CLIENT] Query result: {len(result.get('sources', []))} sources, "
              f"no_data={result.get('no_relevant_data', False)}", flush=True)

        return result

    def chat(
        self,
        messages: List[Dict],
        decryption_key: bytes,
        wallet_address: str,
        file_ids: Optional[List[str]] = None,
        top_k: int = 5,
        thread_id: Optional[str] = None,
    ) -> Dict:
        """Multi-turn RAG chat. Embeds the latest user message locally.

        Args:
            messages: Turns with role/content. Last user content is retrieved.
            decryption_key: AES-256 key for chunk decrypt.
            wallet_address: Owner wallet.
            file_ids: Optional file filter.
            top_k: Retrieval depth.
            thread_id: Optional existing thread.

        Returns:
            Dict with answer, sources, hashes, cost, thread_id, optional verification.
        """
        user_turns = [m.get("content", "") for m in messages if m.get("role") == "user"]
        if not user_turns:
            return {"success": False, "error": "No user message"}
        query_vector = embed_query(user_turns[-1])
        payload = {
            "messages": messages,
            "query_vector": query_vector,
            "wallet_address": wallet_address,
            "decryption_key": base64.b64encode(decryption_key).decode("ascii"),
            "top_k": top_k,
        }
        if file_ids:
            payload["file_ids"] = file_ids
        if thread_id:
            payload["thread_id"] = thread_id
        response = requests.post(
            f"{self.smart_node_url}/chat",
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def get_workspace_stats(self, wallet_address: str) -> Dict:
        """Get workspace statistics from the smart node.

        Args:
            wallet_address: Owner wallet address.

        Returns:
            Dict with workspace statistics.
        """
        response = requests.get(
            f"{self.smart_node_url}/workspace/stats",
            params={"wallet_address": wallet_address},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return response.json()

    def delete_file(self, file_id: str, wallet_address: str) -> bool:
        """Remove an indexed file from the workspace.

        Args:
            file_id: File to remove.
            wallet_address: Owner wallet address.

        Returns:
            True if successfully removed.
        """
        response = requests.delete(
            f"{self.smart_node_url}/workspace/{file_id}",
            params={"wallet_address": wallet_address},
            timeout=self.timeout,
        )
        return response.status_code == 200


def _canonicalize_and_sign(tx: Dict, private_key_hex: str, public_key_hex: str, canon_keys: List[str]) -> Dict:
    """Canonicalize a transaction and sign it (DER-encoded, matching chain verification).

    The chain verifies signatures by:
    1. Extracting canonical keys from the TX dict
    2. Serializing with json.dumps(canonical, sort_keys=True, separators=(',', ':'))
    3. Verifying the DER-encoded ECDSA signature over those bytes

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

    # Build canonical dict (same logic as chain's canonicalize_for_signature)
    canonical = {}
    for k in canon_keys:
        if k in tx and tx[k] not in (None, "", []):
            canonical[k] = tx[k]

    # Serialize deterministically (must match chain's serialize_tx)
    message = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()

    # Sign with DER encoding (must match chain's verify_ecdsa_signature)
    sk = SigningKey.from_string(bytes.fromhex(private_key_hex), curve=SECP256k1)
    sig_bytes = sk.sign(message, sigencode=sigencode_der)

    tx["sig"] = sig_bytes.hex()
    tx["pub"] = public_key_hex
    return tx


def build_smart_index_tx(
    wallet_address: str,
    file_id: str,
    smart_node_id: str,
    smart_node_wallet: str,
    num_chunks_indexed: int,
    total_cost: float,
    private_key_hex: str,
    public_key_hex: str,
) -> Dict:
    """Build and sign a smart_index transaction.

    Args:
        wallet_address: Payer wallet address.
        file_id: UUID of the indexed file.
        smart_node_id: ID of the smart node used.
        smart_node_wallet: Wallet address of the smart node (receives the fee).
        num_chunks_indexed: Number of RAG chunks indexed.
        total_cost: Total cost in BZT.
        private_key_hex: Hex-encoded private key for signing.
        public_key_hex: Hex-encoded public key.

    Returns:
        Signed transaction dict ready for broadcasting.
    """
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    nonce = str(uuid.uuid4())

    # Calculate TX hash (must match chain's calculate_tx_hash)
    payload_str = f"{wallet_address}|{file_id}|{smart_node_id}|{smart_node_wallet}|{num_chunks_indexed}|{total_cost}|{timestamp}"
    tx_hash = hashlib.sha256(payload_str.encode()).hexdigest()

    tx = {
        "type": "smart_index",
        "nonce": nonce,
        "file_id": file_id,
        "smart_node_id": smart_node_id,
        "smart_node_wallet": smart_node_wallet,
        "num_chunks_indexed": num_chunks_indexed,
        "total_cost": total_cost,
        "wallet_address": wallet_address,
        "timestamp": timestamp,
        "tx_hash": tx_hash,
    }

    # Canonical keys must match chain's canonicalize_for_signature for smart_index
    canon_keys = [
        "type", "nonce", "file_id", "smart_node_id", "smart_node_wallet",
        "num_chunks_indexed", "total_cost", "wallet_address", "timestamp", "tx_hash",
    ]
    return _canonicalize_and_sign(tx, private_key_hex, public_key_hex, canon_keys)


def build_smart_query_tx(
    wallet_address: str,
    query_hash: str,
    answer_hash: str,
    smart_node_id: str,
    smart_node_wallet: str,
    cost: float,
    file_ids: List[str],
    private_key_hex: str,
    public_key_hex: str,
) -> Dict:
    """Build and sign a smart_query transaction.

    Args:
        wallet_address: Payer wallet address.
        query_hash: SHA256 of the query text.
        answer_hash: SHA256 of the answer text.
        smart_node_id: ID of the smart node used.
        smart_node_wallet: Wallet address of the smart node (receives the fee).
        cost: Query cost in BZT.
        file_ids: List of file IDs that contributed to the answer.
        private_key_hex: Hex-encoded private key for signing.
        public_key_hex: Hex-encoded public key.

    Returns:
        Signed transaction dict ready for broadcasting.
    """
    timestamp = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    nonce = str(uuid.uuid4())

    # Calculate TX hash (must match chain's calculate_tx_hash)
    file_ids_str = ",".join(sorted(file_ids))
    payload_str = f"{wallet_address}|{query_hash}|{answer_hash}|{smart_node_id}|{smart_node_wallet}|{cost}|{file_ids_str}|{timestamp}"
    tx_hash = hashlib.sha256(payload_str.encode()).hexdigest()

    tx = {
        "type": "smart_query",
        "nonce": nonce,
        "query_hash": query_hash,
        "answer_hash": answer_hash,
        "smart_node_id": smart_node_id,
        "smart_node_wallet": smart_node_wallet,
        "cost": cost,
        "wallet_address": wallet_address,
        "file_ids": file_ids,
        "timestamp": timestamp,
        "tx_hash": tx_hash,
    }

    # Canonical keys must match chain's canonicalize_for_signature for smart_query
    canon_keys = [
        "type", "nonce", "query_hash", "answer_hash", "smart_node_id", "smart_node_wallet",
        "cost", "wallet_address", "file_ids", "timestamp", "tx_hash",
    ]
    return _canonicalize_and_sign(tx, private_key_hex, public_key_hex, canon_keys)
