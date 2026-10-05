use reqwest::blocking::Client;
use serde_json::Value;
use std::time::Duration;

fn client(timeout_secs: u64) -> Result<Client, String> {
    Client::builder()
        .timeout(Duration::from_secs(timeout_secs))
        .build()
        .map_err(|e| e.to_string())
}

pub fn get_json(url: &str, timeout_secs: u64) -> Result<Value, String> {
    let resp = client(timeout_secs)?
        .get(url)
        .send()
        .map_err(|e| e.to_string())?;
    let status = resp.status();
    let text = resp.text().map_err(|e| e.to_string())?;
    if !status.is_success() {
        return Err(format!("{status}: {}", text.chars().take(400).collect::<String>()));
    }
    serde_json::from_str(&text).map_err(|e| e.to_string())
}

pub fn get_json_query(url: &str, query: &[(&str, String)], timeout_secs: u64) -> Result<Value, String> {
    let resp = client(timeout_secs)?
        .get(url)
        .query(query)
        .send()
        .map_err(|e| e.to_string())?;
    let status = resp.status();
    let text = resp.text().map_err(|e| e.to_string())?;
    if !status.is_success() {
        return Err(format!("{status}: {}", text.chars().take(400).collect::<String>()));
    }
    serde_json::from_str(&text).map_err(|e| e.to_string())
}

pub fn post_json(url: &str, body: &Value, timeout_secs: u64) -> Result<(u16, Value, String), String> {
    let resp = client(timeout_secs)?
        .post(url)
        .json(body)
        .send()
        .map_err(|e| e.to_string())?;
    let status = resp.status().as_u16();
    let text = resp.text().map_err(|e| e.to_string())?;
    let val = serde_json::from_str(&text).unwrap_or(Value::String(text.clone()));
    Ok((status, val, text))
}

pub fn get_ok(url: &str, timeout_secs: u64) -> bool {
    client(timeout_secs)
        .ok()
        .and_then(|c| c.get(url).send().ok())
        .map(|r| r.status().is_success())
        .unwrap_or(false)
}

pub fn download_file(url: &str, dest: &std::path::Path) -> Result<u64, String> {
    if let Some(parent) = dest.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let tmp = dest.with_extension("part");
    let mut resp = client(300)?
        .get(url)
        .header("User-Agent", "BeezDesktopTwo")
        .send()
        .map_err(|e| e.to_string())?;
    if !resp.status().is_success() {
        return Err(format!("download {url}: {}", resp.status()));
    }
    let mut file = std::fs::File::create(&tmp).map_err(|e| e.to_string())?;
    let n = resp.copy_to(&mut file).map_err(|e| e.to_string())?;
    std::fs::rename(&tmp, dest).map_err(|e| e.to_string())?;
    Ok(n)
}
