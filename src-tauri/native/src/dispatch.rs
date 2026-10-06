use serde_json::{json, Value};

use crate::chain;
use crate::embed;
use crate::minicpm;
use crate::nodes::{list_all_nodes, list_smart_nodes};
use crate::ops;

pub fn handle(payload: &str) -> Value {
    let msg: Value = serde_json::from_str(payload).unwrap_or(json!({}));
    let method = msg.get("method").and_then(|v| v.as_str()).unwrap_or("");
    let params = msg.get("params").cloned().unwrap_or(json!({}));
    match method {
        "ping" => ops::ping(),
        "read_beez_config" => ops::read_beez_config(),
        "wallet_status" => ops::wallet_status(),
        "wallet_create" => ops::wallet_create(),
        "wallet_import" => ops::wallet_import(&params),
        "wallet_forget" => ops::wallet_forget(),
        "wallet_ledger" => chain::wallet_ledger(),
        "list_smart_nodes" => list_smart_nodes(),
        "list_network_nodes" => list_all_nodes(),
        "rank_smart_nodes" => ops::rank_smart_nodes(&params),
        "chat" => ops::chat(&params),
        "index_file" => ops::index_file(&params),
        "workspace_stats" => ops::workspace_stats(&params),
        "knowledge_search" => ops::knowledge_search(&params),
        "knowledge_query" => ops::knowledge_query(&params),
        "knowledge_publish" => ops::knowledge_publish(&params),
        "knowledge_mine" => ops::knowledge_mine(&params),
        "minicpm_status" => minicpm::status(),
        "minicpm_download" => minicpm::download_gguf(),
        "minicpm_start" => minicpm::start_server(),
        "minicpm_chat" => minicpm::chat(params.get("messages").unwrap_or(&json!([])), 512),
        "blockchain_info" => chain::blockchain_info(),
        "recent_blocks" => chain::recent_blocks(),
        "embed_status" => embed::status(),
        "embed_ensure" => match embed::ensure() {
            Ok(()) => json!({"ok": true, "ready": true}),
            Err(e) => json!({"ok": false, "error": e}),
        },
        "" => json!({"ok": false, "error": "missing method"}),
        other => json!({"ok": false, "error": format!("unknown method {other}")}),
    }
}
