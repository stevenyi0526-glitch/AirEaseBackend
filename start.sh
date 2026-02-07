#!/bin/bash
# AirEase Backend Start Script
# Usage: ./start.sh

set -e

# Resolve script directory
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
VENV_DIR="$PROJECT_ROOT/.venv"

echo "🛫 AirEase Backend Launcher"
echo "============================"

# Check if .venv exists
if [ ! -d "$VENV_DIR" ]; then
    echo "❌ Virtual environment not found at $VENV_DIR"
    echo "   Create one with: python3 -m venv $VENV_DIR"
    exit 1
fi

# Activate virtual environment
echo "🐍 Activating virtual environment..."
source "$VENV_DIR/bin/activate"

# Check if dependencies are installed
if ! python -c "import fastapi" 2>/dev/null; then
    echo "📦 Installing dependencies..."
    pip install -r "$SCRIPT_DIR/requirements.txt"
fi

# Change to backend directory
cd "$SCRIPT_DIR"

# Load .env file if it exists
if [ -f "$SCRIPT_DIR/.env" ]; then
    echo "🔑 Loading .env file..."
fi

echo ""
echo "🚀 Starting AirEase Backend Server..."
echo "   URL: http://0.0.0.0:8000"
echo "   Docs: http://localhost:8000/docs"
echo ""

# Start the server
python run.py
