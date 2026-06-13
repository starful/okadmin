#!/bin/bash
# Check whether auto_register completed successfully on a given day.
# Usage: ./verify_auto_register_day.sh [YYYY-MM-DD]   (default: today)
# Exit: 0 OK | 1 incomplete/failed | 2 bad date | 3 no log | 4 skips only

set -euo pipefail

OPS_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="${WORK_ROOT:-$(cd "$OPS_DIR/../.." && pwd)}"
LOG_DIR="$OPS_DIR/logs"
STATE_FILE="$OPS_DIR/state/auto-register.last-run"

CHECK_DATE="${1:-$(date '+%Y-%m-%d')}"

weekday_from_date() {
    local d="$1" out
    if out="$(date -j -f "%Y-%m-%d" "$d" +%u 2>/dev/null)"; then
        echo "$out"
        return 0
    fi
    if out="$(date -d "$d" +%u 2>/dev/null)"; then
        echo "$out"
        return 0
    fi
    return 1
}

project_for_weekday() {
    case "$1" in
        1) echo "okramen" ;;
        2) echo "okonsen" ;;
        3) echo "okcaddie" ;;
        4) echo "okstats" ;;
        5) echo "starful.biz" ;;
        6) echo "jpcampus" ;;
        7) echo "hatena (cloud + py)" ;;
        *) echo "?" ;;
    esac
}

if ! wd="$(weekday_from_date "$CHECK_DATE")"; then
    echo "Invalid date: $CHECK_DATE (use YYYY-MM-DD)"
    exit 2
fi

exp="$(project_for_weekday "$wd")"
logf="$LOG_DIR/auto-register-$CHECK_DATE.log"

echo "Date: $CHECK_DATE (weekday=$wd)"
echo "Scheduled project: $exp"
echo "Log: $logf"
echo ""

if [ ! -f "$logf" ]; then
    echo "RESULT: NO LOG — that day has no log file (Mac off, or first run)."
    exit 3
fi

if grep -q "Auto register finished" "$logf"; then
    echo "RESULT: OK — script reached 'Auto register finished' (no early abort from deploy)."
    if [ -f "$STATE_FILE" ]; then
        echo "State file (last successful run date): $(tr -d '\n' <"$STATE_FILE")"
    fi
    exit 0
fi

if grep -q "Auto register started" "$logf"; then
    echo "RESULT: INCOMPLETE — 'Auto register started' without a matching successful finish."
    echo "Retry: $OPS_DIR/retry_auto_register.sh${exp:+ $exp}"
    echo "        (with no args: today's weekday project)"
    echo "--- last 40 log lines ---"
    tail -n 40 "$logf"
    exit 1
fi

echo "RESULT: NO MAIN RUN — only pre-9:00 / already-ran skips, or empty."
echo "--- last Skip lines ---"
grep "Skip:" "$logf" | tail -n 8 || true
exit 4
