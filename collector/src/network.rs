use crossbeam_channel::Receiver;
use std::time::{Duration, Instant};
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
    let poll_timeout = Duration::from_millis(50);

    loop {
        // Reconnect if needed
        if ws.is_none() && last_attempt.elapsed() >= config.ws_retry {
            last_attempt = Instant::now();
            ws = connect_ws(&config.ws_url);
            if let Some(ref mut socket) = ws {
                // Set non-blocking for command reads
                if let tungstenite::stream::MaybeTlsStream::Plain(ref s) = socket.get_ref() {
                    let _ = s.set_nonblocking(true);
                }
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

    // Check if this is a command (has "type": "command" field)
    let msg_type = value.get("type").and_then(|v| v.as_str()).unwrap_or("");
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
