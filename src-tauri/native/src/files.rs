use std::path::PathBuf;

use base64::engine::general_purpose::STANDARD;
use base64::Engine;
use serde_json::{json, Map, Value};
use uuid::Uuid;

use crate::crypto::{aes_gcm_decrypt_detached, aes_gcm_encrypt_detached, derive_encryption_key, sha256_hex};
use crate::http;
use crate::nodes::{http_url_for, list_all_nodes};
use crate::tx::{build_upload_tx, send_raw_tx_timeout};
use crate::wallet_store::require_wallet;

const CHUNK_SIZE: usize = 1024 * 1024;
const MAX_FILE: u64 = 500 * 1024 * 1024;

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
    let tx = match build_upload_tx(
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
    })
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
    let mut asset = Value::Null;
    for base in crate::nodes::chain_http_urls() {
        match http::get_json_connect(&format!("{base}/api/assets/{file_id}"), 10, 1200) {
            Ok(v) => {
                asset = v.get("asset").cloned().unwrap_or(v);
                break;
            }
            Err(_) => continue,
        }
    }
    if asset.is_null() {
        return fail("not_found", "asset not found on chain");
    }
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
    let key = match derive_encryption_key(&wallet.privkey) {
        Ok(k) => k,
        Err(e) => return fail("crypto", e),
    };
    let plain = match aes_gcm_decrypt_detached(&key, &nonce, &cipher) {
        Ok(p) => p,
        Err(e) => return fail("crypto", e),
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
