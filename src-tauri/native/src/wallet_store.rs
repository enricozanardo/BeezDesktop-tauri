use std::env;
use std::fs;
use std::path::PathBuf;

use aes::Aes128;
use base64::engine::general_purpose::{STANDARD, URL_SAFE};
use base64::Engine;
use cbc::cipher::{block_padding::Pkcs7, BlockDecryptMut, BlockEncryptMut, KeyIvInit};
use hmac::{Hmac, Mac};
use pbkdf2::pbkdf2_hmac;
use rand::RngCore;
use serde_json::{json, Value};
use sha2::Sha256;

use crate::paths::{data_dir, home_dir, APP_WALLET_NAME, LEGACY_WALLET_NAME};
use crate::wallet::Wallet;

type Aes128CbcEnc = cbc::Encryptor<Aes128>;
type Aes128CbcDec = cbc::Decryptor<Aes128>;
type HmacSha256 = Hmac<Sha256>;

const FERNET_SALT: &[u8] = b"BeezDesktopWalletStorage2024";
const PBKDF2_ITERS: u32 = 100_000;

pub fn wallet_file(app_name: &str) -> PathBuf {
    data_dir(app_name).join("wallet.json")
}

fn machine_id(app_name: &str) -> Vec<u8> {
    let user = env::var("USER").unwrap_or_default();
    let home_env = env::var("HOME").unwrap_or_default();
    let home_path = home_dir().display().to_string();
    format!("{user}|{home_env}|{home_path}|{app_name}").into_bytes()
}

fn fernet_key_bytes(app_name: &str) -> [u8; 32] {
    let mut key = [0u8; 32];
    pbkdf2_hmac::<Sha256>(&machine_id(app_name), FERNET_SALT, PBKDF2_ITERS, &mut key);
    key
}

fn fernet_encrypt(app_name: &str, plaintext: &[u8]) -> Result<Vec<u8>, String> {
    let key = fernet_key_bytes(app_name);
    let signing = &key[..16];
    let encryption = &key[16..];
    let mut iv = [0u8; 16];
    rand::thread_rng().fill_bytes(&mut iv);
    let ciphertext = Aes128CbcEnc::new(encryption.into(), (&iv).into())
        .encrypt_padded_vec_mut::<Pkcs7>(plaintext);
    let ts = chrono::Utc::now().timestamp() as u64;
    let mut raw = Vec::with_capacity(1 + 8 + 16 + ciphertext.len() + 32);
    raw.push(0x80);
    raw.extend_from_slice(&ts.to_be_bytes());
    raw.extend_from_slice(&iv);
    raw.extend_from_slice(&ciphertext);
    let mut mac =
        HmacSha256::new_from_slice(signing).map_err(|e| format!("hmac: {e}"))?;
    mac.update(&raw);
    raw.extend_from_slice(&mac.finalize().into_bytes());
    Ok(URL_SAFE.encode(raw).into_bytes())
}

fn fernet_decrypt(app_name: &str, token: &[u8]) -> Result<Vec<u8>, String> {
    let key = fernet_key_bytes(app_name);
    let signing = &key[..16];
    let encryption = &key[16..];
    let text = std::str::from_utf8(token).unwrap_or("");
    let raw = URL_SAFE
        .decode(text.trim().as_bytes())
        .or_else(|_| STANDARD.decode(token))
        .map_err(|e| format!("fernet b64: {e}"))?;
    if raw.len() < 1 + 8 + 16 + 32 || raw[0] != 0x80 {
        return Err("invalid fernet token".into());
    }
    let (signed, hmac) = raw.split_at(raw.len() - 32);
    let mut mac =
        HmacSha256::new_from_slice(signing).map_err(|e| format!("hmac: {e}"))?;
    mac.update(signed);
    mac.verify_slice(hmac).map_err(|_| "fernet hmac mismatch".to_string())?;
    let iv = &signed[9..25];
    let ciphertext = &signed[25..];
    Aes128CbcDec::new(encryption.into(), iv.into())
        .decrypt_padded_vec_mut::<Pkcs7>(ciphertext)
        .map_err(|_| "fernet decrypt failed".to_string())
}

pub fn save_wallet(app_name: &str, mnemonic: &str, address: &str) -> Result<(), String> {
    let dir = data_dir(app_name);
    fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    let payload = json!({ "mnemonic": mnemonic, "address": address, "version": 1 });
    let enc = fernet_encrypt(app_name, payload.to_string().as_bytes())?;
    fs::write(wallet_file(app_name), enc).map_err(|e| e.to_string())
}

pub fn load_wallet_file(app_name: &str) -> Result<Option<Value>, String> {
    let path = wallet_file(app_name);
    if !path.is_file() {
        return Ok(None);
    }
    let raw = fs::read(&path).map_err(|e| e.to_string())?;
    let dec = fernet_decrypt(app_name, &raw)?;
    let data: Value = serde_json::from_slice(&dec).map_err(|e| e.to_string())?;
    Ok(Some(data))
}

pub fn delete_wallet(app_name: &str) -> Result<(), String> {
    let path = wallet_file(app_name);
    if path.is_file() {
        fs::remove_file(path).map_err(|e| e.to_string())?;
    }
    Ok(())
}

pub fn load_or_migrate() -> Result<(Option<Wallet>, Option<&'static str>), String> {
    if let Some(data) = load_wallet_file(APP_WALLET_NAME)? {
        let mnemonic = data
            .get("mnemonic")
            .and_then(|v| v.as_str())
            .ok_or("Wallet file has no mnemonic")?;
        return Ok((Some(Wallet::from_mnemonic(mnemonic)?), None));
    }
    if let Some(data) = load_wallet_file(LEGACY_WALLET_NAME)? {
        let mnemonic = data
            .get("mnemonic")
            .and_then(|v| v.as_str())
            .ok_or("legacy wallet has no mnemonic")?;
        let wallet = Wallet::from_mnemonic(mnemonic)?;
        save_wallet(APP_WALLET_NAME, &wallet.mnemonic, &wallet.address)?;
        return Ok((Some(wallet), Some(LEGACY_WALLET_NAME)));
    }
    Ok((None, None))
}

pub fn require_wallet() -> Result<Wallet, String> {
    load_or_migrate()?
        .0
        .ok_or_else(|| "No wallet yet. Create or import one in the Wallet page.".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn encrypt_decrypt_roundtrip() {
        let msg = b"{\"mnemonic\":\"hello\"}";
        let token = fernet_encrypt("BeezDesktopTwoTest", msg).unwrap();
        let out = fernet_decrypt("BeezDesktopTwoTest", &token).unwrap();
        assert_eq!(out, msg);
    }
}
