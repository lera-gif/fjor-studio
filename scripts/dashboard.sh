#!/bin/bash
# Launcher for the dashboard. Uses the venv when it is readable, otherwise the
# system python -- the dashboard's only dependency is pyyaml, which both have.
cd "$(dirname "$0")/.."
PY="./.venv/bin/python"
[ -r "./.venv/pyvenv.cfg" ] || PY="$(command -v python3 || echo /usr/bin/python3)"
export PYTHONPATH="$PWD"

# A second instance would bind-fail with a bare traceback. Say what is actually
# wrong instead, because "Address already in use" usually means it is fine.
PORT="8422"
for i in "$@"; do [ "$prev" = "--port" ] && PORT="$i"; prev="$i"; done
if curl -s -o /dev/null --max-time 2 "http://127.0.0.1:$PORT/" 2>/dev/null; then
  echo "FJOR Studio is already serving on http://127.0.0.1:$PORT — nothing to do."
  exit 0
fi

exec "$PY" -m fjor_studio.cli --home "$PWD" dashboard "$@"
