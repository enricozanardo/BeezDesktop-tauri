"""Local MiniCPM5-2B via llama.cpp OpenAI-compatible server."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

PORT = int(os.environ.get("BEEZ_MINICPM_PORT", "18080"))
HF_GGUF = os.environ.get(
    "BEEZ_MINICPM_GGUF_URL",
    "https://huggingface.co/openbmb/MiniCPM5-2B-GGUF/resolve/main/MiniCPM5-2B-Q4_K_M.gguf",
)


def _data_dir() -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    path = base / "BeezDesktopTwo" / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def gguf_path() -> Path:
    named = os.environ.get("BEEZ_MINICPM_GGUF")
    if named:
        return Path(named)
    return _data_dir() / "MiniCPM5-2B-Q4_K_M.gguf"


def llama_bin() -> Optional[str]:
    for name in ("llama-server", "llama-cli"):
        found = shutil.which(name)
        if found and name == "llama-server":
            return found
    return shutil.which("llama-server")


def status() -> Dict[str, Any]:
    """Report whether GGUF, llama-server, and the local HTTP endpoint exist."""
    path = gguf_path()
    binary = llama_bin()
    healthy = False
    if binary:
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=1)
            healthy = True
        except Exception:
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{PORT}/v1/models", timeout=1)
                healthy = True
            except Exception:
                healthy = False
    return {
        "ok": True,
        "node_id": "local_minicpm",
        "capabilities": ["generic", "coding"],
        "llm_backend": "minicpm_local",
        "modalities": ["text"],
        "gguf_path": str(path),
        "gguf_present": path.is_file() and path.stat().st_size > 1_000_000,
        "llama_server": binary,
        "port": PORT,
        "running": healthy,
        "price_per_query": 0,
        "download_url": HF_GGUF,
    }


def download_gguf() -> Dict[str, Any]:
    """Download the MiniCPM5-2B GGUF from Hugging Face into the data dir."""
    dest = gguf_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        req = urllib.request.Request(HF_GGUF, headers={"User-Agent": "BeezDesktopTwo"})
        with urllib.request.urlopen(req, timeout=120) as resp, open(tmp, "wb") as out:
            while True:
                chunk = resp.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
        tmp.replace(dest)
        return {"ok": True, "path": str(dest), "bytes": dest.stat().st_size}
    except Exception as exc:
        if tmp.exists():
            tmp.unlink()
        return {"ok": False, "error": f"download_failed: {exc}"}


def start_server() -> Dict[str, Any]:
    """Launch llama-server if GGUF and binary are present."""
    st = status()
    if st["running"]:
        return {"ok": True, "already_running": True, **st}
    if not st["gguf_present"]:
        return {
            "ok": False,
            "error": "MiniCPM GGUF is not installed. Use download_minicpm first.",
            **st,
        }
    if not st["llama_server"]:
        return {
            "ok": False,
            "error": "llama-server not found on PATH. Install llama.cpp.",
            **st,
        }
    log = _data_dir() / "llama-server.log"
    with open(log, "ab") as logf:
        subprocess.Popen(
            [
                st["llama_server"],
                "-m",
                st["gguf_path"],
                "--port",
                str(PORT),
                "--host",
                "127.0.0.1",
                "-c",
                "8192",
                "--jinja",
            ],
            stdout=logf,
            stderr=logf,
            start_new_session=True,
        )
    for _ in range(30):
        time.sleep(1)
        if status()["running"]:
            return {"ok": True, "started": True, **status()}
    return {"ok": False, "error": "llama-server did not become ready", "log": str(log)}


def chat(messages: List[Dict[str, str]], max_tokens: int = 512) -> Dict[str, Any]:
    """Call the local OpenAI-compatible MiniCPM endpoint. No dummy replies."""
    st = status()
    if not st["running"]:
        started = start_server()
        if not started.get("ok"):
            return started
    body = json.dumps({
        "model": "MiniCPM5-2B",
        "messages": messages,
        "temperature": 1.0,
        "top_p": 0.95,
        "max_tokens": max_tokens,
    }).encode()
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/v1/chat/completions",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode())
        content = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        return {"ok": True, "answer": content, "cost": 0, "sources": [], "raw": data}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "error": f"minicpm_http_{exc.code}: {exc.read()[:300]}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
