use chrono::Utc;
use crossbeam_channel::{unbounded, Receiver, Sender};
use serde::Serialize;
use std::cell::RefCell;
use std::env;
use std::mem::size_of;
use std::sync::{Mutex, OnceLock};
use std::thread;
use std::time::{Duration, Instant};
use tungstenite::{connect, Message};
use url::Url;
use windows::core::BSTR;
use windows::core::PWSTR;
use windows::Win32::Foundation::{CloseHandle, HWND};
use windows::Win32::System::Com::{
    CoCreateInstance, CoInitializeEx, COINIT_APARTMENTTHREADED, CLSCTX_INPROC_SERVER,
};
use windows::Win32::System::SystemInformation::GetTickCount;
use windows::Win32::System::Threading::{
    OpenProcess, QueryFullProcessImageNameW, PROCESS_NAME_FORMAT, PROCESS_QUERY_LIMITED_INFORMATION,
};
use windows::Win32::UI::Accessibility::{
    SetWinEventHook, CUIAutomation, HWINEVENTHOOK, IUIAutomation, IUIAutomationElement,
    IUIAutomationTextPattern, UIA_TextPatternId,
};
use windows::Win32::UI::Input::KeyboardAndMouse::{GetLastInputInfo, LASTINPUTINFO};
use windows::Win32::UI::WindowsAndMessaging::{
    DispatchMessageW, GetMessageW, GetWindowTextLengthW, GetWindowTextW,
    GetWindowThreadProcessId, TranslateMessage, EVENT_SYSTEM_FOREGROUND, MSG, OBJID_WINDOW,
    WINEVENT_OUTOFCONTEXT, WINEVENT_SKIPOWNPROCESS,
};

static EVENT_SENDER: OnceLock<Sender<WindowEvent>> = OnceLock::new();
static CONFIG: OnceLock<Config> = OnceLock::new();
static UIA_LAST_SNAPSHOT: OnceLock<Mutex<Instant>> = OnceLock::new();

thread_local! {
    static UIA_AUTOMATION: RefCell<Option<IUIAutomation>> = RefCell::new(None);
}

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
    #[serde(skip_serializing_if = "Option::is_none")]
    idle_ms: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    uia: Option<UiaSnapshot>,
}

#[derive(Debug, Serialize, Clone)]
struct UiaSnapshot {
    focused_name: String,
    control_type: String,
    document_text: String,
}

#[derive(Clone)]
struct Config {
    ws_url: String,
    http_url: String,
    ws_retry: Duration,
    idle_enabled: bool,
    idle_threshold: Duration,
    idle_poll: Duration,
    uia_enabled: bool,
    uia_throttle: Duration,
    uia_text_max: usize,
}

impl Config {
    fn from_env() -> Self {
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
        }
    }
}

fn env_bool(name: &str, default: bool) -> bool {
    let raw = env::var(name).ok();
    match raw.as_deref().map(|v| v.trim().to_lowercase()) {
        Some(v) if v == "1" || v == "true" || v == "yes" || v == "on" => true,
        Some(v) if v == "0" || v == "false" || v == "no" || v == "off" => false,
        _ => default,
    }
}

fn env_u64(name: &str, default: u64) -> u64 {
    env::var(name)
        .ok()
        .and_then(|v| v.parse::<u64>().ok())
        .unwrap_or(default)
}

fn env_usize(name: &str, default: usize) -> usize {
    env::var(name)
        .ok()
        .and_then(|v| v.parse::<usize>().ok())
        .unwrap_or(default)
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
    let uia = CONFIG
        .get()
        .and_then(|config| uia_snapshot(hwnd, config));
    Some(WindowEvent {
        event_type: "foreground".to_string(),
        hwnd: hwnd_to_hex(hwnd),
        title,
        process_exe,
        pid,
        timestamp: Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Millis, true),
        source: "collector".to_string(),
        idle_ms: None,
        uia,
    })
}

fn build_activity_event(event_type: &str, idle_ms: u64) -> WindowEvent {
    WindowEvent {
        event_type: event_type.to_string(),
        hwnd: "0x0".to_string(),
        title: String::new(),
        process_exe: String::new(),
        pid: 0,
        timestamp: Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Millis, true),
        source: "collector".to_string(),
        idle_ms: Some(idle_ms),
        uia: None,
    }
}

fn idle_duration_ms() -> Option<u64> {
    unsafe {
        let mut info = LASTINPUTINFO {
            cbSize: size_of::<LASTINPUTINFO>() as u32,
            dwTime: 0,
        };
        if !GetLastInputInfo(&mut info).as_bool() {
            return None;
        }
        let now = GetTickCount();
        let diff = now.wrapping_sub(info.dwTime);
        Some(diff as u64)
    }
}

fn allow_uia_snapshot(throttle: Duration) -> bool {
    let lock = UIA_LAST_SNAPSHOT.get_or_init(|| Mutex::new(Instant::now() - throttle));
    let mut last = lock.lock().unwrap();
    if last.elapsed() < throttle {
        return false;
    }
    *last = Instant::now();
    true
}

fn bstr_to_string(value: BSTR) -> String {
    String::from_utf16_lossy(value.as_wide())
}

fn get_uia() -> Option<IUIAutomation> {
    UIA_AUTOMATION.with(|cell| {
        if cell.borrow().is_none() {
            unsafe {
                let _ = CoInitializeEx(None, COINIT_APARTMENTTHREADED);
            }
            let automation =
                unsafe { CoCreateInstance(&CUIAutomation, None, CLSCTX_INPROC_SERVER).ok()? };
            *cell.borrow_mut() = Some(automation);
        }
        cell.borrow().clone()
    })
}

fn extract_document_text(element: &IUIAutomationElement, max_len: usize) -> Option<String> {
    let pattern: IUIAutomationTextPattern =
        unsafe { element.GetCurrentPatternAs(UIA_TextPatternId).ok()? };
    let range = unsafe { pattern.DocumentRange().ok()? };
    let raw = unsafe { range.GetText(max_len as i32).ok()? };
    let mut text = bstr_to_string(raw);
    text = text.replace('\r', " ").replace('\n', " ");
    let text = text.split_whitespace().collect::<Vec<_>>().join(" ");
    let trimmed = text.trim();
    if trimmed.is_empty() {
        return None;
    }
    let mut output = trimmed.to_string();
    if output.len() > max_len {
        output.truncate(max_len);
    }
    Some(output)
}

fn uia_snapshot(hwnd: HWND, config: &Config) -> Option<UiaSnapshot> {
    if !config.uia_enabled {
        return None;
    }
    if !allow_uia_snapshot(config.uia_throttle) {
        return None;
    }
    let automation = get_uia()?;
    let focused = unsafe { automation.GetFocusedElement().ok() };
    let element = focused
        .clone()
        .or_else(|| unsafe { automation.ElementFromHandle(hwnd).ok() })?;
    let focused_name = unsafe {
        element
            .CurrentName()
            .ok()
            .map(bstr_to_string)
            .unwrap_or_default()
    };
    let control_type = unsafe {
        element
            .CurrentLocalizedControlType()
            .ok()
            .map(bstr_to_string)
            .unwrap_or_default()
    };
    let mut document_text = extract_document_text(&element, config.uia_text_max).unwrap_or_default();
    if document_text.is_empty() {
        if let Ok(handle_element) = unsafe { automation.ElementFromHandle(hwnd) } {
            document_text = extract_document_text(&handle_element, config.uia_text_max).unwrap_or_default();
        }
    }
    let snapshot = UiaSnapshot {
        focused_name,
        control_type,
        document_text,
    };
    if snapshot.focused_name.is_empty()
        && snapshot.control_type.is_empty()
        && snapshot.document_text.is_empty()
    {
        None
    } else {
        Some(snapshot)
    }
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

fn idle_worker(tx: Sender<WindowEvent>, config: Config) {
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

fn main() {
    env_logger::init();
    let config = Config::from_env();
    let _ = CONFIG.set(config.clone());

    let (tx, rx) = unbounded();
    if EVENT_SENDER.set(tx).is_err() {
        log::error!("Failed to set event sender");
        return;
    }

    if config.idle_enabled {
        let idle_tx = EVENT_SENDER.get().unwrap().clone();
        let idle_config = config.clone();
        thread::spawn(move || idle_worker(idle_tx, idle_config));
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
