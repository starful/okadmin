#!/bin/bash
set -euo pipefail
APP_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OKADMIN_ROOT="$(tr -d '\r\n' < "${APP_ROOT}/Resources/okadmin-root" || true)"
PYTHON="$(tr -d '\r\n' < "${APP_ROOT}/Resources/python-path" 2>/dev/null || true)"
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
if [[ -z "${OKADMIN_ROOT}" || ! -d "${OKADMIN_ROOT}" ]]; then
  OKADMIN_ROOT="/opt/work/okadmin"
fi
if [[ -z "${PYTHON}" || ! -x "${PYTHON}" ]]; then
  for c in "${OKADMIN_ROOT}/.venv/bin/python" "/opt/homebrew/bin/python3" "/usr/local/bin/python3"; do
    if [[ -x "$c" ]]; then PYTHON="$c"; break; fi
  done
fi
if [[ -z "${PYTHON}" ]]; then
  PYTHON="$(command -v python3 || true)"
fi
if [[ -z "${PYTHON}" || ! -x "${PYTHON}" ]]; then
  osascript -e 'display alert "OK Admin" message "Python3 를 찾을 수 없습니다." as critical' 2>/dev/null || true
  exit 1
fi
export OKADMIN_APP_ROOT="${APP_ROOT}"
exec "${PYTHON}" "${OKADMIN_ROOT}/scripts/okadmin_app_entry.py"
