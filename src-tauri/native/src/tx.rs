use serde_json::{json, Map, Value};
use uuid::Uuid;

use crate::crypto::{canonicalize_and_sign, chain_timestamp, py_float_str, sha256_hex, unix_nonce, utc_timestamp};
use crate::http;
use crate::nodes::chain_http_urls;
use crate::wallet::Wallet;

pub fn send_raw_tx(tx: &Value) -> Value {
    send_raw_tx_timeout(tx, 10)
}

pub fn send_raw_tx_timeout(tx: &Value, timeout_secs: u64) -> Value {
    let mut last = json!({"error": "no chain node"});
    for base in chain_http_urls() {
        let url = format!("{base}/transactions");
        match http::post_json(&url, tx, timeout_secs) {
            Ok((200, body, _)) => {
                return json!({"ok": true, "tx_hash": tx.get("tx_hash"), "body": body});
            }
            Ok((status, _, text)) => {
                last = json!({"status": status, "body": text.chars().take(400).collect::<String>()});
            }
            Err(e) => last = json!({"error": e}),
        }
    }
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

pub fn build_knowledge_purchase_tx(
    wallet: &Wallet,
    seller_address: &str,
    listing_id: &str,
    purchase_price: f64,
    file_ids: &[String],
) -> Result<Value, String> {
    let timestamp = utc_timestamp();
    let nonce = Uuid::new_v4().to_string();
    let mut ids: Vec<String> = file_ids.to_vec();
    ids.sort();
    let file_ids_str = ids.join(",");
    // Match BeezShared knowledge_client: raw float str in payload (e.g. "100.0")
    let payload = format!(
        "{}|{}|{}|{}|{}|{}",
        wallet.address,
        seller_address,
        listing_id,
        purchase_price,
        file_ids_str,
        timestamp
    );
    let tx_hash = sha256_hex(payload.as_bytes());
    let mut tx = Map::new();
    tx.insert("type".into(), json!("knowledge_purchase"));
    tx.insert("nonce".into(), json!(nonce));
    tx.insert("buyer_address".into(), json!(wallet.address));
    tx.insert("seller_address".into(), json!(seller_address));
    tx.insert("listing_id".into(), json!(listing_id));
    insert_num(&mut tx, "purchase_price", purchase_price);
    tx.insert("file_ids".into(), json!(ids));
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
            "purchase_price",
            "file_ids",
            "timestamp",
            "tx_hash",
        ],
    )?;
    Ok(Value::Object(tx))
}

fn price_bzt(asking_price: f64) -> String {
    if asking_price > 0.0 {
        format!("{asking_price:.6} BZT")
    } else {
        "0 BZT".into()
    }
}

/// Ownership request signed by either party: the owner offering the file
/// (`current_owner == wallet.address`) or a buyer asking to purchase it
/// (`new_owner == wallet.address`).
pub fn build_ownership_request_tx(
    wallet: &Wallet,
    file_id: &str,
    current_owner: &str,
    new_owner: &str,
    asking_price: f64,
    message: &str,
    wrapped_file_key: Option<&str>,
    wrap_nonce: Option<&str>,
    encryption_nonce: Option<&str>,
) -> Result<Value, String> {
    let timestamp = chain_timestamp();
    let nonce = unix_nonce();
    let price = price_bzt(asking_price);
    let payload = format!(
        "{}|{}|{}|{}|{}",
        current_owner, new_owner, file_id, price, timestamp
    );
    let tx_hash = sha256_hex(payload.as_bytes());
    let mut tx = Map::new();
    tx.insert("type".into(), json!("ownership_request"));
    tx.insert("nonce".into(), json!(nonce));
    tx.insert("file_id".into(), json!(file_id));
    tx.insert("current_owner".into(), json!(current_owner));
    tx.insert("new_owner".into(), json!(new_owner));
    tx.insert("asking_price".into(), json!(price));
    tx.insert("timestamp".into(), json!(timestamp));
    tx.insert("tx_hash".into(), json!(tx_hash));
    if !message.is_empty() {
        tx.insert("ownership_message".into(), json!(message));
    }
    if let Some(k) = wrapped_file_key {
        tx.insert("wrapped_file_key".into(), json!(k));
    }
    if let Some(n) = wrap_nonce {
        tx.insert("wrap_nonce".into(), json!(n));
    }
    if let Some(n) = encryption_nonce {
        tx.insert("file_encryption_nonce".into(), json!(n));
    }
    let pubhex = wallet.pubkey_hex()?;
    if current_owner == wallet.address {
        tx.insert("seller_pubkey".into(), json!(pubhex.clone()));
    }
    canonicalize_and_sign(
        &mut tx,
        &wallet.privkey,
        &pubhex,
        &[
            "type",
            "nonce",
            "file_id",
            "current_owner",
            "new_owner",
            "asking_price",
            "ownership_message",
            "timestamp",
            "tx_hash",
        ],
    )?;
    Ok(Value::Object(tx))
}

pub fn build_ownership_accept_tx(
    wallet: &Wallet,
    request_id: &str,
    file_id: &str,
    new_owner: &str,
    asking_price: f64,
    message: &str,
    current_owner: Option<&str>,
    wrapped_file_key: Option<&str>,
    wrap_nonce: Option<&str>,
    encryption_nonce: Option<&str>,
) -> Result<Value, String> {
    let timestamp = chain_timestamp();
    let nonce = unix_nonce();
    let price = price_bzt(asking_price);
    let payload = format!(
        "{}|{}|{}|{}|{}",
        new_owner, request_id, file_id, price, timestamp
    );
    let tx_hash = sha256_hex(payload.as_bytes());
    let mut tx = Map::new();
    tx.insert("type".into(), json!("ownership_accept"));
    tx.insert("nonce".into(), json!(nonce));
    tx.insert("request_id".into(), json!(request_id));
    tx.insert("file_id".into(), json!(file_id));
    tx.insert("new_owner".into(), json!(new_owner));
    tx.insert("asking_price".into(), json!(price));
    tx.insert("timestamp".into(), json!(timestamp));
    tx.insert("tx_hash".into(), json!(tx_hash));
    if !message.is_empty() {
        tx.insert("ownership_message".into(), json!(message));
    }
    if let Some(owner) = current_owner {
        tx.insert("current_owner".into(), json!(owner));
    }
    if let Some(k) = wrapped_file_key {
        tx.insert("wrapped_file_key".into(), json!(k));
        if let Some(n) = wrap_nonce {
            tx.insert("wrap_nonce".into(), json!(n));
        }
        if let Some(n) = encryption_nonce {
            tx.insert("file_encryption_nonce".into(), json!(n));
        }
        let pubhex = wallet.pubkey_hex()?;
        tx.insert("seller_pubkey".into(), json!(pubhex));
    }
    let pubhex = wallet.pubkey_hex()?;
    canonicalize_and_sign(
        &mut tx,
        &wallet.privkey,
        &pubhex,
        &[
            "type",
            "nonce",
            "request_id",
            "file_id",
            "new_owner",
            "asking_price",
            "ownership_message",
            "timestamp",
            "tx_hash",
        ],
    )?;
    Ok(Value::Object(tx))
}

pub fn build_ownership_reject_tx(
    wallet: &Wallet,
    request_id: &str,
    file_id: &str,
    message: &str,
) -> Result<Value, String> {
    let timestamp = chain_timestamp();
    let nonce = unix_nonce();
    let payload = format!(
        "{}|{}|{}|{}",
        wallet.address, request_id, file_id, timestamp
    );
    let tx_hash = sha256_hex(payload.as_bytes());
    let mut tx = Map::new();
    tx.insert("type".into(), json!("ownership_reject"));
    tx.insert("nonce".into(), json!(nonce));
    tx.insert("request_id".into(), json!(request_id));
    tx.insert("file_id".into(), json!(file_id));
    tx.insert("new_owner".into(), json!(wallet.address));
    tx.insert("timestamp".into(), json!(timestamp));
    tx.insert("tx_hash".into(), json!(tx_hash));
    if !message.is_empty() {
        tx.insert("ownership_message".into(), json!(message));
    }
    let pubhex = wallet.pubkey_hex()?;
    canonicalize_and_sign(
        &mut tx,
        &wallet.privkey,
        &pubhex,
        &[
            "type",
            "nonce",
            "request_id",
            "file_id",
            "new_owner",
            "ownership_message",
            "timestamp",
            "tx_hash",
        ],
    )?;
    Ok(Value::Object(tx))
}

pub fn build_ownership_cancel_tx(
    wallet: &Wallet,
    request_id: &str,
    file_id: &str,
) -> Result<Value, String> {
    let timestamp = chain_timestamp();
    let nonce = unix_nonce();
    let payload = format!(
        "{}|{}|{}|{}",
        wallet.address, request_id, file_id, timestamp
    );
    let tx_hash = sha256_hex(payload.as_bytes());
    let mut tx = Map::new();
    tx.insert("type".into(), json!("ownership_cancel"));
    tx.insert("nonce".into(), json!(nonce));
    tx.insert("request_id".into(), json!(request_id));
    tx.insert("file_id".into(), json!(file_id));
    tx.insert("current_owner".into(), json!(wallet.address));
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
            "request_id",
            "file_id",
            "current_owner",
            "timestamp",
            "tx_hash",
        ],
    )?;
    Ok(Value::Object(tx))
}

/// Owner sets the marketplace asking price of an asset.
pub fn build_asset_price_tx(
    wallet: &Wallet,
    file_id: &str,
    new_price: f64,
    old_price: f64,
) -> Result<Value, String> {
    let timestamp = chain_timestamp();
    let new_price = format!("{new_price:.6} BZT");
    let payload = format!("{}|{}|{}|{}", wallet.address, file_id, new_price, timestamp);
    let mut tx = Map::new();
    tx.insert("type".into(), json!("update_digital_asset_price"));
    tx.insert("nonce".into(), json!(unix_nonce()));
    tx.insert("file_id".into(), json!(file_id));
    tx.insert("owner_address".into(), json!(wallet.address));
    tx.insert("new_price".into(), json!(new_price));
    tx.insert("old_price".into(), json!(format!("{old_price:.6} BZT")));
    tx.insert("timestamp".into(), json!(timestamp));
    tx.insert("tx_hash".into(), json!(sha256_hex(payload.as_bytes())));
    let pubhex = wallet.pubkey_hex()?;
    canonicalize_and_sign(
        &mut tx,
        &wallet.privkey,
        &pubhex,
        &[
            "type",
            "nonce",
            "file_id",
            "owner_address",
            "new_price",
            "old_price",
            "update_reason",
            "timestamp",
            "tx_hash",
        ],
    )?;
    Ok(Value::Object(tx))
}

/// Owner lists (`public`) or unlists (`private`) an asset on the marketplace.
pub fn build_asset_visibility_tx(
    wallet: &Wallet,
    file_id: &str,
    visibility: &str,
) -> Result<Value, String> {
    let timestamp = chain_timestamp();
    let payload = format!("{}|{}|{}|{}", wallet.address, file_id, visibility, timestamp);
    let mut tx = Map::new();
    tx.insert("type".into(), json!("update_digital_asset_visibility"));
    tx.insert("nonce".into(), json!(unix_nonce()));
    tx.insert("file_id".into(), json!(file_id));
    tx.insert("owner_address".into(), json!(wallet.address));
    tx.insert("visibility".into(), json!(visibility));
    tx.insert("timestamp".into(), json!(timestamp));
    tx.insert("tx_hash".into(), json!(sha256_hex(payload.as_bytes())));
    let pubhex = wallet.pubkey_hex()?;
    canonicalize_and_sign(
        &mut tx,
        &wallet.privkey,
        &pubhex,
        &[
            "type",
            "nonce",
            "file_id",
            "owner_address",
            "visibility",
            "update_reason",
            "timestamp",
            "tx_hash",
        ],
    )?;
    Ok(Value::Object(tx))
}

pub fn build_upload_tx(
    wallet: &Wallet,
    file_id: &str,
    file_name: &str,
    file_size: u64,
    num_chunks: u64,
    chunk_locations: &Value,
    backup_chunk_locations: &Value,
    storage_duration: i64,
    query_hash: &str,
    encryption_nonce: &str,
    guardian_dam_id: Option<&str>,
    visibility: &str,
    sell_price: f64,
    tags: &[String],
    extension: &str,
    amount_bzt: f64,
) -> Result<Value, String> {
    let timestamp = chain_timestamp();
    let nonce = unix_nonce();
    let amount = format!("{amount_bzt:.6} BZT");
    let guardian = guardian_dam_id.unwrap_or("");
    let payload = format!(
        "{}|{}|{}|{}|{}|{}|{}",
        wallet.address, file_id, file_name, amount, storage_duration, guardian, timestamp
    );
    let tx_hash = sha256_hex(payload.as_bytes());
    let mut tx = Map::new();
    tx.insert("type".into(), json!("upload"));
    tx.insert("nonce".into(), json!(nonce));
    tx.insert("uploader".into(), json!(wallet.address));
    tx.insert("sender".into(), json!(wallet.address));
    tx.insert("amount".into(), json!(amount));
    tx.insert("file_id".into(), json!(file_id));
    tx.insert("file_name".into(), json!(file_name));
    tx.insert("file_size".into(), json!(file_size));
    tx.insert("num_chunks".into(), json!(num_chunks));
    tx.insert("chunk_locations".into(), chunk_locations.clone());
    tx.insert("backup_chunk_locations".into(), backup_chunk_locations.clone());
    tx.insert("storage_duration".into(), json!(storage_duration));
    tx.insert("query_hash".into(), json!(query_hash));
    tx.insert("encryption_nonce".into(), json!(encryption_nonce));
    tx.insert("visibility".into(), json!(visibility));
    tx.insert("timestamp".into(), json!(timestamp));
    tx.insert("tx_hash".into(), json!(tx_hash));
    if !guardian.is_empty() {
        tx.insert("guardian_dam_id".into(), json!(guardian));
    }
    if !extension.is_empty() {
        tx.insert("extension".into(), json!(extension));
    }
    if sell_price > 0.0 {
        let price_str = format!("{sell_price:.6} BZT");
        tx.insert("new_price".into(), json!(price_str.clone()));
        tx.insert("marketplace_price".into(), json!(price_str));
    }
    if !tags.is_empty() {
        tx.insert("tags".into(), json!(tags));
    }
    let pubhex = wallet.pubkey_hex()?;
    canonicalize_and_sign(
        &mut tx,
        &wallet.privkey,
        &pubhex,
        &[
            "type",
            "nonce",
            "amount",
            "uploader",
            "file_id",
            "file_name",
            "file_size",
            "num_chunks",
            "chunk_locations",
            "backup_chunk_locations",
            "storage_duration",
            "query_hash",
            "encryption_nonce",
            "guardian_dam_id",
            "timestamp",
            "tx_hash",
        ],
    )?;
    Ok(Value::Object(tx))
}

#[cfg(test)]
mod tests {
    use super::*;

    const FILE_ID: &str = "0b9f3c2e-6a51-4f1e-9d7a-2c4b8e1f5a60";

    fn field<'a>(tx: &'a Value, key: &str) -> &'a str {
        tx.get(key).and_then(|v| v.as_str()).unwrap_or("")
    }

    #[test]
    fn purchase_request_hash_names_seller_first_and_omits_seller_key() {
        let buyer = Wallet::generate().unwrap();
        let tx = build_ownership_request_tx(&buyer, FILE_ID, "bezSeller", &buyer.address, 12.5, "", None, None, None)
            .unwrap();
        let payload = format!(
            "bezSeller|{}|{FILE_ID}|12.500000 BZT|{}",
            buyer.address,
            field(&tx, "timestamp")
        );
        assert_eq!(field(&tx, "tx_hash"), sha256_hex(payload.as_bytes()));
        assert_eq!(field(&tx, "current_owner"), "bezSeller");
        assert_eq!(field(&tx, "pub"), buyer.pubkey_hex().unwrap());
        assert!(tx.get("seller_pubkey").is_none());

        let offer = build_ownership_request_tx(&buyer, FILE_ID, &buyer.address, "bezOther", 0.0, "", None, None, None)
            .unwrap();
        assert_eq!(field(&offer, "seller_pubkey"), buyer.pubkey_hex().unwrap());
    }

    #[test]
    fn listing_updates_use_chain_hash_payloads() {
        let owner = Wallet::generate().unwrap();
        let price = build_asset_price_tx(&owner, FILE_ID, 3.0, 1.0).unwrap();
        let payload = format!("{}|{FILE_ID}|3.000000 BZT|{}", owner.address, field(&price, "timestamp"));
        assert_eq!(field(&price, "tx_hash"), sha256_hex(payload.as_bytes()));
        assert_eq!(field(&price, "old_price"), "1.000000 BZT");

        let vis = build_asset_visibility_tx(&owner, FILE_ID, "public").unwrap();
        let payload = format!("{}|{FILE_ID}|public|{}", owner.address, field(&vis, "timestamp"));
        assert_eq!(field(&vis, "tx_hash"), sha256_hex(payload.as_bytes()));
        assert_eq!(field(&vis, "owner_address"), owner.address);
    }
}
