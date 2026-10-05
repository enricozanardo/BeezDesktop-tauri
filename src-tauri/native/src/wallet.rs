use bip39::{Language, Mnemonic};
use k256::ecdsa::SigningKey;
use rand::RngCore;
use sha2::{Digest, Sha256};

#[derive(Clone)]
pub struct Wallet {
    pub mnemonic: String,
    pub privkey: [u8; 32],
    pub address: String,
}

impl Wallet {
    pub fn generate() -> Result<Self, String> {
        let mut entropy = [0u8; 16];
        rand::thread_rng().fill_bytes(&mut entropy);
        let mnemonic = Mnemonic::from_entropy_in(Language::English, &entropy)
            .map_err(|e| format!("mnemonic generate: {e}"))?;
        Self::from_mnemonic(&mnemonic.to_string())
    }

    pub fn from_mnemonic(mnemonic: &str) -> Result<Self, String> {
        let parsed = Mnemonic::parse_in_normalized(Language::English, mnemonic.trim())
            .map_err(|e| format!("invalid mnemonic: {e}"))?;
        let seed = parsed.to_seed("");
        let digest = Sha256::digest(seed);
        let mut privkey = [0u8; 32];
        privkey.copy_from_slice(&digest);
        let address = privkey_to_address(&privkey)?;
        Ok(Self {
            mnemonic: parsed.to_string(),
            privkey,
            address,
        })
    }

    #[allow(dead_code)]
    pub fn privkey_hex(&self) -> String {
        hex::encode(self.privkey)
    }

    pub fn pubkey_bytes(&self) -> Result<[u8; 64], String> {
        pubkey_from_privkey(&self.privkey)
    }

    pub fn pubkey_hex(&self) -> Result<String, String> {
        Ok(hex::encode(self.pubkey_bytes()?))
    }
}

pub fn privkey_to_address(privkey: &[u8; 32]) -> Result<String, String> {
    let pub_bytes = pubkey_from_privkey(privkey)?;
    let hash = Sha256::digest(pub_bytes);
    Ok(format!("bez{}", bs58::encode(&hash[..20]).into_string()))
}

fn pubkey_from_privkey(privkey: &[u8; 32]) -> Result<[u8; 64], String> {
    let sk = SigningKey::from_bytes(privkey.into()).map_err(|e| format!("secp256k1: {e}"))?;
    let point = sk.verifying_key().to_encoded_point(false);
    let bytes = point.as_bytes();
    if bytes.len() != 65 || bytes[0] != 0x04 {
        return Err("unexpected secp256k1 public key encoding".into());
    }
    let mut out = [0u8; 64];
    out.copy_from_slice(&bytes[1..]);
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn roundtrip_mnemonic_address_stable() {
        let phrase = "abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon abandon about";
        let a = Wallet::from_mnemonic(phrase).unwrap();
        let b = Wallet::from_mnemonic(phrase).unwrap();
        assert_eq!(a.address, b.address);
        assert!(a.address.starts_with("bez"));
        assert_eq!(a.privkey_hex().len(), 64);
        assert_eq!(a.pubkey_hex().unwrap().len(), 128);
    }

    #[test]
    fn generate_has_twelve_words() {
        let w = Wallet::generate().unwrap();
        assert_eq!(w.mnemonic.split_whitespace().count(), 12);
    }
}
