use std::path::PathBuf;

use base64::engine::general_purpose::STANDARD;
use base64::Engine;
use serde_json::{json, Value};
use uuid::Uuid;

use crate::chunking::split_into_rag_chunks;
use crate::crypto::{aes_gcm_encrypt, derive_encryption_key, sha256_hex, sign_der};
use crate::embed;
use crate::http;
use crate::minicpm;
use crate::nodes::{list_smart_nodes, rank_nodes, smart_url, infer_needed_capabilities};
use crate::paths::{home_dir, APP_WALLET_NAME};
use crate::tx::{
    build_knowledge_publish_tx, build_knowledge_purchase_tx, build_knowledge_query_tx,
    build_smart_index_tx, build_smart_query_tx,
    send_raw_tx,
};
use crate::wallet::Wallet;
use crate::wallet_store::{delete_wallet, load_or_migrate, require_wallet, save_wallet};

pub fn ping() -> Value {
    json!({
        "ok": true,
        "sidecar": "native",
        "client_core": true,
        "product": "Beez Desktop Two",
        "engine": "rust",
    })
}

pub fn read_beez_config() -> Value {
    let path = home_dir().join(".beez");
    if path.is_file() {
        let text = std::fs::read_to_string(&path).unwrap_or_default();
        json!({ "ok": true, "exists": true, "text": text })
    } else {
        json!({ "ok": true, "exists": false, "text": "" })
    }
}

pub fn wallet_status() -> Value {
    match load_or_migrate() {
        Ok((Some(w), migrated)) => json!({
            "ok": true,
            "has_wallet": true,
            "address": w.address,
            "storage": APP_WALLET_NAME,
            "migrated_from": migrated,
        }),
        Ok((None, _)) => json!({
            "ok": true,
            "has_wallet": false,
            "address": null,
            "storage": APP_WALLET_NAME,
        }),
        Err(e) => json!({"ok": false, "error": e, "has_wallet": false}),
    }
}

pub fn wallet_create() -> Value {
    if wallet_file_exists() {
        return json!({
            "ok": false,
            "error": "A wallet already exists. Forget it first, or import over after forget."
        });
    }
    match Wallet::generate() {
        Ok(w) => match save_wallet(APP_WALLET_NAME, &w.mnemonic, &w.address) {
            Ok(()) => json!({
                "ok": true,
                "address": w.address,
                "mnemonic": w.mnemonic,
                "storage": APP_WALLET_NAME,
            }),
            Err(e) => json!({"ok": false, "error": e}),
        },
        Err(e) => json!({"ok": false, "error": e}),
    }
}

fn wallet_file_exists() -> bool {
    crate::wallet_store::wallet_file(APP_WALLET_NAME).is_file()
}

pub fn wallet_import(params: &Value) -> Value {
    let mnemonic = params
        .get("mnemonic")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .trim();
    let n = mnemonic.split_whitespace().count();
    if n != 12 && n != 24 {
        return json!({"ok": false, "error": "mnemonic must be 12 or 24 words"});
    }
    match Wallet::from_mnemonic(mnemonic) {
        Ok(w) => match save_wallet(APP_WALLET_NAME, &w.mnemonic, &w.address) {
            Ok(()) => json!({"ok": true, "address": w.address, "storage": APP_WALLET_NAME}),
            Err(e) => json!({"ok": false, "error": e}),
        },
        Err(e) => json!({"ok": false, "error": e}),
    }
}

pub fn wallet_forget() -> Value {
    match delete_wallet(APP_WALLET_NAME) {
        Ok(()) => json!({"ok": true, "has_wallet": false, "storage": APP_WALLET_NAME}),
        Err(e) => json!({"ok": false, "error": e}),
    }
}

pub fn rank_smart_nodes(params: &Value) -> Value {
    let listed = list_smart_nodes();
    let nodes = listed.get("nodes").and_then(|v| v.as_array()).cloned().unwrap_or_default();
    let prompt = params.get("prompt").and_then(|v| v.as_str()).unwrap_or("");
    let attachments: Vec<String> = params
        .get("attachments")
        .and_then(|v| v.as_array())
        .map(|a| {
            a.iter()
                .filter_map(|x| x.as_str().map(|s| s.to_string()))
                .collect()
        })
        .unwrap_or_default();
    let ranked = rank_nodes(&nodes, prompt, &attachments);
    json!({
        "ok": true,
        "needed": infer_needed_capabilities(prompt, &attachments),
        "nodes": ranked,
        "errors": listed.get("errors"),
        "source": listed.get("source"),
    })
}

fn node_is_local(node: &Value) -> bool {
    node.get("node_id").and_then(|v| v.as_str()) == Some("local_minicpm")
        || node.get("llm_backend").and_then(|v| v.as_str()) == Some("minicpm_local")
}

fn fail(code: &str, error: impl Into<String>) -> Value {
    json!({"ok": false, "code": code, "error": error.into()})
}

fn last_user_text(messages: &Value) -> String {
    messages
        .as_array()
        .into_iter()
        .flatten()
        .rev()
        .find(|m| m.get("role").and_then(|r| r.as_str()) == Some("user"))
        .and_then(|m| m.get("content").and_then(|c| c.as_str()))
        .unwrap_or("")
        .to_string()
}

fn settle_smart_query(
    wallet: &Wallet,
    node: &Value,
    info: &Value,
    result: &mut Value,
    last: &str,
) {
    let query_hash = result
        .get("query_hash")
        .and_then(|v| v.as_str())
        .map(|s| s.to_string())
        .unwrap_or_else(|| sha256_hex(last.as_bytes()));
    let answer_hash = result
        .get("answer_hash")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_string();
    let cost = result.get("cost").and_then(|v| v.as_f64()).unwrap_or(0.0);
    let file_ids: Vec<String> = result
        .get("sources")
        .and_then(|v| v.as_array())
        .map(|a| {
            a.iter()
                .filter_map(|s| s.get("file_id").and_then(|v| v.as_str()).map(|s| s.to_string()))
                .collect()
        })
        .unwrap_or_default();
    let node_id = info
        .get("node_id")
        .or_else(|| node.get("node_id"))
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let node_wallet = info
        .get("wallet_address")
        .or_else(|| node.get("wallet_address"))
        .and_then(|v| v.as_str())
        .unwrap_or("");
    match build_smart_query_tx(wallet, &query_hash, &answer_hash, node_id, node_wallet, cost, &file_ids)
    {
        Ok(tx) => {
            let tx_info = send_raw_tx(&tx);
            if let Some(obj) = result.as_object_mut() {
                if tx_info.get("ok") == Some(&json!(true)) {
                    obj.insert("tx_hash".into(), tx.get("tx_hash").cloned().unwrap_or(json!(null)));
                } else {
                    obj.insert("code".into(), json!("tx_failed"));
                }
                obj.insert("tx".into(), tx_info);
            }
        }
        Err(e) => {
            if let Some(obj) = result.as_object_mut() {
                obj.insert("code".into(), json!("tx_failed"));
                obj.insert("tx".into(), json!({"ok": false, "error": e}));
            }
        }
    }
}

pub fn chat(params: &Value) -> Value {
    let messages = params.get("messages").cloned().unwrap_or(json!([]));
    let node = params.get("node").cloned().unwrap_or(json!({}));
    if node_is_local(&node) || params.get("backend").and_then(|v| v.as_str()) == Some("minicpm_local")
    {
        let result = minicpm::chat(&messages, 512);
        if result.get("ok") != Some(&json!(true)) {
            return result;
        }
        return json!({
            "ok": true,
            "answer": result.get("answer"),
            "sources": [],
            "cost": 0,
            "estimated_cost": 0,
            "verification": null,
            "local": true,
        });
    }
    let wallet = match require_wallet() {
        Ok(w) => w,
        Err(e) => return fail("no_wallet", e),
    };
    let key = match derive_encryption_key(&wallet.privkey) {
        Ok(k) => k,
        Err(e) => return fail("crypto", e),
    };
    let last = last_user_text(&messages);
    if last.trim().is_empty() {
        return fail("empty_query", "Type a question before sending.");
    }
    if let Err(e) = embed::ensure() {
        return fail("embed_failed", format!("Preparing embedding model: {e}"));
    }
    let query_vector = match embed::embed_query(&last) {
        Ok(v) => v,
        Err(e) => return fail("embed_failed", e),
    };
    let base = smart_url(&node);
    let info = match http::get_json_connect(&format!("{base}/info"), 6, 1200) {
        Ok(v) => v,
        Err(e) => return fail("node_unreachable", format!("{base}: {e}")),
    };
    let estimated = info
        .get("price_per_query")
        .or_else(|| node.get("price_per_query"))
        .and_then(|v| v.as_f64())
        .unwrap_or(0.0);
    let mut chat_payload = json!({
        "messages": messages,
        "query_vector": query_vector,
        "wallet_address": wallet.address,
        "decryption_key": STANDARD.encode(&key),
        "top_k": params.get("top_k").and_then(|v| v.as_u64()).unwrap_or(5),
    });
    if let Some(ids) = params.get("file_ids") {
        chat_payload["file_ids"] = ids.clone();
    }
    if let Some(tid) = params.get("thread_id") {
        chat_payload["thread_id"] = tid.clone();
    }
    let mut used = "chat";
    let (status, mut result, text) = match http::post_json(&format!("{base}/chat"), &chat_payload, 180) {
        Ok(t) => t,
        Err(e) => return fail("node_unreachable", e),
    };
    if status != 200 {
        if status == 404 || status == 405 || status == 501 {
            used = "query";
            let query_payload = json!({
                "query_text": last,
                "query_vector": query_vector,
                "wallet_address": wallet.address,
                "decryption_key": STANDARD.encode(&key),
                "top_k": params.get("top_k").and_then(|v| v.as_u64()).unwrap_or(5),
                "file_ids": params.get("file_ids").cloned().unwrap_or(json!(null)),
            });
            match http::post_json(&format!("{base}/query"), &query_payload, 180) {
                Ok((200, body, _)) => result = body,
                Ok((st, _, t2)) => {
                    return fail(
                        "smart_http",
                        format!("smart query {st}: {}", t2.chars().take(400).collect::<String>()),
                    );
                }
                Err(e) => return fail("node_unreachable", e),
            }
        } else {
            return fail(
                "smart_http",
                format!("smart chat {status}: {}", text.chars().take(400).collect::<String>()),
            );
        }
    }
    if let Some(obj) = result.as_object_mut() {
        obj.insert("ok".into(), json!(true));
        obj.insert("endpoint".into(), json!(used));
        obj.insert("estimated_cost".into(), json!(estimated));
        obj.insert("http_url".into(), json!(base));
        let existing_code = obj.get("code").and_then(|v| v.as_str()).unwrap_or("");
        if existing_code == "llm_no_credit" {
            // Provider out of credits — do not bill and keep the friendly code.
            obj.insert("cost".into(), json!(0.0));
        } else if obj.get("no_relevant_data").and_then(|v| v.as_bool()) == Some(true)
            && existing_code.is_empty()
        {
            obj.insert("code".into(), json!("empty_workspace"));
        }
    }
    let skip_settle = result.get("code").and_then(|v| v.as_str()) == Some("llm_no_credit")
        || result.get("llm_available").and_then(|v| v.as_bool()) == Some(false);
    if !skip_settle {
        settle_smart_query(&wallet, &node, &info, &mut result, &last);
    }
    result
}

/// Soft caps so indexing a PDF does not OOM the desktop (ONNX embeds in tiny batches).
const MAX_INDEX_CHARS: usize = 250_000;
const MAX_INDEX_CHUNKS: usize = 400;
const INDEX_UPLOAD_BATCH: usize = 32;

fn prepare_index_text(mut text: String) -> (String, bool) {
    let truncated = text.chars().count() > MAX_INDEX_CHARS;
    if truncated {
        text = text.chars().take(MAX_INDEX_CHARS).collect();
    }
    (text, truncated)
}

pub fn index_file(params: &Value) -> Value {
    let path = PathBuf::from(params.get("path").and_then(|v| v.as_str()).unwrap_or(""));
    if !path.is_file() {
        return json!({"ok": false, "error": format!("file not found: {}", path.display())});
    }
    let node = params.get("node").cloned().unwrap_or(json!({}));
    if node_is_local(&node) {
        return json!({"ok": false, "error": "Local MiniCPM does not index network workspaces"});
    }
    let raw = match read_text(&path) {
        Ok(t) => t,
        Err(e) => return fail("extract", e),
    };
    if raw.trim().is_empty() {
        return fail("extract", "no extractable text");
    }
    let (text, truncated) = prepare_index_text(raw);
    let wallet = match require_wallet() {
        Ok(w) => w,
        Err(e) => return fail("no_wallet", e),
    };
    let key = match derive_encryption_key(&wallet.privkey) {
        Ok(k) => k,
        Err(e) => return fail("crypto", e),
    };
    if let Err(e) = embed::ensure() {
        return fail("embed_failed", e);
    }
    let mut chunks = split_into_rag_chunks(&text, 800, 100, 50);
    drop(text);
    if chunks.is_empty() {
        return json!({"ok": false, "error": "No text content to index"});
    }
    let chunk_capped = chunks.len() > MAX_INDEX_CHUNKS;
    if chunk_capped {
        chunks.truncate(MAX_INDEX_CHUNKS);
    }
    let file_id = params
        .get("file_id")
        .and_then(|v| v.as_str())
        .map(|s| s.to_string())
        .unwrap_or_else(|| Uuid::new_v4().to_string());
    let file_name = path
        .file_name()
        .and_then(|s| s.to_str())
        .unwrap_or("file")
        .to_string();
    let url = format!("{}/index", smart_url(&node));
    let mut total_indexed = 0u64;
    let mut total_cost = 0.0;
    let mut last_result = json!({});
    // Embed + encrypt + upload in small batches so peak RAM stays bounded.
    for (batch_i, batch) in chunks.chunks(INDEX_UPLOAD_BATCH).enumerate() {
        let embeddings = match embed::embed_texts(batch) {
            Ok(v) => v,
            Err(e) => return fail("embed_failed", e),
        };
        let mut encrypted_chunks = Vec::with_capacity(batch.len());
        let base_idx = batch_i * INDEX_UPLOAD_BATCH;
        for (j, (chunk_text, embedding)) in batch.iter().zip(embeddings.iter()).enumerate() {
            let blob = match aes_gcm_encrypt(&key, chunk_text.as_bytes()) {
                Ok(b) => b,
                Err(e) => return fail("crypto", e),
            };
            encrypted_chunks.push(json!({
                "chunk_index": base_idx + j,
                "embedding": embedding,
                "encrypted_text": STANDARD.encode(blob),
                "text_hash": sha256_hex(chunk_text.as_bytes()),
            }));
        }
        let payload = json!({
            "file_id": file_id,
            "file_name": file_name,
            "wallet_address": wallet.address,
            "chunks": encrypted_chunks,
        });
        let (status, result, resp_text) = match http::post_json(&url, &payload, 180) {
            Ok(t) => t,
            Err(e) => return fail("node_unreachable", e),
        };
        if status != 200 {
            return fail(
                "smart_http",
                format!(
                    "index batch {batch_i} status {status}: {}",
                    resp_text.chars().take(400).collect::<String>()
                ),
            );
        }
        total_indexed += result.get("chunks_indexed").and_then(|v| v.as_u64()).unwrap_or(0);
        total_cost += result.get("total_cost").and_then(|v| v.as_f64()).unwrap_or(0.0);
        last_result = result;
    }
    let info = http::get_json(&format!("{}/info", smart_url(&node)), 5).unwrap_or(json!({}));
    let node_id = info
        .get("node_id")
        .or_else(|| node.get("node_id"))
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let node_wallet = info
        .get("wallet_address")
        .or_else(|| node.get("wallet_address"))
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let mut tx_info = json!(null);
    let mut tx_hash = json!(null);
    if let Ok(tx) = build_smart_index_tx(&wallet, &file_id, node_id, node_wallet, total_indexed, total_cost)
    {
        tx_info = send_raw_tx(&tx);
        if tx_info.get("ok") == Some(&json!(true)) {
            tx_hash = tx.get("tx_hash").cloned().unwrap_or(json!(null));
        }
    }
    json!({
        "ok": true,
        "file_id": file_id,
        "result": last_result,
        "tx": tx_info,
        "tx_hash": tx_hash,
        "cost": total_cost,
        "chunks": total_indexed,
        "truncated": truncated,
        "chunk_capped": chunk_capped,
        "max_chunks": MAX_INDEX_CHUNKS,
    })
}

pub fn index_estimate(params: &Value) -> Value {
    let path = PathBuf::from(params.get("path").and_then(|v| v.as_str()).unwrap_or(""));
    if !path.is_file() {
        return fail("file_not_found", format!("file not found: {}", path.display()));
    }
    let node = params.get("node").cloned().unwrap_or(json!({}));
    if node_is_local(&node) {
        return fail("local_no_index", "Local MiniCPM does not index network workspaces");
    }
    let raw = match read_text(&path) {
        Ok(t) => t,
        Err(e) => return fail("extract", e),
    };
    let (text, truncated) = prepare_index_text(raw);
    let mut chunks = split_into_rag_chunks(&text, 800, 100, 50);
    let full_chunks = chunks.len();
    let chunk_capped = chunks.len() > MAX_INDEX_CHUNKS;
    if chunk_capped {
        chunks.truncate(MAX_INDEX_CHUNKS);
    }
    let price = node
        .get("price_per_embedding")
        .and_then(|v| v.as_f64())
        .unwrap_or(0.0);
    json!({
        "ok": true,
        "chunks": chunks.len(),
        "chunks_full": full_chunks,
        "price_per_embedding": price,
        "estimated_cost": price * chunks.len() as f64,
        "file_name": path.file_name().and_then(|s| s.to_str()),
        "truncated": truncated,
        "chunk_capped": chunk_capped,
        "max_chunks": MAX_INDEX_CHUNKS,
        "max_chars": MAX_INDEX_CHARS,
        "hint": if truncated || chunk_capped {
            "Large file: only the first part will be indexed for Ask (RAG). Use Files → Upload to store the full encrypted asset."
        } else {
            "Indexing embeds text for Ask. General questions do not require indexing."
        },
    })
}

fn read_text(path: &PathBuf) -> Result<String, String> {
    let suffix = path
        .extension()
        .and_then(|s| s.to_str())
        .unwrap_or("")
        .to_lowercase();
    if suffix == "pdf" {
        pdf_extract::extract_text(path).map_err(|e| e.to_string())
    } else {
        std::fs::read_to_string(path).map_err(|e| e.to_string())
    }
}

pub fn workspace_stats(params: &Value) -> Value {
    let wallet = match require_wallet() {
        Ok(w) => w,
        Err(e) => return json!({"ok": false, "error": e}),
    };
    let node = params.get("node").cloned().unwrap_or(json!({}));
    let url = format!("{}/workspace/stats", smart_url(&node));
    match http::get_json_query(&url, &[("wallet_address", wallet.address.clone())], 8) {
        Ok(v) => {
            let mut out = json!({"ok": true});
            if let Some(obj) = out.as_object_mut() {
                if let Some(src) = v.as_object() {
                    for (k, val) in src {
                        obj.insert(k.clone(), val.clone());
                    }
                }
            }
            out
        }
        Err(e) => json!({"ok": false, "error": e}),
    }
}

pub fn knowledge_search(params: &Value) -> Value {
    let node = params.get("node").cloned().unwrap_or(json!({}));
    let q = params.get("query").and_then(|v| v.as_str()).unwrap_or("");
    let limit = params.get("limit").and_then(|v| v.as_u64()).unwrap_or(20);
    let mut query: Vec<(String, String)> = vec![
        ("q".into(), q.to_string()),
        ("limit".into(), limit.to_string()),
    ];
    if let Some(tags) = params.get("tags").and_then(|v| v.as_array()) {
        let joined: Vec<&str> = tags.iter().filter_map(|t| t.as_str()).collect();
        if !joined.is_empty() {
            query.push(("tags".into(), joined.join(",")));
        }
    }
    let url = format!("{}/marketplace/search", smart_url(&node));
    let qref: Vec<(&str, String)> = query.iter().map(|(k, v)| (k.as_str(), v.clone())).collect();
    match http::get_json_query(&url, &qref, 12) {
        Ok(data) => json!({"ok": true, "listings": data.get("listings").cloned().unwrap_or(json!([]))}),
        Err(e) => json!({"ok": false, "error": e}),
    }
}

pub fn knowledge_mine(params: &Value) -> Value {
    let wallet = match require_wallet() {
        Ok(w) => w,
        Err(e) => return json!({"ok": false, "error": e}),
    };
    let node = params.get("node").cloned().unwrap_or(json!({}));
    let url = format!("{}/marketplace/my", smart_url(&node));
    match http::get_json_query(&url, &[("seller_address", wallet.address)], 12) {
        Ok(data) => json!({"ok": true, "listings": data.get("listings").cloned().unwrap_or(json!([]))}),
        Err(e) => json!({"ok": false, "error": e}),
    }
}

fn signed_seller_body(wallet: &Wallet, action: &str, listing_id: &str) -> Result<Value, String> {
    let ts = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_err(|e| e.to_string())?
        .as_secs();
    let message = format!("beez-marketplace:{action}:{listing_id}:{}:{ts}", wallet.address);
    let sig = sign_der(&wallet.privkey, message.as_bytes())?;
    Ok(json!({
        "seller_address": wallet.address,
        "ts": ts,
        "pub": wallet.pubkey_hex()?,
        "sig": hex::encode(sig),
    }))
}

fn listing_mutation(params: &Value, action: &str) -> Value {
    let wallet = match require_wallet() {
        Ok(w) => w,
        Err(e) => return fail("no_wallet", e),
    };
    let node = params.get("node").cloned().unwrap_or(json!({}));
    let listing_id = params.get("listing_id").and_then(|v| v.as_str()).unwrap_or("");
    if listing_id.is_empty() {
        return fail("bad_request", "listing_id required");
    }
    let mut body = match signed_seller_body(&wallet, action, listing_id) {
        Ok(b) => b,
        Err(e) => return fail("crypto", e),
    };
    let method = if action == "delete" {
        reqwest::Method::DELETE
    } else {
        if let (Some(dst), Some(fields)) = (
            body.as_object_mut(),
            params.get("fields").and_then(|v| v.as_object()),
        ) {
            for key in ["title", "description", "tags", "price_per_query", "purchase_price", "status"] {
                if let Some(v) = fields.get(key) {
                    dst.insert(key.into(), v.clone());
                }
            }
        }
        reqwest::Method::PUT
    };
    let url = format!("{}/marketplace/listing/{listing_id}", smart_url(&node));
    match http::send_json(method, &url, &body, 15) {
        Ok((200, _, _)) => json!({"ok": true, "listing_id": listing_id}),
        Ok((status, v, raw)) => fail(
            "rejected",
            v.get("error")
                .and_then(|e| e.as_str())
                .map(|s| s.to_string())
                .unwrap_or_else(|| format!("{status}: {}", raw.chars().take(300).collect::<String>())),
        ),
        Err(e) => fail("unreachable", e),
    }
}

pub fn knowledge_update(params: &Value) -> Value {
    listing_mutation(params, "update")
}

pub fn knowledge_delete(params: &Value) -> Value {
    listing_mutation(params, "delete")
}

pub fn workspace_remove(params: &Value) -> Value {
    let wallet = match require_wallet() {
        Ok(w) => w,
        Err(e) => return fail("no_wallet", e),
    };
    let node = params.get("node").cloned().unwrap_or(json!({}));
    let file_id = params.get("file_id").and_then(|v| v.as_str()).unwrap_or("");
    if file_id.is_empty() {
        return fail("bad_request", "file_id required");
    }
    let url = format!(
        "{}/workspace/{file_id}?wallet_address={}",
        smart_url(&node),
        wallet.address
    );
    match http::send_json(reqwest::Method::DELETE, &url, &json!({}), 15) {
        Ok((200, _, _)) => json!({"ok": true, "file_id": file_id}),
        Ok((status, v, _)) => fail(
            "rejected",
            v.get("error").and_then(|e| e.as_str()).unwrap_or(&format!("HTTP {status}")).to_string(),
        ),
        Err(e) => fail("unreachable", e),
    }
}

pub fn knowledge_query(params: &Value) -> Value {
    let wallet = match require_wallet() {
        Ok(w) => w,
        Err(e) => return json!({"ok": false, "error": e}),
    };
    let node = params.get("node").cloned().unwrap_or(json!({}));
    let listing_id = params.get("listing_id").and_then(|v| v.as_str()).unwrap_or("");
    let text = params.get("query_text").and_then(|v| v.as_str()).unwrap_or("");
    if let Err(e) = embed::ensure() {
        return json!({"ok": false, "error": e});
    }
    let vector = match embed::embed_query(text) {
        Ok(v) => v,
        Err(e) => return json!({"ok": false, "error": e}),
    };
    let payload = json!({
        "listing_id": listing_id,
        "query_text": text,
        "query_vector": vector,
        "buyer_address": wallet.address,
        "top_k": 5,
    });
    let url = format!("{}/marketplace/query", smart_url(&node));
    let (status, mut result, raw) = match http::post_json(&url, &payload, 120) {
        Ok(t) => t,
        Err(e) => return json!({"ok": false, "error": e}),
    };
    if status != 200 {
        return json!({"ok": false, "error": format!("knowledge query {status}: {}", raw.chars().take(400).collect::<String>())});
    }
    if let Some(obj) = result.as_object_mut() {
        obj.insert("ok".into(), json!(true));
    }
    let listing = http::get_json(
        &format!("{}/marketplace/listing/{listing_id}", smart_url(&node)),
        5,
    )
    .unwrap_or(json!({}));
    let info = http::get_json(&format!("{}/info", smart_url(&node)), 5).unwrap_or(json!({}));
    let seller = listing
        .get("seller_address")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let qh = result.get("query_hash").and_then(|v| v.as_str()).unwrap_or("");
    let ah = result.get("answer_hash").and_then(|v| v.as_str()).unwrap_or("");
    let cost = result.get("cost").and_then(|v| v.as_f64()).unwrap_or(0.0);
    let node_id = info.get("node_id").or_else(|| node.get("node_id")).and_then(|v| v.as_str()).unwrap_or("");
    let node_wallet = info
        .get("wallet_address")
        .or_else(|| node.get("wallet_address"))
        .and_then(|v| v.as_str())
        .unwrap_or("");
    match build_knowledge_query_tx(&wallet, seller, listing_id, qh, ah, cost, node_id, node_wallet) {
        Ok(tx) => {
            let tx_info = send_raw_tx(&tx);
            if let Some(obj) = result.as_object_mut() {
                if tx_info.get("ok") == Some(&json!(true)) {
                    obj.insert("tx_hash".into(), tx.get("tx_hash").cloned().unwrap_or(json!(null)));
                }
                obj.insert("tx".into(), tx_info);
            }
        }
        Err(e) => {
            if let Some(obj) = result.as_object_mut() {
                obj.insert("tx".into(), json!({"ok": false, "error": e}));
            }
        }
    }
    result
}

pub fn knowledge_purchase(params: &Value) -> Value {
    let wallet = match require_wallet() {
        Ok(w) => w,
        Err(e) => return json!({"ok": false, "error": e}),
    };
    let node = params.get("node").cloned().unwrap_or(json!({}));
    let listing_id = params.get("listing_id").and_then(|v| v.as_str()).unwrap_or("");
    if listing_id.is_empty() {
        return json!({"ok": false, "error": "listing_id required"});
    }
    let base = smart_url(&node);
    let listing = match http::get_json(&format!("{base}/marketplace/listing/{listing_id}"), 8) {
        Ok(v) => v,
        Err(e) => return json!({"ok": false, "error": e}),
    };
    let seller = listing
        .get("seller_address")
        .and_then(|v| v.as_str())
        .unwrap_or("");
    let price = listing
        .get("purchase_price")
        .and_then(|v| v.as_f64())
        .unwrap_or(0.0);
    if price <= 0.0 {
        return json!({"ok": false, "error": "This listing is not for sale (purchase_price=0)"});
    }
    let file_ids: Vec<String> = listing
        .get("file_ids")
        .and_then(|v| v.as_array())
        .map(|a| {
            a.iter()
                .filter_map(|x| x.as_str().map(|s| s.to_string()))
                .collect()
        })
        .unwrap_or_default();
    let payload = json!({
        "listing_id": listing_id,
        "buyer_address": wallet.address,
    });
    let (status, mut result, raw) =
        match http::post_json(&format!("{base}/marketplace/purchase"), &payload, 60) {
            Ok(t) => t,
            Err(e) => return json!({"ok": false, "error": e}),
        };
    if status != 200 {
        return json!({
            "ok": false,
            "error": format!("purchase {status}: {}", raw.chars().take(400).collect::<String>())
        });
    }
    if let Some(obj) = result.as_object_mut() {
        obj.insert("ok".into(), json!(true));
    }
    match build_knowledge_purchase_tx(&wallet, seller, listing_id, price, &file_ids) {
        Ok(tx) => {
            let tx_info = send_raw_tx(&tx);
            if let Some(obj) = result.as_object_mut() {
                if tx_info.get("ok") == Some(&json!(true)) {
                    obj.insert(
                        "tx_hash".into(),
                        tx.get("tx_hash").cloned().unwrap_or(json!(null)),
                    );
                }
                obj.insert("tx".into(), tx_info);
            }
        }
        Err(e) => {
            if let Some(obj) = result.as_object_mut() {
                obj.insert("tx".into(), json!({"ok": false, "error": e}));
            }
        }
    }
    result
}

pub fn knowledge_publish(params: &Value) -> Value {
    let wallet = match require_wallet() {
        Ok(w) => w,
        Err(e) => return json!({"ok": false, "error": e}),
    };
    let node = params.get("node").cloned().unwrap_or(json!({}));
    let key = match derive_encryption_key(&wallet.privkey) {
        Ok(k) => k,
        Err(e) => return json!({"ok": false, "error": e}),
    };
    let listing_id = Uuid::new_v4().to_string();
    let title = params.get("title").and_then(|v| v.as_str()).unwrap_or("Untitled");
    let file_ids = params.get("file_ids").cloned().unwrap_or(json!([]));
    let payload = json!({
        "listing_id": listing_id,
        "seller_address": wallet.address,
        "title": title,
        "description": params.get("description").and_then(|v| v.as_str()).unwrap_or(""),
        "tags": params.get("tags").cloned().unwrap_or(json!([])),
        "price_per_query": params.get("price_per_query").and_then(|v| v.as_f64()).unwrap_or(1.0),
        "purchase_price": params.get("purchase_price").and_then(|v| v.as_f64()).unwrap_or(0.0),
        "file_ids": file_ids,
        "marketplace_key": STANDARD.encode(key),
    });
    let url = format!("{}/marketplace/publish", smart_url(&node));
    let (status, mut result, raw) = match http::post_json(&url, &payload, 30) {
        Ok(t) => t,
        Err(e) => return json!({"ok": false, "error": e}),
    };
    if status != 200 {
        return json!({"ok": false, "error": format!("publish {status}: {}", raw.chars().take(400).collect::<String>())});
    }
    if let Some(obj) = result.as_object_mut() {
        obj.insert("ok".into(), json!(true));
    }
    let lid = result
        .get("listing_id")
        .and_then(|v| v.as_str())
        .unwrap_or(&listing_id)
        .to_string();
    let info = http::get_json(&format!("{}/info", smart_url(&node)), 5).unwrap_or(json!({}));
    let node_id = info.get("node_id").or_else(|| node.get("node_id")).and_then(|v| v.as_str()).unwrap_or("");
    let file_count = result
        .get("total_files")
        .and_then(|v| v.as_u64())
        .unwrap_or_else(|| file_ids.as_array().map(|a| a.len() as u64).unwrap_or(0));
    let chunk_count = result.get("total_chunks").and_then(|v| v.as_u64()).unwrap_or(0);
    let price = params.get("price_per_query").and_then(|v| v.as_f64()).unwrap_or(1.0);
    let purchase = params.get("purchase_price").and_then(|v| v.as_f64()).unwrap_or(0.0);
    match build_knowledge_publish_tx(&wallet, &lid, node_id, title, file_count, chunk_count, price, purchase)
    {
        Ok(tx) => {
            let tx_info = send_raw_tx(&tx);
            if let Some(obj) = result.as_object_mut() {
                if tx_info.get("ok") == Some(&json!(true)) {
                    obj.insert("tx_hash".into(), tx.get("tx_hash").cloned().unwrap_or(json!(null)));
                }
                obj.insert("tx".into(), tx_info);
            }
        }
        Err(e) => {
            if let Some(obj) = result.as_object_mut() {
                obj.insert("tx".into(), json!({"ok": false, "error": e}));
            }
        }
    }
    result
}
