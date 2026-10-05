"""
Transaction Status Listener

Subscribes to transaction status updates from chain nodes.
"""

import zmq
import json
import threading
from typing import List, Callable, Optional


def subscribe_tx_status(
    chain_ips: List[str],
    port: str = "5556",
    callback: Optional[Callable[[dict], None]] = None
) -> None:
    """
    Subscribe to transaction status updates from chain nodes.
    
    Args:
        chain_ips: List of chain node IPs to subscribe to
        port: ZMQ PUB port for transaction status
        callback: Optional callback function called with each status update
    """
    ctx = zmq.Context.instance()
    sub = ctx.socket(zmq.SUB)
    sub.setsockopt_string(zmq.SUBSCRIBE, "chain_tx_status")
    
    for ip in chain_ips:
        sub.connect(f"tcp://{ip}:{port}")
    
    while True:
        try:
            topic, payload = sub.recv_multipart()
            msg = json.loads(payload)
            
            if callback:
                callback(msg)
                
        except Exception as e:
            print(f"[TX_STATUS] Error: {e}", flush=True)


def start_tx_status_listener(
    chain_ips: List[str],
    port: str = "5556",
    callback: Optional[Callable[[dict], None]] = None,
    daemon: bool = True
) -> threading.Thread:
    """
    Start transaction status listener in a background thread.
    
    Args:
        chain_ips: List of chain node IPs
        port: ZMQ port for status updates
        callback: Callback for status updates
        daemon: Run as daemon thread
        
    Returns:
        The started thread
    """
    thread = threading.Thread(
        target=subscribe_tx_status,
        args=(chain_ips, port, callback),
        daemon=daemon
    )
    thread.start()
    print("[TX_STATUS] Started transaction status listener", flush=True)
    return thread
