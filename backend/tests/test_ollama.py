import asyncio
import time

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
