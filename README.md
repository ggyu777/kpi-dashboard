# 📊 Running Life — 위클리 KPI 보드

FastAPI + 단일 HTML 파일로 만든 **내부 주간 KPI 대시보드**

## 시작

```bash
# 1. 가상환경 + 패키지 설치
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. 환경변수 설정
cp .env.example .env
# .env에 GA4_PROPERTY_ID, GOOGLE_APPLICATION_CREDENTIALS 입력

# 3. 실행
python main.py
# → http://localhost:8000
```

## GA4 서비스 계정 키 발급

1. Google Cloud Console → IAM → Service Accounts → 키 생성 (JSON)
2. `service-account-key.json` 으로 저장
3. GA4 Admin → Account Access Management → 서비스 계정 이메일 추가 (Viewer)

> GA4 키 없어도 실행됨 — GA4 항목은 0으로 표시, 수동 입력으로 대체 가능

## 추적 KPI

| 카테고리 | KPI                             | 소스     |
| -------- | ------------------------------- | -------- |
| 유저     | MAU, 신규 가입자, 세션 수       | GA4 자동 |
| 유저     | 앱 다운로드                     | 수동     |
| 매출     | 총 매출, 결제 건수, 평균 결제액 | 수동     |
| 광고     | 광고 노출/클릭/수익, CTR        | 수동     |

## GA 커스텀 이벤트 목록

소스: [Running-Rife `packages/analytics/src/events.ts`](https://github.com/Running-Rife/Running-Rife/blob/main/packages/analytics/src/events.ts) · 총 52개 (수동 동기화)

### 대회 (5개)

| 이벤트명 | 설명 | 주요 파라미터 |
|---------|------|--------------|
| `view_contest_detail` | 대회 상세 페이지 조회 | `contest_id`, `entry_path?` |
| `click_external_link` | 대회 외부 링크 클릭 | `contest_id`, `link_url` |
| `click_contest_share` | 대회 공유 버튼 클릭 | `contest_id` |
| `click_contest_bookmark` | 대회 북마크 추가/삭제 | `contest_id`, `action(add\|remove)`, `from_page` |
| `click_contest_review_more` | 대회 리뷰 더보기 클릭 | `contest_id` |

### 홈 (4개)

| 이벤트명 | 설명 | 주요 파라미터 |
|---------|------|--------------|
| `click_home_participation_more` | 홈 참가 섹션 더보기 클릭 | — |
| `click_home_popular_more` | 홈 인기 섹션 더보기 클릭 | — |
| `click_home_shoes_more` | 홈 슈즈 섹션 더보기 클릭 | — |
| `click_home_to_analysis` | 홈에서 분석 화면으로 이동 | — |

### 광고/배너 (10개)

| 이벤트명 | 설명 | 주요 파라미터 |
|---------|------|--------------|
| `click_home_ad_banner` | 홈 광고 배너 클릭 | `ad_id`, `action_type`, `copy_variant`, `banner_copy_mode`, `growthbook_arm`, ... |
| `view_home_styled_banner` | 스타일 홈 배너 노출 (뷰포트, 1회) | `ad_id`, `action_type`, `copy_variant`, `banner_copy_mode`, `growthbook_arm`, ... |
| `click_home_category_banner` | 카테고리 홈 배너 클릭 | `ad_id`, `category?`, `copy_variant`, `banner_copy_mode`, `growthbook_arm` |
| `view_home_category_banner` | 카테고리 홈 배너 노출 (뷰포트, 1회) | `ad_id`, `category?`, `copy_variant`, `banner_copy_mode`, `growthbook_arm` |
| `click_home_magazine_banner` | RIFE 매거진 배너 클릭 | `ad_id`, `ad_name?`, `ad_placement?`, `link_url?` |
| `view_home_magazine_banner` | 매거진 배너 노출 (뷰포트, 1회) | `ad_id`, `ad_name?` |
| `click_home_popular_slot_ad` | 인기 슬롯 광고 클릭 | `ad_id`, `ad_name?` |
| `view_home_popular_slot_ad` | 인기 슬롯 광고 노출 (뷰포트, 1회) | `ad_id`, `ad_name?` |
| `click_home_popup` | 홈 팝업 광고 클릭 | `popup_id?`, `popup_name?`, `action_type?` |
| `view_home_popup` | 홈 팝업 광고 노출 (1회) | `popup_id?`, `popup_name?` |

### 슈즈 (4개)

| 이벤트명 | 설명 | 주요 파라미터 |
|---------|------|--------------|
| `view_shoes_detail` | 슈즈 상세 페이지 조회 | `shoe_id`, `entry_path?` |
| `click_shoes_bookmark` | 슈즈 북마크 추가/삭제 | `shoe_id`, `action(add\|remove)`, `from_page` |
| `apply_shoes_filter` | 슈즈 필터 적용 | `has_brand`, `has_type`, `has_price` |
| `view_shoes_tab` | 슈즈 탭 조회 | `is_first_view` |

### 마이런 (5개)

| 이벤트명 | 설명 | 주요 파라미터 |
|---------|------|--------------|
| `view_myrun_tab` | 마이런 탭 조회 | `user_id?`, `is_first_view` |
| `myrun_stay_time` | 마이런 체류 시간 측정 | `duration_seconds` |
| `click_myrun_sync` | 마이런 데이터 동기화 클릭 | `type(all_data\|refresh)` |
| `click_myrun_stats_goal_button` | 러닝 통계 목표 버튼 클릭 | `course_type(5K\|10K\|HALF\|FULL)`, `mode(create\|edit)` |
| `set_running_stat_goal` | 러닝 통계 목표 설정 완료 | `course_type(5K\|10K\|HALF\|FULL)`, `goal_time?`, `mode(create\|edit)` |

### 참가 신청 (5개)

| 이벤트명 | 설명 | 주요 파라미터 |
|---------|------|--------------|
| `participation_start` | 참가 신청 시작 | `entry_path?` |
| `participation_complete` | 참가 신청 완료 | `contest_id`, `course_id?`, `registration_status?`, `entry_path?`, `used_bookmarked_contest` |
| `participation_abandon` | 참가 신청 이탈 | `step`, `contest_id?`, `entry_path?`, `reason?` |
| `participation_bookmark_usage` | 참가 시 북마크 대회 사용 여부 | `contest_id`, `used_bookmarked_contest` |
| `participation_submit_error` | 참가 신청 제출 오류 발생 | `error_message`, `entry_path` |

### 러닝 기록 (7개)

| 이벤트명 | 설명 | 주요 파라미터 |
|---------|------|--------------|
| `record_start` | 러닝 기록 작성 시작 | `record_type(manual\|auto)`, `entry_path?` |
| `record_complete` | 러닝 기록 작성 완료 | `distance?`, `duration?`, `record_type(manual\|auto)`, `entry_path?` |
| `record_abandon` | 러닝 기록 작성 이탈 | `record_type(manual\|auto)`, `step`, `entry_path?`, `reason?` |
| `record_submit_error` | 러닝 기록 제출 오류 발생 | `error_message`, `entry_path` |
| `upload_certificate` | 완주증 업로드 | `entry_path(myrun\|participation\|participation_detail)` |
| `extract_certificate_success` | 완주증 정보 추출 성공 | `has_time`, `has_bib`, `entry_path` |
| `extract_certificate_fail` | 완주증 정보 추출 실패 | `entry_path` |

### 목표 (5개)

| 이벤트명 | 설명 | 주요 파라미터 |
|---------|------|--------------|
| `set_distance_goal` | 거리 목표 설정 | `goal_type(weekly\|monthly\|yearly)`, `dist_km` |
| `recur_goal_setting` | 반복 목표 설정 | `period_type(W\|M)`, `consecutive_cnt?` |
| `achieve_distance_goal` | 거리 목표 달성 | `goal_type(weekly\|monthly\|yearly)`, `actual_dist`, `is_auto` |
| `click_share_celebration` | 목표 달성 축하 공유 클릭 | `platform(IG\|Kakao\|system)`, `goal_type(weekly\|monthly)` |
| `set_next_goal_after_achieve` | 달성 후 다음 목표 설정 | `prev_goal_type(weekly\|monthly)`, `new_dist_km` |

### 펀넬/검색 (4개)

| 이벤트명 | 설명 | 주요 파라미터 |
|---------|------|--------------|
| `funnel_step_complete` | 펀넬 단계 완료 | `funnel(record_write\|participation_add)`, `step`, `auto_skip?` |
| `search_contest` | 펀넬 내 대회 검색 | `keyword`, `result_count`, `source(record_write\|participation_add)` |
| `select_contest_in_funnel` | 펀넬에서 대회 선택 | `contest_id`, `source(search\|bookmark\|recent\|participation_list)`, `funnel` |
| `select_course` | 코스 선택 | `course_type(5K\|10K\|HALF\|FULL)`, `contest_id?`, `funnel` |

### 기타 (3개)

| 이벤트명 | 설명 | 주요 파라미터 |
|---------|------|--------------|
| `notification_open` | 알림 열기 | `notif_id?`, `notif_type(evaluation\|bookmark)?`, `race_id?` |
| `complete_onboarding_sync` | 온보딩 데이터 동기화 완료 | `hours_since_signup?`, `source?` |
| `view_growthbook_experiment` | GrowthBook A/B 실험 노출 (세션 1회) | `experiment_id`, `variation_id`, `variation_value?`, `in_experiment?` |

## 데이터 저장

| 환경 | 저장소 |
|------|--------|
| `DATABASE_URL` 설정됨 | **PostgreSQL** (Railway / Render) |
| 미설정 (로컬) | `data/kpi-store.json` (git 제외, atomic write) |

플래너·노트·할일은 DB row 단위 upsert로 **동시 저장 race 제거**.

### 로컬 JSON → Postgres 이관

```bash
export DATABASE_URL="postgresql://..."
python migrate_json_to_db.py          # 이관
python migrate_json_to_db.py --dry-run  # 파싱만 (손상 파일 복구 확인)
```

## 배포 (Railway / Render)

### 1. Postgres 추가
- **Railway**: New → Database → PostgreSQL → `DATABASE_URL` 자동 연결
- **Render**: `render.yaml` Blueprint 또는 Dashboard에서 Postgres 생성

### 2. Web 서비스
- Repo 루트에서 Blueprint 또는 Docker 배포
- Build: `Dockerfile`
- Health check: `/api/health`

### 3. 필수 환경변수

| 변수 | 설명 |
|------|------|
| `DATABASE_URL` | Postgres 연결 문자열 (자동 주입) |
| `GA4_PROPERTY_ID` | GA4 속성 ID |
| `GOOGLE_CREDENTIALS_JSON` | 서비스 계정 JSON **전체** (한 줄) |

### 4. CSV (월간 플래너 보조 데이터)
Docker 이미지에 `data/*.csv` 포함. 경로는 `.env.example` 참고.

### Railway 빠른 배포

```bash
railway login
railway init
railway add -d postgres
railway up
railway variables set GOOGLE_CREDENTIALS_JSON='...'
railway variables set GA4_PROPERTY_ID=410384180
python migrate_json_to_db.py   # 로컬에서 DATABASE_URL=Railway URL 로 이관
```
