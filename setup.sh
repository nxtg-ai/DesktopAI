#!/usr/bin/env bash
# DesktopAI — One-command setup for WSL2 development environment
# Usage: ./setup.sh
set -e

cd "$(dirname "$0")"

echo "========================================"
echo "  DesktopAI Setup"
echo "========================================"

# ── 1. Prerequisites check ──────────────────────────────────────────
echo ""
echo "[1/6] Checking prerequisites..."

MISSING=""

if ! command -v python3 &>/dev/null; then
    MISSING="$MISSING python3"
fi

PY_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
    echo "WARNING: Python $PY_VERSION detected. Python 3.10+ recommended."
fi

if ! command -v cargo &>/dev/null; then
    MISSING="$MISSING cargo/rustup"
fi

if ! command -v pip &>/dev/null && ! command -v pip3 &>/dev/null; then
    MISSING="$MISSING pip"
fi

if [ -n "$MISSING" ]; then
    echo "ERROR: Missing required tools:$MISSING"
    echo "Install them and re-run this script."
    exit 1
fi

echo "  Python:  $(python3 --version)"
echo "  Cargo:   $(cargo --version 2>/dev/null | head -1)"
echo "  OK"

# ── 2. Python virtual environment ───────────────────────────────────
echo ""
echo "[2/6] Setting up Python virtual environment..."

if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo "  Created .venv"
else
    echo "  .venv already exists"
fi

source .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -r backend/requirements.txt
echo "  Python dependencies installed"

# ── 3. Ollama ────────────────────────────────────────────────────────
echo ""
echo "[3/6] Setting up Ollama..."

if ! command -v ollama &>/dev/null; then
    echo "  Installing Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
else
    echo "  Ollama already installed"
fi

# Start Ollama if not running
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "  Starting Ollama server..."
    ollama serve &>/dev/null &
    sleep 3
fi

# ── 4. Pull LLM models ──────────────────────────────────────────────
echo ""
echo "[4/6] Pulling LLM models..."

MODELS=$(curl -s http://localhost:11434/api/tags | python3 -c "import sys,json; print(' '.join(m['name'] for m in json.load(sys.stdin).get('models',[])))" 2>/dev/null || echo "")

if [[ "$MODELS" != *"qwen2.5:7b"* ]]; then
    echo "  Pulling qwen2.5:7b (chat model)..."
    ollama pull qwen2.5:7b
else
    echo "  qwen2.5:7b already available"
fi

if [[ "$MODELS" != *"qwen2.5vl"* ]]; then
    echo "  Pulling qwen2.5vl:7b (vision model)..."
    ollama pull qwen2.5vl:7b
else
    echo "  qwen2.5vl:7b already available"
fi

# ── 5. Rust collector ────────────────────────────────────────────────
echo ""
echo "[5/6] Building Rust collector..."

if rustup target list --installed | grep -q x86_64-pc-windows-gnu; then
    echo "  Windows GNU target already installed"
else
    echo "  Adding Windows GNU target..."
    rustup target add x86_64-pc-windows-gnu
fi

# Check for mingw-w64 linker
if command -v x86_64-w64-mingw32-gcc &>/dev/null; then
    echo "  Building collector for Windows..."
    cd collector
    cargo build --release --target x86_64-pc-windows-gnu 2>&1 | tail -3
    cd ..
    echo "  Collector binary: collector/target/x86_64-pc-windows-gnu/release/desktopai-collector.exe"
else
    echo "  SKIP: mingw-w64 not installed (needed for Windows cross-compilation)"
    echo "  Install with: sudo apt install gcc-mingw-w64-x86-64"
    echo "  Building Linux-only (for tests)..."
    cd collector
    cargo build --release 2>&1 | tail -3
    cd ..
fi

# ── 6. Run tests ─────────────────────────────────────────────────────
echo ""
echo "[6/6] Running tests..."

source .venv/bin/activate
python -m pytest backend/tests/ -m "not integration" -q --tb=line 2>&1 | tail -5
cd collector && cargo test --quiet 2>&1 | tail -5 && cd ..

echo ""
echo "========================================"
echo "  Setup Complete!"
echo "========================================"
echo ""
echo "Start development:"
echo "  ./dogfood.sh                   # Start backend with Ollama"
echo ""
echo "Deploy to Windows:"
echo "  collector/target/x86_64-pc-windows-gnu/release/desktopai-collector.exe"
echo "    → Copy to C:\\temp\\desktopai\\"
echo ""
echo "Open in browser:"
echo "  http://localhost:8000"
echo ""
