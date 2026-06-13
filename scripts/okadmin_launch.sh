#!/bin/bash
# macOS .app / CLI: server + UI (browser | app)
set -euo pipefail

UI_MODE="${1:-app}"
OKADMIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=okadmin_env.sh
source "${OKADMIN_ROOT}/scripts/okadmin_env.sh"
okadmin_env_init "${OKADMIN_ROOT}"

PORT="${PORT:-8090}"
OKADMIN_PYTHON="$(okadmin_resolve_python)"

if ! "${OKADMIN_PYTHON}" -c "import dotenv" 2>/dev/null; then
  /usr/bin/osascript -e "display alert \"OK Admin\" message \"Python 패키지 없음.\n${OKADMIN_PYTHON} -m pip install -r requirements.txt\" as critical" 2>/dev/null || true
  exit 1
fi

# app 모드: 단일 Python 프로세스(Flask 스레드+webview) → Dock 아이콘 1개
if [[ "${UI_MODE}" == "app" ]]; then
  exec "${OKADMIN_PYTHON}" "${OKADMIN_ROOT}/scripts/okadmin_app_entry.py" app
fi

# dev/browser: 기존 방식 (서버 분리 + 브라우저)
LOG_DIR="${HOME}/Library/Logs/okadmin"
LOG_FILE="${LOG_DIR}/server.log"
mkdir -p "${LOG_DIR}"

if ! lsof -i ":${PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
  cd "${OKADMIN_ROOT}"
  nohup ./start.sh >>"${LOG_FILE}" 2>&1 &
  disown 2>/dev/null || true
  for _ in $(seq 1 80); do
    curl -sf "http://127.0.0.1:${PORT}/healthz" >/dev/null 2>&1 && break
    sleep 0.25
  done
fi

exec "${OKADMIN_PYTHON}" "${OKADMIN_ROOT}/scripts/okadmin_ui.py" --mode browser
