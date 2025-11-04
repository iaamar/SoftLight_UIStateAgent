#!/bin/bash
# SoftLight UI State Agent - Quick Start (Backend Local, Frontend/MCP Docker)

set -e
cd "$(dirname "$0")"

clear
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🚀 SoftLight UI State Agent"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Clean up any existing processes
echo "🧹 Cleaning up existing processes..."
echo "   Checking for existing backend processes..."
pkill -f "python backend/main.py" 2>/dev/null && echo "   ✓ Killed python backend/main.py" || echo "   - No python backend/main.py process found"
pkill -f "uvicorn backend.main" 2>/dev/null && echo "   ✓ Killed uvicorn backend.main" || echo "   - No uvicorn backend.main process found"
pkill -f "uvicorn.*8000" 2>/dev/null && echo "   ✓ Killed uvicorn processes on port 8000" || echo "   - No uvicorn processes on port 8000 found"

# Kill any process using port 8000 (more aggressive cleanup)
echo "🔌 Freeing port 8000..."
for i in {1..3}; do
    if lsof -ti:8000 >/dev/null 2>&1; then
        if [ $i -eq 1 ]; then
            echo "   Killing processes on port 8000..."
        fi
        lsof -ti:8000 | xargs kill -9 2>/dev/null || true
        sleep 2
    else
        break
    fi
done
# Final check - if still occupied, show warning
if lsof -ti:8000 >/dev/null 2>&1; then
    echo "   ⚠️  Warning: Port 8000 still in use. Attempting to continue..."
    echo "   PID(s) using port 8000: $(lsof -ti:8000 | tr '\n' ' ')"
else
    echo "   ✅ Port 8000 is free"
fi

# Setup conda environment
echo "📦 Activating conda environment..."
echo "   Initializing conda..."
eval "$(conda shell.bash hook)" 2>/dev/null || {
    echo "   ❌ Conda not found. Please install conda/miniconda first."
    exit 1
}
echo "   ✓ Conda initialized"

# Create env only if it doesn't exist
if ! conda env list | grep -q "^softlight "; then
    echo "   Creating 'softlight' environment (one-time setup)..."
    conda create -n softlight python=3.11 -y
fi

echo "   Activating 'softlight' environment..."
conda activate softlight
echo "   ✓ Conda environment activated"

# Install dependencies
echo "📦 Installing dependencies..."
pip install -r backend/requirements.txt

# Ensure Playwright is installed
echo "📦 Installing Playwright browser..."
playwright install chromium || echo "   ⚠️  Playwright installation had issues (continuing anyway)"

# Load environment variables from .env file
if [ -f .env ]; then
    echo "📋 Loading environment variables..."
    ENV_COUNT=$(cat .env | grep -v '^#' | grep -v '^$' | wc -l | tr -d ' ')
    export $(cat .env | grep -v '^#' | grep -v '^$' | xargs)
    echo "   ✓ Loaded $ENV_COUNT environment variables from .env"
else
    echo "   ⚠️  No .env file found (using defaults)"
fi

# Set defaults for local development (browser always visible)
export PLAYWRIGHT_HEADLESS=false
export CREWAI_LLM_MODEL=${CREWAI_LLM_MODEL:-claude-sonnet-4-5-20250929}

# Start Docker services (frontend and MCP only, backend runs locally)
echo "🐳 Starting Docker services (frontend & MCP)..."
cd docker
if ! docker compose up -d frontend mcp 2>&1; then
    echo "   ❌ Failed to start Docker services"
    echo "   Check logs with: cd docker && docker compose logs"
    cd ..
    exit 1
fi

# Wait a moment for containers to initialize
echo "   Waiting for containers to initialize..."
sleep 3

# Verify containers are running
echo "   Verifying container status..."
CONTAINER_STATUS=$(docker compose ps --format json 2>/dev/null || docker compose ps)
if echo "$CONTAINER_STATUS" | grep -q "Up"; then
    echo "   ✅ Docker services started successfully"
    echo "   Container status:"
    docker compose ps | grep -E "(NAME|frontend|mcp)" | sed 's/^/      /'
else
    echo "   ⚠️  Warning: Some containers may not be running"
    echo "   Container status:"
    docker compose ps | sed 's/^/      /'
    echo "   Check logs with: cd docker && docker compose logs frontend"
    echo "   Continuing anyway..."
fi
cd ..

echo ""
echo "✅ Ready (macOS - Browser will open automatically)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📱 Frontend:  http://localhost:3000"
echo "🔌 Backend:   http://localhost:8000 (running locally)"
echo "🪟 Browser:   Opens automatically on your screen for login"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Press Ctrl+C to stop"
echo ""

# Run backend locally (browser will open automatically for login)
echo ""
echo "🚀 Starting backend server..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
# Use python -u to disable buffering for immediate log output
python -u -m uvicorn backend.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --reload \
  --log-level info \
  --access-log
