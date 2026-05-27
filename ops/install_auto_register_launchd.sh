#!/bin/bash

set -euo pipefail

AGENT_NAME="com.starful.auto-register"
AGENT_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$AGENT_DIR/$AGENT_NAME.plist"
SCRIPT_PATH="$(cd "$(dirname "$0")" && pwd)/auto_register.sh"

HOUR="${1:-9}"
MINUTE="${2:-0}"

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
    <string>$HOUR</string>
    <key>TARGET_MINUTE</key>
    <string>$MINUTE</string>
  </dict>

  <key>StartInterval</key>
  <integer>3600</integer>

  <key>RunAtLoad</key>
  <true/>
</dict>
</plist>
EOF

launchctl unload "$PLIST_PATH" >/dev/null 2>&1 || true
launchctl load "$PLIST_PATH"

echo "Installed: $PLIST_PATH"
echo "Schedule: checked every hour, runs once/day after $(printf '%02d:%02d' "$HOUR" "$MINUTE")"
echo "Manual run: /bin/bash $SCRIPT_PATH"
