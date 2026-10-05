use std::sync::Mutex;

use fastembed::{EmbeddingModel, InitOptions, TextEmbedding};
use once_cell::sync::Lazy;

use crate::paths::models_dir;

static ENGINE: Lazy<Mutex<Option<TextEmbedding>>> = Lazy::new(|| Mutex::new(None));

pub fn status() -> serde_json::Value {
    let ready = ENGINE.lock().ok().map(|g| g.is_some()).unwrap_or(false);
    let cache = models_dir();
    let present = cache.join("models").exists() || cache.exists();
    serde_json::json!({
        "ok": true,
        "ready": ready,
        "cache_dir": cache.display().to_string(),
        "model": "BAAI/bge-small-en-v1.5",
        "cache_present": present,
    })
}

pub fn ensure() -> Result<(), String> {
    let mut guard = ENGINE.lock().map_err(|e| e.to_string())?;
    if guard.is_some() {
        return Ok(());
    }
    let cache = models_dir();
    std::fs::create_dir_all(&cache).map_err(|e| e.to_string())?;
    let options = InitOptions::new(EmbeddingModel::BGESmallENV15).with_cache_dir(cache);
    let model = TextEmbedding::try_new(options).map_err(|e| format!("embedding model: {e}"))?;
    *guard = Some(model);
    Ok(())
}

pub fn embed_texts(texts: &[String]) -> Result<Vec<Vec<f32>>, String> {
    if texts.is_empty() {
        return Ok(Vec::new());
    }
    ensure()?;
    let mut guard = ENGINE.lock().map_err(|e| e.to_string())?;
    let model = guard.as_mut().ok_or("embedding engine missing")?;
    model
        .embed(texts.to_vec(), None)
        .map_err(|e| format!("embed: {e}"))
}

pub fn embed_query(query: &str) -> Result<Vec<f32>, String> {
    if query.is_empty() {
        return Ok(vec![0.0; 384]);
    }
    Ok(embed_texts(&[query.to_string()])?.into_iter().next().unwrap_or_else(|| vec![0.0; 384]))
}
