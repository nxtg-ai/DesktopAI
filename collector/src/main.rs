use chrono::Utc;
use crossbeam_channel::{unbounded, Receiver, Sender};
use serde::Serialize;
use std::env;
use std::sync::OnceLock;
use std::thread;
use std::time::{Duration, Instant};
use tungstenite::{connect, Message};
use url::Url;
use windows::core::PWSTR;
use windows::Win32::Foundation::{CloseHandle, HWND};
use windows::Win32::System::Threading::{
    OpenProcess, QueryFullProcessImageNameW, PROCESS_NAME_FORMAT, PROCESS_QUERY_LIMITED_INFORMATION,
};
use windows::Win32::UI::Accessibility::{SetWinEventHook, HWINEVENTHOOK};
use windows::Win32::UI::WindowsAndMessaging::{
    DispatchMessageW, GetMessageW, GetWindowTextLengthW, GetWindowTextW,
    GetWindowThreadProcessId, TranslateMessage, EVENT_SYSTEM_FOREGROUND, MSG, OBJID_WINDOW,
    WINEVENT_OUTOFCONTEXT, WINEVENT_SKIPOWNPROCESS,
};

static EVENT_SENDER: OnceLock<Sender<WindowEvent>> = OnceLock::new();

#[derive(Debug, Serialize, Clone)]
struct WindowEvent {
    #[serde(rename = "type")]
    event_type: String,
    hwnd: String,
    title: String,
    process_exe: String,
    pid: u32,
    timestamp: String,
    source: String,
}

#[derive(Clone)]
struct Config {
    ws_url: String,
    http_url: String,
    ws_retry: Duration,
}

impl Config {
    fn from_env() -> Self {
        let ws_url = env::var("BACKEND_WS_URL").unwrap_or_else(|_| "ws://localhost:8000/ingest".into());
        let http_url =
            env::var("BACKEND_HTTP_URL").unwrap_or_else(|_| "http://localhost:8000/api/events".into());
        let retry = env::var("WS_RETRY_SECONDS")
            .ok()
            .and_then(|v| v.parse::<u64>().ok())
            .unwrap_or(5);
        Self {
            ws_url,
            http_url,
            ws_retry: Duration::from_secs(retry),
        }
    }
}

fn hwnd_to_hex(hwnd: HWND) -> String {
    format!("{:#x}", hwnd.0 as usize)
}

fn window_title(hwnd: HWND) -> String {
    unsafe {
        let len = GetWindowTextLengthW(hwnd);
        if len == 0 {
            return String::new();
        }
        let mut buffer = vec![0u16; (len + 1) as usize];
        let copied = GetWindowTextW(hwnd, buffer.as_mut_slice());
        if copied == 0 {
            return String::new();
        }
        String::from_utf16_lossy(&buffer[..copied as usize])
    }
}

fn process_path(pid: u32) -> String {
    unsafe {
        let handle = match OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, false, pid) {
            Ok(h) => h,
            Err(_) => return String::new(),
        };
        if handle.is_invalid() {
            return String::new();
        }

        let mut buffer = vec![0u16; 260];
        let mut size: u32 = buffer.len() as u32;
        let ok = QueryFullProcessImageNameW(
            handle,
            PROCESS_NAME_FORMAT(0),
            PWSTR(buffer.as_mut_ptr()),
            &mut size as *mut u32,
        )
        .is_ok();
        let _ = CloseHandle(handle);

        if !ok || size == 0 {
            return String::new();
        }
        String::from_utf16_lossy(&buffer[..size as usize])
    }
}

fn build_event(hwnd: HWND) -> Option<WindowEvent> {
    if hwnd.0 == 0 {
        return None;
    }
    let title = window_title(hwnd);
    let mut pid: u32 = 0;
    unsafe {
        let _ = GetWindowThreadProcessId(hwnd, Some(&mut pid));
    }
    let process_exe = if pid == 0 { String::new() } else { process_path(pid) };
    Some(WindowEvent {
        event_type: "foreground".to_string(),
        hwnd: hwnd_to_hex(hwnd),
        title,
        process_exe,
        pid,
        timestamp: Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Millis, true),
        source: "collector".to_string(),
    })
}

unsafe extern "system" fn win_event_hook(
    _hook: HWINEVENTHOOK,
    event: u32,
    hwnd: HWND,
    id_object: i32,
    _id_child: i32,
    _event_thread: u32,
    _event_time: u32,
) {
    if event != EVENT_SYSTEM_FOREGROUND {
        return;
    }
    if id_object != OBJID_WINDOW.0 {
        return;
    }
    let Some(event) = build_event(hwnd) else {
        return;
    };
    if let Some(sender) = EVENT_SENDER.get() {
        let _ = sender.send(event);
    }
}

fn connect_ws(url: &str) -> Option<tungstenite::WebSocket<tungstenite::stream::MaybeTlsStream<std::net::TcpStream>>> {
    let parsed = Url::parse(url).ok()?;
    match connect(parsed) {
        Ok((socket, _)) => Some(socket),
        Err(err) => {
            log::warn!("WebSocket connect failed: {err}");
            None
        }
    }
}

fn send_http(url: &str, event: &WindowEvent) {
    let resp = ureq::post(url).send_json(event);
    if let Err(err) = resp {
        log::warn!("HTTP send failed: {err}");
    }
}

fn network_worker(rx: Receiver<WindowEvent>, config: Config) {
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

fn main() {
    env_logger::init();
    let config = Config::from_env();

    let (tx, rx) = unbounded();
    if EVENT_SENDER.set(tx).is_err() {
        log::error!("Failed to set event sender");
        return;
    }

    thread::spawn(move || network_worker(rx, config));

    unsafe {
        let hook = SetWinEventHook(
            EVENT_SYSTEM_FOREGROUND,
            EVENT_SYSTEM_FOREGROUND,
            None,
            Some(win_event_hook),
            0,
            0,
            WINEVENT_OUTOFCONTEXT | WINEVENT_SKIPOWNPROCESS,
        );
        if hook.0 == 0 {
            log::error!("Failed to install WinEvent hook");
            return;
        }
    }

    unsafe {
        let mut msg = MSG::default();
        while GetMessageW(&mut msg, HWND(0), 0, 0).as_bool() {
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
    }
}
