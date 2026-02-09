"""
Integration tests for OllamaClient against a real Ollama instance.

These tests require a running Ollama server and are marked with @pytest.mark.integration
so they can be skipped in normal test runs.

Run with: pytest backend/tests/test_llm_integration.py -v -m integration
Skip with: pytest -m "not integration"
"""

import asyncio
import json
import os

import pytest

from app.ollama import OllamaClient


# Environment configuration
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:0.5b")

# CI runners have no GPU — first inference cold-starts are slow.
CI_TIMEOUT = 120.0


def skip_if_ollama_unavailable():
    """Skip test if Ollama is not available."""
    try:
        import httpx
        with httpx.Client(timeout=2.0) as client:
            resp = client.get(f"{OLLAMA_URL}/api/tags")
            if resp.status_code != 200:
                return pytest.skip(f"Ollama not available at {OLLAMA_URL} (status {resp.status_code})")
    except Exception as e:
        return pytest.skip(f"Ollama not available at {OLLAMA_URL}: {e}")
    return None


@pytest.fixture
def ollama_client():
    """Create an OllamaClient instance configured for integration tests."""
    skip_if_ollama_unavailable()
    return OllamaClient(base_url=OLLAMA_URL, model=OLLAMA_MODEL, ttl_seconds=1)


@pytest.mark.integration
def test_ollama_available(ollama_client):
    """Verify client.available() returns True when Ollama is running."""
    async def scenario():
        available = await ollama_client.available()
        assert available is True, "Ollama should be available"

        # Check diagnostics populated
        diag = ollama_client.diagnostics()
        assert diag["available"] is True
        assert diag["last_check_source"] == "tags"
        assert diag["last_http_status"] == 200
        assert diag["last_error"] is None

    asyncio.run(scenario())


@pytest.mark.integration
def test_list_models(ollama_client):
    """Verify list_models() returns a non-empty list."""
    async def scenario():
        models = await ollama_client.list_models()
        assert isinstance(models, list), "list_models should return a list"
        assert len(models) > 0, "At least one model should be installed"

        # Each model name should be a non-empty string
        for model_name in models:
            assert isinstance(model_name, str)
            assert len(model_name) > 0

    asyncio.run(scenario())


@pytest.mark.integration
def test_generate_basic(ollama_client):
    """Send a simple prompt and verify non-empty response."""
    async def scenario():
        prompt = "Count from 1 to 3, using only digits separated by spaces."
        response_text, status_code, error = await ollama_client._generate_once(
            prompt, ollama_client.model, timeout_s=CI_TIMEOUT
        )

        assert error is None, f"generate failed: {error}"
        assert response_text is not None, "generate should return a response"
        assert len(response_text.strip()) > 0, "Response should not be empty"

        # Record health and check
        ollama_client._record_health(source="generate", available=True, status_code=status_code)
        diag = ollama_client.diagnostics()
        assert diag["available"] is True
        assert diag["last_error"] is None

    asyncio.run(scenario())


@pytest.mark.integration
def test_chat_basic(ollama_client):
    """Send a chat message and verify response."""
    async def scenario():
        messages = [
            {"role": "user", "content": "What is 2+2? Answer with just the number."}
        ]
        response = await ollama_client.chat(messages, timeout_s=CI_TIMEOUT)

        assert response is not None, "chat should return a response"
        assert isinstance(response, str)
        assert len(response.strip()) > 0, "Response should not be empty"

        # Check health recorded
        diag = ollama_client.diagnostics()
        assert diag["available"] is True
        assert diag["last_check_source"] in ["chat", "chat_fallback"]
        assert diag["last_error"] is None

    asyncio.run(scenario())


@pytest.mark.integration
def test_chat_structured_output(ollama_client):
    """Send chat with format=JSON schema and verify parseable JSON."""
    async def scenario():
        messages = [
            {
                "role": "user",
                "content": "Return a JSON object with a single field 'answer' containing the number 42."
            }
        ]

        # Define JSON schema for structured output
        json_schema = {
            "type": "object",
            "properties": {
                "answer": {"type": "number"}
            },
            "required": ["answer"]
        }

        response = await ollama_client.chat(messages, format=json_schema, timeout_s=CI_TIMEOUT)

        assert response is not None, "chat should return a response"
        assert isinstance(response, str)

        # Should be parseable as JSON
        try:
            parsed = json.loads(response)
            assert isinstance(parsed, dict), "Response should be a JSON object"
            assert "answer" in parsed, "Response should contain 'answer' field"
        except json.JSONDecodeError as e:
            pytest.fail(f"Response is not valid JSON: {e}\nResponse: {response}")

    asyncio.run(scenario())


@pytest.mark.integration
def test_probe_returns_ok(ollama_client):
    """Test probe() with CI-safe timeout and check ok=True."""
    async def scenario():
        report = await ollama_client.probe(timeout_s=CI_TIMEOUT)

        assert isinstance(report, dict), "probe should return a dict"
        assert report["ok"] is True, f"probe should succeed, got error: {report.get('error')}"
        assert isinstance(report["model"], str)
        assert report["elapsed_ms"] >= 0
        assert isinstance(report["response_preview"], str)
        assert report["response_chars"] > 0
        assert report["used_fallback"] is False or report["used_fallback"] is True

        # Check diagnostics
        diag = ollama_client.diagnostics()
        assert diag["available"] is True
        assert diag["last_check_source"] in ["generate_probe", "generate_probe_fallback"]
        assert diag["last_error"] is None

    asyncio.run(scenario())


@pytest.mark.integration
def test_generate_model_not_found_fallback(ollama_client):
    """Test with a fake model name and verify fallback works."""
    async def scenario():
        # Set model to something that doesn't exist
        original_model = ollama_client.model
        ollama_client.set_active_model("fake-nonexistent-model:999")

        try:
            prompt = "Say 'fallback works'"
            response_text, status_code, error = await ollama_client._generate_once(
                prompt, ollama_client.model, timeout_s=CI_TIMEOUT
            )

            # First attempt should fail with model not found
            assert error is not None

            # Now try via generate() which does the fallback
            ollama_client.set_active_model("fake-nonexistent-model:999")
            response = await ollama_client.generate(prompt)

            # Should get a response via fallback (generate uses default 30s, but
            # model is already warm from prior tests)
            assert response is not None, "generate should fallback to available model"
            assert isinstance(response, str)
            assert len(response.strip()) > 0

            # Active model should have changed to fallback
            diag = ollama_client.diagnostics()
            assert diag["active_model"] != "fake-nonexistent-model:999"
            assert diag["configured_model"] == original_model
            assert diag["available"] is True
            assert diag["last_check_source"] == "generate_fallback"

        finally:
            # Restore original model
            ollama_client.reset_active_model()

    asyncio.run(scenario())


@pytest.mark.integration
def test_diagnostics_after_generate(ollama_client):
    """Verify diagnostics() returns sensible data after a generate call."""
    async def scenario():
        # Initial diagnostics before any calls
        diag_before = ollama_client.diagnostics()
        assert diag_before["configured_model"] == OLLAMA_MODEL
        assert diag_before["active_model"] == OLLAMA_MODEL

        # Make a generate call with CI timeout
        prompt = "Hello"
        response_text, status_code, error = await ollama_client._generate_once(
            prompt, ollama_client.model, timeout_s=CI_TIMEOUT
        )
        assert error is None, f"generate failed: {error}"
        ollama_client._record_health(source="generate", available=True, status_code=status_code)

        # Check diagnostics after call
        diag_after = ollama_client.diagnostics()

        # Verify all expected fields present
        assert "available" in diag_after
        assert "last_check_at" in diag_after
        assert "last_check_source" in diag_after
        assert "last_http_status" in diag_after
        assert "last_error" in diag_after
        assert "ttl_seconds" in diag_after
        assert "configured_model" in diag_after
        assert "active_model" in diag_after

        # Verify values are sensible
        assert diag_after["available"] is True
        assert diag_after["last_check_at"] is not None
        assert diag_after["last_check_source"] in ["generate", "generate_fallback"]
        assert diag_after["last_http_status"] == 200
        assert diag_after["last_error"] is None
        assert diag_after["ttl_seconds"] == 1
        assert diag_after["configured_model"] == OLLAMA_MODEL

    asyncio.run(scenario())
