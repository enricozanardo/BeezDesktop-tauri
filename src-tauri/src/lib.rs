use serde_json::json;

#[tauri::command]
fn app_version() -> String {
    env!("CARGO_PKG_VERSION").to_string()
}

#[tauri::command]
fn sidecar_call(payload: String) -> Result<String, String> {
    let reply = beez_native::handle(&payload);
    serde_json::to_string(&reply).map_err(|e| e.to_string())
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

#[allow(dead_code)]
fn native_error(msg: impl Into<String>) -> String {
    json!({"ok": false, "error": msg.into()}).to_string()
}
