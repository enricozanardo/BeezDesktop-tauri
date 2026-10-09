use std::net::IpAddr;

use serde_json::{json, Map, Value};

use crate::http;
use crate::nodes::list_all_nodes;
use crate::paths::{data_dir, APP_WALLET_NAME};

const BATCH_URL: &str = "http://ip-api.com/batch?fields=status,query,lat,lon,city,country,countryCode";
const BATCH_MAX: usize = 100;

fn cache_path() -> std::path::PathBuf {
    data_dir(APP_WALLET_NAME).join("geo_cache.json")
}

fn load_cache() -> Map<String, Value> {
    std::fs::read_to_string(cache_path())
        .ok()
        .and_then(|s| serde_json::from_str::<Value>(&s).ok())
        .and_then(|v| v.as_object().cloned())
        .unwrap_or_default()
}

fn save_cache(cache: &Map<String, Value>) {
    let path = cache_path();
    if let Some(dir) = path.parent() {
        let _ = std::fs::create_dir_all(dir);
    }
    if let Ok(bytes) = serde_json::to_vec(cache) {
        let _ = std::fs::write(path, bytes);
    }
}

fn is_public_ip(ip: &str) -> bool {
    match ip.parse::<IpAddr>() {
        Ok(IpAddr::V4(v4)) => !(v4.is_private() || v4.is_loopback() || v4.is_link_local() || v4.is_unspecified()),
        Ok(IpAddr::V6(v6)) => !(v6.is_loopback() || v6.is_unspecified()),
        Err(_) => false,
    }
}

/// Look up the IPs missing from the cache (one batch request per 100 IPs).
fn resolve(ips: &[String], cache: &mut Map<String, Value>) -> Option<String> {
    let missing: Vec<&String> = ips.iter().filter(|ip| !cache.contains_key(*ip)).collect();
    let mut error = None;
    for batch in missing.chunks(BATCH_MAX) {
        match http::post_json(BATCH_URL, &json!(batch), 10) {
            Ok((200, Value::Array(rows), _)) => {
                for row in rows {
                    if row["status"] == "success" {
                        if let Some(ip) = row["query"].as_str() {
                            cache.insert(ip.to_string(), json!({
                                "lat": row["lat"], "lon": row["lon"], "city": row["city"],
                                "country": row["country"], "country_code": row["countryCode"],
                            }));
                        }
                    }
                }
            }
            Ok((status, _, text)) => error = Some(format!("geolocation service {status}: {}", text.chars().take(120).collect::<String>())),
            Err(e) => error = Some(format!("geolocation service unreachable: {e}")),
        }
    }
    error
}

fn reported_location(node: &Value) -> Option<Value> {
    let num = |k: &str| node.get(k).and_then(|v| v.as_f64().or_else(|| v.as_str().and_then(|s| s.parse().ok())));
    match (num("lat"), num("lon")) {
        (Some(lat), Some(lon)) if lat != 0.0 || lon != 0.0 => Some(json!({"lat": lat, "lon": lon})),
        _ => None,
    }
}

/// Network nodes with wallet address and geographic location.
pub fn network_map() -> Value {
    let listed = list_all_nodes();
    let nodes = listed["nodes"].as_array().cloned().unwrap_or_default();
    let ips: Vec<String> = nodes
        .iter()
        .filter_map(|n| n["ip"].as_str())
        .filter(|ip| is_public_ip(ip))
        .map(str::to_string)
        .collect();
    let mut cache = load_cache();
    let geo_error = resolve(&ips, &mut cache);
    save_cache(&cache);
    let enriched: Vec<Value> = nodes
        .into_iter()
        .map(|mut n| {
            let ip = n["ip"].as_str().unwrap_or("").to_string();
            let location = match cache.get(&ip) {
                Some(g) => {
                    let mut g = g.clone();
                    g["source"] = json!("ip");
                    Some(g)
                }
                None => reported_location(&n).map(|mut g| {
                    g["source"] = json!("reported");
                    g
                }),
            };
            n["location"] = location.unwrap_or(Value::Null);
            n
        })
        .collect();
    json!({
        "ok": true,
        "nodes": enriched,
        "errors": listed["errors"],
        "source": listed["source"],
        "geo_error": geo_error,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn only_public_ips_are_geolocated() {
        assert!(is_public_ip("138.199.217.130"));
        assert!(!is_public_ip("10.0.0.4"));
        assert!(!is_public_ip("127.0.0.1"));
        assert!(!is_public_ip("chain1"));
    }

    #[test]
    fn reported_location_ignores_zero_and_parses_strings() {
        assert!(reported_location(&json!({"lat": 0.0, "lon": 0.0})).is_none());
        let g = reported_location(&json!({"lat": "47.5", "lon": 8.25})).unwrap();
        assert_eq!(g["lat"], 47.5);
        assert_eq!(g["lon"], 8.25);
    }
}
