use serde_json::{json, Value};

use crate::http;
use crate::nodes::chain_http_urls;
use crate::wallet_store::load_or_migrate;

fn first_chain_json(path: &str) -> Result<(String, Value), String> {
    let mut last = "no chain node reachable".to_string();
    for base in chain_http_urls() {
        match http::get_json_connect(&format!("{base}{path}"), 6, 900) {
            Ok(v) => return Ok((base, v)),
            Err(e) => last = format!("{base}: {e}"),
        }
    }
    Err(last)
}

pub fn blockchain_info() -> Value {
    match first_chain_json("/api/blockchain/info") {
        Ok((source, data)) => json!({"ok": true, "source": source, "data": data}),
        Err(e) => json!({"ok": false, "error": e}),
    }
}

pub fn recent_blocks() -> Value {
    match first_chain_json("/api/blockchain/blocks?limit=15&offset=0") {
        Ok((source, data)) => json!({"ok": true, "source": source, "data": data}),
        Err(e) => json!({"ok": false, "error": e}),
    }
}

pub fn wallet_ledger() -> Value {
    let wallet = match load_or_migrate() {
        Ok((Some(w), _)) => w,
        Ok((None, _)) => {
            return json!({"ok": true, "has_wallet": false, "balance": null});
        }
        Err(e) => return json!({"ok": false, "error": e}),
    };
    let mut last = "no chain node reachable".to_string();
    for base in chain_http_urls() {
        let bal_url = format!("{base}/balance?address={}", wallet.address);
        match http::get_json_connect(&bal_url, 6, 900) {
            Ok(bal) => {
                let txs = http::get_json_connect(
                    &format!(
                        "{base}/api/blockchain/wallet/{}/transactions?limit=30&offset=0",
                        wallet.address
                    ),
                    8,
                    900,
                )
                .unwrap_or(json!({}));
                return json!({
                    "ok": true,
                    "has_wallet": true,
                    "address": wallet.address,
                    "balance": bal.get("balance").cloned().unwrap_or(json!(null)),
                    "governance": bal.get("governance"),
                    "source": base,
                    "transactions": txs.get("transactions").cloned()
                        .or_else(|| txs.get("items").cloned())
                        .unwrap_or(json!([])),
                    "tx_payload": txs,
                });
            }
            Err(e) => last = format!("{base}: {e}"),
        }
    }
    json!({"ok": false, "has_wallet": true, "address": wallet.address, "error": last})
}
