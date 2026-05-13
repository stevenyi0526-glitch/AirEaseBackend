#!/bin/bash
# AirEase Backend Start Script
# Usage: ./start.sh
#
# Behavior:
#   1. Kill anything bound to port 8000.
#   2. Quit any existing GNU screen session named "airease-backend".
#   3. Launch uvicorn inside a fresh detached screen session.
#
# Attach later with:  screen -r airease-backend
# Detach from inside: Ctrl-A then D

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$PROJECT_ROOT/.venv"
PORT=8000
SCREEN_NAME="airease-backend"

echo "🛫 AirEase Backend Launcher"
echo "============================"

# --- Pre-flight: venv -------------------------------------------------------
if [ ! -d "$VENV_DIR" ]; then
    echo "❌ Virtual environment not found at $VENV_DIR"
    echo "   Create one with: python3 -m venv $VENV_DIR"
    exit 1
fi

# --- Pre-flight: screen binary ---------------------------------------------
if ! command -v screen >/dev/null 2>&1; then
    echo "❌ GNU 'screen' is required but not installed."
    echo "   Install with: brew install screen   (macOS)"
    echo "                  sudo apt install screen  (Debian/Ubuntu)"
    exit 1
fi

# --- Clean: port 8000 -------------------------------------------------------
echo "🧹 Releasing port $PORT..."
PIDS=$(lsof -ti :"$PORT" 2>/dev/null || true)
if [ -n "$PIDS" ]; then
    echo "   killing PID(s): $PIDS"
    kill -9 $PIDS 2>/dev/null || true
fi

# --- Clean: existing screen session ----------------------------------------
echo "🧹 Removing any existing screen session '$SCREEN_NAME'..."
screen -S "$SCREEN_NAME" -X quit >/dev/null 2>&1 || true
# Also wipe dead sessions to keep `screen -ls` tidy
screen -wipe >/dev/null 2>&1 || true
sleep 1

# --- Launch -----------------------------------------------------------------
echo ""
echo "🚀 Starting backend in detached screen '$SCREEN_NAME'..."
echo "   URL : http://0.0.0.0:$PORT"
echo "   Docs: http://localhost:$PORT/docs"
echo ""

screen -dmS "$SCREEN_NAME" bash -c "cd '$SCRIPT_DIR' && source '$VENV_DIR/bin/activate' && exec python -m uvicorn app.main:app --host 0.0.0.0 --port $PORT --reload"

sleep 2
if screen -list | grep -q "\.${SCREEN_NAME}\b"; then
    echo "✅ Backend started."
    echo "   Attach : screen -r $SCREEN_NAME"
    echo "   Detach : Ctrl-A then D"
    echo "   Stop   : screen -S $SCREEN_NAME -X quit"
else
    echo "❌ Failed to launch screen session. Check uvicorn install."
    exit 1
fi
