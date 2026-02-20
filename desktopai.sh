#!/usr/bin/env bash
# DesktopAI service control — start/stop/restart/status
# Usage: ./desktopai.sh {start|stop|restart|status}
set -e

cd "$(dirname "$0")"

# Source .env for model config (skip lines with spaces/special chars)
if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    . .env
    set +a
fi

PIDFILE=".desktopai.pid"
LOGFILE="desktopai.log"
HOST="${DESKTOPAI_HOST:-0.0.0.0}"
PORT="${DESKTOPAI_PORT:-8000}"

_check_ollama() {
    if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        return 0
    fi
    echo "Ollama not running. Starting..."
    ollama serve > /dev/null 2>&1 &
    sleep 2
    if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        echo "WARNING: Could not start Ollama. Chat will use context-only mode."
        return 1
    fi
}

_check_models() {
    # Read model names from .env, fall back to defaults
    TEXT_MODEL="${OLLAMA_MODEL:-qwen2.5:7b}"
    VISION_MODEL="${OLLAMA_VISION_MODEL:-qwen2.5vl:7b}"
    FALLBACK_MODEL="${OLLAMA_FALLBACK_MODEL:-}"

    MODELS=$(curl -s http://localhost:11434/api/tags 2>/dev/null | python3 -c "import sys,json; print(' '.join(m['name'] for m in json.load(sys.stdin).get('models',[])))" 2>/dev/null || echo "")

    for MODEL in "$TEXT_MODEL" "$VISION_MODEL" $FALLBACK_MODEL; do
        [ -z "$MODEL" ] && continue
        if [[ "$MODELS" != *"$MODEL"* ]]; then
            echo "Pulling $MODEL (this may take a while first time)..."
            ollama pull "$MODEL"
        fi
    done
    echo "Models ready: text=$TEXT_MODEL vision=$VISION_MODEL${FALLBACK_MODEL:+ fallback=$FALLBACK_MODEL}"
}

_is_running() {
    if [ -f "$PIDFILE" ]; then
        PID=$(cat "$PIDFILE")
        if kill -0 "$PID" 2>/dev/null; then
            return 0
        fi
        rm -f "$PIDFILE"
    fi
    return 1
}

do_start() {
    if _is_running; then
        echo "DesktopAI already running (PID $(cat "$PIDFILE"))"
        echo "  Backend: http://$HOST:$PORT"
        echo "  UI:      http://localhost:$PORT/web/"
        return 0
    fi

    echo "=== DesktopAI Start ==="
    _check_ollama && _check_models

    echo "Starting backend on $HOST:$PORT..."
    source .venv/bin/activate
    nohup uvicorn app.main:app --app-dir backend --host "$HOST" --port "$PORT" \
        --ws-ping-interval 20 --ws-ping-timeout 20 \
        > "$LOGFILE" 2>&1 &
    echo $! > "$PIDFILE"
    sleep 1

    if _is_running; then
        echo "DesktopAI started (PID $(cat "$PIDFILE"))"
        echo "  Backend: http://$HOST:$PORT"
        echo "  UI:      http://localhost:$PORT/web/"
        echo "  Logs:    tail -f $LOGFILE"
        echo ""
        echo "Now start the collector on Windows:"
        echo "  C:\\temp\\desktopai\\desktopai-collector.exe"
    else
        echo "ERROR: Backend failed to start. Check $LOGFILE"
        return 1
    fi
}

do_stop() {
    if ! _is_running; then
        echo "DesktopAI is not running."
        return 0
    fi

    PID=$(cat "$PIDFILE")
    echo "Stopping DesktopAI (PID $PID)..."
    kill "$PID" 2>/dev/null || true
    sleep 1

    # Force kill if still running
    if kill -0 "$PID" 2>/dev/null; then
        kill -9 "$PID" 2>/dev/null || true
    fi

    rm -f "$PIDFILE"
    echo "DesktopAI stopped."
}

do_status() {
    if _is_running; then
        PID=$(cat "$PIDFILE")
        echo "DesktopAI is running (PID $PID)"
        echo "  Backend: http://$HOST:$PORT"
        echo "  UI:      http://localhost:$PORT/web/"

        # Check Ollama
        if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
            echo "  Ollama:  running"
        else
            echo "  Ollama:  NOT running"
        fi

        # Check bridge
        BRIDGE=$(curl -s "http://localhost:$PORT/api/agent/bridge" 2>/dev/null || echo '{}')
        if echo "$BRIDGE" | python3 -c "import sys,json; d=json.load(sys.stdin); exit(0 if d.get('connected') else 1)" 2>/dev/null; then
            echo "  Bridge:  connected (collector attached)"
        else
            echo "  Bridge:  disconnected (start collector on Windows)"
        fi
    else
        echo "DesktopAI is not running."
        echo "  Start with: ./desktopai.sh start"
    fi
}

case "${1:-}" in
    start)   do_start ;;
    stop)    do_stop ;;
    restart) do_stop; do_start ;;
    status)  do_status ;;
    *)
        echo "Usage: ./desktopai.sh {start|stop|restart|status}"
        echo ""
        echo "  start    Start Ollama + backend (background)"
        echo "  stop     Stop the backend"
        echo "  restart  Stop then start"
        echo "  status   Show running state + connections"
        exit 1
        ;;
esac
