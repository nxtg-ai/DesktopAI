#!/usr/bin/env bash
# Deploy UI-DETR-1 ONNX model to the Windows collector directory.
#
# Copies models/ui-detr/ui-detr-1.onnx to the Windows deployment path
# via the WSL2 <-> Windows filesystem bridge.
#
# Usage:
#   bash scripts/deploy-detection-model.sh
#
# The collector expects the model at models/ui-detr/ui-detr-1.onnx
# relative to its working directory (C:\temp\desktopai\).

set -euo pipefail

ONNX_FILE="models/ui-detr/ui-detr-1.onnx"
WIN_BASE="/mnt/c/temp/desktopai"
WIN_DEST="$WIN_BASE/models/ui-detr"

if [ ! -f "$ONNX_FILE" ]; then
    echo "Error: $ONNX_FILE not found. Run: bash scripts/download-detection-model.sh"
    exit 1
fi

if [ ! -d "$WIN_BASE" ]; then
    echo "Error: Windows deployment dir not found at $WIN_BASE"
    exit 1
fi

mkdir -p "$WIN_DEST"
cp "$ONNX_FILE" "$WIN_DEST/ui-detr-1.onnx"

SIZE=$(stat -c%s "$WIN_DEST/ui-detr-1.onnx" 2>/dev/null || echo "unknown")
echo "Deployed: $WIN_DEST/ui-detr-1.onnx ($SIZE bytes)"
echo "Collector will load detection model on next observe command."
