from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Optional

import httpx


class OllamaClient:
    def __init__(self, base_url: str, model: str, ttl_seconds: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.configured_model = str(model or "").strip()
        self.model = self.configured_model
        self._ttl = ttl_seconds
        self._last_check = 0.0
        self._available: bool = False
        self._last_check_at: Optional[str] = None
        self._last_check_source: Optional[str] = None
        self._last_http_status: Optional[int] = None
        self._last_error: Optional[str] = None
        self._lock = asyncio.Lock()

    def _record_health(
        self,
        *,
        source: str,
        available: bool,
        status_code: Optional[int] = None,
        error: Optional[str] = None,
    ) -> None:
        self._available = bool(available)
        self._last_check = time.monotonic()
        self._last_check_at = datetime.now(timezone.utc).isoformat()
        self._last_check_source = source
        self._last_http_status = status_code
        self._last_error = error

    def diagnostics(self) -> dict:
        return {
            "available": bool(self._available),
            "last_check_at": self._last_check_at,
            "last_check_source": self._last_check_source,
            "last_http_status": self._last_http_status,
            "last_error": self._last_error,
            "ttl_seconds": self._ttl,
            "configured_model": self.configured_model,
            "active_model": self.model,
        }

    def set_active_model(self, model: str) -> str:
        selected = str(model or "").strip()
        if not selected:
            raise ValueError("ollama model is required")
        self.model = selected
        return self.model

    def reset_active_model(self) -> str:
        self.model = self.configured_model
        return self.model

    @staticmethod
    def _is_model_not_found_error(error: Optional[str]) -> bool:
        text = str(error or "").lower()
        return "model" in text and "not found" in text

    @staticmethod
    def _format_exception(exc: Exception) -> str:
        detail = str(exc).strip()
        if detail:
            return detail
        return exc.__class__.__name__

    async def _list_models(self) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
        except Exception:
            return []

        if resp.status_code != 200:
            return []

        try:
            payload = resp.json()
        except Exception:
            return []
        models = payload.get("models") if isinstance(payload, dict) else None
        if not isinstance(models, list):
            return []

        names: list[str] = []
        for item in models:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if name:
                names.append(name)
        return names

    async def list_models(self) -> list[str]:
        return await self._list_models()

    def _pick_fallback_model(self, names: list[str], unavailable_model: str) -> Optional[str]:
        candidates = [name for name in names if name and name != unavailable_model]
        if not candidates:
            return None

        configured_prefix = self.configured_model.split(":", 1)[0].strip().lower()
        if configured_prefix:
            for name in candidates:
                if name.split(":", 1)[0].strip().lower() == configured_prefix:
                    return name
        for name in candidates:
            if name.endswith(":latest"):
                return name
        return candidates[0]

    async def _generate_once(
        self,
        prompt: str,
        model: str,
        timeout_s: float = 30.0,
    ) -> tuple[Optional[str], Optional[int], Optional[str]]:
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
        }
        try:
            async with httpx.AsyncClient(timeout=timeout_s) as client:
                resp = await client.post(f"{self.base_url}/api/generate", json=payload)
        except Exception as exc:
            return None, None, f"POST /api/generate failed: {self._format_exception(exc)}"

        status_code = resp.status_code
        try:
            data = resp.json()
        except Exception as exc:
            if status_code != 200:
                return None, status_code, f"POST /api/generate returned status {status_code}"
            return None, status_code, f"POST /api/generate returned invalid JSON: {exc}"

        model_error = None
        if isinstance(data, dict):
            model_error = data.get("error") or data.get("message")
            if model_error is not None:
                model_error = str(model_error).strip()

        if status_code != 200:
            error_detail = f"POST /api/generate returned status {status_code}"
            if model_error:
                error_detail = f"{error_detail}: {model_error}"
            return None, status_code, error_detail

        if model_error:
            return None, status_code, f"POST /api/generate returned error: {model_error}"

        response_text = data.get("response") if isinstance(data, dict) else None
        if not isinstance(response_text, str) or not response_text.strip():
            return None, status_code, "POST /api/generate returned empty response"
        return response_text, status_code, None

    async def available(self) -> bool:
        now = time.monotonic()
        if now - self._last_check < self._ttl:
            return self._available
        async with self._lock:
            now = time.monotonic()
            if now - self._last_check < self._ttl:
                return self._available
            try:
                async with httpx.AsyncClient(timeout=2.0) as client:
                    resp = await client.get(f"{self.base_url}/api/tags")
                if resp.status_code == 200:
                    self._record_health(source="tags", available=True, status_code=resp.status_code)
                else:
                    self._record_health(
                        source="tags",
                        available=False,
                        status_code=resp.status_code,
                        error=f"GET /api/tags returned status {resp.status_code}",
                    )
            except Exception as exc:
                self._record_health(
                    source="tags",
                    available=False,
                    error=f"GET /api/tags failed: {exc}",
                )
            return self._available

    async def summarize(self, prompt: str) -> Optional[str]:
        return await self.generate(prompt)

    async def generate(self, prompt: str) -> Optional[str]:
        active_model = self.model
        response_text, status_code, error_detail = await self._generate_once(prompt, active_model)
        if error_detail is None:
            self._record_health(source="generate", available=True, status_code=status_code)
            return response_text

        if self._is_model_not_found_error(error_detail):
            available_models = await self._list_models()
            fallback_model = self._pick_fallback_model(available_models, unavailable_model=active_model)
            if fallback_model:
                fallback_text, fallback_status, fallback_error = await self._generate_once(prompt, fallback_model)
                if fallback_error is None:
                    self.model = fallback_model
                    self._record_health(
                        source="generate_fallback",
                        available=True,
                        status_code=fallback_status,
                    )
                    return fallback_text
                self._record_health(
                    source="generate_fallback",
                    available=False,
                    status_code=fallback_status,
                    error=fallback_error,
                )
                return None
            error_detail = f"{error_detail}; no fallback model available"

        self._record_health(
            source="generate",
            available=False,
            status_code=status_code,
            error=error_detail,
        )
        return None

    async def probe(
        self,
        *,
        prompt: str = "Respond with exactly: OK",
        timeout_s: float = 8.0,
        allow_fallback: bool = False,
    ) -> dict:
        started = time.monotonic()
        active_model = self.model

        response_text, status_code, error_detail = await self._generate_once(
            prompt,
            active_model,
            timeout_s=timeout_s,
        )
        elapsed_ms = int((time.monotonic() - started) * 1000)
        if error_detail is None:
            self._record_health(source="generate_probe", available=True, status_code=status_code)
            return {
                "ok": True,
                "model": active_model,
                "elapsed_ms": elapsed_ms,
                "error": None,
                "response_preview": response_text[:120],
                "response_chars": len(response_text),
                "used_fallback": False,
            }

        if allow_fallback and self._is_model_not_found_error(error_detail):
            available_models = await self._list_models()
            fallback_model = self._pick_fallback_model(available_models, unavailable_model=active_model)
            if fallback_model:
                fallback_text, fallback_status, fallback_error = await self._generate_once(
                    prompt,
                    fallback_model,
                    timeout_s=timeout_s,
                )
                elapsed_ms = int((time.monotonic() - started) * 1000)
                if fallback_error is None:
                    self.model = fallback_model
                    self._record_health(
                        source="generate_probe_fallback",
                        available=True,
                        status_code=fallback_status,
                    )
                    return {
                        "ok": True,
                        "model": fallback_model,
                        "elapsed_ms": elapsed_ms,
                        "error": None,
                        "response_preview": fallback_text[:120],
                        "response_chars": len(fallback_text),
                        "used_fallback": True,
                    }
                status_code = fallback_status
                error_detail = fallback_error
            else:
                error_detail = f"{error_detail}; no fallback model available"

        self._record_health(
            source="generate_probe",
            available=False,
            status_code=status_code,
            error=error_detail,
        )
        return {
            "ok": False,
            "model": active_model,
            "elapsed_ms": elapsed_ms,
            "error": error_detail,
            "response_preview": "",
            "response_chars": 0,
            "used_fallback": False,
        }
