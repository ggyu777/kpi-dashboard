#!/usr/bin/env bash
# Railway 배포 (최초 1회: railway login)
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Railway 로그인 확인"
railway whoami

echo "==> 프로젝트 연결 (미연결 시 railway link)"
railway status 2>/dev/null || railway init

echo "==> Postgres 추가 (이미 있으면 스킵)"
railway add --database postgres 2>/dev/null || true

echo "==> 환경변수 (GA4_PROPERTY_ID)"
railway variables set GA4_PROPERTY_ID="${GA4_PROPERTY_ID:-410384180}"

if [[ -f token.json ]]; then
  echo "==> GOOGLE_TOKEN_JSON 설정 (token.json)"
  TOKEN=$(python3 -c "import json; print(json.dumps(json.load(open('token.json'))))")
  railway variables set "GOOGLE_TOKEN_JSON=${TOKEN}"
elif [[ -n "${GOOGLE_CREDENTIALS_JSON:-}" ]]; then
  railway variables set "GOOGLE_CREDENTIALS_JSON=${GOOGLE_CREDENTIALS_JSON}"
else
  echo "⚠️  token.json 또는 GOOGLE_CREDENTIALS_JSON 없음 — GA4 수동 0 표시"
fi

echo "==> 배포"
railway up --detach

echo "==> DATABASE_URL로 로컬 데이터 이관"
export DATABASE_URL="$(railway variables get DATABASE_URL 2>/dev/null || railway run printenv DATABASE_URL)"
if [[ -n "${DATABASE_URL}" ]]; then
  python3 migrate_json_to_db.py
else
  echo "⚠️  DATABASE_URL 확인 후: DATABASE_URL=... python migrate_json_to_db.py"
fi

echo "✅ 완료: railway open"
