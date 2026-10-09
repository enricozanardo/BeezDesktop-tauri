use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::thread;

use flate2::read::GzDecoder;
use once_cell::sync::Lazy;
use serde_json::{json, Value};
use tar::Archive;

use crate::http;
use crate::paths::models_dir;

pub const PORT: u16 = 18080;
const HF_GGUF: &str =
    "https://huggingface.co/openbmb/MiniCPM5-2B-GGUF/resolve/main/MiniCPM5-2B-Q4_K_M.gguf";
const LLAMA_TAG: &str = "b9571";

struct DownloadState {
    active: bool,
    done: bool,
    error: Option<String>,
    bytes: u64,
    total: Option<u64>,
}

fn empty_state() -> DownloadState {
    DownloadState {
        active: false,
        done: false,
        error: None,
        bytes: 0,
        total: None,
    }
}

static DOWNLOAD: Lazy<Mutex<DownloadState>> = Lazy::new(|| Mutex::new(empty_state()));
static RUNTIME: Lazy<Mutex<DownloadState>> = Lazy::new(|| Mutex::new(empty_state()));
static SERVER: Lazy<Mutex<Option<std::process::Child>>> = Lazy::new(|| Mutex::new(None));

/// True while the llama-server process started by this app is still alive.
fn server_owned() -> bool {
    let mut guard = SERVER.lock().unwrap();
    match guard.as_mut().map(|c| c.try_wait()) {
        Some(Ok(None)) => true,
        Some(_) => {
            *guard = None;
            false
        }
        None => false,
    }
}

fn gguf_path() -> PathBuf {
    if let Ok(named) = std::env::var("BEEZ_MINICPM_GGUF") {
        return PathBuf::from(named);
    }
    models_dir().join("MiniCPM5-2B-Q4_K_M.gguf")
}

fn llama_names() -> &'static [&'static str] {
    if cfg!(windows) {
        &["llama-server.exe"]
    } else {
        &["llama-server"]
    }
}

fn find_named_binary(dir: &Path, names: &[&str]) -> Option<PathBuf> {
    let Ok(entries) = fs::read_dir(dir) else {
        return None;
    };
    for entry in entries.flatten() {
        let path = entry.path();
        if path.is_dir() {
            if let Some(found) = find_named_binary(&path, names) {
                return Some(found);
            }
        } else if let Some(name) = path.file_name().and_then(|s| s.to_str()) {
            if names.iter().any(|n| *n == name) {
                return Some(path);
            }
        }
    }
    None
}

fn llama_bin() -> Option<String> {
    let runtime = models_dir().join("llama-runtime");
    if let Some(p) = find_named_binary(&runtime, llama_names()) {
        return Some(p.display().to_string());
    }
    for name in llama_names() {
        let local = models_dir().join(name);
        if local.is_file() {
            return Some(local.display().to_string());
        }
    }
    which::which("llama-server")
        .ok()
        .map(|p| p.display().to_string())
}

fn snapshot(lock: &Lazy<Mutex<DownloadState>>) -> Value {
    match lock.lock().ok() {
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

fn runtime_asset() -> Result<(String, String), String> {
    let os = std::env::consts::OS;
    let arch = std::env::consts::ARCH;
    let name = match (os, arch) {
        ("macos", "aarch64") => format!("llama-{LLAMA_TAG}-bin-macos-arm64.tar.gz"),
        ("macos", "x86_64") => format!("llama-{LLAMA_TAG}-bin-macos-x64.tar.gz"),
        ("linux", "aarch64") => format!("llama-{LLAMA_TAG}-bin-ubuntu-arm64.tar.gz"),
        ("linux", _) => format!("llama-{LLAMA_TAG}-bin-ubuntu-x64.tar.gz"),
        ("windows", "aarch64") => format!("llama-{LLAMA_TAG}-bin-win-cpu-arm64.zip"),
        ("windows", _) => format!("llama-{LLAMA_TAG}-bin-win-cpu-x64.zip"),
        _ => return Err(format!("no llama.cpp build for {os}/{arch}")),
    };
    let url = format!(
        "https://github.com/ggml-org/llama.cpp/releases/download/{LLAMA_TAG}/{name}"
    );
    Ok((url, name))
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
        "llama_tag": LLAMA_TAG,
        "port": PORT,
        "running": running,
        "owned": server_owned(),
        "price_per_query": 0,
        "download_url": HF_GGUF,
        "download": snapshot(&DOWNLOAD),
        "runtime": snapshot(&RUNTIME),
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
            return json!({"ok": true, "started": false, "already_running": true, "download": snapshot(&DOWNLOAD)});
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

fn chmod_exec(path: &Path) {
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if let Ok(meta) = fs::metadata(path) {
            let mut p = meta.permissions();
            p.set_mode(p.mode() | 0o755);
            let _ = fs::set_permissions(path, p);
        }
    }
}

fn extract_tar_gz(archive: &Path, dest: &Path) -> Result<(), String> {
    let file = fs::File::open(archive).map_err(|e| e.to_string())?;
    let mut tar = Archive::new(GzDecoder::new(file));
    tar.unpack(dest).map_err(|e| e.to_string())
}

fn extract_zip(archive: &Path, dest: &Path) -> Result<(), String> {
    let file = fs::File::open(archive).map_err(|e| e.to_string())?;
    let mut zip = zip::ZipArchive::new(file).map_err(|e| e.to_string())?;
    for i in 0..zip.len() {
        let mut entry = zip.by_index(i).map_err(|e| e.to_string())?;
        let out = dest.join(entry.mangled_name());
        if entry.is_dir() {
            fs::create_dir_all(&out).map_err(|e| e.to_string())?;
            continue;
        }
        if let Some(parent) = out.parent() {
            fs::create_dir_all(parent).map_err(|e| e.to_string())?;
        }
        let mut outfile = fs::File::create(&out).map_err(|e| e.to_string())?;
        std::io::copy(&mut entry, &mut outfile).map_err(|e| e.to_string())?;
    }
    Ok(())
}

/// Download pinned llama.cpp binaries into the app models folder (background).
pub fn install_runtime() -> Value {
    if llama_bin().is_some() {
        return json!({
            "ok": true,
            "already_present": true,
            "llama_server": llama_bin(),
            "message": "llama-server is already available."
        });
    }
    {
        let mut st = match RUNTIME.lock() {
            Ok(g) => g,
            Err(e) => return json!({"ok": false, "error": e.to_string()}),
        };
        if st.active {
            return json!({"ok": true, "started": false, "already_running": true, "runtime": snapshot(&RUNTIME)});
        }
        st.active = true;
        st.done = false;
        st.error = None;
        st.bytes = 0;
        st.total = None;
    }
    thread::spawn(|| {
        let result = (|| -> Result<PathBuf, String> {
            let (url, name) = runtime_asset()?;
            let models = models_dir();
            fs::create_dir_all(&models).map_err(|e| e.to_string())?;
            let archive = models.join(&name);
            http::download_file_progress(&url, &archive, |bytes, total| {
                if let Ok(mut st) = RUNTIME.lock() {
                    st.bytes = bytes;
                    st.total = total;
                }
            })?;
            let dest = models.join("llama-runtime");
            let _ = fs::remove_dir_all(&dest);
            fs::create_dir_all(&dest).map_err(|e| e.to_string())?;
            if name.ends_with(".zip") {
                extract_zip(&archive, &dest)?;
            } else {
                extract_tar_gz(&archive, &dest)?;
            }
            let bin = find_named_binary(&dest, llama_names())
                .ok_or_else(|| "archive did not contain llama-server".to_string())?;
            chmod_exec(&bin);
            let _ = fs::remove_file(&archive);
            Ok(bin)
        })();
        if let Ok(mut st) = RUNTIME.lock() {
            st.active = false;
            match result {
                Ok(_) => {
                    st.done = true;
                    st.error = None;
                }
                Err(e) => {
                    st.done = false;
                    st.error = Some(e);
                }
            }
        }
    });
    json!({
        "ok": true,
        "started": true,
        "message": "Installing llama-server in the background. Keep the app open.",
        "tag": LLAMA_TAG,
    })
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
            "error": "llama-server not found. Use Install local runtime in Ask (no Homebrew required).",
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
    let child = std::process::Command::new(bin)
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
        .spawn();
    match child {
        Ok(c) => *SERVER.lock().unwrap() = Some(c),
        Err(e) => return json!({"ok": false, "error": e.to_string()}),
    }
    for _ in 0..30 {
        thread::sleep(std::time::Duration::from_secs(1));
        if !server_owned() {
            return json!({"ok": false, "error": "llama-server exited during startup", "log": log.display().to_string()});
        }
        let now = status();
        if now.get("running").and_then(|v| v.as_bool()) == Some(true) {
            return json!({"ok": true, "started": true, "status": now});
        }
    }
    json!({"ok": false, "error": "llama-server did not become ready", "log": log.display().to_string()})
}

/// Stop the llama-server process this app started.
pub fn stop_server() -> Value {
    let child = SERVER.lock().unwrap().take();
    match child {
        Some(mut c) => {
            let _ = c.kill();
            let _ = c.wait();
            json!({"ok": true, "stopped": true, "status": status()})
        }
        None if status()["running"] == true => json!({
            "ok": false,
            "error": format!("A llama-server on port {PORT} was started outside Beez Desktop; stop it there."),
        }),
        None => json!({"ok": true, "stopped": false, "status": status()}),
    }
}

/// Stop the server and delete the downloaded model and runtime so setup can start over.
pub fn reset() -> Value {
    if DOWNLOAD.lock().unwrap().active || RUNTIME.lock().unwrap().active {
        return json!({"ok": false, "error": "Wait for the running download to finish first."});
    }
    let stopped = stop_server();
    if stopped["ok"] != true {
        return stopped;
    }
    let models = models_dir();
    let mut removed = Vec::new();
    let gguf = gguf_path();
    if gguf.starts_with(&models) && gguf.is_file() {
        let _ = fs::remove_file(&gguf);
        removed.push(gguf.display().to_string());
    }
    let runtime = models.join("llama-runtime");
    if runtime.is_dir() {
        let _ = fs::remove_dir_all(&runtime);
        removed.push(runtime.display().to_string());
    }
    *DOWNLOAD.lock().unwrap() = empty_state();
    *RUNTIME.lock().unwrap() = empty_state();
    json!({"ok": true, "removed": removed, "status": status()})
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
