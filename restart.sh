#!/bin/bash
# 8090 점유 프로세스 종료 후 start.sh 실행
set -euo pipefail
OKADMIN_ROOT="$(cd "$(dirname "$0")" && pwd)"
PORT="${PORT:-8090}"
if lsof -i ":${PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
  kill $(lsof -i ":${PORT}" -sTCP:LISTEN -t) 2>/dev/null || true
  sleep 1
fi
exec "${OKADMIN_ROOT}/start.sh"
