use std::env;
use std::time::Duration;

#[derive(Clone)]
pub struct Config {
    pub ws_url: String,
    pub http_url: String,
    pub ws_retry: Duration,
    pub idle_enabled: bool,
    pub idle_threshold: Duration,
    pub idle_poll: Duration,
    pub uia_enabled: bool,
    pub uia_throttle: Duration,
    pub uia_text_max: usize,
    pub uia_max_depth: usize,
    pub enable_screenshot: bool,
    pub screenshot_max_width: u32,
    pub screenshot_max_height: u32,
    pub screenshot_quality: u8,
}

impl Config {
    pub fn from_env() -> Self {
        let ws_url =
            env::var("BACKEND_WS_URL").unwrap_or_else(|_| "ws://localhost:8000/ingest".into());
        let http_url =
            env::var("BACKEND_HTTP_URL").unwrap_or_else(|_| "http://localhost:8000/api/events".into());
        let retry = env::var("WS_RETRY_SECONDS")
            .ok()
            .and_then(|v| v.parse::<u64>().ok())
            .unwrap_or(5);
        let idle_enabled = env_bool("IDLE_ENABLED", true);
        let idle_threshold = Duration::from_millis(env_u64("IDLE_THRESHOLD_MS", 60_000));
        let idle_poll = Duration::from_millis(env_u64("IDLE_POLL_MS", 1000));
        let uia_enabled = env_bool("UIA_ENABLED", false);
        let uia_throttle = Duration::from_millis(env_u64("UIA_THROTTLE_MS", 1000));
        let uia_text_max = env_usize("UIA_TEXT_MAX_CHARS", 240);
        let uia_max_depth = env_usize("UIA_MAX_DEPTH", 3);
        let enable_screenshot = env_bool("ENABLE_SCREENSHOT", false);
        let screenshot_max_width = env_u32("SCREENSHOT_MAX_WIDTH", 1024);
        let screenshot_max_height = env_u32("SCREENSHOT_MAX_HEIGHT", 768);
        let screenshot_quality = env_u8("SCREENSHOT_QUALITY", 85);
        Self {
            ws_url,
            http_url,
            ws_retry: Duration::from_secs(retry),
            idle_enabled,
            idle_threshold,
            idle_poll,
            uia_enabled,
            uia_throttle,
            uia_text_max,
            uia_max_depth,
            enable_screenshot,
            screenshot_max_width,
            screenshot_max_height,
            screenshot_quality,
        }
    }
}

pub fn env_bool(name: &str, default: bool) -> bool {
    let raw = env::var(name).ok();
    match raw.as_deref().map(|v| v.trim().to_lowercase()) {
        Some(v) if v == "1" || v == "true" || v == "yes" || v == "on" => true,
        Some(v) if v == "0" || v == "false" || v == "no" || v == "off" => false,
        _ => default,
    }
}

pub fn env_u64(name: &str, default: u64) -> u64 {
    env::var(name)
        .ok()
        .and_then(|v| v.parse::<u64>().ok())
        .unwrap_or(default)
}

pub fn env_usize(name: &str, default: usize) -> usize {
    env::var(name)
        .ok()
        .and_then(|v| v.parse::<usize>().ok())
        .unwrap_or(default)
}

pub fn env_u32(name: &str, default: u32) -> u32 {
    env::var(name)
        .ok()
        .and_then(|v| v.parse::<u32>().ok())
        .unwrap_or(default)
}

pub fn env_u8(name: &str, default: u8) -> u8 {
    env::var(name)
        .ok()
        .and_then(|v| v.parse::<u8>().ok())
        .unwrap_or(default)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::env;
    use std::sync::Mutex;

    /// Env-var-mutating tests must hold this lock to avoid parallel pollution.
    static ENV_LOCK: Mutex<()> = Mutex::new(());

    #[test]
    fn test_env_bool_true_variants() {
        let _guard = ENV_LOCK.lock().unwrap();
        env::set_var("TEST_BOOL_TRUE", "TRUE");
        assert!(env_bool("TEST_BOOL_TRUE", false));
        env::remove_var("TEST_BOOL_TRUE");

        env::set_var("TEST_BOOL_TRUE", "true");
        assert!(env_bool("TEST_BOOL_TRUE", false));
        env::remove_var("TEST_BOOL_TRUE");

        env::set_var("TEST_BOOL_TRUE", "1");
        assert!(env_bool("TEST_BOOL_TRUE", false));
        env::remove_var("TEST_BOOL_TRUE");

        env::set_var("TEST_BOOL_TRUE", "yes");
        assert!(env_bool("TEST_BOOL_TRUE", false));
        env::remove_var("TEST_BOOL_TRUE");

        env::set_var("TEST_BOOL_TRUE", "on");
        assert!(env_bool("TEST_BOOL_TRUE", false));
        env::remove_var("TEST_BOOL_TRUE");

        env::set_var("TEST_BOOL_TRUE", "  TRUE  ");
        assert!(env_bool("TEST_BOOL_TRUE", false));
        env::remove_var("TEST_BOOL_TRUE");
    }

    #[test]
    fn test_env_bool_false_variants() {
        let _guard = ENV_LOCK.lock().unwrap();
        env::set_var("TEST_BOOL_FALSE", "FALSE");
        assert!(!env_bool("TEST_BOOL_FALSE", true));
        env::remove_var("TEST_BOOL_FALSE");

        env::set_var("TEST_BOOL_FALSE", "false");
        assert!(!env_bool("TEST_BOOL_FALSE", true));
        env::remove_var("TEST_BOOL_FALSE");

        env::set_var("TEST_BOOL_FALSE", "0");
        assert!(!env_bool("TEST_BOOL_FALSE", true));
        env::remove_var("TEST_BOOL_FALSE");

        env::set_var("TEST_BOOL_FALSE", "no");
        assert!(!env_bool("TEST_BOOL_FALSE", true));
        env::remove_var("TEST_BOOL_FALSE");

        env::set_var("TEST_BOOL_FALSE", "off");
        assert!(!env_bool("TEST_BOOL_FALSE", true));
        env::remove_var("TEST_BOOL_FALSE");

        env::set_var("TEST_BOOL_FALSE", "  false  ");
        assert!(!env_bool("TEST_BOOL_FALSE", true));
        env::remove_var("TEST_BOOL_FALSE");
    }

    #[test]
    fn test_env_bool_empty_uses_default() {
        let _guard = ENV_LOCK.lock().unwrap();
        env::set_var("TEST_BOOL_EMPTY", "");
        assert!(env_bool("TEST_BOOL_EMPTY", true));
        assert!(!env_bool("TEST_BOOL_EMPTY", false));
        env::remove_var("TEST_BOOL_EMPTY");
    }

    #[test]
    fn test_env_bool_missing_uses_default() {
        let _guard = ENV_LOCK.lock().unwrap();
        env::remove_var("TEST_BOOL_MISSING");
        assert!(env_bool("TEST_BOOL_MISSING", true));
        assert!(!env_bool("TEST_BOOL_MISSING", false));
    }

    #[test]
    fn test_env_bool_invalid_uses_default() {
        let _guard = ENV_LOCK.lock().unwrap();
        env::set_var("TEST_BOOL_INVALID", "maybe");
        assert!(env_bool("TEST_BOOL_INVALID", true));
        assert!(!env_bool("TEST_BOOL_INVALID", false));
        env::remove_var("TEST_BOOL_INVALID");
    }

    #[test]
    fn test_env_u64_valid_value() {
        let _guard = ENV_LOCK.lock().unwrap();
        env::set_var("TEST_U64_VALID", "12345");
        assert_eq!(env_u64("TEST_U64_VALID", 999), 12345);
        env::remove_var("TEST_U64_VALID");
    }

    #[test]
    fn test_env_u64_zero() {
        let _guard = ENV_LOCK.lock().unwrap();
        env::set_var("TEST_U64_ZERO", "0");
        assert_eq!(env_u64("TEST_U64_ZERO", 999), 0);
        env::remove_var("TEST_U64_ZERO");
    }

    #[test]
    fn test_env_u64_max() {
        let _guard = ENV_LOCK.lock().unwrap();
        let max_val = u64::MAX.to_string();
        env::set_var("TEST_U64_MAX", &max_val);
        assert_eq!(env_u64("TEST_U64_MAX", 999), u64::MAX);
        env::remove_var("TEST_U64_MAX");
    }

    #[test]
    fn test_env_u64_invalid_uses_default() {
        let _guard = ENV_LOCK.lock().unwrap();
        env::set_var("TEST_U64_INVALID", "not_a_number");
        assert_eq!(env_u64("TEST_U64_INVALID", 999), 999);
        env::remove_var("TEST_U64_INVALID");

        env::set_var("TEST_U64_INVALID", "-1");
        assert_eq!(env_u64("TEST_U64_INVALID", 999), 999);
        env::remove_var("TEST_U64_INVALID");
    }

    #[test]
    fn test_env_u64_missing_uses_default() {
        let _guard = ENV_LOCK.lock().unwrap();
        env::remove_var("TEST_U64_MISSING");
        assert_eq!(env_u64("TEST_U64_MISSING", 999), 999);
    }

    #[test]
    fn test_env_usize_valid_value() {
        let _guard = ENV_LOCK.lock().unwrap();
        env::set_var("TEST_USIZE_VALID", "54321");
        assert_eq!(env_usize("TEST_USIZE_VALID", 111), 54321);
        env::remove_var("TEST_USIZE_VALID");
    }

    #[test]
    fn test_env_usize_zero() {
        let _guard = ENV_LOCK.lock().unwrap();
        env::set_var("TEST_USIZE_ZERO", "0");
        assert_eq!(env_usize("TEST_USIZE_ZERO", 111), 0);
        env::remove_var("TEST_USIZE_ZERO");
    }

    #[test]
    fn test_env_usize_invalid_uses_default() {
        let _guard = ENV_LOCK.lock().unwrap();
        env::set_var("TEST_USIZE_INVALID", "invalid");
        assert_eq!(env_usize("TEST_USIZE_INVALID", 111), 111);
        env::remove_var("TEST_USIZE_INVALID");

        env::set_var("TEST_USIZE_INVALID", "-10");
        assert_eq!(env_usize("TEST_USIZE_INVALID", 111), 111);
        env::remove_var("TEST_USIZE_INVALID");
    }

    #[test]
    fn test_env_usize_missing_uses_default() {
        let _guard = ENV_LOCK.lock().unwrap();
        env::remove_var("TEST_USIZE_MISSING");
        assert_eq!(env_usize("TEST_USIZE_MISSING", 111), 111);
    }

    #[test]
    fn test_env_u32_valid_value() {
        let _guard = ENV_LOCK.lock().unwrap();
        env::set_var("TEST_U32_VALID", "1920");
        assert_eq!(env_u32("TEST_U32_VALID", 999), 1920);
        env::remove_var("TEST_U32_VALID");
    }

    #[test]
    fn test_env_u32_zero() {
        let _guard = ENV_LOCK.lock().unwrap();
        env::set_var("TEST_U32_ZERO", "0");
        assert_eq!(env_u32("TEST_U32_ZERO", 999), 0);
        env::remove_var("TEST_U32_ZERO");
    }

    #[test]
    fn test_env_u32_max() {
        let _guard = ENV_LOCK.lock().unwrap();
        let max_val = u32::MAX.to_string();
        env::set_var("TEST_U32_MAX", &max_val);
        assert_eq!(env_u32("TEST_U32_MAX", 999), u32::MAX);
        env::remove_var("TEST_U32_MAX");
    }

    #[test]
    fn test_env_u32_invalid_uses_default() {
        let _guard = ENV_LOCK.lock().unwrap();
        env::set_var("TEST_U32_INVALID", "not_a_number");
        assert_eq!(env_u32("TEST_U32_INVALID", 999), 999);
        env::remove_var("TEST_U32_INVALID");

        env::set_var("TEST_U32_INVALID", "-1");
        assert_eq!(env_u32("TEST_U32_INVALID", 999), 999);
        env::remove_var("TEST_U32_INVALID");
    }

    #[test]
    fn test_env_u32_missing_uses_default() {
        let _guard = ENV_LOCK.lock().unwrap();
        env::remove_var("TEST_U32_MISSING");
        assert_eq!(env_u32("TEST_U32_MISSING", 999), 999);
    }

    #[test]
    fn test_env_u8_valid_value() {
        let _guard = ENV_LOCK.lock().unwrap();
        env::set_var("TEST_U8_VALID", "85");
        assert_eq!(env_u8("TEST_U8_VALID", 50), 85);
        env::remove_var("TEST_U8_VALID");
    }

    #[test]
    fn test_env_u8_zero() {
        let _guard = ENV_LOCK.lock().unwrap();
        env::set_var("TEST_U8_ZERO", "0");
        assert_eq!(env_u8("TEST_U8_ZERO", 50), 0);
        env::remove_var("TEST_U8_ZERO");
    }

    #[test]
    fn test_env_u8_max() {
        let _guard = ENV_LOCK.lock().unwrap();
        env::set_var("TEST_U8_MAX", "255");
        assert_eq!(env_u8("TEST_U8_MAX", 50), 255);
        env::remove_var("TEST_U8_MAX");
    }

    #[test]
    fn test_env_u8_invalid_uses_default() {
        let _guard = ENV_LOCK.lock().unwrap();
        env::set_var("TEST_U8_INVALID", "not_a_number");
        assert_eq!(env_u8("TEST_U8_INVALID", 50), 50);
        env::remove_var("TEST_U8_INVALID");

        env::set_var("TEST_U8_INVALID", "-1");
        assert_eq!(env_u8("TEST_U8_INVALID", 50), 50);
        env::remove_var("TEST_U8_INVALID");

        env::set_var("TEST_U8_INVALID", "256");
        assert_eq!(env_u8("TEST_U8_INVALID", 50), 50);
        env::remove_var("TEST_U8_INVALID");
    }

    #[test]
    fn test_env_u8_missing_uses_default() {
        let _guard = ENV_LOCK.lock().unwrap();
        env::remove_var("TEST_U8_MISSING");
        assert_eq!(env_u8("TEST_U8_MISSING", 50), 50);
    }

    #[test]
    fn test_config_from_env_defaults() {
        let _guard = ENV_LOCK.lock().unwrap();
        // Clear all relevant env vars
        env::remove_var("BACKEND_WS_URL");
        env::remove_var("BACKEND_HTTP_URL");
        env::remove_var("WS_RETRY_SECONDS");
        env::remove_var("IDLE_ENABLED");
        env::remove_var("IDLE_THRESHOLD_MS");
        env::remove_var("IDLE_POLL_MS");
        env::remove_var("UIA_ENABLED");
        env::remove_var("UIA_THROTTLE_MS");
        env::remove_var("UIA_TEXT_MAX_CHARS");
        env::remove_var("UIA_MAX_DEPTH");
        env::remove_var("ENABLE_SCREENSHOT");
        env::remove_var("SCREENSHOT_MAX_WIDTH");
        env::remove_var("SCREENSHOT_MAX_HEIGHT");
        env::remove_var("SCREENSHOT_QUALITY");

        let config = Config::from_env();

        assert_eq!(config.ws_url, "ws://localhost:8000/ingest");
        assert_eq!(config.http_url, "http://localhost:8000/api/events");
        assert_eq!(config.ws_retry, Duration::from_secs(5));
        assert!(config.idle_enabled);
        assert_eq!(config.idle_threshold, Duration::from_millis(60_000));
        assert_eq!(config.idle_poll, Duration::from_millis(1000));
        assert!(!config.uia_enabled);
        assert_eq!(config.uia_throttle, Duration::from_millis(1000));
        assert_eq!(config.uia_text_max, 240);
        assert_eq!(config.uia_max_depth, 3);
        assert!(!config.enable_screenshot);
        assert_eq!(config.screenshot_max_width, 1024);
        assert_eq!(config.screenshot_max_height, 768);
        assert_eq!(config.screenshot_quality, 85);
    }

    #[test]
    fn test_config_from_env_custom_values() {
        let _guard = ENV_LOCK.lock().unwrap();
        env::set_var("BACKEND_WS_URL", "ws://custom:9000/ws");
        env::set_var("BACKEND_HTTP_URL", "http://custom:9000/events");
        env::set_var("WS_RETRY_SECONDS", "10");
        env::set_var("IDLE_ENABLED", "false");
        env::set_var("IDLE_THRESHOLD_MS", "120000");
        env::set_var("IDLE_POLL_MS", "2000");
        env::set_var("UIA_ENABLED", "true");
        env::set_var("UIA_THROTTLE_MS", "500");
        env::set_var("UIA_TEXT_MAX_CHARS", "500");
        env::set_var("UIA_MAX_DEPTH", "10");
        env::set_var("ENABLE_SCREENSHOT", "true");
        env::set_var("SCREENSHOT_MAX_WIDTH", "1920");
        env::set_var("SCREENSHOT_MAX_HEIGHT", "1080");
        env::set_var("SCREENSHOT_QUALITY", "90");

        let config = Config::from_env();

        assert_eq!(config.ws_url, "ws://custom:9000/ws");
        assert_eq!(config.http_url, "http://custom:9000/events");
        assert_eq!(config.ws_retry, Duration::from_secs(10));
        assert!(!config.idle_enabled);
        assert_eq!(config.idle_threshold, Duration::from_millis(120000));
        assert_eq!(config.idle_poll, Duration::from_millis(2000));
        assert!(config.uia_enabled);
        assert_eq!(config.uia_throttle, Duration::from_millis(500));
        assert_eq!(config.uia_text_max, 500);
        assert_eq!(config.uia_max_depth, 10);
        assert!(config.enable_screenshot);
        assert_eq!(config.screenshot_max_width, 1920);
        assert_eq!(config.screenshot_max_height, 1080);
        assert_eq!(config.screenshot_quality, 90);

        // Cleanup
        env::remove_var("BACKEND_WS_URL");
        env::remove_var("BACKEND_HTTP_URL");
        env::remove_var("WS_RETRY_SECONDS");
        env::remove_var("IDLE_ENABLED");
        env::remove_var("IDLE_THRESHOLD_MS");
        env::remove_var("IDLE_POLL_MS");
        env::remove_var("UIA_ENABLED");
        env::remove_var("UIA_THROTTLE_MS");
        env::remove_var("UIA_TEXT_MAX_CHARS");
        env::remove_var("UIA_MAX_DEPTH");
        env::remove_var("ENABLE_SCREENSHOT");
        env::remove_var("SCREENSHOT_MAX_WIDTH");
        env::remove_var("SCREENSHOT_MAX_HEIGHT");
        env::remove_var("SCREENSHOT_QUALITY");
    }

    #[test]
    fn test_config_clone() {
        let _guard = ENV_LOCK.lock().unwrap();
        let config1 = Config::from_env();
        let config2 = config1.clone();
        assert_eq!(config1.ws_url, config2.ws_url);
        assert_eq!(config1.http_url, config2.http_url);
        assert_eq!(config1.idle_enabled, config2.idle_enabled);
    }
}
