#!/bin/bash
set -euo pipefail
OKADMIN_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$OKADMIN_ROOT"

# shellcheck source=scripts/okadmin_env.sh
source "${OKADMIN_ROOT}/scripts/okadmin_env.sh"
okadmin_env_init "${OKADMIN_ROOT}"

OKADMIN_PYTHON="$(okadmin_resolve_python)"
if ! "$OKADMIN_PYTHON" -c "import dotenv" 2>/dev/null; then
  echo "❌ Python 패키지 없음 — 다음 실행 후 다시 시도:"
  echo "   ${OKADMIN_PYTHON} -m pip install -r requirements.txt"
  exit 1
fi

if [ ! -f .env ] || [ ! -f secrets/firebase-key.json ]; then
  if command -v gcloud >/dev/null 2>&1; then
    echo "Fetching secrets from GCP..."
    bash scripts/fetch_secrets.sh
  fi
fi

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

export WORK_ROOT="${WORK_ROOT:-/opt/work}"
export SITES_YAML="${SITES_YAML:-/opt/work/sites.yaml}"
# OK 시리즈 로컬 앱(okcaddie 등)이 8080을 쓰는 경우가 많아 허브는 8090
export PORT="${PORT:-8090}"
# 로컬: OAuth redirect_uri(8090) 미등록 시 에러 → 개발용 자동 로그인 (Cloud Run은 K_SERVICE로 비활성)
export LOCAL_DEV_AUTH="${LOCAL_DEV_AUTH:-1}"
export DEV_LOGIN_EMAIL="${DEV_LOGIN_EMAIL:-}"

if [ -n "${GOOGLE_APPLICATION_CREDENTIALS:-}" ] && [[ "$GOOGLE_APPLICATION_CREDENTIALS" != /* ]]; then
  export GOOGLE_APPLICATION_CREDENTIALS="${OKADMIN_ROOT}/${GOOGLE_APPLICATION_CREDENTIALS}"
fi

if lsof -i ":${PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "⚠️  포트 ${PORT} 사용 중 — 다른 PORT=... ./start.sh 또는 점유 프로세스 종료"
fi

echo "OK Admin (Work Hub) → http://127.0.0.1:${PORT}"
echo "WORK_ROOT=${WORK_ROOT}"
echo "  (8080에 okcaddie 등이 떠 있으면 이 주소를 쓰세요)"

if [ -z "${GOOGLE_APPLICATION_CREDENTIALS:-}" ] || [ ! -f "${GOOGLE_APPLICATION_CREDENTIALS}" ]; then
  echo "⚠️  Firestore: run ./scripts/fetch_secrets.sh or set GOOGLE_APPLICATION_CREDENTIALS"
elif [ -z "${GOOGLE_PLACES_API_KEY:-}" ]; then
  echo "⚠️  GOOGLE_PLACES_API_KEY missing — GCS Places 검색 비활성"
else
  echo "✅ Firestore + Places configured"
fi

if [ "${LOCAL_DEV_AUTH}" = "1" ]; then
  echo "🔓 LOCAL_DEV_AUTH=1 — Google 로그인 생략 (OAuth 쓰려면 LOCAL_DEV_AUTH=0 + GCP에 redirect URI 등록)"
fi

exec env LOCAL_DEV_AUTH="${LOCAL_DEV_AUTH}" DEV_LOGIN_EMAIL="${DEV_LOGIN_EMAIL}" \
  "$OKADMIN_PYTHON" admin_server.py
