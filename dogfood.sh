#!/usr/bin/env bash
# Quick dogfood launcher for DesktopAI
# Usage: ./dogfood.sh
set -e

cd "$(dirname "$0")"

echo "=== DesktopAI Dogfood ==="

# 1. Check Ollama is running
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "Ollama not running. Starting..."
    ollama serve &
    sleep 2
fi

# 2. Verify models are available
echo "Checking models..."
MODELS=$(curl -s http://localhost:11434/api/tags | python3 -c "import sys,json; print(' '.join(m['name'] for m in json.load(sys.stdin).get('models',[])))" 2>/dev/null || echo "")
if [[ "$MODELS" != *"qwen2.5:7b"* ]]; then
    echo "Pulling qwen2.5:7b..."
    ollama pull qwen2.5:7b
fi
if [[ "$MODELS" != *"qwen2.5vl"* ]]; then
    echo "Pulling qwen2.5vl:7b..."
    ollama pull qwen2.5vl:7b
fi
echo "Models ready: qwen2.5:7b, qwen2.5vl:7b"

# 3. Warm up model (avoids first-request cold-start timeout)
echo "Warming up models..."
curl -s http://localhost:11434/api/generate -d '{"model":"qwen2.5:7b","prompt":"hello","stream":false}' > /dev/null 2>&1 &

# 4. Activate venv and start backend
echo "Starting backend..."
source .venv/bin/activate
exec uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port 8000 --reload
