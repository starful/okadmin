#!/usr/bin/env bash
# Paperclip / local: git push + Cloud deploy, then stamp okadmin hub clocks.
# Usage: /opt/work/okadmin/scripts/paperclip_site_deploy.sh <site_id> [extra deploy.sh args...]
set -euo pipefail

SITE_ID="${1:-}"
if [[ -z "$SITE_ID" ]]; then
  echo "usage: $0 <site_id> [deploy.sh args...]" >&2
  exit 2
fi
shift || true

OKADMIN_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK_ROOT="${WORK_ROOT:-/opt/work}"
SITE_ROOT="${WORK_ROOT}/${SITE_ID}"

if [[ ! -d "$SITE_ROOT" ]]; then
  echo "missing site repo: $SITE_ROOT" >&2
  exit 1
fi
if [[ ! -x "$SITE_ROOT/deploy.sh" && ! -f "$SITE_ROOT/deploy.sh" ]]; then
  echo "deploy.sh not found in $SITE_ROOT" >&2
  exit 1
fi

cd "$SITE_ROOT"
echo "[paperclip_site_deploy] $SITE_ID → ./deploy.sh --with-git --with-deploy $*"
bash ./deploy.sh --with-git --with-deploy "$@"
echo "[paperclip_site_deploy] stamping okadmin content cycle…"
python3 "$OKADMIN_ROOT/scripts/note_content_shipped.py" "$SITE_ID" --via deploy \
  --detail "paperclip_site_deploy.sh git+cloud $(date '+%Y-%m-%d %H:%M:%S')"
echo "[paperclip_site_deploy] done"
