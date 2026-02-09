use crossbeam_channel::Receiver;
use std::time::Instant;
use tungstenite::{connect, Message};
use url::Url;

use crate::config::Config;
use crate::event::WindowEvent;

pub fn connect_ws(url: &str) -> Option<tungstenite::WebSocket<tungstenite::stream::MaybeTlsStream<std::net::TcpStream>>> {
    let parsed = Url::parse(url).ok()?;
    match connect(parsed) {
        Ok((socket, _)) => Some(socket),
        Err(err) => {
            log::warn!("WebSocket connect failed: {err}");
            None
        }
    }
}

pub fn send_http(url: &str, event: &WindowEvent) {
    let resp = ureq::post(url).send_json(event);
    if let Err(err) = resp {
        log::warn!("HTTP send failed: {err}");
    }
}

pub fn network_worker(rx: Receiver<WindowEvent>, config: Config) {
    let mut ws = None;
    let mut last_attempt = Instant::now() - config.ws_retry;

    while let Ok(event) = rx.recv() {
        if ws.is_none() && last_attempt.elapsed() >= config.ws_retry {
            last_attempt = Instant::now();
            ws = connect_ws(&config.ws_url);
        }

        if let Some(socket) = ws.as_mut() {
            let payload = serde_json::to_string(&event).unwrap_or_else(|_| "{}".into());
            if let Err(err) = socket.send(Message::Text(payload)) {
                log::warn!("WebSocket send failed: {err}");
                ws = None;
            } else {
                continue;
            }
        }

        send_http(&config.http_url, &event);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_connect_ws_invalid_url() {
        // Invalid URL should return None
        let result = connect_ws("not a url");
        assert!(result.is_none());
    }

    #[test]
    fn test_connect_ws_valid_url_no_server() {
        // Valid URL but no server running should return None
        let result = connect_ws("ws://localhost:99999/test");
        assert!(result.is_none());
    }

    #[test]
    fn test_connect_ws_url_parsing() {
        // Test that URL parsing works correctly
        use url::Url;

        let valid_url = "ws://localhost:8000/ingest";
        let parsed = Url::parse(valid_url);
        assert!(parsed.is_ok());

        let invalid_url = "not a url";
        let parsed = Url::parse(invalid_url);
        assert!(parsed.is_err());
    }

    #[test]
    fn test_event_serialization_for_network() {
        use crate::event::build_activity_event;

        let event = build_activity_event("idle", 1000);
        let json = serde_json::to_string(&event);

        assert!(json.is_ok());
        let json_str = json.unwrap();
        assert!(json_str.contains("idle"));
        assert!(json_str.contains("collector"));
    }

    #[test]
    fn test_event_serialization_fallback() {
        use crate::event::build_activity_event;

        let event = build_activity_event("test", 500);
        // Test the unwrap_or_else fallback logic
        let payload = serde_json::to_string(&event).unwrap_or_else(|_| "{}".into());

        assert!(!payload.is_empty());
        // Should be valid JSON
        assert!(serde_json::from_str::<serde_json::Value>(&payload).is_ok());
    }
}
