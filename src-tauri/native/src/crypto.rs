use aes_gcm::aead::{Aead, KeyInit};
use aes_gcm::{Aes256Gcm, Nonce};
use hkdf::Hkdf;
use k256::ecdsa::signature::hazmat::PrehashSigner;
use k256::ecdsa::{Signature, SigningKey};
use k256::elliptic_curve::sec1::ToEncodedPoint;
use k256::{PublicKey, SecretKey};
use rand::RngCore;
use serde_json::{json, Map, Value};
use sha1::Sha1;
use sha2::Sha256;

pub const DOMAIN_FILE_ENC: &[u8] = b"beez-file-enc-v1";
pub const DOMAIN_ECDH_WRAP: &[u8] = b"beez-ecdh-wrap-v1";

pub fn derive_encryption_key(privkey: &[u8; 32]) -> Result<[u8; 32], String> {
    let hk = Hkdf::<Sha256>::new(None, privkey);
    let mut out = [0u8; 32];
    hk.expand(DOMAIN_FILE_ENC, &mut out)
        .map_err(|e| format!("hkdf: {e}"))?;
    Ok(out)
}

/// Derive ECDH shared wrap key: secp256k1 ECDH x-coordinate → HKDF-SHA256.
///
/// Matches `shared.client_core.rekey.derive_shared_key_ecdh`.
pub fn derive_shared_key_ecdh(own_privkey: &[u8; 32], other_pubkey_xy: &[u8]) -> Result<[u8; 32], String> {
    if other_pubkey_xy.len() != 64 {
        return Err(format!(
            "other pubkey must be 64-byte uncompressed x||y, got {}",
            other_pubkey_xy.len()
        ));
    }
    let mut sec1 = [0u8; 65];
    sec1[0] = 0x04;
    sec1[1..].copy_from_slice(other_pubkey_xy);
    let sk = SecretKey::from_slice(own_privkey).map_err(|e| format!("ecdh secret: {e}"))?;
    let pk = PublicKey::from_sec1_bytes(&sec1).map_err(|e| format!("ecdh pubkey: {e}"))?;
    let shared = k256::ecdh::diffie_hellman(sk.to_nonzero_scalar(), pk.as_affine());
    let shared_x = shared.raw_secret_bytes();
    let hk = Hkdf::<Sha256>::new(None, shared_x.as_slice());
    let mut out = [0u8; 32];
    hk.expand(DOMAIN_ECDH_WRAP, &mut out)
        .map_err(|e| format!("ecdh hkdf: {e}"))?;
    Ok(out)
}

/// Wrap a 32-byte file encryption key with an ECDH shared key (AES-GCM).
pub fn wrap_file_key(file_key: &[u8; 32], shared_key: &[u8; 32]) -> Result<(Vec<u8>, [u8; 12]), String> {
    aes_gcm_encrypt_detached(shared_key, file_key)
}

/// Unwrap a file encryption key previously wrapped with ECDH.
pub fn unwrap_file_key(
    wrapped: &[u8],
    wrap_nonce: &[u8; 12],
    shared_key: &[u8; 32],
) -> Result<[u8; 32], String> {
    let plain = aes_gcm_decrypt_detached(shared_key, wrap_nonce, wrapped)?;
    if plain.len() != 32 {
        return Err(format!("unwrapped key length {}, expected 32", plain.len()));
    }
    let mut out = [0u8; 32];
    out.copy_from_slice(&plain);
    Ok(out)
}

/// Encode uncompressed secp256k1 pubkey as 64-byte x||y (no 0x04 prefix).
#[allow(dead_code)]
pub fn pubkey_xy_from_privkey(privkey: &[u8; 32]) -> Result<[u8; 64], String> {
    let sk = SecretKey::from_slice(privkey).map_err(|e| format!("secret: {e}"))?;
    let point = sk.public_key().to_encoded_point(false);
    let bytes = point.as_bytes();
    if bytes.len() != 65 || bytes[0] != 0x04 {
        return Err("unexpected pubkey encoding".into());
    }
    let mut out = [0u8; 64];
    out.copy_from_slice(&bytes[1..]);
    Ok(out)
}

pub fn aes_gcm_encrypt_detached(key: &[u8; 32], plaintext: &[u8]) -> Result<(Vec<u8>, [u8; 12]), String> {
    let cipher = Aes256Gcm::new(key.into());
    let mut nonce_bytes = [0u8; 12];
    rand::thread_rng().fill_bytes(&mut nonce_bytes);
    let nonce = Nonce::from_slice(&nonce_bytes);
    let ct = cipher
        .encrypt(nonce, plaintext)
        .map_err(|e| format!("aes-gcm: {e}"))?;
    Ok((ct, nonce_bytes))
}

pub fn aes_gcm_decrypt_detached(key: &[u8; 32], nonce: &[u8; 12], ciphertext: &[u8]) -> Result<Vec<u8>, String> {
    let cipher = Aes256Gcm::new(key.into());
    cipher
        .decrypt(Nonce::from_slice(nonce), ciphertext.as_ref())
        .map_err(|e| format!("aes-gcm decrypt: {e}"))
}

pub fn aes_gcm_encrypt(key: &[u8; 32], plaintext: &[u8]) -> Result<Vec<u8>, String> {
    let (ct, nonce_bytes) = aes_gcm_encrypt_detached(key, plaintext)?;
    let mut out = Vec::with_capacity(12 + ct.len());
    out.extend_from_slice(&nonce_bytes);
    out.extend_from_slice(&ct);
    Ok(out)
}

pub fn sha256_hex(data: &[u8]) -> String {
    hex::encode(<Sha256 as sha2::Digest>::digest(data))
}

pub fn utc_timestamp() -> String {
    chrono::Utc::now().format("%Y-%m-%dT%H:%M:%S.000Z").to_string()
}

pub fn chain_timestamp() -> String {
    chrono::Utc::now().format("%Y-%m-%d %H:%M:%S UTC+00:00").to_string()
}

pub fn unix_nonce() -> i64 {
    chrono::Utc::now().timestamp()
}

pub fn sign_der(privkey: &[u8; 32], message: &[u8]) -> Result<Vec<u8>, String> {
    let sk = SigningKey::from_bytes(privkey.into()).map_err(|e| format!("sign key: {e}"))?;
    let digest = <Sha1 as sha1::Digest>::digest(message);
    let sig: Signature = sk
        .sign_prehash(&digest)
        .map_err(|e| format!("ecdsa: {e}"))?;
    Ok(sig.to_der().as_bytes().to_vec())
}

fn canonical_value(v: &Value) -> Option<Value> {
    match v {
        Value::Null => None,
        Value::String(s) if s.is_empty() => None,
        Value::Array(a) if a.is_empty() => None,
        other => Some(other.clone()),
    }
}

fn sorted_location_lists(v: &Value) -> Value {
    match v.as_object() {
        Some(map) => Value::Object(
            map.iter()
                .map(|(k, nodes)| {
                    let mut list: Vec<Value> = nodes.as_array().cloned().unwrap_or_default();
                    list.sort_by(|a, b| a.as_str().unwrap_or("").cmp(b.as_str().unwrap_or("")));
                    (k.clone(), Value::Array(list))
                })
                .collect(),
        ),
        None => v.clone(),
    }
}

/// Python `json.dumps(..., ensure_ascii=True)` escaping of non-ASCII characters.
fn ascii_escape(json_text: &str) -> String {
    let mut out = String::with_capacity(json_text.len());
    for ch in json_text.chars() {
        if ch.is_ascii() {
            out.push(ch);
        } else {
            let mut units = [0u16; 2];
            for unit in ch.encode_utf16(&mut units) {
                out.push_str(&format!("\\u{unit:04x}"));
            }
        }
    }
    out
}

/// Bytes the chain verifies: `serialize_tx(canonicalize_for_signature(tx))`.
pub fn canonical_message(tx: &Map<String, Value>, canon_keys: &[&str]) -> Result<Vec<u8>, String> {
    let mut canonical = Map::new();
    for k in canon_keys {
        if let Some(v) = tx.get(*k) {
            if let Some(kept) = canonical_value(v) {
                canonical.insert((*k).to_string(), kept);
            }
        }
    }
    for key in ["chunk_locations", "backup_chunk_locations"] {
        if let Some(v) = canonical.get_mut(key) {
            *v = sorted_location_lists(v);
        }
    }
    if let Some(Value::Array(nodes)) = canonical.get_mut("beneficiary_nodes") {
        nodes.sort_by(|a, b| {
            let id = |v: &Value| v.get("node_id").and_then(|s| s.as_str()).unwrap_or("").to_string();
            id(a).cmp(&id(b))
        });
    }
    let text = serde_json::to_string(&Value::Object(canonical)).map_err(|e| e.to_string())?;
    Ok(ascii_escape(&text).into_bytes())
}

pub fn canonicalize_and_sign(
    tx: &mut Map<String, Value>,
    privkey: &[u8; 32],
    pubkey_hex: &str,
    canon_keys: &[&str],
) -> Result<(), String> {
    let message = canonical_message(tx, canon_keys)?;
    let sig = sign_der(privkey, &message)?;
    tx.insert("sig".into(), json!(hex::encode(sig)));
    tx.insert("pub".into(), json!(pubkey_hex));
    Ok(())
}

pub fn py_float_str(v: f64) -> String {
    let s = format!("{v}");
    if s.contains('.') || s.contains('e') || s.contains('E') {
        s
    } else {
        format!("{v:.1}")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn canonical_message_matches_chain_serializer() {
        let tx = json!({
            "type": "upload", "nonce": 1, "amount": "5.000000 BZT", "uploader": "bezA",
            "file_id": "f1", "file_name": "Università 😀.pdf", "file_size": 10, "num_chunks": 1,
            "chunk_locations": {"f1_chunk_0": ["storage_b", "storage_a"]},
            "backup_chunk_locations": {"f1_chunk_0": ["storage_c", "storage_a"]},
            "storage_duration": 5, "query_hash": "q", "encryption_nonce": "n",
            "guardian_dam_id": "", "timestamp": "t", "tx_hash": "h"
        });
        let keys = [
            "type", "nonce", "amount", "uploader", "file_id", "file_name", "file_size",
            "num_chunks", "chunk_locations", "backup_chunk_locations", "storage_duration",
            "query_hash", "encryption_nonce", "guardian_dam_id", "timestamp", "tx_hash",
        ];
        let got = canonical_message(tx.as_object().unwrap(), &keys).unwrap();
        // Produced by BeezChain: serialize_tx(canonicalize_for_signature(tx)).
        let expected = r#"{"amount":"5.000000 BZT","backup_chunk_locations":{"f1_chunk_0":["storage_a","storage_c"]},"chunk_locations":{"f1_chunk_0":["storage_a","storage_b"]},"encryption_nonce":"n","file_id":"f1","file_name":"Universit\u00e0 \ud83d\ude00.pdf","file_size":10,"nonce":1,"num_chunks":1,"query_hash":"q","storage_duration":5,"timestamp":"t","tx_hash":"h","type":"upload","uploader":"bezA"}"#;
        assert_eq!(String::from_utf8(got).unwrap(), expected);
    }

    #[test]
    fn hkdf_length() {
        let key = derive_encryption_key(&[7u8; 32]).unwrap();
        assert_eq!(key.len(), 32);
        assert_ne!(key, [7u8; 32]);
    }

    #[test]
    fn aes_roundtrip_nonce_prefix() {
        let key = [9u8; 32];
        let blob = aes_gcm_encrypt(&key, b"hello").unwrap();
        assert!(blob.len() > 12 + 16);
    }

    #[test]
    fn ecdh_matches_python_cryptography_vector() {
        let mut priv_a = [0u8; 32];
        priv_a[31] = 0x11;
        let mut priv_b = [0u8; 32];
        priv_b[31] = 0x22;
        let pub_b = hex::decode(
            "1be68a5a028f2601d0e80d468c344ba331d611b96c358b6032e8b4da0547fc11\
             bebc47511ade7308b3ca6265f9400779c076329c75146bc6ff1822f5d1f30e79",
        )
        .unwrap();
        let shared = derive_shared_key_ecdh(&priv_a, &pub_b).unwrap();
        assert_eq!(
            hex::encode(shared),
            "c7d4d9ccb0ae33f9dcad5834027d38a59232f0f462da50b0589cda9df3d4e926"
        );
        let ab = derive_shared_key_ecdh(&priv_a, &pubkey_xy_from_privkey(&priv_b).unwrap()).unwrap();
        let ba = derive_shared_key_ecdh(&priv_b, &pubkey_xy_from_privkey(&priv_a).unwrap()).unwrap();
        assert_eq!(ab, ba);
        let file_key = [0xABu8; 32];
        let (wrapped, nonce) = wrap_file_key(&file_key, &ab).unwrap();
        assert_eq!(unwrap_file_key(&wrapped, &nonce, &ba).unwrap(), file_key);
    }
}
