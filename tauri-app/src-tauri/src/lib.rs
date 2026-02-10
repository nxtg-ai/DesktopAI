use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    Manager,
};

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

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            // Build system tray
            let show = MenuItem::with_id(app, "show", "Show DesktopAI", true, None::<&str>)?;
            let hide = MenuItem::with_id(app, "hide", "Hide", true, None::<&str>)?;
            let dashboard =
                MenuItem::with_id(app, "dashboard", "Open Dashboard", true, None::<&str>)?;
            let quit = MenuItem::with_id(app, "quit", "Quit", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &hide, &dashboard, &quit])?;

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
                    "dashboard" => {
                        let _ = tauri_plugin_opener::OpenerExt::opener(app)
                            .open_url("http://localhost:8000", None::<&str>);
                    }
                    "quit" => {
                        app.exit(0);
                    }
                    _ => {}
                })
                .build(app)?;

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![toggle_visibility, set_compact_mode])
        .run(tauri::generate_context!())
        .expect("error while running DesktopAI");
}
