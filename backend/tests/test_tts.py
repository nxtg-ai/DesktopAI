"""Tests for TtsEngine."""

import struct
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.tts import TtsEngine, _float32_to_wav_bytes


class TestFloat32ToWavBytes:
    def test_wav_header_format(self):
        samples = [0.0, 0.5, -0.5]
        wav = _float32_to_wav_bytes(samples, sample_rate=24000)
        assert wav[:4] == b"RIFF"
        assert wav[8:12] == b"WAVE"
        assert wav[12:16] == b"fmt "
        # Sample rate at offset 24
        sr = struct.unpack_from("<I", wav, 24)[0]
        assert sr == 24000
        # Bits per sample at offset 34
        bps = struct.unpack_from("<H", wav, 34)[0]
        assert bps == 16

    def test_wav_data_size(self):
        samples = [0.0] * 100
        wav = _float32_to_wav_bytes(samples)
        data_size = struct.unpack_from("<I", wav, 40)[0]
        assert data_size == 100 * 2  # 16-bit = 2 bytes per sample

    def test_clamps_values(self):
        samples = [2.0, -2.0]
        wav = _float32_to_wav_bytes(samples)
        # Data starts at offset 44
        s1 = struct.unpack_from("<h", wav, 44)[0]
        s2 = struct.unpack_from("<h", wav, 46)[0]
        assert s1 == 32767
        assert s2 == -32767


class TestTtsEngine:
    def test_init_does_not_load_model(self):
        engine = TtsEngine("fake/model.onnx", "fake/voices.bin")
        assert engine._initialized is False
        assert engine._kokoro is None

    def test_available_false_when_import_error(self):
        engine = TtsEngine("fake/model.onnx", "fake/voices.bin")
        with patch.dict("sys.modules", {"kokoro_onnx": None}):
            assert engine.available is False

    def test_available_false_when_model_load_fails(self):
        mock_module = MagicMock()
        mock_module.Kokoro.side_effect = FileNotFoundError("no model")
        with patch.dict("sys.modules", {"kokoro_onnx": mock_module}):
            engine = TtsEngine("missing/model.onnx", "missing/voices.bin")
            assert engine.available is False

    def test_available_true_when_model_loads(self):
        mock_module = MagicMock()
        mock_kokoro = MagicMock()
        mock_module.Kokoro.return_value = mock_kokoro
        with patch.dict("sys.modules", {"kokoro_onnx": mock_module}):
            engine = TtsEngine("ok/model.onnx", "ok/voices.bin")
            assert engine.available is True

    def test_list_voices_returns_sorted(self):
        mock_module = MagicMock()
        mock_kokoro = MagicMock()
        mock_kokoro.get_voices.return_value = ["bf_emma", "af_bella", "am_adam"]
        mock_module.Kokoro.return_value = mock_kokoro
        with patch.dict("sys.modules", {"kokoro_onnx": mock_module}):
            engine = TtsEngine("m.onnx", "v.bin")
            voices = engine.list_voices()
        assert voices == ["af_bella", "am_adam", "bf_emma"]

    def test_list_voices_empty_when_unavailable(self):
        engine = TtsEngine("fake.onnx", "fake.bin")
        with patch.dict("sys.modules", {"kokoro_onnx": None}):
            assert engine.list_voices() == []

    @pytest.mark.asyncio
    async def test_synthesize_returns_wav_bytes(self):
        mock_module = MagicMock()
        mock_kokoro = MagicMock()
        fake_samples = [0.0, 0.5, -0.5]
        mock_kokoro.create.return_value = (fake_samples, 24000)
        mock_module.Kokoro.return_value = mock_kokoro

        with patch.dict("sys.modules", {"kokoro_onnx": mock_module}):
            engine = TtsEngine("m.onnx", "v.bin")
            wav = await engine.synthesize("Hello", voice="af_bella", speed=1.0)

        assert wav is not None
        assert wav[:4] == b"RIFF"
        mock_kokoro.create.assert_called_once_with(
            "Hello", voice="af_bella", speed=1.0
        )

    @pytest.mark.asyncio
    async def test_synthesize_empty_text_returns_none(self):
        engine = TtsEngine("m.onnx", "v.bin")
        assert await engine.synthesize("") is None
        assert await engine.synthesize("   ") is None

    @pytest.mark.asyncio
    async def test_synthesize_failure_returns_none(self):
        mock_module = MagicMock()
        mock_kokoro = MagicMock()
        mock_kokoro.create.side_effect = RuntimeError("synthesis error")
        mock_module.Kokoro.return_value = mock_kokoro

        with patch.dict("sys.modules", {"kokoro_onnx": mock_module}):
            engine = TtsEngine("m.onnx", "v.bin")
            result = await engine.synthesize("Hello")
        assert result is None

    @pytest.mark.asyncio
    async def test_synthesize_uses_asyncio_to_thread(self):
        mock_module = MagicMock()
        mock_kokoro = MagicMock()
        mock_kokoro.create.return_value = ([0.0] * 10, 24000)
        mock_module.Kokoro.return_value = mock_kokoro

        with patch.dict("sys.modules", {"kokoro_onnx": mock_module}):
            with patch("app.tts.asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
                mock_thread.return_value = ([0.0] * 10, 24000)
                engine = TtsEngine("m.onnx", "v.bin")
                await engine.synthesize("test")
                mock_thread.assert_called_once()
