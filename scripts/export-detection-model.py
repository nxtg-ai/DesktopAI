#!/usr/bin/env python3
"""Export UI-DETR-1 model from PyTorch (.pth) to ONNX format.

Requires: pip install rfdetr[onnxexport]

Usage:
    python scripts/export-detection-model.py [--weights PATH] [--output PATH]
"""

import argparse
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Export UI-DETR-1 to ONNX")
    parser.add_argument(
        "--weights",
        default="models/ui-detr/model.pth",
        help="Path to model.pth weights (default: models/ui-detr/model.pth)",
    )
    parser.add_argument(
        "--output",
        default="models/ui-detr/ui-detr-1.onnx",
        help="Output ONNX path (default: models/ui-detr/ui-detr-1.onnx)",
    )
    args = parser.parse_args()

    weights_path = Path(args.weights)
    output_path = Path(args.output)

    if not weights_path.exists():
        print(f"Error: Weights file not found at {weights_path}", file=sys.stderr)
        print("Run: bash scripts/download-detection-model.sh", file=sys.stderr)
        sys.exit(1)

    try:
        from rfdetr import RFDETRMedium
    except ImportError:
        print(
            "Error: rfdetr not installed. Run: pip install rfdetr[onnxexport]",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Loading UI-DETR-1 weights from {weights_path}...")
    model = RFDETRMedium(pretrain_weights=str(weights_path), resolution=576)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # rfdetr export() writes to output_dir/inference_model.onnx
    export_dir = output_path.parent
    print(f"Exporting to ONNX (dir={export_dir})...")
    model.export(output_dir=str(export_dir))

    intermediate = export_dir / "inference_model.onnx"
    if intermediate.exists() and intermediate != output_path:
        intermediate.rename(output_path)
    elif not output_path.exists():
        print("Error: Export did not produce output file.", file=sys.stderr)
        sys.exit(1)

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"Export complete: {output_path} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
