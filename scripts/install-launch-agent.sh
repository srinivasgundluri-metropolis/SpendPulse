#!/usr/bin/env bash
# Install / reload the spendPulse LaunchAgent (login + KeepAlive).

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.spendpulse.app"
TEMPLATE="$ROOT/launch-agent/${LABEL}.plist.template"
DEST="$HOME/Library/LaunchAgents/${LABEL}.plist"
UID_NUM="$(id -u)"

if [[ ! -f "$TEMPLATE" ]]; then
  echo "Missing template: $TEMPLATE" >&2
  exit 1
fi

chmod +x "$ROOT/scripts/run-server.sh"
mkdir -p "$ROOT/logs" "$HOME/Library/LaunchAgents"

# Fill absolute paths into the installed plist (template stays portable)
sed "s|__SPENDPULSE_ROOT__|${ROOT}|g" "$TEMPLATE" > "$DEST"

# Stop any manual uvicorn on 8787 so launchd can bind the port
pkill -f 'uvicorn app.main:app' 2>/dev/null || true
sleep 0.5

# Unload legacy label if present
LEGACY="com.sgundluri.platinum-ledger"
if launchctl print "gui/${UID_NUM}/${LEGACY}" >/dev/null 2>&1; then
  launchctl bootout "gui/${UID_NUM}/${LEGACY}" 2>/dev/null || true
  rm -f "$HOME/Library/LaunchAgents/${LEGACY}.plist"
  sleep 0.3
fi

if launchctl print "gui/${UID_NUM}/${LABEL}" >/dev/null 2>&1; then
  launchctl bootout "gui/${UID_NUM}/${LABEL}" 2>/dev/null || true
  sleep 0.3
fi

launchctl bootstrap "gui/${UID_NUM}" "$DEST"
launchctl enable "gui/${UID_NUM}/${LABEL}"
launchctl kickstart -k "gui/${UID_NUM}/${LABEL}"

ok=0
for _ in 1 2 3 4 5 6 7 8 9 10; do
  sleep 0.5
  if curl -sf "http://127.0.0.1:8787/api/health" >/dev/null; then
    ok=1
    break
  fi
done

if [ "$ok" -eq 1 ]; then
  echo "spendPulse LaunchAgent installed and running → http://127.0.0.1:8787"
else
  echo "LaunchAgent loaded, but health check failed. Check:"
  echo "  tail -40 $ROOT/logs/server.err.log"
  exit 1
fi

echo "Manage with:"
echo "  launchctl kickstart -k gui/${UID_NUM}/${LABEL}   # restart"
echo "  launchctl bootout gui/${UID_NUM}/${LABEL}        # stop/unload"
