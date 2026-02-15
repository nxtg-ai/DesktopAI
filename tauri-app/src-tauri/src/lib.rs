use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    Manager,
};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};

#[cfg(target_os = "windows")]
mod win_focus {
    use raw_window_handle::{HasWindowHandle, RawWindowHandle};
    use windows::Win32::Foundation::HWND;
    use windows::Win32::UI::WindowsAndMessaging::{
        GetForegroundWindow, GetWindowLongPtrW, SetForegroundWindow, SetWindowLongPtrW,
        GWL_EXSTYLE, WS_EX_NOACTIVATE, WS_EX_TOOLWINDOW,
    };

    static SAVED_HWND: std::sync::Mutex<Option<isize>> = std::sync::Mutex::new(None);

    /// Save the current foreground window before showing the palette.
    pub fn save_foreground() {
        let hwnd = unsafe { GetForegroundWindow() };
        if let Ok(mut saved) = SAVED_HWND.lock() {
            *saved = Some(hwnd.0 as isize);
        }
    }

    /// Restore focus to the previously saved foreground window.
    /// Called while our process is still foreground (palette is focused),
    /// so SetForegroundWindow succeeds directly — no ALT trick needed.
    pub fn restore_foreground() {
        let hwnd_val = SAVED_HWND.lock().ok().and_then(|g| *g);
        let Some(val) = hwnd_val else { return };
        let hwnd = HWND(val as *mut _);
        if hwnd.0.is_null() {
            return;
        }
        unsafe {
            let _ = SetForegroundWindow(hwnd);
        }
    }

    /// Apply WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW to a Tauri window.
    /// Prevents focus stealing and hides from taskbar/Alt+Tab.
    pub fn apply_noactivate(window: &tauri::WebviewWindow) {
        if let Ok(handle) = window.window_handle() {
            if let RawWindowHandle::Win32(win32) = handle.as_raw() {
                let hwnd = HWND(win32.hwnd.get() as *mut _);
                unsafe {
                    let style = GetWindowLongPtrW(hwnd, GWL_EXSTYLE);
                    SetWindowLongPtrW(
                        hwnd,
                        GWL_EXSTYLE,
                        style | WS_EX_NOACTIVATE.0 as isize | WS_EX_TOOLWINDOW.0 as isize,
                    );
                }
            }
        }
    }
}

#[tauri::command]
fn toggle_visibility(window: tauri::Window) {
    if window.is_visible().unwrap_or(false) {
        let _ = window.hide();
    } else {
        let _ = window.show();
        let _ = window.set_focus();
    }
}

#[tauri::command]
fn set_compact_mode(window: tauri::Window, compact: bool) {
    if compact {
        let _ = window.set_size(tauri::LogicalSize::new(380.0, 140.0));
    } else {
        let _ = window.set_size(tauri::LogicalSize::new(380.0, 520.0));
    }
}

/// Toggle the command palette: save foreground, show, or hide + restore focus.
fn toggle_palette(app: &tauri::AppHandle) {
    let Some(palette) = app.get_webview_window("palette") else {
        return;
    };

    if palette.is_visible().unwrap_or(false) {
        let _ = palette.hide();
        #[cfg(target_os = "windows")]
        win_focus::restore_foreground();
    } else {
        #[cfg(target_os = "windows")]
        win_focus::save_foreground();
        let _ = palette.center();
        let _ = palette.show();
        let _ = palette.set_focus();
    }
}

/// Dismiss the palette and restore focus (called from JS via Escape or after command).
#[tauri::command]
fn dismiss_palette(app: tauri::AppHandle) {
    if let Some(palette) = app.get_webview_window("palette") {
        let _ = palette.hide();
    }
    #[cfg(target_os = "windows")]
    win_focus::restore_foreground();
}

/// Kill all running actions by POSTing to the backend.
#[tauri::command]
async fn kill_all_actions() -> Result<String, String> {
    let client = reqwest::Client::new();
    match client
        .post("http://localhost:8000/api/autonomy/cancel-all")
        .send()
        .await
    {
        Ok(resp) => {
            let text = resp.text().await.unwrap_or_default();
            Ok(text)
        }
        Err(e) => Err(format!("Kill request failed: {e}")),
    }
}

pub fn run() {
    let ctrl_space = Shortcut::new(Some(Modifiers::CONTROL), Code::Space);
    let ctrl_shift_x = Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT), Code::KeyX);

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(move |app, shortcut, event| {
                    if event.state != ShortcutState::Pressed {
                        return;
                    }
                    if *shortcut == ctrl_space {
                        toggle_palette(app);
                    } else if *shortcut == ctrl_shift_x {
                        let handle = app.clone();
                        tauri::async_runtime::spawn(async move {
                            let _ = kill_all_actions_internal(&handle).await;
                        });
                    }
                })
                .build(),
        )
        .setup(move |app| {
            // Register global shortcuts (unregister first to handle stale registrations)
            let gs = app.global_shortcut();
            let _ = gs.unregister(ctrl_space);
            let _ = gs.unregister(ctrl_shift_x);
            if let Err(e) = gs.register(ctrl_space) {
                log::warn!("Failed to register Ctrl+Space: {e}");
            }
            if let Err(e) = gs.register(ctrl_shift_x) {
                log::warn!("Failed to register Ctrl+Shift+X: {e}");
            }

            // Apply WS_EX_NOACTIVATE to avatar overlay — never steals focus
            #[cfg(target_os = "windows")]
            if let Some(avatar) = app.get_webview_window("avatar") {
                win_focus::apply_noactivate(&avatar);
            }

            // System tray
            let show = MenuItem::with_id(app, "show", "Show DesktopAI", true, None::<&str>)?;
            let hide = MenuItem::with_id(app, "hide", "Hide", true, None::<&str>)?;
            let palette_item = MenuItem::with_id(
                app,
                "palette",
                "Command Palette (Ctrl+Space)",
                true,
                None::<&str>,
            )?;
            let dashboard =
                MenuItem::with_id(app, "dashboard", "Open Dashboard", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &hide, &palette_item, &dashboard, &quit])?;

            TrayIconBuilder::new()
                .menu(&menu)
                .tooltip("DesktopAI")
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "show" => {
                        if let Some(window) = app.get_webview_window("avatar") {
                            let _ = window.show();
                            let _ = window.set_focus();
                        }
                    }
                    "hide" => {
                        if let Some(window) = app.get_webview_window("avatar") {
                            let _ = window.hide();
                        }
                    }
                    "palette" => toggle_palette(app),
                    "dashboard" => {
                        let _ = tauri_plugin_opener::OpenerExt::opener(app)
                            .open_url("http://localhost:8000", None::<&str>);
                    }
                    "quit" => app.exit(0),
                    _ => {}
                })
                .build(app)?;

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            toggle_visibility,
            set_compact_mode,
            dismiss_palette,
            kill_all_actions,
        ])
        .run(tauri::generate_context!())
        .expect("error while running DesktopAI");
}

async fn kill_all_actions_internal(_app: &tauri::AppHandle) -> Result<(), String> {
    let client = reqwest::Client::new();
    client
        .post("http://localhost:8000/api/autonomy/cancel-all")
        .send()
        .await
        .map_err(|e| format!("{e}"))?;
    Ok(())
}
