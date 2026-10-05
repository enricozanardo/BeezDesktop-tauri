"""
BeezClient Ownership Service

Provides client-side functionality for digital asset ownership transfers:
- Create ownership transfer requests
- Accept ownership offers
- Reject ownership offers
- Cancel pending requests
- Query ownership history
"""

import zmq
from typing import Optional, List, Dict, Any
from dataclasses import dataclass


@dataclass
class OwnershipRequest:
    """Represents an ownership transfer request."""
    request_id: str
    file_id: str
    file_name: Optional[str]
    current_owner: str
    new_owner: str
    asking_price: float
    status: str
    message: Optional[str]
    created_at: str
    expires_at: Optional[str]


class OwnershipService:
    """
    Client-side service for managing digital asset ownership transfers.
    
    This service interacts with the blockchain to:
    1. Create ownership transfer requests
    2. Accept/reject pending requests
    3. Cancel own requests
    4. Query ownership history
    """
    
    def __init__(self, wallet: Any, chain_nodes: List[Dict]):
        """
        Initialize ownership service.
        
        Args:
            wallet: User's wallet object with address and signing capability
            chain_nodes: List of chain node dicts with 'ip' key
        """
        self.wallet = wallet
        self.chain_nodes = chain_nodes
        self.context = zmq.Context()
        self.timeout_ms = 10000  # 10 second timeout
    
    def _get_chain_socket(self) -> Optional[zmq.Socket]:
        """Get a ZMQ socket connected to a chain node."""
        if not self.chain_nodes:
            print("[OWNERSHIP] No chain nodes available", flush=True)
            return None
        
        chain_node = self.chain_nodes[0]
        socket = self.context.socket(zmq.REQ)
        socket.setsockopt(zmq.RCVTIMEO, self.timeout_ms)
        socket.setsockopt(zmq.SNDTIMEO, self.timeout_ms)
        socket.setsockopt(zmq.LINGER, 0)
        socket.connect(f"tcp://{chain_node['ip']}:5555")
        
        return socket
    
    def _get_transaction_class(self):
        """Import Transaction class with fallback."""
        try:
            from shared.transaction import Transaction
        except ImportError:
            from client_network.core.transaction import Transaction
        return Transaction
    
    def _submit_transaction(self, tx_dict: Dict) -> bool:
        """Submit a transaction to the blockchain."""
        socket = self._get_chain_socket()
        if not socket:
            return False
        
        try:
            request = {
                "type": "NEW_TX",
                "transaction": tx_dict
            }
            socket.send_json(request)
            response = socket.recv_json()
            
            if response.get("status_code") == 200:
                print(f"[OWNERSHIP] Transaction submitted: {tx_dict.get('tx_hash', 'unknown')[:16]}...", flush=True)
                return True
            else:
                print(f"[OWNERSHIP] Failed to submit: {response.get('error')}", flush=True)
                return False
                
        except Exception as e:
            print(f"[OWNERSHIP] Error submitting transaction: {e}", flush=True)
            return False
        finally:
            socket.close()
    
    def create_transfer_request(
        self,
        file_id: str,
        new_owner_address: str,
        asking_price: str,
        message: Optional[str] = None
    ) -> Optional[str]:
        """
        Create an ownership transfer request for a digital asset.
        
        Args:
            file_id: UUID of the digital asset
            new_owner_address: Wallet address of proposed new owner
            asking_price: Price in BZT (e.g., "10.5 BZT" or "10.5")
            message: Optional message to new owner
            
        Returns:
            Request ID if successful, None otherwise
        """
        try:
            Transaction = self._get_transaction_class()
            
            tx = Transaction.make_ownership_request(
                file_id=file_id,
                current_owner=self.wallet.address,
                new_owner=new_owner_address,
                asking_price=asking_price,
                wallet=self.wallet,
                message=message
            )
            
            if self._submit_transaction(tx.to_dict()):
                print(f"[OWNERSHIP] Created transfer request for {file_id[:16]}...", flush=True)
                return tx.tx_hash
            
            return None
            
        except Exception as e:
            print(f"[OWNERSHIP] Error creating transfer request: {e}", flush=True)
            return None
    
    def accept_transfer(
        self,
        request_id: str,
        message: Optional[str] = None
    ) -> bool:
        """
        Accept an ownership transfer request.
        
        Args:
            request_id: UUID of the ownership request
            message: Optional response message
            
        Returns:
            True if accepted successfully
        """
        try:
            request = self.get_request_details(request_id)
            if not request:
                print(f"[OWNERSHIP] Request not found: {request_id}", flush=True)
                return False
            
            if request.get("status") != "pending":
                print(f"[OWNERSHIP] Request is not pending: {request.get('status')}", flush=True)
                return False
            
            if request.get("new_owner_address") != self.wallet.address:
                print(f"[OWNERSHIP] Not authorized to accept this request", flush=True)
                return False
            
            file_id = request.get("file_id")
            asking_price = str(request.get("asking_price", 0))
            
            Transaction = self._get_transaction_class()
            
            tx = Transaction.make_ownership_accept(
                request_id=request_id,
                file_id=file_id,
                new_owner=self.wallet.address,
                asking_price=asking_price,
                wallet=self.wallet,
                message=message
            )
            
            if self._submit_transaction(tx.to_dict()):
                print(f"[OWNERSHIP] Accepted ownership of {file_id[:16]}...", flush=True)
                return True
            
            return False
            
        except Exception as e:
            print(f"[OWNERSHIP] Error accepting transfer: {e}", flush=True)
            return False
    
    def reject_transfer(
        self,
        request_id: str,
        reason: Optional[str] = None
    ) -> bool:
        """
        Reject an ownership transfer request.
        
        Args:
            request_id: UUID of the ownership request
            reason: Optional reason for rejection
            
        Returns:
            True if rejected successfully
        """
        try:
            request = self.get_request_details(request_id)
            if not request:
                return False
            
            if request.get("status") != "pending":
                return False
            
            if request.get("new_owner_address") != self.wallet.address:
                return False
            
            file_id = request.get("file_id")
            
            Transaction = self._get_transaction_class()
            
            tx = Transaction.make_ownership_reject(
                request_id=request_id,
                file_id=file_id,
                new_owner=self.wallet.address,
                wallet=self.wallet,
                message=reason
            )
            
            if self._submit_transaction(tx.to_dict()):
                print(f"[OWNERSHIP] Rejected ownership request: {request_id[:16]}...", flush=True)
                return True
            
            return False
            
        except Exception as e:
            print(f"[OWNERSHIP] Error rejecting transfer: {e}", flush=True)
            return False
    
    def cancel_request(self, request_id: str) -> bool:
        """
        Cancel an ownership transfer request (as current owner).
        
        Args:
            request_id: UUID of the ownership request
            
        Returns:
            True if cancelled successfully
        """
        try:
            request = self.get_request_details(request_id)
            if not request:
                return False
            
            if request.get("status") != "pending":
                return False
            
            if request.get("current_owner_address") != self.wallet.address:
                return False
            
            file_id = request.get("file_id")
            
            Transaction = self._get_transaction_class()
            
            tx = Transaction.make_ownership_cancel(
                request_id=request_id,
                file_id=file_id,
                current_owner=self.wallet.address,
                wallet=self.wallet
            )
            
            if self._submit_transaction(tx.to_dict()):
                print(f"[OWNERSHIP] Cancelled ownership request: {request_id[:16]}...", flush=True)
                return True
            
            return False
            
        except Exception as e:
            print(f"[OWNERSHIP] Error cancelling request: {e}", flush=True)
            return False
    
    def get_pending_requests(self) -> List[Dict]:
        """Get all pending ownership requests where current user is the new owner."""
        socket = self._get_chain_socket()
        if not socket:
            return []
        
        try:
            request = {
                "type": "GET_PENDING_OWNERSHIP_REQUESTS",
                "user_address": self.wallet.address
            }
            socket.send_json(request)
            response = socket.recv_json()
            
            if response.get("status_code") == 200:
                return response.get("requests", [])
            return []
                
        except Exception as e:
            print(f"[OWNERSHIP] Error getting pending requests: {e}", flush=True)
            return []
        finally:
            socket.close()
    
    def get_request_details(self, request_id: str) -> Optional[Dict]:
        """Get details of a specific ownership request."""
        socket = self._get_chain_socket()
        if not socket:
            return None
        
        try:
            request = {
                "type": "GET_OWNERSHIP_REQUEST",
                "request_id": request_id
            }
            socket.send_json(request)
            response = socket.recv_json()
            
            if response.get("status_code") == 200:
                return response.get("request")
            return None
                
        except Exception as e:
            print(f"[OWNERSHIP] Error getting request details: {e}", flush=True)
            return None
        finally:
            socket.close()
    
    def get_asset_owner(self, file_id: str) -> Optional[str]:
        """Get the current owner of a digital asset."""
        socket = self._get_chain_socket()
        if not socket:
            return None
        
        try:
            request = {
                "type": "GET_ASSET_OWNER",
                "file_id": file_id
            }
            socket.send_json(request)
            response = socket.recv_json()
            
            if response.get("status_code") == 200:
                return response.get("owner_address")
            return None
                
        except Exception as e:
            print(f"[OWNERSHIP] Error getting asset owner: {e}", flush=True)
            return None
        finally:
            socket.close()
    
    def get_ownership_history(self, file_id: str) -> List[Dict]:
        """Get ownership transfer history for an asset."""
        socket = self._get_chain_socket()
        if not socket:
            return []
        
        try:
            request = {
                "type": "GET_OWNERSHIP_HISTORY",
                "file_id": file_id
            }
            socket.send_json(request)
            response = socket.recv_json()
            
            if response.get("status_code") == 200:
                return response.get("history", [])
            return []
                
        except Exception as e:
            print(f"[OWNERSHIP] Error getting ownership history: {e}", flush=True)
            return []
        finally:
            socket.close()
