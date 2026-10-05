#!/usr/bin/env python3
"""JSON-line sidecar for Beez Desktop Two.

Reads one JSON object from stdin (method + optional params) and prints one
JSON object to stdout.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


def _try_import_core():
    candidates = [
        Path.home() / "github" / "BeezMaster" / "BeezShared",
        Path("/home/fucina/github/BeezMaster/BeezShared"),
        HERE.parent / "shared",
        Path.home() / "github" / "BeezMaster" / "BeezDesktop" / "shared",
        Path("/home/fucina/github/BeezMaster/BeezDesktop/shared"),
        Path("/home/fucina/github/BeezMaster/BeezSmart/shared"),
    ]
    for root in candidates:
        if not root.exists():
            continue
        insert = str(root.parent if root.name == "shared" else root)
        if insert not in sys.path:
            sys.path.insert(0, insert)
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        try:
            from shared.client_core import BeezClientCore, Wallet  # type: ignore

            return BeezClientCore, Wallet
        except Exception:
            try:
                from client_core import BeezClientCore, Wallet  # type: ignore

                return BeezClientCore, Wallet
            except Exception:
                continue
    return None, None


def handle(msg: dict) -> dict:
    method = msg.get("method")
    params = msg.get("params") or {}
    if method == "ping":
        core, _wallet = _try_import_core()
        return {
            "ok": True,
            "sidecar": "beez_sidecar",
            "client_core": core is not None,
            "product": "Beez Desktop Two",
        }
    if method == "read_beez_config":
        path = Path.home() / ".beez"
        if not path.is_file():
            return {"ok": True, "exists": False, "text": ""}
        return {"ok": True, "exists": True, "text": path.read_text(encoding="utf-8")}
    try:
        import minicpm
        import ops
    except Exception as exc:
        return {"ok": False, "error": f"sidecar modules failed: {exc}"}
    dispatch = {
        "list_smart_nodes": lambda: ops.list_smart_nodes(),
        "rank_smart_nodes": lambda: ops.rank_smart_nodes(params),
        "chat": lambda: ops.chat(params),
        "index_file": lambda: ops.index_file(params),
        "workspace_stats": lambda: ops.workspace_stats(params),
        "knowledge_search": lambda: ops.knowledge_search(params),
        "knowledge_query": lambda: ops.knowledge_query(params),
        "knowledge_publish": lambda: ops.knowledge_publish(params),
        "knowledge_mine": lambda: ops.knowledge_mine(params),
        "minicpm_status": minicpm.status,
        "minicpm_download": minicpm.download_gguf,
        "minicpm_start": minicpm.start_server,
        "minicpm_chat": lambda: minicpm.chat(params.get("messages") or []),
    }
    fn = dispatch.get(method)
    if not fn:
        return {"ok": False, "error": f"unknown method {method}"}
    try:
        return fn()
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


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
    print(json.dumps(handle(msg), default=str), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
