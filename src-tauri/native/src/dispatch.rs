use serde_json::{json, Value};

use crate::chain;
use crate::chats;
use crate::embed;
use crate::files;
use crate::geo;
use crate::jobs;
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
        "wallet_history" => chain::wallet_history(&params),
        "send_transfer" => chain::send_transfer(&params),
        "history_reset" => chain::history_reset(),
        "list_smart_nodes" => list_smart_nodes(),
        "list_network_nodes" => list_all_nodes(),
        "network_map" => geo::network_map(),
        "job_start" => jobs::start(&params),
        "job_status" => jobs::status(&params),
        "jobs_list" => jobs::list(),
        "job_dismiss" => jobs::dismiss(&params),
        "rank_smart_nodes" => ops::rank_smart_nodes(&params),
        "chat" => ops::chat(&params),
        "index_file" => ops::index_file(&params),
        "index_estimate" => ops::index_estimate(&params),
        "workspace_stats" => ops::workspace_stats(&params),
        "chats_list" => chats::list(),
        "chats_save" => chats::save(&params),
        "chats_delete" => chats::delete(&params),
        "asset_upload" => files::upload(&params),
        "asset_upload_estimate" => files::estimate(&params),
        "asset_list" => files::list_mine(),
        "asset_download" => files::download(&params),
        "ownership_transfer" => files::ownership_transfer(&params),
        "ownership_pending" => files::ownership_pending(),
        "ownership_accept" => files::ownership_accept(&params),
        "ownership_seller_accept" => files::ownership_seller_accept(&params),
        "ownership_reject" => files::ownership_reject(&params),
        "ownership_cancel" => files::ownership_cancel(&params),
        "asset_purchase_request" => files::purchase_request(&params),
        "asset_set_listing" => files::set_listing(&params),
        "asset_marketplace" => files::marketplace(&params),
        "asset_preview" => files::preview(&params),
        "knowledge_search" => ops::knowledge_search(&params),
        "knowledge_query" => ops::knowledge_query(&params),
        "knowledge_publish" => ops::knowledge_publish(&params),
        "knowledge_purchase" => ops::knowledge_purchase(&params),
        "knowledge_mine" => ops::knowledge_mine(&params),
        "knowledge_update" => ops::knowledge_update(&params),
        "knowledge_delete" => ops::knowledge_delete(&params),
        "knowledge_seller_stats" => chain::knowledge_seller_stats(),
        "workspace_remove" => ops::workspace_remove(&params),
        "minicpm_status" => minicpm::status(),
        "minicpm_download" => minicpm::download_gguf(),
        "minicpm_install_runtime" => minicpm::install_runtime(),
        "minicpm_start" => minicpm::start_server(),
        "minicpm_stop" => minicpm::stop_server(),
        "minicpm_reset" => minicpm::reset(),
        "minicpm_chat" => minicpm::chat(params.get("messages").unwrap_or(&json!([])), 512),
        "blockchain_info" => chain::blockchain_info(),
        "recent_blocks" => chain::recent_blocks(),
        "blocks_page" => chain::blocks_page(&params),
        "block_detail" => chain::block_detail(&params),
        "transaction_detail" => chain::transaction_detail(&params),
        "explorer_search" => chain::explorer_search(&params),
        "explorer_wallet" => chain::explorer_wallet(&params),
        "embed_status" => embed::status(),
        "embed_ensure" => match embed::ensure() {
            Ok(()) => json!({"ok": true, "ready": true}),
            Err(e) => json!({"ok": false, "error": e}),
        },
        "" => json!({"ok": false, "error": "missing method"}),
        other => json!({"ok": false, "error": format!("unknown method {other}")}),
    }
}
