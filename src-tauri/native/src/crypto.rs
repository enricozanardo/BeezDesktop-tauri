use aes_gcm::aead::{Aead, KeyInit};
use aes_gcm::{Aes256Gcm, Nonce};
use hkdf::Hkdf;
use k256::ecdsa::signature::hazmat::PrehashSigner;
use k256::ecdsa::{Signature, SigningKey};
use rand::RngCore;
use serde_json::{json, Map, Value};
use sha1::Sha1;
use sha2::Sha256;

pub const DOMAIN_FILE_ENC: &[u8] = b"beez-file-enc-v1";

pub fn derive_encryption_key(privkey: &[u8; 32]) -> Result<[u8; 32], String> {
    let hk = Hkdf::<Sha256>::new(None, privkey);
    let mut out = [0u8; 32];
    hk.expand(DOMAIN_FILE_ENC, &mut out)
        .map_err(|e| format!("hkdf: {e}"))?;
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

pub fn canonicalize_and_sign(
    tx: &mut Map<String, Value>,
    privkey: &[u8; 32],
    pubkey_hex: &str,
    canon_keys: &[&str],
) -> Result<(), String> {
    let mut canonical = Map::new();
    for k in canon_keys {
        if let Some(v) = tx.get(*k) {
            if let Some(kept) = canonical_value(v) {
                canonical.insert((*k).to_string(), kept);
            }
        }
    }
    let message = serde_json::to_vec(&Value::Object(canonical)).map_err(|e| e.to_string())?;
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
}
