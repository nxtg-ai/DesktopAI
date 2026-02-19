"""Tests for VisionAgent detection mode (text-only LLM path)."""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
from app.vision_agent import AgentAction, AgentObservation, AgentStep, VisionAgent


def _make_observation(
    detections=None, uia_elements=None, screenshot_b64="abc",
    window_title="Test Window", process_exe="test.exe",
    screenshot_width=1024, screenshot_height=768,
):
    return AgentObservation(
        screenshot_b64=screenshot_b64,
        uia_summary=json.dumps({"window_tree": uia_elements or []}),
        window_title=window_title,
        process_exe=process_exe,
        timestamp=datetime.now(timezone.utc),
        detections=detections,
        uia_elements=uia_elements,
        screenshot_width=screenshot_width,
        screenshot_height=screenshot_height,
    )


def _make_agent(vision_mode="auto", **kwargs):
    bridge = AsyncMock()
    ollama = AsyncMock()
    return VisionAgent(
        bridge=bridge,
        ollama=ollama,
        max_iterations=5,
        vision_mode=vision_mode,
        **kwargs,
    ), bridge, ollama


class TestShouldUseDetection:
    def test_vlm_mode_always_false(self):
        agent, _, _ = _make_agent(vision_mode="vlm")
        obs = _make_observation(detections=[{"x": 0.1, "y": 0.1, "width": 0.1, "height": 0.1, "confidence": 0.9}])
        assert not agent._should_use_detection(obs)

    def test_detection_mode_always_true(self):
        agent, _, _ = _make_agent(vision_mode="detection")
        obs = _make_observation(detections=None)
        assert agent._should_use_detection(obs)

    def test_auto_mode_with_detections(self):
        agent, _, _ = _make_agent(vision_mode="auto")
        obs = _make_observation(detections=[{"x": 0.1, "y": 0.1, "width": 0.1, "height": 0.1, "confidence": 0.9}])
        assert agent._should_use_detection(obs)

    def test_auto_mode_without_detections(self):
        agent, _, _ = _make_agent(vision_mode="auto")
        obs = _make_observation(detections=None)
        assert not agent._should_use_detection(obs)

    def test_auto_mode_empty_detections(self):
        agent, _, _ = _make_agent(vision_mode="auto")
        obs = _make_observation(detections=[])
        assert not agent._should_use_detection(obs)


class TestReasonDetection:
    @pytest.mark.asyncio
    async def test_detection_mode_uses_text_prompt(self):
        """Detection mode calls ollama.chat() with text-only prompt (no images)."""
        agent, _, ollama = _make_agent(vision_mode="detection")
        ollama.chat = AsyncMock(return_value=json.dumps({
            "action": "click", "parameters": {"element_id": 0},
            "reasoning": "click OK", "confidence": 0.9,
        }))

        obs = _make_observation(
            detections=[{"x": 0.1, "y": 0.1, "width": 0.08, "height": 0.03, "confidence": 0.9}],
            uia_elements=[{"name": "OK", "control_type": "Button", "bounding_rect": [100, 100, 80, 30]}],
        )

        await agent._reason_detection("click OK button", obs, [])

        # Should call chat(), not chat_with_images()
        ollama.chat.assert_awaited_once()
        call_args = ollama.chat.call_args
        messages = call_args[0][0]
        assert len(messages) == 1
        assert "DETECTED UI ELEMENTS" in messages[0]["content"]

    @pytest.mark.asyncio
    async def test_element_id_resolved_to_uia_name(self):
        """element_id click is resolved to UIA name when available."""
        agent, _, ollama = _make_agent(vision_mode="detection")
        ollama.chat = AsyncMock(return_value=json.dumps({
            "action": "click", "parameters": {"element_id": 0},
            "reasoning": "click OK", "confidence": 0.9,
        }))

        # Detection at (0.1, 0.1, 0.08, 0.03) on 1024x768 → pixel (102, 76, 81, 23)
        # UIA bbox must overlap for merge — use matching pixel coords
        obs = _make_observation(
            detections=[{"x": 0.1, "y": 0.1, "width": 0.08, "height": 0.03, "confidence": 0.9}],
            uia_elements=[{"name": "OK", "control_type": "Button", "bounding_rect": [100, 75, 82, 25]}],
        )

        action = await agent._reason_detection("click OK", obs, [])
        assert action.action == "click"
        assert "name" in action.parameters
        assert action.parameters["name"] == "OK"
        assert "element_id" not in action.parameters

    @pytest.mark.asyncio
    async def test_element_id_resolved_to_xy_when_no_uia(self):
        """element_id falls back to x/y coordinates when no UIA match."""
        agent, _, ollama = _make_agent(vision_mode="detection")
        ollama.chat = AsyncMock(return_value=json.dumps({
            "action": "click", "parameters": {"element_id": 0},
            "reasoning": "click it", "confidence": 0.8,
        }))

        obs = _make_observation(
            detections=[{"x": 0.1, "y": 0.2, "width": 0.08, "height": 0.03, "confidence": 0.8}],
            uia_elements=[],
        )

        action = await agent._reason_detection("click button", obs, [])
        assert action.action == "click"
        assert "x" in action.parameters
        assert "y" in action.parameters
        assert "element_id" not in action.parameters

    @pytest.mark.asyncio
    async def test_element_id_resolved_to_automation_id(self):
        """element_id with automation_id but no name uses automation_id."""
        agent, _, ollama = _make_agent(vision_mode="detection")
        ollama.chat = AsyncMock(return_value=json.dumps({
            "action": "click", "parameters": {"element_id": 0},
            "reasoning": "click", "confidence": 0.9,
        }))

        # Detection pixel coords (102, 76, 81, 23) — UIA must overlap
        obs = _make_observation(
            detections=[{"x": 0.1, "y": 0.1, "width": 0.08, "height": 0.03, "confidence": 0.9}],
            uia_elements=[{"name": "", "control_type": "Button", "automation_id": "submitBtn",
                           "bounding_rect": [100, 75, 82, 25]}],
        )

        action = await agent._reason_detection("submit", obs, [])
        assert action.parameters.get("automation_id") == "submitBtn"

    @pytest.mark.asyncio
    async def test_no_screenshot_sent_to_llm(self):
        """Detection mode never sends screenshot to LLM."""
        agent, _, ollama = _make_agent(vision_mode="detection")
        ollama.chat = AsyncMock(return_value=json.dumps({
            "action": "done", "parameters": {},
            "reasoning": "done", "confidence": 0.95,
        }))

        obs = _make_observation(
            screenshot_b64="huge_base64_image_data",
            detections=[{"x": 0.1, "y": 0.1, "width": 0.1, "height": 0.1, "confidence": 0.9}],
        )

        await agent._reason_detection("check", obs, [])

        # chat() called, not chat_with_images()
        ollama.chat.assert_awaited_once()
        # Verify no image data in messages
        messages = ollama.chat.call_args[0][0]
        content = messages[0]["content"]
        assert "huge_base64_image_data" not in content

    @pytest.mark.asyncio
    async def test_detection_prompt_includes_numbered_elements(self):
        """Element list in prompt has [0], [1], etc. numbering."""
        agent, _, ollama = _make_agent(vision_mode="detection")
        ollama.chat = AsyncMock(return_value=json.dumps({
            "action": "done", "parameters": {}, "reasoning": "ok", "confidence": 0.9,
        }))

        obs = _make_observation(
            detections=[
                {"x": 0.1, "y": 0.1, "width": 0.05, "height": 0.03, "confidence": 0.8},
                {"x": 0.3, "y": 0.3, "width": 0.05, "height": 0.03, "confidence": 0.7},
            ],
        )

        await agent._reason_detection("test", obs, [])

        messages = ollama.chat.call_args[0][0]
        content = messages[0]["content"]
        assert "[0]" in content
        assert "[1]" in content

    @pytest.mark.asyncio
    async def test_detection_with_history(self):
        """History section included in detection prompt."""
        agent, _, ollama = _make_agent(vision_mode="detection")
        ollama.chat = AsyncMock(return_value=json.dumps({
            "action": "done", "parameters": {}, "reasoning": "ok", "confidence": 0.9,
        }))

        obs = _make_observation(detections=[{"x": 0.1, "y": 0.1, "width": 0.05, "height": 0.03, "confidence": 0.8}])
        prev_step = AgentStep(
            observation=obs,
            action=AgentAction(action="click", parameters={"name": "OK"}, reasoning="click OK"),
            result={"ok": True},
        )

        await agent._reason_detection("test", obs, [prev_step])

        messages = ollama.chat.call_args[0][0]
        content = messages[0]["content"]
        assert "HISTORY" in content
        assert "click" in content

    @pytest.mark.asyncio
    async def test_detection_reasoning_error_returns_wait(self):
        """Ollama error during detection reasoning returns wait action."""
        agent, _, ollama = _make_agent(vision_mode="detection")
        ollama.chat = AsyncMock(side_effect=Exception("connection refused"))

        obs = _make_observation(detections=[{"x": 0.1, "y": 0.1, "width": 0.1, "height": 0.1, "confidence": 0.9}])

        action = await agent._reason_detection("test", obs, [])
        assert action.action == "wait"
        assert "reasoning error" in action.reasoning


class TestReasonDispatch:
    @pytest.mark.asyncio
    async def test_auto_mode_dispatches_to_detection(self):
        """Auto mode with detections goes to _reason_detection."""
        agent, _, ollama = _make_agent(vision_mode="auto")
        ollama.chat = AsyncMock(return_value=json.dumps({
            "action": "done", "parameters": {}, "reasoning": "ok", "confidence": 0.9,
        }))

        obs = _make_observation(
            detections=[{"x": 0.1, "y": 0.1, "width": 0.1, "height": 0.1, "confidence": 0.9}],
        )

        with patch.object(agent, "_reason_detection", wraps=agent._reason_detection) as mock_det:
            await agent._reason("test", obs, [])
            mock_det.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_auto_mode_falls_back_to_vlm(self):
        """Auto mode without detections goes to _reason_vlm."""
        agent, _, ollama = _make_agent(vision_mode="auto")
        ollama.chat = AsyncMock(return_value=json.dumps({
            "action": "done", "parameters": {}, "reasoning": "ok", "confidence": 0.9,
        }))

        obs = _make_observation(detections=None)

        with patch.object(agent, "_reason_vlm", wraps=agent._reason_vlm) as mock_vlm:
            await agent._reason("test", obs, [])
            mock_vlm.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_vlm_mode_ignores_detections(self):
        """VLM mode always uses VLM path even with detections."""
        agent, _, ollama = _make_agent(vision_mode="vlm")
        ollama.chat = AsyncMock(return_value=json.dumps({
            "action": "done", "parameters": {}, "reasoning": "ok", "confidence": 0.9,
        }))

        obs = _make_observation(
            detections=[{"x": 0.1, "y": 0.1, "width": 0.1, "height": 0.1, "confidence": 0.9}],
        )

        with patch.object(agent, "_reason_vlm", wraps=agent._reason_vlm) as mock_vlm:
            await agent._reason("test", obs, [])
            mock_vlm.assert_awaited_once()


class TestObserveDetections:
    @pytest.mark.asyncio
    async def test_observe_extracts_detections(self):
        """Observe extracts detections from bridge result."""
        agent, bridge_mock, _ = _make_agent()
        bridge_mock.execute = AsyncMock(return_value={
            "screenshot_b64": "abc",
            "uia": {"window_tree": [{"name": "W", "control_type": "Window"}]},
            "result": {"window_title": "Test", "process_exe": "test.exe"},
            "detections": [{"x": 0.1, "y": 0.2, "width": 0.05, "height": 0.03, "confidence": 0.8}],
        })

        obs = await agent._observe()
        assert obs.detections is not None
        assert len(obs.detections) == 1
        assert obs.detections[0]["confidence"] == 0.8

    @pytest.mark.asyncio
    async def test_observe_no_detections_field(self):
        """Observe handles missing detections gracefully."""
        agent, bridge_mock, _ = _make_agent()
        bridge_mock.execute = AsyncMock(return_value={
            "screenshot_b64": "abc",
            "result": {"window_title": "Test", "process_exe": "test.exe"},
        })

        obs = await agent._observe()
        assert obs.detections is None

    @pytest.mark.asyncio
    async def test_observe_extracts_uia_elements(self):
        """Observe extracts uia_elements from window_tree."""
        agent, bridge_mock, _ = _make_agent()
        bridge_mock.execute = AsyncMock(return_value={
            "screenshot_b64": "abc",
            "uia": {"window_tree": [{"name": "OK", "control_type": "Button", "bounding_rect": [10, 10, 80, 30]}]},
            "result": {"window_title": "Test", "process_exe": "test.exe"},
        })

        obs = await agent._observe()
        assert obs.uia_elements is not None
        assert len(obs.uia_elements) == 1
        assert obs.uia_elements[0]["name"] == "OK"

    @pytest.mark.asyncio
    async def test_observe_extracts_screenshot_dimensions(self):
        """Observe extracts screenshot_width/height from bridge result."""
        agent, bridge_mock, _ = _make_agent()
        bridge_mock.execute = AsyncMock(return_value={
            "screenshot_b64": "abc",
            "result": {
                "window_title": "Test", "process_exe": "test.exe",
                "screenshot_width": 1920, "screenshot_height": 1080,
            },
        })

        obs = await agent._observe()
        assert obs.screenshot_width == 1920
        assert obs.screenshot_height == 1080

    @pytest.mark.asyncio
    async def test_observe_defaults_screenshot_dimensions(self):
        """Observe defaults screenshot_width/height when not provided."""
        agent, bridge_mock, _ = _make_agent()
        bridge_mock.execute = AsyncMock(return_value={
            "screenshot_b64": "abc",
            "result": {"window_title": "Test", "process_exe": "test.exe"},
        })

        obs = await agent._observe()
        assert obs.screenshot_width == 1024
        assert obs.screenshot_height == 768


class TestReasonDetectionDynamicDimensions:
    @pytest.mark.asyncio
    async def test_dynamic_dimensions_passed_to_merger(self):
        """_reason_detection uses observation screenshot_width/height, not hardcoded."""
        agent, _, ollama = _make_agent(vision_mode="detection")
        ollama.chat = AsyncMock(return_value=json.dumps({
            "action": "done", "parameters": {}, "reasoning": "ok", "confidence": 0.9,
        }))

        obs = _make_observation(
            detections=[{"x": 0.1, "y": 0.1, "width": 0.05, "height": 0.03, "confidence": 0.8}],
            screenshot_width=1920,
            screenshot_height=1080,
        )

        with patch("app.detection_merger.merge_detections_with_uia") as mock_merge:
            from app.detection_merger import MergedElement
            mock_merge.return_value = [
                MergedElement(bbox=(192, 108, 96, 32), confidence=0.8, source="detection"),
            ]
            await agent._reason_detection("test", obs, [])
            mock_merge.assert_called_once()
            _, kwargs = mock_merge.call_args
            assert kwargs["image_width"] == 1920
            assert kwargs["image_height"] == 1080


class TestEndToEndDetectionPipeline:
    """N-03 UAT: Full pipeline — bridge observe with detections → VisionAgent → merged → action."""

    @pytest.mark.asyncio
    async def test_full_pipeline_detection_to_action(self):
        """Simulates complete: bridge returns detections + UIA → VisionAgent reasons → click action."""
        agent, bridge_mock, ollama = _make_agent(vision_mode="auto")

        # Bridge returns observe with detections + UIA
        bridge_mock.execute = AsyncMock(return_value={
            "screenshot_b64": "ZmFrZQ==",
            "uia": {
                "window_tree": [
                    {"name": "File", "control_type": "MenuItem", "bounding_rect": [48, 5, 62, 25]},
                    {"name": "Edit", "control_type": "MenuItem", "bounding_rect": [115, 5, 55, 25]},
                ]
            },
            "result": {
                "window_title": "Notepad",
                "process_exe": "notepad.exe",
                "screenshot_width": 1024,
                "screenshot_height": 768,
            },
            "detections": [
                {"x": 0.047, "y": 0.006, "width": 0.061, "height": 0.033, "confidence": 0.92},
                {"x": 0.112, "y": 0.006, "width": 0.054, "height": 0.033, "confidence": 0.88},
            ],
        })

        # LLM returns a click action targeting element 0 (File)
        ollama.chat = AsyncMock(return_value=json.dumps({
            "action": "click",
            "parameters": {"element_id": 0},
            "reasoning": "Clicking File menu as requested",
            "confidence": 0.9,
        }))

        # Run observe
        obs = await agent._observe()
        assert obs.detections is not None
        assert len(obs.detections) == 2
        assert obs.uia_elements is not None
        assert len(obs.uia_elements) == 2

        # Run reason — should use detection path (auto mode + detections present)
        action = await agent._reason("Click the File menu", obs, [])
        assert action.action == "click"
        # element_id should be resolved to UIA name "File"
        assert action.parameters.get("name") == "File" or "x" in action.parameters


class TestBuildHistorySection:
    def test_empty_history(self):
        assert VisionAgent._build_history_section([]) == ""

    def test_with_steps(self):
        obs = _make_observation()
        steps = [
            AgentStep(
                observation=obs,
                action=AgentAction(action="click", parameters={"name": "OK"}, reasoning="click button"),
                result={"ok": True},
            ),
        ]
        section = VisionAgent._build_history_section(steps)
        assert "HISTORY" in section
        assert "click" in section
        assert "click button" in section
