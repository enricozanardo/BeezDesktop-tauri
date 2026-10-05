"""
Node Registration

Utilities for registering client nodes with the Directory.
"""

import os
import random
import requests
from typing import Optional, Dict, List


def get_directory_nodes() -> Dict[str, str]:
    """
    Get directory nodes from config with fallback.
    
    Returns:
        Dictionary mapping node names to IPs
    """
    try:
        from shared.beez_config import get_config
        config = get_config()
        nodes = {}
        for i, ip in enumerate(config.get_directory_ips(), 1):
            nodes[f"DIRECTORY_{i}"] = ip
        return nodes
    except ImportError:
        return {
            "DIRECTORY_1": "directory1",
            "DIRECTORY_2": "directory2",
            "DIRECTORY_3": "directory3"
        }


def register_client_node(
    node_type: str = "client",
    node_ip: Optional[str] = None,
    directory_nodes: Optional[Dict[str, str]] = None,
    timeout: int = 10
) -> Optional[requests.Response]:
    """
    Register a client node with a Directory node.
    
    Args:
        node_type: Type of node (default: "client")
        node_ip: IP address of this node (uses NODE_IP env var if None)
        directory_nodes: Dict of directory nodes (uses config if None)
        timeout: Request timeout in seconds
        
    Returns:
        Response object if successful, None otherwise
    """
    if directory_nodes is None:
        directory_nodes = get_directory_nodes()
    
    if node_ip is None:
        node_ip = os.getenv("NODE_IP")
    
    if not node_ip:
        print("[REGISTER] Error: NODE_IP not defined", flush=True)
        return None
    
    directory_url = random.choice(list(directory_nodes.values()))
    
    payload = {
        "node_type": node_type,
        "ip": node_ip
    }
    
    try:
        response = requests.post(
            f"http://{directory_url}:5000/join_command",
            json=payload,
            timeout=timeout
        )
        
        if response.status_code == 200:
            print(f"[REGISTER] Successfully registered as {node_type}", flush=True)
            return response
        else:
            print(f"[REGISTER] Failed: {response.status_code} - {response.text}", flush=True)
            return None
            
    except requests.RequestException as e:
        print(f"[REGISTER] Connection error: {e}", flush=True)
        return None
