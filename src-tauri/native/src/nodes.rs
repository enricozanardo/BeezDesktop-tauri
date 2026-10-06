use std::net::IpAddr;

use regex::Regex;
use serde_json::{json, Value};

use crate::http;
use crate::minicpm;
use crate::paths::home_dir;

/// Live Beez test-net Directory HTTP hosts (ZMQ is :5557; HTTP is :5000).
pub const PRODUCTION_DIRECTORIES: &[&str] = &[
    "167.235.25.169",
    "157.180.40.116",
    "128.140.114.51",
];

pub const PRODUCTION_CHAINS: &[&str] = &[
    "138.199.217.130",
    "88.99.13.161",
    "37.27.35.61",
];

pub static DOCKER_NODE_MAP: &[(&str, &str, u16)] = &[
    ("directory1", "127.0.0.1", 5001),
    ("directory2", "127.0.0.1", 5002),
    ("directory3", "127.0.0.1", 5003),
    ("chain1", "127.0.0.1", 5000),
    ("chain2", "127.0.0.1", 5010),
    ("chain3", "127.0.0.1", 5011),
    ("storage1", "127.0.0.1", 5005),
    ("storage2", "127.0.0.1", 5006),
    ("storage3", "127.0.0.1", 5007),
    ("storage4", "127.0.0.1", 5014),
    ("storage5", "127.0.0.1", 5015),
    ("storage6", "127.0.0.1", 5016),
    ("dam1", "127.0.0.1", 5004),
    ("dam2", "127.0.0.1", 5012),
    ("dam3", "127.0.0.1", 5013),
    ("smart1", "127.0.0.1", 5017),
    ("smart2", "127.0.0.1", 5018),
    ("smart3", "127.0.0.1", 5019),
];

pub fn is_public_ip_or_hostname(node_ip: &str) -> bool {
    if let Ok(ip) = node_ip.parse::<IpAddr>() {
        return match ip {
            IpAddr::V4(v) => !(v.is_loopback() || v.is_private()),
            IpAddr::V6(v) => !(v.is_loopback() || v.is_unique_local() || v.is_unicast_link_local()),
        };
    }
    node_ip.contains('.')
}

pub fn resolve_node_address(node_ip: &str) -> (String, u16) {
    if is_public_ip_or_hostname(node_ip) {
        return (node_ip.to_string(), 5000);
    }
    let node_key = node_ip.to_lowercase().replace(['-', '_'], "");
    for (key, host, port) in DOCKER_NODE_MAP {
        if *key == node_key {
            return ((*host).to_string(), *port);
        }
    }
    for (key, host, port) in DOCKER_NODE_MAP {
        if node_key.contains(key) {
            return ((*host).to_string(), *port);
        }
    }
    let re = Regex::new(r"(chain|storage|dam|directory|smart)[_-]?(\d+)").unwrap();
    if let Some(c) = re.captures(&node_key) {
        let mapped = format!("{}{}", &c[1], &c[2]);
        for (key, host, port) in DOCKER_NODE_MAP {
            if *key == mapped {
                return ((*host).to_string(), *port);
            }
        }
    }
    (node_ip.to_string(), 5000)
}

pub fn http_url_for(node_ip: &str) -> String {
    let (host, port) = resolve_node_address(node_ip);
    format!("http://{host}:{port}")
}

fn push_unique(urls: &mut Vec<String>, url: String) {
    if !urls.iter().any(|u| u == &url) {
        urls.push(url);
    }
}

/// Convert a .beez directory_nodes entry (`host:zmqPort` or URL) to an HTTP base.
pub fn http_base_from_dir_entry(entry: &str) -> String {
    let s = entry.trim().trim_matches(|c| c == '"' || c == '\'');
    if s.starts_with("http://") || s.starts_with("https://") {
        return s.trim_end_matches('/').to_string();
    }
    let (host, port_s) = s.rsplit_once(':').unwrap_or((s, "5000"));
    let port: u16 = port_s.parse().unwrap_or(5000);
    // 5555–5999 are ZMQ in this network; HTTP is on 5000 for public hosts.
    let http_port = if (5555..6000).contains(&port) { 5000 } else { port };
    if is_public_ip_or_hostname(host) {
        format!("http://{host}:{http_port}")
    } else {
        http_url_for(host)
    }
}

fn directory_hosts_from_beez() -> Vec<String> {
    let path = home_dir().join(".beez");
    let Ok(text) = std::fs::read_to_string(path) else {
        return Vec::new();
    };
    let mut out = Vec::new();
    if let Ok(value) = text.parse::<toml::Value>() {
        if let Some(arr) = value
            .get("network")
            .and_then(|n| n.get("directory_nodes"))
            .and_then(|v| v.as_array())
        {
            for item in arr {
                if let Some(s) = item.as_str() {
                    out.push(http_base_from_dir_entry(s));
                }
            }
        }
    }
    if out.is_empty() {
        for line in text.lines() {
            if let Some(idx) = line.find("http://").or_else(|| line.find("https://")) {
                let part = line[idx..]
                    .trim()
                    .trim_matches(|c| c == '"' || c == '\'');
                let part = part
                    .split_whitespace()
                    .next()
                    .unwrap_or(part)
                    .trim_end_matches('/');
                if part.starts_with("http") {
                    out.push(part.to_string());
                }
            }
        }
    }
    out
}

pub fn ensure_default_beez() {
    let path = home_dir().join(".beez");
    if path.is_file() {
        return;
    }
    let body = r#"# Beez Desktop Two — live test-net directories (HTTP :5000, ZMQ :5557)
[network]
type = "default"
directory_nodes = ["167.235.25.169:5557", "157.180.40.116:5557", "128.140.114.51:5557"]

[logging]
level = "INFO"
"#;
    let _ = std::fs::write(path, body);
}

pub fn directory_http_urls() -> Vec<String> {
    ensure_default_beez();
    let mut urls = Vec::new();
    for host in PRODUCTION_DIRECTORIES {
        push_unique(&mut urls, format!("http://{host}:5000"));
    }
    for host in directory_hosts_from_beez() {
        push_unique(&mut urls, host);
    }
    for name in ["directory1", "directory2", "directory3"] {
        push_unique(&mut urls, http_url_for(name));
    }
    urls
}

pub fn chain_http_urls() -> Vec<String> {
    let mut urls = Vec::new();
    for host in PRODUCTION_CHAINS {
        push_unique(&mut urls, format!("http://{host}:5000"));
    }
    for name in ["chain1", "chain2", "chain3"] {
        push_unique(&mut urls, http_url_for(name));
    }
    urls
}

pub fn smart_url(node: &Value) -> String {
    if node.get("node_id").and_then(|v| v.as_str()) == Some("local_minicpm") {
        return format!("http://127.0.0.1:{}", minicpm::PORT);
    }
    let ip = node
        .get("ip")
        .and_then(|v| v.as_str())
        .or_else(|| node.get("node_id").and_then(|v| v.as_str()))
        .unwrap_or("smart1");
    http_url_for(ip)
}

fn is_smart(n: &Value) -> bool {
    let t = n
        .get("node_type")
        .and_then(|v| v.as_str())
        .unwrap_or("")
        .to_lowercase();
    if t == "smart" {
        return true;
    }
    n.get("capabilities").is_some()
        || n.get("price_per_query").is_some()
        || n.get("llm_backend").is_some()
}

fn fetch_directory_nodes(base: &str) -> Result<Vec<Value>, String> {
    let payload = http::get_json_connect(&format!("{base}/nodes"), 4, 800)?;
    let raw = payload.get("nodes").cloned().unwrap_or(payload);
    raw.as_array()
        .cloned()
        .ok_or_else(|| "directory /nodes is not a list".into())
}

pub fn list_all_nodes() -> Value {
    let mut nodes: Vec<Value> = Vec::new();
    let mut errors = Vec::new();
    let mut source = String::new();
    for base in directory_http_urls() {
        match fetch_directory_nodes(&base) {
            Ok(list) if !list.is_empty() => {
                nodes = list;
                source = base;
                break;
            }
            Ok(_) => errors.push(format!("{base}: empty")),
            Err(e) => errors.push(format!("{base}: {e}")),
        }
    }
    json!({ "ok": true, "nodes": nodes, "errors": errors, "source": source })
}

pub fn list_smart_nodes() -> Value {
    let listed = list_all_nodes();
    let mut errors: Vec<Value> = listed
        .get("errors")
        .and_then(|v| v.as_array())
        .cloned()
        .unwrap_or_default();
    let mut nodes: Vec<Value> = listed
        .get("nodes")
        .and_then(|v| v.as_array())
        .map(|a| a.iter().filter(|n| is_smart(n)).cloned().collect())
        .unwrap_or_default();

    if nodes.is_empty() {
        for name in ["smart1", "smart2", "smart3"] {
            let url = http_url_for(name);
            match http::get_json_connect(&format!("{url}/info"), 2, 400) {
                Ok(mut info) => {
                    if let Some(obj) = info.as_object_mut() {
                        obj.insert("ip".into(), json!(name));
                        obj.insert("node_type".into(), json!("smart"));
                    }
                    nodes.push(info);
                }
                Err(e) => errors.push(json!(format!("{name}: {e}"))),
            }
        }
    }

    let mut merged = Vec::new();
    for mut node in nodes {
        if node.get("banned").and_then(|v| v.as_bool()) == Some(true) {
            continue;
        }
        if node.get("capabilities").is_none() {
            let url = smart_url(&node);
            if let Ok(info) = http::get_json_connect(&format!("{url}/info"), 3, 800) {
                if let Some(obj) = node.as_object_mut() {
                    for k in [
                        "capabilities",
                        "llm_backend",
                        "modalities",
                        "llm_model",
                        "price_per_query",
                        "price_per_embedding",
                        "wallet_address",
                        "node_id",
                    ] {
                        if let Some(v) = info.get(k) {
                            obj.insert(k.to_string(), v.clone());
                        }
                    }
                }
            } else if let Some(obj) = node.as_object_mut() {
                obj.insert("capabilities".into(), json!(["generic"]));
            }
        }
        if let Some(obj) = node.as_object_mut() {
            if obj.get("label").is_none() {
                let label = obj
                    .get("node_id")
                    .and_then(|v| v.as_str())
                    .or_else(|| obj.get("ip").and_then(|v| v.as_str()))
                    .unwrap_or("smart");
                obj.insert("label".into(), json!(label));
            }
            obj.insert("node_type".into(), json!("smart"));
        }
        merged.push(node);
    }
    merged.insert(0, minicpm::local_node());
    json!({
        "ok": true,
        "nodes": merged,
        "errors": errors,
        "source": listed.get("source"),
    })
}

pub fn infer_needed_capabilities(prompt: &str, attachments: &[String]) -> Vec<String> {
    let names = attachments.join(" ");
    let blob = format!("{prompt}\n{names}");
    let code = Regex::new(r"(?i)```|def |class |import |function |typescript|python|rustc|compile error")
        .unwrap();
    let image = Regex::new(r"(?i)\.(png|jpe?g|gif|webp|bmp|tiff)\b|image|photo|picture|vision").unwrap();
    let verify = Regex::new(r"(?i)\b(verify|proof|trace|legal|contract|entail)\b").unwrap();
    let mut needed = Vec::new();
    let attach_img = attachments.iter().any(|n| {
        let l = n.to_lowercase();
        l.ends_with(".png")
            || l.ends_with(".jpg")
            || l.ends_with(".jpeg")
            || l.ends_with(".gif")
            || l.ends_with(".webp")
    });
    if attachments.iter().any(|n| image.is_match(n))
        || (image.is_match(prompt) && attach_img)
    {
        needed.push("vision".into());
    }
    if code.is_match(&blob) {
        needed.push("coding".into());
    }
    if verify.is_match(prompt) {
        needed.push("verifier".into());
    }
    if needed.is_empty() {
        needed.push("generic".into());
    }
    needed
}

pub fn rank_nodes(nodes: &[Value], prompt: &str, attachments: &[String]) -> Vec<Value> {
    let needed = infer_needed_capabilities(prompt, attachments);
    let mut ranked: Vec<(f64, f64, Value)> = nodes
        .iter()
        .map(|node| {
            let caps = match node.get("capabilities") {
                Some(Value::Array(a)) => a
                    .iter()
                    .filter_map(|v| v.as_str().map(|s| s.to_string()))
                    .collect(),
                Some(Value::String(s)) => s
                    .split(',')
                    .map(|c| c.trim().to_string())
                    .filter(|c| !c.is_empty())
                    .collect(),
                _ => vec!["generic".into()],
            };
            let mut score = 0.0;
            for tag in &needed {
                if caps.iter().any(|c| c == tag) {
                    score += 3.0;
                }
            }
            if caps.iter().any(|c| c == "generic") {
                score += 0.5;
            }
            if node.get("banned").and_then(|v| v.as_bool()) == Some(true) {
                score -= 10.0;
            }
            let price = node
                .get("price_per_query")
                .and_then(|v| v.as_f64())
                .unwrap_or(0.0);
            let reputation = node
                .get("reputation")
                .or_else(|| node.get("score"))
                .and_then(|v| v.as_f64())
                .unwrap_or(0.0);
            score += reputation.min(100.0) / 200.0;
            let mut item = node.clone();
            if let Some(obj) = item.as_object_mut() {
                obj.insert("suitability".into(), json!((score * 1000.0).round() / 1000.0));
                obj.insert("recommended_for".into(), json!(needed.clone()));
            }
            (score, price, item)
        })
        .collect();
    ranked.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap().then(a.1.partial_cmp(&b.1).unwrap()));
    ranked.into_iter().map(|t| t.2).collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn local_compose_maps_smart1() {
        assert_eq!(resolve_node_address("smart1"), ("127.0.0.1".into(), 5017));
    }

    #[test]
    fn public_ipv4_passthrough() {
        assert_eq!(resolve_node_address("8.8.8.8"), ("8.8.8.8".into(), 5000));
    }

    #[test]
    fn zmq_directory_entry_becomes_http_5000() {
        assert_eq!(
            http_base_from_dir_entry("167.235.25.169:5557"),
            "http://167.235.25.169:5000"
        );
    }
}
