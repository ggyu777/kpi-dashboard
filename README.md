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

## 데이터 저장 (3가지 중 택1)

| 방식 | env | 용도 |
|------|-----|------|
| **Vercel Blob** (추천·무료) | `BLOB_READ_WRITE_TOKEN` | Supabase 없이 Vercel 배포 |
| 로컬 JSON | (없음) | `npm run dev` 로컬만 |
| Postgres | `DATABASE_URL` | Supabase / Neon / 로컬 Postgres |

### Vercel Blob (Supabase 대안)

1. Vercel Dashboard → Storage → **Blob** 생성 → 프로젝트 연결
2. `BLOB_READ_WRITE_TOKEN` 자동 주입됨
3. 기존 데이터 이관:
   ```bash
   BLOB_READ_WRITE_TOKEN=... npx tsx scripts/upload-store-to-blob.ts
   ```

### Supabase / Neon (Postgres)

1. SQL Editor에서 `supabase/schema.sql` 실행
2. `DATABASE_URL` 설정 (Neon 무료도 동일하게 동작)

## Vercel 배포

1. GitHub `Running-Rife/running-life-kpi-dashboard` 연결
2. Environment Variables:

| 변수 | 설명 |
|------|------|
| `DATABASE_URL` | Supabase Postgres URI (`?sslmode=require` 포함 권장) |
| `GA4_PROPERTY_ID` | GA4 속성 ID |
| `GOOGLE_TOKEN_JSON` | OAuth token JSON 한 줄 (또는 `GOOGLE_CREDENTIALS_JSON`) |

### GA4 OAuth 토큰 갱신 (`invalid_grant`)

```bash
# 1) 브라우저 로그인 → token.json 발급
npm run ga4:auth

# 2) 로컬 연결 확인
npm run ga4:test

# 3) Vercel Production 반영 + 재배포
npm run ga4:push-vercel
# 또는 한 번에: npm run ga4:auth:vercel
```

`client_secret.json`(Google Cloud OAuth Desktop client)이 프로젝트 루트에 있어야 합니다.  
GA4 Admin → 속성 액세스 관리에 로그인한 계정이 **뷰어 이상**이어야 합니다.

**재발 방지:** 서비스 계정 키를 `GOOGLE_CREDENTIALS_JSON`으로 넣으면 OAuth 갱신이 필요 없습니다.

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
