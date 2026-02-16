use std::collections::VecDeque;
use std::sync::{Mutex, OnceLock};
use windows::Win32::Foundation::HWND;
use windows::Win32::Graphics::Gdi::{
    BitBlt, CreateCompatibleBitmap, CreateCompatibleDC, DeleteDC, DeleteObject, GetDC,
    GetDIBits, GetMonitorInfoW, MonitorFromWindow, ReleaseDC, SelectObject, BITMAPINFO,
    BITMAPINFOHEADER, BI_RGB, DIB_RGB_COLORS, MONITOR_DEFAULTTONEAREST, MONITORINFO, SRCCOPY,
};
use windows::Win32::UI::WindowsAndMessaging::GetForegroundWindow;

use crate::config::Config;

const RING_BUFFER_SIZE: usize = 5;

pub static SCREENSHOT_BUFFER: OnceLock<Mutex<VecDeque<Vec<u8>>>> = OnceLock::new();

/// Initialize the screenshot ring buffer
pub fn init_screenshot_buffer() {
    SCREENSHOT_BUFFER.get_or_init(|| Mutex::new(VecDeque::with_capacity(RING_BUFFER_SIZE)));
}

/// Capture a screenshot of the monitor containing the given window (or the
/// foreground window if `hwnd` is null/zero) and return as base64-encoded JPEG.
/// On multi-monitor setups this avoids the squished full-virtual-desktop image
/// that confused the VLM.
pub fn capture_screenshot(config: &Config, hwnd: HWND) -> Option<String> {
    if !config.enable_screenshot {
        return None;
    }

    // Capture the raw screenshot
    let pixels = capture_monitor_pixels(hwnd)?;

    // Downscale if needed
    let (width, height, pixels) = downscale_if_needed(
        pixels.0,
        pixels.1,
        pixels.2,
        config.screenshot_max_width,
        config.screenshot_max_height,
    );

    // Encode as JPEG
    let jpeg_data = encode_jpeg(&pixels, width, height, config.screenshot_quality)?;

    // Store in ring buffer
    store_in_buffer(jpeg_data.clone());

    // Encode to base64
    Some(base64_encode(&jpeg_data))
}

/// Capture raw 24-bit BGR pixels from the monitor containing the given window.
/// Returns (width, height, pixel_data). Public so `handle_observe` can feed
/// pixels to the detection module before JPEG encoding.
pub fn capture_raw_pixels(hwnd: HWND) -> Option<(u32, u32, Vec<u8>)> {
    capture_monitor_pixels(hwnd)
}

/// Encode raw BGR pixels to base64 JPEG, applying downscale and ring buffer.
pub fn encode_raw_to_base64(
    config: &Config,
    width: u32,
    height: u32,
    pixels: Vec<u8>,
) -> Option<String> {
    let (w, h, px) = downscale_if_needed(
        width,
        height,
        pixels,
        config.screenshot_max_width,
        config.screenshot_max_height,
    );
    let jpeg_data = encode_jpeg(&px, w, h, config.screenshot_quality)?;
    store_in_buffer(jpeg_data.clone());
    Some(base64_encode(&jpeg_data))
}

/// Capture raw pixels from the monitor that contains the given window.
/// Falls back to the foreground window when `hwnd` is null, and ultimately
/// to the primary monitor if no foreground window is found.
fn capture_monitor_pixels(hwnd: HWND) -> Option<(u32, u32, Vec<u8>)> {
    unsafe {
        // Resolve the target window: use provided hwnd, or fall back to foreground
        let target = if hwnd.0 == 0 {
            GetForegroundWindow()
        } else {
            hwnd
        };

        // Get the monitor that contains the target window
        let hmonitor = MonitorFromWindow(target, MONITOR_DEFAULTTONEAREST);

        let mut mi = MONITORINFO {
            cbSize: std::mem::size_of::<MONITORINFO>() as u32,
            ..Default::default()
        };

        if !GetMonitorInfoW(hmonitor, &mut mi).as_bool() {
            log::error!("GetMonitorInfoW failed, cannot determine monitor rect");
            return None;
        }

        let mon = mi.rcMonitor;
        let width = (mon.right - mon.left) as u32;
        let height = (mon.bottom - mon.top) as u32;
        let src_x = mon.left;
        let src_y = mon.top;

        let hdc_screen = GetDC(HWND(0));
        if hdc_screen.is_invalid() {
            log::error!("Failed to get screen DC");
            return None;
        }

        let hdc_mem = CreateCompatibleDC(hdc_screen);
        if hdc_mem.is_invalid() {
            let _ = ReleaseDC(HWND(0), hdc_screen);
            log::error!("Failed to create compatible DC");
            return None;
        }

        let hbitmap = CreateCompatibleBitmap(hdc_screen, width as i32, height as i32);
        if hbitmap.is_invalid() {
            let _ = DeleteDC(hdc_mem);
            let _ = ReleaseDC(HWND(0), hdc_screen);
            log::error!("Failed to create compatible bitmap");
            return None;
        }

        let old_bitmap = SelectObject(hdc_mem, hbitmap);

        if BitBlt(
            hdc_mem,
            0,
            0,
            width as i32,
            height as i32,
            hdc_screen,
            src_x,
            src_y,
            SRCCOPY,
        )
        .is_err()
        {
            let _ = SelectObject(hdc_mem, old_bitmap);
            let _ = DeleteObject(hbitmap);
            let _ = DeleteDC(hdc_mem);
            let _ = ReleaseDC(HWND(0), hdc_screen);
            log::error!("BitBlt failed");
            return None;
        }

        // Get bitmap data
        let mut bmi = BITMAPINFO {
            bmiHeader: BITMAPINFOHEADER {
                biSize: std::mem::size_of::<BITMAPINFOHEADER>() as u32,
                biWidth: width as i32,
                biHeight: -(height as i32), // Negative for top-down DIB
                biPlanes: 1,
                biBitCount: 24, // 24-bit RGB
                biCompression: BI_RGB.0,
                biSizeImage: 0,
                biXPelsPerMeter: 0,
                biYPelsPerMeter: 0,
                biClrUsed: 0,
                biClrImportant: 0,
            },
            bmiColors: [windows::Win32::Graphics::Gdi::RGBQUAD::default(); 1],
        };

        let pixel_count = (width * height * 3) as usize;
        let mut pixels: Vec<u8> = vec![0; pixel_count];

        if GetDIBits(
            hdc_screen,
            hbitmap,
            0,
            height,
            Some(pixels.as_mut_ptr() as *mut _),
            &mut bmi,
            DIB_RGB_COLORS,
        ) == 0
        {
            let _ = SelectObject(hdc_mem, old_bitmap);
            let _ = DeleteObject(hbitmap);
            let _ = DeleteDC(hdc_mem);
            let _ = ReleaseDC(HWND(0), hdc_screen);
            log::error!("GetDIBits failed");
            return None;
        }

        // Cleanup
        let _ = SelectObject(hdc_mem, old_bitmap);
        let _ = DeleteObject(hbitmap);
        let _ = DeleteDC(hdc_mem);
        let _ = ReleaseDC(HWND(0), hdc_screen);

        Some((width, height, pixels))
    }
}

/// Downscale image if it exceeds max dimensions using simple averaging
fn downscale_if_needed(
    width: u32,
    height: u32,
    pixels: Vec<u8>,
    max_width: u32,
    max_height: u32,
) -> (u32, u32, Vec<u8>) {
    if width <= max_width && height <= max_height {
        return (width, height, pixels);
    }

    // Calculate scale factor
    let scale_w = width as f32 / max_width as f32;
    let scale_h = height as f32 / max_height as f32;
    let scale = scale_w.max(scale_h);

    let new_width = (width as f32 / scale) as u32;
    let new_height = (height as f32 / scale) as u32;

    let mut new_pixels = vec![0u8; (new_width * new_height * 3) as usize];

    for y in 0..new_height {
        for x in 0..new_width {
            let src_x = (x as f32 * scale) as u32;
            let src_y = (y as f32 * scale) as u32;

            let src_idx = ((src_y * width + src_x) * 3) as usize;
            let dst_idx = ((y * new_width + x) * 3) as usize;

            if src_idx + 2 < pixels.len() && dst_idx + 2 < new_pixels.len() {
                new_pixels[dst_idx] = pixels[src_idx];
                new_pixels[dst_idx + 1] = pixels[src_idx + 1];
                new_pixels[dst_idx + 2] = pixels[src_idx + 2];
            }
        }
    }

    (new_width, new_height, new_pixels)
}

/// Encode pixels as JPEG using the jpeg-encoder crate
fn encode_jpeg(pixels: &[u8], width: u32, height: u32, quality: u8) -> Option<Vec<u8>> {
    use jpeg_encoder::{ColorType, Encoder};

    let mut output = Vec::new();
    let encoder = Encoder::new(&mut output, quality);

    // Convert BGR to RGB (Windows bitmap is BGR)
    let mut rgb_pixels = vec![0u8; pixels.len()];
    for i in (0..pixels.len()).step_by(3) {
        rgb_pixels[i] = pixels[i + 2];     // R
        rgb_pixels[i + 1] = pixels[i + 1]; // G
        rgb_pixels[i + 2] = pixels[i];     // B
    }

    encoder
        .encode(&rgb_pixels, width as u16, height as u16, ColorType::Rgb)
        .ok()?;

    Some(output)
}

/// Store JPEG data in ring buffer
fn store_in_buffer(data: Vec<u8>) {
    if let Some(buffer) = SCREENSHOT_BUFFER.get() {
        if let Ok(mut buf) = buffer.lock() {
            if buf.len() >= RING_BUFFER_SIZE {
                buf.pop_front();
            }
            buf.push_back(data);
        }
    }
}

/// Base64 encode the JPEG data
fn base64_encode(data: &[u8]) -> String {
    use base64::{Engine as _, engine::general_purpose::STANDARD};
    STANDARD.encode(data)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_downscale_no_change_needed() {
        let pixels = vec![255u8; 300]; // 10x10 RGB image
        let (new_w, new_h, new_pixels) = downscale_if_needed(10, 10, pixels.clone(), 100, 100);
        assert_eq!(new_w, 10);
        assert_eq!(new_h, 10);
        assert_eq!(new_pixels, pixels);
    }

    #[test]
    fn test_downscale_width_exceeds() {
        let pixels = vec![255u8; 6000]; // 100x20 RGB image
        let (new_w, new_h, _new_pixels) = downscale_if_needed(100, 20, pixels, 50, 100);
        assert_eq!(new_w, 50);
        assert_eq!(new_h, 10);
    }

    #[test]
    fn test_downscale_height_exceeds() {
        let pixels = vec![255u8; 6000]; // 20x100 RGB image
        let (new_w, new_h, _new_pixels) = downscale_if_needed(20, 100, pixels, 100, 50);
        assert_eq!(new_w, 10);
        assert_eq!(new_h, 50);
    }

    #[test]
    fn test_base64_encode() {
        let data = vec![1, 2, 3, 4, 5];
        let encoded = base64_encode(&data);
        assert!(!encoded.is_empty());
        assert!(encoded.chars().all(|c| c.is_ascii()));
    }

    #[test]
    fn test_init_screenshot_buffer() {
        init_screenshot_buffer();
        assert!(SCREENSHOT_BUFFER.get().is_some());
    }

    #[test]
    fn test_store_in_buffer() {
        init_screenshot_buffer();

        // Add items to buffer
        for i in 0..7 {
            store_in_buffer(vec![i; 100]);
        }

        // Check buffer size is limited to RING_BUFFER_SIZE
        if let Some(buffer) = SCREENSHOT_BUFFER.get() {
            if let Ok(buf) = buffer.lock() {
                assert_eq!(buf.len(), RING_BUFFER_SIZE);
            }
        }
    }
}
