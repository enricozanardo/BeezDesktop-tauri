use serde_json::{json, Value};
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use tauri::path::BaseDirectory;
use tauri::{AppHandle, Manager};

fn home_dir() -> PathBuf {
    std::env::var_os("USERPROFILE")
        .or_else(|| std::env::var_os("HOME"))
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."))
}

fn native_handle(method: &str) -> Option<Value> {
    match method {
        "ping" => Some(json!({
            "ok": true,
            "sidecar": "native",
            "client_core": false,
        })),
        "read_beez_config" => {
            let path = home_dir().join(".beez");
            if path.is_file() {
                let text = std::fs::read_to_string(&path).unwrap_or_default();
                Some(json!({ "ok": true, "exists": true, "text": text }))
            } else {
                Some(json!({ "ok": true, "exists": false, "text": "" }))
            }
        }
        _ => None,
    }
}

fn sidecar_script(app: &AppHandle) -> PathBuf {
    for rel in ["sidecar/beez_sidecar.py", "beez_sidecar.py"] {
        if let Ok(path) = app.path().resolve(rel, BaseDirectory::Resource) {
            if path.exists() {
                return path;
            }
        }
    }
    if let Ok(path) = app.path().resource_dir() {
        let bundled = path.join("sidecar").join("beez_sidecar.py");
        if bundled.exists() {
            return bundled;
        }
        let flat = path.join("beez_sidecar.py");
        if flat.exists() {
            return flat;
        }
    }
    let cwd = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
    for candidate in [
        cwd.join("sidecar/beez_sidecar.py"),
        cwd.join("../sidecar/beez_sidecar.py"),
        cwd.join("../../sidecar/beez_sidecar.py"),
    ] {
        if candidate.exists() {
            return candidate;
        }
    }
    cwd.join("sidecar/beez_sidecar.py")
}

fn python_commands() -> &'static [&'static str] {
    if cfg!(windows) {
        &["python", "py", "python3"]
    } else {
        &["python3", "python"]
    }
}

fn run_python_sidecar(script: &Path, payload: &str) -> Result<String, String> {
    let mut last_err = String::from("no Python interpreter found");
    for cmd in python_commands() {
        let mut command = Command::new(cmd);
        if *cmd == "py" {
            command.arg("-3");
        }
        let spawned = command
            .arg(script)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn();
        let mut child = match spawned {
            Ok(child) => child,
            Err(err) => {
                last_err = format!("{cmd}: {err}");
                continue;
            }
        };
        {
            let mut stdin = child.stdin.take().ok_or("sidecar stdin closed")?;
            writeln!(stdin, "{payload}").map_err(|e| e.to_string())?;
        }
        let stdout = child.stdout.take().ok_or("sidecar stdout closed")?;
        let mut line = String::new();
        BufReader::new(stdout)
            .read_line(&mut line)
            .map_err(|e| e.to_string())?;
        let status = child.wait().map_err(|e| e.to_string())?;
        if !status.success() {
            last_err = format!("{cmd} exited {status}");
            continue;
        }
        return Ok(line.trim().to_string());
    }
    Err(last_err)
}

#[tauri::command]
fn app_version() -> String {
    env!("CARGO_PKG_VERSION").to_string()
}

#[tauri::command]
fn sidecar_call(app: AppHandle, payload: String) -> Result<String, String> {
    let msg: Value = serde_json::from_str(&payload).unwrap_or_else(|_| json!({}));
    let method = msg.get("method").and_then(Value::as_str).unwrap_or("");
    if let Some(reply) = native_handle(method) {
        return Ok(reply.to_string());
    }
    let script = sidecar_script(&app);
    if !script.exists() {
        return Ok(json!({
            "ok": false,
            "error": format!(
                "method {method:?} needs the Python sidecar, which is not available on this install"
            )
        })
        .to_string());
    }
    run_python_sidecar(&script, &payload)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![app_version, sidecar_call])
        .run(tauri::generate_context!())
        .expect("error while building tauri application");
}
