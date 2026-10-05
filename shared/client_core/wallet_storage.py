"""
Wallet Storage

Secure local storage for wallet information with encryption.
"""

import os
import json
import base64
from pathlib import Path
from typing import Optional, Dict
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


class WalletStorage:
    """
    Secure wallet storage manager.
    
    Stores wallet mnemonic encrypted with a machine-specific key.
    """
    
    def __init__(self, app_name: str = "BeezDesktop"):
        """
        Initialize wallet storage.
        
        Args:
            app_name: Application name for storage directory
        """
        self.app_name = app_name
        self.storage_dir = self._get_storage_dir()
        self.wallet_file = self.storage_dir / "wallet.json"
        self._ensure_storage_dir()
    
    def _get_storage_dir(self) -> Path:
        """Get platform-specific storage directory."""
        if os.name == 'nt':  # Windows
            base = Path(os.environ.get('APPDATA', Path.home() / 'AppData' / 'Roaming'))
        elif os.name == 'posix':
            if 'darwin' in os.sys.platform:  # macOS
                base = Path.home() / 'Library' / 'Application Support'
            else:  # Linux
                base = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local' / 'share'))
        else:
            base = Path.home()
        
        return base / self.app_name
    
    def _ensure_storage_dir(self):
        """Ensure storage directory exists."""
        self.storage_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_machine_key(self) -> bytes:
        """
        Generate a machine-specific encryption key.
        
        Uses machine-specific data to derive a consistent key.
        """
        # Combine machine-specific identifiers
        machine_id_parts = [
            os.environ.get('USER', ''),
            os.environ.get('HOME', ''),
            str(Path.home()),
            self.app_name,
        ]
        machine_id = '|'.join(machine_id_parts).encode()
        
        # Use PBKDF2 to derive a key
        salt = b'BeezDesktopWalletStorage2024'
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(machine_id))
        return key
    
    def save_wallet(self, mnemonic: str, address: str) -> bool:
        """
        Save wallet to encrypted storage.
        
        Args:
            mnemonic: Wallet mnemonic phrase
            address: Wallet address
            
        Returns:
            True if saved successfully
        """
        try:
            key = self._get_machine_key()
            fernet = Fernet(key)
            
            wallet_data = {
                "mnemonic": mnemonic,
                "address": address,
                "version": 1
            }
            
            # Encrypt the wallet data
            encrypted = fernet.encrypt(json.dumps(wallet_data).encode())
            
            # Save to file
            with open(self.wallet_file, 'wb') as f:
                f.write(encrypted)
            
            print(f"[WALLET] Saved to {self.wallet_file}", flush=True)
            return True
            
        except Exception as e:
            print(f"[WALLET] Save error: {e}", flush=True)
            return False
    
    def load_wallet(self) -> Optional[Dict]:
        """
        Load wallet from encrypted storage.
        
        Returns:
            Dict with 'mnemonic' and 'address', or None if not found
        """
        if not self.wallet_file.exists():
            return None
        
        try:
            key = self._get_machine_key()
            fernet = Fernet(key)
            
            with open(self.wallet_file, 'rb') as f:
                encrypted = f.read()
            
            decrypted = fernet.decrypt(encrypted)
            wallet_data = json.loads(decrypted.decode())
            
            print(f"[WALLET] Loaded from {self.wallet_file}", flush=True)
            return wallet_data
            
        except Exception as e:
            print(f"[WALLET] Load error: {e}", flush=True)
            return None
    
    def delete_wallet(self) -> bool:
        """
        Delete saved wallet.
        
        Returns:
            True if deleted successfully
        """
        try:
            if self.wallet_file.exists():
                self.wallet_file.unlink()
                print(f"[WALLET] Deleted from {self.wallet_file}", flush=True)
            return True
        except Exception as e:
            print(f"[WALLET] Delete error: {e}", flush=True)
            return False
    
    def has_saved_wallet(self) -> bool:
        """Check if a wallet is saved."""
        return self.wallet_file.exists()
    
    def export_wallet(self, export_path: str, mnemonic: str, address: str) -> bool:
        """
        Export wallet to a plain text file (for backup).
        
        Args:
            export_path: Path to export file
            mnemonic: Wallet mnemonic
            address: Wallet address
            
        Returns:
            True if exported successfully
        """
        try:
            export_data = (
                "=== BEEZ WALLET BACKUP ===\n"
                f"Address: {address}\n\n"
                f"Mnemonic (12 words):\n{mnemonic}\n\n"
                "=== IMPORTANT ===\n"
                "Keep this file secure!\n"
                "Anyone with this mnemonic can access your wallet.\n"
                "Do NOT share this file.\n"
            )
            
            with open(export_path, 'w') as f:
                f.write(export_data)
            
            return True
            
        except Exception as e:
            print(f"[WALLET] Export error: {e}", flush=True)
            return False


# Global instance
_wallet_storage = None

def get_wallet_storage() -> WalletStorage:
    """Get global wallet storage instance."""
    global _wallet_storage
    if _wallet_storage is None:
        _wallet_storage = WalletStorage()
    return _wallet_storage
