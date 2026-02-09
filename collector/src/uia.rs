use std::cell::RefCell;
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, Instant};
use windows::core::BSTR;
use windows::Win32::Foundation::{HWND, RECT};
use windows::Win32::System::Com::{
    CoCreateInstance, CoInitializeEx, COINIT_APARTMENTTHREADED, CLSCTX_INPROC_SERVER,
};
use windows::Win32::UI::Accessibility::{
    CUIAutomation, IUIAutomation, IUIAutomationElement, IUIAutomationTextPattern,
    TreeScope_Children, UIA_InvokePatternId, UIA_TextPatternId, UIA_TogglePatternId,
    UIA_ValuePatternId, ToggleState_Off, ToggleState_On, ToggleState_Indeterminate,
};

use crate::config::Config;
use crate::event::{bstr_to_string, UiaElement, UiaSnapshot};

pub static UIA_LAST_SNAPSHOT: OnceLock<Mutex<Instant>> = OnceLock::new();

thread_local! {
    pub static UIA_AUTOMATION: RefCell<Option<IUIAutomation>> = RefCell::new(None);
}

pub fn allow_uia_snapshot(throttle: Duration) -> bool {
    let lock = UIA_LAST_SNAPSHOT.get_or_init(|| Mutex::new(Instant::now() - throttle));
    let mut last = lock.lock().unwrap();
    if last.elapsed() < throttle {
        return false;
    }
    *last = Instant::now();
    true
}

pub fn get_uia() -> Option<IUIAutomation> {
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

pub fn extract_document_text(element: &IUIAutomationElement, max_len: usize) -> Option<String> {
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

fn get_bstr_property(element: &IUIAutomationElement, getter: impl FnOnce(&IUIAutomationElement) -> windows::core::Result<BSTR>) -> String {
    getter(element).ok().map(bstr_to_string).unwrap_or_default()
}

#[allow(non_upper_case_globals)]
fn build_uia_element(element: &IUIAutomationElement, depth: usize, max_depth: usize) -> Option<UiaElement> {
    let automation_id = get_bstr_property(element, |e| unsafe { e.CurrentAutomationId() });
    let name = get_bstr_property(element, |e| unsafe { e.CurrentName() });
    let control_type = get_bstr_property(element, |e| unsafe { e.CurrentLocalizedControlType() });
    let class_name = get_bstr_property(element, |e| unsafe { e.CurrentClassName() });

    let bounding_rect = unsafe {
        element.CurrentBoundingRectangle().ok().map(|rect: RECT| {
            [rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top]
        })
    };

    let is_enabled = unsafe { element.CurrentIsEnabled().ok().map(|b| b.as_bool()).unwrap_or(true) };
    let is_offscreen = unsafe { element.CurrentIsOffscreen().ok().map(|b| b.as_bool()).unwrap_or(false) };

    let mut patterns = Vec::new();
    let mut value = None;
    let mut toggle_state = None;

    // Check for Value pattern
    if let Ok(value_pattern) = unsafe { element.GetCurrentPatternAs::<windows::Win32::UI::Accessibility::IUIAutomationValuePattern>(UIA_ValuePatternId) } {
        patterns.push("Value".to_string());
        if let Ok(val) = unsafe { value_pattern.CurrentValue() } {
            value = Some(bstr_to_string(val));
        }
    }

    // Check for Toggle pattern
    if let Ok(toggle_pattern) = unsafe { element.GetCurrentPatternAs::<windows::Win32::UI::Accessibility::IUIAutomationTogglePattern>(UIA_TogglePatternId) } {
        patterns.push("Toggle".to_string());
        if let Ok(state) = unsafe { toggle_pattern.CurrentToggleState() } {
            toggle_state = Some(match state {
                ToggleState_Off => "Off".to_string(),
                ToggleState_On => "On".to_string(),
                ToggleState_Indeterminate => "Indeterminate".to_string(),
                _ => "Unknown".to_string(),
            });
        }
    }

    // Check for Invoke pattern
    if unsafe { element.GetCurrentPatternAs::<windows::Win32::UI::Accessibility::IUIAutomationInvokePattern>(UIA_InvokePatternId).is_ok() } {
        patterns.push("Invoke".to_string());
    }

    // Recursively build children if depth allows
    let mut children = Vec::new();
    if depth < max_depth {
        if let Some(condition) = get_uia().and_then(|uia| unsafe { uia.CreateTrueCondition().ok() }) {
            if let Ok(found) = unsafe { element.FindAll(TreeScope_Children, &condition) } {
                if let Ok(length) = unsafe { found.Length() } {
                    for i in 0..length.min(20) {  // Limit to 20 children per element
                        if let Ok(child) = unsafe { found.GetElement(i) } {
                            if let Some(child_element) = build_uia_element(&child, depth + 1, max_depth) {
                                children.push(child_element);
                            }
                        }
                    }
                }
            }
        }
    }

    Some(UiaElement {
        automation_id,
        name,
        control_type,
        class_name,
        bounding_rect,
        is_enabled,
        is_offscreen,
        patterns,
        value,
        toggle_state,
        children,
    })
}

pub fn uia_snapshot(hwnd: HWND, config: &Config) -> Option<UiaSnapshot> {
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

    // Build focused element details
    let focused_element = build_uia_element(&element, 0, config.uia_max_depth);

    // Build window tree from the window root
    let mut window_tree = Vec::new();
    if let Ok(window_element) = unsafe { automation.ElementFromHandle(hwnd) } {
        if let Some(root) = build_uia_element(&window_element, 0, config.uia_max_depth) {
            window_tree.push(root);
        }
    }

    let snapshot = UiaSnapshot {
        focused_name,
        control_type,
        document_text,
        focused_element,
        window_tree,
    };
    if snapshot.focused_name.is_empty()
        && snapshot.control_type.is_empty()
        && snapshot.document_text.is_empty()
        && snapshot.focused_element.is_none()
        && snapshot.window_tree.is_empty()
    {
        None
    } else {
        Some(snapshot)
    }
}
