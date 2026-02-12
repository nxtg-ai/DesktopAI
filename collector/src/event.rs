//! Desktop event types sent from the collector to the backend.

use chrono::Utc;
use serde::Serialize;
use windows::core::BSTR;
use windows::Win32::Foundation::HWND;

/// A desktop event capturing a foreground window change or idle state transition.
#[derive(Debug, Serialize, Clone)]
pub struct WindowEvent {
    #[serde(rename = "type")]
    pub event_type: String,
    pub hwnd: String,
    pub title: String,
    pub process_exe: String,
    pub pid: u32,
    pub timestamp: String,
    pub source: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub idle_ms: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub uia: Option<UiaSnapshot>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub screenshot_b64: Option<String>,
}

/// A single UI Automation element in the accessibility tree.
#[derive(Debug, Serialize, Clone, Default)]
pub struct UiaElement {
    pub automation_id: String,
    pub name: String,
    pub control_type: String,
    pub class_name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub bounding_rect: Option<[i32; 4]>,  // [x, y, width, height]
    pub is_enabled: bool,
    pub is_offscreen: bool,
    pub patterns: Vec<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub value: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub toggle_state: Option<String>,
    pub children: Vec<UiaElement>,
}

/// A snapshot of the UIA tree for the focused window, including the focused element and descendants.
#[derive(Debug, Serialize, Clone, Default)]
pub struct UiaSnapshot {
    pub focused_name: String,
    pub control_type: String,
    pub document_text: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub focused_element: Option<UiaElement>,
    pub window_tree: Vec<UiaElement>,
}

/// Convert a window handle to a hex string for serialization.
pub fn hwnd_to_hex(hwnd: HWND) -> String {
    format!("{:#x}", hwnd.0 as usize)
}

/// Build an idle/active activity event (no window context, just the state transition).
pub fn build_activity_event(event_type: &str, idle_ms: u64) -> WindowEvent {
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
        screenshot_b64: None,
    }
}

pub fn bstr_to_string(value: BSTR) -> String {
    String::from_utf16_lossy(value.as_wide())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_window_event_serialization() {
        let event = WindowEvent {
            event_type: "focus".to_string(),
            hwnd: "0x12345".to_string(),
            title: "Test Window".to_string(),
            process_exe: "test.exe".to_string(),
            pid: 1234,
            timestamp: "2026-02-09T12:00:00.000Z".to_string(),
            source: "collector".to_string(),
            idle_ms: None,
            uia: None,
            screenshot_b64: None,
        };

        let json = serde_json::to_value(&event).unwrap();
        assert_eq!(json["type"], "focus");
        assert_eq!(json["hwnd"], "0x12345");
        assert_eq!(json["title"], "Test Window");
        assert_eq!(json["process_exe"], "test.exe");
        assert_eq!(json["pid"], 1234);
        assert_eq!(json["source"], "collector");
        assert!(json.get("idle_ms").is_none());
        assert!(json.get("uia").is_none());
        assert!(json.get("screenshot_b64").is_none());
    }

    #[test]
    fn test_window_event_serialization_with_idle() {
        let event = WindowEvent {
            event_type: "idle".to_string(),
            hwnd: "0x0".to_string(),
            title: String::new(),
            process_exe: String::new(),
            pid: 0,
            timestamp: "2026-02-09T12:00:00.000Z".to_string(),
            source: "collector".to_string(),
            idle_ms: Some(60000),
            uia: None,
            screenshot_b64: None,
        };

        let json = serde_json::to_value(&event).unwrap();
        assert_eq!(json["type"], "idle");
        assert_eq!(json["idle_ms"], 60000);
    }

    #[test]
    fn test_window_event_serialization_with_screenshot() {
        let event = WindowEvent {
            event_type: "focus".to_string(),
            hwnd: "0x12345".to_string(),
            title: "Test".to_string(),
            process_exe: "test.exe".to_string(),
            pid: 1234,
            timestamp: "2026-02-09T12:00:00.000Z".to_string(),
            source: "collector".to_string(),
            idle_ms: None,
            uia: None,
            screenshot_b64: Some("base64data".to_string()),
        };

        let json = serde_json::to_value(&event).unwrap();
        assert_eq!(json["screenshot_b64"], "base64data");
    }

    #[test]
    fn test_uia_element_default() {
        let element = UiaElement::default();
        assert_eq!(element.automation_id, "");
        assert_eq!(element.name, "");
        assert_eq!(element.control_type, "");
        assert_eq!(element.class_name, "");
        assert!(element.bounding_rect.is_none());
        assert!(!element.is_enabled);
        assert!(!element.is_offscreen);
        assert!(element.patterns.is_empty());
        assert!(element.value.is_none());
        assert!(element.toggle_state.is_none());
        assert!(element.children.is_empty());
    }

    #[test]
    fn test_uia_element_serialization() {
        let element = UiaElement {
            automation_id: "btn1".to_string(),
            name: "Submit".to_string(),
            control_type: "Button".to_string(),
            class_name: "Button".to_string(),
            bounding_rect: Some([10, 20, 100, 50]),
            is_enabled: true,
            is_offscreen: false,
            patterns: vec!["Invoke".to_string()],
            value: None,
            toggle_state: None,
            children: vec![],
        };

        let json = serde_json::to_value(&element).unwrap();
        assert_eq!(json["automation_id"], "btn1");
        assert_eq!(json["name"], "Submit");
        assert_eq!(json["control_type"], "Button");
        assert_eq!(json["bounding_rect"][0], 10);
        assert_eq!(json["bounding_rect"][1], 20);
        assert_eq!(json["bounding_rect"][2], 100);
        assert_eq!(json["bounding_rect"][3], 50);
        assert_eq!(json["is_enabled"], true);
        assert_eq!(json["patterns"][0], "Invoke");
    }

    #[test]
    fn test_uia_element_with_children() {
        let child = UiaElement {
            automation_id: "child1".to_string(),
            name: "Child".to_string(),
            control_type: "Text".to_string(),
            class_name: "Static".to_string(),
            bounding_rect: None,
            is_enabled: true,
            is_offscreen: false,
            patterns: vec![],
            value: Some("Hello".to_string()),
            toggle_state: None,
            children: vec![],
        };

        let parent = UiaElement {
            automation_id: "parent1".to_string(),
            name: "Parent".to_string(),
            control_type: "Group".to_string(),
            class_name: "GroupBox".to_string(),
            bounding_rect: None,
            is_enabled: true,
            is_offscreen: false,
            patterns: vec![],
            value: None,
            toggle_state: None,
            children: vec![child],
        };

        let json = serde_json::to_value(&parent).unwrap();
        assert_eq!(json["children"].as_array().unwrap().len(), 1);
        assert_eq!(json["children"][0]["name"], "Child");
        assert_eq!(json["children"][0]["value"], "Hello");
    }

    #[test]
    fn test_uia_snapshot_default() {
        let snapshot = UiaSnapshot::default();
        assert_eq!(snapshot.focused_name, "");
        assert_eq!(snapshot.control_type, "");
        assert_eq!(snapshot.document_text, "");
        assert!(snapshot.focused_element.is_none());
        assert!(snapshot.window_tree.is_empty());
    }

    #[test]
    fn test_uia_snapshot_serialization() {
        let element = UiaElement {
            automation_id: "edit1".to_string(),
            name: "TextBox".to_string(),
            control_type: "Edit".to_string(),
            class_name: "Edit".to_string(),
            bounding_rect: None,
            is_enabled: true,
            is_offscreen: false,
            patterns: vec!["Value".to_string()],
            value: Some("Content".to_string()),
            toggle_state: None,
            children: vec![],
        };

        let snapshot = UiaSnapshot {
            focused_name: "TextBox".to_string(),
            control_type: "Edit".to_string(),
            document_text: "Sample text".to_string(),
            focused_element: Some(element.clone()),
            window_tree: vec![element],
        };

        let json = serde_json::to_value(&snapshot).unwrap();
        assert_eq!(json["focused_name"], "TextBox");
        assert_eq!(json["control_type"], "Edit");
        assert_eq!(json["document_text"], "Sample text");
        assert!(json["focused_element"].is_object());
        assert_eq!(json["window_tree"].as_array().unwrap().len(), 1);
    }

    #[test]
    fn test_window_event_with_uia() {
        let snapshot = UiaSnapshot {
            focused_name: "Button".to_string(),
            control_type: "Button".to_string(),
            document_text: "Click me".to_string(),
            focused_element: None,
            window_tree: vec![],
        };

        let event = WindowEvent {
            event_type: "focus".to_string(),
            hwnd: "0x12345".to_string(),
            title: "Test Window".to_string(),
            process_exe: "test.exe".to_string(),
            pid: 1234,
            timestamp: "2026-02-09T12:00:00.000Z".to_string(),
            source: "collector".to_string(),
            idle_ms: None,
            uia: Some(snapshot),
            screenshot_b64: None,
        };

        let json = serde_json::to_value(&event).unwrap();
        assert!(json.get("uia").is_some());
        assert_eq!(json["uia"]["focused_name"], "Button");
        assert_eq!(json["uia"]["control_type"], "Button");
        assert_eq!(json["uia"]["document_text"], "Click me");
    }

    #[test]
    fn test_build_activity_event_idle() {
        let event = build_activity_event("idle", 120000);

        assert_eq!(event.event_type, "idle");
        assert_eq!(event.hwnd, "0x0");
        assert_eq!(event.title, "");
        assert_eq!(event.process_exe, "");
        assert_eq!(event.pid, 0);
        assert_eq!(event.source, "collector");
        assert_eq!(event.idle_ms, Some(120000));
        assert!(event.uia.is_none());
        assert!(event.screenshot_b64.is_none());
        assert!(!event.timestamp.is_empty());
    }

    #[test]
    fn test_build_activity_event_active() {
        let event = build_activity_event("active", 500);

        assert_eq!(event.event_type, "active");
        assert_eq!(event.hwnd, "0x0");
        assert_eq!(event.source, "collector");
        assert_eq!(event.idle_ms, Some(500));
    }

    #[test]
    fn test_build_activity_event_timestamp_format() {
        let event = build_activity_event("idle", 0);

        // Verify RFC3339 format with milliseconds
        assert!(event.timestamp.contains("T"));
        assert!(event.timestamp.contains("Z"));
        assert!(event.timestamp.contains("."));
    }

    #[cfg(windows)]
    #[test]
    fn test_hwnd_to_hex_zero() {
        let hwnd = HWND(0);
        assert_eq!(hwnd_to_hex(hwnd), "0x0");
    }

    #[cfg(windows)]
    #[test]
    fn test_hwnd_to_hex_small_value() {
        let hwnd = HWND(255);
        assert_eq!(hwnd_to_hex(hwnd), "0xff");
    }

    #[cfg(windows)]
    #[test]
    fn test_hwnd_to_hex_large_value() {
        let hwnd = HWND(0x12345678);
        assert_eq!(hwnd_to_hex(hwnd), "0x12345678");
    }

    #[cfg(windows)]
    #[test]
    fn test_bstr_to_string_empty() {
        let bstr = BSTR::new();
        let result = bstr_to_string(bstr);
        assert_eq!(result, "");
    }

    #[cfg(windows)]
    #[test]
    fn test_bstr_to_string_ascii() {
        let bstr = BSTR::from("Hello");
        let result = bstr_to_string(bstr);
        assert_eq!(result, "Hello");
    }

    #[cfg(windows)]
    #[test]
    fn test_bstr_to_string_unicode() {
        let bstr = BSTR::from("Hello 世界");
        let result = bstr_to_string(bstr);
        assert_eq!(result, "Hello 世界");
    }

    #[test]
    fn test_window_event_clone() {
        let event1 = build_activity_event("idle", 1000);
        let event2 = event1.clone();

        assert_eq!(event1.event_type, event2.event_type);
        assert_eq!(event1.hwnd, event2.hwnd);
        assert_eq!(event1.idle_ms, event2.idle_ms);
    }

    #[test]
    fn test_uia_snapshot_clone() {
        let snapshot1 = UiaSnapshot {
            focused_name: "Test".to_string(),
            control_type: "Edit".to_string(),
            document_text: "Content".to_string(),
            focused_element: None,
            window_tree: vec![],
        };
        let snapshot2 = snapshot1.clone();

        assert_eq!(snapshot1.focused_name, snapshot2.focused_name);
        assert_eq!(snapshot1.control_type, snapshot2.control_type);
        assert_eq!(snapshot1.document_text, snapshot2.document_text);
    }

    #[test]
    fn test_uia_element_clone() {
        let element1 = UiaElement {
            automation_id: "test".to_string(),
            name: "Test".to_string(),
            control_type: "Button".to_string(),
            class_name: "Button".to_string(),
            bounding_rect: Some([0, 0, 100, 50]),
            is_enabled: true,
            is_offscreen: false,
            patterns: vec!["Invoke".to_string()],
            value: Some("val".to_string()),
            toggle_state: None,
            children: vec![],
        };
        let element2 = element1.clone();

        assert_eq!(element1.automation_id, element2.automation_id);
        assert_eq!(element1.name, element2.name);
        assert_eq!(element1.bounding_rect, element2.bounding_rect);
        assert_eq!(element1.patterns, element2.patterns);
    }

    #[test]
    fn test_window_event_debug_format() {
        let event = build_activity_event("idle", 1000);
        let debug_str = format!("{:?}", event);
        assert!(debug_str.contains("WindowEvent"));
        assert!(debug_str.contains("idle"));
    }

    #[test]
    fn test_uia_snapshot_debug_format() {
        let snapshot = UiaSnapshot {
            focused_name: "Test".to_string(),
            control_type: "Edit".to_string(),
            document_text: "Content".to_string(),
            focused_element: None,
            window_tree: vec![],
        };
        let debug_str = format!("{:?}", snapshot);
        assert!(debug_str.contains("UiaSnapshot"));
        assert!(debug_str.contains("Test"));
    }

    #[test]
    fn test_uia_element_debug_format() {
        let element = UiaElement::default();
        let debug_str = format!("{:?}", element);
        assert!(debug_str.contains("UiaElement"));
    }
}
