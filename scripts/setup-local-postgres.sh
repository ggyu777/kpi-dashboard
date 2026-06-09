#!/usr/bin/env bash
# 로컬 Homebrew Postgres 설정 + 마이그레이션
set -euo pipefail
cd "$(dirname "$0")/.."

DB_NAME=ga4_kpi
USER="${USER}"
export DATABASE_URL="postgresql://${USER}@localhost:5432/${DB_NAME}"

createdb "${DB_NAME}" 2>/dev/null || true

if [[ ! -f .env ]]; then
  cp .env.example .env
fi

if ! grep -q "^DATABASE_URL=" .env 2>/dev/null; then
  echo "DATABASE_URL=${DATABASE_URL}" >> .env
else
  sed -i '' "s|^DATABASE_URL=.*|DATABASE_URL=${DATABASE_URL}|" .env 2>/dev/null || \
    sed -i "s|^DATABASE_URL=.*|DATABASE_URL=${DATABASE_URL}|" .env
fi

source .venv/bin/activate 2>/dev/null || { python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt; }

python scripts/repair_json_store.py
python migrate_json_to_db.py

echo "✅ Postgres 준비 완료: ${DATABASE_URL}"
echo "   python main.py 로 서버 실행"
