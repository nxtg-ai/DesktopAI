pub mod config;
pub mod event;
pub mod network;
pub mod idle;

#[cfg(windows)]
pub mod uia;
#[cfg(windows)]
pub mod windows;
#[cfg(windows)]
pub mod screenshot;

pub mod command;

// Re-export public types for testability and external use
pub use config::{Config, env_bool, env_u64, env_usize, env_u32, env_u8};
pub use event::{WindowEvent, UiaSnapshot, UiaElement, build_activity_event};
pub use network::{connect_ws, send_http, network_worker};
pub use idle::idle_worker;

#[cfg(windows)]
pub use event::{hwnd_to_hex, bstr_to_string};
#[cfg(windows)]
pub use uia::{allow_uia_snapshot, get_uia, extract_document_text, uia_snapshot};
#[cfg(windows)]
pub use windows::{window_title, process_path, build_event, win_event_hook, idle_duration_ms};
#[cfg(windows)]
pub use screenshot::{capture_screenshot, init_screenshot_buffer};

#[cfg(windows)]
use crossbeam_channel::unbounded;
#[cfg(windows)]
use std::thread;

#[cfg(windows)]
use ::windows::Win32::Foundation::HWND;
#[cfg(windows)]
use ::windows::Win32::UI::Accessibility::SetWinEventHook;
#[cfg(windows)]
use ::windows::Win32::UI::WindowsAndMessaging::{
    DispatchMessageW, GetMessageW, TranslateMessage, EVENT_SYSTEM_FOREGROUND, MSG,
    WINEVENT_OUTOFCONTEXT, WINEVENT_SKIPOWNPROCESS,
};

/// Main entry point for the collector library
#[cfg(windows)]
pub fn run() {
    env_logger::init();
    let config = Config::from_env();

    // Initialize screenshot buffer if enabled
    if config.enable_screenshot {
        init_screenshot_buffer();
    }

    // Initialize global config
    if crate::windows::CONFIG.set(config.clone()).is_err() {
        log::error!("Failed to set global config");
        return;
    }

    let (tx, rx) = unbounded();
    if crate::windows::EVENT_SENDER.set(tx).is_err() {
        log::error!("Failed to set event sender");
        return;
    }

    if config.idle_enabled {
        let idle_tx = crate::windows::EVENT_SENDER.get().unwrap().clone();
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

#[cfg(not(windows))]
pub fn run() {
    eprintln!("This collector is Windows-only");
}
