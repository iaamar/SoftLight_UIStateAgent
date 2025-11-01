#!/usr/bin/env bash
set -e

echo "[*] Starting FastAPI backend"

# Simple approach: always use xvfb-run for headed mode, headless otherwise
if [ "${VIEW_BROWSER}" = "true" ] || [ "${PLAYWRIGHT_HEADLESS}" = "false" ]; then
  echo "[*] Starting with virtual display (xvfb-run) for headed browser"
  echo "[*] Connect to http://localhost:7900/vnc.html to view the browser"
  
  # Start x11vnc and noVNC in background first
  Xvfb :99 -screen 0 1920x1080x24 -ac +extension RANDR > /tmp/xvfb.log 2>&1 &
  sleep 2
  
  x11vnc -display :99 -forever -shared -nopw -rfbport 5900 -modtweak -xkb > /tmp/x11vnc.log 2>&1 &
  sleep 1
  
  websockify --web=/usr/share/novnc/ 7900 localhost:5900 > /tmp/novnc.log 2>&1 &
  sleep 1
  
  echo "[*] Display services started. Running backend with DISPLAY=:99"
  export DISPLAY=:99
  export PLAYWRIGHT_HEADLESS=false
  exec python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
else
  echo "[*] Running in headless mode"
  exec python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
fi


