#!/bin/bash
# Double-click this to open the dashboard. Closing the Terminal window stops it.
cd "$(dirname "$0")"
PORT="${FJOR_STUDIO_PORT:-8422}"

if curl -s -o /dev/null --max-time 2 "http://127.0.0.1:$PORT/" 2>/dev/null; then
  echo "FJOR Studio is already running on port $PORT — opening it."
  open "http://127.0.0.1:$PORT/"
  exit 0
fi

# open the browser once the server answers, not before
( for _ in $(seq 1 60); do
    curl -s -o /dev/null --max-time 1 "http://127.0.0.1:$PORT/" 2>/dev/null && {
      open "http://127.0.0.1:$PORT/"; exit 0; }
    sleep 1
  done ) &

echo "Starting FJOR Studio on http://127.0.0.1:$PORT"
echo "Close this window to stop it."
echo
exec ./scripts/dashboard.sh --port "$PORT"
