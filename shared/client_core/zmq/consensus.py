"""
Consensus Listener

Subscribes to Directory node consensus updates and maintains
the list of active nodes in the network.
"""

import zmq
import time
import json
import threading
from typing import List, Dict, Callable, Optional

from shared.client_core.state import ClientState, get_global_state


def get_directory_config() -> tuple:
    """
    Get directory nodes and consensus port from config.
    
    Returns:
        Tuple of (directory_ips, consensus_port)
    """
    try:
        from shared.beez_config import get_config
        config = get_config()
        directory_ips = config.get_directory_ips()
        consensus_port = str(config.zmq.consensus_port)
        return directory_ips, consensus_port
    except ImportError:
        # Fallback to default values
        return ["directory1", "directory2", "directory3"], "5557"


def subscribe_consensus(
    state: Optional[ClientState] = None,
    directory_ips: Optional[List[str]] = None,
    consensus_port: str = "5557",
    callback: Optional[Callable[[Dict], None]] = None
) -> None:
    """
    Subscribe to consensus updates from Directory nodes.
    
    This function runs in a loop, receiving consensus messages and updating
    the provided state object or the global state.
    
    Args:
        state: ClientState instance to update (uses global if None)
        directory_ips: List of Directory node IPs (uses config if None)
        consensus_port: ZMQ port for consensus PUB socket
        callback: Optional callback function called with consensus data
    """
    if state is None:
        state = get_global_state()
    
    if directory_ips is None:
        directory_ips, consensus_port = get_directory_config()
    
    context = zmq.Context.instance()
    consensus_subscriber = context.socket(zmq.SUB)
    
    for peer_ip in directory_ips:
        endpoint = f"tcp://{peer_ip}:{consensus_port}"
        consensus_subscriber.connect(endpoint)
    
    consensus_subscriber.setsockopt_string(zmq.SUBSCRIBE, "consensus")
    
    while True:
        try:
            message = consensus_subscriber.recv_string(flags=zmq.NOBLOCK)
            _, payload = message.split(" ", 1)
            consensus_data = json.loads(payload)
            
            # Update state from consensus
            state.update_from_consensus(consensus_data)
            
            # Call optional callback
            if callback:
                callback(consensus_data)
                
        except zmq.Again:
            time.sleep(1)
        except Exception as e:
            print(f"[CONSENSUS] Error: {e}", flush=True)
            time.sleep(1)


def start_consensus_listener(
    state: Optional[ClientState] = None,
    directory_ips: Optional[List[str]] = None,
    consensus_port: str = "5557",
    callback: Optional[Callable[[Dict], None]] = None,
    daemon: bool = True
) -> threading.Thread:
    """
    Start the consensus listener in a background thread.
    
    Args:
        state: ClientState instance to update
        directory_ips: List of Directory node IPs
        consensus_port: ZMQ port for consensus
        callback: Optional callback for consensus updates
        daemon: Run as daemon thread (default: True)
        
    Returns:
        The started thread
    """
    thread = threading.Thread(
        target=subscribe_consensus,
        args=(state, directory_ips, consensus_port, callback),
        daemon=daemon
    )
    thread.start()
    print("[CONSENSUS] Started consensus listener thread", flush=True)
    return thread
