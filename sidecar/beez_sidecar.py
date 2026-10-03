#!/usr/bin/env python3
"""JSON-line sidecar for BeezDesktop Tauri.

Reads one JSON object from stdin (method + optional params) and prints one
JSON object to stdout. Wallet/AES-256-GCM/ECDH/ZMQ stay in client_core;
this process only brokers calls.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _shared_roots() -> list[Path]:
    here = Path(__file__).resolve().parent
    return [
        here.parent / "shared",
        Path.home() / "github" / "BeezMaster" / "BeezShared",
        Path.home() / "github" / "BeezMaster" / "BeezDesktop" / "shared",
    ]


def _try_import_core():
    for root in _shared_roots():
        if (root / "client_core").is_dir():
            sys.path.insert(0, str(root.parent if root.name == "shared" else root))
            try:
                from client_core import BeezClientCore, Wallet  # type: ignore

                return BeezClientCore, Wallet
            except Exception:
                try:
                    from shared.client_core import BeezClientCore, Wallet  # type: ignore

                    return BeezClientCore, Wallet
                except Exception:
                    continue
    return None, None


def handle(msg: dict) -> dict:
    method = msg.get("method")
    if method == "ping":
        core, _wallet = _try_import_core()
        return {
            "ok": True,
            "sidecar": "beez_sidecar",
            "client_core": core is not None,
        }
    if method == "read_beez_config":
        path = Path.home() / ".beez"
        if not path.is_file():
            return {"ok": True, "exists": False, "text": ""}
        return {"ok": True, "exists": True, "text": path.read_text(encoding="utf-8")}
    return {"ok": False, "error": f"unknown method {method}"}


def main() -> int:
    raw = sys.stdin.readline()
    if not raw.strip():
        print(json.dumps({"ok": False, "error": "empty stdin"}))
        return 1
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    print(json.dumps(handle(msg)), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
