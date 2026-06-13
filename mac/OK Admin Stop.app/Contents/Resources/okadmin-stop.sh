#!/bin/bash
PORT="${PORT:-8090}"
export PATH="/opt/homebrew/bin:/usr/local/bin:${PATH:-/usr/bin:/bin}"
if lsof -i ":${PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
  kill $(lsof -i ":${PORT}" -sTCP:LISTEN -t) 2>/dev/null || true
  /usr/bin/osascript -e 'display notification "서버 종료됨" with title "OK Admin"' 2>/dev/null || true
else
  /usr/bin/osascript -e 'display notification "실행 중인 서버 없음" with title "OK Admin"' 2>/dev/null || true
fi
