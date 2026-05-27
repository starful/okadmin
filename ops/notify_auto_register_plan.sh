#!/bin/bash

set -euo pipefail

TARGET_HOUR="${TARGET_HOUR:-9}"
TARGET_MINUTE="${TARGET_MINUTE:-0}"

day_projects() {
    case "$1" in
        1) echo "okramen" ;;      # Mon
        2) echo "okonsen" ;;      # Tue
        3) echo "okcaddie" ;;     # Wed
        4) echo "oksushi" ;;      # Thu
        5) echo "starful.biz" ;;  # Fri
        6) echo "jpcampus" ;;     # Sat
        7) echo "hatena (cloud + py)" ;; # Sun
        *) echo "-" ;;
    esac
}

day_name() {
    case "$1" in
        1) echo "월" ;;
        2) echo "화" ;;
        3) echo "수" ;;
        4) echo "목" ;;
        5) echo "금" ;;
        6) echo "토" ;;
        7) echo "일" ;;
        *) echo "?" ;;
    esac
}

today_num="$(date '+%u')"
tomorrow_num="$(( (today_num % 7) + 1 ))"

today_projects="$(day_projects "$today_num")"
tomorrow_projects="$(day_projects "$tomorrow_num")"
today_name="$(day_name "$today_num")"
tomorrow_name="$(day_name "$tomorrow_num")"
run_time="$(printf '%02d:%02d' "$TARGET_HOUR" "$TARGET_MINUTE")"

msg_today="오늘(${today_name}) ${run_time}: ${today_projects}"
msg_tomorrow="내일(${tomorrow_name}) ${run_time}: ${tomorrow_projects}"

echo "[PLAN] $msg_today"
echo "[PLAN] $msg_tomorrow"

if [[ "$OSTYPE" == "darwin"* ]]; then
    osascript -e "display notification \"$msg_tomorrow\" with title \"Auto Register 실행 계획\" subtitle \"$msg_today\"" 2>/dev/null || true
fi
