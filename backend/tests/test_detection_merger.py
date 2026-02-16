"""Tests for detection_merger: IoU, merging, formatting."""

import pytest
from app.detection_merger import (
    MergedElement,
    compute_iou,
    format_element_list,
    merge_detections_with_uia,
)


class TestComputeIou:
    def test_identical_boxes(self):
        assert compute_iou((10, 10, 50, 50), (10, 10, 50, 50)) == pytest.approx(1.0)

    def test_no_overlap(self):
        assert compute_iou((0, 0, 10, 10), (100, 100, 10, 10)) == 0.0

    def test_partial_overlap(self):
        # Box A: (0,0,20,20) and Box B: (10,10,20,20)
        # Intersection: (10,10) to (20,20) = 10x10 = 100
        # Union: 400 + 400 - 100 = 700
        iou = compute_iou((0, 0, 20, 20), (10, 10, 20, 20))
        assert iou == pytest.approx(100 / 700, abs=1e-4)

    def test_contained_box(self):
        # Small box inside large box
        # Intersection = small box area = 10*10 = 100
        # Union = 100*100 + 100 - 100 = 10000
        iou = compute_iou((0, 0, 100, 100), (45, 45, 10, 10))
        assert iou == pytest.approx(100 / 10000, abs=1e-4)

    def test_zero_area_box(self):
        assert compute_iou((0, 0, 0, 0), (10, 10, 50, 50)) == 0.0
        assert compute_iou((10, 10, 50, 50), (0, 0, 0, 0)) == 0.0

    def test_adjacent_boxes(self):
        # Boxes share an edge but no area overlap
        assert compute_iou((0, 0, 10, 10), (10, 0, 10, 10)) == 0.0


class TestMergeDetectionsWithUia:
    def test_merge_perfect_overlap(self):
        """Detection and UIA at the same location merge into one element."""
        detections = [{"x": 0.1, "y": 0.1, "width": 0.1, "height": 0.05, "confidence": 0.9}]
        uia = [{"name": "OK", "control_type": "Button", "automation_id": "okBtn",
                "bounding_rect": [100, 100, 100, 50]}]
        result = merge_detections_with_uia(detections, uia, 1000, 1000, iou_threshold=0.3)
        assert len(result) == 1
        assert result[0].source == "merged"
        assert result[0].uia_name == "OK"
        assert result[0].confidence == 0.9

    def test_merge_no_overlap(self):
        """Detection and UIA far apart stay separate."""
        detections = [{"x": 0.0, "y": 0.0, "width": 0.05, "height": 0.05, "confidence": 0.8}]
        uia = [{"name": "Cancel", "control_type": "Button", "bounding_rect": [900, 900, 50, 50]}]
        result = merge_detections_with_uia(detections, uia, 1000, 1000, iou_threshold=0.3)
        assert len(result) == 2
        sources = {e.source for e in result}
        assert sources == {"detection", "uia"}

    def test_detection_only_elements(self):
        """Detections with no UIA match return as detection-only."""
        detections = [{"x": 0.5, "y": 0.5, "width": 0.1, "height": 0.1, "confidence": 0.7}]
        result = merge_detections_with_uia(detections, [], 1000, 1000)
        assert len(result) == 1
        assert result[0].source == "detection"
        assert result[0].uia_name == ""

    def test_uia_only_elements(self):
        """UIA elements with no detection match return as uia-only."""
        uia = [{"name": "File", "control_type": "MenuItem", "bounding_rect": [10, 10, 60, 30]}]
        result = merge_detections_with_uia([], uia, 1000, 1000)
        assert len(result) == 1
        assert result[0].source == "uia"
        assert result[0].uia_name == "File"
        assert result[0].confidence == 0.0

    def test_both_empty(self):
        result = merge_detections_with_uia([], [], 1000, 1000)
        assert result == []

    def test_sort_order_top_to_bottom_left_to_right(self):
        """Elements are sorted by y then x."""
        detections = [
            {"x": 0.5, "y": 0.5, "width": 0.05, "height": 0.05, "confidence": 0.8},
            {"x": 0.1, "y": 0.1, "width": 0.05, "height": 0.05, "confidence": 0.8},
            {"x": 0.8, "y": 0.1, "width": 0.05, "height": 0.05, "confidence": 0.8},
        ]
        result = merge_detections_with_uia(detections, [], 1000, 1000)
        ys = [e.bbox[1] for e in result]
        assert ys == sorted(ys)
        # Two elements at y=100: x should be sorted
        top_two = [e for e in result if e.bbox[1] == 100]
        if len(top_two) == 2:
            assert top_two[0].bbox[0] <= top_two[1].bbox[0]

    def test_normalized_to_pixel_conversion(self):
        """Normalized [0,1] coordinates convert to pixel coordinates."""
        detections = [{"x": 0.5, "y": 0.25, "width": 0.1, "height": 0.2, "confidence": 0.9}]
        result = merge_detections_with_uia(detections, [], 1920, 1080)
        assert len(result) == 1
        el = result[0]
        assert el.bbox == (960, 270, 192, 216)

    def test_confidence_threshold_filter(self):
        """Low-confidence detections are excluded."""
        detections = [
            {"x": 0.1, "y": 0.1, "width": 0.1, "height": 0.1, "confidence": 0.1},
            {"x": 0.5, "y": 0.5, "width": 0.1, "height": 0.1, "confidence": 0.9},
        ]
        result = merge_detections_with_uia(
            detections, [], 1000, 1000, confidence_threshold=0.5,
        )
        assert len(result) == 1
        assert result[0].confidence == 0.9

    def test_flatten_nested_uia_tree(self):
        """Nested UIA elements with children are flattened."""
        uia = [{
            "name": "Window",
            "control_type": "Window",
            "bounding_rect": [0, 0, 1000, 1000],
            "children": [
                {"name": "OK", "control_type": "Button", "bounding_rect": [100, 100, 80, 30]},
                {"name": "Cancel", "control_type": "Button", "bounding_rect": [200, 100, 80, 30]},
            ],
        }]
        result = merge_detections_with_uia([], uia, 1000, 1000)
        names = {e.uia_name for e in result}
        assert "Window" in names
        assert "OK" in names
        assert "Cancel" in names

    def test_multiple_detections_match_different_uia(self):
        """Each detection matches at most one UIA element (greedy matching)."""
        detections = [
            {"x": 0.1, "y": 0.1, "width": 0.08, "height": 0.03, "confidence": 0.9},
            {"x": 0.2, "y": 0.1, "width": 0.08, "height": 0.03, "confidence": 0.85},
        ]
        uia = [
            {"name": "OK", "control_type": "Button", "bounding_rect": [100, 100, 80, 30]},
            {"name": "Cancel", "control_type": "Button", "bounding_rect": [200, 100, 80, 30]},
        ]
        result = merge_detections_with_uia(detections, uia, 1000, 1000, iou_threshold=0.3)
        merged_els = [e for e in result if e.source == "merged"]
        names = {e.uia_name for e in merged_els}
        # Each UIA matched to at most one detection
        assert len(names) == len(merged_els)


class TestFormatElementList:
    def test_basic_format(self):
        elements = [
            MergedElement(bbox=(100, 200, 80, 30), confidence=0.9, uia_name="OK",
                          uia_control_type="Button", source="merged"),
        ]
        text = format_element_list(elements)
        assert "[0]" in text
        assert "(140,215)" in text  # center of (100,200,80,30)
        assert "80x30" in text
        assert '"OK"' in text
        assert "(Button)" in text
        assert "conf=0.90" in text
        assert "[merged]" in text

    def test_detection_only_no_uia_fields(self):
        elements = [
            MergedElement(bbox=(50, 50, 40, 20), confidence=0.7, source="detection"),
        ]
        text = format_element_list(elements)
        assert "[0]" in text
        assert "conf=0.70" in text
        assert "[detection]" in text
        # No UIA name/type should appear
        assert '"' not in text or '""' not in text

    def test_empty_list(self):
        assert format_element_list([]) == ""

    def test_automation_id_included(self):
        elements = [
            MergedElement(bbox=(0, 0, 10, 10), confidence=0.5,
                          uia_automation_id="btn_ok", source="uia"),
        ]
        text = format_element_list(elements)
        assert "id=btn_ok" in text
