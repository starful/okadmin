#!/bin/bash

set -euo pipefail

FORCE=0
ONLY_PROJECT=""
while [ $# -gt 0 ]; do
    case "$1" in
        --force|-f) FORCE=1; shift ;;
        --project)
            ONLY_PROJECT="${2:?--project needs a directory name under /opt/work}"
            shift 2
            ;;
        *)
            echo "Unknown option: $1 (use --force, --project DIR)" >&2
            exit 1
            ;;
    esac
done

if [ -n "$ONLY_PROJECT" ]; then
    FORCE=1
fi

OPS_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="${WORK_ROOT:-$(cd "$OPS_DIR/../.." && pwd)}"
LOG_DIR="$OPS_DIR/logs"
mkdir -p "$LOG_DIR"
STATE_DIR="$OPS_DIR/state"
mkdir -p "$STATE_DIR"
STATE_FILE="$STATE_DIR/auto-register.last-run"

DATE_TAG="$(date '+%Y-%m-%d')"
LOG_FILE="$LOG_DIR/auto-register-$DATE_TAG.log"

# Notifications (macOS): set AUTO_REGISTER_NO_NOTIFY=1 to disable.
# Failure sound: AUTO_REGISTER_ALERT_SOUND=Basso (default) or Ping/Glass, or empty to mute sound only.
darwin_notify() {
    local title="$1" subtitle="$2" sound="${3:-}"
    [[ "${AUTO_REGISTER_NO_NOTIFY:-}" == "1" ]] && return 0
    [[ "$OSTYPE" != "darwin"* ]] && return 0
    osascript -e "display notification \"${subtitle//\"/\\\"}\" with title \"${title//\"/\\\"}\"" 2>/dev/null || true
    if [[ -n "$sound" ]]; then
        local wav="/System/Library/Sounds/${sound}.aiff"
        [[ -f "$wav" ]] && afplay "$wav" 2>/dev/null || true
    fi
}

_auto_register_err_trap() {
    trap - ERR
    local ec=$?
    echo "[$(date '+%F %T')] ERROR: pipeline/command failed (exit $ec). Log: $LOG_FILE" | tee -a "$LOG_FILE"
    local fail_sound="${AUTO_REGISTER_ALERT_SOUND-Basso}"
    if [[ -z "$fail_sound" || "$fail_sound" == "none" ]]; then
        fail_sound=""
    fi
    darwin_notify "Auto Register 실패" "$LOG_FILE 를 확인하세요 (exit $ec)" "$fail_sound"
    exit "$ec"
}
trap '_auto_register_err_trap' ERR

# Default generation policy: content 10 / guide 3
export CONTENT_LIMIT="${CONTENT_LIMIT:-6}"
export GUIDE_LIMIT="${GUIDE_LIMIT:-3}"

# Deployment policy
AUTO_WITH_GIT="${AUTO_WITH_GIT:-1}"
AUTO_WITH_DEPLOY="${AUTO_WITH_DEPLOY:-1}"
TARGET_HOUR="${TARGET_HOUR:-9}"
TARGET_MINUTE="${TARGET_MINUTE:-0}"
AUTO_REGISTER_RUN=1
export AUTO_REGISTER_RUN
export TERM="${TERM:-xterm}"

run_deploy() {
    local project="$1"
    local mode="${2:---content-only}"

    local cmd=("./deploy.sh" "$mode")
    if [ "$AUTO_WITH_GIT" = "1" ]; then
        cmd+=("--with-git")
    fi
    if [ "$AUTO_WITH_DEPLOY" = "1" ]; then
        cmd+=("--with-deploy")
    fi

    {
        echo ""
        echo "=================================================="
        echo "[$(date '+%F %T')] $project ${cmd[*]}"
        echo "=================================================="
    } | tee -a "$LOG_FILE"

    (
        cd "$ROOT/$project"
        "${cmd[@]}"
    ) >>"$LOG_FILE" 2>&1
}

# 일요일: 하테나 2종(클라우드 비교 + Python 라이브러리). 건수는 환경변수로 조절 가능.
HATENA_MAX_CLOUD="${HATENA_MAX_CLOUD:-6}"
HATENA_MAX_PY="${HATENA_MAX_PY:-6}"

run_hatena_task() {
    local task="$1"
    local max_posts="${2:-1}"

    {
        echo ""
        echo "=================================================="
        echo "[$(date '+%F %T')] hatena python3 unified_poster.py $task --max_posts $max_posts"
        echo "=================================================="
    } | tee -a "$LOG_FILE"

    (
        cd "$ROOT/hatena"
        python3 unified_poster.py "$task" --max_posts "$max_posts"
    ) >>"$LOG_FILE" 2>&1
}

run_hatena_sunday() {
    if [ ! -d "$ROOT/hatena" ]; then
        echo "[$(date '+%F %T')] ERROR: no directory $ROOT/hatena" | tee -a "$LOG_FILE"
        exit 1
    fi
    run_hatena_task cloud "$HATENA_MAX_CLOUD"
    run_hatena_task py "$HATENA_MAX_PY"
}

weekday="$(date '+%u')" # 1=Mon ... 7=Sun
today="$(date '+%F')"
now_hm="$(date '+%H%M')"
target_hm="$(printf '%02d%02d' "$TARGET_HOUR" "$TARGET_MINUTE")"

# Catch-up guard (skipped with --force / --project):
# - run only after target time
# - run only once per day
if [ "$FORCE" != "1" ]; then
    if [ "$now_hm" -lt "$target_hm" ]; then
        trap - ERR
        echo "[$(date '+%F %T')] Skip: before target time ${TARGET_HOUR}:$(printf '%02d' "$TARGET_MINUTE")" >>"$LOG_FILE"
        exit 0
    fi

    if [ -f "$STATE_FILE" ] && [ "$(cat "$STATE_FILE" 2>/dev/null || true)" = "$today" ]; then
        trap - ERR
        echo "[$(date '+%F %T')] Skip: already executed today" >>"$LOG_FILE"
        exit 0
    fi
else
    echo "[$(date '+%F %T')] Forced run (bypass time / once-per-day guards)" | tee -a "$LOG_FILE"
fi

{
    echo "[$(date '+%F %T')] Auto register started (weekday=$weekday)"
    echo "CONTENT_LIMIT=$CONTENT_LIMIT, GUIDE_LIMIT=$GUIDE_LIMIT"
    echo "AUTO_WITH_GIT=$AUTO_WITH_GIT, AUTO_WITH_DEPLOY=$AUTO_WITH_DEPLOY"
} | tee -a "$LOG_FILE"

if [ -n "$ONLY_PROJECT" ]; then
    if [ ! -d "$ROOT/$ONLY_PROJECT" ]; then
        echo "[$(date '+%F %T')] ERROR: no directory $ROOT/$ONLY_PROJECT" | tee -a "$LOG_FILE"
        trap - ERR
        _fs="${AUTO_REGISTER_ALERT_SOUND-Basso}"
        [[ -z "$_fs" || "$_fs" == "none" ]] && _fs=""
        darwin_notify "Auto Register 실패" "디렉터리 없음: $ONLY_PROJECT" "$_fs"
        exit 1
    fi
    echo "[$(date '+%F %T')] Single project: $ONLY_PROJECT" | tee -a "$LOG_FILE"
    if [ "$ONLY_PROJECT" = "hatena" ]; then
        run_hatena_sunday
    else
        run_deploy "$ONLY_PROJECT"
    fi
else
    case "$weekday" in
        1) # Mon
            run_deploy "okramen"
            ;;
        2) # Tue
            run_deploy "okonsen"
            ;;
        3) # Wed
            run_deploy "okcaddie"
            ;;
        4) # Thu
            run_deploy "okstats"
            ;;
        5) # Fri
            run_deploy "starful.biz"
            ;;
        6) # Sat
            run_deploy "jpcampus"
            ;;
        7) # Sun — Hatena: cloud comparison + Python library
            run_hatena_sunday
            ;;
    esac
fi

echo "[$(date '+%F %T')] Auto register finished" | tee -a "$LOG_FILE"
echo "$today" >"$STATE_FILE"

trap - ERR
ok_sound="${AUTO_REGISTER_SUCCESS_SOUND-}"
[[ "$ok_sound" == "none" ]] && ok_sound=""
darwin_notify "Auto Register" "자동 등록이 완료되었습니다." "$ok_sound"
