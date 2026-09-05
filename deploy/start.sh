#!/bin/sh
set -eu

PORT="${PORT:-3000}"

/opt/venv/bin/uvicorn backend.app.main:app \
  --host 127.0.0.1 \
  --port 8000 \
  --proxy-headers \
  --forwarded-allow-ips='*' &
backend_pid=$!

cleanup() {
  kill "$backend_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

cd /app/frontend
HOSTNAME=0.0.0.0 PORT="$PORT" node server.js
