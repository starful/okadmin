#!/bin/bash

set -euo pipefail

AGENT_NAME="com.starful.auto-register-plan"
AGENT_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$AGENT_DIR/$AGENT_NAME.plist"
SCRIPT_PATH="$(cd "$(dirname "$0")" && pwd)/notify_auto_register_plan.sh"

# Auto-register run time for message text
TARGET_HOUR="${1:-9}"
TARGET_MINUTE="${2:-0}"

# Plan notification times (morning/evening)
MORNING_HOUR="${3:-8}"
MORNING_MINUTE="${4:-30}"
EVENING_HOUR="${5:-20}"
EVENING_MINUTE="${6:-30}"

mkdir -p "$AGENT_DIR"

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$AGENT_NAME</string>

  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$SCRIPT_PATH</string>
  </array>

  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>TARGET_HOUR</key>
    <string>$TARGET_HOUR</string>
    <key>TARGET_MINUTE</key>
    <string>$TARGET_MINUTE</string>
  </dict>

  <key>StartCalendarInterval</key>
  <array>
    <dict>
      <key>Hour</key><integer>$MORNING_HOUR</integer>
      <key>Minute</key><integer>$MORNING_MINUTE</integer>
    </dict>
    <dict>
      <key>Hour</key><integer>$EVENING_HOUR</integer>
      <key>Minute</key><integer>$EVENING_MINUTE</integer>
    </dict>
  </array>

  <key>RunAtLoad</key>
  <true/>
</dict>
</plist>
EOF

launchctl unload "$PLIST_PATH" >/dev/null 2>&1 || true
launchctl load "$PLIST_PATH"

echo "Installed: $PLIST_PATH"
echo "Notify schedule: $(printf '%02d:%02d' "$MORNING_HOUR" "$MORNING_MINUTE"), $(printf '%02d:%02d' "$EVENING_HOUR" "$EVENING_MINUTE")"
echo "Run target shown in message: $(printf '%02d:%02d' "$TARGET_HOUR" "$TARGET_MINUTE")"
