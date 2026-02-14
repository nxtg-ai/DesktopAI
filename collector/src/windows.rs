use chrono::Utc;
use crossbeam_channel::Sender;
use std::mem::size_of;
use std::sync::OnceLock;
use windows::core::PWSTR;
use windows::Win32::Foundation::{CloseHandle, HWND};
use windows::Win32::System::SystemInformation::GetTickCount;
use windows::Win32::System::Threading::{
    OpenProcess, QueryFullProcessImageNameW, PROCESS_NAME_FORMAT, PROCESS_QUERY_LIMITED_INFORMATION,
};
use windows::Win32::UI::Accessibility::{HWINEVENTHOOK};
use windows::Win32::UI::Input::KeyboardAndMouse::{GetLastInputInfo, LASTINPUTINFO};
use windows::Win32::UI::WindowsAndMessaging::{
    GetWindowTextLengthW, GetWindowTextW, GetWindowThreadProcessId, EVENT_SYSTEM_FOREGROUND,
    OBJID_WINDOW,
};

use crate::config::Config;
use crate::event::{hwnd_to_hex, WindowEvent};
use crate::uia::uia_snapshot;
use crate::screenshot::capture_screenshot;

pub static EVENT_SENDER: OnceLock<Sender<WindowEvent>> = OnceLock::new();
pub static CONFIG: OnceLock<Config> = OnceLock::new();

pub fn window_title(hwnd: HWND) -> String {
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

pub fn process_path(pid: u32) -> String {
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

pub fn build_event(hwnd: HWND) -> Option<WindowEvent> {
    if hwnd.0 == 0 {
        return None;
    }
    let title = window_title(hwnd);
    let mut pid: u32 = 0;
    unsafe {
        let _ = GetWindowThreadProcessId(hwnd, Some(&mut pid));
    }
    let process_exe = if pid == 0 { String::new() } else { process_path(pid) };
    let config = CONFIG.get();
    let uia = config.and_then(|cfg| uia_snapshot(hwnd, cfg));
    let screenshot_b64 = config.and_then(|cfg| capture_screenshot(cfg, hwnd));
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
        screenshot_b64,
    })
}

pub fn idle_duration_ms() -> Option<u64> {
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

pub unsafe extern "system" fn win_event_hook(
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
