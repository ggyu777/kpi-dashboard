# 📊 Running Life — 위클리 KPI 보드

Next.js + Supabase(Postgres) + Vercel 배포용 **내부 주간 KPI 대시보드**

## 스택

| 구분 | 기술 |
|------|------|
| 프론트 | Alpine.js + Chart.js (기존 UI 유지) |
| API | Next.js Route Handlers (`/api/*`) |
| DB | Supabase Postgres (`DATABASE_URL`) |
| GA4 | `@google-analytics/data` (서버 env) |
| 배포 | Vercel |

## 로컬 실행

```bash
npm install
cp .env.example .env.local
# .env.local에 DATABASE_URL, GOOGLE_TOKEN_JSON 설정

npm run dev
# → http://localhost:3000
```

## Supabase 설정

1. [supabase.com](https://supabase.com)에서 프로젝트 생성
2. SQL Editor에서 `supabase/schema.sql` 실행
3. Settings → Database → **Connection string (URI)** 복사
4. Vercel / `.env.local`에 `DATABASE_URL` 로 설정

기존 로컬 Postgres 데이터가 있으면 동일 connection string으로 이관하면 됩니다.

## Vercel 배포

1. GitHub `Running-Rife/running-life-kpi-dashboard` 연결
2. Environment Variables:

| 변수 | 설명 |
|------|------|
| `DATABASE_URL` | Supabase Postgres URI (`?sslmode=require` 포함 권장) |
| `GA4_PROPERTY_ID` | GA4 속성 ID |
| `GOOGLE_TOKEN_JSON` | OAuth token JSON 한 줄 (또는 `GOOGLE_CREDENTIALS_JSON`) |

3. Deploy — Root는 repo 루트, Framework: Next.js 자동 감지

## API

기존 FastAPI와 동일 경로 유지: `/api/health`, `/api/kpi`, `/api/weekly-plan`, `/api/monthly-plan` 등

## 레거시 (Python)

이전 FastAPI 앱은 `legacy-python/`에 보관. 로컬 venv 실행은 더 이상 필요 없습니다.

```bash
# 참고용 (deprecated)
cd legacy-python && python main.py
```

## CSV 보조 데이터

`data/*.csv` — W1 리텐션, MAU overview, iOS/Android 신규 (월간 플래너 보조)
