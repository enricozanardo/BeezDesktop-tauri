"""
BeezClient Timestamp Utilities

Provides consistent timestamp handling across Beez applications.
All timestamps use Rome timezone (Europe/Rome) for consistency.
"""

from datetime import datetime, timezone, timedelta
import time

# Rome timezone (UTC+1 in winter, UTC+2 in summer - simplified)
ROME_TZ = timezone(timedelta(hours=1))


def get_rome_timestamp() -> str:
    """
    Get current timestamp in Rome timezone, formatted as human-readable string.
    
    Returns:
        str: Timestamp in format "2025-09-09 14:30:45 CET"
    """
    now_utc = datetime.now(timezone.utc)
    rome_time = now_utc.astimezone(ROME_TZ)
    return rome_time.strftime("%Y-%m-%d %H:%M:%S %Z")


def get_rome_timestamp_iso() -> str:
    """
    Get current timestamp in Rome timezone, ISO format.
    
    Returns:
        str: Timestamp in format "2025-09-09T14:30:45+01:00"
    """
    now_utc = datetime.now(timezone.utc)
    rome_time = now_utc.astimezone(ROME_TZ)
    return rome_time.isoformat()


def get_rome_unix_timestamp() -> int:
    """
    Get current Unix timestamp (seconds since epoch).
    
    Returns:
        int: Unix timestamp
    """
    return int(time.time())


def unix_to_rome_readable(unix_timestamp: int) -> str:
    """
    Convert Unix timestamp to Rome timezone readable format.
    
    Args:
        unix_timestamp: Unix timestamp
        
    Returns:
        str: Formatted timestamp in Rome timezone
    """
    dt_utc = datetime.fromtimestamp(unix_timestamp, tz=timezone.utc)
    rome_time = dt_utc.astimezone(ROME_TZ)
    return rome_time.strftime("%Y-%m-%d %H:%M:%S %Z")


# Backward compatibility aliases
def get_current_timestamp() -> str:
    """Legacy function name for backward compatibility."""
    return get_rome_timestamp()


def get_blockchain_timestamp() -> dict:
    """
    Get timestamp data suitable for blockchain operations.
    
    Returns:
        dict: Contains single timestamp field in readable format
    """
    return {
        "timestamp": get_rome_timestamp()
    }
