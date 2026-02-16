#!/usr/bin/env bash
# Download UI-DETR-1 PyTorch weights and export to ONNX.
# Places model in models/ui-detr/ui-detr-1.onnx (git-ignored).
#
# The HuggingFace repo only has model.pth (PyTorch), so we download
# the weights and then run the export script to produce ONNX.
#
# Usage:
#   bash scripts/download-detection-model.sh
#
# Prerequisites for export:
#   pip install rfdetr[onnxexport]

set -euo pipefail

MODEL_DIR="models/ui-detr"
ONNX_FILE="$MODEL_DIR/ui-detr-1.onnx"
PTH_FILE="$MODEL_DIR/model.pth"
HF_REPO="racineai/UI-DETR-1"
HF_FILE="model.pth"

if [ -f "$ONNX_FILE" ]; then
    echo "ONNX model already exists at $ONNX_FILE"
    exit 0
fi

mkdir -p "$MODEL_DIR"

# Step 1: Download .pth weights (if not already present)
if [ ! -f "$PTH_FILE" ]; then
    echo "Downloading UI-DETR-1 weights from HuggingFace ($HF_REPO)..."

    if command -v huggingface-cli &>/dev/null; then
        huggingface-cli download "$HF_REPO" "$HF_FILE" --local-dir "$MODEL_DIR"
    elif command -v curl &>/dev/null; then
        curl -L -o "$PTH_FILE" \
            "https://huggingface.co/$HF_REPO/resolve/main/$HF_FILE"
    elif command -v wget &>/dev/null; then
        wget -O "$PTH_FILE" \
            "https://huggingface.co/$HF_REPO/resolve/main/$HF_FILE"
    else
        echo "Error: No download tool available. Install curl, wget, or huggingface-cli."
        exit 1
    fi

    if [ ! -f "$PTH_FILE" ]; then
        echo "Error: Download failed — $PTH_FILE not found."
        exit 1
    fi
    SIZE=$(stat -c%s "$PTH_FILE" 2>/dev/null || stat -f%z "$PTH_FILE" 2>/dev/null || echo "unknown")
    echo "Downloaded $PTH_FILE ($SIZE bytes)"
else
    echo "Weights already exist at $PTH_FILE"
fi

# Step 2: Export to ONNX
echo "Exporting to ONNX..."
python scripts/export-detection-model.py --weights "$PTH_FILE" --output "$ONNX_FILE"

if [ -f "$ONNX_FILE" ]; then
    SIZE=$(stat -c%s "$ONNX_FILE" 2>/dev/null || stat -f%z "$ONNX_FILE" 2>/dev/null || echo "unknown")
    echo "Done: $ONNX_FILE ($SIZE bytes)"
else
    echo "Error: ONNX export failed."
    exit 1
fi
