"""
Transaction Polling Service

Periodically checks the blockchain for pending transactions and their status.
Provides real-time updates without local database persistence.
"""

import threading
import time
import requests
from typing import Dict, List, Optional


class TransactionPoller:
    """
    Background service that polls blockchain for transaction status updates.

    Maintains an in-memory cache of recent transaction states without
    duplicating blockchain data.
    """

    def __init__(self, interval: int = 30, chain_nodes: List[Dict] = None):
        """
        Initialize transaction polling service.

        Args:
            interval: Polling interval in seconds (default: 30)
            chain_nodes: List of chain node dicts (optional, can be set later)
        """
        self.interval = interval
        self.chain_nodes = chain_nodes or []
        self.running = False
        self._cache = {}  # {address: {transactions, timestamp}}
        self._cache_ttl = 60  # Cache TTL in seconds
        self._lock = threading.RLock()
        self._thread = None

        print(f"[TxPoller] Initialized with {interval}s interval", flush=True)

    def set_chain_nodes(self, chain_nodes: List[Dict]) -> None:
        """Update the chain nodes list."""
        self.chain_nodes = chain_nodes

    def start(self) -> None:
        """Start polling service in background thread."""
        if self.running:
            print("[TxPoller] Already running", flush=True)
            return

        self.running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        print("[TxPoller] Started transaction polling service", flush=True)

    def stop(self) -> None:
        """Stop polling service gracefully."""
        self.running = False
        if self._thread:
            self._thread.join(timeout=5)
        print("[TxPoller] Stopped", flush=True)

    def _poll_loop(self) -> None:
        """Main polling loop in background thread."""
        while self.running:
            try:
                self._poll_updates()
            except Exception as e:
                print(f"[TxPoller] Error in poll loop: {e}", flush=True)

            # Sleep in small increments for quick shutdown
            for _ in range(self.interval):
                if not self.running:
                    break
                time.sleep(1)

    def _poll_updates(self) -> None:
        """Poll blockchain for transaction updates."""
        if not self.chain_nodes:
            return

        with self._lock:
            addresses_to_check = list(self._cache.keys())

        if not addresses_to_check:
            return

        node = self.chain_nodes[0]

        for address in addresses_to_check:
            try:
                url = f"http://{node['ip']}:5000/api/mempool/transactions"
                params = {'address': address, 'limit': 100}

                response = requests.get(url, params=params, timeout=10)

                if response.status_code == 200:
                    data = response.json()

                    with self._lock:
                        self._cache[address] = {
                            'transactions': data.get('pending_transactions', []),
                            'count': data.get('count', 0),
                            'total_mempool_size': data.get('total_mempool_size', 0),
                            'timestamp': time.time(),
                            'source_node': node.get('node_id')
                        }

            except Exception as e:
                print(f"[TxPoller] Error polling {address[:16]}...: {e}", flush=True)

        self._cleanup_cache()

    def _cleanup_cache(self) -> None:
        """Remove stale cache entries."""
        current_time = time.time()

        with self._lock:
            expired = [
                addr for addr, data in self._cache.items()
                if current_time - data['timestamp'] > self._cache_ttl
            ]

            for addr in expired:
                del self._cache[addr]

    def get_pending_transactions(self, address: str, force_refresh: bool = False) -> Optional[Dict]:
        """
        Get pending transactions for an address.

        Args:
            address: Wallet address
            force_refresh: Bypass cache and query blockchain

        Returns:
            Dictionary with pending transactions and metadata
        """
        if not force_refresh:
            with self._lock:
                cached = self._cache.get(address)
                if cached and (time.time() - cached['timestamp']) < self._cache_ttl:
                    return cached

        if not self.chain_nodes:
            return None

        try:
            node = self.chain_nodes[0]
            url = f"http://{node['ip']}:5000/api/mempool/transactions"
            params = {'address': address, 'limit': 100}

            response = requests.get(url, params=params, timeout=10)

            if response.status_code == 200:
                data = response.json()

                result = {
                    'transactions': data.get('pending_transactions', []),
                    'count': data.get('count', 0),
                    'total_mempool_size': data.get('total_mempool_size', 0),
                    'timestamp': time.time(),
                    'source_node': node.get('node_id')
                }

                with self._lock:
                    self._cache[address] = result

                return result

        except Exception as e:
            print(f"[TxPoller] Error getting pending transactions: {e}", flush=True)
            return None

    def get_transaction_status(self, tx_hash: str) -> Optional[Dict]:
        """
        Check status of a specific transaction.

        Args:
            tx_hash: Transaction hash

        Returns:
            Dictionary with transaction state and details
        """
        if not self.chain_nodes:
            return None

        try:
            node = self.chain_nodes[0]

            # Check mempool first
            mempool_url = f"http://{node['ip']}:5000/api/mempool/transaction/{tx_hash}"
            response = requests.get(mempool_url, timeout=5)

            if response.status_code == 200:
                data = response.json()
                if data.get('found'):
                    return {
                        'state': 'pending',
                        'transaction': data.get('transaction'),
                        'message': 'Transaction pending in mempool'
                    }

            # Check blockchain
            blockchain_url = f"http://{node['ip']}:5000/api/blockchain/transaction/{tx_hash}"
            response = requests.get(blockchain_url, timeout=5)

            if response.status_code == 200:
                data = response.json()
                return {
                    'state': 'confirmed',
                    'transaction': data.get('transaction'),
                    'block_info': {
                        'block_height': data.get('block_height'),
                        'block_hash': data.get('block_hash')
                    }
                }

            return {
                'state': 'not_found',
                'message': 'Transaction not found'
            }

        except Exception as e:
            print(f"[TxPoller] Error checking transaction status: {e}", flush=True)
            return None

    def get_cache_stats(self) -> Dict:
        """Get statistics about the cache."""
        with self._lock:
            return {
                'cached_addresses': len(self._cache),
                'total_cached_transactions': sum(
                    data['count'] for data in self._cache.values()
                ),
                'cache_ttl_seconds': self._cache_ttl,
                'polling_interval_seconds': self.interval
            }


# Global singleton instance
_poller_instance = None


def get_poller(chain_nodes: List[Dict] = None) -> TransactionPoller:
    """Get global TransactionPoller singleton instance."""
    global _poller_instance
    if _poller_instance is None:
        _poller_instance = TransactionPoller(chain_nodes=chain_nodes)
    elif chain_nodes:
        _poller_instance.set_chain_nodes(chain_nodes)
    return _poller_instance


def start_polling_service(chain_nodes: List[Dict] = None) -> None:
    """Start the global transaction polling service."""
    poller = get_poller(chain_nodes)
    poller.start()


def stop_polling_service() -> None:
    """Stop the global transaction polling service."""
    global _poller_instance
    if _poller_instance:
        _poller_instance.stop()
        _poller_instance = None
