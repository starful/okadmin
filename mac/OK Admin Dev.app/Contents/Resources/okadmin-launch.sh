#!/bin/bash
set -euo pipefail
APP_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OKADMIN_ROOT="$(cat "${APP_ROOT}/Resources/okadmin-root" 2>/dev/null | tr -d '\r\n' || true)"
if [[ -z "${OKADMIN_ROOT}" || ! -d "${OKADMIN_ROOT}" ]]; then
  OKADMIN_ROOT="/opt/work/okadmin"
fi
export PATH="/opt/homebrew/bin:/usr/local/bin:${PATH:-/usr/bin:/bin:/usr/sbin:/sbin}"
exec "${OKADMIN_ROOT}/scripts/okadmin_launch.sh" browser
