use std::env;
use std::path::PathBuf;

pub const APP_WALLET_NAME: &str = "BeezDesktopTwo";
pub const LEGACY_WALLET_NAME: &str = "BeezDesktop";

pub fn home_dir() -> PathBuf {
    env::var_os("USERPROFILE")
        .or_else(|| env::var_os("HOME"))
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("."))
}

pub fn data_dir(app_name: &str) -> PathBuf {
    if cfg!(windows) {
        let base = env::var_os("APPDATA")
            .map(PathBuf::from)
            .unwrap_or_else(|| home_dir().join("AppData").join("Roaming"));
        return base.join(app_name);
    }
    if cfg!(target_os = "macos") {
        return home_dir()
            .join("Library")
            .join("Application Support")
            .join(app_name);
    }
    let base = env::var_os("XDG_DATA_HOME")
        .map(PathBuf::from)
        .unwrap_or_else(|| home_dir().join(".local").join("share"));
    base.join(app_name)
}

pub fn models_dir() -> PathBuf {
    data_dir(APP_WALLET_NAME).join("models")
}
