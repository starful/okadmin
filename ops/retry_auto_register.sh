#!/bin/bash
# Re-run content deploy without waiting for the next launchd tick or the daily guard.
# Usage:
#   ./retry_auto_register.sh              → today's weekday project
#   ./retry_auto_register.sh okcaddie     → that repo only (any day)
# Env: CONTENT_LIMIT, GUIDE_LIMIT, AUTO_WITH_GIT, AUTO_WITH_DEPLOY (same as auto_register)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
    cat <<'EOF'
Usage:
  retry_auto_register.sh              Re-run today's scheduled site under /opt/work.
  retry_auto_register.sh <project>  Re-run one site (e.g. okcaddie, okramen).

Logs append to: /opt/work/ops/logs/auto-register-YYYY-MM-DD.log

Optional env:
  CONTENT_LIMIT=10 GUIDE_LIMIT=3 AUTO_WITH_GIT=1 AUTO_WITH_DEPLOY=1
  AUTO_REGISTER_NO_NOTIFY=1           — macOS 알림/사운드 끄기
  AUTO_REGISTER_ALERT_SOUND=Ping      — 실패 시 사운드 (.aiff 이름, 빈 값=무음)
  AUTO_REGISTER_SUCCESS_SOUND=Glass   — 성공 시만 재생(기본 무음)
EOF
    exit 0
fi

if [ $# -eq 1 ] && [[ "$1" != -* ]]; then
    exec bash "$SCRIPT_DIR/auto_register.sh" --project "$1"
fi

exec bash "$SCRIPT_DIR/auto_register.sh" --force "$@"
