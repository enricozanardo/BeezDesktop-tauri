use serde_json::{json, Value};

use crate::paths::{data_dir, APP_WALLET_NAME};
use crate::wallet_store::load_or_migrate;

fn chats_path() -> std::path::PathBuf {
    let addr = load_or_migrate()
        .ok()
        .and_then(|(w, _)| w.map(|w| w.address))
        .unwrap_or_else(|| "anon".into());
    let safe: String = addr
        .chars()
        .map(|c| if c.is_ascii_alphanumeric() { c } else { '_' })
        .collect();
    data_dir(APP_WALLET_NAME).join("chats").join(format!("{safe}.json"))
}

fn load_store() -> Value {
    let path = chats_path();
    if let Ok(text) = std::fs::read_to_string(&path) {
        if let Ok(v) = serde_json::from_str::<Value>(&text) {
            return v;
        }
    }
    json!({"conversations": []})
}

fn save_store(store: &Value) -> Result<(), String> {
    let path = chats_path();
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    std::fs::write(path, serde_json::to_string_pretty(store).map_err(|e| e.to_string())?)
        .map_err(|e| e.to_string())
}

pub fn list() -> Value {
    let store = load_store();
    json!({"ok": true, "conversations": store.get("conversations").cloned().unwrap_or(json!([]))})
}

pub fn save(params: &Value) -> Value {
    let conv = params.get("conversation").cloned().unwrap_or(json!({}));
    let id = conv
        .get("id")
        .and_then(|v| v.as_str())
        .map(|s| s.to_string())
        .unwrap_or_else(|| uuid::Uuid::new_v4().to_string());
    let mut store = load_store();
    let mut list = store
        .get("conversations")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    let mut found = false;
    for item in list.iter_mut() {
        if item.get("id").and_then(|v| v.as_str()) == Some(id.as_str()) {
            *item = conv.clone();
            if let Some(obj) = item.as_object_mut() {
                obj.insert("id".into(), json!(id.clone()));
            }
            found = true;
            break;
        }
    }
    if !found {
        let mut item = conv;
        if let Some(obj) = item.as_object_mut() {
            obj.insert("id".into(), json!(id.clone()));
        }
        list.insert(0, item);
    }
    if let Some(obj) = store.as_object_mut() {
        obj.insert("conversations".into(), json!(list));
    }
    match save_store(&store) {
        Ok(()) => json!({"ok": true, "id": id}),
        Err(e) => json!({"ok": false, "error": e}),
    }
}

pub fn delete(params: &Value) -> Value {
    let id = params.get("id").and_then(|v| v.as_str()).unwrap_or("");
    let mut store = load_store();
    let list: Vec<Value> = store
        .get("conversations")
        .and_then(|v| v.as_array())
        .map(|a| {
            a.iter()
                .filter(|c| c.get("id").and_then(|v| v.as_str()) != Some(id))
                .cloned()
                .collect()
        })
        .unwrap_or_default();
    if let Some(obj) = store.as_object_mut() {
        obj.insert("conversations".into(), json!(list));
    }
    match save_store(&store) {
        Ok(()) => json!({"ok": true}),
        Err(e) => json!({"ok": false, "error": e}),
    }
}
