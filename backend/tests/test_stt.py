"""Tests for SttEngine."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.stt import SttEngine


class TestSttEngine:
    def test_init_does_not_load_model(self):
        engine = SttEngine("base.en")
        assert engine._initialized is False
        assert engine._model is None

    def test_available_false_when_import_error(self):
        engine = SttEngine("base.en")
        with patch.dict("sys.modules", {"faster_whisper": None}):
            assert engine.available is False

    def test_available_false_when_model_load_fails(self):
        mock_module = MagicMock()
        mock_module.WhisperModel.side_effect = FileNotFoundError("no model")
        with patch.dict("sys.modules", {"faster_whisper": mock_module}):
            engine = SttEngine("base.en")
            assert engine.available is False

    def test_available_true_when_model_loads(self):
        mock_module = MagicMock()
        mock_model = MagicMock()
        mock_module.WhisperModel.return_value = mock_model
        with patch.dict("sys.modules", {"faster_whisper": mock_module}):
            engine = SttEngine("base.en")
            assert engine.available is True

    def test_available_with_custom_model_dir(self):
        mock_module = MagicMock()
        mock_model = MagicMock()
        mock_module.WhisperModel.return_value = mock_model
        with patch.dict("sys.modules", {"faster_whisper": mock_module}):
            engine = SttEngine("base.en", model_dir="/tmp/whisper")
            assert engine.available is True
            call_kwargs = mock_module.WhisperModel.call_args
            assert call_kwargs.kwargs["download_root"] == "/tmp/whisper"

    @pytest.mark.asyncio
    async def test_transcribe_returns_text(self):
        mock_module = MagicMock()
        mock_model = MagicMock()

        mock_seg = MagicMock()
        mock_seg.text = "Hello world"
        mock_model.transcribe.return_value = ([mock_seg], MagicMock())
        mock_module.WhisperModel.return_value = mock_model

        with patch.dict("sys.modules", {"faster_whisper": mock_module}):
            engine = SttEngine("base.en")
            result = await engine.transcribe(b"RIFF" + b"\x00" * 40)

        assert result == "Hello world"

    @pytest.mark.asyncio
    async def test_transcribe_empty_bytes_returns_none(self):
        engine = SttEngine("base.en")
        assert await engine.transcribe(b"") is None

    @pytest.mark.asyncio
    async def test_transcribe_none_bytes_returns_none(self):
        engine = SttEngine("base.en")
        # Pass falsy value
        assert await engine.transcribe(b"") is None

    @pytest.mark.asyncio
    async def test_transcribe_failure_returns_none(self):
        mock_module = MagicMock()
        mock_model = MagicMock()
        mock_model.transcribe.side_effect = RuntimeError("decode error")
        mock_module.WhisperModel.return_value = mock_model

        with patch.dict("sys.modules", {"faster_whisper": mock_module}):
            engine = SttEngine("base.en")
            result = await engine.transcribe(b"RIFF" + b"\x00" * 40)
        assert result is None

    @pytest.mark.asyncio
    async def test_transcribe_unavailable_returns_none(self):
        engine = SttEngine("base.en")
        with patch.dict("sys.modules", {"faster_whisper": None}):
            _ = engine.available  # trigger init
            result = await engine.transcribe(b"RIFF" + b"\x00" * 40)
        assert result is None

    @pytest.mark.asyncio
    async def test_transcribe_uses_asyncio_to_thread(self):
        mock_module = MagicMock()
        mock_model = MagicMock()
        mock_seg = MagicMock()
        mock_seg.text = "test"
        mock_model.transcribe.return_value = ([mock_seg], MagicMock())
        mock_module.WhisperModel.return_value = mock_model

        with patch.dict("sys.modules", {"faster_whisper": mock_module}):
            with patch("app.stt.asyncio.to_thread", new_callable=AsyncMock) as mock_thread:
                mock_thread.return_value = "test output"
                engine = SttEngine("base.en")
                await engine.transcribe(b"RIFF" + b"\x00" * 40)
                mock_thread.assert_called_once()

    @pytest.mark.asyncio
    async def test_transcribe_cleans_up_temp_file(self):
        mock_module = MagicMock()
        mock_model = MagicMock()
        mock_seg = MagicMock()
        mock_seg.text = "cleanup test"
        mock_model.transcribe.return_value = ([mock_seg], MagicMock())
        mock_module.WhisperModel.return_value = mock_model

        import os
        created_files = []
        original_mkstemp = __import__("tempfile").mkstemp

        def tracking_mkstemp(**kwargs):
            fd, path = original_mkstemp(**kwargs)
            created_files.append(path)
            return fd, path

        with patch.dict("sys.modules", {"faster_whisper": mock_module}), \
             patch("app.stt.tempfile.mkstemp", side_effect=tracking_mkstemp):
            engine = SttEngine("base.en")
            await engine.transcribe(b"RIFF" + b"\x00" * 40)

        # Temp file should have been cleaned up
        for f in created_files:
            assert not os.path.exists(f), f"Temp file {f} was not cleaned up"
