use std::fs;
use std::sync::Mutex;
use std::thread;

use once_cell::sync::Lazy;
use serde_json::{json, Value};

use crate::http;
use crate::paths::models_dir;

pub const PORT: u16 = 18080;
const HF_GGUF: &str =
    "https://huggingface.co/openbmb/MiniCPM5-2B-GGUF/resolve/main/MiniCPM5-2B-Q4_K_M.gguf";

struct DownloadState {
    active: bool,
    done: bool,
    error: Option<String>,
    bytes: u64,
    total: Option<u64>,
}

static DOWNLOAD: Lazy<Mutex<DownloadState>> = Lazy::new(|| {
    Mutex::new(DownloadState {
        active: false,
        done: false,
        error: None,
        bytes: 0,
        total: None,
    })
});

fn gguf_path() -> std::path::PathBuf {
    if let Ok(named) = std::env::var("BEEZ_MINICPM_GGUF") {
        return std::path::PathBuf::from(named);
    }
    models_dir().join("MiniCPM5-2B-Q4_K_M.gguf")
}

fn llama_bin() -> Option<String> {
    which::which("llama-server")
        .ok()
        .map(|p| p.display().to_string())
        .or_else(|| {
            let name = if cfg!(windows) {
                "llama-server.exe"
            } else {
                "llama-server"
            };
            let local = models_dir().join(name);
            local.is_file().then(|| local.display().to_string())
        })
}

fn download_snapshot() -> Value {
    let st = DOWNLOAD.lock().ok();
    match st {
        Some(s) => json!({
            "active": s.active,
            "done": s.done,
            "error": s.error,
            "bytes": s.bytes,
            "total": s.total,
        }),
        None => json!({}),
    }
}

pub fn status() -> Value {
    let path = gguf_path();
    let binary = llama_bin();
    let running = http::get_ok(&format!("http://127.0.0.1:{PORT}/health"), 1)
        || http::get_ok(&format!("http://127.0.0.1:{PORT}/v1/models"), 1);
    let present = path.is_file() && path.metadata().map(|m| m.len() > 1_000_000).unwrap_or(false);
    json!({
        "ok": true,
        "node_id": "local_minicpm",
        "capabilities": ["generic", "coding"],
        "llm_backend": "minicpm_local",
        "modalities": ["text"],
        "gguf_path": path.display().to_string(),
        "gguf_present": present,
        "llama_server": binary,
        "port": PORT,
        "running": running,
        "price_per_query": 0,
        "download_url": HF_GGUF,
        "download": download_snapshot(),
    })
}

pub fn local_node() -> Value {
    let st = status();
    json!({
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
        "banned": false,
        "gguf_present": st.get("gguf_present"),
        "running": st.get("running"),
        "llama_server": st.get("llama_server"),
        "label": "Local MiniCPM (on-device)",
    })
}

/// Start a background GGUF download and return immediately (does not freeze the UI).
pub fn download_gguf() -> Value {
    {
        let mut st = match DOWNLOAD.lock() {
            Ok(g) => g,
            Err(e) => return json!({"ok": false, "error": e.to_string()}),
        };
        if st.active {
            return json!({"ok": true, "started": false, "already_running": true, "download": download_snapshot()});
        }
        let dest = gguf_path();
        if dest.is_file() && dest.metadata().map(|m| m.len() > 1_000_000).unwrap_or(false) {
            st.done = true;
            st.bytes = dest.metadata().map(|m| m.len()).unwrap_or(0);
            return json!({"ok": true, "already_present": true, "path": dest.display().to_string(), "bytes": st.bytes});
        }
        st.active = true;
        st.done = false;
        st.error = None;
        st.bytes = 0;
        st.total = None;
    }
    thread::spawn(|| {
        let dest = gguf_path();
        let result = http::download_file_progress(HF_GGUF, &dest, |bytes, total| {
            if let Ok(mut st) = DOWNLOAD.lock() {
                st.bytes = bytes;
                st.total = total;
            }
        });
        if let Ok(mut st) = DOWNLOAD.lock() {
            st.active = false;
            match result {
                Ok(n) => {
                    st.done = true;
                    st.bytes = n;
                    st.error = None;
                }
                Err(e) => {
                    st.done = false;
                    st.error = Some(e);
                }
            }
        }
    });
    json!({"ok": true, "started": true, "message": "Download started in the background. Keep the app open."})
}

pub fn start_server() -> Value {
    let st = status();
    if st.get("running").and_then(|v| v.as_bool()) == Some(true) {
        return json!({"ok": true, "already_running": true, "status": st});
    }
    if st.get("gguf_present").and_then(|v| v.as_bool()) != Some(true) {
        return json!({
            "ok": false,
            "error": "MiniCPM GGUF is not installed. Use Download model in Ask.",
            "status": st
        });
    }
    let Some(bin) = st
        .get("llama_server")
        .and_then(|v| v.as_str())
        .filter(|s| !s.is_empty())
    else {
        return json!({
            "ok": false,
            "error": "llama-server not found. Place a llama-server binary in the app models folder or on PATH.",
            "status": st
        });
    };
    let gguf = st.get("gguf_path").and_then(|v| v.as_str()).unwrap_or("");
    let log = models_dir().join("llama-server.log");
    let logf = match fs::OpenOptions::new().create(true).append(true).open(&log) {
        Ok(f) => f,
        Err(e) => return json!({"ok": false, "error": e.to_string()}),
    };
    let errf = match logf.try_clone() {
        Ok(f) => f,
        Err(e) => return json!({"ok": false, "error": e.to_string()}),
    };
    if let Err(e) = std::process::Command::new(bin)
        .args([
            "-m",
            gguf,
            "--port",
            &PORT.to_string(),
            "--host",
            "127.0.0.1",
            "-c",
            "8192",
            "--jinja",
        ])
        .stdout(std::process::Stdio::from(logf))
        .stderr(std::process::Stdio::from(errf))
        .spawn()
    {
        return json!({"ok": false, "error": e.to_string()});
    }
    for _ in 0..30 {
        thread::sleep(std::time::Duration::from_secs(1));
        let now = status();
        if now.get("running").and_then(|v| v.as_bool()) == Some(true) {
            return json!({"ok": true, "started": true, "status": now});
        }
    }
    json!({"ok": false, "error": "llama-server did not become ready", "log": log.display().to_string()})
}

pub fn chat(messages: &Value, max_tokens: u32) -> Value {
    let st = status();
    if st.get("running").and_then(|v| v.as_bool()) != Some(true) {
        let started = start_server();
        if started.get("ok") != Some(&json!(true)) {
            return started;
        }
    }
    let body = json!({
        "model": "MiniCPM5-2B",
        "messages": messages,
        "temperature": 1.0,
        "top_p": 0.95,
        "max_tokens": max_tokens,
    });
    match http::post_json(
        &format!("http://127.0.0.1:{PORT}/v1/chat/completions"),
        &body,
        180,
    ) {
        Ok((200, data, _)) => {
            let content = data
                .pointer("/choices/0/message/content")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            json!({"ok": true, "answer": content, "cost": 0, "sources": [], "raw": data})
        }
        Ok((code, _, text)) => json!({
            "ok": false,
            "error": format!("minicpm_http_{code}: {}", text.chars().take(300).collect::<String>())
        }),
        Err(e) => json!({"ok": false, "error": e}),
    }
}
