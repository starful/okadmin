#!/bin/bash

set -euo pipefail

AGENT_NAME="com.starful.auto-register"
PLIST_PATH="$HOME/Library/LaunchAgents/$AGENT_NAME.plist"
OPS_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="${WORK_ROOT:-$(cd "$OPS_DIR/../.." && pwd)}"
STATE_FILE="$OPS_DIR/state/auto-register.last-run"
LOG_DIR="$OPS_DIR/logs"

echo "== Auto Register Status =="
echo "Agent: $AGENT_NAME"
echo "Plist: $PLIST_PATH"
echo ""

if [ -f "$PLIST_PATH" ]; then
    echo "[Schedule]"
    /usr/libexec/PlistBuddy -c "Print :RunAtLoad" "$PLIST_PATH" 2>/dev/null || true
    /usr/libexec/PlistBuddy -c "Print :StartInterval" "$PLIST_PATH" 2>/dev/null || true
    echo "TARGET_HOUR=$(/usr/libexec/PlistBuddy -c 'Print :EnvironmentVariables:TARGET_HOUR' "$PLIST_PATH" 2>/dev/null || echo '?')"
    echo "TARGET_MINUTE=$(/usr/libexec/PlistBuddy -c 'Print :EnvironmentVariables:TARGET_MINUTE' "$PLIST_PATH" 2>/dev/null || echo '?')"
else
    echo "Plist not found."
fi

echo ""
echo "[Launchctl]"
launchctl print "gui/$(id -u)/$AGENT_NAME" 2>/dev/null | awk '/state =|last exit code =|runs =|pid =/ {print}' || echo "Agent not loaded."

echo ""
echo "[Last run]"
if [ -f "$STATE_FILE" ]; then
    echo "Last successful date: $(cat "$STATE_FILE")"
else
    echo "No run state yet."
fi

echo ""
echo "[Recent logs]"
latest_log="$(ls -t "$LOG_DIR"/auto-register-*.log 2>/dev/null | head -n 1 || true)"
if [ -n "${latest_log:-}" ] && [ -f "$latest_log" ]; then
    echo "Latest log: $latest_log"
    awk 'NR>=(n-20){print} {n=NR}' "$latest_log"
else
    echo "No logs found."
fi

if [[ "$OSTYPE" == "darwin"* ]]; then
    hour=$(/usr/libexec/PlistBuddy -c 'Print :EnvironmentVariables:TARGET_HOUR' "$PLIST_PATH" 2>/dev/null || echo '?')
    minute=$(/usr/libexec/PlistBuddy -c 'Print :EnvironmentVariables:TARGET_MINUTE' "$PLIST_PATH" 2>/dev/null || echo '?')
    last_run="none"
    if [ -f "$STATE_FILE" ]; then
        last_run="$(cat "$STATE_FILE" 2>/dev/null || echo 'unknown')"
    fi
    osascript -e "display notification \"Schedule ${hour}:$(printf '%02d' "$minute"), last run: ${last_run}\" with title \"Auto Register Status\" subtitle \"조회 완료\" " 2>/dev/null || true
fi
