//! Command bridge: receives desktop automation commands from the backend and executes them.
//! Supports: observe, click, type_text, send_keys, open_application, focus_window,
//! scroll, double_click, right_click. Uses UIA (UI Automation) for element resolution
//! and SendInput for mouse/keyboard actions on Windows.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

use crate::config::Config;

/// A command received from the backend for desktop automation.
#[derive(Debug, Deserialize, Clone)]
pub struct Command {
    pub command_id: String,
    pub action: String,
    #[serde(default)]
    pub parameters: HashMap<String, serde_json::Value>,
    #[serde(default = "default_timeout_ms")]
    pub timeout_ms: u64,
}

fn default_timeout_ms() -> u64 {
    5000
}

/// Result of executing a command, sent back to the backend. Optionally includes
/// a post-action screenshot and UIA snapshot for the agent's verification loop.
#[derive(Debug, Serialize, Clone)]
pub struct CommandResult {
    #[serde(rename = "type")]
    pub msg_type: String,
    pub command_id: String,
    pub ok: bool,
    pub result: HashMap<String, serde_json::Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub screenshot_b64: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub uia: Option<serde_json::Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

impl CommandResult {
    pub fn success(command_id: &str, result: HashMap<String, serde_json::Value>) -> Self {
        Self {
            msg_type: "command_result".to_string(),
            command_id: command_id.to_string(),
            ok: true,
            result,
            screenshot_b64: None,
            uia: None,
            error: None,
        }
    }

    pub fn failure(command_id: &str, error: &str) -> Self {
        Self {
            msg_type: "command_result".to_string(),
            command_id: command_id.to_string(),
            ok: false,
            result: HashMap::new(),
            screenshot_b64: None,
            uia: None,
            error: Some(error.to_string()),
        }
    }
}

/// Dispatch a command to the appropriate handler.
/// On non-Windows, only returns errors (the real handlers use Win32 APIs).
pub fn execute_command(cmd: &Command, _config: &Config) -> CommandResult {
    match cmd.action.as_str() {
        "observe" => handle_observe(cmd, _config),
        "click" => handle_click(cmd, _config),
        "type_text" => handle_type_text(cmd, _config),
        "send_keys" => handle_send_keys(cmd, _config),
        "open_application" => handle_open_application(cmd, _config),
        "focus_window" => handle_focus_window(cmd, _config),
        "scroll" => handle_scroll(cmd, _config),
        "double_click" => handle_double_click(cmd, _config),
        "right_click" => handle_right_click(cmd, _config),
        _ => CommandResult::failure(&cmd.command_id, &format!("unknown action: {}", cmd.action)),
    }
}

// --- Platform-gated action handlers ---

#[cfg(windows)]
fn handle_observe(cmd: &Command, config: &Config) -> CommandResult {
    let mut result = HashMap::new();
    result.insert("action".to_string(), serde_json::Value::String("observe".to_string()));

    // Capture screenshot if enabled
    let screenshot_b64 = if config.enable_screenshot {
        match crate::screenshot::capture_screenshot(config, windows::Win32::Foundation::HWND(0)) {
            Some(b64) => Some(b64),
            None => {
                log::warn!("Screenshot capture failed during observe");
                None
            }
        }
    } else {
        None
    };

    // Get foreground window info
    use crate::windows::{window_title, process_path};
    use windows::Win32::UI::WindowsAndMessaging::GetForegroundWindow;
    use windows::Win32::UI::WindowsAndMessaging::GetWindowThreadProcessId;

    let hwnd = unsafe { GetForegroundWindow() };
    let title = window_title(hwnd);
    let mut pid: u32 = 0;
    unsafe { GetWindowThreadProcessId(hwnd, Some(&mut pid)); }
    let process = process_path(pid);

    // Capture UIA snapshot if enabled
    let uia = if config.uia_enabled {
        use crate::uia::uia_snapshot;
        match uia_snapshot(hwnd, config) {
            Some(snapshot) => serde_json::to_value(&snapshot).ok(),
            None => None,
        }
    } else {
        None
    };

    result.insert("window_title".to_string(), serde_json::Value::String(title));
    result.insert("process_exe".to_string(), serde_json::Value::String(process));

    let mut cmd_result = CommandResult::success(&cmd.command_id, result);
    cmd_result.screenshot_b64 = screenshot_b64;
    cmd_result.uia = uia;
    cmd_result
}

#[cfg(not(windows))]
fn handle_observe(cmd: &Command, _config: &Config) -> CommandResult {
    CommandResult::failure(&cmd.command_id, "observe requires Windows")
}

#[cfg(windows)]
fn bstr_to_variant(s: &str) -> windows::Win32::System::Variant::VARIANT {
    use windows::Win32::System::Variant::*;
    let bstr = windows::core::BSTR::from(s);
    unsafe {
        let mut var: VARIANT = std::mem::zeroed();
        let inner = &mut *var.Anonymous.Anonymous;
        inner.vt = VT_BSTR;
        inner.Anonymous.bstrVal = std::mem::ManuallyDrop::new(bstr);
        var
    }
}

#[cfg(windows)]
fn handle_click(cmd: &Command, config: &Config) -> CommandResult {
    use windows::Win32::UI::Accessibility::*;
    use windows::Win32::System::Com::{CoInitializeEx, COINIT_APARTMENTTHREADED};

    let name = cmd.parameters.get("name").and_then(|v| v.as_str()).unwrap_or("");
    let automation_id = cmd.parameters.get("automation_id").and_then(|v| v.as_str()).unwrap_or("");

    // If no UIA identifier provided, fall back to x/y pixel coordinates
    if name.is_empty() && automation_id.is_empty() {
        let x = cmd.parameters.get("x").and_then(|v| v.as_i64()).unwrap_or(-1) as i32;
        let y = cmd.parameters.get("y").and_then(|v| v.as_i64()).unwrap_or(-1) as i32;
        if x < 0 || y < 0 {
            return CommandResult::failure(&cmd.command_id, "click requires 'name', 'automation_id', or 'x'/'y' parameters");
        }
        click_at(x, y);
        let mut result = HashMap::new();
        result.insert("x".to_string(), serde_json::json!(x));
        result.insert("y".to_string(), serde_json::json!(y));
        result.insert("method".to_string(), serde_json::Value::String("coordinate".to_string()));
        let mut cmd_result = CommandResult::success(&cmd.command_id, result);
        cmd_result.screenshot_b64 = if config.enable_screenshot {
            crate::screenshot::capture_screenshot(config, windows::Win32::Foundation::HWND(0))
        } else {
            None
        };
        return cmd_result;
    }

    // Try UIA Invoke first
    unsafe {
        let _ = CoInitializeEx(None, COINIT_APARTMENTTHREADED);
    }

    let uia: windows::Win32::UI::Accessibility::IUIAutomation = unsafe {
        match windows::Win32::System::Com::CoCreateInstance(
            &CUIAutomation,
            None,
            windows::Win32::System::Com::CLSCTX_INPROC_SERVER,
        ) {
            Ok(u) => u,
            Err(e) => return CommandResult::failure(&cmd.command_id, &format!("UIA init failed: {e}")),
        }
    };

    let root = unsafe {
        match uia.GetRootElement() {
            Ok(r) => r,
            Err(e) => return CommandResult::failure(&cmd.command_id, &format!("GetRootElement failed: {e}")),
        }
    };

    // Build condition: prefer automation_id, fallback to name
    let condition = if !automation_id.is_empty() {
        let prop = UIA_AutomationIdPropertyId;
        let val = bstr_to_variant(automation_id);
        unsafe { uia.CreatePropertyCondition(prop, val) }
    } else {
        let prop = UIA_NamePropertyId;
        let val = bstr_to_variant(name);
        unsafe { uia.CreatePropertyCondition(prop, val) }
    };

    let condition = match condition {
        Ok(c) => c,
        Err(e) => return CommandResult::failure(&cmd.command_id, &format!("CreatePropertyCondition failed: {e}")),
    };

    let element = unsafe {
        match root.FindFirst(TreeScope_Descendants, &condition) {
            Ok(e) => e,
            Err(e) => return CommandResult::failure(&cmd.command_id, &format!("element not found: {e}")),
        }
    };

    // Try InvokePattern
    let invoke_result: Result<IUIAutomationInvokePattern, _> = unsafe {
        element.GetCurrentPatternAs(UIA_InvokePatternId)
    };

    if let Ok(invoke) = invoke_result {
        if let Err(e) = unsafe { invoke.Invoke() } {
            return CommandResult::failure(&cmd.command_id, &format!("Invoke failed: {e}"));
        }
        let mut result = HashMap::new();
        let clicked_name = if !name.is_empty() { name } else { automation_id };
        result.insert("clicked".to_string(), serde_json::Value::String(clicked_name.to_string()));
        result.insert("method".to_string(), serde_json::Value::String("invoke".to_string()));

        let mut cmd_result = CommandResult::success(&cmd.command_id, result);
        // Capture post-action state
        cmd_result.screenshot_b64 = if config.enable_screenshot {
            crate::screenshot::capture_screenshot(config, windows::Win32::Foundation::HWND(0))
        } else {
            None
        };
        return cmd_result;
    }

    // Fallback: click at bounding rect center via SendInput
    let rect = unsafe { element.CurrentBoundingRectangle() };
    match rect {
        Ok(r) => {
            let center_x = (r.left + r.right) / 2;
            let center_y = (r.top + r.bottom) / 2;
            click_at(center_x, center_y);
            let mut result = HashMap::new();
            let clicked_name = if !name.is_empty() { name } else { automation_id };
            result.insert("clicked".to_string(), serde_json::Value::String(clicked_name.to_string()));
            result.insert("method".to_string(), serde_json::Value::String("coordinate".to_string()));
            result.insert("x".to_string(), serde_json::json!(center_x));
            result.insert("y".to_string(), serde_json::json!(center_y));

            let mut cmd_result = CommandResult::success(&cmd.command_id, result);
            cmd_result.screenshot_b64 = if config.enable_screenshot {
                crate::screenshot::capture_screenshot(config, windows::Win32::Foundation::HWND(0))
            } else {
                None
            };
            cmd_result
        }
        Err(e) => CommandResult::failure(&cmd.command_id, &format!("bounding rect failed: {e}")),
    }
}

#[cfg(windows)]
fn click_at(x: i32, y: i32) {
    use windows::Win32::UI::Input::KeyboardAndMouse::*;

    let screen_w = unsafe { windows::Win32::UI::WindowsAndMessaging::GetSystemMetrics(windows::Win32::UI::WindowsAndMessaging::SM_CXSCREEN) };
    let screen_h = unsafe { windows::Win32::UI::WindowsAndMessaging::GetSystemMetrics(windows::Win32::UI::WindowsAndMessaging::SM_CYSCREEN) };

    let norm_x = (x as i64 * 65535 / screen_w as i64) as i32;
    let norm_y = (y as i64 * 65535 / screen_h as i64) as i32;

    let inputs = [
        INPUT {
            r#type: INPUT_MOUSE,
            Anonymous: INPUT_0 {
                mi: MOUSEINPUT {
                    dx: norm_x,
                    dy: norm_y,
                    mouseData: 0,
                    dwFlags: MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_MOVE | MOUSEEVENTF_LEFTDOWN,
                    time: 0,
                    dwExtraInfo: 0,
                },
            },
        },
        INPUT {
            r#type: INPUT_MOUSE,
            Anonymous: INPUT_0 {
                mi: MOUSEINPUT {
                    dx: norm_x,
                    dy: norm_y,
                    mouseData: 0,
                    dwFlags: MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_MOVE | MOUSEEVENTF_LEFTUP,
                    time: 0,
                    dwExtraInfo: 0,
                },
            },
        },
    ];

    unsafe {
        SendInput(&inputs, std::mem::size_of::<INPUT>() as i32);
    }
}

#[cfg(not(windows))]
fn handle_click(cmd: &Command, _config: &Config) -> CommandResult {
    let name = cmd.parameters.get("name").and_then(|v| v.as_str()).unwrap_or("");
    let automation_id = cmd.parameters.get("automation_id").and_then(|v| v.as_str()).unwrap_or("");
    if name.is_empty() && automation_id.is_empty() {
        let x = cmd.parameters.get("x").and_then(|v| v.as_i64()).unwrap_or(-1);
        let y = cmd.parameters.get("y").and_then(|v| v.as_i64()).unwrap_or(-1);
        if x < 0 || y < 0 {
            return CommandResult::failure(&cmd.command_id, "click requires 'name', 'automation_id', or 'x'/'y' parameters");
        }
    }
    CommandResult::failure(&cmd.command_id, "click requires Windows")
}

#[cfg(windows)]
fn handle_type_text(cmd: &Command, config: &Config) -> CommandResult {
    let text = cmd.parameters.get("text").and_then(|v| v.as_str()).unwrap_or("");
    if text.is_empty() {
        return CommandResult::failure(&cmd.command_id, "type_text requires 'text' parameter");
    }

    // Try to find target element and use ValuePattern
    let target = cmd.parameters.get("automation_id").and_then(|v| v.as_str());

    if let Some(target_id) = target {
        if !target_id.is_empty() {
            if let Some(_typed) = try_set_value(target_id, text) {
                let mut result = HashMap::new();
                result.insert("typed".to_string(), serde_json::Value::String(text.to_string()));
                result.insert("method".to_string(), serde_json::Value::String("value_pattern".to_string()));
                result.insert("target".to_string(), serde_json::Value::String(target_id.to_string()));
                let mut cmd_result = CommandResult::success(&cmd.command_id, result);
                cmd_result.screenshot_b64 = if config.enable_screenshot {
                    crate::screenshot::capture_screenshot(config, windows::Win32::Foundation::HWND(0))
                } else {
                    None
                };
                return cmd_result;
            }
        }
    }

    // Fallback: SendInput key-by-key
    send_text_via_input(text);
    let mut result = HashMap::new();
    result.insert("typed".to_string(), serde_json::Value::String(text.to_string()));
    result.insert("method".to_string(), serde_json::Value::String("send_input".to_string()));
    let mut cmd_result = CommandResult::success(&cmd.command_id, result);
    cmd_result.screenshot_b64 = if config.enable_screenshot {
        crate::screenshot::capture_screenshot(config, windows::Win32::Foundation::HWND(0))
    } else {
        None
    };
    cmd_result
}

#[cfg(windows)]
fn try_set_value(automation_id: &str, text: &str) -> Option<bool> {
    use windows::Win32::UI::Accessibility::*;
    use windows::Win32::System::Com::{CoInitializeEx, COINIT_APARTMENTTHREADED};

    unsafe { let _ = CoInitializeEx(None, COINIT_APARTMENTTHREADED); }

    let uia: IUIAutomation = unsafe {
        windows::Win32::System::Com::CoCreateInstance(&CUIAutomation, None, windows::Win32::System::Com::CLSCTX_INPROC_SERVER).ok()?
    };
    let root = unsafe { uia.GetRootElement().ok()? };
    let prop = UIA_AutomationIdPropertyId;
    let val = bstr_to_variant(automation_id);
    let condition = unsafe { uia.CreatePropertyCondition(prop, val).ok()? };
    let element = unsafe { root.FindFirst(TreeScope_Descendants, &condition).ok()? };

    let value_pattern: Result<IUIAutomationValuePattern, _> = unsafe {
        element.GetCurrentPatternAs(UIA_ValuePatternId)
    };
    if let Ok(vp) = value_pattern {
        let bstr = windows::core::BSTR::from(text);
        if unsafe { vp.SetValue(&bstr) }.is_ok() {
            return Some(true);
        }
    }
    None
}

#[cfg(windows)]
fn send_text_via_input(text: &str) {
    use windows::Win32::UI::Input::KeyboardAndMouse::*;

    for ch in text.encode_utf16() {
        let inputs = [
            INPUT {
                r#type: INPUT_KEYBOARD,
                Anonymous: INPUT_0 {
                    ki: KEYBDINPUT {
                        wVk: VIRTUAL_KEY(0),
                        wScan: ch,
                        dwFlags: KEYEVENTF_UNICODE,
                        time: 0,
                        dwExtraInfo: 0,
                    },
                },
            },
            INPUT {
                r#type: INPUT_KEYBOARD,
                Anonymous: INPUT_0 {
                    ki: KEYBDINPUT {
                        wVk: VIRTUAL_KEY(0),
                        wScan: ch,
                        dwFlags: KEYEVENTF_UNICODE | KEYEVENTF_KEYUP,
                        time: 0,
                        dwExtraInfo: 0,
                    },
                },
            },
        ];
        unsafe { SendInput(&inputs, std::mem::size_of::<INPUT>() as i32); }
    }
}

#[cfg(not(windows))]
fn handle_type_text(cmd: &Command, _config: &Config) -> CommandResult {
    CommandResult::failure(&cmd.command_id, "type_text requires Windows")
}

#[cfg(windows)]
fn handle_send_keys(cmd: &Command, config: &Config) -> CommandResult {
    use windows::Win32::UI::Input::KeyboardAndMouse::*;

    let keys = cmd.parameters.get("keys").and_then(|v| v.as_str()).unwrap_or("");
    if keys.is_empty() {
        return CommandResult::failure(&cmd.command_id, "send_keys requires 'keys' parameter");
    }

    // Parse modifier+key combos like "ctrl+c", "alt+f4", "ctrl+shift+s"
    let parts: Vec<&str> = keys.split('+').collect();
    let mut modifiers: Vec<VIRTUAL_KEY> = Vec::new();
    let mut key_code: Option<VIRTUAL_KEY> = None;

    for part in &parts {
        match part.to_lowercase().as_str() {
            "ctrl" | "control" => modifiers.push(VK_CONTROL),
            "alt" => modifiers.push(VK_MENU),
            "shift" => modifiers.push(VK_SHIFT),
            "win" | "windows" => modifiers.push(VK_LWIN),
            _ => {
                key_code = parse_vk(part);
            }
        }
    }

    let vk = match key_code {
        Some(k) => k,
        None => return CommandResult::failure(&cmd.command_id, &format!("unknown key: {keys}")),
    };

    // Press modifiers
    for m in &modifiers {
        let input = INPUT {
            r#type: INPUT_KEYBOARD,
            Anonymous: INPUT_0 {
                ki: KEYBDINPUT {
                    wVk: *m,
                    wScan: 0,
                    dwFlags: KEYBD_EVENT_FLAGS(0),
                    time: 0,
                    dwExtraInfo: 0,
                },
            },
        };
        unsafe { SendInput(&[input], std::mem::size_of::<INPUT>() as i32); }
    }

    // Press and release key
    let down = INPUT {
        r#type: INPUT_KEYBOARD,
        Anonymous: INPUT_0 {
            ki: KEYBDINPUT {
                wVk: vk,
                wScan: 0,
                dwFlags: KEYBD_EVENT_FLAGS(0),
                time: 0,
                dwExtraInfo: 0,
            },
        },
    };
    let up = INPUT {
        r#type: INPUT_KEYBOARD,
        Anonymous: INPUT_0 {
            ki: KEYBDINPUT {
                wVk: vk,
                wScan: 0,
                dwFlags: KEYEVENTF_KEYUP,
                time: 0,
                dwExtraInfo: 0,
            },
        },
    };
    unsafe {
        SendInput(&[down], std::mem::size_of::<INPUT>() as i32);
        SendInput(&[up], std::mem::size_of::<INPUT>() as i32);
    }

    // Release modifiers (reverse order)
    for m in modifiers.iter().rev() {
        let input = INPUT {
            r#type: INPUT_KEYBOARD,
            Anonymous: INPUT_0 {
                ki: KEYBDINPUT {
                    wVk: *m,
                    wScan: 0,
                    dwFlags: KEYEVENTF_KEYUP,
                    time: 0,
                    dwExtraInfo: 0,
                },
            },
        };
        unsafe { SendInput(&[input], std::mem::size_of::<INPUT>() as i32); }
    }

    let mut result = HashMap::new();
    result.insert("keys".to_string(), serde_json::Value::String(keys.to_string()));
    let mut cmd_result = CommandResult::success(&cmd.command_id, result);
    cmd_result.screenshot_b64 = if config.enable_screenshot {
        crate::screenshot::capture_screenshot(config, windows::Win32::Foundation::HWND(0))
    } else {
        None
    };
    cmd_result
}

#[cfg(windows)]
fn parse_vk(key: &str) -> Option<windows::Win32::UI::Input::KeyboardAndMouse::VIRTUAL_KEY> {
    use windows::Win32::UI::Input::KeyboardAndMouse::*;
    match key.to_lowercase().as_str() {
        "a" => Some(VK_A), "b" => Some(VK_B), "c" => Some(VK_C), "d" => Some(VK_D),
        "e" => Some(VK_E), "f" => Some(VK_F), "g" => Some(VK_G), "h" => Some(VK_H),
        "i" => Some(VK_I), "j" => Some(VK_J), "k" => Some(VK_K), "l" => Some(VK_L),
        "m" => Some(VK_M), "n" => Some(VK_N), "o" => Some(VK_O), "p" => Some(VK_P),
        "q" => Some(VK_Q), "r" => Some(VK_R), "s" => Some(VK_S), "t" => Some(VK_T),
        "u" => Some(VK_U), "v" => Some(VK_V), "w" => Some(VK_W), "x" => Some(VK_X),
        "y" => Some(VK_Y), "z" => Some(VK_Z),
        "0" => Some(VK_0), "1" => Some(VK_1), "2" => Some(VK_2), "3" => Some(VK_3),
        "4" => Some(VK_4), "5" => Some(VK_5), "6" => Some(VK_6), "7" => Some(VK_7),
        "8" => Some(VK_8), "9" => Some(VK_9),
        "enter" | "return" => Some(VK_RETURN),
        "escape" | "esc" => Some(VK_ESCAPE),
        "tab" => Some(VK_TAB),
        "space" => Some(VK_SPACE),
        "backspace" => Some(VK_BACK),
        "delete" | "del" => Some(VK_DELETE),
        "home" => Some(VK_HOME),
        "end" => Some(VK_END),
        "pageup" => Some(VK_PRIOR),
        "pagedown" => Some(VK_NEXT),
        "up" => Some(VK_UP),
        "down" => Some(VK_DOWN),
        "left" => Some(VK_LEFT),
        "right" => Some(VK_RIGHT),
        "f1" => Some(VK_F1), "f2" => Some(VK_F2), "f3" => Some(VK_F3), "f4" => Some(VK_F4),
        "f5" => Some(VK_F5), "f6" => Some(VK_F6), "f7" => Some(VK_F7), "f8" => Some(VK_F8),
        "f9" => Some(VK_F9), "f10" => Some(VK_F10), "f11" => Some(VK_F11), "f12" => Some(VK_F12),
        _ => None,
    }
}

#[cfg(not(windows))]
fn handle_send_keys(cmd: &Command, _config: &Config) -> CommandResult {
    CommandResult::failure(&cmd.command_id, "send_keys requires Windows")
}

#[cfg(windows)]
fn handle_open_application(cmd: &Command, config: &Config) -> CommandResult {
    use std::ffi::OsStr;
    use std::os::windows::ffi::OsStrExt;
    use windows::Win32::UI::Shell::ShellExecuteW;
    use windows::Win32::Foundation::HWND;
    use windows::core::PCWSTR;

    let app = cmd.parameters.get("application").and_then(|v| v.as_str()).unwrap_or("");
    if app.is_empty() {
        return CommandResult::failure(&cmd.command_id, "open_application requires 'application' parameter");
    }

    let operation: Vec<u16> = OsStr::new("open").encode_wide().chain(Some(0)).collect();
    let file: Vec<u16> = OsStr::new(app).encode_wide().chain(Some(0)).collect();

    let result = unsafe {
        ShellExecuteW(
            HWND(0),
            PCWSTR(operation.as_ptr()),
            PCWSTR(file.as_ptr()),
            PCWSTR::null(),
            PCWSTR::null(),
            windows::Win32::UI::WindowsAndMessaging::SW_SHOWNORMAL,
        )
    };

    let code = result.0 as usize;
    if code <= 32 {
        return CommandResult::failure(&cmd.command_id, &format!("ShellExecute failed with code {code}"));
    }

    // Wait briefly for app to start
    std::thread::sleep(std::time::Duration::from_millis(500));

    let mut res = HashMap::new();
    res.insert("started".to_string(), serde_json::Value::String(app.to_string()));
    let mut cmd_result = CommandResult::success(&cmd.command_id, res);
    cmd_result.screenshot_b64 = if config.enable_screenshot {
        crate::screenshot::capture_screenshot(config, windows::Win32::Foundation::HWND(0))
    } else {
        None
    };
    cmd_result
}

#[cfg(not(windows))]
fn handle_open_application(cmd: &Command, _config: &Config) -> CommandResult {
    CommandResult::failure(&cmd.command_id, "open_application requires Windows")
}

#[cfg(windows)]
fn handle_focus_window(cmd: &Command, config: &Config) -> CommandResult {
    use windows::Win32::Foundation::HWND;
    use windows::Win32::UI::WindowsAndMessaging::*;
    use windows::core::PCWSTR;

    let title_pattern = cmd.parameters.get("title").and_then(|v| v.as_str()).unwrap_or("");
    let process_pattern = cmd.parameters.get("process").and_then(|v| v.as_str()).unwrap_or("");

    if title_pattern.is_empty() && process_pattern.is_empty() {
        return CommandResult::failure(&cmd.command_id, "focus_window requires 'title' or 'process' parameter");
    }

    let pattern_lower = title_pattern.to_lowercase();

    // Iterate visible windows to find match
    let mut target = HWND(0);

    // Use FindWindowW for exact matches, or enumerate
    if !title_pattern.is_empty() {
        // Enumerate all top-level windows
        let mut buf = [0u16; 512];
        let mut current = unsafe { FindWindowW(PCWSTR::null(), PCWSTR::null()) };
        while current.0 != 0 {
            let len = unsafe { GetWindowTextW(current, &mut buf) };
            if len > 0 {
                let title = String::from_utf16_lossy(&buf[..len as usize]);
                if title.to_lowercase().contains(&pattern_lower) {
                    if unsafe { IsWindowVisible(current) }.as_bool() {
                        target = current;
                        break;
                    }
                }
            }
            current = unsafe { GetWindow(current, GW_HWNDNEXT) };
            if current.0 == 0 { break; }
        }
    }

    if target.0 == 0 {
        return CommandResult::failure(&cmd.command_id, &format!("window not found matching: {title_pattern}"));
    }

    unsafe {
        let _ = SetForegroundWindow(target);
    }

    std::thread::sleep(std::time::Duration::from_millis(200));

    let mut result = HashMap::new();
    result.insert("focused".to_string(), serde_json::Value::String(title_pattern.to_string()));
    let mut cmd_result = CommandResult::success(&cmd.command_id, result);
    cmd_result.screenshot_b64 = if config.enable_screenshot {
        crate::screenshot::capture_screenshot(config, windows::Win32::Foundation::HWND(0))
    } else {
        None
    };
    cmd_result
}

#[cfg(not(windows))]
fn handle_focus_window(cmd: &Command, _config: &Config) -> CommandResult {
    CommandResult::failure(&cmd.command_id, "focus_window requires Windows")
}

#[cfg(windows)]
fn handle_scroll(cmd: &Command, config: &Config) -> CommandResult {
    use windows::Win32::UI::Input::KeyboardAndMouse::*;

    let direction = cmd.parameters.get("direction").and_then(|v| v.as_str()).unwrap_or("down");
    let amount = cmd.parameters.get("amount").and_then(|v| v.as_i64()).unwrap_or(3) as i32;

    // WHEEL_DELTA is 120 per "click"; positive = up, negative = down
    let wheel_delta = match direction {
        "up" => 120 * amount,
        "down" => -120 * amount,
        _ => return CommandResult::failure(&cmd.command_id, &format!("unknown scroll direction: {direction}")),
    };

    let input = INPUT {
        r#type: INPUT_MOUSE,
        Anonymous: INPUT_0 {
            mi: MOUSEINPUT {
                dx: 0,
                dy: 0,
                mouseData: wheel_delta as u32,
                dwFlags: MOUSEEVENTF_WHEEL,
                time: 0,
                dwExtraInfo: 0,
            },
        },
    };
    unsafe { SendInput(&[input], std::mem::size_of::<INPUT>() as i32); }

    let mut result = HashMap::new();
    result.insert("direction".to_string(), serde_json::Value::String(direction.to_string()));
    result.insert("amount".to_string(), serde_json::json!(amount));
    let mut cmd_result = CommandResult::success(&cmd.command_id, result);
    cmd_result.screenshot_b64 = if config.enable_screenshot {
        crate::screenshot::capture_screenshot(config, windows::Win32::Foundation::HWND(0))
    } else {
        None
    };
    cmd_result
}

#[cfg(not(windows))]
fn handle_scroll(cmd: &Command, _config: &Config) -> CommandResult {
    CommandResult::failure(&cmd.command_id, "scroll requires Windows")
}

/// Resolve a UIA element by name or automation_id and return its bounding rect center.
#[cfg(windows)]
fn resolve_uia_coords(name: &str, automation_id: &str) -> Option<(i32, i32)> {
    use windows::Win32::UI::Accessibility::*;
    use windows::Win32::System::Com::{CoInitializeEx, COINIT_APARTMENTTHREADED};

    unsafe { let _ = CoInitializeEx(None, COINIT_APARTMENTTHREADED); }

    let uia: IUIAutomation = unsafe {
        windows::Win32::System::Com::CoCreateInstance(
            &CUIAutomation, None,
            windows::Win32::System::Com::CLSCTX_INPROC_SERVER,
        ).ok()?
    };
    let root = unsafe { uia.GetRootElement().ok()? };

    let condition = if !automation_id.is_empty() {
        unsafe { uia.CreatePropertyCondition(UIA_AutomationIdPropertyId, bstr_to_variant(automation_id)).ok()? }
    } else {
        unsafe { uia.CreatePropertyCondition(UIA_NamePropertyId, bstr_to_variant(name)).ok()? }
    };

    let element = unsafe { root.FindFirst(TreeScope_Descendants, &condition).ok()? };
    let rect = unsafe { element.CurrentBoundingRectangle().ok()? };
    Some(((rect.left + rect.right) / 2, (rect.top + rect.bottom) / 2))
}

#[cfg(windows)]
fn handle_double_click(cmd: &Command, config: &Config) -> CommandResult {
    // Support name-based UIA resolution (same as click), with x/y fallback
    let name = cmd.parameters.get("name").and_then(|v| v.as_str()).unwrap_or("");
    let automation_id = cmd.parameters.get("automation_id").and_then(|v| v.as_str()).unwrap_or("");

    let (x, y) = if !name.is_empty() || !automation_id.is_empty() {
        match resolve_uia_coords(name, automation_id) {
            Some(coords) => coords,
            None => return CommandResult::failure(&cmd.command_id, &format!("element not found: {}", if !name.is_empty() { name } else { automation_id })),
        }
    } else {
        let x = cmd.parameters.get("x").and_then(|v| v.as_i64()).unwrap_or(-1) as i32;
        let y = cmd.parameters.get("y").and_then(|v| v.as_i64()).unwrap_or(-1) as i32;
        if x < 0 || y < 0 {
            return CommandResult::failure(&cmd.command_id, "double_click requires 'name', 'automation_id', or 'x'/'y' parameters");
        }
        (x, y)
    };

    // Move + double left-click using SendInput
    use windows::Win32::UI::Input::KeyboardAndMouse::*;

    let screen_w = unsafe { windows::Win32::UI::WindowsAndMessaging::GetSystemMetrics(windows::Win32::UI::WindowsAndMessaging::SM_CXSCREEN) };
    let screen_h = unsafe { windows::Win32::UI::WindowsAndMessaging::GetSystemMetrics(windows::Win32::UI::WindowsAndMessaging::SM_CYSCREEN) };

    let norm_x = (x as i64 * 65535 / screen_w as i64) as i32;
    let norm_y = (y as i64 * 65535 / screen_h as i64) as i32;

    let inputs = [
        // First click
        INPUT {
            r#type: INPUT_MOUSE,
            Anonymous: INPUT_0 {
                mi: MOUSEINPUT {
                    dx: norm_x, dy: norm_y, mouseData: 0,
                    dwFlags: MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_MOVE | MOUSEEVENTF_LEFTDOWN,
                    time: 0, dwExtraInfo: 0,
                },
            },
        },
        INPUT {
            r#type: INPUT_MOUSE,
            Anonymous: INPUT_0 {
                mi: MOUSEINPUT {
                    dx: norm_x, dy: norm_y, mouseData: 0,
                    dwFlags: MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_MOVE | MOUSEEVENTF_LEFTUP,
                    time: 0, dwExtraInfo: 0,
                },
            },
        },
        // Second click
        INPUT {
            r#type: INPUT_MOUSE,
            Anonymous: INPUT_0 {
                mi: MOUSEINPUT {
                    dx: norm_x, dy: norm_y, mouseData: 0,
                    dwFlags: MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_MOVE | MOUSEEVENTF_LEFTDOWN,
                    time: 0, dwExtraInfo: 0,
                },
            },
        },
        INPUT {
            r#type: INPUT_MOUSE,
            Anonymous: INPUT_0 {
                mi: MOUSEINPUT {
                    dx: norm_x, dy: norm_y, mouseData: 0,
                    dwFlags: MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_MOVE | MOUSEEVENTF_LEFTUP,
                    time: 0, dwExtraInfo: 0,
                },
            },
        },
    ];

    unsafe { SendInput(&inputs, std::mem::size_of::<INPUT>() as i32); }

    let mut result = HashMap::new();
    result.insert("x".to_string(), serde_json::json!(x));
    result.insert("y".to_string(), serde_json::json!(y));
    let mut cmd_result = CommandResult::success(&cmd.command_id, result);
    cmd_result.screenshot_b64 = if config.enable_screenshot {
        crate::screenshot::capture_screenshot(config, windows::Win32::Foundation::HWND(0))
    } else {
        None
    };
    cmd_result
}

#[cfg(not(windows))]
fn handle_double_click(cmd: &Command, _config: &Config) -> CommandResult {
    CommandResult::failure(&cmd.command_id, "double_click requires Windows")
}

#[cfg(windows)]
fn handle_right_click(cmd: &Command, config: &Config) -> CommandResult {
    // Support name-based UIA resolution (same as click/double_click), with x/y fallback
    let name = cmd.parameters.get("name").and_then(|v| v.as_str()).unwrap_or("");
    let automation_id = cmd.parameters.get("automation_id").and_then(|v| v.as_str()).unwrap_or("");

    let (x, y) = if !name.is_empty() || !automation_id.is_empty() {
        match resolve_uia_coords(name, automation_id) {
            Some(coords) => coords,
            None => return CommandResult::failure(&cmd.command_id, &format!("element not found: {}", if !name.is_empty() { name } else { automation_id })),
        }
    } else {
        let x = cmd.parameters.get("x").and_then(|v| v.as_i64()).unwrap_or(-1) as i32;
        let y = cmd.parameters.get("y").and_then(|v| v.as_i64()).unwrap_or(-1) as i32;
        if x < 0 || y < 0 {
            return CommandResult::failure(&cmd.command_id, "right_click requires 'name', 'automation_id', or 'x'/'y' parameters");
        }
        (x, y)
    };

    use windows::Win32::UI::Input::KeyboardAndMouse::*;

    let screen_w = unsafe { windows::Win32::UI::WindowsAndMessaging::GetSystemMetrics(windows::Win32::UI::WindowsAndMessaging::SM_CXSCREEN) };
    let screen_h = unsafe { windows::Win32::UI::WindowsAndMessaging::GetSystemMetrics(windows::Win32::UI::WindowsAndMessaging::SM_CYSCREEN) };

    let norm_x = (x as i64 * 65535 / screen_w as i64) as i32;
    let norm_y = (y as i64 * 65535 / screen_h as i64) as i32;

    let inputs = [
        INPUT {
            r#type: INPUT_MOUSE,
            Anonymous: INPUT_0 {
                mi: MOUSEINPUT {
                    dx: norm_x, dy: norm_y, mouseData: 0,
                    dwFlags: MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_MOVE | MOUSEEVENTF_RIGHTDOWN,
                    time: 0, dwExtraInfo: 0,
                },
            },
        },
        INPUT {
            r#type: INPUT_MOUSE,
            Anonymous: INPUT_0 {
                mi: MOUSEINPUT {
                    dx: norm_x, dy: norm_y, mouseData: 0,
                    dwFlags: MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_MOVE | MOUSEEVENTF_RIGHTUP,
                    time: 0, dwExtraInfo: 0,
                },
            },
        },
    ];

    unsafe { SendInput(&inputs, std::mem::size_of::<INPUT>() as i32); }

    let mut result = HashMap::new();
    result.insert("x".to_string(), serde_json::json!(x));
    result.insert("y".to_string(), serde_json::json!(y));
    let mut cmd_result = CommandResult::success(&cmd.command_id, result);
    cmd_result.screenshot_b64 = if config.enable_screenshot {
        crate::screenshot::capture_screenshot(config, windows::Win32::Foundation::HWND(0))
    } else {
        None
    };
    cmd_result
}

#[cfg(not(windows))]
fn handle_right_click(cmd: &Command, _config: &Config) -> CommandResult {
    CommandResult::failure(&cmd.command_id, "right_click requires Windows")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_command_parse_from_json() {
        let json = r#"{"command_id": "abc-123", "action": "observe", "parameters": {}, "timeout_ms": 3000}"#;
        let cmd: Command = serde_json::from_str(json).unwrap();
        assert_eq!(cmd.command_id, "abc-123");
        assert_eq!(cmd.action, "observe");
        assert_eq!(cmd.timeout_ms, 3000);
        assert!(cmd.parameters.is_empty());
    }

    #[test]
    fn test_command_parse_with_parameters() {
        let json = r#"{"command_id": "def-456", "action": "click", "parameters": {"name": "Send", "automation_id": "btn_send"}}"#;
        let cmd: Command = serde_json::from_str(json).unwrap();
        assert_eq!(cmd.action, "click");
        assert_eq!(cmd.parameters["name"], "Send");
        assert_eq!(cmd.parameters["automation_id"], "btn_send");
        assert_eq!(cmd.timeout_ms, 5000); // default
    }

    #[test]
    fn test_command_result_success_serialize() {
        let mut result = HashMap::new();
        result.insert("clicked".to_string(), serde_json::Value::String("Send".to_string()));
        let cr = CommandResult::success("abc-123", result);

        let json = serde_json::to_value(&cr).unwrap();
        assert_eq!(json["type"], "command_result");
        assert_eq!(json["command_id"], "abc-123");
        assert_eq!(json["ok"], true);
        assert_eq!(json["result"]["clicked"], "Send");
        assert!(json.get("error").is_none());
        assert!(json.get("screenshot_b64").is_none());
    }

    #[test]
    fn test_command_result_failure_serialize() {
        let cr = CommandResult::failure("abc-123", "element not found");

        let json = serde_json::to_value(&cr).unwrap();
        assert_eq!(json["type"], "command_result");
        assert_eq!(json["command_id"], "abc-123");
        assert_eq!(json["ok"], false);
        assert_eq!(json["error"], "element not found");
    }

    #[test]
    fn test_command_result_with_screenshot() {
        let mut cr = CommandResult::success("test-id", HashMap::new());
        cr.screenshot_b64 = Some("base64data".to_string());
        cr.uia = Some(serde_json::json!({"focused_name": "Button"}));

        let json = serde_json::to_value(&cr).unwrap();
        assert_eq!(json["screenshot_b64"], "base64data");
        assert_eq!(json["uia"]["focused_name"], "Button");
    }

    #[test]
    fn test_unknown_action_returns_error() {
        let cmd = Command {
            command_id: "test-id".to_string(),
            action: "nonexistent".to_string(),
            parameters: HashMap::new(),
            timeout_ms: 5000,
        };
        let config = Config::from_env();
        let result = execute_command(&cmd, &config);
        assert!(!result.ok);
        assert!(result.error.as_ref().unwrap().contains("unknown action"));
    }

    #[test]
    fn test_command_parse_minimal() {
        let json = r#"{"command_id": "x", "action": "observe"}"#;
        let cmd: Command = serde_json::from_str(json).unwrap();
        assert_eq!(cmd.command_id, "x");
        assert_eq!(cmd.action, "observe");
        assert!(cmd.parameters.is_empty());
        assert_eq!(cmd.timeout_ms, 5000);
    }

    #[test]
    fn test_scroll_command_parse() {
        let json = r#"{"command_id": "s1", "action": "scroll", "parameters": {"direction": "up", "amount": 5}}"#;
        let cmd: Command = serde_json::from_str(json).unwrap();
        assert_eq!(cmd.action, "scroll");
        assert_eq!(cmd.parameters["direction"], "up");
        assert_eq!(cmd.parameters["amount"], 5);
    }

    #[test]
    fn test_double_click_command_parse() {
        let json = r#"{"command_id": "dc1", "action": "double_click", "parameters": {"x": 100, "y": 200}}"#;
        let cmd: Command = serde_json::from_str(json).unwrap();
        assert_eq!(cmd.action, "double_click");
        assert_eq!(cmd.parameters["x"], 100);
        assert_eq!(cmd.parameters["y"], 200);
    }

    #[test]
    fn test_right_click_command_parse() {
        let json = r#"{"command_id": "rc1", "action": "right_click", "parameters": {"x": 50, "y": 75}}"#;
        let cmd: Command = serde_json::from_str(json).unwrap();
        assert_eq!(cmd.action, "right_click");
        assert_eq!(cmd.parameters["x"], 50);
        assert_eq!(cmd.parameters["y"], 75);
    }

    #[test]
    fn test_double_click_name_based_parse() {
        let json = r#"{"command_id": "dc2", "action": "double_click", "parameters": {"name": "Submit"}}"#;
        let cmd: Command = serde_json::from_str(json).unwrap();
        assert_eq!(cmd.action, "double_click");
        assert_eq!(cmd.parameters["name"], "Submit");
    }

    #[test]
    fn test_right_click_name_based_parse() {
        let json = r#"{"command_id": "rc2", "action": "right_click", "parameters": {"name": "FileItem", "automation_id": "file_1"}}"#;
        let cmd: Command = serde_json::from_str(json).unwrap();
        assert_eq!(cmd.action, "right_click");
        assert_eq!(cmd.parameters["name"], "FileItem");
        assert_eq!(cmd.parameters["automation_id"], "file_1");
    }

    #[cfg(not(windows))]
    #[test]
    fn test_new_commands_fail_on_non_windows() {
        let config = Config::from_env();
        for action in &["scroll", "double_click", "right_click"] {
            let cmd = Command {
                command_id: "test".to_string(),
                action: action.to_string(),
                parameters: HashMap::new(),
                timeout_ms: 5000,
            };
            let result = execute_command(&cmd, &config);
            assert!(!result.ok, "{action} should fail on non-Windows");
            assert!(result.error.as_ref().unwrap().contains("requires Windows"));
        }
    }

    #[test]
    fn test_click_xy_command_parse() {
        let json = r#"{"command_id": "c1", "action": "click", "parameters": {"x": 300, "y": 450}}"#;
        let cmd: Command = serde_json::from_str(json).unwrap();
        assert_eq!(cmd.action, "click");
        assert_eq!(cmd.parameters["x"], 300);
        assert_eq!(cmd.parameters["y"], 450);
    }

    #[cfg(not(windows))]
    #[test]
    fn test_click_missing_all_params_returns_error() {
        let config = Config::from_env();
        let cmd = Command {
            command_id: "test-click".to_string(),
            action: "click".to_string(),
            parameters: HashMap::new(),
            timeout_ms: 5000,
        };
        let result = execute_command(&cmd, &config);
        assert!(!result.ok);
        assert!(result.error.as_ref().unwrap().contains("click requires"));
        assert!(result.error.as_ref().unwrap().contains("x")); // mentions x/y
    }
}
