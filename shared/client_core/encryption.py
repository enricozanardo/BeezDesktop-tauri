"""
BeezClient File Encryption

Provides AES-256-GCM encryption for file content using wallet-derived keys.
Key derivation uses HKDF-SHA256 with domain-separation labels to decouple
signing and encryption key material.  Legacy SHA-256-only derivation is
retained as a backward-compatible fallback for data encrypted before the
HKDF migration.
"""

import os
import base64
import hashlib
from typing import Tuple

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes
from cryptography.exceptions import InvalidTag

DOMAIN_FILE_ENC = b"beez-file-enc-v1"


def _validate_wallet(wallet) -> None:
    """Validate that wallet has a 32-byte privkey."""
    if not hasattr(wallet, 'privkey'):
        raise ValueError("Wallet must have 'privkey' attribute")
    if len(wallet.privkey) != 32:
        raise ValueError(f"Wallet privkey must be 32 bytes, got {len(wallet.privkey)}")


def derive_encryption_key(wallet, *, domain: bytes = DOMAIN_FILE_ENC) -> bytes:
    """Derive a 256-bit AES key from wallet private key using HKDF-SHA256.

    HKDF with an explicit domain-separation label ensures the encryption
    key is cryptographically independent of the wallet signing key.

    Args:
        wallet: Wallet object with .privkey attribute (32 bytes).
        domain: HKDF info/context label for domain separation.

    Returns:
        bytes: 32-byte (256-bit) AES encryption key.
    """
    _validate_wallet(wallet)
    hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=domain)
    return hkdf.derive(wallet.privkey)


def derive_encryption_key_legacy(wallet) -> bytes:
    """Legacy key derivation (SHA-256 only, no domain separation).

    Retained for backward-compatible decryption of data encrypted before
    the HKDF migration.  New encryptions MUST use ``derive_encryption_key``.

    Args:
        wallet: Wallet object with .privkey attribute (32 bytes).

    Returns:
        bytes: 32-byte (256-bit) AES encryption key.
    """
    _validate_wallet(wallet)
    return hashlib.sha256(wallet.privkey).digest()


def encrypt_file_content(file_content: bytes, wallet) -> Tuple[bytes, bytes]:
    """
    Encrypt file content using AES-256-GCM with wallet-derived key.

    Args:
        file_content: Raw file bytes to encrypt
        wallet: Wallet object for key derivation

    Returns:
        tuple: (encrypted_data, nonce)
            - encrypted_data: ciphertext + 16-byte authentication tag
            - nonce: 12-byte random value (needed for decryption)

    Raises:
        ValueError: If file_content is empty or wallet is invalid

    Security Notes:
        - Nonce MUST be unique for each encryption (generated randomly)
        - Authentication tag prevents tampering/corruption
        - Output size: len(file_content) + 16 bytes (tag)
    """
    if not file_content:
        raise ValueError("File content cannot be empty")

    # Derive encryption key from wallet
    encryption_key = derive_encryption_key(wallet)

    # Generate random nonce (96 bits = 12 bytes for GCM)
    nonce = os.urandom(12)

    # Encrypt with AES-256-GCM
    aesgcm = AESGCM(encryption_key)
    encrypted_data = aesgcm.encrypt(
        nonce=nonce,
        data=file_content,
        associated_data=None
    )

    print(f"[ENCRYPT] File encrypted: {len(file_content)} bytes → {len(encrypted_data)} bytes", flush=True)

    return encrypted_data, nonce


def decrypt_file_content(encrypted_data: bytes, nonce: bytes, wallet) -> bytes:
    """Decrypt file content using AES-256-GCM with HKDF key, falling back to legacy.

    Tries the HKDF-derived key first.  If authentication fails, retries
    with the legacy SHA-256-only key so that data encrypted before the
    HKDF migration can still be decrypted.

    Args:
        encrypted_data: Ciphertext + 16-byte authentication tag.
        nonce: 12-byte nonce used during encryption.
        wallet: Wallet object for key derivation.

    Returns:
        bytes: Original plaintext file content.

    Raises:
        InvalidTag: If both HKDF and legacy keys fail.
        ValueError: If inputs are invalid.
    """
    if not encrypted_data:
        raise ValueError("Encrypted data cannot be empty")

    if len(encrypted_data) < 16:
        raise ValueError("Encrypted data too short (must include 16-byte auth tag)")

    if len(nonce) != 12:
        raise ValueError(f"Nonce must be 12 bytes, got {len(nonce)}")

    # Try HKDF-derived key first
    encryption_key = derive_encryption_key(wallet)
    aesgcm = AESGCM(encryption_key)

    try:
        file_content = aesgcm.decrypt(nonce=nonce, data=encrypted_data, associated_data=None)
        print(f"[DECRYPT] File decrypted (HKDF): {len(encrypted_data)} → {len(file_content)} bytes", flush=True)
        return file_content
    except InvalidTag:
        pass  # fall through to legacy attempt

    # Fallback: legacy SHA-256-only key
    legacy_key = derive_encryption_key_legacy(wallet)
    aesgcm_legacy = AESGCM(legacy_key)

    try:
        file_content = aesgcm_legacy.decrypt(nonce=nonce, data=encrypted_data, associated_data=None)
        print(f"[DECRYPT] File decrypted (legacy SHA-256): {len(encrypted_data)} → {len(file_content)} bytes", flush=True)
        print("[DECRYPT] WARNING: data uses legacy key derivation — re-encrypt with HKDF key", flush=True)
        return file_content
    except InvalidTag:
        print("[DECRYPT] Authentication failed with both HKDF and legacy keys", flush=True)
        raise


def recover_truncated_gcm(encrypted_data: bytes, nonce: bytes, wallet,
                          expected_plaintext_hash: str = None) -> bytes:
    """Recover plaintext from AES-GCM data that is missing the auth tag.

    Tries HKDF key first, then legacy SHA-256 key.  Integrity is verified
    via ``expected_plaintext_hash`` (SHA-256 of the original plaintext).

    Args:
        encrypted_data: Ciphertext WITHOUT the 16-byte GCM tag.
        nonce: 12-byte GCM nonce used during encryption.
        wallet: Wallet object for key derivation.
        expected_plaintext_hash: SHA-256 hex digest for verification.

    Returns:
        bytes: Recovered plaintext if hash verification passes.

    Raises:
        ValueError: If hash verification fails or inputs are invalid.
    """
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    if len(nonce) != 12:
        raise ValueError(f"Nonce must be 12 bytes, got {len(nonce)}")

    keys_to_try = [
        ("HKDF", derive_encryption_key(wallet)),
        ("legacy", derive_encryption_key_legacy(wallet)),
    ]

    ctr_nonce = nonce + b'\x00\x00\x00\x02'

    for label, key in keys_to_try:
        cipher = Cipher(algorithms.AES(key), modes.CTR(ctr_nonce))
        decryptor = cipher.decryptor()
        recovered = decryptor.update(encrypted_data) + decryptor.finalize()

        if expected_plaintext_hash:
            actual_hash = hashlib.sha256(recovered).hexdigest()
            if actual_hash == expected_plaintext_hash:
                print(f"[DECRYPT] CTR recovery ({label}): hash verified", flush=True)
                return recovered
        else:
            print(f"[DECRYPT] CTR recovery ({label}): no hash to verify", flush=True)
            return recovered

    raise ValueError("CTR recovery hash mismatch with both HKDF and legacy keys")


def encode_nonce_b64(nonce: bytes) -> str:
    """
    Encode nonce to base64 string for JSON storage.

    Args:
        nonce: 12-byte nonce from encryption

    Returns:
        str: Base64-encoded nonce
    """
    return base64.b64encode(nonce).decode('utf-8')


def decode_nonce_b64(nonce_b64: str) -> bytes:
    """
    Decode base64 nonce string to bytes.

    Args:
        nonce_b64: Base64-encoded nonce string

    Returns:
        bytes: 12-byte nonce
    """
    return base64.b64decode(nonce_b64)
