"""Framework-agnostic client_core for Beez Desktop Two.

Imports are lazy so missing optional deps (fastembed, pymupdf) do not block
wallet create / status.
"""

from __future__ import annotations

__all__ = [
    "BeezClientCore",
    "ClientState",
    "Wallet",
    "generate_mnemonic",
    "mnemonic_to_privkey",
    "privkey_to_address",
    "sign_message",
    "verify_signature",
]


def __getattr__(name: str):
    if name in (
        "Wallet",
        "generate_mnemonic",
        "mnemonic_to_privkey",
        "privkey_to_address",
        "sign_message",
        "verify_signature",
    ):
        from shared.client_core import wallet as _wallet

        return getattr(_wallet, name)
    if name == "ClientState":
        from shared.client_core.state import ClientState

        return ClientState
    if name == "BeezClientCore":
        from shared.client_core.client import BeezClientCore

        return BeezClientCore
    raise AttributeError(name)
