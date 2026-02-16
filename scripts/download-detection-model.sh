#!/usr/bin/env bash
# Download UI-DETR-1 ONNX model for UI element detection.
# Places model in models/ui-detr/ui-detr-1.onnx (git-ignored).
#
# Usage:
#   bash scripts/download-detection-model.sh

set -euo pipefail

MODEL_DIR="models/ui-detr"
MODEL_FILE="$MODEL_DIR/ui-detr-1.onnx"
HF_REPO="racineai/UI-DETR-1"
HF_FILE="model.onnx"

if [ -f "$MODEL_FILE" ]; then
    echo "Model already exists at $MODEL_FILE"
    exit 0
fi

mkdir -p "$MODEL_DIR"

echo "Downloading UI-DETR-1 ONNX model from HuggingFace ($HF_REPO)..."

# Try huggingface-cli first (if installed via pip install huggingface_hub)
if command -v huggingface-cli &>/dev/null; then
    huggingface-cli download "$HF_REPO" "$HF_FILE" --local-dir "$MODEL_DIR"
    if [ -f "$MODEL_DIR/$HF_FILE" ] && [ "$HF_FILE" != "ui-detr-1.onnx" ]; then
        mv "$MODEL_DIR/$HF_FILE" "$MODEL_FILE"
    fi
elif command -v curl &>/dev/null; then
    curl -L -o "$MODEL_FILE" \
        "https://huggingface.co/$HF_REPO/resolve/main/$HF_FILE"
elif command -v wget &>/dev/null; then
    wget -O "$MODEL_FILE" \
        "https://huggingface.co/$HF_REPO/resolve/main/$HF_FILE"
else
    echo "Error: No download tool available. Install curl, wget, or huggingface-cli."
    exit 1
fi

if [ -f "$MODEL_FILE" ]; then
    SIZE=$(stat -c%s "$MODEL_FILE" 2>/dev/null || stat -f%z "$MODEL_FILE" 2>/dev/null || echo "unknown")
    echo "Downloaded $MODEL_FILE ($SIZE bytes)"
else
    echo "Error: Download failed — $MODEL_FILE not found."
    exit 1
fi
