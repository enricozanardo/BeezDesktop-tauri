use std::path::PathBuf;

use base64::engine::general_purpose::STANDARD;
use base64::Engine;
use serde_json::{json, Map, Value};
use uuid::Uuid;

use crate::crypto::{
    aes_gcm_decrypt_detached, aes_gcm_encrypt_detached, derive_encryption_key, derive_shared_key_ecdh,
    sha256_hex, unwrap_file_key, wrap_file_key,
};
use crate::http;
use crate::nodes::{http_url_for, list_all_nodes};
use crate::preview::{blurred_preview, is_previewable};
use crate::tx::{
    build_asset_price_tx, build_asset_visibility_tx, build_ownership_accept_tx,
    build_ownership_cancel_tx, build_ownership_reject_tx, build_ownership_request_tx,
    build_upload_tx, send_raw_tx_timeout,
};
use crate::wallet::Wallet;
use crate::wallet_store::require_wallet;

const CHUNK_SIZE: usize = 1024 * 1024;
const MAX_FILE: u64 = 500 * 1024 * 1024;
/// Chain protocol fee for an `upload` TX (`fee_config.TRANSACTION_FEES`).
const UPLOAD_FEE: f64 = 0.10;

fn fail(code: &str, error: impl Into<String>) -> Value {
    json!({"ok": false, "code": code, "error": error.into()})
}

fn latin1_encode(bytes: &[u8]) -> String {
    bytes.iter().map(|&b| char::from(b)).collect()
}

fn roster() -> Vec<Value> {
    list_all_nodes()
        .get("nodes")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default()
}

fn node_type(n: &Value) -> String {
    n.get("node_type")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_lowercase()
}

fn pick_storage(count: usize) -> Vec<Value> {
    let mut nodes: Vec<Value> = roster()
        .into_iter()
        .filter(|n| node_type(n) == "storage" && n.get("banned").and_then(|v| v.as_bool()) != Some(true))
        .collect();
    nodes.sort_by(|a, b| {
        let ra = a
            .get("reputation")
            .or_else(|| a.get("score"))
            .and_then(|v| v.as_f64())
            .unwrap_or(0.0);
        let rb = b
            .get("reputation")
            .or_else(|| b.get("score"))
            .and_then(|v| v.as_f64())
            .unwrap_or(0.0);
        rb.partial_cmp(&ra).unwrap()
    });
    nodes.truncate(count.max(1).min(6));
    nodes
}

fn pick_guardian() -> Option<String> {
    let mut dams: Vec<Value> = roster()
        .into_iter()
        .filter(|n| matches!(node_type(n).as_str(), "dam" | "manager"))
        .collect();
    dams.sort_by(|a, b| {
        let ra = a.get("score").and_then(|v| v.as_f64()).unwrap_or(0.0);
        let rb = b.get("score").and_then(|v| v.as_f64()).unwrap_or(0.0);
        rb.partial_cmp(&ra).unwrap()
    });
    dams.first()
        .and_then(|n| n.get("node_id").and_then(|v| v.as_str()).map(|s| s.to_string()))
}

fn storage_http(node: &Value) -> String {
    let ip = node
        .get("ip")
        .and_then(|v| v.as_str())
        .or_else(|| node.get("node_id").and_then(|v| v.as_str()))
        .unwrap_or("");
    http_url_for(ip)
}

fn lookup_http(node_id: &str) -> Option<String> {
    for n in roster() {
        if n.get("node_id").and_then(|v| v.as_str()) == Some(node_id) {
            return Some(storage_http(&n));
        }
    }
    None
}

fn upload_chunk(base: &str, file_id: &str, chunk_id: &str, data: &[u8], preferred: &[String]) -> Result<Vec<String>, String> {
    let body = json!({
        "file_id": file_id,
        "chunk_id": chunk_id,
        "chunk_content": latin1_encode(data),
        "source": "client",
        "preferred_backups": preferred,
    });
    let (status, val, text) = http::post_json(&format!("{base}/store_chunk"), &body, 90)?;
    if status != 200 && status != 202 {
        return Err(format!("store_chunk {status}: {}", text.chars().take(200).collect::<String>()));
    }
    Ok(val
        .get("backup_locations")
        .and_then(|v| v.as_array())
        .map(|a| {
            a.iter()
                .filter_map(|x| x.as_str().map(|s| s.to_string()))
                .collect()
        })
        .unwrap_or_default())
}

pub fn estimate(params: &Value) -> Value {
    let path = PathBuf::from(params.get("path").and_then(|v| v.as_str()).unwrap_or(""));
    let duration = params
        .get("duration")
        .and_then(|v| v.as_i64().or_else(|| v.as_u64().map(|n| n as i64)).or_else(|| v.as_f64().map(|n| n as i64)))
        .unwrap_or(5);
    let node_count = params.get("node_count").and_then(|v| v.as_u64()).unwrap_or(3) as usize;
    if !path.is_file() {
        return fail("file_not_found", format!("file not found: {}", path.display()));
    }
    let size = path.metadata().map(|m| m.len()).unwrap_or(0);
    if size > MAX_FILE {
        return fail("too_large", "File exceeds 500 MB");
    }
    let enc_len = size + 16;
    let chunks = ((enc_len as usize + CHUNK_SIZE - 1) / CHUNK_SIZE).max(1);
    let nodes = pick_storage(node_count);
    if nodes.is_empty() {
        return fail("no_storage", "No Storage nodes in the Directory roster");
    }
    let price: f64 = nodes
        .iter()
        .map(|n| n.get("price_per_chunk").and_then(|v| v.as_f64()).unwrap_or(1.0))
        .sum::<f64>()
        / nodes.len() as f64;
    json!({
        "ok": true,
        "file_name": path.file_name().and_then(|s| s.to_str()),
        "file_size": size,
        "chunks": chunks,
        "storage_nodes": nodes.len(),
        "duration_years": duration,
        "estimated_cost": price * chunks as f64 * duration as f64,
        "network_fee": UPLOAD_FEE,
        "price_per_chunk": price,
        "nodes": nodes.iter().map(|n| json!({
            "node_id": n.get("node_id"),
            "ip": n.get("ip"),
            "price_per_chunk": n.get("price_per_chunk"),
            "reputation": n.get("reputation"),
        })).collect::<Vec<_>>(),
        "guardian_dam_id": pick_guardian(),
    })
}

pub fn upload(params: &Value) -> Value {
    let path = PathBuf::from(params.get("path").and_then(|v| v.as_str()).unwrap_or(""));
    if !path.is_file() {
        return fail("file_not_found", format!("file not found: {}", path.display()));
    }
    let wallet = match require_wallet() {
        Ok(w) => w,
        Err(e) => return fail("no_wallet", e),
    };
    let size = path.metadata().map(|m| m.len()).unwrap_or(0);
    if size == 0 {
        return fail("empty", "file is empty");
    }
    if size > MAX_FILE {
        return fail("too_large", "File exceeds 500 MB");
    }
    let duration = params
        .get("duration")
        .and_then(|v| {
            v.as_i64()
                .or_else(|| v.as_u64().map(|n| n as i64))
                .or_else(|| v.as_f64().map(|n| n as i64))
        })
        .unwrap_or(5)
        .clamp(3, 10);
    let node_count = params
        .get("node_count")
        .and_then(|v| {
            v.as_u64()
                .or_else(|| v.as_i64().map(|n| n as u64))
                .or_else(|| v.as_f64().map(|n| n as u64))
        })
        .unwrap_or(3) as usize;
    let visibility = params.get("visibility").and_then(|v| v.as_str()).unwrap_or("private");
    let sell_price = params.get("price").and_then(|v| v.as_f64()).unwrap_or(0.0);
    let tags: Vec<String> = params
        .get("tags")
        .and_then(|v| v.as_array())
        .map(|a| a.iter().filter_map(|x| x.as_str().map(|s| s.to_string())).collect())
        .unwrap_or_default();
    let plaintext = match std::fs::read(&path) {
        Ok(b) => b,
        Err(e) => return fail("read", e.to_string()),
    };
    let query_hash = sha256_hex(&plaintext);
    let key = match derive_encryption_key(&wallet.privkey) {
        Ok(k) => k,
        Err(e) => return fail("crypto", e),
    };
    let (ciphertext, nonce) = match aes_gcm_encrypt_detached(&key, &plaintext) {
        Ok(v) => v,
        Err(e) => return fail("crypto", e),
    };
    let nonce_b64 = STANDARD.encode(nonce);
    let storage = pick_storage(node_count);
    if storage.is_empty() {
        return fail("no_storage", "No Storage nodes in the Directory roster");
    }
    let file_id = Uuid::new_v4().to_string();
    let file_name = path
        .file_name()
        .and_then(|s| s.to_str())
        .unwrap_or("file")
        .to_string();
    let extension = path
        .extension()
        .and_then(|s| s.to_str())
        .unwrap_or("")
        .to_string();
    let num_chunks = (ciphertext.len() + CHUNK_SIZE - 1) / CHUNK_SIZE;
    let nids: Vec<String> = storage
        .iter()
        .filter_map(|n| n.get("node_id").and_then(|v| v.as_str()).map(|s| s.to_string()))
        .collect();
    let mut locations = Map::new();
    let mut backups = Map::new();
    let mut node_chunk_count: std::collections::HashMap<String, u64> = std::collections::HashMap::new();
    for i in 0..num_chunks {
        let start = i * CHUNK_SIZE;
        let end = (start + CHUNK_SIZE).min(ciphertext.len());
        let slice = &ciphertext[start..end];
        let chunk_key = format!("{file_id}_chunk_{i}");
        let chunk_id = i.to_string();
        let primary_idx = i % storage.len();
        let mut order: Vec<usize> = (0..storage.len()).collect();
        order.rotate_left(primary_idx);
        let mut uploaded = false;
        for idx in order {
            let node = &storage[idx];
            let nid = node
                .get("node_id")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            let preferred: Vec<String> = nids.iter().filter(|id| *id != &nid).cloned().collect();
            match upload_chunk(&storage_http(node), &file_id, &chunk_id, slice, &preferred) {
                Ok(backup_nids) => {
                    locations.insert(chunk_key.clone(), json!([nid.clone()]));
                    let bk = if backup_nids.is_empty() {
                        preferred.into_iter().take(2).collect::<Vec<_>>()
                    } else {
                        backup_nids
                    };
                    backups.insert(chunk_key.clone(), json!(bk));
                    *node_chunk_count.entry(nid).or_insert(0) += 1;
                    uploaded = true;
                    break;
                }
                Err(_) => continue,
            }
        }
        if !uploaded {
            return fail("chunk_failed", format!("chunk {i} could not be stored on any Storage node"));
        }
    }
    let mut storage_cost = 0.0;
    for (nid, count) in &node_chunk_count {
        let price = storage
            .iter()
            .find(|n| n.get("node_id").and_then(|v| v.as_str()) == Some(nid.as_str()))
            .and_then(|n| n.get("price_per_chunk").and_then(|v| v.as_f64()))
            .unwrap_or(1.0);
        storage_cost += *count as f64 * price * duration as f64;
    }
    let guardian = pick_guardian();
    let mut tx = match build_upload_tx(
        &wallet,
        &file_id,
        &file_name,
        size,
        num_chunks as u64,
        &Value::Object(locations),
        &Value::Object(backups),
        duration,
        &query_hash,
        &nonce_b64,
        guardian.as_deref(),
        visibility,
        sell_price,
        &tags,
        &extension,
        storage_cost,
    ) {
        Ok(t) => t,
        Err(e) => return fail("tx_build", e),
    };
    let want_preview = params
        .get("preview")
        .and_then(|v| v.as_bool())
        .unwrap_or(visibility == "public");
    let mut preview_note = None;
    if want_preview && is_previewable(&extension) {
        match blurred_preview(&plaintext) {
            Ok(Value::Object(fields)) => {
                if let Some(obj) = tx.as_object_mut() {
                    obj.extend(fields);
                }
            }
            Ok(_) => {}
            Err(e) => preview_note = Some(e),
        }
    }
    let sent = send_raw_tx_timeout(&tx, 45);
    if sent.get("ok") != Some(&json!(true)) {
        return json!({
            "ok": false,
            "code": "tx_failed",
            "error": "Chunks are on Storage nodes but the upload TX was not accepted",
            "file_id": file_id,
            "tx": sent,
        });
    }
    json!({
        "ok": true,
        "file_id": file_id,
        "file_name": file_name,
        "chunks": num_chunks,
        "cost": storage_cost,
        "guardian_dam_id": guardian,
        "tx_hash": tx.get("tx_hash"),
        "visibility": visibility,
        "has_preview": tx.get("preview_data").is_some(),
        "preview_error": preview_note,
    })
}

fn fetch_wallet_pubkey(address: &str) -> Result<Vec<u8>, String> {
    for base in crate::nodes::chain_http_urls() {
        let url = format!("{base}/api/blockchain/wallet/{address}/pubkey");
        if let Ok(data) = http::get_json_connect(&url, 8, 1200) {
            if let Some(hex_str) = data.get("pubkey").and_then(|v| v.as_str()) {
                let bytes = hex::decode(hex_str.trim()).map_err(|e| format!("pubkey hex: {e}"))?;
                if bytes.len() == 64 || (bytes.len() == 65 && bytes[0] == 0x04) {
                    return Ok(if bytes.len() == 65 {
                        bytes[1..].to_vec()
                    } else {
                        bytes
                    });
                }
                return Err(format!("unexpected pubkey length {}", bytes.len()));
            }
        }
    }
    Err(format!("could not fetch pubkey for {address}"))
}

fn fetch_asset(file_id: &str) -> Result<Value, String> {
    for base in crate::nodes::chain_http_urls() {
        match http::get_json_connect(&format!("{base}/api/assets/{file_id}"), 10, 1200) {
            Ok(v) => return Ok(v.get("asset").cloned().unwrap_or(v)),
            Err(_) => continue,
        }
    }
    Err("asset not found on chain".into())
}

fn wrap_key_for_buyer(
    wallet: &Wallet,
    buyer_address: &str,
    encryption_nonce: &str,
) -> Result<(String, String, String), String> {
    let buyer_pub = fetch_wallet_pubkey(buyer_address)?;
    let shared = derive_shared_key_ecdh(&wallet.privkey, &buyer_pub)?;
    let owner_key = derive_encryption_key(&wallet.privkey)?;
    let (wrapped, wrap_nonce) = wrap_file_key(&owner_key, &shared)?;
    Ok((
        STANDARD.encode(wrapped),
        STANDARD.encode(wrap_nonce),
        encryption_nonce.to_string(),
    ))
}

fn parse_price_bzt(v: &Value) -> f64 {
    if let Some(n) = v.as_f64() {
        return n;
    }
    if let Some(s) = v.as_str() {
        let trimmed = s.replace(" BZT", "").replace("BZT", "").trim().to_string();
        return trimmed.parse::<f64>().unwrap_or(0.0);
    }
    0.0
}

/// Seller-initiated ownership offer with ECDH-wrapped file key.
pub fn ownership_transfer(params: &Value) -> Value {
    let wallet = match require_wallet() {
        Ok(w) => w,
        Err(e) => return fail("no_wallet", e),
    };
    let file_id = params.get("file_id").and_then(|v| v.as_str()).unwrap_or("");
    let new_owner = params
        .get("new_owner")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim();
    let asking_price = params.get("asking_price").and_then(|v| v.as_f64()).unwrap_or(0.0);
    let message = params.get("message").and_then(|v| v.as_str()).unwrap_or("");
    if file_id.is_empty() || new_owner.is_empty() {
        return fail("args", "file_id and new_owner are required");
    }
    if new_owner == wallet.address {
        return fail("args", "Cannot transfer to yourself");
    }
    let asset = match fetch_asset(file_id) {
        Ok(a) => a,
        Err(e) => return fail("not_found", e),
    };
    let owner = asset
        .get("owner")
        .or_else(|| asset.get("owner_address"))
        .and_then(|v| v.as_str())
        .unwrap_or("");
    if owner != wallet.address {
        return fail("forbidden", "You do not own this asset");
    }
    let enc_nonce = asset
        .get("encryption_nonce")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let mut wrapped = None;
    let mut wrap_n = None;
    let mut file_n = None;
    if !enc_nonce.is_empty() {
        match wrap_key_for_buyer(&wallet, new_owner, enc_nonce) {
            Ok((w, n, e)) => {
                wrapped = Some(w);
                wrap_n = Some(n);
                file_n = Some(e);
            }
            Err(e) => {
                return fail(
                    "ecdh",
                    format!("Could not wrap encryption key for buyer (pubkey on chain?): {e}"),
                );
            }
        }
    }
    let tx = match build_ownership_request_tx(
        &wallet,
        file_id,
        &wallet.address,
        new_owner,
        asking_price,
        message,
        wrapped.as_deref(),
        wrap_n.as_deref(),
        file_n.as_deref(),
    ) {
        Ok(t) => t,
        Err(e) => return fail("tx_build", e),
    };
    let sent = send_raw_tx_timeout(&tx, 45);
    if sent.get("ok") != Some(&json!(true)) {
        return json!({"ok": false, "code": "tx_failed", "error": sent});
    }
    json!({
        "ok": true,
        "tx_hash": tx.get("tx_hash"),
        "request_id": tx.get("tx_hash"),
        "file_id": file_id,
        "new_owner": new_owner,
        "asking_price": asking_price,
        "status": "pending",
    })
}

/// Buyer asks the owner of a public asset to sell it at the listed price.
pub fn purchase_request(params: &Value) -> Value {
    let wallet = match require_wallet() {
        Ok(w) => w,
        Err(e) => return fail("no_wallet", e),
    };
    let file_id = params.get("file_id").and_then(|v| v.as_str()).unwrap_or("");
    let message = params.get("message").and_then(|v| v.as_str()).unwrap_or("");
    if file_id.is_empty() {
        return fail("args", "file_id is required");
    }
    let asset = match fetch_asset(file_id) {
        Ok(a) => a,
        Err(e) => return fail("not_found", e),
    };
    let owner = asset.get("owner").and_then(|v| v.as_str()).unwrap_or("");
    if owner.is_empty() {
        return fail("not_found", "asset has no owner on chain");
    }
    if owner == wallet.address {
        return fail("args", "You already own this file");
    }
    if asset.get("visibility").and_then(|v| v.as_str()) != Some("public") {
        return fail("forbidden", "This file is not listed on the marketplace");
    }
    if asset.get("transfer_locked").and_then(|v| v.as_bool()) == Some(true) {
        return fail("locked", "Another transfer of this file is already pending");
    }
    let price = asset.get("price").map(parse_price_bzt).unwrap_or(0.0);
    let tx = match build_ownership_request_tx(
        &wallet, file_id, owner, &wallet.address, price, message, None, None, None,
    ) {
        Ok(t) => t,
        Err(e) => return fail("tx_build", e),
    };
    let sent = send_raw_tx_timeout(&tx, 45);
    if sent.get("ok") != Some(&json!(true)) {
        return json!({"ok": false, "code": "tx_failed", "error": sent});
    }
    json!({
        "ok": true,
        "tx_hash": tx.get("tx_hash"),
        "file_id": file_id,
        "seller": owner,
        "asking_price": price,
        "status": "pending",
    })
}

/// Owner lists (`public`) or unlists (`private`) a file and optionally reprices it.
pub fn set_listing(params: &Value) -> Value {
    let wallet = match require_wallet() {
        Ok(w) => w,
        Err(e) => return fail("no_wallet", e),
    };
    let file_id = params.get("file_id").and_then(|v| v.as_str()).unwrap_or("");
    let visibility = params.get("visibility").and_then(|v| v.as_str());
    let price = params.get("price").and_then(|v| v.as_f64());
    let old_price = params.get("old_price").and_then(|v| v.as_f64()).unwrap_or(0.0);
    if file_id.is_empty() || (visibility.is_none() && price.is_none()) {
        return fail("args", "file_id and a visibility or price change are required");
    }
    if let Some(v) = visibility {
        if v != "public" && v != "private" {
            return fail("args", "visibility must be public or private");
        }
    }
    if let Some(p) = price {
        if !p.is_finite() || p < 0.0 {
            return fail("args", "price must be zero or positive");
        }
    }
    let mut txs = Vec::new();
    if let Some(p) = price {
        match build_asset_price_tx(&wallet, file_id, p, old_price) {
            Ok(t) => txs.push(t),
            Err(e) => return fail("tx_build", e),
        }
    }
    if let Some(v) = visibility {
        match build_asset_visibility_tx(&wallet, file_id, v) {
            Ok(t) => txs.push(t),
            Err(e) => return fail("tx_build", e),
        }
    }
    let mut hashes = Vec::new();
    for tx in &txs {
        let sent = send_raw_tx_timeout(tx, 45);
        if sent.get("ok") != Some(&json!(true)) {
            return json!({"ok": false, "code": "tx_failed", "error": sent, "submitted": hashes});
        }
        hashes.push(tx.get("tx_hash").cloned().unwrap_or(Value::Null));
    }
    json!({"ok": true, "tx_hashes": hashes})
}

/// Public files listed by other wallets (`/api/marketplace/assets`).
pub fn marketplace(params: &Value) -> Value {
    let query = params.get("query").and_then(|v| v.as_str()).unwrap_or("").trim();
    let limit = params.get("limit").and_then(|v| v.as_u64()).unwrap_or(50).min(200);
    let offset = params.get("offset").and_then(|v| v.as_u64()).unwrap_or(0);
    let mut args = vec![
        ("query", query.to_string()),
        ("limit", limit.to_string()),
        ("offset", offset.to_string()),
    ];
    let tags = params.get("tags").and_then(|v| v.as_str()).unwrap_or("").trim();
    if !tags.is_empty() {
        args.push(("tags", tags.to_string()));
    }
    for key in ["min_price", "max_price"] {
        if let Some(p) = params.get(key).and_then(|v| v.as_f64()).filter(|p| *p >= 0.0) {
            args.push((key, p.to_string()));
        }
    }
    for base in crate::nodes::chain_http_urls() {
        let Ok(url) = reqwest::Url::parse_with_params(&format!("{base}/api/marketplace/assets"), &args) else {
            continue;
        };
        if let Ok(data) = http::get_json_connect(url.as_str(), 10, 1200) {
            return json!({
                "ok": true,
                "assets": data.get("assets").cloned().unwrap_or(json!([])),
                "total": data.get("total").cloned().unwrap_or(Value::Null),
            });
        }
    }
    fail("chain", "no chain node returned marketplace assets")
}

/// Blurred preview image recorded in an asset's upload transaction.
pub fn preview(params: &Value) -> Value {
    let file_id = params.get("file_id").and_then(|v| v.as_str()).unwrap_or("");
    if Uuid::parse_str(file_id).is_err() {
        return fail("args", "file_id must be a UUID");
    }
    let mut last = "no chain node reachable".to_string();
    for base in crate::nodes::chain_http_urls() {
        match http::get_json_connect(&format!("{base}/api/assets/{file_id}/preview"), 20, 1200) {
            Ok(data) => {
                return json!({
                    "ok": true,
                    "has_preview": data.get("has_preview").and_then(|v| v.as_bool()).unwrap_or(false),
                    "preview_data": data.get("preview_data"),
                    "width": data.get("preview_width"),
                    "height": data.get("preview_height"),
                });
            }
            Err(e) => last = e,
        }
    }
    fail("chain", last)
}

pub fn ownership_pending() -> Value {
    let wallet = match require_wallet() {
        Ok(w) => w,
        Err(e) => return fail("no_wallet", e),
    };
    for base in crate::nodes::chain_http_urls() {
        let url = format!("{base}/api/ownership/pending?address={}", wallet.address);
        match http::get_json_connect(&url, 10, 1200) {
            Ok(data) => {
                return json!({
                    "ok": true,
                    "incoming": data.get("incoming").cloned().unwrap_or(json!([])),
                    "outgoing": data.get("outgoing").cloned().unwrap_or(json!([])),
                    "source": base,
                });
            }
            Err(_) => continue,
        }
    }
    fail("chain", "no chain node returned ownership pending")
}

/// Buyer accepts a seller-initiated offer (pays asking_price).
pub fn ownership_accept(params: &Value) -> Value {
    let wallet = match require_wallet() {
        Ok(w) => w,
        Err(e) => return fail("no_wallet", e),
    };
    let request_id = params.get("request_id").and_then(|v| v.as_str()).unwrap_or("");
    let file_id = params.get("file_id").and_then(|v| v.as_str()).unwrap_or("");
    let asking_price = params
        .get("asking_price")
        .map(parse_price_bzt)
        .unwrap_or(0.0);
    if request_id.is_empty() || file_id.is_empty() {
        return fail("args", "request_id and file_id are required");
    }
    let tx = match build_ownership_accept_tx(
        &wallet,
        request_id,
        file_id,
        &wallet.address,
        asking_price,
        "",
        None,
        None,
        None,
        None,
    ) {
        Ok(t) => t,
        Err(e) => return fail("tx_build", e),
    };
    let sent = send_raw_tx_timeout(&tx, 45);
    if sent.get("ok") != Some(&json!(true)) {
        return json!({"ok": false, "code": "tx_failed", "error": sent});
    }
    json!({"ok": true, "tx_hash": tx.get("tx_hash"), "status": "accepted"})
}

/// Seller accepts a buyer-initiated purchase request (wraps key for buyer).
pub fn ownership_seller_accept(params: &Value) -> Value {
    let wallet = match require_wallet() {
        Ok(w) => w,
        Err(e) => return fail("no_wallet", e),
    };
    let request_id = params.get("request_id").and_then(|v| v.as_str()).unwrap_or("");
    let file_id = params.get("file_id").and_then(|v| v.as_str()).unwrap_or("");
    let buyer = params
        .get("buyer_address")
        .or_else(|| params.get("new_owner"))
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim();
    let asking_price = params
        .get("asking_price")
        .map(parse_price_bzt)
        .unwrap_or(0.0);
    if request_id.is_empty() || file_id.is_empty() || buyer.is_empty() {
        return fail("args", "request_id, file_id, and buyer_address are required");
    }
    let asset = match fetch_asset(file_id) {
        Ok(a) => a,
        Err(e) => return fail("not_found", e),
    };
    let enc_nonce = asset
        .get("encryption_nonce")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let mut wrapped = None;
    let mut wrap_n = None;
    let mut file_n = None;
    if !enc_nonce.is_empty() {
        match wrap_key_for_buyer(&wallet, buyer, enc_nonce) {
            Ok((w, n, e)) => {
                wrapped = Some(w);
                wrap_n = Some(n);
                file_n = Some(e);
            }
            Err(e) => return fail("ecdh", e),
        }
    }
    let tx = match build_ownership_accept_tx(
        &wallet,
        request_id,
        file_id,
        buyer,
        asking_price,
        "",
        Some(&wallet.address),
        wrapped.as_deref(),
        wrap_n.as_deref(),
        file_n.as_deref(),
    ) {
        Ok(t) => t,
        Err(e) => return fail("tx_build", e),
    };
    let sent = send_raw_tx_timeout(&tx, 45);
    if sent.get("ok") != Some(&json!(true)) {
        return json!({"ok": false, "code": "tx_failed", "error": sent});
    }
    json!({"ok": true, "tx_hash": tx.get("tx_hash"), "status": "accepted"})
}

pub fn ownership_reject(params: &Value) -> Value {
    let wallet = match require_wallet() {
        Ok(w) => w,
        Err(e) => return fail("no_wallet", e),
    };
    let request_id = params.get("request_id").and_then(|v| v.as_str()).unwrap_or("");
    let file_id = params.get("file_id").and_then(|v| v.as_str()).unwrap_or("");
    let message = params
        .get("message")
        .and_then(|v| v.as_str())
        .unwrap_or("Rejected by recipient");
    if request_id.is_empty() || file_id.is_empty() {
        return fail("args", "request_id and file_id are required");
    }
    let tx = match build_ownership_reject_tx(&wallet, request_id, file_id, message) {
        Ok(t) => t,
        Err(e) => return fail("tx_build", e),
    };
    let sent = send_raw_tx_timeout(&tx, 45);
    if sent.get("ok") != Some(&json!(true)) {
        return json!({"ok": false, "code": "tx_failed", "error": sent});
    }
    json!({"ok": true, "tx_hash": tx.get("tx_hash"), "status": "rejected"})
}

pub fn ownership_cancel(params: &Value) -> Value {
    let wallet = match require_wallet() {
        Ok(w) => w,
        Err(e) => return fail("no_wallet", e),
    };
    let request_id = params.get("request_id").and_then(|v| v.as_str()).unwrap_or("");
    let file_id = params.get("file_id").and_then(|v| v.as_str()).unwrap_or("");
    if request_id.is_empty() || file_id.is_empty() {
        return fail("args", "request_id and file_id are required");
    }
    let tx = match build_ownership_cancel_tx(&wallet, request_id, file_id) {
        Ok(t) => t,
        Err(e) => return fail("tx_build", e),
    };
    let sent = send_raw_tx_timeout(&tx, 45);
    if sent.get("ok") != Some(&json!(true)) {
        return json!({"ok": false, "code": "tx_failed", "error": sent});
    }
    json!({"ok": true, "tx_hash": tx.get("tx_hash"), "status": "cancelled"})
}

fn resolve_decrypt_key(wallet: &Wallet, file_id: &str, asset: &Value) -> Result<[u8; 32], String> {
    let own_key = derive_encryption_key(&wallet.privkey)?;
    let nonce_b64 = asset.get("encryption_nonce").and_then(|v| v.as_str()).unwrap_or("");
    let nonce_vec = STANDARD.decode(nonce_b64).unwrap_or_default();
    if nonce_vec.len() != 12 {
        return Err("asset is missing a 12-byte encryption nonce".into());
    }
    // Prefer ECDH unwrap from ownership history when this wallet acquired the file.
    for base in crate::nodes::chain_http_urls() {
        let url = format!("{base}/api/ownership/history/{file_id}");
        if let Ok(data) = http::get_json_connect(&url, 10, 1200) {
            let history = data
                .get("history")
                .and_then(|v| v.as_array())
                .cloned()
                .unwrap_or_default();
            for transfer in history {
                let to_owner = transfer
                    .get("to_owner")
                    .or_else(|| transfer.get("new_owner"))
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                if to_owner != wallet.address {
                    continue;
                }
                let Some(wrapped_b64) = transfer.get("wrapped_file_key").and_then(|v| v.as_str())
                else {
                    continue;
                };
                let Some(wrap_n_b64) = transfer.get("wrap_nonce").and_then(|v| v.as_str()) else {
                    continue;
                };
                let Some(seller_hex) = transfer.get("seller_pubkey").and_then(|v| v.as_str()) else {
                    continue;
                };
                let wrapped = STANDARD
                    .decode(wrapped_b64)
                    .map_err(|e| format!("wrapped key b64: {e}"))?;
                let wrap_n = STANDARD
                    .decode(wrap_n_b64)
                    .map_err(|e| format!("wrap nonce b64: {e}"))?;
                if wrap_n.len() != 12 {
                    continue;
                }
                let mut wrap_nonce = [0u8; 12];
                wrap_nonce.copy_from_slice(&wrap_n);
                let mut seller = hex::decode(seller_hex.trim()).map_err(|e| format!("seller pub: {e}"))?;
                if seller.len() == 65 && seller[0] == 0x04 {
                    seller = seller[1..].to_vec();
                }
                if seller.len() != 64 {
                    continue;
                }
                let shared = derive_shared_key_ecdh(&wallet.privkey, &seller)?;
                return unwrap_file_key(&wrapped, &wrap_nonce, &shared);
            }
        }
    }
    Ok(own_key)
}

pub fn list_mine() -> Value {
    let wallet = match require_wallet() {
        Ok(w) => w,
        Err(e) => return fail("no_wallet", e),
    };
    for base in crate::nodes::chain_http_urls() {
        let url = format!("{base}/api/blockchain/wallet/{}/uploads", wallet.address);
        match http::get_json_connect(&url, 10, 1200) {
            Ok(data) => {
                return json!({
                    "ok": true,
                    "uploads": data.get("uploads").cloned().unwrap_or(json!([])),
                    "source": base,
                });
            }
            Err(_) => continue,
        }
    }
    fail("chain", "no chain node returned uploads")
}

pub fn download(params: &Value) -> Value {
    let wallet = match require_wallet() {
        Ok(w) => w,
        Err(e) => return fail("no_wallet", e),
    };
    let file_id = params.get("file_id").and_then(|v| v.as_str()).unwrap_or("");
    let dest_dir = PathBuf::from(params.get("dest_dir").and_then(|v| v.as_str()).unwrap_or(""));
    if file_id.is_empty() || !dest_dir.is_dir() {
        return fail("args", "file_id and dest_dir (existing folder) are required");
    }
    let asset = match fetch_asset(file_id) {
        Ok(a) => a,
        Err(e) => return fail("not_found", e),
    };
    let owner = asset
        .get("owner")
        .or_else(|| asset.get("owner_address"))
        .and_then(|v| v.as_str())
        .unwrap_or("");
    if owner != wallet.address {
        return fail("forbidden", "You do not own this asset");
    }
    let num_chunks = asset.get("num_chunks").and_then(|v| v.as_u64()).unwrap_or(0) as usize;
    let locations = asset.get("chunk_locations").cloned().unwrap_or(json!({}));
    let backups = asset.get("backup_chunk_locations").cloned().unwrap_or(json!({}));
    let mut cipher = Vec::new();
    for i in 0..num_chunks {
        let key = format!("{file_id}_chunk_{i}");
        let mut nids: Vec<String> = Vec::new();
        for src in [&locations, &backups] {
            if let Some(arr) = src.get(&key).and_then(|v| v.as_array()) {
                for x in arr {
                    if let Some(s) = x.as_str() {
                        if !nids.iter().any(|n| n == s) {
                            nids.push(s.to_string());
                        }
                    }
                }
            }
        }
        let mut got = None;
        for nid in &nids {
            let Some(base) = lookup_http(nid) else {
                continue;
            };
            match http::get_bytes(&format!("{base}/get_chunk/{file_id}/{i}"), 30) {
                Ok(bytes) if !bytes.is_empty() => {
                    got = Some(bytes);
                    break;
                }
                _ => continue,
            }
        }
        match got {
            Some(b) => cipher.extend_from_slice(&b),
            None => return fail("chunk_missing", format!("could not fetch chunk {i}")),
        }
    }
    let nonce_b64 = asset.get("encryption_nonce").and_then(|v| v.as_str()).unwrap_or("");
    let nonce_vec = STANDARD.decode(nonce_b64).unwrap_or_default();
    if nonce_vec.len() != 12 {
        return fail("crypto", "asset is missing a 12-byte encryption nonce");
    }
    let mut nonce = [0u8; 12];
    nonce.copy_from_slice(&nonce_vec);
    let key = match resolve_decrypt_key(&wallet, file_id, &asset) {
        Ok(k) => k,
        Err(e) => return fail("crypto", e),
    };
    let plain = match aes_gcm_decrypt_detached(&key, &nonce, &cipher) {
        Ok(p) => p,
        Err(own_err) => {
            // Original uploader path if ECDH unwrap was tried incorrectly.
            match derive_encryption_key(&wallet.privkey) {
                Ok(own_key) if own_key != key => match aes_gcm_decrypt_detached(&own_key, &nonce, &cipher)
                {
                    Ok(p) => p,
                    Err(e) => return fail("crypto", format!("decrypt failed ({own_err}; own-key: {e})")),
                },
                _ => return fail("crypto", own_err),
            }
        }
    };
    let mut name = asset
        .get("file_name")
        .and_then(|v| v.as_str())
        .unwrap_or("download")
        .to_string();
    if let Some(ext) = asset.get("extension").and_then(|v| v.as_str()) {
        if !ext.is_empty() && !name.ends_with(&format!(".{ext}")) {
            name = format!("{name}.{ext}");
        }
    }
    let dest = dest_dir.join(name);
    if let Err(e) = std::fs::write(&dest, &plain) {
        return fail("write", e.to_string());
    }
    json!({"ok": true, "path": dest.display().to_string(), "bytes": plain.len()})
}
