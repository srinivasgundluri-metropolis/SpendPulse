#!/usr/bin/env bash
# Wrapper for launchd (no login shell). Keeps spendPulse running.

set -euo pipefail

ROOT="${SPENDPULSE_ROOT:-${SPEND_LEDGER_ROOT:-${PLATINUM_LEDGER_ROOT:-$HOME/Projects/amex-spend-tracker}}}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8787}"

cd "$ROOT" || exit 1
mkdir -p "$ROOT/logs"

UVICORN=""
for candidate in \
  "${UVICORN_BIN:-}" \
  "$ROOT/.venv/bin/uvicorn" \
  "$(command -v uvicorn 2>/dev/null || true)"; do
  if [ -n "$candidate" ] && [ -x "$candidate" ]; then
    UVICORN="$candidate"
    break
  fi
done

if [ -z "$UVICORN" ]; then
  echo "uvicorn not found. Create the venv and install deps first:" >&2
  echo "  cd \"$ROOT\" && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 127
fi

# Prefer the venv python that owns this uvicorn
PYTHON="$ROOT/.venv/bin/python3"
if [ ! -x "$PYTHON" ]; then
  PYTHON="$(command -v python3)"
fi

echo $$ >"$ROOT/logs/server.pid"
exec "$UVICORN" app.main:app --host "$HOST" --port "$PORT"
