"""
Integration tests for the vision detection pipeline.

Tests ONNX model format, inference, and detection-mode reasoning against
a real Ollama instance.

Run with: pytest backend/tests/test_vision_detection_integration.py -v -m integration --timeout=120
Skip with: pytest -m "not integration"
"""

import asyncio
import os
import time
from pathlib import Path

import pytest

# Environment configuration (shared with test_llm_integration.py)
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:0.5b")

ONNX_MODEL_PATH = Path("models/ui-detr/ui-detr-1.onnx")

CI_TIMEOUT = 120.0


def skip_if_model_absent():
    """Skip test if the ONNX model file is not present."""
    if not ONNX_MODEL_PATH.exists():
        pytest.skip(f"ONNX model not found at {ONNX_MODEL_PATH}")


def skip_if_ollama_unavailable():
    """Skip test if Ollama is not available."""
    try:
        import httpx

        with httpx.Client(timeout=2.0) as client:
            resp = client.get(f"{OLLAMA_URL}/api/tags")
            if resp.status_code != 200:
                pytest.skip(
                    f"Ollama not available at {OLLAMA_URL} (status {resp.status_code})"
                )
    except Exception as e:
        pytest.skip(f"Ollama not available at {OLLAMA_URL}: {e}")


# ---------------------------------------------------------------------------
# Test 1: ONNX model format
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_onnx_model_format():
    """Verify ONNX model has expected input/output shapes."""
    skip_if_model_absent()
    import onnxruntime as ort

    session = ort.InferenceSession(str(ONNX_MODEL_PATH))

    # Single input: [1, 3, 576, 576]
    inputs = session.get_inputs()
    assert len(inputs) == 1
    inp = inputs[0]
    assert inp.name == "input"
    assert inp.shape == [1, 3, 576, 576]

    # Two outputs: boxes (rank 3) and scores (rank 3)
    outputs = session.get_outputs()
    assert len(outputs) == 2

    dets = outputs[0]
    assert dets.name == "dets"
    assert len(dets.shape) == 3  # [1, N, 4]
    assert dets.shape[0] == 1
    assert dets.shape[2] == 4

    labels = outputs[1]
    assert labels.name == "labels"
    assert len(labels.shape) == 3  # [1, N, 1]
    assert labels.shape[0] == 1


# ---------------------------------------------------------------------------
# Test 2: ONNX model inference with dummy input
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_onnx_model_inference():
    """Run inference on a dummy tensor and verify output shapes."""
    skip_if_model_absent()
    import numpy as np
    import onnxruntime as ort

    session = ort.InferenceSession(str(ONNX_MODEL_PATH))

    # Dummy 576x576 RGB image (normalized)
    dummy = np.random.rand(1, 3, 576, 576).astype(np.float32)
    results = session.run(None, {"input": dummy})

    assert len(results) == 2

    dets = results[0]  # boxes
    labels = results[1]  # scores

    assert dets.ndim == 3
    assert dets.shape[0] == 1
    assert dets.shape[2] == 4

    assert labels.ndim == 3
    assert labels.shape[0] == 1
    assert labels.shape[1] == dets.shape[1]  # same N


# ---------------------------------------------------------------------------
# Test 3: Detection reasoning with real Ollama
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_detection_reasoning_with_real_ollama():
    """VisionAgent._reason_detection returns a valid action with real Ollama."""
    skip_if_ollama_unavailable()
    from datetime import datetime, timezone

    from app.ollama import OllamaClient
    from app.vision_agent import AgentObservation, VisionAgent

    ollama = OllamaClient(base_url=OLLAMA_URL, model=OLLAMA_MODEL, ttl_seconds=1)

    class FakeBridge:
        connected = False

        async def execute(self, *a, **kw):
            return {}

    agent = VisionAgent(
        bridge=FakeBridge(),
        ollama=ollama,
        vision_mode="detection",
    )

    observation = AgentObservation(
        screenshot_b64=None,
        uia_summary=None,
        window_title="Test App",
        process_exe="testapp.exe",
        timestamp=datetime.now(timezone.utc),
        detections=[
            {"x": 0.1, "y": 0.2, "width": 0.08, "height": 0.04, "confidence": 0.95},
            {"x": 0.5, "y": 0.5, "width": 0.1, "height": 0.05, "confidence": 0.88},
        ],
        uia_elements=[
            {
                "name": "OK",
                "control_type": "Button",
                "automation_id": "btn_ok",
                "bounding_rect": [100, 150, 82, 31],
            },
            {
                "name": "Cancel",
                "control_type": "Button",
                "automation_id": "btn_cancel",
                "bounding_rect": [500, 380, 102, 38],
            },
        ],
        screenshot_width=1024,
        screenshot_height=768,
    )

    async def scenario():
        action = await agent._reason_detection(
            "click the OK button", observation, []
        )
        assert action is not None
        assert action.action in (
            "click",
            "double_click",
            "right_click",
            "type_text",
            "send_keys",
            "open_application",
            "focus_window",
            "scroll",
            "wait",
            "done",
        )
        assert isinstance(action.reasoning, str)
        assert 0.0 <= action.confidence <= 1.0

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Test 4: Detection pipeline latency
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_detection_pipeline_latency():
    """Detection reasoning completes within 300s (CPU cold start can be slow)."""
    skip_if_ollama_unavailable()
    from datetime import datetime, timezone

    from app.ollama import OllamaClient
    from app.vision_agent import AgentObservation, VisionAgent

    ollama = OllamaClient(base_url=OLLAMA_URL, model=OLLAMA_MODEL, ttl_seconds=1)

    class FakeBridge:
        connected = False

        async def execute(self, *a, **kw):
            return {}

    agent = VisionAgent(
        bridge=FakeBridge(),
        ollama=ollama,
        vision_mode="detection",
    )

    observation = AgentObservation(
        screenshot_b64=None,
        uia_summary=None,
        window_title="Notepad",
        process_exe="notepad.exe",
        timestamp=datetime.now(timezone.utc),
        detections=[
            {"x": 0.3, "y": 0.1, "width": 0.05, "height": 0.03, "confidence": 0.9},
        ],
        uia_elements=[
            {
                "name": "File",
                "control_type": "MenuItem",
                "automation_id": "menu_file",
                "bounding_rect": [307, 77, 51, 23],
            },
        ],
        screenshot_width=1024,
        screenshot_height=768,
    )

    async def scenario():
        t0 = time.monotonic()
        await agent._reason_detection("click the File menu", observation, [])
        elapsed = time.monotonic() - t0
        assert elapsed < 300.0, f"Detection reasoning took {elapsed:.1f}s (limit: 300s)"

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Test 5: Detection reasoning error handling (no Ollama needed)
# ---------------------------------------------------------------------------


def test_detection_reasoning_error_handling():
    """_reason_detection returns wait action when Ollama is unreachable."""
    from datetime import datetime, timezone

    from app.ollama import OllamaClient
    from app.vision_agent import AgentObservation, VisionAgent

    # Point at an invalid URL
    ollama = OllamaClient(
        base_url="http://localhost:99999", model="fake", ttl_seconds=1
    )

    class FakeBridge:
        connected = False

        async def execute(self, *a, **kw):
            return {}

    agent = VisionAgent(
        bridge=FakeBridge(),
        ollama=ollama,
        vision_mode="detection",
    )

    observation = AgentObservation(
        screenshot_b64=None,
        uia_summary=None,
        window_title="Test",
        process_exe="test.exe",
        timestamp=datetime.now(timezone.utc),
        detections=[
            {"x": 0.5, "y": 0.5, "width": 0.1, "height": 0.05, "confidence": 0.9},
        ],
        uia_elements=[],
        screenshot_width=1024,
        screenshot_height=768,
    )

    async def scenario():
        action = await agent._reason_detection("click something", observation, [])
        assert action.action == "wait"
        # OllamaClient retries swallow the transport error and return None,
        # which _parse_action converts to "empty response".  Either path
        # (exception caught → "reasoning error", or None → "empty response")
        # is acceptable — the agent gracefully degrades.
        assert "error" in action.reasoning or "empty response" in action.reasoning

    asyncio.run(scenario())
