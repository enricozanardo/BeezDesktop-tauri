"""
BeezClientCore - Core Client Logic (Standalone)

This is the main client class that provides all core functionality
WITHOUT depending on BeezClient. It communicates directly with
chain/storage nodes via HTTP.

Used by:
- BeezDesktop (Toga desktop app)
- CLI applications
"""

import os
import hashlib
import requests
import random
from typing import Optional, Dict, List, Tuple, Any

from shared.client_core.state import ClientState, get_global_state
from shared.client_core.wallet import Wallet
from shared.client_core.timestamp import get_rome_unix_timestamp
from shared.client_core.docker_mapping import resolve_node_address, get_chain_node_http_url


class BeezClientCore:
    """
    Core client logic - standalone, no BeezClient dependency.
    
    Communicates directly with chain nodes via HTTP API.
    Handles Docker container name -> host port mapping automatically.
    """
    
    def __init__(
        self,
        state: Optional[ClientState] = None,
        request_timeout: int = 10
    ):
        """
        Initialize the client core.
        
        Args:
            state: ClientState instance (uses global if None)
            request_timeout: HTTP request timeout in seconds
        """
        self.state = state or get_global_state()
        self.request_timeout = request_timeout
        self.session = requests.Session()
    
    def _get_random_chain_node(self) -> Optional[Dict]:
        """Get a random chain node from state."""
        if not self.state.chain_nodes:
            return None
        return random.choice(self.state.chain_nodes)
    
    def _chain_request(self, endpoint: str, method: str = "GET", 
                       data: Dict = None, params: Dict = None) -> Tuple[Dict, int]:
        """
        Make HTTP request to a chain node.
        
        Args:
            endpoint: API endpoint (e.g., "/api/blockchain/info")
            method: HTTP method
            data: POST data
            params: Query parameters
            
        Returns:
            Tuple of (response_dict, status_code)
        """
        node = self._get_random_chain_node()
        if not node:
            print("[CLIENT] _chain_request: No chain nodes available", flush=True)
            return {"error": "No chain nodes available"}, 503
        
        base_url = get_chain_node_http_url(node)
        url = f"{base_url}{endpoint}"
        
        print(f"[CLIENT] _chain_request: {method} {url}", flush=True)
        
        try:
            m = method.upper()
            if m == "GET":
                response = self.session.get(url, params=params, timeout=self.request_timeout)
            elif m == "PUT":
                response = self.session.put(url, json=data, timeout=self.request_timeout)
            elif m == "DELETE":
                response = self.session.delete(url, timeout=self.request_timeout)
            else:
                response = self.session.post(url, json=data, timeout=self.request_timeout)
            
            print(f"[CLIENT] _chain_request: Response status {response.status_code}", flush=True)
            
            # Handle empty responses (e.g., 201 Created, 204 No Content)
            if response.status_code in (200, 201, 202, 204) and not response.text.strip():
                return {"status": "ok"}, response.status_code
            
            try:
                return response.json(), response.status_code
            except ValueError:
                # Response is not JSON
                print(f"[CLIENT] _chain_request: Non-JSON response: {response.text[:100]}", flush=True)
                return {"message": response.text[:200] if response.text else "ok"}, response.status_code
                
        except requests.exceptions.ConnectionError as e:
            print(f"[CLIENT] _chain_request: Connection error: {e}", flush=True)
            return {"error": f"Cannot connect to chain node at {base_url}"}, 503
        except requests.exceptions.Timeout:
            print(f"[CLIENT] _chain_request: Timeout", flush=True)
            return {"error": "Request timeout"}, 504
        except Exception as e:
            print(f"[CLIENT] _chain_request: Error: {e}", flush=True)
            return {"error": str(e)}, 500
    
    # === Wallet Management (Local) ===
    
    def connect_wallet(self, mnemonic: str) -> Dict:
        """Connect a wallet using mnemonic phrase."""
        wallet = Wallet(mnemonic)
        self.state.set_wallet(wallet)
        print(f"[CLIENT] Wallet connected: {wallet.address}", flush=True)
        return {"address": wallet.address}
    
    def create_wallet(self) -> Dict:
        """Create a new wallet with random mnemonic."""
        wallet = Wallet()
        self.state.set_wallet(wallet)
        print(f"[CLIENT] New wallet created: {wallet.address}", flush=True)
        return {
            "address": wallet.address,
            "mnemonic": wallet.mnemonic
        }
    
    def disconnect_wallet(self) -> None:
        """Disconnect the current wallet."""
        self.state.clear_wallet()
        print("[CLIENT] Wallet disconnected", flush=True)
    
    def get_current_wallet(self) -> Optional[Wallet]:
        """Get the currently connected wallet."""
        return self.state.CURRENT_WALLET
    
    def is_wallet_connected(self) -> bool:
        """Check if a wallet is connected."""
        return self.state.CURRENT_WALLET is not None
    
    # === Balance Queries (Direct to Chain Node) ===
    
    def get_wallet_balance(self, address: Optional[str] = None) -> Tuple[Dict, int]:
        """
        Get wallet balance from blockchain.
        
        Args:
            address: Wallet address (uses current wallet if None)
            
        Returns:
            Tuple of ({"balance": float}, status_code)
        """
        if address is None:
            if not self.state.CURRENT_WALLET:
                return {"error": "No wallet loaded"}, 400
            address = self.state.CURRENT_WALLET.address
        
        # Chain node uses /wallet/balance (no /api prefix)
        result, status = self._chain_request(
            "/wallet/balance",
            params={"address": address}
        )
        
        if status == 200:
            balance = result.get("balance", 0)
            # Parse if string like "100 BZT"
            if isinstance(balance, str):
                try:
                    balance = float(balance.replace("BZT", "").strip())
                except:
                    balance = 0
            return {"balance": balance}, 200
        
        return result, status
    
    # === Transaction Operations ===
    
    def create_and_send_transaction(self, amount: float, recipient: str) -> Tuple[Dict, int]:
        """
        Create and send a token transfer transaction.
        
        Args:
            amount: Amount in BZT
            recipient: Recipient address
            
        Returns:
            Tuple of (response, status_code)
        """
        if not self.state.CURRENT_WALLET:
            return {"error": "No wallet loaded"}, 400
        
        # Create transaction
        try:
            from shared.transaction import Transaction
        except ImportError:
            return {"error": "Transaction module not available"}, 500
        
        tx_dict = {
            "type": "normal",
            "nonce": get_rome_unix_timestamp(),
            "sender": self.state.CURRENT_WALLET.address,
            "recipient": recipient,
            "amount": f"{amount} BZT",
        }
        tx = Transaction(**tx_dict)
        tx.sign_with_wallet(self.state.CURRENT_WALLET)
        
        print(f"[CLIENT] Transaction created: {tx.tx_hash[:16]}...", flush=True)
        
        # Send to chain node - endpoint is /transactions (no /api prefix)
        result, status = self._chain_request(
            "/transactions",
            method="POST",
            data=tx.to_dict()  # Send tx dict directly, not wrapped
        )
        
        if status == 200:
            return {"tx_hash": tx.tx_hash, "status": "sent"}, 200
        
        return result, status
    
    def send_raw_transaction(self, tx_dict: Dict) -> Tuple[Dict, int]:
        """Send a pre-built, signed transaction to the chain.

        Args:
            tx_dict: Complete transaction dictionary (already signed with tx_hash, sig, pub).

        Returns:
            Tuple of (response, status_code)
        """
        result, status = self._chain_request(
            "/transactions",
            method="POST",
            data=tx_dict,
        )
        if status == 200:
            tx_hash = tx_dict.get("tx_hash", "unknown")
            print(f"[CLIENT] Raw TX sent: {tx_hash[:16]}... type={tx_dict.get('type')}", flush=True)
            return {"tx_hash": tx_hash, "status": "sent"}, 200
        else:
            print(f"[CLIENT] Raw TX failed ({status}): {result}", flush=True)
        return result, status

    def get_transaction_status(self, tx_hash: str) -> Tuple[Dict, int]:
        """Get transaction status."""
        return self._chain_request(f"/api/transaction/{tx_hash}")
    
    # === Blockchain Queries (Direct to Chain Node) ===
    
    def get_blockchain_info(self) -> Tuple[Dict, int]:
        """Get blockchain info (height, mempool, etc)."""
        return self._chain_request("/api/blockchain/info")
    
    def get_blocks(self, limit: int = 10, offset: int = 0) -> Tuple[Dict, int]:
        """Get list of blocks."""
        return self._chain_request(
            "/api/blockchain/blocks",
            params={"limit": limit, "offset": offset}
        )
    
    def get_block_by_height(self, height: int) -> Tuple[Dict, int]:
        """Get block by height."""
        return self._chain_request(f"/api/blockchain/block/{height}")
    
    def get_block_by_hash(self, block_hash: str) -> Tuple[Dict, int]:
        """Get block by hash."""
        return self._chain_request(f"/api/blockchain/block/hash/{block_hash}")
    
    def get_transaction(self, tx_hash: str) -> Tuple[Dict, int]:
        """Get transaction details."""
        return self._chain_request(f"/api/blockchain/transaction/{tx_hash}")
    
    def get_wallet_transactions(
        self, 
        address: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        tx_type: str = "all"
    ) -> Tuple[Dict, int]:
        """Get wallet transaction history."""
        if address is None:
            if not self.state.CURRENT_WALLET:
                return {"error": "No wallet loaded"}, 400
            address = self.state.CURRENT_WALLET.address
        
        return self._chain_request(
            f"/api/blockchain/wallet/{address}/transactions",
            params={"limit": limit, "offset": offset, "type": tx_type}
        )
    
    # === File Operations ===
    
    def get_user_uploads(self, user_address: Optional[str] = None) -> List[Dict]:
        """Get all uploads by a user."""
        if user_address is None:
            if not self.state.CURRENT_WALLET:
                print("[CLIENT] get_user_uploads: No wallet connected", flush=True)
                return []
            user_address = self.state.CURRENT_WALLET.address
        
        print(f"[CLIENT] get_user_uploads: Fetching for {user_address}", flush=True)
        
        result, status = self._chain_request(
            f"/api/blockchain/wallet/{user_address}/uploads"
        )
        
        print(f"[CLIENT] get_user_uploads: status={status}, result keys={list(result.keys()) if isinstance(result, dict) else 'not dict'}", flush=True)
        
        if status == 200:
            uploads = result.get("uploads", [])
            print(f"[CLIENT] get_user_uploads: Found {len(uploads)} uploads", flush=True)
            return uploads
        else:
            print(f"[CLIENT] get_user_uploads: Error - {result}", flush=True)
        return []
    
    def create_upload_transaction(
        self,
        file_path: str,
        file_id: str,
        visibility: str = "public",
        price: float = 0.0,
        duration: int = 5,
        node_selection: str = "reputation",
        user_lat: float = None,
        user_lon: float = None,
        max_distance_km: int = None,
        blur_level: str = "none",
        network_type: str = "default",
        node_count: int = 3,
        tags: List[str] = None,
    ) -> Tuple[Dict, int]:
        """
        Create and register a file upload on the blockchain.

        Encrypts the file, splits it into 100 KB chunks, uploads them in
        parallel to storage nodes, and registers the transaction on-chain.

        Args:
            file_path: Path to file
            file_id: UUID for the file
            visibility: "public" or "private"
            price: Price in BZT (0 for free) - sell price
            duration: Storage duration in years (3-10)
            node_selection: Node selection mode (reputation, proximity, price, random)
            user_lat: User's latitude for proximity filtering
            user_lon: User's longitude for proximity filtering
            max_distance_km: Maximum distance for proximity filtering (km)
            blur_level: Blur level for image previews ("none", "light", "medium", "heavy")
            network_type: Network to store on ("default" or "private_<name>")
            node_count: Number of primary storage nodes to use (1-10)

        Returns:
            Tuple of (response, status_code)
        """
        import os
        import hashlib
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        if not self.state.CURRENT_WALLET:
            return {"error": "No wallet loaded"}, 400
        
        if not os.path.exists(file_path):
            return {"error": "File not found"}, 400
        
        # Get file info
        file_name = os.path.basename(file_path)
        file_size = os.path.getsize(file_path)

        max_file_size = 500 * 1024 * 1024  # 500 MB
        if file_size > max_file_size:
            return {"error": f"File too large ({file_size / (1024*1024):.1f} MB). Maximum allowed: {max_file_size // (1024*1024)} MB"}, 400
        
        # Calculate file hash for query_hash
        with open(file_path, 'rb') as f:
            file_hash = hashlib.sha256(f.read()).hexdigest()
        
        chunk_size = 1024 * 1024  # 1MB – aligned with BeezClient / pricing_config
        num_chunks = (file_size + chunk_size - 1) // chunk_size
        
        # Create upload transaction
        try:
            from shared.transaction import Transaction
        except ImportError:
            return {"error": "Transaction module not available"}, 500
        
        # Select storage nodes based on selection mode + network_type filter
        storage_nodes = self._select_storage_nodes(
            node_selection=node_selection,
            user_lat=user_lat,
            user_lon=user_lon,
            max_distance_km=max_distance_km,
            count=max(1, min(node_count, 10)),
            network_type=network_type,
        )
        
        if not storage_nodes:
            return {"error": f"No storage nodes available for network '{network_type}'"}, 400
        
        # Read file content
        with open(file_path, 'rb') as f:
            file_content = f.read()
        
        # Encrypt file content before chunking (as per initial_doc.txt spec)
        encryption_nonce = None
        try:
            from shared.client_core.encryption import encrypt_file_content, encode_nonce_b64
            encrypted_content, nonce_bytes = encrypt_file_content(file_content, self.state.CURRENT_WALLET)
            encryption_nonce = encode_nonce_b64(nonce_bytes)
            print(f"[CLIENT] File encrypted: {len(file_content)} → {len(encrypted_content)} bytes", flush=True)
            file_content = encrypted_content
            file_size_encrypted = len(file_content)
            num_chunks = (file_size_encrypted + chunk_size - 1) // chunk_size
            print(f"[CLIENT] Encrypted chunks: {num_chunks}", flush=True)
        except Exception as e:
            print(f"[CLIENT] WARNING: Encryption failed, uploading unencrypted: {e}", flush=True)
        
        print(f"[CLIENT] Uploading {num_chunks} chunks in parallel to {len(storage_nodes)} nodes...", flush=True)
        
        # Prepare chunk tasks: list of (chunk_index, chunk_key, chunk_data, primary_node)
        chunk_tasks = []
        for i in range(num_chunks):
            chunk_key = f"{file_id}_chunk_{i}"
            start = i * chunk_size
            end = min(start + chunk_size, len(file_content))
            chunk_data = file_content[start:end]
            primary_node_idx = i % len(storage_nodes)
            chunk_tasks.append((i, chunk_key, chunk_data, primary_node_idx))
        
        # Upload chunks in parallel using ThreadPoolExecutor
        chunk_locations = {}
        backup_chunk_locations = {}
        failed_chunks = []
        
        # Build a list of all selected node IDs for backup hints
        all_selected_nids = [n.get("node_id") for n in storage_nodes]

        def _upload_single_chunk(task):
            """Upload a single chunk with fallback. Returns (chunk_key, primary_node_id, backup_nodes) or raises."""
            idx, chunk_key, chunk_data, primary_idx = task
            chunk_id = str(idx)
            primary_node = storage_nodes[primary_idx]
            # Suggest the other selected nodes as preferred backups
            preferred = [nid for nid in all_selected_nids if nid != primary_node.get("node_id")]
            
            success, backup_nodes = self._upload_chunk_to_storage(
                primary_node, file_id, chunk_id, chunk_data,
                preferred_backups=preferred,
            )
            
            if not success and len(storage_nodes) > 1:
                for j in range(len(storage_nodes)):
                    if j == primary_idx:
                        continue
                    fallback_node = storage_nodes[j]
                    preferred_fb = [nid for nid in all_selected_nids if nid != fallback_node.get("node_id")]
                    success, backup_nodes = self._upload_chunk_to_storage(
                        fallback_node, file_id, chunk_id, chunk_data,
                        preferred_backups=preferred_fb,
                    )
                    if success:
                        primary_node = fallback_node
                        break
            
            if success:
                return (chunk_key, primary_node.get("node_id", "unknown"), backup_nodes)
            else:
                raise RuntimeError(f"Chunk {idx} upload failed on all nodes")
        
        max_workers = min(len(chunk_tasks), len(storage_nodes) * 2, 8)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_map = {executor.submit(_upload_single_chunk, t): t for t in chunk_tasks}
            for future in as_completed(future_map):
                task = future_map[future]
                idx = task[0]
                chunk_key = task[1]
                try:
                    ck, primary_nid, backup_nids = future.result()
                    chunk_locations[ck] = [primary_nid]
                    if backup_nids:
                        backup_chunk_locations[ck] = backup_nids
                    else:
                        other_nids = [n.get("node_id") for n in storage_nodes if n.get("node_id") != primary_nid]
                        if other_nids:
                            backup_chunk_locations[ck] = other_nids[:2]
                    print(f"[CLIENT] Chunk {idx+1}/{num_chunks} uploaded OK", flush=True)
                except Exception as e:
                    print(f"[CLIENT] ERROR: Chunk {idx+1}/{num_chunks} failed: {e}", flush=True)
                    failed_chunks.append(idx)
        
        if failed_chunks:
            return {
                "error": f"Failed to upload chunks: {failed_chunks}",
                "failed_chunks": failed_chunks
            }, 500
        
        # Calculate storage cost based on actual per-node prices
        node_chunk_count: dict = {}
        for chunk_key, node_ids in chunk_locations.items():
            for nid in node_ids:
                node_chunk_count[nid] = node_chunk_count.get(nid, 0) + 1
        
        node_price_map = {n.get("node_id"): n.get("price_per_chunk", 1.0) for n in storage_nodes}
        
        storage_cost = 0.0
        for nid, count in node_chunk_count.items():
            node_cost = node_price_map.get(nid, 1.0)
            storage_cost += count * node_cost * duration
        
        print(f"[CLIENT] Storage cost calculated: {storage_cost:.2f} BZT "
              f"({len(node_chunk_count)} nodes, {len(chunk_locations)} chunks, {duration} years)", flush=True)
        
        # Select a guardian DAM from available manager nodes
        guardian_dam_id = None
        if self.state.manager_nodes:
            # Select the DAM with highest score
            sorted_dams = sorted(
                self.state.manager_nodes, 
                key=lambda d: d.get("score", 0), 
                reverse=True
            )
            guardian_dam_id = sorted_dams[0].get("node_id")
            print(f"[CLIENT] Selected guardian DAM: {guardian_dam_id}", flush=True)
        else:
            print("[CLIENT] Warning: No DAM nodes available for guardian assignment", flush=True)
        
        tx_dict = {
            "type": "upload",
            "nonce": get_rome_unix_timestamp(),
            "uploader": self.state.CURRENT_WALLET.address,
            "sender": self.state.CURRENT_WALLET.address,
            "amount": f"{storage_cost:.6f} BZT",
            "file_id": file_id,
            "file_name": file_name,
            "file_size": file_size,
            "num_chunks": num_chunks,
            "chunk_locations": chunk_locations,
            "backup_chunk_locations": backup_chunk_locations,
            "storage_duration": duration,
            "query_hash": file_hash,
            "visibility": visibility,
            "guardian_dam_id": guardian_dam_id,
        }
        
        # Add encryption nonce if file was encrypted
        if encryption_nonce:
            tx_dict["encryption_nonce"] = encryption_nonce
            # Store the original (unencrypted) file extension for download
            ext = os.path.splitext(file_name)[1].lstrip('.')
            if ext:
                tx_dict["extension"] = ext
        
        # Add marketplace price in both field names so the chain can
        # always find it regardless of which key it looks up.
        if price > 0:
            price_str = f"{price:.6f} BZT"
            tx_dict["new_price"] = price_str
            tx_dict["marketplace_price"] = price_str
            print(f"[CLIENT] Marketplace price set: {price_str}", flush=True)
        else:
            print(f"[CLIENT] No marketplace price (price={price})", flush=True)

        if blur_level and blur_level != "none":
            tx_dict["blur"] = blur_level

        if tags:
            tx_dict["tags"] = tags

        # Generate blur preview for previewable files (images, PDFs)
        try:
            from shared.client_core.preview import PreviewGenerator, encode_preview_base64
            ext = os.path.splitext(file_name)[1] if '.' in file_name else ''
            if PreviewGenerator.is_previewable(ext):
                print(f"[CLIENT] Generating blur preview for {file_name}...", flush=True)
                preview_gen = PreviewGenerator(wallet=self.state.CURRENT_WALLET)
                preview_result = preview_gen.generate_preview_from_file(file_path)
                
                if preview_result.success and preview_result.preview_data:
                    preview_b64 = encode_preview_base64(preview_result.preview_data)
                    tx_dict["preview_data"] = preview_b64
                    tx_dict["preview_hash"] = preview_result.preview_hash
                    tx_dict["preview_width"] = preview_result.width
                    tx_dict["preview_height"] = preview_result.height
                    tx_dict["blur"] = blur_level if blur_level and blur_level != "none" else "blur"
                    print(f"[CLIENT] Preview generated: {preview_result.width}x{preview_result.height}, "
                          f"{len(preview_b64)} bytes b64", flush=True)
                else:
                    print(f"[CLIENT] Preview generation failed: {preview_result.error}", flush=True)
        except Exception as e:
            print(f"[CLIENT] Preview generation error (non-fatal): {e}", flush=True)
        
        print(f"[CLIENT] Creating Transaction object...", flush=True)
        try:
            tx = Transaction(**tx_dict)
        except Exception as tx_err:
            print(f"[CLIENT] ERROR creating Transaction: {tx_err}", flush=True)
            import traceback
            traceback.print_exc()
            return {"error": f"Transaction creation failed: {tx_err}"}, 500

        print(f"[CLIENT] Signing transaction...", flush=True)
        try:
            tx.sign_with_wallet(self.state.CURRENT_WALLET)
        except Exception as sign_err:
            print(f"[CLIENT] ERROR signing Transaction: {sign_err}", flush=True)
            import traceback
            traceback.print_exc()
            return {"error": f"Transaction signing failed: {sign_err}"}, 500
        
        print(f"[CLIENT] Upload transaction created: {tx.tx_hash[:16]}...", flush=True)
        print(f"[CLIENT] File: {file_name}, Size: {file_size}, Chunks: {num_chunks}, Cost: {storage_cost:.2f} BZT", flush=True)
        
        # Send to chain node (use longer timeout for large upload TXs with preview data)
        print(f"[CLIENT] Sending upload transaction to chain...", flush=True)
        old_timeout = self.request_timeout
        self.request_timeout = max(30, self.request_timeout)
        try:
            result, status = self._chain_request(
                "/transactions",
                method="POST",
                data=tx.to_dict()
            )
        except Exception as chain_err:
            print(f"[CLIENT] ERROR submitting TX to chain: {chain_err}", flush=True)
            import traceback
            traceback.print_exc()
            return {"error": f"Chain submission failed: {chain_err}"}, 500
        finally:
            self.request_timeout = old_timeout
        
        print(f"[CLIENT] Chain response: status={status}, result={result}", flush=True)
        
        if status in (200, 201):
            print(f"[CLIENT] Upload registered successfully: {file_id}", flush=True)
            return {
                "tx_hash": tx.tx_hash,
                "file_id": file_id,
                "file_name": file_name,
                "storage_cost": storage_cost,
                "status": "registered"
            }, 200
        
        print(f"[CLIENT] Upload failed: {result}", flush=True)
        return result, status
    
    def _select_storage_nodes(
        self, 
        node_selection: str = "reputation",
        user_lat: float = None,
        user_lon: float = None,
        max_distance_km: int = None,
        count: int = 3,
        network_type: str = "default"
    ) -> List[Dict]:
        """
        Select storage nodes based on selection criteria.

        Args:
            node_selection: Selection mode (reputation, proximity, price, random)
            user_lat: User's latitude for proximity filtering
            user_lon: User's longitude for proximity filtering
            max_distance_km: Maximum distance filter (km)
            count: Number of nodes to select (1-10)
            network_type: Network type filter ("default" or "private_<name>")

        Returns:
            List of selected storage node dicts
        """
        nodes = [n for n in self.state.active_nodes if n.get("node_type") == "storage"] if self.state.active_nodes else []
        
        if not nodes:
            return []
        
        # Filter by network type
        # Nodes with network_type "default" are available to everyone.
        # Nodes in a private network are only available when that network is
        # explicitly selected. Nodes without a network_type field are treated
        # as "default".
        if network_type and network_type != "default":
            # Private network: only nodes that declared this network OR "default" nodes (shared infra)
            nodes = [n for n in nodes if n.get("network_type", "default") in (network_type, "default")]
        else:
            # Default network: only nodes in "default" network
            nodes = [n for n in nodes if n.get("network_type", "default") == "default"]
        
        if not nodes:
            return []
        
        # Apply distance filter if specified
        if max_distance_km and user_lat is not None and user_lon is not None:
            try:
                from shared.client_core.geolocation import calculate_distance
                filtered = []
                for node in nodes:
                    node_lat = node.get("lat", 0)
                    node_lon = node.get("lon", 0)
                    dist = calculate_distance(user_lat, user_lon, node_lat, node_lon)
                    if dist <= max_distance_km:
                        node["_distance"] = dist
                        filtered.append(node)
                if filtered:
                    nodes = filtered
            except ImportError:
                pass  # Skip distance filtering if module not available
        
        if node_selection == "reputation":
            # Sort by reputation score (highest first)
            nodes.sort(key=lambda n: n.get("reputation", n.get("score", 0) * 100), reverse=True)
        
        elif node_selection == "price":
            # Sort by price (lowest first)
            nodes.sort(key=lambda n: n.get("price_per_chunk", 1.0))
        
        elif node_selection == "proximity":
            # Sort by distance (closest first)
            if user_lat is not None and user_lon is not None:
                try:
                    from shared.client_core.geolocation import calculate_distance
                    for node in nodes:
                        if "_distance" not in node:
                            node_lat = node.get("lat", 0)
                            node_lon = node.get("lon", 0)
                            node["_distance"] = calculate_distance(user_lat, user_lon, node_lat, node_lon)
                    nodes.sort(key=lambda n: n.get("_distance", 99999))
                except ImportError:
                    pass
        
        elif node_selection == "random":
            import random
            random.shuffle(nodes)
        
        return nodes[:count]
    
    def _upload_chunk_to_storage(
        self,
        storage_node: Dict,
        file_id: str,
        chunk_id: str,
        chunk_data: bytes,
        preferred_backups: List[str] = None,
    ) -> Tuple[bool, List[str]]:
        """
        Upload a chunk to a storage node.

        Args:
            storage_node: Storage node dict with ip/port
            file_id: UUID of the file
            chunk_id: Chunk identifier (just the index, e.g., "0", "1")
            chunk_data: Raw chunk bytes
            preferred_backups: Optional list of preferred backup node IDs

        Returns:
            Tuple of (success, list of backup node IDs)
        """
        try:
            from shared.client_core.docker_mapping import resolve_node_address
            
            # Get node IP - could be Docker container name or direct IP
            node_ip_raw = storage_node.get("ip", "")
            node_id = storage_node.get("node_id", "")
            
            print(f"[CLIENT] Storage node: ip={node_ip_raw}, node_id={node_id}", flush=True)
            
            # Use the ip field from consensus (Docker hostname, e.g. "storage5")
            # which is the actual container name.  Do NOT derive from node_id
            # because node_id contains the storage *tier* (storage_1_xxx) which
            # does not correspond to the container number.
            if node_ip_raw:
                host_ip, http_port = resolve_node_address(node_ip_raw, use_zmq=False)
            elif node_id:
                host_ip, http_port = resolve_node_address(node_id, use_zmq=False)
            else:
                host_ip, http_port = resolve_node_address("localhost", use_zmq=False)
            
            url = f"http://{host_ip}:{http_port}/store_chunk"
            
            # Encode chunk data as latin1 (as expected by storage node)
            payload = {
                "file_id": file_id,
                "chunk_id": chunk_id,
                "chunk_content": chunk_data.decode("latin1"),
                "source": "client",
            }
            if preferred_backups:
                payload["preferred_backups"] = preferred_backups
            
            print(f"[CLIENT] Uploading chunk to {url}", flush=True)
            
            # Use shorter timeout to avoid freezing
            response = self.session.post(url, json=payload, timeout=15)
            
            if response.status_code == 200:
                result = response.json()
                backup_nodes = result.get("backup_locations", [])
                print(f"[CLIENT] Chunk uploaded, backups: {backup_nodes}", flush=True)
                return True, backup_nodes
            else:
                print(f"[CLIENT] Chunk upload failed: {response.status_code} - {response.text}", flush=True)
                return False, []
                
        except Exception as e:
            print(f"[CLIENT] Error uploading chunk: {e}", flush=True)
            import traceback
            traceback.print_exc()
            return False, []
    
    # === Network State ===
    
    def get_active_storage_nodes(self) -> List[Dict]:
        """Get list of active storage nodes."""
        return self.state.active_nodes
    
    def get_chain_nodes(self) -> List[Dict]:
        """Get list of chain nodes."""
        return self.state.chain_nodes
    
    def get_manager_nodes(self) -> List[Dict]:
        """Get list of DAM/manager nodes."""
        return self.state.manager_nodes
    
    # === Public Files / Marketplace ===
    
    def search_public_assets(
        self,
        query: str = "",
        tags: List[str] = None,
        min_price: float = None,
        max_price: float = None,
        limit: int = 50,
        offset: int = 0
    ) -> Tuple[Dict, int]:
        """
        Search for public digital assets in the marketplace.
        
        Args:
            query: Search query (file name)
            tags: Filter by tags
            min_price: Minimum price filter
            max_price: Maximum price filter
            limit: Max results to return
            offset: Pagination offset
            
        Returns:
            Tuple of ({"assets": [...], "total": N}, status_code)
        """
        params = {"limit": limit, "offset": offset}
        if query:
            params["query"] = query
        if tags:
            params["tags"] = ",".join(tags)
        if min_price is not None:
            params["min_price"] = min_price
        if max_price is not None:
            params["max_price"] = max_price
        
        return self._chain_request("/api/marketplace/assets", params=params)

    def get_asset_tags(self, file_id: str) -> Tuple[Dict, int]:
        """Get current tags for a digital asset.

        Args:
            file_id: UUID of the digital asset

        Returns:
            Tuple of ({"tags": [...]}, status_code)
        """
        return self._chain_request(f"/api/assets/{file_id}/tags")

    def update_asset_tags(self, file_id: str, tags: List[str]) -> Tuple[Dict, int]:
        """
        Update tags for a digital asset (owner only).

        Args:
            file_id: UUID of the digital asset
            tags: List of tag strings

        Returns:
            Tuple of (response, status_code)
        """
        if not self.state.CURRENT_WALLET:
            return {"error": "No wallet loaded"}, 400

        return self._chain_request(
            f"/api/assets/{file_id}/tags",
            method="PUT",
            data={
                "tags": tags,
                "owner_address": self.state.CURRENT_WALLET.address,
            }
        )

    def create_ownership_request_from_marketplace(
        self,
        file_id: str,
        message: str = ""
    ) -> Tuple[Dict, int]:
        """
        Buyer-initiated ownership request for a public marketplace asset.

        The buyer creates an ownership_request TX targeting the current owner.
        The owner sees it in their notifications and can accept/reject.

        Args:
            file_id: UUID of the digital asset
            message: Optional message to the owner

        Returns:
            Tuple of (response, status_code)
        """
        if not self.state.CURRENT_WALLET:
            return {"error": "No wallet loaded"}, 400

        # Get asset details to find the owner and price
        asset_result, asset_status = self.get_asset_details(file_id)
        if asset_status != 200:
            return {"error": "Asset not found"}, 404

        asset = asset_result.get("asset", asset_result)
        owner = asset.get("owner") or asset.get("owner_address")
        price = asset.get("marketplace_price", asset.get("price", 0))
        visibility = asset.get("visibility", "private")

        if visibility != "public":
            return {"error": "Asset is not public"}, 400
        if owner == self.state.CURRENT_WALLET.address:
            return {"error": "You already own this asset"}, 400

        price_str = f"{float(price):.6f} BZT" if price else "0 BZT"

        from shared.transaction import Transaction

        # Build ownership_request: the buyer requests ownership from the current owner
        # In buyer-initiated flow, the "current_owner" is the seller, and "new_owner" is the buyer
        req_tx = Transaction.make_ownership_request(
            file_id=file_id,
            current_owner=owner,
            new_owner=self.state.CURRENT_WALLET.address,
            asking_price=price_str,
            wallet=self.state.CURRENT_WALLET,
            message=message,
        )

        print(f"[CLIENT] Marketplace purchase request: {req_tx.tx_hash[:16]}...", flush=True)

        result, status = self._chain_request(
            "/transactions",
            method="POST",
            data=req_tx.to_dict()
        )

        if status in (200, 201):
            return {
                "tx_hash": req_tx.tx_hash,
                "status": "request_sent",
                "file_id": file_id,
                "owner": owner,
                "price": price_str,
            }, 200

        return result, status

    def get_asset_details(self, file_id: str) -> Tuple[Dict, int]:
        """
        Get detailed information about a digital asset.
        
        Args:
            file_id: UUID of the digital asset
            
        Returns:
            Tuple of (asset_dict, status_code)
        """
        return self._chain_request(f"/api/assets/{file_id}")
    
    def get_asset_preview(self, file_id: str) -> Tuple[Dict, int]:
        """
        Get the blurred preview of a digital asset.
        
        First checks the blockchain for stored preview data.
        If none found and the user owns the asset, generates preview on-the-fly
        by downloading the file from storage and applying blur.
        
        Args:
            file_id: UUID of the digital asset
            
        Returns:
            Tuple of ({"preview_data": base64_str, "mime_type": str, "has_preview": bool}, status_code)
        """
        result, status = self._chain_request(f"/api/assets/{file_id}/preview")
        
        # If on-chain preview exists, return it directly
        if status == 200 and result.get("has_preview"):
            return result, status
        
        # No on-chain preview - try to generate locally if we own the asset
        try:
            if not self.state.CURRENT_WALLET:
                return result, status
            
            # Check if we own the asset
            asset_result, asset_status = self.get_asset_details(file_id)
            if asset_status != 200:
                return result, status
            
            asset = asset_result.get("asset", asset_result)
            owner = asset.get("owner") or asset.get("owner_address")
            file_name = asset.get("file_name", "")
            ext = ""
            if "." in file_name:
                ext = "." + file_name.rsplit(".", 1)[-1]
            elif asset.get("extension"):
                ext = asset["extension"] if asset["extension"].startswith(".") else "." + asset["extension"]
            
            if owner != self.state.CURRENT_WALLET.address:
                # Not the owner - can't download to generate preview
                return result, status
            
            from shared.client_core.preview import PreviewGenerator, encode_preview_base64
            
            if not PreviewGenerator.is_previewable(ext):
                return result, status
            
            print(f"[CLIENT] No on-chain preview for {file_name}, generating locally...", flush=True)
            
            # Download the file to a temp directory
            # download_file() expects a directory path and appends the filename
            import tempfile
            import shutil
            tmp_dir = tempfile.mkdtemp(prefix="beez_preview_")
            
            try:
                dl_result, dl_status = self.download_file(file_id, tmp_dir)
                if dl_status != 200:
                    print(f"[CLIENT] Download failed for preview generation: {dl_result}", flush=True)
                    return result, status
                
                # download_file returns the actual saved path
                downloaded_path = dl_result.get("path", "")
                if not downloaded_path or not os.path.exists(downloaded_path):
                    # Fallback: look for any file in the temp dir
                    files_in_dir = os.listdir(tmp_dir)
                    if files_in_dir:
                        downloaded_path = os.path.join(tmp_dir, files_in_dir[0])
                    else:
                        print(f"[CLIENT] No file found in temp dir after download", flush=True)
                        return result, status
                
                print(f"[CLIENT] Downloaded file for preview: {downloaded_path}", flush=True)
                
                # Generate preview from downloaded file
                preview_gen = PreviewGenerator(wallet=self.state.CURRENT_WALLET)
                preview_result = preview_gen.generate_preview_from_file(downloaded_path)
                
                if preview_result.success and preview_result.preview_data:
                    preview_b64 = encode_preview_base64(preview_result.preview_data)
                    print(f"[CLIENT] Local preview generated: {preview_result.width}x{preview_result.height}", flush=True)
                    return {
                        "status": "success",
                        "file_id": file_id,
                        "file_name": file_name,
                        "has_preview": True,
                        "preview_data": preview_b64,
                        "preview_hash": preview_result.preview_hash,
                        "preview_width": preview_result.width,
                        "preview_height": preview_result.height,
                        "mime_type": "image/jpeg",
                        "source": "local"
                    }, 200
                else:
                    print(f"[CLIENT] Preview generation failed: {preview_result.error}", flush=True)
            finally:
                try:
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                except:
                    pass
        except Exception as e:
            print(f"[CLIENT] Error generating local preview: {e}", flush=True)
        
        return result, status
    
    def get_asset_history(self, file_id: str) -> Tuple[Dict, int]:
        """
        Get ownership and change history for an asset.
        
        Args:
            file_id: UUID of the digital asset
            
        Returns:
            Tuple of ({"history": [...]}, status_code)
        """
        return self._chain_request(f"/api/assets/{file_id}/history")
    
    # === Ownership Requests ===
    
    def initiate_ownership_transfer(
        self,
        file_id: str,
        new_owner_address: str,
        asking_price: float,
        message: str = ""
    ) -> Tuple[Dict, int]:
        """
        Initiate an ownership transfer request (as current owner).
        
        The CURRENT OWNER creates a transfer offer to a new owner.
        The new owner can then accept or reject the offer.
        
        Args:
            file_id: UUID of the digital asset
            new_owner_address: Wallet address of the proposed new owner
            asking_price: Price in BZT that new owner must pay
            message: Optional message to new owner
            
        Returns:
            Tuple of (response, status_code)
        """
        if not self.state.CURRENT_WALLET:
            return {"error": "No wallet loaded"}, 400
        
        # Verify we own the asset
        asset_result, asset_status = self.get_asset_details(file_id)
        if asset_status != 200:
            return {"error": "Asset not found"}, 404
        
        asset = asset_result.get("asset", asset_result)
        current_owner = asset.get("owner") or asset.get("owner_address")
        
        if current_owner != self.state.CURRENT_WALLET.address:
            return {"error": "You don't own this asset"}, 403
        
        if new_owner_address == self.state.CURRENT_WALLET.address:
            return {"error": "Cannot transfer to yourself"}, 400
        
        try:
            from shared.transaction import Transaction
        except ImportError:
            return {"error": "Transaction module not available"}, 500
        
        # Format price
        price_str = f"{asking_price:.6f} BZT" if asking_price > 0 else "0 BZT"
        
        # ECDH key wrapping: wrap encryption key so new owner can decrypt the file
        wrapped_file_key = None
        wrap_nonce = None
        encryption_nonce = asset.get("encryption_nonce")
        
        if encryption_nonce:
            # File is encrypted - wrap the encryption key for the new owner
            try:
                from shared.client_core.rekey import derive_shared_key_ecdh, encrypt_with_key
                from shared.client_core.encryption import derive_encryption_key
                import base64
                
                # Get new owner's public key from blockchain
                pubkey_result, pubkey_status = self._chain_request(
                    f"/api/blockchain/wallet/{new_owner_address}/pubkey"
                )
                
                if pubkey_status == 200 and pubkey_result.get("pubkey"):
                    new_owner_pubkey = bytes.fromhex(pubkey_result["pubkey"])
                    
                    # Derive ECDH shared key
                    shared_key = derive_shared_key_ecdh(
                        self.state.CURRENT_WALLET.privkey,
                        new_owner_pubkey
                    )
                    
                    # Get current owner's encryption key
                    owner_enc_key = derive_encryption_key(self.state.CURRENT_WALLET)
                    
                    # Wrap the encryption key with the ECDH shared key
                    wrapped_bytes, wrap_nonce_bytes = encrypt_with_key(owner_enc_key, shared_key)
                    wrapped_file_key = base64.b64encode(wrapped_bytes).decode('utf-8')
                    wrap_nonce = base64.b64encode(wrap_nonce_bytes).decode('utf-8')
                    
                    print(f"[CLIENT] Encryption key wrapped for new owner via ECDH", flush=True)
                else:
                    print(f"[CLIENT] WARNING: Could not get new owner pubkey, "
                          f"new owner may not be able to decrypt", flush=True)
            except Exception as e:
                print(f"[CLIENT] WARNING: Key wrapping failed: {e}", flush=True)
        
        tx = Transaction.make_ownership_request(
            file_id=file_id,
            current_owner=self.state.CURRENT_WALLET.address,
            new_owner=new_owner_address,
            asking_price=price_str,
            wallet=self.state.CURRENT_WALLET,
            message=message,
            wrapped_file_key=wrapped_file_key,
            wrap_nonce=wrap_nonce,
            encryption_nonce=encryption_nonce,
            seller_pubkey=self.state.CURRENT_WALLET.get_pubkey_hex()
        )
        
        print(f"[CLIENT] Created ownership request: {tx.tx_hash[:16]}...", flush=True)
        
        result, status = self._chain_request(
            "/transactions",
            method="POST",
            data=tx.to_dict()
        )
        
        if status in (200, 201):
            return {
                "tx_hash": tx.tx_hash,
                "request_id": tx.tx_hash,  # tx_hash serves as request_id
                "status": "pending",
                "file_id": file_id,
                "new_owner": new_owner_address,
                "asking_price": price_str
            }, 200
        
        return result, status
    
    def get_pending_ownership_requests(self) -> Tuple[Dict, int]:
        """
        Get pending ownership requests where current user is involved.
        
        Returns:
            Tuple of ({"incoming": [...], "outgoing": [...]}, status_code)
            - incoming: Requests where user is the proposed new owner
            - outgoing: Requests where user is the current owner (initiator)
        """
        if not self.state.CURRENT_WALLET:
            return {"error": "No wallet loaded"}, 400
        
        return self._chain_request(
            "/api/ownership/pending",
            params={"address": self.state.CURRENT_WALLET.address}
        )
    
    def accept_ownership_request(
        self,
        request_id: str,
        file_id: str,
        asking_price: float
    ) -> Tuple[Dict, int]:
        """
        Accept an ownership transfer request (as NEW owner).
        
        The NEW OWNER accepts the transfer and pays the asking price.
        
        Args:
            request_id: UUID/tx_hash of the ownership request
            file_id: UUID of the digital asset
            asking_price: Price to pay in BZT (must match request)
            
        Returns:
            Tuple of (response, status_code)
        """
        if not self.state.CURRENT_WALLET:
            return {"error": "No wallet loaded"}, 400
        
        try:
            from shared.transaction import Transaction
        except ImportError:
            return {"error": "Transaction module not available"}, 500
        
        # Format price
        price_str = f"{asking_price:.6f} BZT" if asking_price > 0 else "0 BZT"
        
        tx = Transaction.make_ownership_accept(
            request_id=request_id,
            file_id=file_id,
            new_owner=self.state.CURRENT_WALLET.address,
            asking_price=price_str,
            wallet=self.state.CURRENT_WALLET
        )
        
        print(f"[CLIENT] Accepting ownership: {tx.tx_hash[:16]}...", flush=True)
        
        result, status = self._chain_request(
            "/transactions",
            method="POST",
            data=tx.to_dict()
        )
        
        if status in (200, 201):
            return {"tx_hash": tx.tx_hash, "status": "accepted"}, 200
        
        return result, status

    def seller_accept_ownership_request(
        self,
        request_id: str,
        file_id: str,
        buyer_address: str,
        asking_price: float
    ) -> Tuple[Dict, int]:
        """
        Seller accepts a buyer-initiated ownership request.
        
        The CURRENT OWNER (seller) approves the buyer's purchase request.
        The buyer will pay the asking price; ownership transfers to buyer.
        For encrypted files the seller wraps the encryption key via ECDH
        so the buyer can decrypt after transfer.

        Args:
            request_id: TX hash of the ownership_request
            file_id: UUID of the digital asset
            buyer_address: The buyer's wallet address (new_owner)
            asking_price: The agreed price in BZT

        Returns:
            Tuple of (response, status_code)
        """
        if not self.state.CURRENT_WALLET:
            return {"error": "No wallet loaded"}, 400

        try:
            from shared.transaction import Transaction
        except ImportError:
            return {"error": "Transaction module not available"}, 500

        price_str = f"{asking_price:.6f} BZT" if asking_price > 0 else "0 BZT"

        # ECDH key wrapping for encrypted files (buyer-initiated flow)
        wrapped_file_key = None
        wrap_nonce = None
        encryption_nonce = None

        asset_result, asset_status = self.get_asset_details(file_id)
        if asset_status == 200:
            asset = asset_result.get("asset", asset_result)
            encryption_nonce = asset.get("encryption_nonce")

            if encryption_nonce:
                try:
                    from shared.client_core.rekey import derive_shared_key_ecdh, encrypt_with_key
                    from shared.client_core.encryption import derive_encryption_key
                    import base64

                    pubkey_result, pubkey_status = self._chain_request(
                        f"/api/blockchain/wallet/{buyer_address}/pubkey"
                    )

                    if pubkey_status == 200 and pubkey_result.get("pubkey"):
                        buyer_pubkey = bytes.fromhex(pubkey_result["pubkey"])
                        shared_key = derive_shared_key_ecdh(
                            self.state.CURRENT_WALLET.privkey,
                            buyer_pubkey
                        )
                        owner_enc_key = derive_encryption_key(self.state.CURRENT_WALLET)
                        wrapped_bytes, wrap_nonce_bytes = encrypt_with_key(owner_enc_key, shared_key)
                        wrapped_file_key = base64.b64encode(wrapped_bytes).decode('utf-8')
                        wrap_nonce = base64.b64encode(wrap_nonce_bytes).decode('utf-8')
                        print(f"[CLIENT] ECDH key wrapped for buyer (seller-accept flow)", flush=True)
                    else:
                        print(f"[CLIENT] WARNING: Could not get buyer pubkey for ECDH wrapping", flush=True)
                except Exception as e:
                    print(f"[CLIENT] WARNING: ECDH key wrapping failed: {e}", flush=True)

        tx = Transaction.make_ownership_accept(
            request_id=request_id,
            file_id=file_id,
            new_owner=buyer_address,
            asking_price=price_str,
            wallet=self.state.CURRENT_WALLET,
            current_owner=self.state.CURRENT_WALLET.address,
        )

        tx_data = tx.to_dict()

        if wrapped_file_key:
            tx_data["wrapped_file_key"] = wrapped_file_key
            tx_data["wrap_nonce"] = wrap_nonce
            tx_data["seller_pubkey"] = self.state.CURRENT_WALLET.get_pubkey_hex()
            tx_data["file_encryption_nonce"] = encryption_nonce

        print(f"[CLIENT] Seller accepting buyer request: {tx.tx_hash[:16]}...", flush=True)
        if wrapped_file_key:
            print(f"[CLIENT]   ECDH wrapping data included in accept TX", flush=True)

        result, status = self._chain_request(
            "/transactions",
            method="POST",
            data=tx_data
        )

        if status in (200, 201):
            return {"tx_hash": tx.tx_hash, "status": "accepted"}, 200

        return result, status

    # ---- Lightning Transfer (two-party, no secret sharing) ----

    def lightning_create_offer(
        self,
        file_id: str,
        buyer_address: str,
        asking_price: float,
        message: str = "",
    ) -> Tuple[Dict, int]:
        """
        SELLER: Create a signed ownership_request and export it as a
        shareable offer code.  No buyer secrets are needed.

        The offer is a JSON dict containing the fully signed
        ownership_request transaction that the buyer can inspect and
        then countersign with their own wallet.

        Args:
            file_id: UUID of the digital asset
            buyer_address: Buyer's wallet address (public info)
            asking_price: Price in BZT
            message: Optional message to buyer

        Returns:
            Tuple of (offer_dict, status_code)
        """
        if not self.state.CURRENT_WALLET:
            return {"error": "No wallet loaded"}, 400

        asset_result, asset_status = self.get_asset_details(file_id)
        if asset_status != 200:
            return {"error": "Asset not found"}, 404

        asset = asset_result.get("asset", asset_result)
        current_owner = asset.get("owner") or asset.get("owner_address")

        if current_owner != self.state.CURRENT_WALLET.address:
            return {"error": "You don't own this asset"}, 403
        if buyer_address == self.state.CURRENT_WALLET.address:
            return {"error": "Cannot transfer to yourself"}, 400

        from shared.transaction import Transaction

        price_str = f"{asking_price:.6f} BZT" if asking_price > 0 else "0 BZT"

        # ECDH key wrapping for encrypted files
        wrapped_file_key = None
        wrap_nonce = None
        encryption_nonce = asset.get("encryption_nonce")

        if encryption_nonce:
            try:
                from shared.client_core.rekey import derive_shared_key_ecdh, encrypt_with_key
                from shared.client_core.encryption import derive_encryption_key
                import base64

                # Get buyer's public key from the blockchain (public info)
                pubkey_result, pubkey_status = self._chain_request(
                    f"/api/blockchain/wallet/{buyer_address}/pubkey"
                )
                if pubkey_status == 200 and pubkey_result.get("pubkey"):
                    buyer_pubkey_bytes = bytes.fromhex(pubkey_result["pubkey"])
                    shared_key = derive_shared_key_ecdh(
                        self.state.CURRENT_WALLET.privkey, buyer_pubkey_bytes
                    )
                    owner_enc_key = derive_encryption_key(self.state.CURRENT_WALLET)
                    wrapped_bytes, wrap_nonce_bytes = encrypt_with_key(owner_enc_key, shared_key)
                    wrapped_file_key = base64.b64encode(wrapped_bytes).decode("utf-8")
                    wrap_nonce = base64.b64encode(wrap_nonce_bytes).decode("utf-8")
                    print("[LIGHTNING] Encryption key wrapped via ECDH (buyer pubkey from chain)", flush=True)
                else:
                    print("[LIGHTNING] WARNING: buyer pubkey not on chain, key wrapping skipped", flush=True)
            except Exception as e:
                print(f"[LIGHTNING] WARNING: Key wrapping failed: {e}", flush=True)

        req_tx = Transaction.make_ownership_request(
            file_id=file_id,
            current_owner=self.state.CURRENT_WALLET.address,
            new_owner=buyer_address,
            asking_price=price_str,
            wallet=self.state.CURRENT_WALLET,
            message=message,
            wrapped_file_key=wrapped_file_key,
            wrap_nonce=wrap_nonce,
            encryption_nonce=encryption_nonce,
            seller_pubkey=self.state.CURRENT_WALLET.get_pubkey_hex(),
        )

        import time as _time
        # Offer expires in 30 minutes (buyer must accept within this window)
        expires_at = int(_time.time()) + 30 * 60

        offer = {
            "type": "lightning_offer",
            "ownership_request": req_tx.to_dict(),
            "file_id": file_id,
            "file_name": asset.get("file_name", asset.get("name", "Unknown")),
            "seller": self.state.CURRENT_WALLET.address,
            "buyer": buyer_address,
            "asking_price": price_str,
            "message": message,
            "expires_at": expires_at,
        }

        print(f"[LIGHTNING] Offer created: {req_tx.tx_hash[:16]}...", flush=True)
        return offer, 200

    def lightning_accept_offer(self, offer: Dict) -> Tuple[Dict, int]:
        """
        BUYER: Accept a Lightning offer by signing an ownership_accept TX
        with the buyer's own wallet and submitting the bundle to the chain.

        The buyer NEVER shares their mnemonic or private key.  They only
        sign with the wallet already loaded in their client.

        Args:
            offer: The offer dict received from the seller (contains the
                   signed ownership_request transaction)

        Returns:
            Tuple of (response, status_code)
        """
        if not self.state.CURRENT_WALLET:
            return {"error": "No wallet loaded"}, 400

        req_tx_dict = offer.get("ownership_request")
        if not req_tx_dict:
            return {"error": "Invalid offer: missing ownership_request"}, 400

        # Check expiry
        import time as _time
        expires_at = offer.get("expires_at")
        if expires_at and int(_time.time()) > int(expires_at):
            return {"error": "This offer has expired"}, 410

        buyer_address = offer.get("buyer")
        if buyer_address != self.state.CURRENT_WALLET.address:
            return {"error": "This offer is not addressed to your wallet"}, 403

        file_id = offer.get("file_id")
        asking_price = offer.get("asking_price", "0 BZT")
        request_tx_hash = req_tx_dict.get("tx_hash")

        from shared.transaction import Transaction

        acc_tx = Transaction.make_ownership_accept(
            request_id=request_tx_hash,
            file_id=file_id,
            new_owner=self.state.CURRENT_WALLET.address,
            asking_price=asking_price,
            wallet=self.state.CURRENT_WALLET,
        )

        print(f"[LIGHTNING] Buyer signed accept: {acc_tx.tx_hash[:16]}...", flush=True)

        bundle = {
            "ownership_request": req_tx_dict,
            "ownership_accept": acc_tx.to_dict(),
        }

        result, status = self._chain_request(
            "/api/ownership/lightning-bundle",
            method="POST",
            data=bundle,
        )

        if status in (200, 201):
            return {
                "status": "success",
                "request_tx_hash": request_tx_hash,
                "accept_tx_hash": acc_tx.tx_hash,
                "file_id": file_id,
                "seller": offer.get("seller"),
                "asking_price": asking_price,
                "message": "Lightning bundle submitted - will be mined in next block",
            }, 200

        return result, status

    def reject_ownership_request(
        self,
        request_id: str,
        file_id: str,
        reason: str = ""
    ) -> Tuple[Dict, int]:
        """
        Reject an ownership transfer request (as NEW owner).
        
        The NEW OWNER rejects the transfer offer.
        
        Args:
            request_id: UUID/tx_hash of the ownership request
            file_id: UUID of the digital asset
            reason: Optional rejection reason
            
        Returns:
            Tuple of (response, status_code)
        """
        if not self.state.CURRENT_WALLET:
            return {"error": "No wallet loaded"}, 400
        
        try:
            from shared.transaction import Transaction
        except ImportError:
            return {"error": "Transaction module not available"}, 500
        
        tx = Transaction.make_ownership_reject(
            request_id=request_id,
            file_id=file_id,
            new_owner=self.state.CURRENT_WALLET.address,
            wallet=self.state.CURRENT_WALLET,
            message=reason
        )
        
        print(f"[CLIENT] Rejecting ownership: {tx.tx_hash[:16]}...", flush=True)
        
        result, status = self._chain_request(
            "/transactions",
            method="POST",
            data=tx.to_dict()
        )
        
        if status in (200, 201):
            return {"tx_hash": tx.tx_hash, "status": "rejected"}, 200
        
        return result, status
    
    def cancel_ownership_request(
        self,
        request_id: str,
        file_id: str
    ) -> Tuple[Dict, int]:
        """
        Cancel an ownership transfer request (as CURRENT owner).
        
        The CURRENT OWNER cancels their own transfer offer.
        
        Args:
            request_id: UUID/tx_hash of the ownership request
            file_id: UUID of the digital asset
            
        Returns:
            Tuple of (response, status_code)
        """
        if not self.state.CURRENT_WALLET:
            return {"error": "No wallet loaded"}, 400
        
        try:
            from shared.transaction import Transaction
        except ImportError:
            return {"error": "Transaction module not available"}, 500
        
        tx = Transaction.make_ownership_cancel(
            request_id=request_id,
            file_id=file_id,
            current_owner=self.state.CURRENT_WALLET.address,
            wallet=self.state.CURRENT_WALLET
        )
        
        print(f"[CLIENT] Cancelling ownership request: {tx.tx_hash[:16]}...", flush=True)
        
        result, status = self._chain_request(
            "/transactions",
            method="POST",
            data=tx.to_dict()
        )
        
        if status in (200, 201):
            return {"tx_hash": tx.tx_hash, "status": "cancelled"}, 200
        
        return result, status
    
    def get_ownership_request_details(
        self,
        request_id: str
    ) -> Tuple[Dict, int]:
        """
        Get details of a specific ownership request.
        
        Args:
            request_id: UUID/tx_hash of the ownership request
            
        Returns:
            Tuple of (request_details, status_code)
        """
        return self._chain_request(f"/api/ownership/request/{request_id}")
    
    # === Asset Updates ===
    
    def update_asset_price(
        self,
        file_id: str,
        new_price: float
    ) -> Tuple[Dict, int]:
        """
        Update the marketplace price of a digital asset.
        
        Args:
            file_id: UUID of the digital asset
            new_price: New price in BZT
            
        Returns:
            Tuple of (response, status_code)
        """
        if not self.state.CURRENT_WALLET:
            return {"error": "No wallet loaded"}, 400
        
        try:
            from shared.transaction import Transaction
        except ImportError:
            return {"error": "Transaction module not available"}, 500
        
        print(f"[CLIENT] Creating update_price TX: file_id={file_id}, new_price={new_price}", flush=True)
        try:
            tx = Transaction.make_update_price(
                file_id=file_id,
                owner_address=self.state.CURRENT_WALLET.address,
                new_price=f"{new_price:.6f} BZT",
                wallet=self.state.CURRENT_WALLET
            )
        except Exception as e:
            print(f"[CLIENT] ERROR creating update_price TX: {e}", flush=True)
            import traceback; traceback.print_exc()
            return {"error": f"TX creation failed: {e}"}, 500
        
        print(f"[CLIENT] Update price TX created: {tx.tx_hash[:16]}...", flush=True)
        
        result, status = self._chain_request(
            "/transactions",
            method="POST",
            data=tx.to_dict()
        )
        
        print(f"[CLIENT] Update price chain response: status={status}, result={result}", flush=True)
        
        if status in (200, 201):
            return {"tx_hash": tx.tx_hash, "new_price": new_price, "status": "sent"}, 200
        
        return result, status
    
    def update_asset_visibility(
        self,
        file_id: str,
        visibility: str,
        blur: bool = True
    ) -> Tuple[Dict, int]:
        """
        Update the visibility of a digital asset.
        
        Args:
            file_id: UUID of the digital asset
            visibility: "public" or "private"
            blur: If True and visibility is private, regenerate blur preview
            
        Returns:
            Tuple of (response, status_code)
        """
        if not self.state.CURRENT_WALLET:
            return {"error": "No wallet loaded"}, 400
        
        try:
            from shared.transaction import Transaction
        except ImportError:
            return {"error": "Transaction module not available"}, 500
        
        # When going from public to private, blur must be True
        if visibility == "private":
            blur = True
        
        print(f"[CLIENT] Creating update_visibility TX: file_id={file_id}, visibility={visibility}", flush=True)
        try:
            tx = Transaction.make_update_visibility(
                file_id=file_id,
                owner_address=self.state.CURRENT_WALLET.address,
                visibility=visibility,
                wallet=self.state.CURRENT_WALLET
            )
        except Exception as e:
            print(f"[CLIENT] ERROR creating update_visibility TX: {e}", flush=True)
            import traceback; traceback.print_exc()
            return {"error": f"TX creation failed: {e}"}, 500
        
        print(f"[CLIENT] Update visibility TX created: {tx.tx_hash[:16]}...", flush=True)
        
        result, status = self._chain_request(
            "/transactions",
            method="POST",
            data=tx.to_dict()
        )
        
        print(f"[CLIENT] Update visibility chain response: status={status}, result={result}", flush=True)
        
        if status in (200, 201):
            return {"tx_hash": tx.tx_hash, "visibility": visibility, "status": "sent"}, 200
        
        return result, status
    
    # === File Download ===
    
    def download_file(
        self,
        file_id: str,
        destination_path: str
    ) -> Tuple[Dict, int]:
        """
        Download a digital asset file.
        
        Retrieves chunks from storage nodes, decrypts and reassembles.
        Falls back to backup chunk locations if primary fails.
        
        Args:
            file_id: UUID of the digital asset
            destination_path: Local path to save the file
            
        Returns:
            Tuple of ({"status": "downloaded", "path": str}, status_code)
        """
        if not self.state.CURRENT_WALLET:
            return {"error": "No wallet loaded"}, 400
        
        import os
        
        # Get asset details including chunk locations
        asset_result, asset_status = self.get_asset_details(file_id)
        if asset_status != 200:
            return {"error": "Asset not found"}, 404
        
        # Extract asset data from response
        asset = asset_result.get("asset", asset_result)
        
        # Check ownership
        owner = asset.get("owner") or asset.get("owner_address")
        if owner != self.state.CURRENT_WALLET.address:
            return {"error": "You don't own this asset"}, 403
        
        chunk_locations = asset.get("chunk_locations", {})
        backup_chunk_locations = asset.get("backup_chunk_locations", {})
        num_chunks = asset.get("num_chunks", 0)
        file_name = asset.get("file_name", "downloaded_file")
        
        # Ensure file extension is included in filename
        extension = asset.get("extension", "")
        if extension and not file_name.endswith(f".{extension}"):
            file_name = f"{file_name}.{extension}"
        
        if not chunk_locations or num_chunks == 0:
            return {"error": "No chunk data available"}, 400
        
        print(f"[CLIENT] Downloading {file_name} ({num_chunks} chunks)...", flush=True)
        print(f"[CLIENT] Primary locations: {len(chunk_locations)}, Backup locations: {len(backup_chunk_locations)}", flush=True)
        
        # Download and reassemble chunks
        try:
            from shared.client_core.encryption import decrypt_file_content, decode_nonce_b64
            from shared.client_core.chunking import concatenate_chunks
        except ImportError as e:
            print(f"[CLIENT] Import error: {e}", flush=True)
            return {"error": f"Download modules not available: {e}"}, 500
        
        chunks_data = []
        failed_chunks = []
        
        for i in range(num_chunks):
            chunk_id = f"{file_id}_chunk_{i}"
            
            # Collect all possible storage nodes (primary + backup)
            primary_nodes = chunk_locations.get(chunk_id, [])
            backup_nodes = backup_chunk_locations.get(chunk_id, [])
            
            # Combine and deduplicate node list
            all_nodes = []
            seen = set()
            for node_id in primary_nodes + backup_nodes:
                if node_id not in seen:
                    all_nodes.append(node_id)
                    seen.add(node_id)
            
            if not all_nodes:
                print(f"[CLIENT] ERROR: No storage nodes for chunk {i}", flush=True)
                failed_chunks.append(i)
                continue
            
            print(f"[CLIENT] Chunk {i}: {len(all_nodes)} potential sources", flush=True)
            
            # Try each storage node until success
            chunk_data = None
            for node_id in all_nodes:
                # First try to find node in active nodes
                node = self._find_storage_node(node_id)
                if node:
                    chunk_data = self._fetch_chunk(node, file_id, chunk_id)
                    if chunk_data:
                        print(f"[CLIENT] Chunk {i} fetched from active node {node_id[:16]}...", flush=True)
                        break
                
                # If not in active nodes, try direct fetch by node_id
                if not chunk_data:
                    chunk_data = self._fetch_chunk_by_node_id(node_id, file_id, chunk_id)
                    if chunk_data:
                        print(f"[CLIENT] Chunk {i} fetched directly from {node_id[:16]}...", flush=True)
                        break
            
            if not chunk_data:
                print(f"[CLIENT] WARNING: Failed to download chunk {i} from any source", flush=True)
                failed_chunks.append(i)
                continue
            
            chunks_data.append((i, chunk_data))
            print(f"[CLIENT] Downloaded chunk {i+1}/{num_chunks}", flush=True)
        
        # Check if any chunks failed
        if failed_chunks:
            return {
                "error": f"Failed to download chunks: {failed_chunks}",
                "failed_chunks": failed_chunks,
                "total_chunks": num_chunks,
                "successful_chunks": len(chunks_data)
            }, 500
        
        # Sort chunks by index and extract data
        chunks_data.sort(key=lambda x: x[0])
        ordered_chunks = [data for _, data in chunks_data]
        
        # Reassemble chunks
        file_data = concatenate_chunks(ordered_chunks)
        print(f"[CLIENT] Reassembled {len(file_data)} bytes", flush=True)
        
        # Check if file is encrypted
        # encryption_nonce is the actual 12-byte nonce (base64 encoded, ~16-24 chars)
        # query_hash is a SHA256 content hash (64 hex chars) - NOT an encryption nonce
        encryption_nonce = asset.get("encryption_nonce")
        if encryption_nonce:
            nonce = decode_nonce_b64(encryption_nonce)
            uploader = asset.get("uploader") or asset.get("uploader_address", "")
            is_original_uploader = (uploader == self.state.CURRENT_WALLET.address)
            
            if is_original_uploader:
                # Original uploader: decrypt with wallet-derived key
                original_file_size = asset.get("file_size", 0)
                query_hash = asset.get("query_hash", "")
                decrypted_data = None

                # --- Strategy 1: Standard AES-GCM decryption ---
                try:
                    decrypted_data = decrypt_file_content(file_data, nonce, self.state.CURRENT_WALLET)
                    print(f"[CLIENT] Decrypted with own key (GCM): {len(decrypted_data)} bytes", flush=True)
                except Exception as e:
                    print(f"[CLIENT] GCM decryption failed: {e}", flush=True)

                # --- Strategy 2: Check if data is actually unencrypted ---
                if decrypted_data is None and query_hash:
                    data_hash = hashlib.sha256(file_data).hexdigest()
                    if data_hash == query_hash:
                        print(f"[CLIENT] Data hash matches query_hash — file is UNENCRYPTED", flush=True)
                        decrypted_data = file_data

                # --- Strategy 3: AES-CTR recovery (GCM tag may be truncated) ---
                if decrypted_data is None:
                    print(f"[CLIENT] Attempting AES-CTR recovery (GCM tag may have been lost)...", flush=True)
                    print(f"[CLIENT]   data_size={len(file_data)}, file_size={original_file_size}", flush=True)
                    try:
                        from shared.client_core.encryption import recover_truncated_gcm
                        decrypted_data = recover_truncated_gcm(
                            file_data, nonce, self.state.CURRENT_WALLET,
                            expected_plaintext_hash=query_hash if query_hash else None
                        )
                        print(f"[CLIENT] ✓ File recovered via CTR fallback: {len(decrypted_data)} bytes", flush=True)
                    except Exception as recovery_err:
                        print(f"[CLIENT] CTR recovery also failed: {recovery_err}", flush=True)

                # --- Strategy 4: CTR on data[:-16] in case file_size is encrypted size ---
                if decrypted_data is None and len(file_data) > 16:
                    print(f"[CLIENT] Trying CTR on data[:-16] (tag may be appended)...", flush=True)
                    try:
                        from shared.client_core.encryption import recover_truncated_gcm
                        decrypted_data = recover_truncated_gcm(
                            file_data[:-16], nonce, self.state.CURRENT_WALLET,
                            expected_plaintext_hash=query_hash if query_hash else None
                        )
                        print(f"[CLIENT] ✓ File recovered via CTR on data[:-16]: {len(decrypted_data)} bytes", flush=True)
                    except Exception as recovery_err2:
                        print(f"[CLIENT] CTR on data[:-16] also failed: {recovery_err2}", flush=True)

                if decrypted_data is None:
                    import traceback
                    traceback.print_exc()
                    return {
                        "error": "All decryption strategies failed. File may be corrupted or wallet mismatch.",
                        "details": (
                            f"data_size={len(file_data)}, file_size={original_file_size}, "
                            f"query_hash={query_hash[:16]}..."
                        )
                    }, 500
            else:
                # Acquired via ownership transfer: unwrap key via ECDH
                print(f"[CLIENT] File acquired via transfer, attempting ECDH key unwrap...", flush=True)
                decrypted_data = self._decrypt_transferred_file(file_id, file_data, nonce)
                if decrypted_data is None:
                    print(f"[CLIENT] ECDH unwrap failed", flush=True)
                    return {
                        "error": "ECDH key unwrap failed. Re-encryption may not have completed.",
                        "details": "The seller's encryption key could not be unwrapped."
                    }, 500
        else:
            # Not encrypted - use raw data
            decrypted_data = file_data
        
        # Save to destination
        full_path = os.path.join(destination_path, file_name)
        with open(full_path, 'wb') as f:
            f.write(decrypted_data)
        
        print(f"[CLIENT] Downloaded to {full_path}", flush=True)
        return {"status": "downloaded", "path": full_path, "file_name": file_name}, 200
    
    def _decrypt_transferred_file(
        self, file_id: str, encrypted_data: bytes, nonce: bytes
    ) -> Optional[bytes]:
        """
        Decrypt a file acquired via ownership transfer using ECDH key unwrapping.
        
        The original owner wrapped their encryption key with an ECDH shared secret.
        This method:
        1. Finds the ownership_request transaction for this file
        2. Extracts wrapped_file_key, wrap_nonce, and seller_pubkey
        3. Derives the same ECDH shared key using own privkey + seller pubkey
        4. Unwraps the original encryption key
        5. Decrypts the file with the original key + original nonce
        
        Args:
            file_id: UUID of the digital asset
            encrypted_data: Encrypted file content (all chunks reassembled)
            nonce: Original encryption nonce (12 bytes)
            
        Returns:
            Decrypted file content, or None if unwrapping fails
        """
        try:
            import base64
            from shared.client_core.rekey import derive_shared_key_ecdh, decrypt_with_key
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
            
            # Find the ECDH wrapping data from ownership history
            result, status = self._chain_request(
                f"/api/ownership/history/{file_id}"
            )
            
            wrapped_file_key = None
            wrap_nonce_b64 = None
            seller_pubkey_hex = None
            
            if status == 200:
                transfers = result.get("history", [])
                for transfer in transfers:
                    if transfer.get("to_owner") == self.state.CURRENT_WALLET.address:
                        wrapped_file_key = transfer.get("wrapped_file_key")
                        wrap_nonce_b64 = transfer.get("wrap_nonce")
                        seller_pubkey_hex = transfer.get("seller_pubkey")
                        if wrapped_file_key:
                            print(f"[CLIENT] Found ECDH data in ownership history", flush=True)
                            break
            
            # Fallback: scan blockchain for the ownership_request TX
            if not wrapped_file_key:
                print(f"[CLIENT] Ownership history lookup failed (status={status}), scanning blocks...", flush=True)
                result2, status2 = self._chain_request(
                    "/api/blockchain/blocks"
                )
                if status2 == 200:
                    blocks = result2.get("blocks", [])
                    for block in blocks:
                        body = block.get("body", {})
                        txs = body.get("txs", []) or body.get("transactions", [])
                        for tx in txs:
                            if (tx.get("type") == "ownership_request" and
                                tx.get("file_id") == file_id and
                                tx.get("new_owner") == self.state.CURRENT_WALLET.address):
                                wrapped_file_key = tx.get("wrapped_file_key")
                                wrap_nonce_b64 = tx.get("wrap_nonce")
                                seller_pubkey_hex = tx.get("seller_pubkey")
                                if wrapped_file_key:
                                    print(f"[CLIENT] Found ECDH data in blockchain TX", flush=True)
                                    break
                        if wrapped_file_key:
                            break
            
            if not wrapped_file_key or not wrap_nonce_b64 or not seller_pubkey_hex:
                print(f"[CLIENT] No ECDH key wrapping data found for file {file_id[:16]}...", flush=True)
                print(f"[CLIENT] File may have been uploaded before encryption was enabled", flush=True)
                return None
            
            # Derive ECDH shared key
            seller_pubkey = bytes.fromhex(seller_pubkey_hex)
            shared_key = derive_shared_key_ecdh(
                self.state.CURRENT_WALLET.privkey,
                seller_pubkey
            )
            
            # Unwrap the original encryption key
            wrapped_bytes = base64.b64decode(wrapped_file_key)
            wrap_nonce_bytes = base64.b64decode(wrap_nonce_b64)
            original_enc_key = decrypt_with_key(wrapped_bytes, wrap_nonce_bytes, shared_key)
            
            print(f"[CLIENT] Encryption key unwrapped via ECDH", flush=True)
            
            # Decrypt file with original encryption key + original nonce
            aesgcm = AESGCM(original_enc_key)
            decrypted = aesgcm.decrypt(nonce, encrypted_data, None)
            
            print(f"[CLIENT] File decrypted via ECDH: {len(decrypted)} bytes", flush=True)
            return decrypted
            
        except Exception as e:
            print(f"[CLIENT] ECDH decryption error: {e}", flush=True)
            import traceback
            traceback.print_exc()
            return None
    
    def _find_storage_node(self, node_id: str) -> Optional[Dict]:
        """Find a storage node by ID in active nodes."""
        if not self.state.active_nodes:
            return None
        for node in self.state.active_nodes:
            if node.get("node_id") == node_id:
                return node
        return None
    
    def _resolve_storage_node_id(self, node_id: str) -> Optional[str]:
        """Resolve a node_id to its Docker hostname by looking up the ip
        field in the active node list.

        Falls back to the raw node_id if the node isn't found (the
        resolve_node_address function can handle Docker hostnames and
        partial matches).
        """
        if not node_id:
            return None

        # Prefer the authoritative ip field from consensus
        for node in (self.state.active_nodes or []):
            if node.get("node_id") == node_id:
                ip = node.get("ip")
                if ip:
                    return ip

        # Fallback: return node_id itself so resolve_node_address can
        # attempt its own partial matching
        return node_id
    
    def _fetch_chunk_by_node_id(self, node_id: str, file_id: str, chunk_id: str) -> Optional[bytes]:
        """
        Fetch a chunk directly by node_id without requiring node in active list.
        
        This is used as fallback when the primary node isn't in active_nodes
        (e.g., when downloading from backup nodes).
        """
        try:
            from shared.client_core.docker_mapping import resolve_node_address
            
            # Resolve node_id to hostname (e.g., "storage_1_673a33" -> "storage1")
            storage_name = self._resolve_storage_node_id(node_id)
            if not storage_name:
                print(f"[CLIENT] Cannot resolve node_id: {node_id}", flush=True)
                return None
            
            # Get host IP and port
            host_ip, http_port = resolve_node_address(storage_name, use_zmq=False)
            
            # Extract chunk index
            if "_chunk_" in chunk_id:
                chunk_index = chunk_id.split("_chunk_")[-1]
            else:
                chunk_index = chunk_id
            
            url = f"http://{host_ip}:{http_port}/get_chunk/{file_id}/{chunk_index}"
            print(f"[CLIENT] Fetching chunk from {url} (node_id: {node_id[:16]}...)", flush=True)
            
            response = self.session.get(url, timeout=30)
            if response.status_code == 200:
                return response.content
            print(f"[CLIENT] Chunk fetch returned status {response.status_code}", flush=True)
            return None
        except Exception as e:
            print(f"[CLIENT] Error fetching chunk by node_id {node_id}: {e}", flush=True)
            return None
    
    def _fetch_chunk(self, node: Dict, file_id: str, chunk_id: str) -> Optional[bytes]:
        """Fetch a chunk from a storage node."""
        try:
            from shared.client_core.docker_mapping import resolve_node_address
            
            # Get node IP - could be Docker container name or direct IP
            node_ip_raw = node.get("ip", "")
            node_id = node.get("node_id", "")
            
            # Use the ip field from consensus (Docker hostname) - same fix
            # as the upload path.
            if node_ip_raw:
                host_ip, http_port = resolve_node_address(node_ip_raw, use_zmq=False)
            elif node_id:
                host_ip, http_port = resolve_node_address(node_id, use_zmq=False)
            else:
                host_ip, http_port = resolve_node_address("localhost", use_zmq=False)
            
            # Extract just the chunk index from chunk_id (e.g., "file_id_chunk_0" -> "0")
            if "_chunk_" in chunk_id:
                chunk_index = chunk_id.split("_chunk_")[-1]
            else:
                chunk_index = chunk_id
            
            # Storage node endpoint is /get_chunk/{file_id}/{chunk_index}
            url = f"http://{host_ip}:{http_port}/get_chunk/{file_id}/{chunk_index}"
            print(f"[CLIENT] Fetching chunk from {url}", flush=True)
            
            response = self.session.get(url, timeout=30)
            if response.status_code == 200:
                return response.content
            print(f"[CLIENT] Chunk fetch returned status {response.status_code}", flush=True)
            return None
        except Exception as e:
            print(f"[CLIENT] Error fetching chunk: {e}", flush=True)
            return None
    
    # === Notifications ===
    
    def get_notifications(self) -> Tuple[Dict, int]:
        """
        Get all notifications for the current user.
        
        Returns ownership requests, responses, and other events.
        
        Returns:
            Tuple of ({"notifications": [...]}, status_code)
        """
        if not self.state.CURRENT_WALLET:
            return {"error": "No wallet loaded"}, 400
        
        return self._chain_request(
            "/api/notifications",
            params={"address": self.state.CURRENT_WALLET.address}
        )
    
    def mark_notification_read(self, notification_id: str) -> Tuple[Dict, int]:
        """Mark a notification as read."""
        return self._chain_request(
            f"/api/notifications/{notification_id}/read",
            method="POST"
        )
