"""
Geolocation Module

Get user's location via IP-based geolocation services.
"""

import requests
from typing import Tuple, Optional
from dataclasses import dataclass


@dataclass
class GeoLocation:
    """User's geographic location."""
    lat: float
    lon: float
    city: str = ""
    country: str = ""
    is_fallback: bool = False


# Default fallback location (Europe - Paris)
DEFAULT_LOCATION = GeoLocation(
    lat=48.8566,
    lon=2.3522,
    city="Paris",
    country="France",
    is_fallback=True
)


def get_location_from_ip() -> GeoLocation:
    """
    Get user's location based on their IP address.
    
    Uses free IP geolocation APIs with fallback.
    
    Returns:
        GeoLocation object with lat/lon and location info
    """
    # Try multiple free services in order
    services = [
        _try_ipapi,
        _try_ipinfo,
        _try_ipwho,
    ]
    
    for service in services:
        try:
            result = service()
            if result:
                print(f"[GEOLOCATION] Got location: {result.city}, {result.country} ({result.lat}, {result.lon})", flush=True)
                return result
        except Exception as e:
            print(f"[GEOLOCATION] Service failed: {e}", flush=True)
            continue
    
    print(f"[GEOLOCATION] All services failed, using fallback: {DEFAULT_LOCATION.city}", flush=True)
    return DEFAULT_LOCATION


def _try_ipapi() -> Optional[GeoLocation]:
    """Try ip-api.com (free, no key required)."""
    response = requests.get(
        "http://ip-api.com/json/?fields=status,lat,lon,city,country",
        timeout=5
    )
    if response.status_code == 200:
        data = response.json()
        if data.get("status") == "success":
            return GeoLocation(
                lat=data.get("lat", 0),
                lon=data.get("lon", 0),
                city=data.get("city", ""),
                country=data.get("country", ""),
                is_fallback=False
            )
    return None


def _try_ipinfo() -> Optional[GeoLocation]:
    """Try ipinfo.io (free tier, no key required)."""
    response = requests.get(
        "https://ipinfo.io/json",
        timeout=5
    )
    if response.status_code == 200:
        data = response.json()
        loc = data.get("loc", "0,0").split(",")
        if len(loc) == 2:
            return GeoLocation(
                lat=float(loc[0]),
                lon=float(loc[1]),
                city=data.get("city", ""),
                country=data.get("country", ""),
                is_fallback=False
            )
    return None


def _try_ipwho() -> Optional[GeoLocation]:
    """Try ipwho.is (free, no key required)."""
    response = requests.get(
        "https://ipwho.is/",
        timeout=5
    )
    if response.status_code == 200:
        data = response.json()
        if data.get("success"):
            return GeoLocation(
                lat=data.get("latitude", 0),
                lon=data.get("longitude", 0),
                city=data.get("city", ""),
                country=data.get("country", ""),
                is_fallback=False
            )
    return None


def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate distance between two points using Haversine formula.
    
    Args:
        lat1, lon1: First point coordinates
        lat2, lon2: Second point coordinates
        
    Returns:
        Distance in kilometers
    """
    import math
    
    R = 6371  # Earth's radius in km
    
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)
    
    a = (math.sin(delta_lat / 2) ** 2 +
         math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return R * c


# Cache the location to avoid repeated API calls
_cached_location: Optional[GeoLocation] = None


def get_cached_location() -> GeoLocation:
    """Get cached location or fetch new one."""
    global _cached_location
    if _cached_location is None:
        _cached_location = get_location_from_ip()
    return _cached_location


def clear_location_cache():
    """Clear the cached location."""
    global _cached_location
    _cached_location = None
