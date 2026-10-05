use serde_json::{json, Map, Value};
use uuid::Uuid;

use crate::crypto::{canonicalize_and_sign, py_float_str, sha256_hex, utc_timestamp};
use crate::http;
use crate::nodes::{http_url_for, DOCKER_NODE_MAP};
use crate::wallet::Wallet;

pub fn send_raw_tx(tx: &Value) -> Value {
    let mut last = json!({"error": "no chain node"});
    for name in ["chain1", "chain2", "chain3"] {
        let url = format!("{}/transactions", http_url_for(name));
        match http::post_json(&url, tx, 10) {
            Ok((200, body, _)) => {
                return json!({"ok": true, "tx_hash": tx.get("tx_hash"), "body": body});
            }
            Ok((status, _, text)) => {
                last = json!({"status": status, "body": text.chars().take(400).collect::<String>()});
            }
            Err(e) => last = json!({"error": e}),
        }
    }
    // Also try any mapped host even if compose names failed
    let _ = DOCKER_NODE_MAP;
    json!({"ok": false, "error": last})
}

fn insert_num(map: &mut Map<String, Value>, key: &str, v: f64) {
    map.insert(key.into(), json!(v));
}

pub fn build_smart_index_tx(
    wallet: &Wallet,
    file_id: &str,
    smart_node_id: &str,
    smart_node_wallet: &str,
    num_chunks: u64,
    total_cost: f64,
) -> Result<Value, String> {
    let timestamp = utc_timestamp();
    let nonce = Uuid::new_v4().to_string();
    let payload = format!(
        "{}|{}|{}|{}|{}|{}|{}",
        wallet.address,
        file_id,
        smart_node_id,
        smart_node_wallet,
        num_chunks,
        py_float_str(total_cost),
        timestamp
    );
    let tx_hash = sha256_hex(payload.as_bytes());
    let mut tx = Map::new();
    tx.insert("type".into(), json!("smart_index"));
    tx.insert("nonce".into(), json!(nonce));
    tx.insert("file_id".into(), json!(file_id));
    tx.insert("smart_node_id".into(), json!(smart_node_id));
    tx.insert("smart_node_wallet".into(), json!(smart_node_wallet));
    tx.insert("num_chunks_indexed".into(), json!(num_chunks));
    insert_num(&mut tx, "total_cost", total_cost);
    tx.insert("wallet_address".into(), json!(wallet.address));
    tx.insert("timestamp".into(), json!(timestamp));
    tx.insert("tx_hash".into(), json!(tx_hash));
    let pubhex = wallet.pubkey_hex()?;
    canonicalize_and_sign(
        &mut tx,
        &wallet.privkey,
        &pubhex,
        &[
            "type",
            "nonce",
            "file_id",
            "smart_node_id",
            "smart_node_wallet",
            "num_chunks_indexed",
            "total_cost",
            "wallet_address",
            "timestamp",
            "tx_hash",
        ],
    )?;
    Ok(Value::Object(tx))
}

pub fn build_smart_query_tx(
    wallet: &Wallet,
    query_hash: &str,
    answer_hash: &str,
    smart_node_id: &str,
    smart_node_wallet: &str,
    cost: f64,
    file_ids: &[String],
) -> Result<Value, String> {
    let timestamp = utc_timestamp();
    let nonce = Uuid::new_v4().to_string();
    let mut ids = file_ids.to_vec();
    ids.sort();
    let file_ids_str = ids.join(",");
    let payload = format!(
        "{}|{}|{}|{}|{}|{}|{}|{}",
        wallet.address,
        query_hash,
        answer_hash,
        smart_node_id,
        smart_node_wallet,
        py_float_str(cost),
        file_ids_str,
        timestamp
    );
    let tx_hash = sha256_hex(payload.as_bytes());
    let mut tx = Map::new();
    tx.insert("type".into(), json!("smart_query"));
    tx.insert("nonce".into(), json!(nonce));
    tx.insert("query_hash".into(), json!(query_hash));
    tx.insert("answer_hash".into(), json!(answer_hash));
    tx.insert("smart_node_id".into(), json!(smart_node_id));
    tx.insert("smart_node_wallet".into(), json!(smart_node_wallet));
    insert_num(&mut tx, "cost", cost);
    tx.insert("wallet_address".into(), json!(wallet.address));
    tx.insert("file_ids".into(), json!(file_ids));
    tx.insert("timestamp".into(), json!(timestamp));
    tx.insert("tx_hash".into(), json!(tx_hash));
    let pubhex = wallet.pubkey_hex()?;
    canonicalize_and_sign(
        &mut tx,
        &wallet.privkey,
        &pubhex,
        &[
            "type",
            "nonce",
            "query_hash",
            "answer_hash",
            "smart_node_id",
            "smart_node_wallet",
            "cost",
            "wallet_address",
            "file_ids",
            "timestamp",
            "tx_hash",
        ],
    )?;
    Ok(Value::Object(tx))
}

pub fn build_knowledge_query_tx(
    wallet: &Wallet,
    seller_address: &str,
    listing_id: &str,
    query_hash: &str,
    answer_hash: &str,
    cost: f64,
    smart_node_id: &str,
    smart_node_wallet: &str,
) -> Result<Value, String> {
    let timestamp = utc_timestamp();
    let nonce = Uuid::new_v4().to_string();
    let payload = format!(
        "{}|{}|{}|{}|{}|{}|{}|{}|{}",
        wallet.address,
        seller_address,
        listing_id,
        query_hash,
        answer_hash,
        py_float_str(cost),
        smart_node_id,
        smart_node_wallet,
        timestamp
    );
    let tx_hash = sha256_hex(payload.as_bytes());
    let mut tx = Map::new();
    tx.insert("type".into(), json!("knowledge_query"));
    tx.insert("nonce".into(), json!(nonce));
    tx.insert("buyer_address".into(), json!(wallet.address));
    tx.insert("seller_address".into(), json!(seller_address));
    tx.insert("listing_id".into(), json!(listing_id));
    tx.insert("query_hash".into(), json!(query_hash));
    tx.insert("answer_hash".into(), json!(answer_hash));
    insert_num(&mut tx, "cost", cost);
    tx.insert("smart_node_id".into(), json!(smart_node_id));
    tx.insert("smart_node_wallet".into(), json!(smart_node_wallet));
    tx.insert("timestamp".into(), json!(timestamp));
    tx.insert("tx_hash".into(), json!(tx_hash));
    let pubhex = wallet.pubkey_hex()?;
    canonicalize_and_sign(
        &mut tx,
        &wallet.privkey,
        &pubhex,
        &[
            "type",
            "nonce",
            "buyer_address",
            "seller_address",
            "listing_id",
            "query_hash",
            "answer_hash",
            "cost",
            "smart_node_id",
            "smart_node_wallet",
            "timestamp",
            "tx_hash",
        ],
    )?;
    Ok(Value::Object(tx))
}

pub fn build_knowledge_publish_tx(
    wallet: &Wallet,
    listing_id: &str,
    smart_node_id: &str,
    title: &str,
    file_count: u64,
    chunk_count: u64,
    price_per_query: f64,
    purchase_price: f64,
) -> Result<Value, String> {
    let timestamp = utc_timestamp();
    let nonce = Uuid::new_v4().to_string();
    let title_hash = sha256_hex(title.as_bytes());
    let payload = format!(
        "{}|{}|{}|{}|{}|{}|{}|{}|{}",
        wallet.address,
        listing_id,
        smart_node_id,
        title_hash,
        file_count,
        chunk_count,
        py_float_str(price_per_query),
        py_float_str(purchase_price),
        timestamp
    );
    let tx_hash = sha256_hex(payload.as_bytes());
    let mut tx = Map::new();
    tx.insert("type".into(), json!("knowledge_publish"));
    tx.insert("nonce".into(), json!(nonce));
    tx.insert("seller_address".into(), json!(wallet.address));
    tx.insert("listing_id".into(), json!(listing_id));
    tx.insert("smart_node_id".into(), json!(smart_node_id));
    tx.insert("title_hash".into(), json!(title_hash));
    tx.insert("file_count".into(), json!(file_count));
    tx.insert("chunk_count".into(), json!(chunk_count));
    insert_num(&mut tx, "price_per_query", price_per_query);
    insert_num(&mut tx, "purchase_price", purchase_price);
    tx.insert("timestamp".into(), json!(timestamp));
    tx.insert("tx_hash".into(), json!(tx_hash));
    let pubhex = wallet.pubkey_hex()?;
    canonicalize_and_sign(
        &mut tx,
        &wallet.privkey,
        &pubhex,
        &[
            "type",
            "nonce",
            "seller_address",
            "listing_id",
            "smart_node_id",
            "title_hash",
            "file_count",
            "chunk_count",
            "price_per_query",
            "purchase_price",
            "timestamp",
            "tx_hash",
        ],
    )?;
    Ok(Value::Object(tx))
}
