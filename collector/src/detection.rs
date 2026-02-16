//! UI element detection using ONNX Runtime (UI-DETR-1 model).
//!
//! Runs a class-agnostic object detector to find interactive UI elements
//! (buttons, fields, links, menus) in screenshots. Results are sent to the
//! Python backend where they are merged with UIA accessibility data and
//! fed to a text-only LLM for reasoning — replacing the slow VLM path.

use ndarray::Array4;
use serde::Serialize;
use std::path::Path;
use std::time::Instant;

use ort::session::Session;

/// A single detected UI element with normalized coordinates.
#[derive(Debug, Clone, Serialize)]
pub struct Detection {
    /// Top-left x (normalized 0..1)
    pub x: f32,
    /// Top-left y (normalized 0..1)
    pub y: f32,
    /// Width (normalized 0..1)
    pub width: f32,
    /// Height (normalized 0..1)
    pub height: f32,
    /// Detection confidence (0..1)
    pub confidence: f32,
}

/// ONNX-based UI element detector. Holds a loaded model session.
pub struct Detector {
    session: Session,
    confidence_threshold: f32,
    input_size: u32,
}

impl Detector {
    /// Load the ONNX model from disk. Returns `None` if the file doesn't exist.
    pub fn new(model_path: &str, confidence_threshold: f32, input_size: u32) -> Option<Self> {
        if !Path::new(model_path).exists() {
            log::info!("Detection model not found at {model_path}, detection disabled");
            return None;
        }

        match Session::builder()
            .and_then(|b| b.with_intra_threads(2))
            .and_then(|b| b.commit_from_file(model_path))
        {
            Ok(session) => {
                log::info!("Loaded detection model from {model_path} (input_size={input_size})");
                Some(Self {
                    session,
                    confidence_threshold,
                    input_size,
                })
            }
            Err(e) => {
                log::warn!("Failed to load detection model: {e}");
                None
            }
        }
    }

    /// Run detection on raw pixel data (BGR or BGRA).
    ///
    /// `channels` is the bytes-per-pixel (3 for 24-bit BGR, 4 for 32-bit BGRA).
    /// Returns a list of detected UI elements with normalized coordinates.
    pub fn detect(&self, pixels: &[u8], width: u32, height: u32, channels: usize) -> Vec<Detection> {
        let start = Instant::now();

        let input = preprocess(pixels, width, height, channels, self.input_size);

        let outputs = match self.session.run(ort::inputs![input.view()].unwrap()) {
            Ok(o) => o,
            Err(e) => {
                log::warn!("Detection inference failed: {e}");
                return Vec::new();
            }
        };

        // RF-DETR / DETR-style output: boxes [1, N, 4] + scores [1, N]
        // Boxes are in CXCYWH format normalized to input size.
        let (boxes_raw, scores_raw) = match extract_outputs(&outputs) {
            Some(pair) => pair,
            None => {
                log::warn!("Could not extract detection outputs");
                return Vec::new();
            }
        };

        let detections = postprocess(&boxes_raw, &scores_raw, self.confidence_threshold, self.input_size);
        let elapsed_ms = start.elapsed().as_millis();
        log::info!("Detection: {} elements in {}ms (input_size={})", detections.len(), elapsed_ms, self.input_size);
        detections
    }
}

/// Extract boxes and scores arrays from model outputs.
/// Handles common DETR output formats.
fn extract_outputs(
    outputs: &ort::session::output::SessionOutputs,
) -> Option<(Vec<[f32; 4]>, Vec<f32>)> {
    if outputs.len() < 2 {
        return None;
    }

    // Access by index (output 0 = boxes, output 1 = scores)
    let boxes_view = outputs[0].try_extract_tensor::<f32>().ok()?;
    let scores_view = outputs[1].try_extract_tensor::<f32>().ok()?;

    let boxes_shape = boxes_view.shape();
    let scores_shape = scores_view.shape();

    if boxes_shape.len() < 2 || scores_shape.is_empty() {
        return None;
    }

    // Number of detections
    let n = if boxes_shape.len() == 3 {
        boxes_shape[1]
    } else {
        boxes_shape[0]
    };

    let boxes_flat = boxes_view.as_slice()?;
    let scores_flat = scores_view.as_slice()?;

    // Determine score count per detection (class-agnostic = 1, or multi-class)
    let scores_per_det = if scores_shape.len() == 3 {
        scores_shape[2]
    } else if scores_shape.len() == 2 {
        scores_shape[1]
    } else {
        1
    };

    let mut boxes = Vec::with_capacity(n);
    let mut scores = Vec::with_capacity(n);

    for i in 0..n {
        let box_offset = i * 4;
        if box_offset + 3 >= boxes_flat.len() {
            break;
        }
        boxes.push([
            boxes_flat[box_offset],
            boxes_flat[box_offset + 1],
            boxes_flat[box_offset + 2],
            boxes_flat[box_offset + 3],
        ]);

        // Take max score across classes
        let score_offset = i * scores_per_det;
        let max_score = scores_flat[score_offset..score_offset + scores_per_det]
            .iter()
            .cloned()
            .fold(f32::NEG_INFINITY, f32::max);
        scores.push(max_score);
    }

    Some((boxes, scores))
}

/// Preprocess BGR screenshot pixels to an NxN RGB float tensor [1, 3, N, N].
///
/// `channels` is the number of bytes per pixel (3 for BGR, 4 for BGRA).
/// `target_size` is the model's expected input resolution (e.g. 576 for RF-DETR-M).
/// Windows `GetDIBits` with `biBitCount=24` produces 3-channel BGR.
pub fn preprocess(pixels: &[u8], width: u32, height: u32, channels: usize, target_size: u32) -> Array4<f32> {
    let target = target_size as usize;
    let mut tensor = Array4::<f32>::zeros((1, 3, target, target));

    let w = width as usize;
    let h = height as usize;
    let scale_x = w as f32 / target as f32;
    let scale_y = h as f32 / target as f32;

    for ty in 0..target {
        for tx in 0..target {
            // Nearest-neighbor sampling for speed
            let sx = ((tx as f32 * scale_x) as usize).min(w.saturating_sub(1));
            let sy = ((ty as f32 * scale_y) as usize).min(h.saturating_sub(1));
            let idx = (sy * w + sx) * channels;

            if idx + 2 < pixels.len() {
                let b = pixels[idx] as f32 / 255.0;
                let g = pixels[idx + 1] as f32 / 255.0;
                let r = pixels[idx + 2] as f32 / 255.0;
                tensor[[0, 0, ty, tx]] = r;
                tensor[[0, 1, ty, tx]] = g;
                tensor[[0, 2, ty, tx]] = b;
            }
        }
    }

    tensor
}

/// Postprocess model output: filter by confidence, convert CXCYWH to XYWH, apply NMS.
/// Returns detections with normalized [0,1] coordinates.
pub fn postprocess(
    boxes: &[[f32; 4]],
    scores: &[f32],
    confidence_threshold: f32,
    input_size: u32,
) -> Vec<Detection> {
    let input_size = input_size as f32;

    // Filter by confidence and convert CXCYWH → normalized XYWH
    let mut candidates: Vec<Detection> = boxes
        .iter()
        .zip(scores.iter())
        .filter(|(_, &score)| score >= confidence_threshold)
        .map(|(bbox, &score)| {
            let cx = bbox[0] / input_size;
            let cy = bbox[1] / input_size;
            let w = bbox[2] / input_size;
            let h = bbox[3] / input_size;
            Detection {
                x: (cx - w / 2.0).max(0.0),
                y: (cy - h / 2.0).max(0.0),
                width: w.min(1.0),
                height: h.min(1.0),
                confidence: score,
            }
        })
        .collect();

    // Sort by confidence descending for NMS
    candidates.sort_by(|a, b| b.confidence.partial_cmp(&a.confidence).unwrap_or(std::cmp::Ordering::Equal));

    nms(&candidates, 0.5)
}

/// Non-maximum suppression: remove overlapping detections.
pub fn nms(detections: &[Detection], iou_threshold: f32) -> Vec<Detection> {
    let mut keep = Vec::new();
    let mut suppressed = vec![false; detections.len()];

    for i in 0..detections.len() {
        if suppressed[i] {
            continue;
        }
        keep.push(detections[i].clone());

        for j in (i + 1)..detections.len() {
            if suppressed[j] {
                continue;
            }
            if iou(&detections[i], &detections[j]) > iou_threshold {
                suppressed[j] = true;
            }
        }
    }

    keep
}

/// Compute Intersection over Union between two detections.
pub fn iou(a: &Detection, b: &Detection) -> f32 {
    let a_x2 = a.x + a.width;
    let a_y2 = a.y + a.height;
    let b_x2 = b.x + b.width;
    let b_y2 = b.y + b.height;

    let inter_x1 = a.x.max(b.x);
    let inter_y1 = a.y.max(b.y);
    let inter_x2 = a_x2.min(b_x2);
    let inter_y2 = a_y2.min(b_y2);

    let inter_w = (inter_x2 - inter_x1).max(0.0);
    let inter_h = (inter_y2 - inter_y1).max(0.0);
    let inter_area = inter_w * inter_h;

    let a_area = a.width * a.height;
    let b_area = b.width * b.height;
    let union_area = a_area + b_area - inter_area;

    if union_area <= 0.0 {
        return 0.0;
    }

    inter_area / union_area
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_preprocess_dimensions() {
        // 4x3 BGR image (3 channels, matching Windows GetDIBits output)
        let pixels = vec![128u8; 4 * 3 * 3]; // 4w * 3h * 3 channels
        let tensor = preprocess(&pixels, 4, 3, 3, 576);
        assert_eq!(tensor.shape(), &[1, 3, 576, 576]);
    }

    #[test]
    fn test_preprocess_pixel_values() {
        // Single white pixel (BGR: 255,255,255)
        let pixels = vec![255u8; 3];
        let tensor = preprocess(&pixels, 1, 1, 3, 576);
        // All tensor values should be ~1.0 (white)
        assert!((tensor[[0, 0, 0, 0]] - 1.0).abs() < 0.01);
        assert!((tensor[[0, 1, 0, 0]] - 1.0).abs() < 0.01);
        assert!((tensor[[0, 2, 0, 0]] - 1.0).abs() < 0.01);
    }

    #[test]
    fn test_preprocess_bgr_to_rgb_order() {
        // B=100, G=150, R=200 (3-channel BGR)
        let pixels = vec![100, 150, 200];
        let tensor = preprocess(&pixels, 1, 1, 3, 576);
        // Channel 0 = R, Channel 1 = G, Channel 2 = B
        assert!((tensor[[0, 0, 0, 0]] - 200.0 / 255.0).abs() < 0.01);
        assert!((tensor[[0, 1, 0, 0]] - 150.0 / 255.0).abs() < 0.01);
        assert!((tensor[[0, 2, 0, 0]] - 100.0 / 255.0).abs() < 0.01);
    }

    #[test]
    fn test_preprocess_bgra_4channel() {
        // B=100, G=150, R=200, A=255 (4-channel BGRA)
        let pixels = vec![100, 150, 200, 255];
        let tensor = preprocess(&pixels, 1, 1, 4, 576);
        assert!((tensor[[0, 0, 0, 0]] - 200.0 / 255.0).abs() < 0.01);
        assert!((tensor[[0, 1, 0, 0]] - 150.0 / 255.0).abs() < 0.01);
        assert!((tensor[[0, 2, 0, 0]] - 100.0 / 255.0).abs() < 0.01);
    }

    #[test]
    fn test_preprocess_custom_size() {
        // Verify that a non-default size (640) produces the correct tensor shape
        let pixels = vec![128u8; 4 * 3 * 3]; // 4w * 3h * 3 channels
        let tensor = preprocess(&pixels, 4, 3, 3, 640);
        assert_eq!(tensor.shape(), &[1, 3, 640, 640]);
    }

    #[test]
    fn test_nms_removes_overlapping() {
        let dets = vec![
            Detection { x: 0.1, y: 0.1, width: 0.3, height: 0.3, confidence: 0.9 },
            Detection { x: 0.12, y: 0.12, width: 0.3, height: 0.3, confidence: 0.7 }, // ~overlapping
            Detection { x: 0.7, y: 0.7, width: 0.2, height: 0.2, confidence: 0.8 },  // far away
        ];
        let kept = nms(&dets, 0.5);
        assert_eq!(kept.len(), 2);
        assert!((kept[0].confidence - 0.9).abs() < f32::EPSILON);
        assert!((kept[1].confidence - 0.8).abs() < f32::EPSILON);
    }

    #[test]
    fn test_nms_no_overlap() {
        let dets = vec![
            Detection { x: 0.0, y: 0.0, width: 0.1, height: 0.1, confidence: 0.9 },
            Detection { x: 0.5, y: 0.5, width: 0.1, height: 0.1, confidence: 0.8 },
        ];
        let kept = nms(&dets, 0.5);
        assert_eq!(kept.len(), 2);
    }

    #[test]
    fn test_confidence_filter() {
        let boxes = vec![
            [288.0, 288.0, 100.0, 100.0], // center of 576x576
            [100.0, 100.0, 50.0, 50.0],
        ];
        let scores = vec![0.8, 0.1]; // second below threshold

        let dets = postprocess(&boxes, &scores, 0.3, 576);
        assert_eq!(dets.len(), 1);
        assert!((dets[0].confidence - 0.8).abs() < f32::EPSILON);
    }

    #[test]
    fn test_confidence_filter_640() {
        // Verify postprocess works with 640 input size too
        let boxes = vec![[320.0, 320.0, 100.0, 100.0]];
        let scores = vec![0.8];
        let dets = postprocess(&boxes, &scores, 0.3, 640);
        assert_eq!(dets.len(), 1);
    }

    #[test]
    fn test_detection_empty_input() {
        let dets = postprocess(&[], &[], 0.3, 576);
        assert!(dets.is_empty());
    }

    #[test]
    fn test_detection_serde() {
        let det = Detection {
            x: 0.1,
            y: 0.2,
            width: 0.3,
            height: 0.4,
            confidence: 0.95,
        };
        let json = serde_json::to_string(&det).unwrap();
        assert!(json.contains("\"x\":0.1"));
        assert!(json.contains("\"confidence\":0.95"));
    }

    #[test]
    fn test_iou_identical() {
        let a = Detection { x: 0.1, y: 0.1, width: 0.3, height: 0.3, confidence: 0.9 };
        assert!((iou(&a, &a) - 1.0).abs() < f32::EPSILON);
    }

    #[test]
    fn test_iou_no_overlap() {
        let a = Detection { x: 0.0, y: 0.0, width: 0.1, height: 0.1, confidence: 0.9 };
        let b = Detection { x: 0.5, y: 0.5, width: 0.1, height: 0.1, confidence: 0.8 };
        assert!((iou(&a, &b)).abs() < f32::EPSILON);
    }

    #[test]
    fn test_iou_contained() {
        // b fully inside a
        let a = Detection { x: 0.0, y: 0.0, width: 1.0, height: 1.0, confidence: 0.9 };
        let b = Detection { x: 0.2, y: 0.2, width: 0.1, height: 0.1, confidence: 0.8 };
        let result = iou(&a, &b);
        // IoU = area(b) / area(a) = 0.01 / 1.0 = 0.01
        assert!((result - 0.01).abs() < 0.001);
    }

    #[test]
    fn test_iou_zero_area() {
        let a = Detection { x: 0.5, y: 0.5, width: 0.0, height: 0.0, confidence: 0.9 };
        let b = Detection { x: 0.5, y: 0.5, width: 0.1, height: 0.1, confidence: 0.8 };
        assert_eq!(iou(&a, &b), 0.0);
    }

    #[test]
    fn test_postprocess_cxcywh_conversion() {
        // Center at (288,288) with size (576,576) should yield x=0, y=0, w=1, h=1
        let boxes = vec![[288.0, 288.0, 576.0, 576.0]];
        let scores = vec![0.9];
        let dets = postprocess(&boxes, &scores, 0.3, 576);
        assert_eq!(dets.len(), 1);
        assert!((dets[0].x).abs() < 0.01);
        assert!((dets[0].y).abs() < 0.01);
        assert!((dets[0].width - 1.0).abs() < 0.01);
        assert!((dets[0].height - 1.0).abs() < 0.01);
    }
}
