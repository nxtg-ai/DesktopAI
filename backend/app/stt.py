"""Faster-Whisper STT engine wrapper."""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from typing import Any, Optional

logger = logging.getLogger("desktopai.stt")


class SttEngine:
    """Wraps faster-whisper for speech-to-text transcription."""

    def __init__(
        self,
        model_size: str = "base.en",
        device: str = "cpu",
        compute_type: str = "int8",
        language: str = "en",
        model_dir: Optional[str] = None,
    ) -> None:
        self._model_size = model_size
        self._device = device
        self._compute_type = compute_type
        self._language = language
        self._model_dir = model_dir
        self._model: Any = None
        self._available: bool = False
        self._initialized: bool = False

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        try:
            from faster_whisper import WhisperModel  # type: ignore[import-untyped]

            kwargs: dict[str, Any] = {
                "device": self._device,
                "compute_type": self._compute_type,
            }
            if self._model_dir:
                kwargs["download_root"] = self._model_dir

            self._model = WhisperModel(self._model_size, **kwargs)
            self._available = True
            logger.info(
                "STT engine loaded: %s (device=%s, compute=%s)",
                self._model_size,
                self._device,
                self._compute_type,
            )
        except ImportError:
            logger.warning("faster-whisper not installed — STT unavailable")
            self._available = False
        except Exception as exc:
            logger.warning("Failed to load STT model: %s", exc)
            self._available = False

    @property
    def available(self) -> bool:
        self._ensure_initialized()
        return self._available

    def _transcribe_sync(self, audio_path: str) -> Optional[str]:
        """Synchronous transcription — runs in a thread."""
        if self._model is None:
            return None
        segments, _info = self._model.transcribe(
            audio_path,
            language=self._language,
            vad_filter=True,
        )
        text_parts = [seg.text for seg in segments]
        result = " ".join(text_parts).strip()
        return result if result else None

    async def transcribe(self, audio_bytes: bytes) -> Optional[str]:
        """Transcribe audio bytes to text. Returns None on failure."""
        if not audio_bytes:
            return None
        self._ensure_initialized()
        if not self._available or self._model is None:
            return None

        # Write to temp file — faster-whisper needs a file path
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=".wav")
        try:
            os.write(tmp_fd, audio_bytes)
            os.close(tmp_fd)
            return await asyncio.to_thread(self._transcribe_sync, tmp_path)
        except Exception as exc:
            logger.error("STT transcription failed: %s", exc)
            return None
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
