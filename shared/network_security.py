"""
Shared network security middleware for all Beez node types.

Provides:
- Request filtering: drops non-HTTP garbage (TLS probes, SSH, RDP scanners)
- Network authentication: validates X-Network-Token on inter-node routes
- Rate limiting helper for external-facing endpoints
"""

import os
import time
import threading
from functools import wraps
from flask import request, jsonify, abort

BEEZ_NETWORK_SECRET = os.getenv("BEEZ_NETWORK_SECRET", "")

# Inter-node endpoints that REQUIRE X-Network-Token.
# Everything else (client-facing APIs, health checks) is open.
PROTECTED_PREFIXES = (
    "/join_command",
    "/broadcast_join",
    "/migrate_chunk",
    "/chunk-management",
    "/api/dam/",
    "/api/postgres/",
    "/api/sync/",
    "/escrows/",
    "/submit_guardian_update",
)

# Specific paths to whitelist even when their prefix is protected. Used for
# read-only liveness probes that the desktop client must hit without
# possessing the network secret. Keep this list MINIMAL - any endpoint here
# is exposed to the internet on prod nodes.
PUBLIC_OVERRIDES = (
    "/api/postgres/health",
)

_rate_limit_lock = threading.Lock()
_rate_limit_cache: dict[str, list] = {}
RATE_LIMIT_PER_MINUTE = int(os.getenv("API_RATE_LIMIT_PER_MINUTE", "120"))


def _is_binary_garbage(data: bytes) -> bool:
    """Detect TLS ClientHello, SSH banners, RDP cookies, and other non-HTTP probes."""
    if not data:
        return False
    if data[:3] in (b"\x16\x03\x01", b"\x16\x03\x03", b"\x16\x03\x02"):
        return True
    if data.startswith(b"SSH-"):
        return True
    if b"mstshash=" in data[:64]:
        return True
    if data[0:1] == b"\x03" and b"Cookie:" in data[:48]:
        return True
    return False


def _check_rate_limit(client_ip: str) -> bool:
    """Returns True if the request should be allowed."""
    now = time.time()
    window_start = now - 60

    with _rate_limit_lock:
        timestamps = _rate_limit_cache.get(client_ip, [])
        timestamps = [t for t in timestamps if t > window_start]

        if len(timestamps) >= RATE_LIMIT_PER_MINUTE:
            _rate_limit_cache[client_ip] = timestamps
            return False

        timestamps.append(now)
        _rate_limit_cache[client_ip] = timestamps
        return True


def init_network_security(app, node_type: str = "unknown"):
    """Register before_request hooks on the Flask app.

    Args:
        app: Flask application instance
        node_type: e.g. "chain", "storage", "dam", "directory", "smart"
    """

    @app.before_request
    def _security_filter():
        try:
            raw = request.get_data(cache=True, as_text=False)
        except Exception:
            raw = b""

        if _is_binary_garbage(raw):
            abort(400)

        if not _check_rate_limit(request.remote_addr):
            return jsonify({"error": "rate limit exceeded"}), 429

        if not BEEZ_NETWORK_SECRET:
            return None

        path = request.path
        if path in PUBLIC_OVERRIDES:
            return None
        if any(path.startswith(p) for p in PROTECTED_PREFIXES):
            token = request.headers.get("X-Network-Token", "")
            if token != BEEZ_NETWORK_SECRET:
                abort(403)

        return None


def get_network_headers() -> dict:
    """Return headers dict with X-Network-Token for outgoing inter-node requests."""
    if BEEZ_NETWORK_SECRET:
        return {"X-Network-Token": BEEZ_NETWORK_SECRET}
    return {}


def authenticated_request(method: str, url: str, **kwargs):
    """Wrapper around requests that automatically injects network auth headers.

    Args:
        method: HTTP method ("get", "post", "put", etc.)
        url: Target URL
        **kwargs: Additional arguments passed to requests.request()

    Returns:
        requests.Response
    """
    import requests as _requests

    headers = kwargs.pop("headers", {}) or {}
    headers.update(get_network_headers())
    kwargs["headers"] = headers

    return _requests.request(method, url, **kwargs)
