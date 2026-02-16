"""Kokoro-82M TTS engine wrapper."""

from __future__ import annotations

import asyncio
import io
import logging
import struct
from typing import Any, Optional

logger = logging.getLogger("desktopai.tts")

SAMPLE_RATE = 24000
BITS_PER_SAMPLE = 16
NUM_CHANNELS = 1


def _float32_to_wav_bytes(samples, sample_rate: int = SAMPLE_RATE) -> bytes:
    """Convert float32 numpy array to 16-bit PCM WAV bytes."""
    buf = io.BytesIO()
    num_samples = len(samples)
    data_size = num_samples * NUM_CHANNELS * (BITS_PER_SAMPLE // 8)
    byte_rate = sample_rate * NUM_CHANNELS * (BITS_PER_SAMPLE // 8)
    block_align = NUM_CHANNELS * (BITS_PER_SAMPLE // 8)

    # WAV header
    buf.write(b"RIFF")
    buf.write(struct.pack("<I", 36 + data_size))
    buf.write(b"WAVE")
    buf.write(b"fmt ")
    buf.write(struct.pack("<I", 16))  # chunk size
    buf.write(struct.pack("<H", 1))  # PCM format
    buf.write(struct.pack("<H", NUM_CHANNELS))
    buf.write(struct.pack("<I", sample_rate))
    buf.write(struct.pack("<I", byte_rate))
    buf.write(struct.pack("<H", block_align))
    buf.write(struct.pack("<H", BITS_PER_SAMPLE))
    buf.write(b"data")
    buf.write(struct.pack("<I", data_size))

    # Convert float32 [-1, 1] to int16
    for s in samples:
        clamped = max(-1.0, min(1.0, float(s)))
        buf.write(struct.pack("<h", int(clamped * 32767)))

    return buf.getvalue()


class TtsEngine:
    """Wraps kokoro_onnx for text-to-speech synthesis."""

    def __init__(self, model_path: str, voices_path: str) -> None:
        self._model_path = model_path
        self._voices_path = voices_path
        self._kokoro: Any = None
        self._available: bool = False
        self._initialized: bool = False

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        try:
            from kokoro_onnx import Kokoro  # type: ignore[import-untyped]

            self._kokoro = Kokoro(self._model_path, self._voices_path)
            self._available = True
            logger.info("TTS engine loaded: %s", self._model_path)
        except ImportError:
            logger.warning("kokoro_onnx not installed — TTS unavailable")
            self._available = False
        except Exception as exc:
            logger.warning("Failed to load TTS model: %s", exc)
            self._available = False

    @property
    def available(self) -> bool:
        self._ensure_initialized()
        return self._available

    def list_voices(self) -> list[str]:
        self._ensure_initialized()
        if not self._available or self._kokoro is None:
            return []
        try:
            voices = self._kokoro.get_voices()
            return sorted(voices) if voices else []
        except Exception:
            return []

    async def synthesize(
        self,
        text: str,
        voice: str = "af_bella",
        speed: float = 1.0,
    ) -> Optional[bytes]:
        """Synthesize text to WAV bytes. Returns None on failure."""
        if not text or not text.strip():
            return None
        self._ensure_initialized()
        if not self._available or self._kokoro is None:
            return None
        try:
            samples, sr = await asyncio.to_thread(
                self._kokoro.create, text, voice=voice, speed=speed
            )
            return _float32_to_wav_bytes(samples, sr)
        except Exception as exc:
            logger.error("TTS synthesis failed: %s", exc)
            return None
