//! Idle detection: polls GetLastInputInfo to detect user idle/active transitions.

use crossbeam_channel::Sender;
use std::thread;

use crate::config::Config;
use crate::event::{build_activity_event, WindowEvent};

#[cfg(windows)]
use crate::windows::idle_duration_ms;

#[cfg(not(windows))]
fn idle_duration_ms() -> Option<u64> {
    // Stub for non-Windows platforms in tests
    None
}

pub fn idle_worker(tx: Sender<WindowEvent>, config: Config) {
    if !config.idle_enabled {
        return;
    }
    let mut last_state: Option<bool> = None;
    loop {
        if let Some(idle_ms) = idle_duration_ms() {
            let now_idle = idle_ms >= config.idle_threshold.as_millis() as u64;
            if last_state.map(|state| state != now_idle).unwrap_or(true) {
                let event_type = if now_idle { "idle" } else { "active" };
                let event = build_activity_event(event_type, idle_ms);
                let _ = tx.send(event);
                last_state = Some(now_idle);
            }
        }
        thread::sleep(config.idle_poll);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crossbeam_channel::unbounded;
    use std::time::Duration;

    #[test]
    fn test_idle_worker_disabled_returns_immediately() {
        let (tx, rx) = unbounded();
        let mut config = Config {
            ws_url: String::new(),
            http_url: String::new(),
            ws_retry: Duration::from_secs(1),
            idle_enabled: false,
            idle_threshold: Duration::from_millis(60000),
            idle_poll: Duration::from_millis(1000),
            uia_enabled: false,
            uia_throttle: Duration::from_millis(1000),
            uia_text_max: 240,
            uia_max_depth: 5,
            enable_screenshot: false,
            screenshot_max_width: 1920,
            screenshot_max_height: 1080,
            screenshot_quality: 85,
            command_enabled: true,
            screenshot_format: "jpeg".into(),
            uia_cache_ttl_ms: 2000,
            ws_reconnect_max_ms: 30_000,
            detection_enabled: false,
            detection_model_path: String::new(),
            detection_confidence: 0.3,
        };

        // Should return immediately when idle_enabled is false
        config.idle_enabled = false;
        idle_worker(tx, config);

        // Channel should be empty since worker returned immediately
        assert!(rx.try_recv().is_err());
    }

    #[test]
    fn test_idle_threshold_comparison() {
        let threshold_ms = 60000u64;
        let threshold_duration = Duration::from_millis(threshold_ms);

        // Test idle detection logic
        let idle_ms_1 = 30000u64;
        let now_idle_1 = idle_ms_1 >= threshold_duration.as_millis() as u64;
        assert!(!now_idle_1, "30s should not be idle with 60s threshold");

        let idle_ms_2 = 60000u64;
        let now_idle_2 = idle_ms_2 >= threshold_duration.as_millis() as u64;
        assert!(now_idle_2, "60s should be idle with 60s threshold");

        let idle_ms_3 = 120000u64;
        let now_idle_3 = idle_ms_3 >= threshold_duration.as_millis() as u64;
        assert!(now_idle_3, "120s should be idle with 60s threshold");
    }

    #[test]
    fn test_state_change_detection() {
        let last_state: Option<bool> = None;
        let now_idle = true;

        // First time (None) should trigger event
        let should_send = last_state.map(|state| state != now_idle).unwrap_or(true);
        assert!(should_send);

        // Same state should not trigger event
        let last_state = Some(true);
        let now_idle = true;
        let should_send = last_state.map(|state| state != now_idle).unwrap_or(true);
        assert!(!should_send);

        // Different state should trigger event
        let last_state = Some(true);
        let now_idle = false;
        let should_send = last_state.map(|state| state != now_idle).unwrap_or(true);
        assert!(should_send);

        // Back to different state should trigger event
        let last_state = Some(false);
        let now_idle = true;
        let should_send = last_state.map(|state| state != now_idle).unwrap_or(true);
        assert!(should_send);
    }

    #[test]
    fn test_event_type_selection() {
        // Test event type selection logic
        let now_idle = true;
        let event_type = if now_idle { "idle" } else { "active" };
        assert_eq!(event_type, "idle");

        let now_idle = false;
        let event_type = if now_idle { "idle" } else { "active" };
        assert_eq!(event_type, "active");
    }

    #[test]
    fn test_build_activity_event_integration() {
        // Test that build_activity_event creates correct events
        let idle_event = build_activity_event("idle", 120000);
        assert_eq!(idle_event.event_type, "idle");
        assert_eq!(idle_event.idle_ms, Some(120000));

        let active_event = build_activity_event("active", 500);
        assert_eq!(active_event.event_type, "active");
        assert_eq!(active_event.idle_ms, Some(500));
    }
}
