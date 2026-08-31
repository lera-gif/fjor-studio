#!/bin/bash
# Double-click to open FJOR Studio. Closing this Terminal window stops it.
#
# It does not just look for something listening on the port. A server can hold
# the port and still be unable to read its own config -- that happened on
# 2026-08-27, and the old version of this file cheerfully reported "already
# running" and opened a dashboard where every action failed. So it asks the
# server a real question, and takes over from an instance that cannot answer.
cd "$(dirname "$0")"
PORT="${FJOR_STUDIO_PORT:-8422}"
URL="http://127.0.0.1:$PORT"

# --- is something there, and does it work? ----------------------------------
answers()  { curl -s -o /dev/null --max-time 2 "$URL/" 2>/dev/null; }
healthy()  { curl -s --max-time 5 "$URL/api/state" 2>/dev/null | grep -q '"jobs"'; }
why_not()  { curl -s --max-time 5 "$URL/api/state" 2>/dev/null | head -c 300; }

# --- stop whatever is on the port, if it is ours ----------------------------
stop_it() {
  local pids stale=""
  pids="$(lsof -ti "tcp:$PORT" -sTCP:LISTEN 2>/dev/null)"
  for pid in $pids; do
    case "$(ps -o command= -p "$pid" 2>/dev/null)" in
      *fjor_studio*) stale="$stale $pid" ;;
      *) echo "Port $PORT is held by something that is not FJOR Studio (pid $pid)."
         echo "Close it, or set FJOR_STUDIO_PORT to a free port."; return 1 ;;
    esac
  done
  [ -z "$stale" ] && return 0
  echo "Stopping the old instance ($stale)…"
  kill $stale 2>/dev/null
  for _ in $(seq 1 10); do
    answers || return 0
    sleep 1
  done
  kill -9 $stale 2>/dev/null      # it ignored a polite request
  sleep 1
  return 0
}

if [ "${FJOR_STUDIO_RESTART:-}" = "1" ] && answers; then
  echo "Restarting FJOR Studio on port $PORT."
  stop_it || exit 1
elif answers; then
  if healthy; then
    echo "FJOR Studio is already running on $PORT — opening it."
    open "$URL/"
    exit 0
  fi
  echo "Something is serving $PORT but cannot answer for itself:"
  echo
  echo "  $(why_not)"
  echo
  echo "Replacing it with a fresh one."
  stop_it || exit 1
fi

# open the browser once the server answers, not before
( for _ in $(seq 1 60); do
    if healthy; then open "$URL/"; exit 0; fi
    sleep 1
  done
  echo "The dashboard did not come up. The error above says why." ) &

echo "Starting FJOR Studio on $URL"
echo "Close this window to stop it."
echo
exec ./scripts/dashboard.sh --port "$PORT"
