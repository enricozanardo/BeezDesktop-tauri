use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Command, Stdio};

fn sidecar_script() -> PathBuf {
    let cwd = std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."));
    let candidates = [
        cwd.join("sidecar/beez_sidecar.py"),
        cwd.join("../sidecar/beez_sidecar.py"),
        cwd.join("../../sidecar/beez_sidecar.py"),
    ];
    for path in candidates {
        if path.exists() {
            return path;
        }
    }
    cwd.join("sidecar/beez_sidecar.py")
}

#[tauri::command]
fn app_version() -> String {
    env!("CARGO_PKG_VERSION").to_string()
}

#[tauri::command]
fn sidecar_call(payload: String) -> Result<String, String> {
    let script = sidecar_script();
    if !script.exists() {
        return Err(format!("sidecar missing at {}", script.display()));
    }
    let mut child = Command::new("python3")
        .arg(&script)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("failed to start python sidecar: {e}"))?;
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
        let mut err = String::new();
        if let Some(stderr) = child.stderr.as_mut() {
            let _ = BufReader::new(stderr).read_line(&mut err);
        }
        return Err(format!("sidecar exit {status}: {err}"));
    }
    Ok(line.trim().to_string())
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
