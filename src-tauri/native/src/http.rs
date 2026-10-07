use reqwest::blocking::Client;
use serde_json::Value;
use std::io::{Read, Write};
use std::time::Duration;

fn client(timeout_secs: u64, connect_ms: u64) -> Result<Client, String> {
    Client::builder()
        .connect_timeout(Duration::from_millis(connect_ms))
        .timeout(Duration::from_secs(timeout_secs.max(1)))
        .redirect(reqwest::redirect::Policy::limited(10))
        .build()
        .map_err(|e| e.to_string())
}

pub fn get_json(url: &str, timeout_secs: u64) -> Result<Value, String> {
    get_json_connect(url, timeout_secs, 1500)
}

pub fn get_json_connect(url: &str, timeout_secs: u64, connect_ms: u64) -> Result<Value, String> {
    let resp = client(timeout_secs, connect_ms)?
        .get(url)
        .send()
        .map_err(|e| e.to_string())?;
    let status = resp.status();
    let text = resp.text().map_err(|e| e.to_string())?;
    if !status.is_success() {
        return Err(format!(
            "{status}: {}",
            text.chars().take(400).collect::<String>()
        ));
    }
    serde_json::from_str(&text).map_err(|e| e.to_string())
}

pub fn get_json_query(
    url: &str,
    query: &[(&str, String)],
    timeout_secs: u64,
) -> Result<Value, String> {
    let resp = client(timeout_secs, 1500)?
        .get(url)
        .query(query)
        .send()
        .map_err(|e| e.to_string())?;
    let status = resp.status();
    let text = resp.text().map_err(|e| e.to_string())?;
    if !status.is_success() {
        return Err(format!(
            "{status}: {}",
            text.chars().take(400).collect::<String>()
        ));
    }
    serde_json::from_str(&text).map_err(|e| e.to_string())
}

pub fn post_json(url: &str, body: &Value, timeout_secs: u64) -> Result<(u16, Value, String), String> {
    let resp = client(timeout_secs, 4000)?
        .post(url)
        .json(body)
        .send()
        .map_err(|e| e.to_string())?;
    let status = resp.status().as_u16();
    let text = resp.text().map_err(|e| e.to_string())?;
    let val = serde_json::from_str(&text).unwrap_or(Value::String(text.clone()));
    Ok((status, val, text))
}

pub fn get_bytes(url: &str, timeout_secs: u64) -> Result<Vec<u8>, String> {
    let mut resp = client(timeout_secs, 3000)?
        .get(url)
        .send()
        .map_err(|e| e.to_string())?;
    let status = resp.status();
    if !status.is_success() {
        let text = resp.text().unwrap_or_default();
        return Err(format!(
            "{status}: {}",
            text.chars().take(200).collect::<String>()
        ));
    }
    let mut buf = Vec::new();
    resp.read_to_end(&mut buf).map_err(|e| e.to_string())?;
    Ok(buf)
}

pub fn get_ok(url: &str, timeout_secs: u64) -> bool {
    client(timeout_secs, 400)
        .ok()
        .and_then(|c| c.get(url).send().ok())
        .map(|r| r.status().is_success())
        .unwrap_or(false)
}

pub fn download_file_progress<F>(
    url: &str,
    dest: &std::path::Path,
    mut on_progress: F,
) -> Result<u64, String>
where
    F: FnMut(u64, Option<u64>),
{
    if let Some(parent) = dest.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let tmp = dest.with_extension("part");
    let mut resp = client(600, 8000)?
        .get(url)
        .header("User-Agent", "BeezDesktopTwo/0.1.23")
        .send()
        .map_err(|e| e.to_string())?;
    if !resp.status().is_success() {
        return Err(format!("download {url}: {}", resp.status()));
    }
    let total = resp.content_length();
    let mut file = std::fs::File::create(&tmp).map_err(|e| e.to_string())?;
    let mut n = 0u64;
    let mut buf = [0u8; 64 * 1024];
    loop {
        let read = resp.read(&mut buf).map_err(|e| e.to_string())?;
        if read == 0 {
            break;
        }
        file.write_all(&buf[..read]).map_err(|e| e.to_string())?;
        n += read as u64;
        on_progress(n, total);
    }
    std::fs::rename(&tmp, dest).map_err(|e| e.to_string())?;
    Ok(n)
}
