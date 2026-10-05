"""
BeezClient Geographic Distance Utilities

Provides distance calculation for storage node selection based on proximity.
"""

import math
from typing import Tuple


def calculate_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate the great-circle distance between two points using the Haversine formula.
    
    Args:
        lat1: Latitude of first point (degrees)
        lon1: Longitude of first point (degrees)
        lat2: Latitude of second point (degrees)
        lon2: Longitude of second point (degrees)
        
    Returns:
        Distance in kilometers
    """
    R = 6371  # Earth's radius in kilometers
    
    # Convert to radians
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    
    # Haversine formula
    a = math.sin(dlat / 2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return R * c


def filter_nodes_by_distance(
    nodes: list,
    client_lat: float,
    client_lon: float,
    max_distance_km: float
) -> list:
    """
    Filter nodes within a maximum distance from the client.
    
    Args:
        nodes: List of node dicts with 'latitude' and 'longitude' keys
        client_lat: Client's latitude
        client_lon: Client's longitude
        max_distance_km: Maximum distance in kilometers
        
    Returns:
        List of nodes within the specified distance, sorted by distance
    """
    nodes_with_distance = []
    
    for node in nodes:
        node_lat = node.get("latitude")
        node_lon = node.get("longitude")
        
        if node_lat is None or node_lon is None:
            continue
        
        distance = calculate_distance(client_lat, client_lon, node_lat, node_lon)
        
        if distance <= max_distance_km:
            nodes_with_distance.append({
                **node,
                "_distance_km": distance
            })
    
    # Sort by distance
    return sorted(nodes_with_distance, key=lambda n: n["_distance_km"])


def get_distance_range(distance_km: float) -> str:
    """
    Categorize distance into ranges as per Beez specification.
    
    Ranges:
        - 0-100 km: "local"
        - 100-1000 km: "regional"
        - 1000-10000 km: "continental"
        - >10000 km: "global"
    
    Args:
        distance_km: Distance in kilometers
        
    Returns:
        Distance category string
    """
    if distance_km <= 100:
        return "local"
    elif distance_km <= 1000:
        return "regional"
    elif distance_km <= 10000:
        return "continental"
    else:
        return "global"
