use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

use once_cell::sync::Lazy;
use serde_json::{json, Value};

use crate::ops;

const KEEP_FINISHED: usize = 20;

static JOBS: Lazy<Mutex<Vec<Value>>> = Lazy::new(|| Mutex::new(Vec::new()));

fn now_secs() -> u64 {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).unwrap_or(0)
}

fn update(id: &str, f: impl FnOnce(&mut Value)) {
    let mut jobs = JOBS.lock().unwrap();
    if let Some(job) = jobs.iter_mut().find(|j| j["id"] == id) {
        f(job);
    }
}

/// Handle given to a running job to publish its stage and progress.
pub struct Progress {
    id: String,
}

impl Progress {
    pub fn set(&self, stage: &str, done: u64, total: u64) {
        update(&self.id, |j| {
            j["stage"] = json!(stage);
            j["done"] = json!(done);
            j["total"] = json!(total);
        });
    }
}

fn spawn(kind: &str, label: &str, run: impl FnOnce(&Progress) -> Value + Send + 'static) -> String {
    let id = uuid::Uuid::new_v4().to_string();
    {
        let mut jobs = JOBS.lock().unwrap();
        let finished: Vec<usize> = jobs
            .iter()
            .enumerate()
            .filter(|(_, j)| j["status"] != "running")
            .map(|(i, _)| i)
            .collect();
        if finished.len() >= KEEP_FINISHED {
            jobs.remove(finished[0]);
        }
        jobs.push(json!({
            "id": id, "kind": kind, "label": label, "status": "running",
            "stage": "Starting", "done": 0, "total": 0,
            "started": now_secs(), "finished": null, "result": null,
        }));
    }
    let progress = Progress { id: id.clone() };
    std::thread::spawn(move || {
        let result = run(&progress);
        let status = if result["ok"] == true { "done" } else { "error" };
        update(&progress.id, |j| {
            j["status"] = json!(status);
            j["result"] = result;
            j["finished"] = json!(now_secs());
        });
    });
    id
}

/// Start a background job: `index` (embed + upload a file) or `index_estimate`.
pub fn start(params: &Value) -> Value {
    let kind = params.get("kind").and_then(|v| v.as_str()).unwrap_or("");
    let inner = params.get("params").cloned().unwrap_or(json!({}));
    let file = inner
        .get("path")
        .and_then(|v| v.as_str())
        .and_then(|p| std::path::Path::new(p).file_name().and_then(|s| s.to_str()).map(str::to_string))
        .unwrap_or_else(|| "file".into());
    let id = match kind {
        "index" => spawn(kind, &format!("Indexing {file}"), move |p| ops::index_file_with(&inner, p)),
        "index_estimate" => spawn(kind, &format!("Estimating {file}"), move |p| ops::index_estimate_with(&inner, p)),
        other => return json!({"ok": false, "error": format!("unknown job kind {other}")}),
    };
    json!({"ok": true, "id": id})
}

pub fn status(params: &Value) -> Value {
    let id = params.get("id").and_then(|v| v.as_str()).unwrap_or("");
    match JOBS.lock().unwrap().iter().find(|j| j["id"] == id) {
        Some(job) => json!({"ok": true, "job": job}),
        None => json!({"ok": false, "error": "unknown job"}),
    }
}

pub fn list() -> Value {
    json!({"ok": true, "jobs": *JOBS.lock().unwrap()})
}

pub fn dismiss(params: &Value) -> Value {
    let id = params.get("id").and_then(|v| v.as_str()).unwrap_or("");
    JOBS.lock().unwrap().retain(|j| j["id"] != id || j["status"] == "running");
    json!({"ok": true})
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn job_reports_progress_then_result() {
        let id = spawn("test", "Test job", |p| {
            p.set("Working", 1, 2);
            json!({"ok": true, "value": 7})
        });
        let mut job = json!(null);
        for _ in 0..100 {
            job = status(&json!({"id": id}))["job"].clone();
            if job["status"] != "running" {
                break;
            }
            std::thread::sleep(std::time::Duration::from_millis(10));
        }
        assert_eq!(job["status"], "done");
        assert_eq!(job["result"]["value"], 7);
        assert_eq!(job["done"], 1);
        dismiss(&json!({"id": id}));
        assert_eq!(status(&json!({"id": id}))["ok"], false);
    }
}
