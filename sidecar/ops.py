"""Sidecar operations: wallet, consensus smart list, index, chat, knowledge.

Standalone Beez Desktop Two — uses vendored shared/ and app name BeezDesktopTwo.
Optional one-time migration from legacy Toga BeezDesktop wallet storage.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from rank import infer_needed_capabilities, rank_nodes
import minicpm

# Own storage namespace (not Toga BeezDesktop).
APP_WALLET_NAME = "BeezDesktopTwo"
LEGACY_WALLET_NAME = "BeezDesktop"


def _import_shared():
    import sys

    here = Path(__file__).resolve().parent
    roots = [
        here.parent / "shared",
        here / "shared",
    ]
    for root in roots:
        if not root.exists():
            continue
        parent = str(root.parent if root.name == "shared" else root)
        for p in (parent, str(root)):
            if p not in sys.path:
                sys.path.insert(0, p)
        try:
            from shared.client_core.wallet_storage import WalletStorage
            from shared.client_core.wallet import Wallet, generate_mnemonic
            from shared.client_core.encryption import derive_encryption_key
            from shared.client_core.docker_mapping import (
                resolve_node_address,
                DOCKER_NODE_MAP,
            )
            from shared.client_core.smart_client import (
                SmartNodeClient,
                build_smart_index_tx,
                build_smart_query_tx,
            )
            from shared.client_core.knowledge_client import (
                KnowledgeMarketplaceClient,
                build_knowledge_query_tx,
                build_knowledge_publish_tx,
            )
            return {
                "WalletStorage": WalletStorage,
                "Wallet": Wallet,
                "generate_mnemonic": generate_mnemonic,
                "derive_encryption_key": derive_encryption_key,
                "resolve_node_address": resolve_node_address,
                "DOCKER_NODE_MAP": DOCKER_NODE_MAP,
                "SmartNodeClient": SmartNodeClient,
                "build_smart_index_tx": build_smart_index_tx,
                "build_smart_query_tx": build_smart_query_tx,
                "KnowledgeMarketplaceClient": KnowledgeMarketplaceClient,
                "build_knowledge_query_tx": build_knowledge_query_tx,
                "build_knowledge_publish_tx": build_knowledge_publish_tx,
            }
        except Exception:
            continue
    return None


SHARED = _import_shared()


def _storage(app_name: str = APP_WALLET_NAME):
    if not SHARED:
        raise RuntimeError(
            "client_core is not importable. Install sidecar/requirements.txt "
            "(python3 -m pip install -r sidecar/requirements.txt)."
        )
    return SHARED["WalletStorage"](app_name)


def _load_wallet_data() -> Optional[Dict[str, Any]]:
    """Load Two wallet; migrate once from legacy Toga storage if needed."""
    own = _storage(APP_WALLET_NAME)
    loaded = own.load_wallet()
    if loaded:
        return loaded
    legacy = _storage(LEGACY_WALLET_NAME)
    migrated = legacy.load_wallet()
    if not migrated:
        return None
    mnemonic = migrated.get("mnemonic") if isinstance(migrated, dict) else None
    address = migrated.get("address") if isinstance(migrated, dict) else None
    if not mnemonic:
        return None
    if not address:
        address = SHARED["Wallet"](mnemonic).address
    own.save_wallet(mnemonic, address)
    return {"mnemonic": mnemonic, "address": address, "migrated_from": LEGACY_WALLET_NAME}


def _wallet():
    loaded = _load_wallet_data()
    if not loaded:
        raise RuntimeError("No wallet yet. Create or import one in the Wallet page.")
    mnemonic = loaded.get("mnemonic") if isinstance(loaded, dict) else None
    if not mnemonic:
        raise RuntimeError("Wallet file has no mnemonic")
    return SHARED["Wallet"](mnemonic)


def _wallet_keys():
    wallet = _wallet()
    return (
        wallet.address,
        wallet.privkey.hex(),
        wallet.get_pubkey_bytes().hex(),
        wallet,
    )


def wallet_status() -> Dict[str, Any]:
    """Return whether a wallet is present and its address (never the mnemonic)."""
    if not SHARED:
        return {
            "ok": False,
            "error": "client_core is not importable",
            "has_wallet": False,
            "hint": "pip install -r sidecar/requirements.txt",
        }
    try:
        loaded = _load_wallet_data()
    except Exception as exc:
        return {"ok": False, "error": str(exc), "has_wallet": False}
    if not loaded:
        return {
            "ok": True,
            "has_wallet": False,
            "address": None,
            "storage": APP_WALLET_NAME,
        }
    address = loaded.get("address")
    if not address and loaded.get("mnemonic"):
        address = SHARED["Wallet"](loaded["mnemonic"]).address
    return {
        "ok": True,
        "has_wallet": True,
        "address": address,
        "storage": APP_WALLET_NAME,
        "migrated_from": loaded.get("migrated_from"),
    }


def wallet_create() -> Dict[str, Any]:
    """Generate a new 12-word wallet and persist it under BeezDesktopTwo."""
    if not SHARED:
        return {"ok": False, "error": "client_core is not importable"}
    if _storage(APP_WALLET_NAME).has_saved_wallet():
        return {
            "ok": False,
            "error": "A wallet already exists. Forget it first, or import over after forget.",
        }
    mnemonic = SHARED["generate_mnemonic"](128)
    wallet = SHARED["Wallet"](mnemonic)
    if not _storage(APP_WALLET_NAME).save_wallet(mnemonic, wallet.address):
        return {"ok": False, "error": "failed to save wallet"}
    return {
        "ok": True,
        "address": wallet.address,
        "mnemonic": mnemonic,
        "storage": APP_WALLET_NAME,
    }


def wallet_import(params: Dict[str, Any]) -> Dict[str, Any]:
    """Import a mnemonic (12/24 words) into BeezDesktopTwo storage."""
    if not SHARED:
        return {"ok": False, "error": "client_core is not importable"}
    mnemonic = (params.get("mnemonic") or "").strip()
    words = mnemonic.split()
    if len(words) not in (12, 24):
        return {"ok": False, "error": "mnemonic must be 12 or 24 words"}
    try:
        wallet = SHARED["Wallet"](mnemonic)
    except Exception as exc:
        return {"ok": False, "error": f"invalid mnemonic: {exc}"}
    if not _storage(APP_WALLET_NAME).save_wallet(mnemonic, wallet.address):
        return {"ok": False, "error": "failed to save wallet"}
    return {"ok": True, "address": wallet.address, "storage": APP_WALLET_NAME}


def wallet_forget() -> Dict[str, Any]:
    """Delete the BeezDesktopTwo wallet file (does not touch Toga storage)."""
    if not SHARED:
        return {"ok": False, "error": "client_core is not importable"}
    ok = _storage(APP_WALLET_NAME).delete_wallet()
    return {"ok": ok, "has_wallet": False, "storage": APP_WALLET_NAME}


def _directory_http_urls() -> List[str]:
    urls = []
    mapping = (SHARED or {}).get("DOCKER_NODE_MAP") or {}
    for name in ("directory1", "directory2", "directory3"):
        if name in mapping:
            host, port, _zmq = mapping[name]
            urls.append(f"http://{host}:{port}")
    beez = Path.home() / ".beez"
    if beez.is_file():
        text = beez.read_text(encoding="utf-8")
        for line in text.splitlines():
            if "http://" in line:
                part = line.strip().split()[-1].strip("\"'")
                if part.startswith("http"):
                    urls.append(part.rstrip("/"))
    # de-dupe
    out = []
    for u in urls:
        if u not in out:
            out.append(u)
    return out or ["http://127.0.0.1:5001", "http://127.0.0.1:5002", "http://127.0.0.1:5003"]


def _smart_url(node: Dict[str, Any]) -> str:
    if node.get("node_id") == "local_minicpm":
        return f"http://127.0.0.1:{minicpm.PORT}"
    ip = node.get("ip") or node.get("node_id") or "smart1"
    if SHARED:
        host, port = SHARED["resolve_node_address"](ip, use_zmq=False)
        return f"http://{host}:{port}"
    return f"http://{ip}:5000"


def _local_minicpm_node() -> Dict[str, Any]:
    st = minicpm.status()
    return {
        "node_id": "local_minicpm",
        "ip": "127.0.0.1",
        "node_type": "smart",
        "capabilities": ["generic", "coding"],
        "llm_backend": "minicpm_local",
        "modalities": ["text"],
        "models": ["MiniCPM5-2B"],
        "price_per_query": 0,
        "price_per_embedding": 0,
        "reputation": 100,
        "banned": False,
        "gguf_present": st.get("gguf_present"),
        "running": st.get("running"),
        "llama_server": st.get("llama_server"),
        "label": "Local MiniCPM (on-device)",
    }


def list_smart_nodes() -> Dict[str, Any]:
    """Fetch Directory /nodes and merge /info capabilities; always include MiniCPM."""
    nodes: List[Dict[str, Any]] = []
    errors = []
    for base in _directory_http_urls():
        try:
            resp = requests.get(f"{base}/nodes", timeout=4)
            resp.raise_for_status()
            payload = resp.json()
            raw = payload.get("nodes") if isinstance(payload, dict) else payload
            if isinstance(raw, list):
                nodes = [n for n in raw if isinstance(n, dict) and n.get("node_type") == "smart"]
                break
        except Exception as exc:
            errors.append(f"{base}: {exc}")
    if not nodes:
        for name in ("smart1", "smart2", "smart3"):
            try:
                if SHARED:
                    host, port = SHARED["resolve_node_address"](name, use_zmq=False)
                    url = f"http://{host}:{port}"
                else:
                    url = f"http://127.0.0.1:{5017 + int(name[-1]) - 1}"
                info = requests.get(f"{url}/info", timeout=3).json()
                info["ip"] = name
                info["node_type"] = "smart"
                nodes.append(info)
            except Exception as exc:
                errors.append(f"{name}: {exc}")
    merged = []
    for node in nodes:
        if node.get("banned"):
            continue
        try:
            info = requests.get(f"{_smart_url(node)}/info", timeout=3).json()
            node = {**node, **{k: info[k] for k in (
                "capabilities", "llm_backend", "modalities", "llm_model",
                "price_per_query", "price_per_embedding", "wallet_address", "node_id",
            ) if k in info}}
            if info.get("llm_model") and not node.get("models"):
                node["models"] = [info["llm_model"]]
        except Exception:
            node.setdefault("capabilities", ["generic"])
        merged.append(node)
    merged.append(_local_minicpm_node())
    return {"ok": True, "nodes": merged, "errors": errors}


def rank_smart_nodes(params: Dict[str, Any]) -> Dict[str, Any]:
    listed = list_smart_nodes()
    ranked = rank_nodes(
        listed.get("nodes") or [],
        params.get("prompt") or "",
        params.get("attachments") or [],
    )
    return {"ok": True, "needed": infer_needed_capabilities(
        params.get("prompt") or "", params.get("attachments") or []
    ), "nodes": ranked}


def _send_raw_tx(tx: Dict[str, Any]) -> Dict[str, Any]:
    if not SHARED:
        return {"ok": False, "error": "no client_core"}
    mapping = SHARED["DOCKER_NODE_MAP"]
    last = None
    for name in ("chain1", "chain2", "chain3"):
        if name not in mapping:
            continue
        host, port, _ = mapping[name]
        try:
            resp = requests.post(
                f"http://{host}:{port}/transactions",
                json=tx,
                timeout=10,
            )
            if resp.status_code == 200:
                return {"ok": True, "tx_hash": tx.get("tx_hash")}
            last = {"status": resp.status_code, "body": resp.text[:400]}
        except Exception as exc:
            last = {"error": str(exc)}
    return {"ok": False, "error": last}


def index_file(params: Dict[str, Any]) -> Dict[str, Any]:
    """Extract text, embed, POST /index, optional smart_index TX."""
    if not SHARED:
        return {"ok": False, "error": "client_core is not importable"}
    path = Path(params.get("path") or "")
    if not path.is_file():
        return {"ok": False, "error": f"file not found: {path}"}
    node = params.get("node") or {}
    if node.get("node_id") == "local_minicpm":
        return {"ok": False, "error": "Local MiniCPM does not index network workspaces"}
    text = _read_text(path)
    if not text.strip():
        return {"ok": False, "error": "no extractable text"}
    address, priv, pub, wallet = _wallet_keys()
    key = SHARED["derive_encryption_key"](wallet)
    client = SHARED["SmartNodeClient"](_smart_url(node))
    file_id = params.get("file_id") or str(uuid.uuid4())
    result = client.index_file(
        file_id=file_id,
        file_name=path.name,
        plaintext_content=text,
        encryption_key=key,
        wallet_address=address,
    )
    tx_info = None
    try:
        info = client.get_info()
        tx = SHARED["build_smart_index_tx"](
            wallet_address=address,
            file_id=file_id,
            smart_node_id=info.get("node_id") or node.get("node_id") or "",
            smart_node_wallet=info.get("wallet_address") or node.get("wallet_address") or "",
            num_chunks_indexed=int(result.get("chunks_indexed") or 0),
            total_cost=float(result.get("total_cost") or 0),
            private_key_hex=priv,
            public_key_hex=pub,
        )
        tx_info = _send_raw_tx(tx)
        if tx_info.get("ok"):
            result["tx_hash"] = tx["tx_hash"]
    except Exception as exc:
        tx_info = {"ok": False, "error": str(exc)}
    return {"ok": True, "file_id": file_id, "result": result, "tx": tx_info}


def _read_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        import fitz
        parts = []
        with fitz.open(str(path)) as doc:
            for i, page in enumerate(doc):
                t = page.get_text("text")
                if t.strip():
                    parts.append(f"[Page {i + 1}]\n{t}")
        return "\n\n".join(parts)
    return path.read_text(encoding="utf-8", errors="replace")


def chat(params: Dict[str, Any]) -> Dict[str, Any]:
    """Network RAG chat or local MiniCPM."""
    messages = params.get("messages") or []
    node = params.get("node") or {}
    if node.get("node_id") == "local_minicpm" or params.get("backend") == "minicpm_local":
        result = minicpm.chat(messages)
        if not result.get("ok"):
            return result
        return {
            "ok": True,
            "answer": result.get("answer"),
            "sources": [],
            "cost": 0,
            "verification": None,
            "local": True,
        }
    if not SHARED:
        return {"ok": False, "error": "client_core is not importable"}
    address, priv, pub, wallet = _wallet_keys()
    key = SHARED["derive_encryption_key"](wallet)
    client = SHARED["SmartNodeClient"](_smart_url(node), timeout=180)
    if hasattr(client, "chat"):
        result = client.chat(
            messages=messages,
            decryption_key=key,
            wallet_address=address,
            file_ids=params.get("file_ids"),
            top_k=int(params.get("top_k") or 5),
            thread_id=params.get("thread_id"),
        )
    else:
        last = next(m["content"] for m in reversed(messages) if m.get("role") == "user")
        result = client.query(
            query_text=last,
            decryption_key=key,
            wallet_address=address,
            file_ids=params.get("file_ids"),
            top_k=int(params.get("top_k") or 5),
        )
    try:
        info = client.get_info()
        last = next(m["content"] for m in reversed(messages) if m.get("role") == "user")
        import hashlib
        query_hash = result.get("query_hash") or hashlib.sha256(last.encode()).hexdigest()
        file_ids = [s.get("file_id") for s in result.get("sources") or [] if s.get("file_id")]
        tx = SHARED["build_smart_query_tx"](
            wallet_address=address,
            query_hash=query_hash,
            answer_hash=result.get("answer_hash") or "",
            smart_node_id=info.get("node_id") or node.get("node_id") or "",
            smart_node_wallet=info.get("wallet_address") or node.get("wallet_address") or "",
            cost=float(result.get("cost") or 0),
            file_ids=list(set(file_ids)),
            private_key_hex=priv,
            public_key_hex=pub,
        )
        tx_info = _send_raw_tx(tx)
        if tx_info.get("ok"):
            result["tx_hash"] = tx["tx_hash"]
        result["tx"] = tx_info
    except Exception as exc:
        result["tx"] = {"ok": False, "error": str(exc)}
    return {"ok": True, **result}


def workspace_stats(params: Dict[str, Any]) -> Dict[str, Any]:
    if not SHARED:
        return {"ok": False, "error": "client_core is not importable"}
    node = params.get("node") or {}
    address = _wallet().address
    client = SHARED["SmartNodeClient"](_smart_url(node), timeout=8)
    return {"ok": True, **client.get_workspace_stats(address)}


def knowledge_search(params: Dict[str, Any]) -> Dict[str, Any]:
    if not SHARED:
        return {"ok": False, "error": "client_core is not importable"}
    node = params.get("node") or {}
    client = SHARED["KnowledgeMarketplaceClient"](_smart_url(node), timeout=12)
    listings = client.search_marketplace(
        query=params.get("query") or "",
        tags=params.get("tags"),
        limit=int(params.get("limit") or 20),
    )
    return {"ok": True, "listings": listings}


def knowledge_query(params: Dict[str, Any]) -> Dict[str, Any]:
    if not SHARED:
        return {"ok": False, "error": "client_core is not importable"}
    from shared.client_core.embedding import EmbeddingEngine
    node = params.get("node") or {}
    address, priv, pub, _wallet_obj = _wallet_keys()
    client = SHARED["KnowledgeMarketplaceClient"](_smart_url(node), timeout=120)
    text = params.get("query_text") or ""
    vector = EmbeddingEngine().embed_query(text)
    result = client.query_listing(
        listing_id=params["listing_id"],
        query_text=text,
        query_vector=vector,
        buyer_address=address,
    )
    try:
        listing = client.get_listing(params["listing_id"]) or {}
        info = requests.get(f"{_smart_url(node)}/info", timeout=5).json()
        tx = SHARED["build_knowledge_query_tx"](
            buyer_address=address,
            seller_address=listing.get("seller_address") or "",
            listing_id=params["listing_id"],
            query_hash=result.get("query_hash") or "",
            answer_hash=result.get("answer_hash") or "",
            cost=float(result.get("cost") or 0),
            smart_node_id=info.get("node_id") or node.get("node_id") or "",
            smart_node_wallet=info.get("wallet_address") or node.get("wallet_address") or "",
            private_key_hex=priv,
            public_key_hex=pub,
        )
        tx_info = _send_raw_tx(tx)
        if tx_info.get("ok"):
            result["tx_hash"] = tx["tx_hash"]
        result["tx"] = tx_info
    except Exception as exc:
        result["tx"] = {"ok": False, "error": str(exc)}
    return {"ok": True, **result}


def knowledge_publish(params: Dict[str, Any]) -> Dict[str, Any]:
    if not SHARED:
        return {"ok": False, "error": "client_core is not importable"}
    node = params.get("node") or {}
    address, priv, pub, wallet = _wallet_keys()
    key = SHARED["derive_encryption_key"](wallet)
    client = SHARED["KnowledgeMarketplaceClient"](_smart_url(node), timeout=30)
    result = client.publish_listing(
        seller_address=address,
        title=params.get("title") or "Untitled",
        description=params.get("description") or "",
        tags=params.get("tags") or [],
        price_per_query=float(params.get("price_per_query") or 1),
        purchase_price=float(params.get("purchase_price") or 0),
        file_ids=params.get("file_ids") or [],
        marketplace_key=key,
    )
    try:
        info = requests.get(f"{_smart_url(node)}/info", timeout=5).json()
        tx = SHARED["build_knowledge_publish_tx"](
            seller_address=address,
            listing_id=result.get("listing_id") or "",
            smart_node_id=info.get("node_id") or node.get("node_id") or "",
            title=params.get("title") or "Untitled",
            file_count=int(result.get("total_files") or len(params.get("file_ids") or [])),
            chunk_count=int(result.get("total_chunks") or 0),
            price_per_query=float(params.get("price_per_query") or 1),
            purchase_price=float(params.get("purchase_price") or 0),
            private_key_hex=priv,
            public_key_hex=pub,
        )
        tx_info = _send_raw_tx(tx)
        if tx_info.get("ok"):
            result["tx_hash"] = tx["tx_hash"]
        result["tx"] = tx_info
    except Exception as exc:
        result["tx"] = {"ok": False, "error": str(exc)}
    return {"ok": True, **result}


def knowledge_mine(params: Dict[str, Any]) -> Dict[str, Any]:
    if not SHARED:
        return {"ok": False, "error": "client_core is not importable"}
    node = params.get("node") or {}
    address = _wallet().address
    client = SHARED["KnowledgeMarketplaceClient"](_smart_url(node), timeout=12)
    return {"ok": True, "listings": client.get_my_listings(address)}
