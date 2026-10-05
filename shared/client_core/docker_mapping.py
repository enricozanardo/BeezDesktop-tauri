"""
Docker Node Mapping

Maps Docker container names to host-accessible ports.
This allows BeezDesktop to communicate with nodes running in Docker
from the local Docker host (127.0.0.1 published compose ports).
"""

# Docker container name -> (host_ip, http_port, zmq_port)
# Based on docker-compose.yml port mappings
DOCKER_NODE_MAP = {
    # Directory nodes
    "directory1": ("127.0.0.1", 5001, 5565),
    "directory2": ("127.0.0.1", 5002, 5665),
    "directory3": ("127.0.0.1", 5003, 5725),
    
    # Chain nodes
    "chain1": ("127.0.0.1", 5000, 5555),
    "chain2": ("127.0.0.1", 5010, 5890),
    "chain3": ("127.0.0.1", 5011, 5896),
    
    # Storage nodes
    "storage1": ("127.0.0.1", 5005, 5578),
    "storage2": ("127.0.0.1", 5006, 5582),
    "storage3": ("127.0.0.1", 5007, 5586),
    "storage4": ("127.0.0.1", 5014, 5906),
    "storage5": ("127.0.0.1", 5015, 5910),
    "storage6": ("127.0.0.1", 5016, 5914),
    
    # DAM nodes
    "dam1": ("127.0.0.1", 5004, 5576),
    "dam2": ("127.0.0.1", 5012, 5902),
    "dam3": ("127.0.0.1", 5013, 5904),
    
    # Smart nodes
    "smart1": ("127.0.0.1", 5017, 5930),
    "smart2": ("127.0.0.1", 5018, 5932),
    "smart3": ("127.0.0.1", 5019, 5934),
}


def _is_public_ip_or_hostname(node_ip: str) -> bool:
    """Return True if node_ip looks like a real production IP or DNS name.

    Production hosts are routable IPv4 addresses (no leading 127., 192.168.,
    10., 172.16-31.) or fully-qualified domain names. We never want to remap
    those to docker-compose loopback ports.
    """
    import ipaddress
    try:
        ip = ipaddress.ip_address(node_ip)
    except ValueError:
        # Not a literal IP. Treat any string with a dot as a public hostname.
        return "." in node_ip
    return not (ip.is_loopback or ip.is_private)


def resolve_node_address(node_ip: str, use_zmq: bool = False) -> tuple:
    """
    Resolve a node IP/hostname to host-accessible address.

    Args:
        node_ip: Node IP or Docker container name (e.g., "chain1", "192.168.1.1")
        use_zmq: If True, return ZMQ port; otherwise HTTP port

    Returns:
        Tuple of (host_ip, port)
    """
    # SAFETY: For real production hosts, never remap to docker-compose ports.
    # Production smart/dam/storage/chain hosts publish their public IP via
    # consensus and serve on 5000 (HTTP) / 5555+ (ZMQ).
    if _is_public_ip_or_hostname(node_ip):
        return (node_ip, 5555 if use_zmq else 5000)

    # Check if it's a Docker container name
    node_key = node_ip.lower().replace("-", "").replace("_", "")

    if node_key in DOCKER_NODE_MAP:
        host_ip, http_port, zmq_port = DOCKER_NODE_MAP[node_key]
        return (host_ip, zmq_port if use_zmq else http_port)

    # Check partial matches (e.g., "chain_1_abc123" -> "chain1")
    for key in DOCKER_NODE_MAP:
        if key in node_key or node_key.startswith(key.replace("_", "")):
            host_ip, http_port, zmq_port = DOCKER_NODE_MAP[key]
            return (host_ip, zmq_port if use_zmq else http_port)

    # Check if node_ip contains a number that maps to a node type
    # e.g., "beezchain1" or "beez-chain-1" -> "chain1"
    import re
    for node_type in ["chain", "storage", "dam", "directory", "smart"]:
        match = re.search(rf'{node_type}[_\-]?(\d+)', node_key)
        if match:
            mapped_key = f"{node_type}{match.group(1)}"
            if mapped_key in DOCKER_NODE_MAP:
                host_ip, http_port, zmq_port = DOCKER_NODE_MAP[mapped_key]
                return (host_ip, zmq_port if use_zmq else http_port)

    # Not a Docker container - return as-is with default ports
    return (node_ip, 5555 if use_zmq else 5000)


def get_chain_node_http_url(node: dict) -> str:
    """
    Get HTTP URL for a chain node.
    
    Args:
        node: Node dict from consensus (has 'ip' field)
        
    Returns:
        HTTP URL like "http://127.0.0.1:5000"
    """
    node_ip = node.get("ip", "localhost")
    host_ip, port = resolve_node_address(node_ip, use_zmq=False)
    url = f"http://{host_ip}:{port}"
    print(f"[DOCKER_MAP] Node IP '{node_ip}' -> {url}", flush=True)
    return url
