import asyncio
import time
from unittest.mock import AsyncMock

from app.ollama import OllamaClient


class _Resp:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def test_generate_failure_marks_client_temporarily_unavailable(monkeypatch):
    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *_args, **_kwargs):
            return _Resp(404, {})

        async def get(self, *_args, **_kwargs):
            raise AssertionError("available() should use cached availability and skip network")

    async def scenario():
        monkeypatch.setattr("app.ollama.httpx.AsyncClient", _Client)
        client = OllamaClient("http://localhost:11434", "llama", ttl_seconds=30)
        client._available = True
        client._last_check = time.monotonic()

        out = await client.generate("hello")
        assert out is None
        assert client._available is False

        available = await client.available()
        assert available is False

    asyncio.run(scenario())


def test_generate_success_refreshes_available_cache(monkeypatch):
    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *_args, **_kwargs):
            return _Resp(200, {"response": "ok"})

    async def scenario():
        monkeypatch.setattr("app.ollama.httpx.AsyncClient", _Client)
        client = OllamaClient("http://localhost:11434", "llama", ttl_seconds=30)
        client._available = False
        client._last_check = 0.0

        out = await client.generate("hello")
        assert out == "ok"
        assert client._available is True
        assert client._last_check > 0

    asyncio.run(scenario())


def test_available_non_200_records_tags_diagnostics(monkeypatch):
    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, *_args, **_kwargs):
            return _Resp(503, {"error": "service unavailable"})

    async def scenario():
        monkeypatch.setattr("app.ollama.httpx.AsyncClient", _Client)
        client = OllamaClient("http://localhost:11434", "llama", ttl_seconds=30)

        available = await client.available()
        assert available is False

        diagnostics = client.diagnostics()
        assert diagnostics["available"] is False
        assert diagnostics["last_check_source"] == "tags"
        assert diagnostics["last_http_status"] == 503
        assert diagnostics["last_check_at"] is not None
        assert "503" in (diagnostics["last_error"] or "")

    asyncio.run(scenario())


def test_generate_failure_records_generate_diagnostics(monkeypatch):
    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *_args, **_kwargs):
            return _Resp(404, {"error": "model not found"})

    async def scenario():
        monkeypatch.setattr("app.ollama.httpx.AsyncClient", _Client)
        client = OllamaClient("http://localhost:11434", "llama", ttl_seconds=30)

        out = await client.generate("hello")
        assert out is None

        diagnostics = client.diagnostics()
        assert diagnostics["available"] is False
        assert diagnostics["last_check_source"] == "generate"
        assert diagnostics["last_http_status"] == 404
        assert diagnostics["last_check_at"] is not None
        assert "404" in (diagnostics["last_error"] or "")

    asyncio.run(scenario())


def test_generate_model_not_found_falls_back_to_installed_model(monkeypatch):
    post_models = []

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *_args, **kwargs):
            model = kwargs.get("json", {}).get("model")
            post_models.append(model)
            if model == "llama3.1:8b":
                return _Resp(404, {"error": "model 'llama3.1:8b' not found, try pulling it first"})
            if model == "mistral:latest":
                return _Resp(200, {"response": "fallback ok"})
            return _Resp(404, {"error": "model not found"})

        async def get(self, *_args, **_kwargs):
            return _Resp(
                200,
                {
                    "models": [
                        {"name": "mistral:latest"},
                        {"name": "mistral:instruct"},
                    ]
                },
            )

    async def scenario():
        monkeypatch.setattr("app.ollama.httpx.AsyncClient", _Client)
        client = OllamaClient("http://localhost:11434", "llama3.1:8b", ttl_seconds=30)

        out = await client.generate("hello")
        assert out == "fallback ok"
        assert post_models == ["llama3.1:8b", "mistral:latest"]

        diagnostics = client.diagnostics()
        assert diagnostics["available"] is True
        assert diagnostics["configured_model"] == "llama3.1:8b"
        assert diagnostics["active_model"] == "mistral:latest"
        assert diagnostics["last_check_source"] == "generate_fallback"
        assert diagnostics["last_error"] is None

    asyncio.run(scenario())


def test_generate_model_not_found_without_fallback_stays_unavailable(monkeypatch):
    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *_args, **_kwargs):
            return _Resp(404, {"error": "model 'llama3.1:8b' not found, try pulling it first"})

        async def get(self, *_args, **_kwargs):
            return _Resp(200, {"models": []})

    async def scenario():
        monkeypatch.setattr("app.ollama.httpx.AsyncClient", _Client)
        client = OllamaClient("http://localhost:11434", "llama3.1:8b", ttl_seconds=30)

        out = await client.generate("hello")
        assert out is None

        diagnostics = client.diagnostics()
        assert diagnostics["available"] is False
        assert diagnostics["configured_model"] == "llama3.1:8b"
        assert diagnostics["active_model"] == "llama3.1:8b"
        assert "no fallback model available" in (diagnostics["last_error"] or "")

    asyncio.run(scenario())


def test_generate_exception_without_message_records_exception_class(monkeypatch):
    class _SilentError(Exception):
        def __str__(self):
            return ""

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *_args, **_kwargs):
            raise _SilentError()

    async def scenario():
        monkeypatch.setattr("app.ollama.httpx.AsyncClient", _Client)
        client = OllamaClient("http://localhost:11434", "llama3.1:8b", ttl_seconds=30)

        out = await client.generate("hello")
        assert out is None

        diagnostics = client.diagnostics()
        assert diagnostics["available"] is False
        assert "SilentError" in (diagnostics["last_error"] or "")

    asyncio.run(scenario())


def test_list_models_reads_tags_payload(monkeypatch):
    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, *_args, **_kwargs):
            return _Resp(
                200,
                {
                    "models": [
                        {"name": "mistral:latest"},
                        {"name": ""},
                        {"name": "mistral:instruct"},
                    ]
                },
            )

    async def scenario():
        monkeypatch.setattr("app.ollama.httpx.AsyncClient", _Client)
        client = OllamaClient("http://localhost:11434", "llama3.1:8b", ttl_seconds=30)
        models = await client.list_models()
        assert models == ["mistral:latest", "mistral:instruct"]

    asyncio.run(scenario())


def test_probe_success_records_probe_health(monkeypatch):
    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *_args, **_kwargs):
            return _Resp(200, {"response": "OK"})

    async def scenario():
        monkeypatch.setattr("app.ollama.httpx.AsyncClient", _Client)
        client = OllamaClient("http://localhost:11434", "mistral:latest", ttl_seconds=30)
        report = await client.probe(prompt="Respond with exactly: OK", timeout_s=5.0)
        assert report["ok"] is True
        assert report["model"] == "mistral:latest"
        assert report["elapsed_ms"] >= 0
        assert report["response_preview"] == "OK"

        diagnostics = client.diagnostics()
        assert diagnostics["available"] is True
        assert diagnostics["last_check_source"] == "generate_probe"
        assert diagnostics["last_error"] is None

    asyncio.run(scenario())


def test_probe_failure_records_probe_error(monkeypatch):
    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *_args, **_kwargs):
            return _Resp(404, {"error": "model not found"})

    async def scenario():
        monkeypatch.setattr("app.ollama.httpx.AsyncClient", _Client)
        client = OllamaClient("http://localhost:11434", "missing:model", ttl_seconds=30)
        report = await client.probe(prompt="ping", timeout_s=5.0, allow_fallback=False)
        assert report["ok"] is False
        assert report["model"] == "missing:model"
        assert report["elapsed_ms"] >= 0
        assert "404" in (report["error"] or "")

        diagnostics = client.diagnostics()
        assert diagnostics["available"] is False
        assert diagnostics["last_check_source"] == "generate_probe"
        assert "404" in (diagnostics["last_error"] or "")

    asyncio.run(scenario())


# ── Retry + circuit breaker tests ────────────────────────────────────


def test_retry_on_transport_error(monkeypatch):
    """Transport errors (connection refused, timeout) are retried up to 2 times."""
    attempt_count = 0

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *_args, **_kwargs):
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 3:
                raise ConnectionError("connection refused")
            return _Resp(200, {"response": "ok"})

    async def scenario():
        monkeypatch.setattr("app.ollama.httpx.AsyncClient", _Client)
        monkeypatch.setattr("app.ollama.asyncio.sleep", AsyncMock())
        client = OllamaClient("http://localhost:11434", "llama", ttl_seconds=30)
        out = await client.generate("hello")
        assert out == "ok"
        assert attempt_count == 3  # 1 original + 2 retries

    asyncio.run(scenario())


def test_retry_on_500_error(monkeypatch):
    """5xx errors are retried; final 500 returns None."""
    attempt_count = 0

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *_args, **_kwargs):
            nonlocal attempt_count
            attempt_count += 1
            return _Resp(500, {"error": "internal server error"})

    async def scenario():
        monkeypatch.setattr("app.ollama.httpx.AsyncClient", _Client)
        monkeypatch.setattr("app.ollama.asyncio.sleep", AsyncMock())
        client = OllamaClient("http://localhost:11434", "llama", ttl_seconds=30)
        out = await client.generate("hello")
        assert out is None
        assert attempt_count == 3  # 1 original + 2 retries

    asyncio.run(scenario())


def test_no_retry_on_404(monkeypatch):
    """4xx errors (like 404 model not found) are NOT retried."""
    attempt_count = 0

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *_args, **_kwargs):
            nonlocal attempt_count
            attempt_count += 1
            return _Resp(404, {"error": "model not found"})

        async def get(self, *_args, **_kwargs):
            return _Resp(200, {"models": []})

    async def scenario():
        monkeypatch.setattr("app.ollama.httpx.AsyncClient", _Client)
        client = OllamaClient("http://localhost:11434", "llama", ttl_seconds=30)
        out = await client.generate("hello")
        assert out is None
        assert attempt_count == 1  # No retries

    asyncio.run(scenario())


def test_circuit_breaker_opens_after_3_failures(monkeypatch):
    """Circuit opens after 3 consecutive failures, returns None immediately."""

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *_args, **_kwargs):
            return _Resp(500, {"error": "crash"})

    async def scenario():
        monkeypatch.setattr("app.ollama.httpx.AsyncClient", _Client)
        monkeypatch.setattr("app.ollama.asyncio.sleep", AsyncMock())
        client = OllamaClient("http://localhost:11434", "llama", ttl_seconds=30)

        # 3 failures to open circuit (each with 2 retries = 9 HTTP calls)
        for _ in range(3):
            out = await client.generate("hello")
            assert out is None

        assert client._consecutive_failures >= 3
        assert client._circuit_open_until > time.monotonic()

    asyncio.run(scenario())


def test_circuit_breaker_blocks_requests_when_open(monkeypatch):
    """When circuit is open, generate() returns None without making HTTP calls."""
    http_calls = 0

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *_args, **_kwargs):
            nonlocal http_calls
            http_calls += 1
            return _Resp(200, {"response": "ok"})

    async def scenario():
        monkeypatch.setattr("app.ollama.httpx.AsyncClient", _Client)
        client = OllamaClient("http://localhost:11434", "llama", ttl_seconds=30)
        # Manually open circuit
        client._consecutive_failures = 5
        client._circuit_open_until = time.monotonic() + 60

        out = await client.generate("hello")
        assert out is None
        assert http_calls == 0  # No HTTP call made

    asyncio.run(scenario())


def test_circuit_breaker_resets_on_success(monkeypatch):
    """Successful request resets the failure counter and closes circuit."""

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *_args, **_kwargs):
            return _Resp(200, {"response": "ok"})

    async def scenario():
        monkeypatch.setattr("app.ollama.httpx.AsyncClient", _Client)
        client = OllamaClient("http://localhost:11434", "llama", ttl_seconds=30)
        # Set failure state
        client._consecutive_failures = 2
        client._circuit_open_until = 0.0  # Not open yet (below threshold)

        out = await client.generate("hello")
        assert out == "ok"
        assert client._consecutive_failures == 0
        assert client._circuit_open_until == 0.0

    asyncio.run(scenario())


def test_diagnostics_includes_circuit_breaker_state(monkeypatch):
    """Diagnostics reports circuit breaker failures and down_since."""

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *_args, **_kwargs):
            return _Resp(500, {"error": "crash"})

    async def scenario():
        monkeypatch.setattr("app.ollama.httpx.AsyncClient", _Client)
        monkeypatch.setattr("app.ollama.asyncio.sleep", AsyncMock())
        client = OllamaClient("http://localhost:11434", "llama", ttl_seconds=30)

        await client.generate("hello")

        diag = client.diagnostics()
        assert "consecutive_failures" in diag
        assert diag["consecutive_failures"] >= 1

    asyncio.run(scenario())


def test_chat_retry_on_transport_error(monkeypatch):
    """Chat method also retries on transport errors."""
    attempt_count = 0

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *_args, **_kwargs):
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 3:
                raise ConnectionError("connection refused")
            return _Resp(200, {"message": {"role": "assistant", "content": "ok"}})

    async def scenario():
        monkeypatch.setattr("app.ollama.httpx.AsyncClient", _Client)
        monkeypatch.setattr("app.ollama.asyncio.sleep", AsyncMock())
        client = OllamaClient("http://localhost:11434", "llama", ttl_seconds=30)
        out = await client.chat([{"role": "user", "content": "hello"}])
        assert out == "ok"
        assert attempt_count == 3

    asyncio.run(scenario())


def test_chat_circuit_breaker_blocks(monkeypatch):
    """Chat also respects the circuit breaker."""
    http_calls = 0

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *_args, **_kwargs):
            nonlocal http_calls
            http_calls += 1
            return _Resp(200, {"message": {"role": "assistant", "content": "ok"}})

    async def scenario():
        monkeypatch.setattr("app.ollama.httpx.AsyncClient", _Client)
        client = OllamaClient("http://localhost:11434", "llama", ttl_seconds=30)
        client._consecutive_failures = 5
        client._circuit_open_until = time.monotonic() + 60

        out = await client.chat([{"role": "user", "content": "hello"}])
        assert out is None
        assert http_calls == 0

    asyncio.run(scenario())


# ── chat_stream tests ────────────────────────────────────────────────


def test_chat_stream_circuit_breaker_blocks(monkeypatch):
    """chat_stream yields error event when circuit breaker is open."""

    async def scenario():
        client = OllamaClient("http://localhost:11434", "llama", ttl_seconds=30)
        client._consecutive_failures = 5
        client._circuit_open_until = time.monotonic() + 60

        events = []
        async for chunk in client.chat_stream([{"role": "user", "content": "hello"}]):
            events.append(chunk)

        assert len(events) == 1
        assert events[0]["done"] is True
        assert "circuit breaker" in events[0].get("error", "")

    asyncio.run(scenario())


def test_chat_stream_yields_tokens(monkeypatch):
    """chat_stream yields individual token chunks and a final done event."""
    import json as json_mod

    lines_to_send = [
        json_mod.dumps({"message": {"content": "Hello"}, "done": False}),
        json_mod.dumps({"message": {"content": " world"}, "done": False}),
        json_mod.dumps({"message": {"content": ""}, "done": True}),
    ]

    class _MockResp:
        status_code = 200

        async def aiter_lines(self):
            for line in lines_to_send:
                yield line

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def stream(self, *args, **kwargs):
            return _MockResp()

    async def scenario():
        monkeypatch.setattr("app.ollama.httpx.AsyncClient", _Client)
        client = OllamaClient("http://localhost:11434", "llama", ttl_seconds=30)

        events = []
        async for chunk in client.chat_stream([{"role": "user", "content": "hello"}]):
            events.append(chunk)

        assert len(events) == 3
        assert events[0]["token"] == "Hello"
        assert events[0]["done"] is False
        assert events[1]["token"] == " world"
        assert events[2]["done"] is True

    asyncio.run(scenario())


# ── Fallback model tests ────────────────────────────────────────────


def test_fallback_model_used_when_circuit_breaker_open(monkeypatch):
    """When circuit breaker is open and fallback model is configured, use it."""
    models_used = []

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *_args, **kwargs):
            model = kwargs.get("json", {}).get("model")
            models_used.append(model)
            return _Resp(200, {"message": {"role": "assistant", "content": "fallback ok"}})

    async def scenario():
        monkeypatch.setattr("app.ollama.httpx.AsyncClient", _Client)
        client = OllamaClient(
            "http://localhost:11434", "qwen2.5vl:7b",
            fallback_model="qwen2.5:3b",
        )
        # Manually open circuit
        client._consecutive_failures = 5
        client._circuit_open_until = time.monotonic() + 60

        out = await client.chat([{"role": "user", "content": "hello"}])
        assert out == "fallback ok"
        assert models_used == ["qwen2.5:3b"]
        # Success resets the circuit breaker
        assert client._consecutive_failures == 0

    asyncio.run(scenario())


def test_fallback_model_not_used_when_circuit_breaker_closed(monkeypatch):
    """When circuit breaker is closed, primary model is used (not fallback)."""
    models_used = []

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *_args, **kwargs):
            model = kwargs.get("json", {}).get("model")
            models_used.append(model)
            return _Resp(200, {"message": {"role": "assistant", "content": "primary ok"}})

    async def scenario():
        monkeypatch.setattr("app.ollama.httpx.AsyncClient", _Client)
        client = OllamaClient(
            "http://localhost:11434", "qwen2.5vl:7b",
            fallback_model="qwen2.5:3b",
        )
        # Circuit breaker is NOT open (default state)

        out = await client.chat([{"role": "user", "content": "hello"}])
        assert out == "primary ok"
        assert models_used == ["qwen2.5vl:7b"]

    asyncio.run(scenario())


def test_fallback_not_used_when_not_configured(monkeypatch):
    """When no fallback model is configured, circuit breaker open returns None."""
    http_calls = 0

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, *_args, **_kwargs):
            nonlocal http_calls
            http_calls += 1
            return _Resp(200, {"message": {"role": "assistant", "content": "ok"}})

    async def scenario():
        monkeypatch.setattr("app.ollama.httpx.AsyncClient", _Client)
        client = OllamaClient(
            "http://localhost:11434", "qwen2.5vl:7b",
            fallback_model="",  # No fallback
        )
        # Manually open circuit
        client._consecutive_failures = 5
        client._circuit_open_until = time.monotonic() + 60

        out = await client.chat([{"role": "user", "content": "hello"}])
        assert out is None
        assert http_calls == 0  # No HTTP call made

    asyncio.run(scenario())
