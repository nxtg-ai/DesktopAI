#!/usr/bin/env bash
# Pre-cache faster-whisper model so first request doesn't download it.
# Usage: bash scripts/download-stt-model.sh [model_size]
set -euo pipefail

MODEL_SIZE="${1:-base.en}"
MODEL_DIR="${STT_MODEL_DIR:-models/whisper}"

echo "=== DesktopAI STT Model Download ==="
echo "Model size : $MODEL_SIZE"
echo "Cache dir  : $MODEL_DIR"

mkdir -p "$MODEL_DIR"

python3 -c "
from faster_whisper import WhisperModel
print(f'Downloading {\"$MODEL_SIZE\"} to {\"$MODEL_DIR\"}...')
model = WhisperModel('$MODEL_SIZE', device='cpu', compute_type='int8', download_root='$MODEL_DIR')
print('Done! Model cached successfully.')
"

echo "=== STT model ready ==="
