"""
BeezMaster Shared Configuration Module

Provides unified configuration loading from .beez TOML files with environment variable fallback.
All node types (BeezChain, BeezStorage, BeezDAM, BeezClient) should use this module.

Usage:
    from shared.beez_config import BeezConfig
    
    config = BeezConfig.load()  # Auto-discovers .beez file
    # or
    config = BeezConfig.load("/path/to/.beez")
    
    # Access configuration
    directory_nodes = config.get_directory_nodes()
    wallet_address = config.wallet.address
    zmq_port = config.zmq.tx_port
"""

import os
import tomllib  # Python 3.11+ built-in TOML parser
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from pathlib import Path


@dataclass
class NetworkConfig:
    """Network configuration section."""
    type: str = "default"
    directory_nodes: List[str] = field(default_factory=lambda: [
        "directory1:5557",
        "directory2:5557", 
        "directory3:5557"
    ])


@dataclass
class WalletConfig:
    """Wallet configuration section."""
    address: str = ""
    mnemonic: str = ""
    reward_address: str = ""
    keystore_path: str = ""


@dataclass
class ChainConfig:
    """BeezChain specific configuration."""
    mining_enabled: bool = True
    max_transactions_per_block: int = 1000
    pow_difficulty: int = 2
    leveldb_path: str = "./data/leveldb"
    
    # PostgreSQL
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "beez_chain_assets"
    postgres_user: str = "chain_user"
    postgres_password: str = ""
    postgres_enabled: bool = True
    postgres_min_conn: int = 2
    postgres_max_conn: int = 10


@dataclass
class StorageConfig:
    """BeezStorage specific configuration."""
    price_per_chunk: float = 1.0
    max_storage_gb: int = 100
    storage_path: str = "./data/chunks"
    accepted_networks: List[str] = field(default_factory=list)
    country_code: str = ""
    latitude: float = 0.0
    longitude: float = 0.0
    enable_backup_replication: bool = True
    max_backup_copies: int = 3


@dataclass
class DAMConfig:
    """BeezDAM specific configuration."""
    verification_interval: int = 3600  # 1 hour in seconds
    chunks_per_verification: int = 10
    escrow_delay_hours: int = 24
    ban_threshold: int = -100
    monitored_networks: List[str] = field(default_factory=list)


@dataclass
class SmartConfig:
    """BeezSmart specific configuration."""
    price_per_embedding: float = 0.5
    price_per_query: float = 1.0
    supported_apis: List[str] = field(default_factory=lambda: ["openai", "anthropic", "ollama"])
    max_context_tokens: int = 8000
    embedding_model: str = "all-MiniLM-L6-v2"
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o-mini"
    llm_api_key: str = ""
    llm_base_url: str = ""  # Custom base URL for OpenAI-compatible providers
    ollama_url: str = "http://localhost:11434"
    served_networks: List[str] = field(default_factory=list)
    api_keys: Dict[str, str] = field(default_factory=dict)
    # PostgreSQL for pgvector
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "beez_smart"
    postgres_user: str = "smart_user"
    postgres_password: str = ""


@dataclass
class ZMQConfig:
    """ZeroMQ communication configuration."""
    tx_port: int = 5555
    consensus_port: int = 5557
    proposal_port: int = 5559
    sync_port: int = 5560
    asset_port: int = 5558
    health_port: int = 5559
    timeout_ms: int = 5000
    reconnect_interval_ms: int = 1000


@dataclass
class LoggingConfig:
    """Logging configuration."""
    level: str = "INFO"
    file_path: str = ""
    max_file_size_mb: int = 100
    backup_count: int = 5


@dataclass
class SecurityConfig:
    """Security configuration."""
    enable_tls: bool = False
    tls_cert_path: str = ""
    tls_key_path: str = ""
    tls_ca_path: str = ""
    rate_limit: int = 1000
    flask_secret_key: str = ""
    dam_api_secret: str = ""


@dataclass
class MagisterConfig:
    """Magister wallet addresses."""
    addresses: List[str] = field(default_factory=list)
    num_magisters: int = 5


@dataclass
class SpecialWalletsConfig:
    """Special system wallet addresses."""
    beezbase_address: str = ""
    datrone_address: str = ""


class BeezConfig:
    """
    Main configuration class that loads and provides access to all configuration.
    
    Priority order:
    1. .beez file (if exists)
    2. Environment variables
    3. Default values
    """
    
    def __init__(self):
        self.network = NetworkConfig()
        self.wallet = WalletConfig()
        self.chain = ChainConfig()
        self.storage = StorageConfig()
        self.dam = DAMConfig()
        self.smart = SmartConfig()
        self.zmq = ZMQConfig()
        self.logging = LoggingConfig()
        self.security = SecurityConfig()
        self.magisters = MagisterConfig()
        self.special_wallets = SpecialWalletsConfig()
        
        # Node-specific
        self.node_ip: str = ""
        self.node_id: str = ""
        self.data_dir: str = ""
    
    @classmethod
    def load(cls, config_path: Optional[str] = None) -> "BeezConfig":
        """
        Load configuration from .beez file with environment variable fallback.
        
        Args:
            config_path: Optional path to .beez file. If None, searches for:
                1. ./.beez
                2. ~/.beez
                3. /etc/beez/.beez
        
        Returns:
            BeezConfig instance with loaded configuration
        """
        config = cls()
        
        # Find config file
        beez_path = config._find_config_file(config_path)
        
        # Load from TOML if file exists
        if beez_path and beez_path.exists():
            config._load_from_toml(beez_path)
        
        # Override with environment variables
        config._load_from_env()
        
        return config
    
    def _find_config_file(self, config_path: Optional[str]) -> Optional[Path]:
        """Find the .beez configuration file.

        Search order:
            1. Explicit path (if provided)
            2. ./.beez (current working directory)
            3. ~/.beez (user home)
            4. /etc/beez/.beez (system-wide)
            5. Bundled default.beez in BeezDesktop app resources

        If found only in the app bundle (step 5), copies it to ~/.beez
        so the user can edit it later.
        """
        if config_path:
            return Path(config_path)

        search_paths = [
            Path.cwd() / ".beez",
            Path.home() / ".beez",
            Path("/etc/beez/.beez"),
        ]

        for path in search_paths:
            if path.exists():
                return path

        # Search in app resources (Briefcase packages resources alongside the module)
        bundled = self._find_bundled_config()
        if bundled and bundled.exists():
            user_config = Path.home() / ".beez"
            try:
                import shutil
                shutil.copy2(bundled, user_config)
                print(f"[CONFIG] Created {user_config} from bundled defaults", flush=True)
                return user_config
            except Exception as e:
                print(f"[CONFIG] Could not copy bundled config to home: {e}", flush=True)
                return bundled

        return None

    @staticmethod
    def _find_bundled_config() -> Optional[Path]:
        """Locate default.beez bundled inside the app package."""
        try:
            import beezdesktop
            resources_dir = Path(beezdesktop.__file__).parent / "resources"
            candidate = resources_dir / "default.beez"
            if candidate.exists():
                return candidate
        except (ImportError, AttributeError):
            pass

        # Fallback: search relative to this file (development layout)
        this_dir = Path(__file__).parent
        for candidate in [
            this_dir.parent / "src" / "beezdesktop" / "resources" / "default.beez",
            this_dir.parent / "beezdesktop" / "resources" / "default.beez",
        ]:
            if candidate.exists():
                return candidate

        return None
    
    def _load_from_toml(self, path: Path) -> None:
        """Load configuration from TOML file."""
        try:
            with open(path, "rb") as f:
                data = tomllib.load(f)
            
            # Network section
            if "network" in data:
                net = data["network"]
                self.network.type = net.get("type", self.network.type)
                self.network.directory_nodes = net.get("directory_nodes", self.network.directory_nodes)
            
            # Wallet section
            if "wallet" in data:
                w = data["wallet"]
                self.wallet.address = w.get("address", self.wallet.address)
                self.wallet.mnemonic = w.get("mnemonic", self.wallet.mnemonic)
                self.wallet.reward_address = w.get("reward_address", self.wallet.reward_address)
                self.wallet.keystore_path = w.get("keystore_path", self.wallet.keystore_path)
            
            # Chain section
            if "chain" in data:
                c = data["chain"]
                self.chain.mining_enabled = c.get("mining_enabled", self.chain.mining_enabled)
                self.chain.max_transactions_per_block = c.get("max_transactions_per_block", self.chain.max_transactions_per_block)
                self.chain.pow_difficulty = c.get("pow_difficulty", self.chain.pow_difficulty)
                self.chain.leveldb_path = c.get("leveldb_path", self.chain.leveldb_path)
                self.chain.postgres_host = c.get("postgres_host", self.chain.postgres_host)
                self.chain.postgres_port = c.get("postgres_port", self.chain.postgres_port)
                self.chain.postgres_db = c.get("postgres_db", self.chain.postgres_db)
                self.chain.postgres_user = c.get("postgres_user", self.chain.postgres_user)
                self.chain.postgres_password = c.get("postgres_password", self.chain.postgres_password)
                self.chain.postgres_enabled = c.get("postgres_enabled", self.chain.postgres_enabled)
            
            # Storage section
            if "storage" in data:
                s = data["storage"]
                self.storage.price_per_chunk = s.get("price_per_chunk", self.storage.price_per_chunk)
                self.storage.max_storage_gb = s.get("max_storage_gb", self.storage.max_storage_gb)
                self.storage.storage_path = s.get("storage_path", self.storage.storage_path)
                self.storage.accepted_networks = s.get("accepted_networks", self.storage.accepted_networks)
                self.storage.country_code = s.get("country_code", self.storage.country_code)
                self.storage.latitude = s.get("latitude", self.storage.latitude)
                self.storage.longitude = s.get("longitude", self.storage.longitude)
            
            # DAM section
            if "dam" in data:
                d = data["dam"]
                self.dam.verification_interval = d.get("verification_interval", self.dam.verification_interval)
                self.dam.chunks_per_verification = d.get("chunks_per_verification", self.dam.chunks_per_verification)
                self.dam.escrow_delay_hours = d.get("escrow_delay_hours", self.dam.escrow_delay_hours)
                self.dam.ban_threshold = d.get("ban_threshold", self.dam.ban_threshold)
                self.dam.monitored_networks = d.get("monitored_networks", self.dam.monitored_networks)
            
            # Smart section
            if "smart" in data:
                sm = data["smart"]
                self.smart.price_per_embedding = sm.get("price_per_embedding", self.smart.price_per_embedding)
                self.smart.price_per_query = sm.get("price_per_query", self.smart.price_per_query)
                self.smart.supported_apis = sm.get("supported_apis", self.smart.supported_apis)
                self.smart.max_context_tokens = sm.get("max_context_tokens", self.smart.max_context_tokens)
                self.smart.embedding_model = sm.get("embedding_model", self.smart.embedding_model)
                self.smart.llm_provider = sm.get("llm_provider", self.smart.llm_provider)
                self.smart.llm_model = sm.get("llm_model", self.smart.llm_model)
                self.smart.llm_api_key = sm.get("llm_api_key", self.smart.llm_api_key)
                self.smart.llm_base_url = sm.get("llm_base_url", self.smart.llm_base_url)
                self.smart.ollama_url = sm.get("ollama_url", self.smart.ollama_url)
                self.smart.postgres_host = sm.get("postgres_host", self.smart.postgres_host)
                self.smart.postgres_port = sm.get("postgres_port", self.smart.postgres_port)
                self.smart.postgres_db = sm.get("postgres_db", self.smart.postgres_db)
                self.smart.postgres_user = sm.get("postgres_user", self.smart.postgres_user)
                self.smart.postgres_password = sm.get("postgres_password", self.smart.postgres_password)
                if "api_keys" in sm:
                    self.smart.api_keys = sm["api_keys"]
            
            # ZMQ section
            if "zmq" in data:
                z = data["zmq"]
                self.zmq.tx_port = z.get("tx_port", self.zmq.tx_port)
                self.zmq.consensus_port = z.get("consensus_port", self.zmq.consensus_port)
                self.zmq.proposal_port = z.get("proposal_port", self.zmq.proposal_port)
                self.zmq.sync_port = z.get("sync_port", self.zmq.sync_port)
                self.zmq.timeout_ms = z.get("timeout_ms", self.zmq.timeout_ms)
                self.zmq.reconnect_interval_ms = z.get("reconnect_interval_ms", self.zmq.reconnect_interval_ms)
            
            # Logging section
            if "logging" in data:
                log = data["logging"]
                self.logging.level = log.get("level", self.logging.level)
                self.logging.file_path = log.get("file_path", self.logging.file_path)
                self.logging.max_file_size_mb = log.get("max_file_size_mb", self.logging.max_file_size_mb)
                self.logging.backup_count = log.get("backup_count", self.logging.backup_count)
            
            # Security section
            if "security" in data:
                sec = data["security"]
                self.security.enable_tls = sec.get("enable_tls", self.security.enable_tls)
                self.security.tls_cert_path = sec.get("tls_cert_path", self.security.tls_cert_path)
                self.security.tls_key_path = sec.get("tls_key_path", self.security.tls_key_path)
                self.security.tls_ca_path = sec.get("tls_ca_path", self.security.tls_ca_path)
                self.security.rate_limit = sec.get("rate_limit", self.security.rate_limit)
            
            # Magisters section
            if "magisters" in data:
                mag = data["magisters"]
                self.magisters.addresses = mag.get("addresses", self.magisters.addresses)
                self.magisters.num_magisters = mag.get("num_magisters", self.magisters.num_magisters)
            
            # Special wallets section
            if "special_wallets" in data:
                sw = data["special_wallets"]
                self.special_wallets.beezbase_address = sw.get("beezbase_address", self.special_wallets.beezbase_address)
                self.special_wallets.datrone_address = sw.get("datrone_address", self.special_wallets.datrone_address)
            
            print(f"[CONFIG] Loaded configuration from {path}")
            
        except Exception as e:
            print(f"[CONFIG] Warning: Failed to load {path}: {e}")
    
    def _load_from_env(self) -> None:
        """Load/override configuration from environment variables."""
        
        # Node identification
        self.node_ip = os.getenv("NODE_IP", self.node_ip)
        self.node_id = os.getenv("NODE_ID", self.node_id)
        self.data_dir = os.getenv("DATA_DIR", self.data_dir)
        
        # Wallet (env vars take priority for sensitive data)
        if os.getenv("CURRENT_WALLET_ADDRESS"):
            self.wallet.address = os.getenv("CURRENT_WALLET_ADDRESS", "")
        if os.getenv("MINER_WALLET_ADDRESS"):
            self.wallet.address = os.getenv("MINER_WALLET_ADDRESS", "")
        if os.getenv("CURRENT_WALLET_MNEMONIC"):
            self.wallet.mnemonic = os.getenv("CURRENT_WALLET_MNEMONIC", "")
        if os.getenv("MINER_WALLET_MNEMONIC"):
            self.wallet.mnemonic = os.getenv("MINER_WALLET_MNEMONIC", "")
        if os.getenv("WALLET_MNEMONIC"):
            self.wallet.mnemonic = os.getenv("WALLET_MNEMONIC", "")
        
        # PostgreSQL
        if os.getenv("POSTGRES_HOST"):
            self.chain.postgres_host = os.getenv("POSTGRES_HOST", "")
        if os.getenv("POSTGRES_PORT"):
            self.chain.postgres_port = int(os.getenv("POSTGRES_PORT", "5432"))
        if os.getenv("POSTGRES_DB"):
            self.chain.postgres_db = os.getenv("POSTGRES_DB", "")
        if os.getenv("POSTGRES_USER"):
            self.chain.postgres_user = os.getenv("POSTGRES_USER", "")
        if os.getenv("POSTGRES_PASSWORD"):
            self.chain.postgres_password = os.getenv("POSTGRES_PASSWORD", "")
        if os.getenv("ENABLE_POSTGRES"):
            self.chain.postgres_enabled = os.getenv("ENABLE_POSTGRES", "").lower() == "true"
        
        # ZMQ ports
        if os.getenv("ZMQ_PORT"):
            self.zmq.tx_port = int(os.getenv("ZMQ_PORT", "5555"))
        if os.getenv("ASSET_ZMQ_PORT"):
            self.zmq.asset_port = int(os.getenv("ASSET_ZMQ_PORT", "5558"))
        
        # Security
        if os.getenv("FLASK_SECRET_KEY"):
            self.security.flask_secret_key = os.getenv("FLASK_SECRET_KEY", "")
        if os.getenv("DAM_API_SECRET"):
            self.security.dam_api_secret = os.getenv("DAM_API_SECRET", "")
        
        # Magisters
        for i in range(1, 6):
            addr = os.getenv(f"MAGISTER_{i}_ADDRESS")
            if addr and len(self.magisters.addresses) < i:
                self.magisters.addresses.append(addr)
        if os.getenv("NUM_MAGISTERS"):
            self.magisters.num_magisters = int(os.getenv("NUM_MAGISTERS", "5"))
        
        # Special wallets
        if os.getenv("BEEZBASE_ADDRESS"):
            self.special_wallets.beezbase_address = os.getenv("BEEZBASE_ADDRESS", "")
        if os.getenv("DATRONE_ADDRESS"):
            self.special_wallets.datrone_address = os.getenv("DATRONE_ADDRESS", "")
        
        # Smart node configuration
        if os.getenv("SMART_PRICE_PER_EMBEDDING"):
            self.smart.price_per_embedding = float(os.getenv("SMART_PRICE_PER_EMBEDDING", "0.5"))
        if os.getenv("SMART_PRICE_PER_QUERY"):
            self.smart.price_per_query = float(os.getenv("SMART_PRICE_PER_QUERY", "1.0"))
        if os.getenv("LLM_PROVIDER"):
            self.smart.llm_provider = os.getenv("LLM_PROVIDER", "openai")
        if os.getenv("LLM_API_KEY"):
            self.smart.llm_api_key = os.getenv("LLM_API_KEY", "")
        if os.getenv("LLM_MODEL"):
            self.smart.llm_model = os.getenv("LLM_MODEL", "gpt-4o-mini")
        if os.getenv("EMBEDDING_MODEL"):
            self.smart.embedding_model = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
        if os.getenv("OLLAMA_URL"):
            self.smart.ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
    
    def get_directory_nodes(self) -> Dict[str, Dict[str, Any]]:
        """
        Get directory nodes as a dictionary compatible with existing code.
        
        Returns:
            Dict mapping node names to {ip, port} dicts
        """
        nodes = {}
        for i, node_addr in enumerate(self.network.directory_nodes, 1):
            parts = node_addr.split(":")
            ip = parts[0]
            port = int(parts[1]) if len(parts) > 1 else 5557
            nodes[f"directory{i}"] = {"ip": ip, "port": port}
        return nodes
    
    def get_directory_ips(self) -> List[str]:
        """Get list of directory node IPs only."""
        return [addr.split(":")[0] for addr in self.network.directory_nodes]
    
    def get_postgres_config(self) -> Dict[str, Any]:
        """Get PostgreSQL configuration as a dictionary."""
        return {
            "host": self.chain.postgres_host,
            "port": self.chain.postgres_port,
            "database": self.chain.postgres_db,
            "user": self.chain.postgres_user,
            "password": self.chain.postgres_password,
            "enabled": self.chain.postgres_enabled,
            "min_conn": self.chain.postgres_min_conn,
            "max_conn": self.chain.postgres_max_conn,
        }


# Singleton instance for convenience
_config_instance: Optional[BeezConfig] = None


def get_config(config_path: Optional[str] = None) -> BeezConfig:
    """
    Get the singleton configuration instance.
    
    Args:
        config_path: Optional path to .beez file (only used on first call)
    
    Returns:
        BeezConfig singleton instance
    """
    global _config_instance
    if _config_instance is None:
        _config_instance = BeezConfig.load(config_path)
    return _config_instance


def reload_config(config_path: Optional[str] = None) -> BeezConfig:
    """
    Force reload of configuration.
    
    Args:
        config_path: Optional path to .beez file
    
    Returns:
        New BeezConfig instance
    """
    global _config_instance
    _config_instance = BeezConfig.load(config_path)
    return _config_instance
