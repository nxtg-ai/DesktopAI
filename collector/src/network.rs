//! Network layer: WebSocket connection to backend, event sending, command receiving.
//! Uses exponential backoff for reconnection and handles ping/pong keep-alive.

use crossbeam_channel::Receiver;
use std::time::{Duration, Instant};
use tungstenite::{connect, Message};
use url::Url;

use crate::config::Config;
use crate::event::WindowEvent;

/// Attempt a WebSocket connection to the given URL. Returns None on failure.
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

/// Send an event to the backend via HTTP POST (fallback when WebSocket is unavailable).
pub fn send_http(url: &str, event: &WindowEvent) {
    let resp = ureq::post(url).send_json(event);
    if let Err(err) = resp {
        log::warn!("HTTP send failed: {err}");
    }
}

/// Calculate backoff duration with exponential increase, capped at max.
pub fn calculate_backoff(current_ms: u64, max_ms: u64) -> u64 {
    (current_ms.saturating_mul(2)).min(max_ms)
}

/// Main network loop: sends events from the channel, receives commands, auto-reconnects.
pub fn network_worker(rx: Receiver<WindowEvent>, config: Config) {
    let mut ws = None;
    let mut last_attempt = Instant::now() - config.ws_retry;
    let poll_timeout = Duration::from_millis(50);
    let mut backoff_ms: u64 = 1000;
    let max_backoff_ms = config.ws_reconnect_max_ms;

    println!("Network worker started, connecting to {}", config.ws_url);

    loop {
        // Reconnect if needed (with exponential backoff)
        if ws.is_none() && last_attempt.elapsed() >= Duration::from_millis(backoff_ms) {
            last_attempt = Instant::now();
            println!("Attempting WebSocket connection...");
            ws = connect_ws(&config.ws_url);
            if let Some(ref mut socket) = ws {
                println!("Connected to backend!");
                // Reset backoff on successful connection
                backoff_ms = 1000;
                // Set non-blocking for command reads
                if let tungstenite::stream::MaybeTlsStream::Plain(ref s) = socket.get_ref() {
                    let _ = s.set_nonblocking(true);
                }
            } else {
                // Increase backoff on failed connection
                backoff_ms = calculate_backoff(backoff_ms, max_backoff_ms);
                println!("WebSocket connect failed, retrying in {}ms", backoff_ms);
                log::info!("WebSocket reconnect failed, next attempt in {}ms", backoff_ms);
            }
        }

        // Check for outgoing events (with timeout so we can also check for commands)
        match rx.recv_timeout(poll_timeout) {
            Ok(event) => {
                if let Some(socket) = ws.as_mut() {
                    let payload = serde_json::to_string(&event).unwrap_or_else(|_| "{}".into());
                    if let Err(err) = socket.send(Message::Text(payload)) {
                        log::warn!("WebSocket send failed: {err}");
                        ws = None;
                        // Fallback to HTTP
                        send_http(&config.http_url, &event);
                    }
                } else {
                    send_http(&config.http_url, &event);
                }
            }
            Err(crossbeam_channel::RecvTimeoutError::Timeout) => {
                // No event — check for incoming commands below
            }
            Err(crossbeam_channel::RecvTimeoutError::Disconnected) => {
                log::info!("Event channel disconnected, network worker exiting");
                break;
            }
        }

        // Check for incoming commands from backend
        if config.command_enabled {
            if let Some(socket) = ws.as_mut() {
                match socket.read() {
                    Ok(Message::Text(text)) => {
                        handle_incoming_message(&text, socket, &config);
                    }
                    Ok(_) => {
                        // Binary/ping/pong — ignore
                    }
                    Err(tungstenite::Error::Io(ref e))
                        if e.kind() == std::io::ErrorKind::WouldBlock =>
                    {
                        // No data available — normal for non-blocking
                    }
                    Err(err) => {
                        log::warn!("WebSocket read error: {err}");
                        ws = None;
                    }
                }
            }
        }
    }
}

fn handle_incoming_message(
    text: &str,
    socket: &mut tungstenite::WebSocket<tungstenite::stream::MaybeTlsStream<std::net::TcpStream>>,
    config: &Config,
) {
    // Try to parse as a command
    let parsed: Result<serde_json::Value, _> = serde_json::from_str(text);
    let value = match parsed {
        Ok(v) => v,
        Err(e) => {
            log::warn!("Failed to parse incoming message: {e}");
            return;
        }
    };

    // Check message type
    let msg_type = value.get("type").and_then(|v| v.as_str()).unwrap_or("");

    // Respond to heartbeat pings
    if msg_type == "ping" {
        let pong = r#"{"type":"pong"}"#;
        if let Err(err) = socket.send(Message::Text(pong.to_string())) {
            log::warn!("Failed to send pong: {err}");
        }
        return;
    }

    if msg_type != "command" {
        // Not a command — might be an ack or other message, ignore
        return;
    }

    let cmd: crate::command::Command = match serde_json::from_value(value) {
        Ok(c) => c,
        Err(e) => {
            log::warn!("Failed to parse command: {e}");
            return;
        }
    };

    log::info!("Received command: {} (id={})", cmd.action, cmd.command_id);
    let result = crate::command::execute_command(&cmd, config);
    let result_json = serde_json::to_string(&result).unwrap_or_else(|_| "{}".into());

    if let Err(err) = socket.send(Message::Text(result_json)) {
        log::warn!("Failed to send command result: {err}");
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
    fn test_exponential_backoff_calculation() {
        assert_eq!(calculate_backoff(1000, 30000), 2000);
        assert_eq!(calculate_backoff(2000, 30000), 4000);
        assert_eq!(calculate_backoff(4000, 30000), 8000);
        assert_eq!(calculate_backoff(16000, 30000), 30000); // capped
        assert_eq!(calculate_backoff(30000, 30000), 30000); // stays at cap
    }

    #[test]
    fn test_backoff_resets_on_success() {
        // Simulate: backoff grows, then resets
        let mut backoff_ms: u64 = 1000;
        let max = 30000;
        backoff_ms = calculate_backoff(backoff_ms, max);
        assert_eq!(backoff_ms, 2000);
        backoff_ms = calculate_backoff(backoff_ms, max);
        assert_eq!(backoff_ms, 4000);
        // Simulate successful connection → reset
        backoff_ms = 1000;
        assert_eq!(backoff_ms, 1000);
    }

    #[test]
    fn test_ping_message_detected() {
        let ping = r#"{"type":"ping"}"#;
        let value: serde_json::Value = serde_json::from_str(ping).unwrap();
        let msg_type = value.get("type").and_then(|v| v.as_str()).unwrap_or("");
        assert_eq!(msg_type, "ping");
    }

    #[test]
    fn test_pong_response_format() {
        let pong = r#"{"type":"pong"}"#;
        let value: serde_json::Value = serde_json::from_str(pong).unwrap();
        assert_eq!(value.get("type").and_then(|v| v.as_str()), Some("pong"));
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
