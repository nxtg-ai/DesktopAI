#!/bin/bash
# Downloads Kokoro-82M ONNX model files for TTS
set -e

DEST="models/kokoro"
mkdir -p "$DEST"

BASE="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"

echo "Downloading Kokoro-82M model files..."
curl -L --progress-bar -o "$DEST/kokoro-v1.0.onnx" "$BASE/kokoro-v1.0.onnx"
curl -L --progress-bar -o "$DEST/voices-v1.0.bin" "$BASE/voices-v1.0.bin"

echo "Done. Models saved to $DEST/"
ls -lh "$DEST/"
