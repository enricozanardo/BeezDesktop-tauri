use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use once_cell::sync::Lazy;
use serde_json::{json, Value};

use crate::http;
use crate::nodes::chain_http_urls;
use crate::paths::{data_dir, APP_WALLET_NAME};
use crate::tx::{build_transfer_tx, send_raw_tx};
use crate::wallet_store::{load_or_migrate, require_wallet};

const HISTORY_PAGE: u64 = 200;
const BLOCK_PAGE_MAX: u64 = 100;

static HISTORY_SYNCING: AtomicBool = AtomicBool::new(false);
static HISTORY_ERROR: Lazy<Mutex<Option<String>>> = Lazy::new(|| Mutex::new(None));
static LAST_SYNC: Lazy<Mutex<Option<(String, Instant)>>> = Lazy::new(|| Mutex::new(None));
const SYNC_INTERVAL: Duration = Duration::from_secs(20);

fn first_chain_json(path: &str) -> Result<(String, Value), String> {
    first_chain_json_timeout(path, 6)
}

fn first_chain_json_timeout(path: &str, timeout_secs: u64) -> Result<(String, Value), String> {
    let mut last = "no chain node reachable".to_string();
    for base in chain_http_urls() {
        match http::get_json_connect(&format!("{base}{path}"), timeout_secs, 900) {
            Ok(v) => return Ok((base, v)),
            Err(e) => last = format!("{base}: {e}"),
        }
    }
    Err(last)
}

fn wrap(res: Result<(String, Value), String>) -> Value {
    match res {
        Ok((source, data)) => json!({"ok": true, "source": source, "data": data}),
        Err(e) => json!({"ok": false, "error": e}),
    }
}

pub fn blockchain_info() -> Value {
    wrap(first_chain_json("/api/blockchain/info"))
}

pub fn recent_blocks() -> Value {
    wrap(first_chain_json("/api/blockchain/blocks?limit=15&offset=0"))
}

/// Page of blocks, newest first.
pub fn blocks_page(params: &Value) -> Value {
    let limit = params.get("limit").and_then(|v| v.as_u64()).unwrap_or(20).clamp(1, BLOCK_PAGE_MAX);
    let offset = params.get("offset").and_then(|v| v.as_u64()).unwrap_or(0);
    wrap(first_chain_json(&format!("/api/blockchain/blocks?limit={limit}&offset={offset}")))
}

/// Full block (with transactions) by height or hash.
pub fn block_detail(params: &Value) -> Value {
    if let Some(h) = params.get("height").and_then(|v| v.as_u64()) {
        return wrap(first_chain_json(&format!("/api/blockchain/block/{h}")));
    }
    match params.get("hash").and_then(|v| v.as_str()).map(str::trim) {
        Some(hash) if is_hex64(hash) => wrap(first_chain_json(&format!("/api/blockchain/block/hash/{hash}"))),
        _ => json!({"ok": false, "error": "Give a block height or a 64-character block hash."}),
    }
}

/// Mined (or pending) transaction by hash.
pub fn transaction_detail(params: &Value) -> Value {
    let hash = params.get("hash").and_then(|v| v.as_str()).unwrap_or("").trim();
    if !is_hex64(hash) {
        return json!({"ok": false, "error": "A transaction hash has 64 hexadecimal characters."});
    }
    if let Ok((source, data)) = first_chain_json(&format!("/api/blockchain/transaction/{hash}")) {
        return json!({"ok": true, "source": source, "status": "confirmed", "transaction": data.get("transaction")});
    }
    match first_chain_json(&format!("/api/mempool/transaction/{hash}")) {
        Ok((source, data)) if data["found"] == true => json!({
            "ok": true,
            "source": source,
            "status": "pending",
            "transaction": data["transaction"],
        }),
        _ => json!({"ok": false, "error": "No block or pending transaction has this hash."}),
    }
}

/// Resolve a free-text explorer query into a block, transaction or wallet.
pub fn explorer_search(params: &Value) -> Value {
    let q = params.get("query").and_then(|v| v.as_str()).unwrap_or("").trim();
    if q.is_empty() {
        return json!({"ok": false, "error": "Type a block height, a hash or a bez… address."});
    }
    if let Ok(h) = q.parse::<u64>() {
        let r = block_detail(&json!({"height": h}));
        return if r["ok"] == true {
            json!({"ok": true, "kind": "block", "height": h})
        } else {
            json!({"ok": false, "error": format!("No block at height {h}.")})
        };
    }
    if is_hex64(q) {
        if let Ok((_, data)) = first_chain_json(&format!("/api/blockchain/block/hash/{q}")) {
            let height = data.pointer("/block/header/height").cloned().unwrap_or(json!(null));
            return json!({"ok": true, "kind": "block", "height": height});
        }
        let tx = transaction_detail(&json!({"hash": q}));
        if tx["ok"] == true {
            return json!({"ok": true, "kind": "transaction", "hash": q});
        }
        return json!({"ok": false, "error": "No block or transaction has this hash."});
    }
    if q.starts_with("bez") && q.len() >= 20 {
        return json!({"ok": true, "kind": "wallet", "address": q});
    }
    json!({"ok": false, "error": "Not a block height, a 64-character hash or a bez… address."})
}

/// Recent transactions of any wallet (explorer view, not cached).
pub fn explorer_wallet(params: &Value) -> Value {
    let address = params.get("address").and_then(|v| v.as_str()).unwrap_or("").trim();
    if !address.starts_with("bez") {
        return json!({"ok": false, "error": "Not a bez… address."});
    }
    let limit = params.get("limit").and_then(|v| v.as_u64()).unwrap_or(50).clamp(1, 200);
    let offset = params.get("offset").and_then(|v| v.as_u64()).unwrap_or(0);
    wrap(first_chain_json_timeout(
        &format!("/api/blockchain/wallet/{address}/transactions?limit={limit}&offset={offset}"),
        120,
    ))
}

fn is_hex64(s: &str) -> bool {
    s.len() == 64 && s.chars().all(|c| c.is_ascii_hexdigit())
}

pub fn knowledge_seller_stats() -> Value {
    let wallet = match load_or_migrate() {
        Ok((Some(w), _)) => w,
        Ok((None, _)) => return json!({"ok": false, "error": "Create a wallet first."}),
        Err(e) => return json!({"ok": false, "error": e}),
    };
    match first_chain_json(&format!("/api/knowledge/seller/{}/stats", wallet.address)) {
        Ok((source, data)) => json!({
            "ok": true,
            "source": source,
            "listings": data.get("listings").cloned().unwrap_or(json!([])),
            "totals": data.get("totals").cloned().unwrap_or(json!({})),
        }),
        Err(e) => json!({"ok": false, "error": e}),
    }
}

fn history_path(address: &str) -> PathBuf {
    data_dir(APP_WALLET_NAME).join("history").join(format!("{address}.json"))
}

fn load_history(address: &str) -> Value {
    std::fs::read_to_string(history_path(address))
        .ok()
        .and_then(|s| serde_json::from_str::<Value>(&s).ok())
        .filter(|v| v.get("transactions").map(Value::is_array).unwrap_or(false))
        .unwrap_or_else(|| json!({"synced_height": null, "transactions": []}))
}

fn save_history(address: &str, cache: &Value) -> Result<(), String> {
    let path = history_path(address);
    if let Some(dir) = path.parent() {
        std::fs::create_dir_all(dir).map_err(|e| e.to_string())?;
    }
    let tmp = path.with_extension("tmp");
    std::fs::write(&tmp, serde_json::to_vec(cache).map_err(|e| e.to_string())?).map_err(|e| e.to_string())?;
    std::fs::rename(&tmp, &path).map_err(|e| e.to_string())
}

/// Merge newly mined entries into the cache, newest block first.
fn merge_history(cache: &mut Value, fresh: Vec<Value>, chain_height: u64) {
    let mut txs: Vec<Value> = cache["transactions"].as_array().cloned().unwrap_or_default();
    for t in fresh {
        let hash = t.get("tx_hash").and_then(|v| v.as_str()).unwrap_or("");
        if hash.is_empty() || txs.iter().any(|o| o.get("tx_hash").and_then(|v| v.as_str()) == Some(hash)) {
            continue;
        }
        txs.push(t);
    }
    txs.sort_by_key(|t| std::cmp::Reverse(t.get("block_height").and_then(|v| v.as_u64()).unwrap_or(0)));
    cache["transactions"] = json!(txs);
    cache["synced_height"] = json!(chain_height);
}

fn sync_history(address: &str) -> Result<(), String> {
    let mut cache = load_history(address);
    let since = cache["synced_height"].as_u64().map(|h| h + 1).unwrap_or(0);
    let mut fresh = Vec::new();
    let mut offset = 0;
    let mut chain_height = None;
    loop {
        let path = format!(
            "/api/blockchain/wallet/{address}/transactions?limit={HISTORY_PAGE}&offset={offset}&since_height={since}"
        );
        let (_, page) = first_chain_json_timeout(&path, 180)?;
        if chain_height.is_none() {
            chain_height = page.get("chain_height").and_then(|v| v.as_u64());
        }
        let items = page.get("transactions").and_then(|v| v.as_array()).cloned().unwrap_or_default();
        let n = items.len() as u64;
        fresh.extend(items);
        if n < HISTORY_PAGE {
            break;
        }
        offset += HISTORY_PAGE;
    }
    let Some(height) = chain_height else {
        return Err("chain did not report its height".into());
    };
    merge_history(&mut cache, fresh, height);
    save_history(address, &cache)
}

fn spawn_history_sync(address: String) {
    {
        let last = LAST_SYNC.lock().unwrap();
        if matches!(&*last, Some((a, at)) if *a == address && at.elapsed() < SYNC_INTERVAL) {
            return;
        }
    }
    if HISTORY_SYNCING.swap(true, Ordering::SeqCst) {
        return;
    }
    std::thread::spawn(move || {
        let res = sync_history(&address);
        *HISTORY_ERROR.lock().unwrap() = res.err();
        *LAST_SYNC.lock().unwrap() = Some((address, Instant::now()));
        HISTORY_SYNCING.store(false, Ordering::SeqCst);
    });
}

fn history_matches(t: &Value, kind: &str, q: &str) -> bool {
    let dir = t.get("direction").and_then(|v| v.as_str()).unwrap_or("");
    let ok_kind = match kind {
        "sent" => dir == "sent",
        "received" => dir == "received",
        "messages" => t.get("memo").and_then(|v| v.as_str()).map(|m| !m.is_empty()).unwrap_or(false),
        _ => true,
    };
    if !ok_kind {
        return false;
    }
    if q.is_empty() {
        return true;
    }
    ["tx_hash", "type", "counterparty", "memo", "file_name"]
        .iter()
        .filter_map(|k| t.get(*k).and_then(|v| v.as_str()))
        .any(|s| s.to_lowercase().contains(q))
}

/// Delete the cached history of the current wallet; the next sync rebuilds it from the chain.
pub fn history_reset() -> Value {
    let wallet = match require_wallet() {
        Ok(w) => w,
        Err(e) => return json!({"ok": false, "error": e}),
    };
    if HISTORY_SYNCING.load(Ordering::SeqCst) {
        return json!({"ok": false, "error": "A history sync is running; try again in a few seconds."});
    }
    let path = history_path(&wallet.address);
    if path.is_file() {
        if let Err(e) = std::fs::remove_file(&path) {
            return json!({"ok": false, "error": e.to_string()});
        }
    }
    *LAST_SYNC.lock().unwrap() = None;
    json!({"ok": true, "path": path.display().to_string()})
}

/// Filtered page of the locally cached history (kicks off a background sync).
pub fn wallet_history(params: &Value) -> Value {
    let wallet = match require_wallet() {
        Ok(w) => w,
        Err(e) => return json!({"ok": false, "error": e}),
    };
    spawn_history_sync(wallet.address.clone());
    let cache = load_history(&wallet.address);
    let kind = params.get("kind").and_then(|v| v.as_str()).unwrap_or("all");
    let q = params.get("query").and_then(|v| v.as_str()).unwrap_or("").trim().to_lowercase();
    let limit = params.get("limit").and_then(|v| v.as_u64()).unwrap_or(20).clamp(1, 200) as usize;
    let offset = params.get("offset").and_then(|v| v.as_u64()).unwrap_or(0) as usize;
    let all = cache["transactions"].as_array().cloned().unwrap_or_default();
    let matching: Vec<&Value> = all.iter().filter(|t| history_matches(t, kind, &q)).collect();
    json!({
        "ok": true,
        "address": wallet.address,
        "total": matching.len(),
        "transactions": matching.into_iter().skip(offset).take(limit).collect::<Vec<_>>(),
        "synced_height": cache["synced_height"],
        "syncing": HISTORY_SYNCING.load(Ordering::SeqCst),
        "sync_error": HISTORY_ERROR.lock().unwrap().clone(),
    })
}

/// Balance, pending mempool entries and the newest cached history entries.
pub fn wallet_ledger() -> Value {
    let wallet = match load_or_migrate() {
        Ok((Some(w), _)) => w,
        Ok((None, _)) => {
            return json!({"ok": true, "has_wallet": false, "balance": null});
        }
        Err(e) => return json!({"ok": false, "error": e}),
    };
    spawn_history_sync(wallet.address.clone());
    let cache = load_history(&wallet.address);
    let recent: Vec<Value> = cache["transactions"].as_array().cloned().unwrap_or_default().into_iter().take(30).collect();
    let mut last = "no chain node reachable".to_string();
    for base in chain_http_urls() {
        let bal_url = format!("{base}/balance?address={}", wallet.address);
        match http::get_json_connect(&bal_url, 6, 900) {
            Ok(bal) => {
                let pending = http::get_json_connect(
                    &format!("{base}/api/mempool/transactions?address={}&limit=50", wallet.address),
                    6,
                    900,
                )
                .ok()
                .and_then(|v| v.get("pending_transactions").cloned())
                .unwrap_or(json!([]));
                return json!({
                    "pending": pending,
                    "ok": true,
                    "has_wallet": true,
                    "address": wallet.address,
                    "balance": bal.get("balance").cloned().unwrap_or(json!(null)),
                    "governance": bal.get("governance"),
                    "source": base,
                    "transactions": recent,
                    "synced_height": cache["synced_height"],
                    "syncing": HISTORY_SYNCING.load(Ordering::SeqCst),
                });
            }
            Err(e) => last = format!("{base}: {e}"),
        }
    }
    json!({"ok": false, "has_wallet": true, "address": wallet.address, "error": last, "transactions": recent})
}

/// Send BZT and/or a text message to another wallet.
pub fn send_transfer(params: &Value) -> Value {
    let wallet = match require_wallet() {
        Ok(w) => w,
        Err(e) => return json!({"ok": false, "error": e}),
    };
    let recipient = params.get("recipient").and_then(|v| v.as_str()).unwrap_or("").trim();
    let amount = params.get("amount").and_then(|v| v.as_f64()).unwrap_or(0.0);
    let memo = params.get("memo").and_then(|v| v.as_str()).unwrap_or("").trim();
    if amount <= 0.0 && memo.is_empty() {
        return json!({"ok": false, "error": "Enter an amount, a message, or both."});
    }
    let tx = match build_transfer_tx(&wallet, recipient, amount, memo) {
        Ok(t) => t,
        Err(e) => return json!({"ok": false, "error": e}),
    };
    let res = send_raw_tx(&tx);
    if res["ok"] == true {
        json!({"ok": true, "tx_hash": tx["tx_hash"]})
    } else {
        let body = res.pointer("/error/body").and_then(|v| v.as_str()).unwrap_or("");
        let reason = if body.contains("Insufficient") {
            "Not enough BZT for this amount plus the 0.01 BZT network fee.".to_string()
        } else if body.is_empty() {
            res["error"].to_string()
        } else {
            body.to_string()
        };
        json!({"ok": false, "error": reason})
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn merge_dedupes_and_orders_newest_first() {
        let mut cache = json!({"synced_height": 10, "transactions": [{"tx_hash": "a", "block_height": 5}]});
        merge_history(
            &mut cache,
            vec![json!({"tx_hash": "b", "block_height": 12}), json!({"tx_hash": "a", "block_height": 5})],
            20,
        );
        let hashes: Vec<&str> = cache["transactions"].as_array().unwrap().iter().map(|t| t["tx_hash"].as_str().unwrap()).collect();
        assert_eq!(hashes, ["b", "a"]);
        assert_eq!(cache["synced_height"], 20);
    }

    #[test]
    fn history_filters_by_kind_and_text() {
        let t = json!({"direction": "received", "memo": "Invoice 42", "type": "normal", "tx_hash": "ff"});
        assert!(history_matches(&t, "messages", ""));
        assert!(history_matches(&t, "received", "invoice"));
        assert!(!history_matches(&t, "sent", ""));
        assert!(!history_matches(&json!({"direction": "sent"}), "messages", ""));
    }
}
