"""Shared helper to resolve a Flask SECRET_KEY safely.

Production rule: every Flask app MUST be configured with a real secret loaded
from the environment. We refuse to boot with the legacy "supersecretkey" /
"smart-secret-key" placeholders. In dev mode (BEEZ_ENV=dev) we fall back to a
random per-process secret so local hacking still works without ceremony.
"""
from __future__ import annotations

import os
import secrets

_INSECURE_PLACEHOLDERS = {
    "supersecretkey",
    "smart-secret-key",
    "change_me",
    "change_me_dam_secret_key",
    "",
}


class InsecureFlaskSecret(RuntimeError):
    """Raised when running in production without a real Flask secret."""


def resolve_flask_secret(node_type: str) -> str:
    """Return a cryptographically strong Flask SECRET_KEY.

    Lookup order (first non-placeholder wins):
      1. ``FLASK_SECRET_KEY`` env var
      2. ``BEEZ_FLASK_SECRET`` env var
      3. ``BEEZ_NETWORK_SECRET`` env var (acceptable as a strong shared secret)

    In production (``BEEZ_ENV=prod`` or unset), missing / placeholder values
    raise :class:`InsecureFlaskSecret`.  In dev (``BEEZ_ENV=dev``) we fall
    back to a random ``secrets.token_hex(32)`` and warn loudly.
    """
    candidates = (
        os.getenv("FLASK_SECRET_KEY"),
        os.getenv("BEEZ_FLASK_SECRET"),
        os.getenv("BEEZ_NETWORK_SECRET"),
    )
    for candidate in candidates:
        if candidate and candidate.strip().lower() not in _INSECURE_PLACEHOLDERS and len(candidate) >= 16:
            return candidate

    env = os.getenv("BEEZ_ENV", "prod").lower()
    if env in ("dev", "development", "test"):
        random_secret = secrets.token_hex(32)
        print(
            f"[SECURITY] {node_type}: no Flask secret in env (BEEZ_ENV={env}); "
            f"using ephemeral random secret. Set FLASK_SECRET_KEY for stable sessions.",
            flush=True,
        )
        return random_secret

    raise InsecureFlaskSecret(
        f"{node_type} refuses to start: FLASK_SECRET_KEY (or BEEZ_FLASK_SECRET / "
        "BEEZ_NETWORK_SECRET) must be set to a non-placeholder value of at least "
        "16 characters in production. Set BEEZ_ENV=dev to allow ephemeral secrets."
    )


__all__ = ["resolve_flask_secret", "InsecureFlaskSecret"]
