"""
BeezClient State Management

Provides a centralized state container for client applications.
Can be used as a singleton or instantiated per-session.
"""

from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field


@dataclass
class ClientState:
    """
    Centralized state container for client applications.
    
    This replaces the global state module pattern with an injectable
    state container that can be passed to services.
    """
    # Node lists from consensus
    active_nodes: List[Dict] = field(default_factory=list)
    chain_nodes: List[Dict] = field(default_factory=list)
    manager_nodes: List[Dict] = field(default_factory=list)
    smart_nodes: List[Dict] = field(default_factory=list)
    
    # Consensus data
    consensus: Dict = field(default_factory=dict)
    
    # Mempool (local cache)
    mempool: List[Dict] = field(default_factory=list)
    
    # DAM guardian selection (Phase 2)
    selected_guardian_dam_id: Optional[str] = None
    
    # Security
    SECRET_KEY: Optional[str] = None
    
    # Wallet state
    CURRENT_WALLET: Optional[Any] = None
    
    # Magister state
    IS_MAGISTER: bool = False
    MAGISTER_INFO: Optional[Dict] = None
    
    def update_from_consensus(self, consensus_data: Dict) -> None:
        """
        Update state from consensus message.
        
        Args:
            consensus_data: Consensus data from Directory nodes
        """
        self.consensus = consensus_data
        nodes = consensus_data.get("nodes", [])
        
        # Filter storage nodes - include all relevant fields
        self.active_nodes = [
            {
                "node_id": n["node_id"],
                "ip": n["ip"],
                "node_type": n["node_type"],
                "score": n.get("score", 0.5),
                "price_per_chunk": n.get("price_per_chunk", 1.0),
                "reputation": n.get("reputation", int(n.get("score", 0.5) * 100)),
                "lat": n.get("lat", 0.0),
                "lon": n.get("lon", 0.0),
                "network_type": n.get("network_type", "default"),
            }
            for n in nodes
            if n.get("node_type") == "storage" and not n.get("banned", False)
        ]
        
        # Filter chain nodes
        self.chain_nodes = [
            {"node_id": n["node_id"], "ip": n["ip"], "score": n.get("score", 0.5)}
            for n in nodes
            if n.get("node_type") == "chain" and not n.get("banned", False)
        ]
        
        # Filter DAM/manager nodes
        self.manager_nodes = [
            {"node_id": n["node_id"], "ip": n["ip"], "score": n.get("score", 0.5)}
            for n in nodes
            if n.get("node_type") == "manager" and not n.get("banned", False)
        ]
        
        # Filter smart nodes
        self.smart_nodes = [
            {
                "node_id": n["node_id"],
                "ip": n["ip"],
                "node_type": n["node_type"],
                "score": n.get("score", 0.5),
                "price_per_embedding": n.get("price_per_embedding", 0.5),
                "price_per_query": n.get("price_per_query", 1.0),
                "lat": n.get("lat", 0.0),
                "lon": n.get("lon", 0.0),
                "wallet_address": n.get("wallet_address", ""),
            }
            for n in nodes
            if n.get("node_type") == "smart" and not n.get("banned", False)
        ]
    
    def set_wallet(self, wallet: Any) -> None:
        """Set the current wallet."""
        self.CURRENT_WALLET = wallet
    
    def clear_wallet(self) -> None:
        """Clear the current wallet."""
        self.CURRENT_WALLET = None
        self.IS_MAGISTER = False
        self.MAGISTER_INFO = None


# Global singleton instance for backward compatibility
_global_state: Optional[ClientState] = None


def get_global_state() -> ClientState:
    """Get the global client state singleton."""
    global _global_state
    if _global_state is None:
        _global_state = ClientState()
    return _global_state


def reset_global_state() -> None:
    """Reset the global state (useful for testing)."""
    global _global_state
    _global_state = ClientState()
