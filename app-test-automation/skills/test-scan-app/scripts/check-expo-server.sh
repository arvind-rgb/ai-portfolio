#!/usr/bin/env bash
# Verify the Expo / Metro dev server is running. Start it if not.
# Required because the Bhookle dev build on the sim has no bundled JS — it pulls
# the bundle from this server. Without it the app silently fails to launch.
#
# Usage: check-expo-server.sh <app_dir>
set -euo pipefail

APP_DIR="${1:-}"
if [[ -z "$APP_DIR" || ! -d "$APP_DIR" ]]; then
  echo "❌ Usage: check-expo-server.sh <path-to-bhookleApp-v2>"
  exit 2
fi

is_up() {
  # Metro on 8081 returns "packager-status:running" for /status
  curl -sf --max-time 2 "http://localhost:8081/status" 2>/dev/null | grep -q "packager-status:running"
}

if is_up; then
  echo "✅ Expo dev server already running on :8081"
  exit 0
fi

echo "🚀 Starting Expo dev server in background (cd $APP_DIR && npx expo start --dev-client)…"
LOG=/tmp/bhookle-expo.log
( cd "$APP_DIR" && nohup npx expo start --dev-client > "$LOG" 2>&1 & )

# Poll up to 90s for the server to come up
for i in $(seq 1 90); do
  sleep 1
  if is_up; then
    echo "✅ Expo dev server up after ${i}s (log: $LOG)"
    exit 0
  fi
done

echo "❌ Expo dev server did not start within 90s. Last log lines:"
tail -20 "$LOG" 2>/dev/null
exit 1
