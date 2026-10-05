"""
BeezClient ZeroMQ Communication Module

Provides network communication utilities for client applications:
- Consensus subscription from Directory nodes
- Transaction status updates
- Node registration
"""

from shared.client_core.zmq.consensus import (
    subscribe_consensus,
    start_consensus_listener,
)
from shared.client_core.zmq.tx_status import (
    start_tx_status_listener,
)
from shared.client_core.zmq.register import (
    register_client_node,
)

__all__ = [
    "subscribe_consensus",
    "start_consensus_listener",
    "start_tx_status_listener",
    "register_client_node",
]
