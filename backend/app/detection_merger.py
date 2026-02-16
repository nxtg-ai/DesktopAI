"""Merge UI-DETR-1 detection bounding boxes with UIA accessibility elements."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List


@dataclass
class MergedElement:
    bbox: tuple[int, int, int, int]  # x, y, w, h in pixels
    confidence: float
    uia_name: str = ""
    uia_control_type: str = ""
    uia_automation_id: str = ""
    source: str = "detection"  # "detection", "uia", "merged"


def compute_iou(
    box_a: tuple[int, int, int, int],
    box_b: tuple[int, int, int, int],
) -> float:
    """Compute Intersection over Union between two (x, y, w, h) boxes."""
    ax, ay, aw, ah = box_a
    bx, by, bw, bh = box_b

    a_area = aw * ah
    b_area = bw * bh
    if a_area <= 0 or b_area <= 0:
        return 0.0

    inter_x1 = max(ax, bx)
    inter_y1 = max(ay, by)
    inter_x2 = min(ax + aw, bx + bw)
    inter_y2 = min(ay + ah, by + bh)

    inter_w = max(0, inter_x2 - inter_x1)
    inter_h = max(0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h

    union_area = a_area + b_area - inter_area
    if union_area <= 0:
        return 0.0

    return inter_area / union_area


def _flatten_uia_tree(elements: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Flatten a nested UIA tree into a list of elements with bounding_rect."""
    flat: List[Dict[str, Any]] = []
    for el in elements:
        if el.get("bounding_rect"):
            flat.append(el)
        for child in el.get("children", []):
            flat.extend(_flatten_uia_tree([child]))
    return flat


def merge_detections_with_uia(
    detections: List[Dict[str, Any]],
    uia_elements: List[Dict[str, Any]],
    image_width: int,
    image_height: int,
    iou_threshold: float = 0.3,
    confidence_threshold: float = 0.0,
) -> List[MergedElement]:
    """Merge detector bounding boxes with UIA accessibility elements.

    Args:
        detections: List of dicts with {x, y, width, height, confidence}
                    where coordinates are normalized [0,1].
        uia_elements: Flattened or nested UIA tree elements.
        image_width: Screenshot width in pixels.
        image_height: Screenshot height in pixels.
        iou_threshold: Minimum IoU to consider a match.
        confidence_threshold: Minimum confidence to keep a detection.

    Returns:
        Sorted list of MergedElement (top-to-bottom, left-to-right).
    """
    # Convert normalized detection boxes to pixel coordinates
    det_boxes: List[tuple[int, int, int, int]] = []
    det_confs: List[float] = []
    for d in detections:
        conf = d.get("confidence", 0.0)
        if conf < confidence_threshold:
            continue
        px = int(d["x"] * image_width)
        py = int(d["y"] * image_height)
        pw = int(d["width"] * image_width)
        ph = int(d["height"] * image_height)
        det_boxes.append((px, py, pw, ph))
        det_confs.append(conf)

    # Flatten UIA tree
    flat_uia = _flatten_uia_tree(uia_elements)
    uia_boxes: List[tuple[int, int, int, int]] = []
    uia_data: List[Dict[str, Any]] = []
    for el in flat_uia:
        rect = el.get("bounding_rect")
        if rect and len(rect) >= 4:
            uia_boxes.append((rect[0], rect[1], rect[2], rect[3]))
            uia_data.append(el)

    matched_uia: set[int] = set()
    merged: List[MergedElement] = []

    # Match each detection to best UIA element by IoU
    for i, (dbox, conf) in enumerate(zip(det_boxes, det_confs)):
        best_iou = 0.0
        best_j = -1
        for j, ubox in enumerate(uia_boxes):
            if j in matched_uia:
                continue
            score = compute_iou(dbox, ubox)
            if score > best_iou:
                best_iou = score
                best_j = j

        if best_iou >= iou_threshold and best_j >= 0:
            matched_uia.add(best_j)
            el = uia_data[best_j]
            merged.append(MergedElement(
                bbox=dbox,
                confidence=conf,
                uia_name=el.get("name", ""),
                uia_control_type=el.get("control_type", ""),
                uia_automation_id=el.get("automation_id", ""),
                source="merged",
            ))
        else:
            merged.append(MergedElement(
                bbox=dbox,
                confidence=conf,
                source="detection",
            ))

    # Add unmatched UIA elements
    for j, (ubox, el) in enumerate(zip(uia_boxes, uia_data)):
        if j not in matched_uia:
            merged.append(MergedElement(
                bbox=ubox,
                confidence=0.0,
                uia_name=el.get("name", ""),
                uia_control_type=el.get("control_type", ""),
                uia_automation_id=el.get("automation_id", ""),
                source="uia",
            ))

    # Sort top-to-bottom, left-to-right
    merged.sort(key=lambda e: (e.bbox[1], e.bbox[0]))
    return merged


def format_element_list(elements: List[MergedElement]) -> str:
    """Format merged elements as a numbered text list for the LLM prompt."""
    lines: List[str] = []
    for i, el in enumerate(elements):
        x, y, w, h = el.bbox
        cx, cy = x + w // 2, y + h // 2
        parts = [f"[{i}] ({cx},{cy}) {w}x{h}"]
        if el.uia_name:
            parts.append(f'"{el.uia_name}"')
        if el.uia_control_type:
            parts.append(f"({el.uia_control_type})")
        if el.uia_automation_id:
            parts.append(f"id={el.uia_automation_id}")
        parts.append(f"conf={el.confidence:.2f}")
        parts.append(f"[{el.source}]")
        lines.append(" ".join(parts))
    return "\n".join(lines)
