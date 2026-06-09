"""
Running Life 위클리 KPI 대시보드
FastAPI 서버 — http://localhost:8000
"""
from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path
from typing import Optional, Union

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from db import (
    default_ad_revenues as _default_ad_revenues,
    get_ad_conversions,
    get_ad_placement_meta,
    get_manual_data,
    get_monthly_feedback,
    get_monthly_plan,
    get_targets,
    get_weekly_notes,
    get_weekly_plan,
    get_weekly_tasks,
    init_db,
    save_ad_conversions,
    save_ad_placement_meta_field,
    save_manual_data,
    save_monthly_feedback,
    save_monthly_plan,
    save_targets,
    save_weekly_notes,
    save_weekly_plan,
    save_weekly_tasks,
    using_postgres,
)

load_dotenv()

app = FastAPI(title="Running Life KPI Dashboard", docs_url=None, redoc_url=None)


@app.on_event("startup")
def _startup_init_db():
    if using_postgres():
        init_db()
        print("[db] PostgreSQL 연결 · 테이블 준비 완료")
    else:
        print("[db] DATABASE_URL 없음 — 로컬 JSON 저장소 사용 (data/kpi-store.json)")


@app.get("/api/health")
def health():
    return {"ok": True, "storage": "postgres" if using_postgres() else "json"}

# ──────────────────────────────────────────────
# 설정
# ──────────────────────────────────────────────
GA4_PROPERTY_ID = os.getenv("GA4_PROPERTY_ID", "410384180")
COHORT_RETENTION_CSV = Path(
    os.getenv("COHORT_RETENTION_CSV", str(Path(__file__).parent / "data" / "cohort_retention.csv"))
)
GA4_OVERVIEW_CSV = Path(
    os.getenv("GA4_OVERVIEW_CSV", str(Path(__file__).parent / "data" / "ga4_overview.csv"))
)
USER_ACQUISITION_CSV = Path(
    os.getenv("USER_ACQUISITION_CSV", str(Path(__file__).parent / "data" / "user_acquisition.csv"))
)
APP_DOWNLOADS_CSV = Path(
    os.getenv("APP_DOWNLOADS_CSV", str(Path(__file__).parent / "data" / "app_downloads.csv"))
)

PLACEMENTS = [
    {"id": "top",         "label": "상단 카테고리"},
    {"id": "center",      "label": "스타일"},
    {"id": "bottom",      "label": "매거진"},
    {"id": "popular_slot","label": "인기 슬롯"},
    {"id": "popup",       "label": "팝업"},
]


def _fmt_quill_segment(text: str, attrs: dict) -> str:
    if not text:
        return ""
    if attrs.get("bold") and attrs.get("italic"):
        return f"***{text}***"
    if attrs.get("bold"):
        return f"**{text}**"
    if attrs.get("italic"):
        return f"*{text}*"
    return text


def quill_delta_to_md(raw: str | None) -> str:
    """Quill Delta JSON → 마크다운(유사) 텍스트. 플레인 텍스트는 그대로 반환."""
    if not raw or not str(raw).strip():
        return "- (미입력)"
    text = str(raw).strip()
    try:
        ops = json.loads(text).get("ops")
        if not isinstance(ops, list):
            return text
    except json.JSONDecodeError:
        return text

    lines_out: list[str] = []
    pending = ""
    ol_counter = 0

    def flush_line(line_text: str, attrs: dict) -> None:
        nonlocal ol_counter
        header = attrs.get("header")
        list_attr = attrs.get("list")
        if header:
            lines_out.append("#" * int(header) + " " + line_text)
            ol_counter = 0
        elif list_attr == "bullet":
            lines_out.append(f"- {line_text}")
            ol_counter = 0
        elif list_attr == "ordered":
            ol_counter += 1
            lines_out.append(f"{ol_counter}. {line_text}")
        elif list_attr == "unchecked":
            lines_out.append(f"- [ ] {line_text}")
            ol_counter = 0
        elif list_attr == "checked":
            lines_out.append(f"- [x] {line_text}")
            ol_counter = 0
        else:
            lines_out.append(line_text)
            ol_counter = 0

    for op in ops:
        insert = op.get("insert", "")
        if not isinstance(insert, str):
            continue
        attrs = op.get("attributes") or {}
        if "\n" not in insert:
            pending += _fmt_quill_segment(insert, attrs)
            continue
        chunks = insert.split("\n")
        for idx, chunk in enumerate(chunks):
            if chunk:
                pending += _fmt_quill_segment(chunk, attrs if idx == 0 else {})
            if idx < len(chunks) - 1:
                flush_line(pending, attrs)
                pending = ""

    if pending:
        flush_line(pending, {})

    result = "\n".join(lines_out).strip()
    return result or "- (미입력)"


def quill_delta_first_line(raw: str | None) -> str:
    md = quill_delta_to_md(raw)
    if md == "- (미입력)":
        return "—"
    first = md.splitlines()[0].strip()
    return first or "—"

CUSTOM_EVENT_DEFINITIONS = [
    # 대회
    {"event_name": "view_contest_detail",         "label": "대회 상세 조회",    "category": "contest"},
    {"event_name": "click_external_link",         "label": "외부 링크 클릭",    "category": "contest"},
    {"event_name": "click_contest_share",         "label": "대회 공유",          "category": "contest"},
    {"event_name": "click_contest_bookmark",      "label": "대회 북마크",        "category": "contest"},
    {"event_name": "click_contest_review_more",   "label": "리뷰 더보기",        "category": "contest"},
    # 홈
    {"event_name": "click_home_participation_more","label": "참가 더보기",       "category": "home"},
    {"event_name": "click_home_popular_more",     "label": "인기 더보기",        "category": "home"},
    {"event_name": "click_home_shoes_more",       "label": "슈즈 더보기",        "category": "home"},
    {"event_name": "click_home_to_analysis",      "label": "분석 이동",          "category": "home"},
    # 슈즈
    {"event_name": "view_shoes_detail",           "label": "슈즈 상세 조회",     "category": "shoes"},
    {"event_name": "click_shoes_bookmark",        "label": "슈즈 북마크",        "category": "shoes"},
    {"event_name": "apply_shoes_filter",          "label": "슈즈 필터 적용",     "category": "shoes"},
    {"event_name": "view_shoes_tab",              "label": "슈즈 탭 진입",       "category": "shoes"},
    # 마이런
    {"event_name": "view_myrun_tab",              "label": "마이런 탭 진입",     "category": "myrun"},
    {"event_name": "myrun_stay_time",             "label": "마이런 체류 이벤트", "category": "myrun"},
    {"event_name": "click_myrun_sync",            "label": "데이터 동기화",      "category": "myrun"},
    {"event_name": "click_myrun_stats_goal_button","label": "목표 버튼 클릭",    "category": "myrun"},
    {"event_name": "set_running_stat_goal",       "label": "러닝 목표 설정",     "category": "myrun"},
    # 참가 신청
    {"event_name": "participation_start",         "label": "참가 신청 시작",     "category": "participation"},
    {"event_name": "participation_complete",      "label": "참가 신청 완료",     "category": "participation"},
    {"event_name": "participation_abandon",       "label": "참가 신청 이탈",     "category": "participation"},
    {"event_name": "participation_bookmark_usage","label": "북마크 대회 사용",   "category": "participation"},
    {"event_name": "participation_submit_error",  "label": "참가 제출 오류",     "category": "participation"},
    # 러닝 기록
    {"event_name": "record_start",                "label": "기록 시작",          "category": "record"},
    {"event_name": "record_complete",             "label": "기록 완료",          "category": "record"},
    {"event_name": "record_abandon",              "label": "기록 이탈",          "category": "record"},
    {"event_name": "record_submit_error",         "label": "기록 제출 오류",     "category": "record"},
    {"event_name": "upload_certificate",          "label": "완주증 업로드",      "category": "record"},
    {"event_name": "extract_certificate_success", "label": "완주증 추출 성공",   "category": "record"},
    {"event_name": "extract_certificate_fail",    "label": "완주증 추출 실패",   "category": "record"},
    # 목표
    {"event_name": "set_distance_goal",           "label": "거리 목표 설정",     "category": "goal"},
    {"event_name": "recur_goal_setting",          "label": "반복 목표 설정",     "category": "goal"},
    {"event_name": "achieve_distance_goal",       "label": "목표 달성",          "category": "goal"},
    {"event_name": "click_share_celebration",     "label": "달성 공유",          "category": "goal"},
    {"event_name": "set_next_goal_after_achieve", "label": "다음 목표 설정",     "category": "goal"},
    # 펀넬/검색
    {"event_name": "funnel_step_complete",        "label": "펀넬 단계 완료",     "category": "funnel"},
    {"event_name": "search_contest",              "label": "대회 검색",          "category": "funnel"},
    {"event_name": "select_contest_in_funnel",    "label": "펀넬 대회 선택",     "category": "funnel"},
    {"event_name": "select_course",               "label": "코스 선택",          "category": "funnel"},
    # 기타
    {"event_name": "notification_open",           "label": "알림 열기",          "category": "etc"},
    {"event_name": "complete_onboarding_sync",    "label": "온보딩 동기화",      "category": "etc"},
    {"event_name": "view_growthbook_experiment",  "label": "A/B 실험 노출",      "category": "etc"},
]

KPI_DEFINITIONS = [
    # id, name, category, unit, source
    {"id": "mau",           "name": "MAU",        "category": "user",    "unit": "명", "source": "ga4"},
    {"id": "new_users",     "name": "신규 가입자", "category": "user",    "unit": "명", "source": "ga4"},
    {"id": "sessions",      "name": "세션 수",     "category": "user",    "unit": "회", "source": "ga4"},
    {"id": "app_downloads", "name": "앱 다운로드", "category": "user",    "unit": "건", "source": "manual"},
    {"id": "total_revenue", "name": "총 매출",     "category": "revenue", "unit": "원", "source": "manual"},
    {"id": "payment_count", "name": "결제 건수",   "category": "revenue", "unit": "건", "source": "manual"},
    {"id": "avg_order_value","name": "평균 결제액", "category": "revenue", "unit": "원", "source": "manual"},
    {"id": "ad_impressions","name": "광고 노출",   "category": "ads",     "unit": "회", "source": "manual"},
    {"id": "ad_clicks",     "name": "광고 클릭",   "category": "ads",     "unit": "건", "source": "manual"},
    {"id": "ad_revenue",    "name": "광고 수익",   "category": "ads",     "unit": "원", "source": "manual"},
    {"id": "ctr",           "name": "CTR",         "category": "ads",     "unit": "%",  "source": "manual"},
]


# ──────────────────────────────────────────────
# 주차 유틸
# ──────────────────────────────────────────────
def get_iso_week_key(d: date = None) -> str:
    """date → 'YYYY-WW' ISO 주차 키"""
    d = d or date.today()
    iso = d.isocalendar()
    return f"{iso.year}-{iso.week:02d}"


def week_key_to_monday(week_key: str) -> date:
    """'YYYY-WW' → 해당 주 월요일"""
    year, week = map(int, week_key.split("-"))
    # ISO 주차의 1월 4일 기준 계산
    jan4 = date(year, 1, 4)
    # 해당 주 목요일 기준 (ISO week의 관례)
    thursday = jan4 + timedelta(weeks=week - jan4.isocalendar().week, days=3 - jan4.weekday())
    monday = thursday - timedelta(days=3)
    return monday


def get_week_label(week_key: str) -> str:
    monday = week_key_to_monday(week_key)
    sunday = monday + timedelta(days=6)
    year, week = week_key.split("-")
    return f"{year}년 {int(week)}주차 ({monday.month}/{monday.day}~{sunday.month}/{sunday.day})"


ORDINAL_KO = ("첫째", "둘째", "셋째", "넷째", "다섯째", "여섯째")


def _reference_month_key(week_key: str) -> str:
    """주차 내 날짜가 가장 많이 속한 월 (6월 첫째주 라벨용)."""
    monday = week_key_to_monday(week_key)
    counts: dict[str, int] = {}
    for i in range(7):
        d = monday + timedelta(days=i)
        mk = f"{d.year}-{d.month:02d}"
        counts[mk] = counts.get(mk, 0) + 1
    return max(counts, key=counts.get)


def _iso_week_keys_in_month(month_key: str) -> list[str]:
    """해당 월에 걸치는 ISO 주차 키 (오래된→최신 순)."""
    import calendar

    year, month = map(int, month_key.split("-"))
    first = date(year, month, 1)
    last = date(year, month, calendar.monthrange(year, month)[1])
    seen: set[str] = set()
    keys: list[str] = []
    d = first
    while d <= last:
        wk = get_iso_week_key(d)
        if wk not in seen:
            seen.add(wk)
            keys.append(wk)
        d += timedelta(days=1)
    return keys


def get_planner_week_label(week_key: str) -> str:
    """'6월 둘째주 (6/9~6/15)' 형식 (월간 플래너 주차 표기)."""
    monday = week_key_to_monday(week_key)
    sunday = monday + timedelta(days=6)
    date_range = f"({monday.month}/{monday.day}~{sunday.month}/{sunday.day})"
    month_key = _reference_month_key(week_key)
    week_keys = _iso_week_keys_in_month(month_key)
    try:
        idx = week_keys.index(week_key)
    except ValueError:
        return get_week_label(week_key)
    month_num = int(month_key.split("-")[1])
    ord_label = ORDINAL_KO[idx] if idx < len(ORDINAL_KO) else f"{idx + 1}째"
    return f"{month_num}월 {ord_label}주 {date_range}"


def get_week_date_range(week_key: str) -> tuple[str, str]:
    monday = week_key_to_monday(week_key)
    sunday = monday + timedelta(days=6)
    return monday.isoformat(), sunday.isoformat()


WEEKDAY_KO = ("월", "화", "수", "목", "금", "토", "일")

KPI_GA4_METRIC = {
    "mau": "activeUsers",
    "new_users": "newUsers",
    "sessions": "sessions",
}


def get_week_days(week_key: str) -> list[dict]:
    """ISO 주차 월~일 7일 메타."""
    monday = week_key_to_monday(week_key)
    days = []
    for i in range(7):
        d = monday + timedelta(days=i)
        days.append({
            "date": d.isoformat(),
            "weekday": WEEKDAY_KO[i],
            "date_label": f"{d.month}/{d.day}",
        })
    return days


def _ga4_date_to_iso(ga4_date: str) -> str:
    """GA4 date dimension 'YYYYMMDD' → 'YYYY-MM-DD'."""
    s = ga4_date.strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s


def _fetch_ga4_metric_daily(week_key: str, metric_key: str) -> dict[str, int]:
    """주차 내 일별 GA4 metric. 반환: {'YYYY-MM-DD': value}."""
    ga4_metric = KPI_GA4_METRIC.get(metric_key)
    if not ga4_metric:
        return {}
    try:
        from google.analytics.data_v1beta.types import DateRange, Dimension, Metric, RunReportRequest

        client = _ga4_client()
        if client is None:
            return {}
        start_date, end_date = get_week_date_range(week_key)
        request = RunReportRequest(
            property=f"properties/{GA4_PROPERTY_ID}",
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            dimensions=[Dimension(name="date")],
            metrics=[Metric(name=ga4_metric)],
        )
        response = client.run_report(request)
        out: dict[str, int] = {}
        for row in response.rows:
            iso = _ga4_date_to_iso(row.dimension_values[0].value)
            out[iso] = int(row.metric_values[0].value)
        return out
    except Exception as e:
        print(f"[GA4 Daily KPI] 조회 실패 ({metric_key}): {e}")
        return {}


def _fetch_event_count_daily(week_key: str, event_name: str) -> dict[str, int]:
    """주차 내 일별 이벤트 카운트. 반환: {'YYYY-MM-DD': count}."""
    try:
        from google.analytics.data_v1beta.types import (
            DateRange, Dimension, Filter, FilterExpression, Metric, RunReportRequest,
        )

        client = _ga4_client()
        if client is None:
            return {}
        start_date, end_date = get_week_date_range(week_key)
        request = RunReportRequest(
            property=f"properties/{GA4_PROPERTY_ID}",
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            dimensions=[Dimension(name="date")],
            metrics=[Metric(name="eventCount")],
            dimension_filter=FilterExpression(
                filter=Filter(
                    field_name="eventName",
                    string_filter=Filter.StringFilter(value=event_name),
                )
            ),
        )
        response = client.run_report(request)
        out: dict[str, int] = {}
        for row in response.rows:
            iso = _ga4_date_to_iso(row.dimension_values[0].value)
            out[iso] = int(row.metric_values[0].value)
        return out
    except Exception as e:
        print(f"[GA4 Daily Event] 조회 실패 ({event_name}): {e}")
        return {}


def _build_daily_series(week_key: str, values_by_date: dict[str, int]) -> list[dict]:
    days = []
    total = 0
    for d in get_week_days(week_key):
        v = values_by_date.get(d["date"], 0)
        total += v
        days.append({**d, "value": v})
    return days, total


def prev_week_key(week_key: str) -> str:
    monday = week_key_to_monday(week_key)
    prev_monday = monday - timedelta(weeks=1)
    return get_iso_week_key(prev_monday)


def recent_week_keys(n: int, from_week: str = None) -> list[str]:
    """최근 n주 키 (오래된→최신 순)"""
    base = week_key_to_monday(from_week or get_iso_week_key())
    weeks = []
    for i in range(n - 1, -1, -1):
        d = base - timedelta(weeks=i)
        weeks.append(get_iso_week_key(d))
    return weeks


# ──────────────────────────────────────────────
# 월별 유틸
# ──────────────────────────────────────────────
def get_month_key(d: date = None) -> str:
    """date → 'YYYY-MM' 월 키"""
    d = d or date.today()
    return f"{d.year}-{d.month:02d}"


def get_month_label(month_key: str) -> str:
    year, month = month_key.split("-")
    return f"{year}년 {int(month)}월"


def get_month_date_range(month_key: str) -> tuple[str, str]:
    import calendar
    year, month = map(int, month_key.split("-"))
    start = date(year, month, 1)
    last_day = calendar.monthrange(year, month)[1]
    end = date(year, month, last_day)
    return start.isoformat(), end.isoformat()


def prev_month_key(month_key: str) -> str:
    year, month = map(int, month_key.split("-"))
    if month == 1:
        return f"{year - 1}-12"
    return f"{year}-{month - 1:02d}"


def recent_month_keys(n: int, from_month: str = None) -> list[str]:
    """최근 n개월 키 (오래된→최신 순)"""
    base_year, base_month = map(int, (from_month or get_month_key()).split("-"))
    months = []
    for i in range(n - 1, -1, -1):
        m = base_month - i
        y = base_year
        while m <= 0:
            m += 12
            y -= 1
        months.append(f"{y}-{m:02d}")
    return months


def get_iso_weeks_in_month(month_key: str) -> list[dict]:
    """해당 월에 걸치는 ISO 주차 목록 (오래된→최신 순)"""
    weeks: list[dict] = []
    for wk in _iso_week_keys_in_month(month_key):
        weeks.append({"week": wk, "week_label": get_planner_week_label(wk)})
    return weeks


def fetch_ga4_metrics_monthly(month_key: str) -> dict[str, int]:
    """GA4 Data API로 월간 지표 조회."""
    try:
        from google.analytics.data_v1beta.types import DateRange, Metric, RunReportRequest
        client = _ga4_client()
        if client is None:
            return {"mau": 0, "new_users": 0, "sessions": 0}
        start_date, end_date = get_month_date_range(month_key)
        request = RunReportRequest(
            property=f"properties/{GA4_PROPERTY_ID}",
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            metrics=[
                Metric(name="activeUsers"),
                Metric(name="newUsers"),
                Metric(name="sessions"),
            ],
        )
        response = client.run_report(request)
        row = response.rows[0] if response.rows else None
        vals = [int(v.value) for v in row.metric_values] if row else [0, 0, 0]
        return {"mau": vals[0], "new_users": vals[1], "sessions": vals[2]}
    except Exception as e:
        print(f"[GA4 Monthly] 조회 실패: {e}")
        return {"mau": 0, "new_users": 0, "sessions": 0}


APP_LAUNCH_DATE = os.getenv("APP_LAUNCH_DATE", "2022-01-01")


def fetch_new_users_by_platform(month_key: str) -> dict[str, int]:
    """신규 가입자를 OS(iOS/Android/Web 등)별로 구분."""
    try:
        from google.analytics.data_v1beta.types import DateRange, Dimension, Metric, RunReportRequest
        client = _ga4_client()
        if client is None:
            return {}
        start_date, end_date = get_month_date_range(month_key)
        request = RunReportRequest(
            property=f"properties/{GA4_PROPERTY_ID}",
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            dimensions=[Dimension(name="operatingSystem")],
            metrics=[Metric(name="newUsers")],
        )
        response = client.run_report(request)
        result = {}
        for row in response.rows:
            os_name = row.dimension_values[0].value
            count   = int(row.metric_values[0].value)
            result[os_name] = result.get(os_name, 0) + count
        return result
    except Exception as e:
        print(f"[GA4 플랫폼별 신규] 조회 실패: {e}")
        return {}


def fetch_cumulative_users(until_month: str) -> int:
    """앱 출시일 ~ 해당 월 말일까지의 누적 가입자 (totalUsers)."""
    try:
        from google.analytics.data_v1beta.types import DateRange, Metric, RunReportRequest
        client = _ga4_client()
        if client is None:
            return 0
        _, end_date = get_month_date_range(until_month)
        request = RunReportRequest(
            property=f"properties/{GA4_PROPERTY_ID}",
            date_ranges=[DateRange(start_date=APP_LAUNCH_DATE, end_date=end_date)],
            metrics=[Metric(name="totalUsers")],
        )
        response = client.run_report(request)
        row = response.rows[0] if response.rows else None
        return int(row.metric_values[0].value) if row else 0
    except Exception as e:
        print(f"[GA4 누적 가입자] 조회 실패: {e}")
        return 0


def _sunday_of_week(d: date) -> date:
    """GA4 동질집단 탐색분석 주차 시작일 (일요일)."""
    return d - timedelta(days=(d.weekday() + 1) % 7)


def _first_sunday_in_month(year: int, month: int) -> date:
    """해당 월에 코호트가 시작되는 첫 일요일."""
    first = date(year, month, 1)
    sun = _sunday_of_week(first)
    if sun < first:
        sun += timedelta(days=7)
    return sun


def _ga4_cohort_weeks_for_data_month(month_key: str) -> list[tuple[date, date]]:
    """GA4 CSV와 동일한 일~토 코호트 주차 목록.

    - 전달 마지막 주 (전달 말일 포함 주, 예: 4/26~5/2)
    - 이번 달 주차 (마지막 완전 주 + 말일 부분 주 제외)
    """
    import calendar as _cal

    year, month = map(int, month_key.split("-"))
    prev_year = year if month > 1 else year - 1
    prev_month = month - 1 if month > 1 else 12
    prev_last = date(prev_year, prev_month, _cal.monthrange(prev_year, prev_month)[1])
    last_day = date(year, month, _cal.monthrange(year, month)[1])

    prev_ws = _sunday_of_week(prev_last)
    prev_we = prev_ws + timedelta(days=6)

    weeks_in_month: list[tuple[date, date]] = []
    ws = _first_sunday_in_month(year, month)
    while ws <= last_day:
        weeks_in_month.append((ws, min(ws + timedelta(days=6), last_day)))
        ws += timedelta(days=7)

    # 마지막 주 제외 (W1 미완료): 말일 부분 주가 있으면 2개, 없으면 1개 제외
    if not weeks_in_month:
        this_weeks: list[tuple[date, date]] = []
    elif len(weeks_in_month) >= 2 and (weeks_in_month[-1][1] - weeks_in_month[-1][0]).days < 6:
        this_weeks = weeks_in_month[:-2]
    elif len(weeks_in_month) >= 1:
        this_weeks = weeks_in_month[:-1]
    else:
        this_weeks = []

    if this_weeks and prev_ws == this_weeks[0][0]:
        target_weeks = this_weeks
    else:
        target_weeks = [(prev_ws, prev_we)] + this_weeks

    return target_weeks


def _week_key(ws: date, we: date) -> str:
    return f"{ws.strftime('%Y%m%d')}-{we.strftime('%Y%m%d')}"


_cohort_csv_cache: dict[str, dict] | None = None
_cohort_csv_mtime: float | None = None


def _parse_cohort_retention_csv(path: Path) -> dict[str, dict]:
    """GA4 동질집단 탐색분석 CSV 파싱.

    W1(0001) 행만 사용. key = YYYYMMDD-YYYYMMDD
    value = {cohort_total, w1_active, rate(%)} 
    """
    result: dict[str, dict] = {}
    if not path.exists():
        print(f"[W1 CSV] 파일 없음: {path}")
        return result

    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("주간"):
                continue
            parts = line.split(",")
            if len(parts) < 5:
                continue
            nth, date_range, col3, col4, col5 = parts[0], parts[1], parts[2], parts[3], parts[4]
            if nth != "0001":
                continue
            if len(date_range) != 17 or date_range[8] != "-":
                continue
            if "RESERVED" in date_range or not col3.isdigit():
                continue
            try:
                total = int(col3)
                active = int(col4)
                rate = round(float(col5) * 100, 1)
            except ValueError:
                continue
            result[date_range] = {
                "cohort_total": total,
                "w1_active": active,
                "rate": rate,
            }
    return result


def _load_cohort_retention_csv() -> dict[str, dict]:
    global _cohort_csv_cache, _cohort_csv_mtime
    path = COHORT_RETENTION_CSV
    if not path.exists():
        return {}
    mtime = path.stat().st_mtime
    if _cohort_csv_cache is not None and _cohort_csv_mtime == mtime:
        return _cohort_csv_cache
    _cohort_csv_cache = _parse_cohort_retention_csv(path)
    _cohort_csv_mtime = mtime
    print(f"[W1 CSV] {len(_cohort_csv_cache)}개 주차 로드 ({path.name})")
    return _cohort_csv_cache


def fetch_d7_retention_weekly(month_key: str) -> dict:
    """주차별 W1 리텐션 — GA4 동질집단 탐색 CSV 기준.

    CSV: data/cohort_retention.csv (COHORT_RETENTION_CSV로 경로 변경 가능)
    GA4에서 내보낸 CSV를 교체하면 최신 데이터 반영.
    """
    csv_data = _load_cohort_retention_csv()
    target_weeks = _ga4_cohort_weeks_for_data_month(month_key)

    result_weeks = []
    valid_rates = []
    for ws, we in target_weeks:
        key = _week_key(ws, we)
        entry = csv_data.get(key)
        label = f"{ws.month}/{ws.day}~{we.month}/{we.day}"
        if entry:
            result_weeks.append({
                "label": label,
                "week_start": ws.isoformat(),
                "rate": entry["rate"],
                "day0": entry["cohort_total"],
                "day7": entry["w1_active"],
            })
            valid_rates.append(entry["rate"])
        else:
            print(f"[W1 CSV] {key} 데이터 없음")
            result_weeks.append({
                "label": label,
                "week_start": ws.isoformat(),
                "rate": None,
                "day0": 0,
                "day7": 0,
            })

    avg_rate = round(sum(valid_rates) / len(valid_rates), 1) if valid_rates else None
    return {"weeks": result_weeks, "avg_rate": avg_rate}


_overview_csv_cache: dict[str, dict] | None = None
_overview_csv_mtime: float | None = None


def _parse_date_from_header(line: str) -> date | None:
    """'# 시작일: 20250101' → date"""
    if "시작일:" not in line:
        return None
    raw = line.split("시작일:")[-1].strip()
    if len(raw) != 8 or not raw.isdigit():
        return None
    return date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))


def _month_key(d: date) -> str:
    return f"{d.year}-{d.month:02d}"


def _parse_ga4_overview_csv(path: Path) -> dict[str, dict]:
    """GA4 보고서 개요 CSV → 월별 {mau, new_users}.

    - MAU: 일별 추이 '30일' 컬럼, 각 월 마지막 날 값
    - 신규: 주별 '새 사용자 수' 합산 (주 시작일 기준 월)
    """
    from collections import defaultdict

    result: dict[str, dict] = {}
    if not path.exists():
        print(f"[Overview CSV] 파일 없음: {path}")
        return result

    section: str | None = None
    section_start: date | None = None
    monthly_mau: dict[str, int] = {}
    monthly_new: dict[str, int] = defaultdict(int)

    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            if line.startswith("#"):
                d = _parse_date_from_header(line)
                if d:
                    section_start = d
                if "활성 사용자 추이" in line:
                    section = "daily"
                continue

            if line in ("N주,활성 사용자",):
                section = "weekly_active"
                continue
            if line in ("N주,새 사용자 수",):
                section = "weekly_new"
                continue
            if line == "N일,30일,7일,1일":
                section = "daily"
                continue

            parts = line.split(",")
            if section == "weekly_new" and len(parts) >= 2 and section_start:
                week_label, val_str = parts[0], parts[1]
                if not week_label.isdigit() or not val_str.isdigit():
                    continue
                week_start = section_start + timedelta(weeks=int(week_label))
                monthly_new[_month_key(week_start)] += int(val_str)

            elif section == "daily" and len(parts) >= 2 and section_start:
                day_label, mau_30_str = parts[0], parts[1]
                if not day_label.isdigit() or not mau_30_str.isdigit():
                    continue
                d = section_start + timedelta(days=int(day_label))
                monthly_mau[_month_key(d)] = int(mau_30_str)

    all_months = set(monthly_mau) | set(monthly_new)
    for mk in all_months:
        entry: dict[str, int] = {}
        if mk in monthly_mau:
            entry["mau"] = monthly_mau[mk]
        if mk in monthly_new:
            entry["new_users"] = monthly_new[mk]
        result[mk] = entry
    return result


def _load_ga4_overview_csv() -> dict[str, dict]:
    global _overview_csv_cache, _overview_csv_mtime
    path = GA4_OVERVIEW_CSV
    if not path.exists():
        return {}
    mtime = path.stat().st_mtime
    if _overview_csv_cache is not None and _overview_csv_mtime == mtime:
        return _overview_csv_cache
    _overview_csv_cache = _parse_ga4_overview_csv(path)
    _overview_csv_mtime = mtime
    print(f"[Overview CSV] {len(_overview_csv_cache)}개월 로드 ({path.name})")
    return _overview_csv_cache


def _parse_korean_date(s: str) -> date | None:
    """'2025년 6월 1일' → date"""
    try:
        y_part, rest = s.strip().split("년", 1)
        m_part, d_part = rest.split("월", 1)
        return date(int(y_part), int(m_part.strip()), int(d_part.replace("일", "").strip()))
    except (ValueError, IndexError):
        return None


def _parse_dot_date(s: str) -> date | None:
    """'24. 5. 29.' → date"""
    try:
        parts = [p.strip() for p in s.strip().rstrip(".").split(".") if p.strip()]
        if len(parts) != 3:
            return None
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
        if y < 100:
            y += 2000
        return date(y, m, d)
    except ValueError:
        return None


_acquisition_csv_cache: dict[str, int] | None = None
_acquisition_csv_mtime: float | None = None
_downloads_csv_cache: dict[str, int] | None = None
_downloads_csv_mtime: float | None = None


def _parse_user_acquisition_csv(path: Path) -> dict[str, int]:
    """Android Firebase 사용자 획득 CSV → 월별 신규 (모든 국가/지역 컬럼)."""
    from collections import defaultdict

    monthly: dict[str, int] = defaultdict(int)
    if not path.exists():
        return {}

    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("날짜,"):
                continue
            parts = line.split(",")
            if len(parts) < 2:
                continue
            d = _parse_korean_date(parts[0])
            if not d:
                continue
            try:
                val = int(float(parts[1]))
            except ValueError:
                continue
            monthly[_month_key(d)] += val
    return dict(monthly)


def _parse_app_downloads_csv(path: Path) -> dict[str, int]:
    """iOS App Store 다운로드 CSV → 월별 다운로드 합."""
    from collections import defaultdict

    monthly: dict[str, int] = defaultdict(int)
    if not path.exists():
        return {}

    started = False
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if line.startswith("날짜,"):
                started = True
                continue
            if not started or not line:
                continue
            parts = line.split(",")
            if len(parts) < 2:
                continue
            d = _parse_dot_date(parts[0])
            if not d:
                continue
            try:
                val = int(float(parts[1]))
            except ValueError:
                continue
            monthly[_month_key(d)] += val
    return dict(monthly)


def _load_user_acquisition_csv() -> dict[str, int]:
    global _acquisition_csv_cache, _acquisition_csv_mtime
    path = USER_ACQUISITION_CSV
    if not path.exists():
        return {}
    mtime = path.stat().st_mtime
    if _acquisition_csv_cache is not None and _acquisition_csv_mtime == mtime:
        return _acquisition_csv_cache
    _acquisition_csv_cache = _parse_user_acquisition_csv(path)
    _acquisition_csv_mtime = mtime
    print(f"[Acquisition CSV] {len(_acquisition_csv_cache)}개월 로드 ({path.name})")
    return _acquisition_csv_cache


def _load_app_downloads_csv() -> dict[str, int]:
    global _downloads_csv_cache, _downloads_csv_mtime
    path = APP_DOWNLOADS_CSV
    if not path.exists():
        return {}
    mtime = path.stat().st_mtime
    if _downloads_csv_cache is not None and _downloads_csv_mtime == mtime:
        return _downloads_csv_cache
    _downloads_csv_cache = _parse_app_downloads_csv(path)
    _downloads_csv_mtime = mtime
    print(f"[Downloads CSV] {len(_downloads_csv_cache)}개월 로드 ({path.name})")
    return _downloads_csv_cache


def _get_csv_new_users_by_platform(month_key: str) -> dict[str, int] | None:
    """월별 신규 iOS(App Store) + Android(Firebase) — 플랫폼별."""
    ios = _load_app_downloads_csv().get(month_key, 0)
    android = _load_user_acquisition_csv().get(month_key, 0)
    if ios or android:
        return {"ios": ios, "android": android}
    return None


def _get_csv_new_users(month_key: str) -> int | None:
    """월별 신규 합계: iOS App Store + Android Firebase (모든 국가)."""
    plat = _get_csv_new_users_by_platform(month_key)
    if plat is None:
        return None
    return plat["ios"] + plat["android"]


def _merge_trend_with_overview(trend_data: list[dict]) -> list[dict]:
    """MAU: GA4 + overview CSV. 신규: iOS+Android CSV 합산 우선."""
    overview = _load_ga4_overview_csv()
    for item in trend_data:
        mk = item["month"]
        ov = overview.get(mk, {})
        if not item.get("mau") and ov.get("mau"):
            item["mau"] = ov["mau"]
        csv_new = _get_csv_new_users(mk)
        if csv_new is not None:
            item["new_users"] = csv_new
        elif not item.get("new_users") and ov.get("new_users"):
            item["new_users"] = ov["new_users"]
    return trend_data


def fetch_ad_events_monthly(month_key: str, event_names: list[str]) -> dict[str, int]:
    """월 단위 이벤트 카운트."""
    try:
        from google.analytics.data_v1beta.types import (
            DateRange, Dimension, FilterExpression,
            Filter, FilterExpressionList, Metric, RunReportRequest,
        )
        client = _ga4_client()
        if client is None:
            return {}
        start_date, end_date = get_month_date_range(month_key)
        request = RunReportRequest(
            property=f"properties/{GA4_PROPERTY_ID}",
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            dimensions=[Dimension(name="eventName")],
            metrics=[Metric(name="eventCount")],
            dimension_filter=FilterExpression(
                or_group=FilterExpressionList(
                    expressions=[
                        FilterExpression(filter=Filter(
                            field_name="eventName",
                            string_filter=Filter.StringFilter(value=evt),
                        ))
                        for evt in event_names
                    ]
                )
            ),
        )
        response = client.run_report(request)
        return {
            row.dimension_values[0].value: int(row.metric_values[0].value)
            for row in response.rows
        }
    except Exception as e:
        print(f"[GA4 Monthly Events] 조회 실패: {e}")
        return {}


# ──────────────────────────────────────────────
# GA4 데이터 조회
# ──────────────────────────────────────────────
TOKEN_FILE = Path(__file__).parent / "token.json"
GA4_SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]


def _ga4_client():
    """GA4 클라이언트 생성. token.json → 서비스 계정 순으로 시도. 실패 시 None."""
    try:
        from google.analytics.data_v1beta import BetaAnalyticsDataClient

        def _oauth_client(creds):
            from google.auth.transport.requests import Request
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
            if creds.valid:
                return BetaAnalyticsDataClient(credentials=creds)
            return None

        # 1순위: token.json (OAuth 사용자 인증)
        if TOKEN_FILE.exists():
            from google.oauth2.credentials import Credentials
            creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), GA4_SCOPES)
            client = _oauth_client(creds)
            if client:
                TOKEN_FILE.write_text(creds.to_json())
                return client

        # 1-b: OAuth token JSON 환경변수 (Railway/Render)
        token_json = os.getenv("GOOGLE_TOKEN_JSON", "").strip()
        if token_json:
            from google.oauth2.credentials import Credentials
            creds = Credentials.from_authorized_user_info(json.loads(token_json), GA4_SCOPES)
            client = _oauth_client(creds)
            if client:
                return client

        # 2순위: 서비스 계정 JSON 환경변수 (Railway/Render)
        creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON", "").strip()
        if creds_json:
            from google.oauth2 import service_account
            info = json.loads(creds_json)
            creds = service_account.Credentials.from_service_account_info(info, scopes=GA4_SCOPES)
            return BetaAnalyticsDataClient(credentials=creds)

        # 3순위: 서비스 계정 파일 (GOOGLE_APPLICATION_CREDENTIALS)
        svc_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if svc_path and Path(svc_path).exists():
            return BetaAnalyticsDataClient()

        return None
    except Exception as e:
        print(f"[GA4] 클라이언트 생성 실패: {e}")
        return None


def fetch_ga4_metrics(week_key: str) -> dict[str, int]:
    """GA4 Data API로 주간 지표 조회. 실패 시 0 반환."""
    try:
        from google.analytics.data_v1beta.types import DateRange, Metric, RunReportRequest

        client = _ga4_client()
        if client is None:
            return {"mau": 0, "new_users": 0, "sessions": 0}

        start_date, end_date = get_week_date_range(week_key)
        request = RunReportRequest(
            property=f"properties/{GA4_PROPERTY_ID}",
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            metrics=[
                Metric(name="activeUsers"),
                Metric(name="newUsers"),
                Metric(name="sessions"),
            ],
        )
        response = client.run_report(request)
        row = response.rows[0] if response.rows else None
        vals = [int(v.value) for v in row.metric_values] if row else [0, 0, 0]
        return {"mau": vals[0], "new_users": vals[1], "sessions": vals[2]}
    except Exception as e:
        print(f"[GA4] 조회 실패 (수동 입력으로 대체 가능): {e}")
        return {"mau": 0, "new_users": 0, "sessions": 0}


def _fetch_ad_events_by_name(week_key: str, event_names: list[str]) -> dict[str, int]:
    """지정한 이벤트명 목록의 eventCount를 {eventName: count} 로 반환."""
    try:
        from google.analytics.data_v1beta.types import (
            DateRange, Dimension, FilterExpression,
            Filter, FilterExpressionList, Metric, RunReportRequest,
        )
        client = _ga4_client()
        if client is None:
            return {}
        start_date, end_date = get_week_date_range(week_key)
        request = RunReportRequest(
            property=f"properties/{GA4_PROPERTY_ID}",
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)],
            dimensions=[Dimension(name="eventName")],
            metrics=[Metric(name="eventCount")],
            dimension_filter=FilterExpression(
                or_group=FilterExpressionList(
                    expressions=[
                        FilterExpression(filter=Filter(
                            field_name="eventName",
                            string_filter=Filter.StringFilter(value=evt),
                        ))
                        for evt in event_names
                    ]
                )
            ),
        )
        response = client.run_report(request)
        return {
            row.dimension_values[0].value: int(row.metric_values[0].value)
            for row in response.rows
        }
    except Exception as e:
        print(f"[GA4] 이벤트 조회 실패 ({event_names}): {e}")
        return {}


# placement id → 클릭 이벤트명
CLICK_EVENT_MAP = {
    "top":          "click_home_category_banner",
    "center":       "click_home_ad_banner",
    "bottom":       "click_home_magazine_banner",
    "popular_slot": "click_home_popular_slot_ad",
    "popup":        "click_home_popup",
}

# placement id → 노출 이벤트명
IMPRESSION_EVENT_MAP = {
    "top":          "view_home_category_banner",
    "center":       "view_home_styled_banner",
    "bottom":       "view_home_magazine_banner",
    "popular_slot": "view_home_popular_slot_ad",
    "popup":        "view_home_popup",
}


def fetch_ad_placement_clicks(week_key: str) -> dict[str, int]:
    """광고 위치별 클릭 수. 반환: {"top": 123, "center": 45, ...}"""
    raw = _fetch_ad_events_by_name(week_key, list(CLICK_EVENT_MAP.values()))
    event_to_placement = {v: k for k, v in CLICK_EVENT_MAP.items()}
    return {event_to_placement[evt]: cnt for evt, cnt in raw.items() if evt in event_to_placement}


def fetch_ad_placement_impressions(week_key: str) -> dict[str, int]:
    """광고 위치별 노출 수. 반환: {"top": 5000, "popup": 120, ...}"""
    raw = _fetch_ad_events_by_name(week_key, list(IMPRESSION_EVENT_MAP.values()))
    event_to_placement = {v: k for k, v in IMPRESSION_EVENT_MAP.items()}
    return {event_to_placement[evt]: cnt for evt, cnt in raw.items() if evt in event_to_placement}


def _placement_impression_count(impressions: dict[str, int], placement_id: str) -> int | None:
    """노출 이벤트가 정의된 placement는 0 포함, 없으면 None."""
    if placement_id in IMPRESSION_EVENT_MAP:
        return impressions.get(placement_id, 0)
    return impressions.get(placement_id)


def _placement_ctr(clicks: int, impressions: int | None) -> float | None:
    if impressions is None:
        return None
    if impressions <= 0:
        return 0.0
    return round(clicks / impressions * 100, 2)


def fetch_ad_placement_clicks_monthly(month_key: str) -> dict[str, int]:
    """광고 위치별 월간 클릭 수."""
    raw = fetch_ad_events_monthly(month_key, list(CLICK_EVENT_MAP.values()))
    event_to_placement = {v: k for k, v in CLICK_EVENT_MAP.items()}
    return {event_to_placement[evt]: cnt for evt, cnt in raw.items() if evt in event_to_placement}


def fetch_ad_placement_impressions_monthly(month_key: str) -> dict[str, int]:
    """광고 위치별 월간 노출 수."""
    raw = fetch_ad_events_monthly(month_key, list(IMPRESSION_EVENT_MAP.values()))
    event_to_placement = {v: k for k, v in IMPRESSION_EVENT_MAP.items()}
    return {event_to_placement[evt]: cnt for evt, cnt in raw.items() if evt in event_to_placement}


# ──────────────────────────────────────────────
# API 모델
# ──────────────────────────────────────────────
class TargetSaveRequest(BaseModel):
    week: str
    targets: dict[str, float]


class ManualDataSaveRequest(BaseModel):
    week: str
    data: dict[str, float]


class AdConversionSaveRequest(BaseModel):
    week: str
    rates: dict[str, float]  # placement → conversion_rate (%)


class AdPlacementMetaSaveRequest(BaseModel):
    week: str
    placement: str
    field: str  # revenue | note
    value: Optional[Union[str, int, float]] = None


class WeeklyNotesSaveRequest(BaseModel):
    week: str
    kpi_summary: str = ""
    project_progress: str = ""
    next_week_strategy: str = ""


class WeeklyTaskItem(BaseModel):
    id: str
    text: str
    done: bool = False


class WeeklyTasksSaveRequest(BaseModel):
    week: str
    tasks: list[WeeklyTaskItem] = []


class MonthlyFeedbackSaveRequest(BaseModel):
    month: str
    feedback: str = ""


class MonthlyPlanSaveRequest(BaseModel):
    month: str
    author: str = ""
    north_star: str = ""
    mau_target: int = 0
    goals: list[dict] = []
    kpt_keep: str = ""
    kpt_problem: str = ""
    kpt_try: str = ""
    next_actions: list[dict] = []
    ad_revenues: dict[str, float] = {}


class WeeklyPlanSaveRequest(BaseModel):
    week: str
    author: str = ""
    north_star: str = ""
    goals: list[dict] = []
    actions: list[dict] = []
    ad_revenues: dict[str, float] = {}


# ──────────────────────────────────────────────
# API 라우트
# ──────────────────────────────────────────────
@app.get("/api/kpi")
def get_kpi(week: Optional[str] = None):
    """주차별 전체 KPI 데이터 반환"""
    week = week or get_iso_week_key()
    prev_week = prev_week_key(week)

    targets = get_targets(week)
    manual = get_manual_data(week)
    prev_manual = get_manual_data(prev_week)

    with ThreadPoolExecutor(max_workers=2) as ex:
        f_ga4      = ex.submit(fetch_ga4_metrics, week)
        f_ga4_prev = ex.submit(fetch_ga4_metrics, prev_week)
    ga4      = f_ga4.result()
    ga4_prev = f_ga4_prev.result()

    entries = []
    for kpi in KPI_DEFINITIONS:
        kid = kpi["id"]
        source = kpi["source"]

        if source == "ga4":
            value = ga4.get(kid, 0)
            prev_value = ga4_prev.get(kid, 0)
        else:
            value = manual.get(kid, 0)
            prev_value = prev_manual.get(kid, 0)

        target = targets.get(kid, 0)
        achievement = (value / target * 100) if target > 0 else 0
        wow = ((value - prev_value) / prev_value * 100) if prev_value > 0 else None

        entries.append({
            **kpi,
            "week": week,
            "value": value,
            "target": target,
            "prev_value": prev_value,
            "achievement_rate": round(achievement, 1),
            "wow_change": round(wow, 1) if wow is not None else None,
        })

    return {
        "week": week,
        "week_label": get_week_label(week),
        "entries": entries,
    }


@app.get("/api/kpi/trend")
def get_trend(kpi_id: str, weeks: int = 8, from_week: Optional[str] = None):
    """특정 KPI의 최근 N주 트렌드"""
    kpi_def = next((k for k in KPI_DEFINITIONS if k["id"] == kpi_id), None)
    if not kpi_def:
        raise HTTPException(status_code=404, detail="KPI not found")

    week_list = recent_week_keys(weeks, from_week)
    trend = []
    for wk in week_list:
        if kpi_def["source"] == "ga4":
            ga4 = fetch_ga4_metrics(wk)
            value = ga4.get(kpi_id, 0)
        else:
            manual = get_manual_data(wk)
            value = manual.get(kpi_id, 0)

        target = get_targets(wk).get(kpi_id, 0)
        trend.append({
            "week": wk,
            "week_label": get_week_label(wk),
            "value": value,
            "target": target,
            "achievement_rate": round(value / target * 100, 1) if target > 0 else 0,
        })

    return {"kpi_id": kpi_id, "kpi_def": kpi_def, "trend": trend}


@app.get("/api/kpi/daily")
def get_kpi_daily(week: Optional[str] = None, kpi_id: str = ""):
    """주차 내 KPI 일별 (월~일). GA4 자동 지표만."""
    week = week or get_iso_week_key()
    kpi_def = next((k for k in KPI_DEFINITIONS if k["id"] == kpi_id), None)
    if not kpi_def:
        raise HTTPException(status_code=404, detail="KPI not found")
    if kpi_def["source"] != "ga4":
        return {
            "week": week,
            "week_label": get_week_label(week),
            "kpi_id": kpi_id,
            "kpi_def": kpi_def,
            "days": get_week_days(week),
            "week_total": 0,
            "manual_only": True,
        }
    raw = _fetch_ga4_metric_daily(week, kpi_id)
    days, total = _build_daily_series(week, raw)
    daily_label = "일 활성" if kpi_id == "mau" else kpi_def["name"]
    return {
        "week": week,
        "week_label": get_week_label(week),
        "kpi_id": kpi_id,
        "kpi_def": kpi_def,
        "daily_label": daily_label,
        "days": days,
        "week_total": total,
        "manual_only": False,
    }


@app.put("/api/kpi/targets")
def update_targets(body: TargetSaveRequest):
    """주간 목표 저장"""
    save_targets(body.week, body.targets)
    return {"ok": True, "saved": len(body.targets)}


@app.post("/api/kpi/manual")
def update_manual(body: ManualDataSaveRequest):
    """수동 데이터 저장"""
    save_manual_data(body.week, body.data)
    return {"ok": True, "saved": len(body.data)}


@app.get("/api/kpi/ad-placements")
def get_ad_placements(week: Optional[str] = None):
    """광고 위치별 클릭수·노출수·CTR(GA4 자동) + 전환율(수동) 반환"""
    week = week or get_iso_week_key()
    prev_week = prev_week_key(week)

    with ThreadPoolExecutor(max_workers=3) as ex:
        f_clicks      = ex.submit(fetch_ad_placement_clicks, week)
        f_prev_clicks = ex.submit(fetch_ad_placement_clicks, prev_week)
        f_impressions = ex.submit(fetch_ad_placement_impressions, week)
    clicks      = f_clicks.result()
    prev_clicks = f_prev_clicks.result()
    impressions = f_impressions.result()
    conversions = get_ad_conversions(week)
    meta = get_ad_placement_meta(week)

    result = []
    for p in PLACEMENTS:
        pid   = p["id"]
        c     = clicks.get(pid, 0)
        c_prev = prev_clicks.get(pid, 0)
        imp   = _placement_impression_count(impressions, pid)
        ctr   = _placement_ctr(c, imp)
        m     = meta.get(pid, {})

        wow = round((c - c_prev) / c_prev * 100, 1) if c_prev > 0 else None

        result.append({
            **p,
            "clicks":          c,
            "prev_clicks":     c_prev,
            "wow_change":      wow,
            "impressions":     imp,
            "ctr":             ctr,
            "conversion_rate": conversions.get(pid),
            "revenue":         m.get("revenue"),
            "note":            m.get("note") or "",
        })

    return {"week": week, "week_label": get_week_label(week), "placements": result}


@app.get("/api/kpi/ad-placements/daily")
def get_ad_placement_daily(week: Optional[str] = None, placement: str = ""):
    """광고 위치별 주차 내 일별 클릭·노출 (월~일)."""
    week = week or get_iso_week_key()
    p_def = next((p for p in PLACEMENTS if p["id"] == placement), None)
    if not p_def:
        raise HTTPException(status_code=404, detail="Placement not found")

    click_evt = CLICK_EVENT_MAP.get(placement)
    imp_evt = IMPRESSION_EVENT_MAP.get(placement)

    clicks_raw = _fetch_event_count_daily(week, click_evt) if click_evt else {}
    impr_raw = _fetch_event_count_daily(week, imp_evt) if imp_evt else {}

    days = []
    clicks_total = 0
    impr_total = 0
    for d in get_week_days(week):
        c = clicks_raw.get(d["date"], 0)
        imp = impr_raw.get(d["date"], 0) if imp_evt else None
        clicks_total += c
        if imp is not None:
            impr_total += imp
        days.append({
            **d,
            "clicks": c,
            "impressions": imp,
            "ctr": round(c / imp * 100, 2) if imp and imp > 0 else None,
        })

    return {
        "week": week,
        "week_label": get_week_label(week),
        "placement": placement,
        "label": p_def["label"],
        "has_impressions": imp_evt is not None,
        "days": days,
        "clicks_total": clicks_total,
        "impressions_total": impr_total if imp_evt else None,
    }


@app.put("/api/kpi/ad-placements/conversion")
def update_ad_conversion(body: AdConversionSaveRequest):
    """광고 위치별 전환율 저장"""
    save_ad_conversions(body.week, body.rates)
    return {"ok": True, "saved": len(body.rates)}


@app.put("/api/kpi/ad-placements/meta")
def update_ad_placement_meta(body: AdPlacementMetaSaveRequest):
    """광고 위치별 매출·비고 저장 (주간 인라인 편집)"""
    if body.field not in ("revenue", "note"):
        raise HTTPException(status_code=400, detail="field must be revenue or note")
    if body.placement not in {p["id"] for p in PLACEMENTS}:
        raise HTTPException(status_code=404, detail="Placement not found")
    save_ad_placement_meta_field(body.week, body.placement, body.field, body.value)
    return {"ok": True}


@app.get("/api/kpi/events")
def get_events(week: Optional[str] = None):
    """커스텀 이벤트 카운트 (주별 전체)"""
    week = week or get_iso_week_key()
    prev = prev_week_key(week)
    names = [e["event_name"] for e in CUSTOM_EVENT_DEFINITIONS]
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_counts      = ex.submit(_fetch_ad_events_by_name, week, names)
        f_prev_counts = ex.submit(_fetch_ad_events_by_name, prev, names)
    counts      = f_counts.result()
    prev_counts = f_prev_counts.result()
    result = []
    for evt in CUSTOM_EVENT_DEFINITIONS:
        n = evt["event_name"]
        c = counts.get(n, 0)
        p = prev_counts.get(n, 0)
        wow = round((c - p) / p * 100, 1) if p > 0 else None
        result.append({**evt, "count": c, "prev_count": p, "wow_change": wow})
    return {"week": week, "week_label": get_week_label(week), "events": result}


@app.get("/api/kpi/events/daily")
def get_event_daily(week: Optional[str] = None, event_name: str = ""):
    """커스텀 이벤트 주차 내 일별 (월~일)."""
    week = week or get_iso_week_key()
    evt = next((e for e in CUSTOM_EVENT_DEFINITIONS if e["event_name"] == event_name), None)
    if not evt:
        raise HTTPException(status_code=404, detail="Event not found")
    raw = _fetch_event_count_daily(week, event_name)
    days, total = _build_daily_series(week, raw)
    return {
        "week": week,
        "week_label": get_week_label(week),
        "event_name": event_name,
        "label": evt["label"],
        "category": evt["category"],
        "days": days,
        "week_total": total,
    }


@app.get("/api/kpi/events/trend")
def get_event_trend(event_name: str, weeks: int = 8, from_week: Optional[str] = None):
    """특정 커스텀 이벤트의 최근 N주 추이"""
    evt = next((e for e in CUSTOM_EVENT_DEFINITIONS if e["event_name"] == event_name), None)
    if not evt:
        raise HTTPException(status_code=404, detail="Event not found")
    week_list = recent_week_keys(weeks, from_week)
    trend = []
    for wk in week_list:
        counts = _fetch_ad_events_by_name(wk, [event_name])
        trend.append({
            "week": wk,
            "week_label": get_week_label(wk),
            "count": counts.get(event_name, 0),
        })
    return {"event_name": event_name, "label": evt["label"], "category": evt["category"], "trend": trend}


@app.get("/api/kpi/monthly")
def get_kpi_monthly(month: Optional[str] = None):
    """월별 전체 KPI 데이터 반환"""
    month = month or get_month_key()
    prev = prev_month_key(month)

    with ThreadPoolExecutor(max_workers=2) as ex:
        f_ga4      = ex.submit(fetch_ga4_metrics_monthly, month)
        f_ga4_prev = ex.submit(fetch_ga4_metrics_monthly, prev)
    ga4      = f_ga4.result()
    ga4_prev = f_ga4_prev.result()

    manual      = get_manual_data(month)
    prev_manual = get_manual_data(prev)

    entries = []
    for kpi in KPI_DEFINITIONS:
        kid = kpi["id"]
        if kpi["source"] == "ga4":
            value      = ga4.get(kid, 0)
            prev_value = ga4_prev.get(kid, 0)
        else:
            value      = manual.get(kid, 0)
            prev_value = prev_manual.get(kid, 0)

        mom = round((value - prev_value) / prev_value * 100, 1) if prev_value > 0 else None
        entries.append({
            **kpi,
            "month": month,
            "value": value,
            "prev_value": prev_value,
            "mom_change": mom,
        })

    return {"month": month, "month_label": get_month_label(month), "entries": entries}


@app.get("/api/kpi/monthly/trend")
def get_kpi_monthly_trend(kpi_id: str, months: int = 6, from_month: Optional[str] = None):
    """특정 KPI의 최근 N개월 트렌드"""
    kpi_def = next((k for k in KPI_DEFINITIONS if k["id"] == kpi_id), None)
    if not kpi_def:
        raise HTTPException(status_code=404, detail="KPI not found")

    month_list = recent_month_keys(months, from_month)
    trend = []
    for mk in month_list:
        if kpi_def["source"] == "ga4":
            ga4   = fetch_ga4_metrics_monthly(mk)
            value = ga4.get(kpi_id, 0)
        else:
            manual = get_manual_data(mk)
            value  = manual.get(kpi_id, 0)
        trend.append({
            "month": mk,
            "month_label": get_month_label(mk),
            "value": value,
        })

    return {"kpi_id": kpi_id, "kpi_def": kpi_def, "trend": trend}


@app.get("/api/kpi/events/monthly")
def get_events_monthly(month: Optional[str] = None):
    """커스텀 이벤트 월별 카운트"""
    month = month or get_month_key()
    prev  = prev_month_key(month)
    names = [e["event_name"] for e in CUSTOM_EVENT_DEFINITIONS]
    with ThreadPoolExecutor(max_workers=2) as ex:
        f_counts      = ex.submit(fetch_ad_events_monthly, month, names)
        f_prev_counts = ex.submit(fetch_ad_events_monthly, prev, names)
    counts      = f_counts.result()
    prev_counts = f_prev_counts.result()
    result = []
    for evt in CUSTOM_EVENT_DEFINITIONS:
        n   = evt["event_name"]
        c   = counts.get(n, 0)
        p   = prev_counts.get(n, 0)
        mom = round((c - p) / p * 100, 1) if p > 0 else None
        result.append({**evt, "count": c, "prev_count": p, "mom_change": mom})
    return {"month": month, "month_label": get_month_label(month), "events": result}


@app.get("/api/kpi/events/monthly-trend")
def get_event_monthly_trend(event_name: str, months: int = 6, from_month: Optional[str] = None):
    """특정 커스텀 이벤트의 최근 N개월 추이"""
    evt = next((e for e in CUSTOM_EVENT_DEFINITIONS if e["event_name"] == event_name), None)
    if not evt:
        raise HTTPException(status_code=404, detail="Event not found")
    month_list = recent_month_keys(months, from_month)
    trend = []
    for mk in month_list:
        counts = fetch_ad_events_monthly(mk, [event_name])
        trend.append({
            "month": mk,
            "month_label": get_month_label(mk),
            "count": counts.get(event_name, 0),
        })
    return {"event_name": event_name, "label": evt["label"], "category": evt["category"], "trend": trend}


@app.get("/api/notes")
def get_notes(week: Optional[str] = None):
    """주차별 주간 노트 조회"""
    week = week or get_iso_week_key()
    return get_weekly_notes(week)


@app.put("/api/notes")
def update_notes(body: WeeklyNotesSaveRequest):
    """주간 노트 저장"""
    save_weekly_notes(body.week, body.kpi_summary, body.project_progress, body.next_week_strategy)
    return {"ok": True}


@app.get("/api/weekly-tasks")
def get_weekly_tasks_api(week: Optional[str] = None):
    """주차별 할일 목록"""
    week = week or get_iso_week_key()
    return {
        "week": week,
        "week_label": get_week_label(week),
        "tasks": get_weekly_tasks(week),
    }


@app.put("/api/weekly-tasks")
def update_weekly_tasks(body: WeeklyTasksSaveRequest):
    """주차별 할일 저장"""
    save_weekly_tasks(body.week, [t.model_dump() for t in body.tasks])
    return {"ok": True, "saved": len(body.tasks)}


@app.get("/api/monthly-tasks")
def get_monthly_tasks_api(month: Optional[str] = None):
    """해당 월 ISO 주차별 할일 (주간 할일과 동일 저장소)"""
    month = month or get_month_key()
    weeks = []
    for w in get_iso_weeks_in_month(month):
        wk = w["week"]
        weeks.append({
            **w,
            "tasks": get_weekly_tasks(wk),
            "is_current_week": wk == get_iso_week_key(),
        })
    return {
        "month": month,
        "month_label": get_month_label(month),
        "weeks": weeks,
    }


@app.get("/api/monthly-feedback")
def get_monthly_feedback_api(month: Optional[str] = None):
    """월간 피드백 조회"""
    month = month or get_month_key()
    return {
        "month": month,
        "month_label": get_month_label(month),
        "feedback": get_monthly_feedback(month),
    }


@app.put("/api/monthly-feedback")
def update_monthly_feedback(body: MonthlyFeedbackSaveRequest):
    """월간 피드백 저장"""
    save_monthly_feedback(body.month, body.feedback)
    return {"ok": True}


@app.get("/api/monthly-plan")
def get_monthly_plan_api(month: Optional[str] = None):
    """월간 플래너 데이터 (GA4 자동 지표 + 기능별/광고별 + 저장된 플랜)
    
    지표는 전달 기준: 6월 플래너 → 5월(5/1~5/31) 실적 사용
    MoM 비교는 전전달 기준: 5월 실적 vs 4월 실적
    """
    month = month or get_month_key()
    data_month = prev_month_key(month)           # 실제 지표 조회 기준 (전달)
    prev_data_month = prev_month_key(data_month) # MoM 비교 기준 (전전달)

    names = [e["event_name"] for e in CUSTOM_EVENT_DEFINITIONS]

    # 12개월 트렌드용 월 목록 (data_month 포함 최근 12개월)
    trend_months = recent_month_keys(12, data_month)

    # GA4 API 병렬 실행 (W1 리텐션은 CSV에서 동기 로드)
    d7_data = fetch_d7_retention_weekly(data_month)

    with ThreadPoolExecutor(max_workers=11 + len(trend_months)) as ex:
        f_ga4        = ex.submit(fetch_ga4_metrics_monthly,              data_month)
        f_ga4_prev   = ex.submit(fetch_ga4_metrics_monthly,              prev_data_month)
        f_events     = ex.submit(fetch_ad_events_monthly,                data_month, names)
        f_events_p   = ex.submit(fetch_ad_events_monthly,                prev_data_month, names)
        f_clicks     = ex.submit(fetch_ad_placement_clicks_monthly,      data_month)
        f_clicks_p   = ex.submit(fetch_ad_placement_clicks_monthly,      prev_data_month)
        f_impr       = ex.submit(fetch_ad_placement_impressions_monthly, data_month)
        f_cumulative = ex.submit(fetch_cumulative_users,                 data_month)
        f_platform   = ex.submit(fetch_new_users_by_platform,            data_month)
        # 트렌드: 각 월 GA4 지표 병렬 조회
        f_trend = {mk: ex.submit(fetch_ga4_metrics_monthly, mk) for mk in trend_months}

    ga4              = f_ga4.result()
    ga4_prev         = f_ga4_prev.result()
    event_counts     = f_events.result()
    event_prev       = f_events_p.result()
    clicks           = f_clicks.result()
    prev_clicks      = f_clicks_p.result()
    impressions      = f_impr.result()
    cumulative_users = f_cumulative.result()
    platform_users   = f_platform.result()

    # 트렌드 결과 조립 (GA4 API + overview CSV 병합)
    trend_data = []
    for mk in trend_months:
        r = f_trend[mk].result()
        trend_data.append({
            "month": mk,
            "month_label": get_month_label(mk),
            "mau": r.get("mau", 0),
            "new_users": r.get("new_users", 0),
        })
    trend_data = _merge_trend_with_overview(trend_data)

    def mom(cur, prv):
        return round((cur - prv) / prv * 100, 1) if prv > 0 else None

    events = []
    for evt in CUSTOM_EVENT_DEFINITIONS:
        n = evt["event_name"]
        c = event_counts.get(n, 0)
        p = event_prev.get(n, 0)
        events.append({**evt, "count": c, "prev_count": p, "mom_change": mom(c, p)})

    ad_placements = []
    for p_def in PLACEMENTS:
        pid = p_def["id"]
        c   = clicks.get(pid, 0)
        c_p = prev_clicks.get(pid, 0)
        imp = _placement_impression_count(impressions, pid)
        ctr = _placement_ctr(c, imp)
        ad_placements.append({
            **p_def, "clicks": c, "prev_clicks": c_p,
            "mom_change": mom(c, c_p), "impressions": imp, "ctr": ctr,
        })

    plan = get_monthly_plan(month)

    csv_plat      = _get_csv_new_users_by_platform(data_month)
    csv_plat_prev = _get_csv_new_users_by_platform(prev_data_month)
    csv_new      = _get_csv_new_users(data_month)
    csv_new_prev = _get_csv_new_users(prev_data_month)
    new_users      = csv_new      if csv_new      is not None else ga4.get("new_users", 0)
    new_users_prev = csv_new_prev if csv_new_prev is not None else ga4_prev.get("new_users", 0)
    if csv_plat:
        new_users_ios     = csv_plat["ios"]
        new_users_android = csv_plat["android"]
    else:
        new_users_ios     = platform_users.get("iOS", 0)
        new_users_android = platform_users.get("Android", 0)

    return {
        "month": month,
        "month_label": get_month_label(month),
        "data_month": data_month,
        "data_month_label": get_month_label(data_month),
        "auto_kpi": {
            "mau":              ga4.get("mau", 0),
            "mau_prev":         ga4_prev.get("mau", 0),
            "mau_mom":          mom(ga4.get("mau", 0), ga4_prev.get("mau", 0)),
            "new_users":        new_users,
            "new_users_prev":   new_users_prev,
            "new_users_mom":    mom(new_users, new_users_prev),
            "cumulative_users": cumulative_users,
            # D7 리텐션 (GA4 코호트 주차 평균)
            "d7_retention_rate": d7_data["avg_rate"],
            "d7_day0":           0,
            "d7_day7":           0,
            # 플랫폼별 신규 (CSV: iOS App Store + Android Firebase)
            "new_users_ios":     new_users_ios,
            "new_users_android": new_users_android,
            "new_users_web":     platform_users.get("web", platform_users.get("Web", 0)),
        },
        "trend": trend_data,
        "d7_weekly": d7_data["weeks"],
        "events": events,
        "ad_placements": ad_placements,
        "plan": plan,
    }


@app.put("/api/monthly-plan")
def save_monthly_plan_api(body: MonthlyPlanSaveRequest):
    """월간 플래너 저장"""
    save_monthly_plan(body.month, body.model_dump())
    return {"ok": True}


@app.get("/api/weekly-plan")
def get_weekly_plan_api(week: Optional[str] = None):
    """주간 플래너 데이터

    plan_week: 플래너·할일·노트 기준 (이번 주 계획)
    data_week: GA4 지표 기준 (전주 실적, 월간 플래너의 전달과 동일 개념)
    """
    week = week or get_iso_week_key()
    data_week = prev_week_key(week)
    prev_data_week = prev_week_key(data_week)
    names = [e["event_name"] for e in CUSTOM_EVENT_DEFINITIONS]
    plan_start, plan_end = get_week_date_range(week)
    data_start, data_end = get_week_date_range(data_week)

    with ThreadPoolExecutor(max_workers=6) as ex:
        f_ga4        = ex.submit(fetch_ga4_metrics, data_week)
        f_ga4_prev   = ex.submit(fetch_ga4_metrics, prev_data_week)
        f_events     = ex.submit(_fetch_ad_events_by_name, data_week, names)
        f_events_p   = ex.submit(_fetch_ad_events_by_name, prev_data_week, names)
        f_clicks     = ex.submit(fetch_ad_placement_clicks, data_week)
        f_clicks_p   = ex.submit(fetch_ad_placement_clicks, prev_data_week)
        f_impr       = ex.submit(fetch_ad_placement_impressions, data_week)

    ga4          = f_ga4.result()
    ga4_prev     = f_ga4_prev.result()
    event_counts = f_events.result()
    event_prev   = f_events_p.result()
    clicks       = f_clicks.result()
    prev_clicks  = f_clicks_p.result()
    impressions  = f_impr.result()

    def wow(cur, prv):
        return round((cur - prv) / prv * 100, 1) if prv > 0 else None

    events = []
    for evt in CUSTOM_EVENT_DEFINITIONS:
        n = evt["event_name"]
        c = event_counts.get(n, 0)
        p = event_prev.get(n, 0)
        events.append({**evt, "count": c, "prev_count": p, "wow_change": wow(c, p)})

    ad_placements = []
    for p_def in PLACEMENTS:
        pid = p_def["id"]
        c   = clicks.get(pid, 0)
        c_p = prev_clicks.get(pid, 0)
        imp = _placement_impression_count(impressions, pid)
        ctr = _placement_ctr(c, imp)
        ad_placements.append({
            **p_def, "clicks": c, "prev_clicks": c_p,
            "wow_change": wow(c, c_p), "impressions": imp, "ctr": ctr,
        })

    plan = get_weekly_plan(week)

    return {
        "week": week,
        "week_label": get_planner_week_label(week),
        "date_range": {"start": plan_start, "end": plan_end},
        "data_week": data_week,
        "data_week_label": get_planner_week_label(data_week),
        "data_date_range": {"start": data_start, "end": data_end},
        "auto_kpi": {
            "mau":         ga4.get("mau", 0),
            "mau_prev":    ga4_prev.get("mau", 0),
            "mau_wow":     wow(ga4.get("mau", 0), ga4_prev.get("mau", 0)),
            "new_users":   ga4.get("new_users", 0),
            "new_users_prev": ga4_prev.get("new_users", 0),
            "new_users_wow": wow(ga4.get("new_users", 0), ga4_prev.get("new_users", 0)),
            "sessions":    ga4.get("sessions", 0),
            "sessions_prev": ga4_prev.get("sessions", 0),
            "sessions_wow": wow(ga4.get("sessions", 0), ga4_prev.get("sessions", 0)),
        },
        "events": events,
        "ad_placements": ad_placements,
        "plan": plan,
        "notes": get_weekly_notes(week),
        "tasks": get_weekly_tasks(week),
    }


@app.put("/api/weekly-plan")
def save_weekly_plan_api(body: WeeklyPlanSaveRequest):
    """주간 플래너 저장"""
    save_weekly_plan(body.week, body.model_dump())
    return {"ok": True}


@app.get("/api/monthly-plan/generate-md")
def generate_monthly_plan_md(month: Optional[str] = None):
    """월간 플랜 마크다운 생성 (파일 다운로드)"""
    from fastapi.responses import Response
    month = month or get_month_key()
    d = get_monthly_plan_api(month)
    kpi   = d["auto_kpi"]
    plan  = d["plan"]
    label = d["month_label"]
    trend = d.get("trend", [])

    year_short = month.split("-")[0][2:]
    month_num  = int(month.split("-")[1])
    today_str  = date.today().strftime("%Y.%m.%d")

    def fmt_n(v):
        if v is None: return "—"
        if v >= 10000: return f"{v:,.0f}"
        return str(v)

    def fmt_mom(v):
        if v is None: return "—"
        sign = "+" if v > 0 else ""
        return f"{sign}{v:.1f}%"

    def goal_status(g):
        return g.get("status", "🟡")

    goals_rows = "\n".join(
        f"| {g.get('name','')} | {g.get('target','')} | {g.get('actual','')} | {g.get('actual_rate','')} | {goal_status(g)} |"
        for g in plan.get("goals", [])
    ) or "| (목표 없음) | — | — | — | — |"

    mau_target_str = fmt_n(plan.get("mau_target") or 0) if plan.get("mau_target") else "미설정"

    actions_rows = "\n".join(
        f"| {i+1} | [{a.get('channel','')}] | {a.get('action','')} | {a.get('goal','')} | {a.get('deadline','')} |"
        for i, a in enumerate(plan.get("next_actions", []))
    ) or "| 1 | — | — | — | — |"

    action_task_sections: list[str] = []
    for i, a in enumerate(plan.get("next_actions", [])):
        tasks_md = quill_delta_to_md(a.get("tasks"))
        block = f"#### {i + 1}. [{a.get('channel', '')}] {a.get('action', '')}\n"
        block += f"- 목표: {a.get('goal', '') or '—'} | 마감: {a.get('deadline', '') or '—'}"
        if tasks_md and tasks_md != "- (미입력)":
            block += f"\n\n{tasks_md}"
        action_task_sections.append(block)
    actions_tasks_md = "\n\n".join(action_task_sections) if action_task_sections else "(액션 없음)"

    def fmt_imp(v):
        return f"{v:,}" if v is not None else "—"

    ad_rev = {**_default_ad_revenues(), **(plan.get("ad_revenues") or {})}
    ad_rows = "\n".join(
        f"| {p['label']} | {p['clicks']:,} | {fmt_mom(p['mom_change'])} | {fmt_imp(p['impressions'])} | {fmt_n(p['ctr'])}{'%' if p['ctr'] else ''} | {fmt_n(ad_rev.get(p['id'], 0))} |"
        for p in d["ad_placements"]
    )
    ad_rev_total = sum(ad_rev.get(p["id"], 0) for p in d["ad_placements"])
    ad_rows += f"\n| **합계** | — | — | — | — | **{fmt_n(ad_rev_total)}** |"

    cat_labels = {
        "contest":"대회", "home":"홈", "shoes":"슈즈", "myrun":"마이런",
        "participation":"참가", "record":"기록", "goal":"목표", "funnel":"펀넬", "etc":"기타",
    }
    from itertools import groupby
    events_sorted = sorted(d["events"], key=lambda e: e["category"])
    evt_sections = []
    for cat, group in groupby(events_sorted, key=lambda e: e["category"]):
        rows = "\n".join(
            f"| {e['label']} | {e['count']:,} | {fmt_mom(e['mom_change'])} |"
            for e in group
        )
        evt_sections.append(f"### {cat_labels.get(cat, cat)}\n| 이벤트 | 이번 달 | MoM |\n|--------|--------|-----|\n{rows}")
    events_md = "\n\n".join(evt_sections)

    data_month_label = d["data_month_label"]

    md = f"""# 📋 {year_short}년 {month_num}월 | Monthly Plan | 플랫폼팀

> 작성일: {today_str}  |  작성자: {plan.get('author') or 'OOO'}
> 📌 KPI 기준: **{data_month_label} 실적** (전달 기준)

---

## ① 이번 달 목표 & 달성률

| 핵심 목표 | 목표치 | 실적 | 달성률 | 상태 |
|--------|------|-----|------|-----|
{goals_rows}

> 상태 기준: 🟢 달성 / 🟡 진행중 / 🔴 미달성

---

## ② MAU / 가입자 현황 ({data_month_label} 실적)

### 합계 MAU
| 구분 | 전전달 실적 | 목표 | 전달 실적 | MoM |
|-----|-----------|-----|---------|-----|
| 합계 MAU | {fmt_n(kpi['mau_prev'])} | {mau_target_str} | {fmt_n(kpi['mau'])} | {fmt_mom(kpi['mau_mom'])} |

### 신규 가입자 / 리텐션 / 누적 가입자
| 구분 | 전전달 실적 | 전달 실적 | MoM |
|-----|-----------|---------|-----|
| 신규 가입자 (합계) | {fmt_n(kpi['new_users_prev'])} | {fmt_n(kpi['new_users'])} | {fmt_mom(kpi['new_users_mom'])} |
| ∟ iOS | — | {fmt_n(kpi.get('new_users_ios', 0))} | — |
| ∟ Android | — | {fmt_n(kpi.get('new_users_android', 0))} | — |
| W1 리텐션 (코호트 · GA4) | — | {(str(kpi['d7_retention_rate']) + '%') if kpi.get('d7_retention_rate') is not None else '—'} | — |
| 누적 가입자 | — | {fmt_n(kpi['cumulative_users'])} | — |

### MAU 12개월 추이

```mermaid
xychart-beta
    title "MAU 추이 (12개월)"
    x-axis [{', '.join('"' + d['month_label'].replace('년 ','년 ').replace('월','월') + '"' for d in trend)}]
    bar [{', '.join(str(d['mau']) for d in trend)}]
```

### 신규 가입자 12개월 추이

```mermaid
xychart-beta
    title "신규 가입자 추이 (12개월)"
    x-axis [{', '.join('"' + d['month_label'].replace('년 ','년 ').replace('월','월') + '"' for d in trend)}]
    bar [{', '.join(str(d['new_users']) for d in trend)}]
```

---

## ③ 기능별 지표 ({data_month_label} 실적 · GA4 자동)

{events_md}

---

## ④ 광고별 지표 ({data_month_label} 실적 · GA4 자동 + 매출 수동)

| 위치 | 클릭수 | MoM | 노출수 | CTR | 매출(원) |
|-----|-------|-----|------|-----|---------|
{ad_rows}

---

## ⑤ 월간 회고 (KPT)

**👍 Keep** (잘 된 것, 유지할 것)
{quill_delta_to_md(plan.get('kpt_keep'))}

**⚠️ Problem** (아쉬운 점, 문제 원인)
{quill_delta_to_md(plan.get('kpt_problem'))}

**🚀 Try** (다음 달 개선 시도)
{quill_delta_to_md(plan.get('kpt_try'))}

---

## ⑥ 이번 달 플랜

### 🎯 North Star Metric
> **{plan.get('north_star') or '(미입력)'}**

### 핵심 액션
| # | 채널 | 액션 | 목표 | 마감 |
|---|-----|-----|-----|-----|
{actions_rows}

### 구체적 할일
{actions_tasks_md}

---

# 📣 슬랙 공유용 (복붙)

```
📋 *{month_num}월 Monthly Plan* | 플랫폼팀

*① 이번 달 목표*
{chr(10).join('• ' + g.get('name','') + ' — ' + g.get('actual','?') + ' / 목표 ' + g.get('target','?') + ' (' + goal_status(g) + ')' for g in plan.get('goals', []))}

*② MAU / 가입자*
MAU: 전월 {fmt_n(kpi['mau_prev'])} → {fmt_n(kpi['mau'])} (MoM {fmt_mom(kpi['mau_mom'])})
신규 가입자: {fmt_n(kpi['new_users'])} (MoM {fmt_mom(kpi['new_users_mom'])})

*③ 회고 (KPT 요약)*
👍 Keep: {quill_delta_first_line(plan.get('kpt_keep'))}
⚠️ Problem: {quill_delta_first_line(plan.get('kpt_problem'))}
🚀 Try: {quill_delta_first_line(plan.get('kpt_try'))}

*④ 이번 달 핵심 액션*
{chr(10).join(
        f'{i+1}️⃣ [{a.get("channel","")}] {a.get("action","")}'
        + (chr(10) + '   └ ' + quill_delta_first_line(a.get("tasks"))
           if quill_delta_first_line(a.get("tasks")) != "—" else '')
        for i, a in enumerate(plan.get('next_actions', []))
    )}

🎯 North Star: {plan.get('north_star') or '(미설정)'}
```
"""

    filename = f"{month}_monthly_plan.md"
    return Response(
        content=md.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/weekly-plan/generate-md")
def generate_weekly_plan_md(week: Optional[str] = None):
    """주간 플랜 마크다운 생성 (파일 다운로드)"""
    from fastapi.responses import Response
    week = week or get_iso_week_key()
    d = get_weekly_plan_api(week)
    kpi   = d["auto_kpi"]
    plan  = d["plan"]
    notes = d["notes"]
    tasks = d["tasks"]
    plan_label = d["week_label"]
    data_label = d["data_week_label"]
    data_dr    = d["data_date_range"]
    plan_dr    = d["date_range"]

    today_str = date.today().strftime("%Y.%m.%d")

    def fmt_n(v):
        if v is None:
            return "—"
        if v >= 10000:
            return f"{v:,.0f}"
        return str(v)

    def fmt_wow(v):
        if v is None:
            return "—"
        sign = "+" if v > 0 else ""
        return f"{sign}{v:.1f}%"

    def goal_status(g):
        return g.get("status", "🟡")

    goals_rows = "\n".join(
        f"| {g.get('name','')} | {g.get('target','')} | {g.get('actual','')} | {g.get('actual_rate','')} | {goal_status(g)} |"
        for g in plan.get("goals", [])
    ) or "| (목표 없음) | — | — | — | — |"

    actions_rows = "\n".join(
        f"| {i+1} | [{a.get('channel','')}] | {a.get('action','')} | {a.get('goal','')} | {a.get('deadline','')} |"
        for i, a in enumerate(plan.get("actions", []))
    ) or "| 1 | — | — | — | — |"

    action_task_sections: list[str] = []
    for i, a in enumerate(plan.get("actions", [])):
        tasks_md = quill_delta_to_md(a.get("tasks"))
        block = f"#### {i + 1}. [{a.get('channel', '')}] {a.get('action', '')}\n"
        block += f"- 목표: {a.get('goal', '') or '—'} | 마감: {a.get('deadline', '') or '—'}"
        if tasks_md and tasks_md != "- (미입력)":
            block += f"\n\n{tasks_md}"
        action_task_sections.append(block)
    actions_tasks_md = "\n\n".join(action_task_sections) if action_task_sections else "(액션 없음)"

    def fmt_imp(v):
        return f"{v:,}" if v is not None else "—"

    ad_rev = {**_default_ad_revenues(), **(plan.get("ad_revenues") or {})}
    ad_rows = "\n".join(
        f"| {p['label']} | {p['clicks']:,} | {fmt_wow(p['wow_change'])} | {fmt_imp(p['impressions'])} | {fmt_n(p['ctr'])}{'%' if p['ctr'] else ''} | {fmt_n(ad_rev.get(p['id'], 0))} |"
        for p in d["ad_placements"]
    )
    ad_rev_total = sum(ad_rev.get(p["id"], 0) for p in d["ad_placements"])
    ad_rows += f"\n| **합계** | — | — | — | — | **{fmt_n(ad_rev_total)}** |"

    cat_labels = {
        "contest": "대회", "home": "홈", "shoes": "슈즈", "myrun": "마이런",
        "participation": "참가", "record": "기록", "goal": "목표", "funnel": "펀넬", "etc": "기타",
    }
    from itertools import groupby
    events_sorted = sorted(d["events"], key=lambda e: e["category"])
    evt_sections = []
    for cat, group in groupby(events_sorted, key=lambda e: e["category"]):
        rows = "\n".join(
            f"| {e['label']} | {e['count']:,} | {fmt_wow(e['wow_change'])} |"
            for e in group
        )
        evt_sections.append(f"### {cat_labels.get(cat, cat)}\n| 이벤트 | 실적 | WoW |\n|--------|------|-----|\n{rows}")
    events_md = "\n\n".join(evt_sections)

    task_lines = "\n".join(
        f"- {'[x]' if t.get('done') else '[ ]'} {t.get('text', '')}"
        for t in tasks
    ) or "- (할일 없음)"

    md = f"""# 📋 {plan_label} | Weekly Plan | 플랫폼팀

> 작성일: {today_str}  |  작성자: {plan.get('author') or 'OOO'}
> 📌 플래너 주차: **{plan_label}** ({plan_dr['start']} ~ {plan_dr['end']})
> 📌 KPI 기준: **{data_label} 실적** ({data_dr['start']} ~ {data_dr['end']} · 전주 기준)

---

## ① {plan_label} 목표 & 달성률

| 핵심 목표 | 목표치 | 실적 | 달성률 | 상태 |
|--------|------|-----|------|-----|
{goals_rows}

> 상태 기준: 🟢 달성 / 🟡 진행중 / 🔴 미달성

---

## ② KPI 현황 ({data_label} 실적)

| 구분 | 전전주 | 전주 실적 | WoW |
|-----|------|---------|-----|
| MAU (주간 활성) | {fmt_n(kpi['mau_prev'])} | {fmt_n(kpi['mau'])} | {fmt_wow(kpi['mau_wow'])} |
| 신규 가입자 | {fmt_n(kpi['new_users_prev'])} | {fmt_n(kpi['new_users'])} | {fmt_wow(kpi['new_users_wow'])} |
| 세션 수 | {fmt_n(kpi['sessions_prev'])} | {fmt_n(kpi['sessions'])} | {fmt_wow(kpi['sessions_wow'])} |

---

## ③ 기능별 지표 ({data_label} 실적 · GA4 자동 · WoW)

{events_md}

---

## ④ 광고별 지표 ({data_label} 실적 · GA4 자동 + 매출 수동)

| 위치 | 클릭수 | WoW | 노출수 | CTR | 매출(원) |
|-----|-------|-----|------|-----|---------|
{ad_rows}

---

## ⑤ 주간 플래닝 노트

### 🎯 Weekly KPI Dashboard
{quill_delta_to_md(notes.get('kpi_summary'))}

### 🔧 Project Progress
{quill_delta_to_md(notes.get('project_progress'))}

### 📅 Next Week's Strategy
{quill_delta_to_md(notes.get('next_week_strategy'))}

---

## ⑥ {plan_label} 할일

{task_lines}

---

## ⑦ {plan_label} 핵심 액션

### 🎯 North Star
> **{plan.get('north_star') or '(미입력)'}**

| # | 채널 | 액션 | 목표 | 마감 |
|---|-----|-----|-----|-----|
{actions_rows}

### 구체적 할일
{actions_tasks_md}

---

# 📣 슬랙 공유용 (복붙)

```
📋 *{plan_label} Weekly Plan* | 플랫폼팀

*① 이번 주 목표*
{chr(10).join('• ' + g.get('name','') + ' — ' + g.get('actual','?') + ' / 목표 ' + g.get('target','?') + ' (' + goal_status(g) + ')' for g in plan.get('goals', []))}

*② KPI ({data_label} 실적)*
MAU: {fmt_n(kpi['mau_prev'])} → {fmt_n(kpi['mau'])} (WoW {fmt_wow(kpi['mau_wow'])})
신규: {fmt_n(kpi['new_users'])} (WoW {fmt_wow(kpi['new_users_wow'])})

*③ 할일 ({plan_label})*
{chr(10).join(('✅' if t.get('done') else '⬜') + ' ' + t.get('text','') for t in tasks)}

*④ 핵심 액션*
{chr(10).join(
        f'{i+1}️⃣ [{a.get("channel","")}] {a.get("action","")}'
        + (chr(10) + '   └ ' + quill_delta_first_line(a.get("tasks"))
           if quill_delta_first_line(a.get("tasks")) != "—" else '')
        for i, a in enumerate(plan.get('actions', []))
    )}

🎯 North Star: {plan.get('north_star') or '(미설정)'}
```
"""

    filename = f"{week}_weekly_plan.md"
    return Response(
        content=md.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ──────────────────────────────────────────────
# 대시보드 HTML (단일 파일)
# ──────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
def dashboard():
    return HTMLResponse(content=DASHBOARD_HTML)


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Running Life | 위클리 KPI</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/alpinejs@3.14.3/dist/cdn.min.js" defer></script>
<link rel="preconnect" href="https://cdn.jsdelivr.net">
<link href="https://cdn.jsdelivr.net/npm/quill@2.0.3/dist/quill.snow.css" rel="stylesheet">
<script src="https://cdn.jsdelivr.net/npm/quill@2.0.3/dist/quill.js"></script>
<style>
  [x-cloak] { display: none !important; }
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --bg: #0f172a; --card: #1e293b; --border: #334155;
    --text: #f1f5f9; --muted: #94a3b8; --dim: #475569;
    --indigo: #6366f1; --green: #10b981; --amber: #f59e0b; --red: #ef4444;
  }
  body { background: var(--bg); color: var(--text); font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; min-height: 100vh; }

  /* 헤더 */
  header { position: sticky; top: 0; z-index: 40; background: rgba(15,23,42,.9); backdrop-filter: blur(8px); border-bottom: 1px solid var(--border); padding: 10px 20px; display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
  .logo { display: flex; align-items: center; gap: 10px; }
  .logo-icon { width: 32px; height: 32px; background: var(--indigo); border-radius: 8px; display: flex; align-items: center; justify-content: center; font-size: 16px; }
  .logo h1 { font-size: 13px; font-weight: 700; }
  .logo p { font-size: 11px; color: var(--muted); }

  /* 주차 선택기 */
  .week-nav { display: flex; align-items: center; gap: 6px; }
  .week-nav button { width: 30px; height: 30px; border-radius: 8px; border: 1px solid var(--border); background: transparent; color: var(--muted); cursor: pointer; font-size: 14px; transition: all .15s; }
  .week-nav button:hover:not(:disabled) { border-color: var(--dim); color: var(--text); }
  .week-nav button:disabled { opacity: .3; cursor: not-allowed; }
  .week-badge { border: 1px solid var(--border); background: var(--card); border-radius: 8px; padding: 4px 12px; text-align: center; min-width: 200px; }
  .week-badge .label { font-size: 13px; font-weight: 600; }
  .week-badge .key { font-size: 11px; color: var(--muted); }
  .btn-today { background: rgba(99,102,241,.15); border: 1px solid rgba(99,102,241,.4); color: #a5b4fc; border-radius: 8px; padding: 4px 10px; font-size: 12px; cursor: pointer; transition: all .15s; }
  .btn-today:hover { background: rgba(99,102,241,.25); }

  /* 액션 버튼 */
  .actions { display: flex; gap: 6px; align-items: center; }
  .btn { padding: 6px 12px; border-radius: 8px; font-size: 12px; font-weight: 500; cursor: pointer; border: none; transition: all .15s; }
  .btn-outline { background: var(--card); border: 1px solid var(--border); color: var(--muted); }
  .btn-outline:hover { border-color: var(--dim); color: var(--text); }
  .btn-primary { background: var(--indigo); color: #fff; }
  .btn-primary:hover { background: #4f46e5; }
  .btn-icon { width: 30px; height: 30px; padding: 0; display: flex; align-items: center; justify-content: center; font-size: 16px; }

  /* 메인 */
  main { max-width: 1200px; margin: 0 auto; padding: 24px 20px; }

  /* 요약 배너 */
  .summary-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 24px; }
  .summary-card { background: rgba(30,41,59,.5); border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px; }
  .summary-card .cat-label { font-size: 11px; color: var(--muted); margin-bottom: 4px; }
  .summary-card .rate { font-size: 24px; font-weight: 700; }
  .summary-card .sub { font-size: 11px; color: var(--muted); }

  /* KPI 섹션 */
  .section-title { font-size: 12px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: .05em; margin-bottom: 10px; }
  .kpi-section { margin-bottom: 28px; }
  .kpi-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 10px; }

  /* KPI 카드 */
  .kpi-card-wrap { display: flex; flex-direction: column; min-width: 0; }
  .kpi-card-wrap.expanded { grid-column: 1 / -1; flex-direction: row; align-items: stretch; gap: 0; }
  .kpi-card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 14px; cursor: pointer; transition: all .15s; text-align: left; width: 100%; }
  .kpi-card-wrap.expanded > .kpi-card { flex: 0 0 200px; width: auto; border-radius: 12px 0 0 12px; border-right: none; }
  .kpi-card:hover { border-color: var(--dim); box-shadow: 0 4px 20px rgba(0,0,0,.3); }
  .kpi-card.expanded { border-color: var(--indigo); box-shadow: 0 0 0 1px var(--indigo); border-bottom-left-radius: 12px; border-bottom-right-radius: 0; }
  .kpi-card-wrap.expanded > .kpi-card.expanded { border-bottom-left-radius: 12px; }
  .daily-panel { background: rgba(15,23,42,.55); border: 1px solid var(--indigo); border-top: none; border-radius: 0 0 12px 12px; padding: 14px 16px 16px; margin-top: -1px; }
  .kpi-card-wrap.expanded > .daily-panel { flex: 1; margin-top: 0; border-radius: 0 12px 12px 0; border-top: 1px solid var(--indigo); border-left: none; min-width: 0; }
  .daily-panel-title { font-size: 11px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; margin-bottom: 10px; }
  .daily-chart-wrap { position: relative; height: 180px; margin-bottom: 12px; }
  .daily-table { width: 100%; border-collapse: collapse; font-size: 12px; }
  .daily-table th { padding: 6px 8px; text-align: center; font-size: 11px; font-weight: 600; color: var(--muted); border-bottom: 1px solid var(--border); }
  .daily-table td { padding: 8px; text-align: center; color: var(--text); border-bottom: 1px solid rgba(51,65,85,.35); }
  .daily-table tr:last-child td { border-bottom: none; font-weight: 700; color: #a5b4fc; }
  .daily-table .day-label { color: var(--muted); font-size: 10px; display: block; margin-top: 2px; }
  .daily-table-h th, .daily-table-h td { white-space: nowrap; }
  .daily-table-h tr:last-child td:last-child { color: #a5b4fc; font-weight: 700; }
  .daily-empty { font-size: 12px; color: var(--muted); text-align: center; padding: 16px 0; }
  .placement-row-clickable { cursor: pointer; transition: background .15s; }
  .placement-row-clickable:hover { background: rgba(99,102,241,.06); }
  .placement-row-clickable.expanded { background: rgba(99,102,241,.1); }
  .placement-daily-row td { padding: 0 !important; border-bottom: 1px solid var(--border) !important; }
  .placement-daily-inner { padding: 12px 16px 16px; background: rgba(15,23,42,.4); }
  .kpi-card-header { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px; }
  .kpi-name { font-size: 12px; color: var(--muted); }
  .ga4-badge { background: rgba(99,102,241,.2); color: #a5b4fc; border-radius: 20px; padding: 1px 6px; font-size: 10px; font-weight: 500; }
  .kpi-value { font-size: 22px; font-weight: 700; color: var(--text); }
  .kpi-unit { font-size: 12px; color: var(--muted); margin-left: 2px; }
  .kpi-target { font-size: 11px; color: var(--muted); margin: 2px 0 6px; }

  /* 달성률 바 */
  .progress-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
  .progress-label { font-size: 11px; color: var(--muted); }
  .progress-rate { font-size: 11px; font-weight: 600; }
  .progress-bar-bg { height: 5px; background: var(--border); border-radius: 99px; overflow: hidden; margin-bottom: 6px; }
  .progress-bar-fill { height: 100%; border-radius: 99px; transition: width .4s; }
  .rate-green { color: var(--green); } .fill-green { background: var(--green); }
  .rate-amber { color: var(--amber); } .fill-amber { background: var(--amber); }
  .rate-red { color: var(--red); }   .fill-red { background: var(--red); }
  .rate-none { color: var(--dim); }  .fill-none { background: var(--dim); }

  .wow { font-size: 11px; }
  .wow-up { color: var(--green); } .wow-down { color: var(--red); } .wow-flat { color: var(--dim); }
  .no-data { font-size: 11px; color: var(--dim); margin-top: 4px; }

  /* 트렌드 차트 모달 */
  .trend-modal { background: #0f172a; border: 1px solid var(--border); border-radius: 16px; width: 100%; max-width: 680px; box-shadow: 0 24px 64px rgba(0,0,0,.6); }
  .trend-modal-header { padding: 16px 20px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: center; }
  .trend-title { font-size: 15px; font-weight: 700; }
  .trend-modal-body { padding: 20px; }
  .btn-close { background: none; border: none; color: var(--muted); cursor: pointer; font-size: 20px; line-height: 1; }
  .btn-close:hover { color: var(--text); }

  /* 로딩 스피너 */
  .spinner { width: 28px; height: 28px; border: 2px solid var(--border); border-top-color: var(--indigo); border-radius: 50%; animation: spin .7s linear infinite; margin: 40px auto; }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* 모달 */
  .modal-backdrop { position: fixed; inset: 0; z-index: 50; background: rgba(0,0,0,.6); backdrop-filter: blur(4px); display: flex; align-items: center; justify-content: center; padding: 16px; }
  .modal { background: #0f172a; border: 1px solid var(--border); border-radius: 16px; width: 100%; max-width: 480px; box-shadow: 0 20px 60px rgba(0,0,0,.5); }
  .modal-header { padding: 16px 20px; border-bottom: 1px solid var(--border); display: flex; justify-content: space-between; align-items: flex-start; }
  .modal-title { font-size: 15px; font-weight: 700; }
  .modal-sub { font-size: 11px; color: var(--muted); margin-top: 2px; }
  .modal-body { padding: 16px 20px; max-height: 55vh; overflow-y: auto; }
  .modal-section-title { font-size: 11px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: .05em; margin-bottom: 8px; margin-top: 14px; }
  .modal-section-title:first-child { margin-top: 0; }
  .input-row { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
  .input-row label { font-size: 13px; color: #cbd5e1; min-width: 90px; }
  .input-row input { flex: 1; background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 6px 10px; font-size: 13px; color: var(--text); outline: none; transition: border-color .15s; }
  .input-row input:focus { border-color: var(--indigo); }
  .modal-footer { padding: 12px 20px; border-top: 1px solid var(--border); display: flex; gap: 8px; }
  .modal-footer .btn { flex: 1; padding: 8px; font-size: 13px; font-weight: 600; border-radius: 8px; }
  .btn-cancel { background: transparent; border: 1px solid var(--border); color: var(--muted); cursor: pointer; }
  .btn-cancel:hover { background: var(--card); }
  .btn-save-target { background: var(--indigo); color: #fff; border: none; cursor: pointer; }
  .btn-save-target:hover:not(:disabled) { background: #4f46e5; }
  .btn-save-manual { background: var(--green); color: #fff; border: none; cursor: pointer; }
  .btn-save-manual:hover:not(:disabled) { background: #059669; }
  .btn-save-target:disabled, .btn-save-manual:disabled { opacity: .5; cursor: not-allowed; }

  .error-banner { background: rgba(239,68,68,.1); border: 1px solid rgba(239,68,68,.3); color: #fca5a5; border-radius: 10px; padding: 10px 14px; font-size: 13px; margin-bottom: 16px; }

  /* 광고 위치별 테이블 */
  .placement-section { margin-bottom: 28px; }

  /* 주간 노트 섹션 */
  .notes-section { margin-top: 36px; }
  .notes-section-title { font-size: 11px; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; margin-bottom: 14px; }
  .notes-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
  .note-card { background: var(--card); border: 1px solid var(--border); border-radius: 14px; padding: 16px; display: flex; flex-direction: column; gap: 10px; }
  .note-card-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 2px; }
  .note-card-title { font-size: 13px; font-weight: 700; color: var(--text); display: flex; align-items: center; gap: 6px; }
  .note-save-badge { font-size: 10px; color: #22c55e; opacity: 0; transition: opacity .4s; }
  .note-save-badge.visible { opacity: 1; }
  @media (max-width: 900px) { .notes-grid { grid-template-columns: 1fr; } }

  /* 주간/월간 할일 체크리스트 */
  .task-section { margin-top: 36px; margin-bottom: 28px; }
  .task-week-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 14px; }
  .task-week-card { background: var(--card); border: 1px solid var(--border); border-radius: 14px; padding: 14px; }
  .task-week-card.current { border-color: rgba(99,102,241,.45); box-shadow: 0 0 0 1px rgba(99,102,241,.25); }
  .task-week-header { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 10px; }
  .task-week-title { font-size: 13px; font-weight: 700; color: var(--text); }
  .task-week-meta { font-size: 10px; color: var(--dim); margin-top: 2px; }
  .task-row { display: flex; align-items: flex-start; gap: 8px; padding: 5px 0; }
  .task-row input[type=checkbox] { accent-color: var(--indigo); width: 15px; height: 15px; cursor: pointer; flex-shrink: 0; margin-top: 2px; }
  .task-row-text { flex: 1; font-size: 13px; line-height: 1.45; word-break: break-word; color: var(--text); }
  .task-row-text.done { color: var(--dim); text-decoration: line-through; }
  .task-del { background: none; border: none; color: var(--dim); cursor: pointer; font-size: 15px; line-height: 1; padding: 0 2px; flex-shrink: 0; }
  .task-del:hover { color: var(--red); }
  .task-add-row { display: flex; gap: 6px; margin-top: 10px; }
  .task-add-input { flex: 1; background: rgba(255,255,255,.04); border: 1px solid var(--border); border-radius: 8px; padding: 6px 10px; font-size: 12px; color: var(--text); outline: none; }
  .task-add-input:focus { border-color: var(--indigo); }
  .task-add-btn { background: rgba(99,102,241,.2); border: 1px solid rgba(99,102,241,.4); color: #a5b4fc; border-radius: 8px; padding: 5px 10px; font-size: 12px; cursor: pointer; white-space: nowrap; }
  .task-add-btn:hover { background: rgba(99,102,241,.3); }
  .task-go-week { font-size: 11px; color: #a5b4fc; cursor: pointer; background: none; border: none; padding: 0; text-decoration: underline; white-space: nowrap; }
  .task-empty { font-size: 12px; color: var(--dim); padding: 4px 0 2px; }
  .task-progress { font-size: 11px; color: var(--muted); }
  .feedback-card { background: var(--card); border: 1px solid var(--border); border-radius: 14px; padding: 16px; }
  .feedback-card .ql-editor { min-height: 160px; }

  /* Quill 다크 테마 */
  .ql-toolbar.ql-snow {
    background: rgba(255,255,255,.03);
    border: 1px solid var(--border) !important;
    border-radius: 8px 8px 0 0;
    padding: 6px 8px;
  }
  .ql-container.ql-snow {
    background: rgba(255,255,255,.04);
    border: 1px solid var(--border) !important;
    border-top: none !important;
    border-radius: 0 0 8px 8px;
    font-family: inherit;
    font-size: 13px;
  }
  .ql-editor {
    color: var(--text);
    min-height: 180px;
    line-height: 1.7;
    padding: 12px 14px;
  }
  .ql-editor.ql-blank::before { color: var(--dim); font-style: normal; }

  /* 툴바 아이콘 */
  .ql-snow .ql-stroke { stroke: var(--muted) !important; }
  .ql-snow .ql-fill { fill: var(--muted) !important; }
  .ql-snow .ql-picker-label, .ql-snow .ql-picker { color: var(--muted); }
  .ql-snow .ql-picker-options { background: #1e293b; border-color: var(--border); color: var(--text); }
  .ql-snow .ql-picker-item:hover, .ql-snow .ql-picker-item.ql-selected { color: var(--text); }
  .ql-snow button:hover .ql-stroke, .ql-snow button.ql-active .ql-stroke { stroke: #f1f5f9 !important; }
  .ql-snow button:hover .ql-fill, .ql-snow button.ql-active .ql-fill { fill: #f1f5f9 !important; }
  .ql-snow button:hover, .ql-snow button.ql-active { color: #f1f5f9; }
  .ql-snow .ql-picker-label:hover .ql-stroke { stroke: #f1f5f9 !important; }

  /* 에디터 내 블록 스타일 */
  .ql-editor h1 { font-size: 20px; font-weight: 700; margin: 6px 0 4px; color: var(--text); }
  .ql-editor h2 { font-size: 16px; font-weight: 600; margin: 5px 0 3px; color: var(--text); }
  .ql-editor h3 { font-size: 14px; font-weight: 600; margin: 4px 0 2px; color: var(--muted); }
  .ql-editor ul li, .ql-editor ol li { color: var(--text); }
  .ql-editor strong { color: #fff; }
  .ql-snow.ql-toolbar button, .ql-snow .ql-toolbar button { padding: 3px 5px; }

  /* 체크리스트 */
  .ql-editor li[data-list="unchecked"]::before { color: var(--muted); }
  .ql-editor li[data-list="checked"]::before { color: #22c55e; }
  .ql-editor li[data-list="checked"] { color: var(--dim); text-decoration: line-through; }
  .placement-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }
  .placement-table-wrap { background: var(--card); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }
  .placement-table { width: 100%; border-collapse: collapse; font-size: 13px; }
  .placement-table th { padding: 10px 14px; text-align: left; font-size: 11px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; border-bottom: 1px solid var(--border); background: rgba(15,23,42,.4); }
  .placement-table td { padding: 12px 14px; border-bottom: 1px solid rgba(51,65,85,.5); vertical-align: middle; }
  .placement-table tr:last-child td { border-bottom: none; }
  .placement-table tr:hover td { background: rgba(255,255,255,.02); }
  .placement-label { font-weight: 600; color: var(--text); }
  .placement-badge { display: inline-block; padding: 1px 7px; border-radius: 20px; font-size: 10px; font-weight: 600; margin-left: 6px; }
  .badge-top          { background: rgba(99,102,241,.2);  color: #a5b4fc; }
  .badge-center       { background: rgba(16,185,129,.2);  color: #6ee7b7; }
  .badge-bottom       { background: rgba(245,158,11,.2);  color: #fcd34d; }
  .badge-popular_slot { background: rgba(20,184,166,.2);  color: #5eead4; }
  .badge-popup        { background: rgba(239,68,68,.2);   color: #fca5a5; }
  .clicks-bar-cell { min-width: 140px; }
  .clicks-bar-wrap { display: flex; align-items: center; gap: 8px; }
  .clicks-bar-bg { flex: 1; height: 6px; background: var(--border); border-radius: 99px; overflow: hidden; }
  .clicks-bar-fill { height: 100%; border-radius: 99px; background: var(--amber); transition: width .4s; }
  .clicks-val { font-weight: 600; min-width: 45px; text-align: right; font-size: 13px; }
  .conv-rate { font-weight: 600; }
  .conv-none { color: var(--dim); font-size: 12px; }
  .btn-edit-conv { background: transparent; border: 1px solid var(--border); color: var(--muted); border-radius: 6px; padding: 3px 8px; font-size: 11px; cursor: pointer; transition: all .15s; }
  .btn-edit-conv:hover { border-color: var(--amber); color: var(--amber); }
  .placement-chart-wrap { padding: 12px 14px 4px; border-top: 1px solid var(--border); }
  .placement-chart-label { font-size: 11px; color: var(--muted); margin-bottom: 8px; }
  .placement-inline-cell { cursor: text; min-width: 90px; }
  .placement-inline-cell:hover { background: rgba(99,102,241,.08); }
  .placement-inline-cell .placeholder { color: var(--dim); font-size: 12px; }
  .placement-inline-input { width: 100%; min-width: 80px; padding: 6px 8px; background: var(--bg); border: 1px solid var(--indigo); border-radius: 6px; color: var(--text); font-size: 13px; }
  .placement-inline-input.note { min-width: 140px; }

  /* 커스텀 이벤트 카테고리 탭 버튼 */
  .evt-cat-btn { background: transparent; border: 1px solid var(--border); color: var(--muted); border-radius: 20px; padding: 3px 10px; font-size: 11px; cursor: pointer; transition: all .15s; white-space: nowrap; }
  .evt-cat-btn:hover { border-color: var(--dim); color: var(--text); }
  .evt-cat-btn.active { background: rgba(99,102,241,.15); border-color: rgba(99,102,241,.5); color: #a5b4fc; }

  @media (max-width: 640px) {
    .summary-grid { grid-template-columns: 1fr; }
    .kpi-grid { grid-template-columns: 1fr 1fr; }
    .kpi-card-wrap.expanded { flex-direction: column; }
    .kpi-card-wrap.expanded > .kpi-card { flex: none; width: 100%; border-radius: 12px 12px 0 0; border-right: 1px solid var(--indigo); }
    .kpi-card-wrap.expanded > .daily-panel { border-radius: 0 0 12px 12px; border-left: 1px solid var(--indigo); }
    header { gap: 8px; }
    .placement-table th:nth-child(3), .placement-table td:nth-child(3) { display: none; }
  }

  /* 월간 플래너 */
  .planner-section { margin-bottom: 32px; }
  .planner-section-title { font-size: 13px; font-weight: 700; color: var(--text); margin-bottom: 14px; display: flex; align-items: center; gap: 8px; }
  .planner-auto-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 28px; }
  .planner-auto-card { background: rgba(99,102,241,.08); border: 1px solid rgba(99,102,241,.25); border-radius: 12px; padding: 14px 16px; }
  .planner-auto-card .pac-label { font-size: 11px; color: var(--muted); margin-bottom: 4px; }
  .planner-auto-card .pac-value { font-size: 24px; font-weight: 700; color: #a5b4fc; }
  .planner-auto-card .pac-mom { font-size: 11px; margin-top: 2px; }
  .planner-author-row { display: flex; align-items: center; gap: 10px; margin-bottom: 20px; }
  .planner-author-row label { font-size: 13px; color: var(--muted); min-width: 60px; }
  .planner-input { flex: 1; background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 7px 12px; font-size: 13px; color: var(--text); outline: none; transition: border-color .15s; font-family: inherit; }
  .planner-input:focus { border-color: var(--indigo); }
  .planner-textarea { width: 100%; background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; font-size: 13px; color: var(--text); outline: none; resize: vertical; min-height: 100px; transition: border-color .15s; font-family: inherit; line-height: 1.7; }
  .planner-textarea:focus { border-color: var(--indigo); }
  .planner-kpt-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
  .planner-kpt-card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 14px; }
  .planner-kpt-title { font-size: 13px; font-weight: 700; margin-bottom: 10px; }
  .planner-kpt-card .ql-editor { min-height: 140px; }
  .planner-goals-table { width: 100%; border-collapse: collapse; font-size: 13px; }
  .planner-goals-table th { padding: 8px 12px; text-align: left; font-size: 11px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; border-bottom: 1px solid var(--border); background: rgba(15,23,42,.4); }
  .planner-goals-table td { padding: 6px 8px; border-bottom: 1px solid rgba(51,65,85,.4); vertical-align: middle; }
  .planner-goals-table tr:last-child td { border-bottom: none; }
  .planner-goals-table input { width: 100%; background: transparent; border: none; border-radius: 6px; padding: 4px 6px; font-size: 13px; color: var(--text); outline: none; font-family: inherit; transition: background .15s; }
  .planner-goals-table input:focus { background: rgba(99,102,241,.1); }
  .planner-goals-table select { background: var(--card); border: 1px solid var(--border); border-radius: 6px; padding: 3px 6px; font-size: 13px; color: var(--text); outline: none; cursor: pointer; }
  .btn-add-row { background: transparent; border: 1px dashed var(--border); color: var(--muted); border-radius: 8px; padding: 6px 14px; font-size: 12px; cursor: pointer; transition: all .15s; width: 100%; margin-top: 8px; }
  .btn-add-row:hover { border-color: var(--indigo); color: #a5b4fc; }
  .btn-del-row { background: none; border: none; color: var(--dim); cursor: pointer; font-size: 16px; padding: 0 4px; line-height: 1; }
  .btn-del-row:hover { color: var(--red); }
  .planner-actions-table { width: 100%; border-collapse: collapse; font-size: 13px; }
  .planner-actions-table th { padding: 8px 12px; text-align: left; font-size: 11px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; border-bottom: 1px solid var(--border); background: rgba(15,23,42,.4); }
  .planner-actions-table td { padding: 6px 8px; border-bottom: 1px solid rgba(51,65,85,.4); vertical-align: middle; }
  .planner-actions-table tr:last-child td { border-bottom: none; }
  .planner-actions-table input { width: 100%; background: transparent; border: none; border-radius: 6px; padding: 4px 6px; font-size: 13px; color: var(--text); outline: none; font-family: inherit; transition: background .15s; }
  .planner-actions-table input:focus { background: rgba(99,102,241,.1); }
  .action-card-list { display: flex; flex-direction: column; gap: 12px; }
  .action-card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }
  .action-card-header { display: flex; align-items: center; gap: 8px; padding: 10px 12px; border-bottom: 1px solid rgba(51,65,85,.4); background: rgba(15,23,42,.35); }
  .action-card-num { font-size: 12px; font-weight: 700; color: var(--muted); min-width: 22px; }
  .action-move-btns { display: flex; flex-direction: column; gap: 2px; }
  .action-move-btn { background: none; border: 1px solid var(--border); border-radius: 4px; color: var(--muted); cursor: pointer; font-size: 10px; line-height: 1; padding: 2px 5px; }
  .action-move-btn:hover:not(:disabled) { border-color: var(--indigo); color: #a5b4fc; }
  .action-move-btn:disabled { opacity: .3; cursor: default; }
  .action-fields { display: grid; grid-template-columns: 90px 1fr 100px 72px; gap: 8px; flex: 1; min-width: 0; }
  .action-fields input { background: transparent; border: none; border-radius: 6px; padding: 4px 6px; font-size: 13px; color: var(--text); outline: none; font-family: inherit; width: 100%; }
  .action-fields input:focus { background: rgba(99,102,241,.1); }
  .action-card-tasks { padding: 10px 12px 12px; }
  .action-card-tasks-label { font-size: 11px; font-weight: 600; color: var(--muted); margin-bottom: 8px; text-transform: uppercase; letter-spacing: .04em; }
  .action-task-editor { min-height: 100px; }
  @media (max-width: 720px) { .action-fields { grid-template-columns: 1fr 1fr; } }
  .planner-save-toast { position: fixed; bottom: 24px; right: 24px; background: #065f46; border: 1px solid #10b981; color: #6ee7b7; border-radius: 10px; padding: 10px 18px; font-size: 13px; font-weight: 600; z-index: 100; transition: opacity .3s; }
  .planner-event-mini { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 8px; margin-top: 10px; }
  .planner-event-chip { position: relative; background: var(--card); border: 1px solid var(--border); border-radius: 8px; padding: 8px 12px; transition: border-color .2s, background .2s; }
  .planner-event-chip .pec-name { font-size: 11px; color: var(--muted); margin-bottom: 2px; }
  .planner-event-chip .pec-val { font-size: 16px; font-weight: 700; }
  .planner-event-chip .pec-mom { font-size: 11px; }
  .planner-chart-section { margin-bottom: 32px; }
  .planner-charts-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
  .planner-chart-card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px; }
  .planner-chart-title { font-size: 12px; font-weight: 600; color: var(--muted); text-transform: uppercase; letter-spacing: .04em; margin-bottom: 12px; }
  @media (max-width: 900px) { .planner-kpt-grid { grid-template-columns: 1fr; } .planner-auto-grid { grid-template-columns: 1fr 1fr; } .planner-charts-grid { grid-template-columns: 1fr; } }
  @media (max-width: 640px) { .planner-auto-grid { grid-template-columns: 1fr; } }
</style>
</head>
<body x-data="kpiApp()" x-init="init()">

<!-- 헤더 -->
<header>
  <div class="logo">
    <div class="logo-icon">🏃</div>
    <div>
      <h1>Running Life</h1>
      <p>위클리 KPI 보드</p>
    </div>
  </div>

  <div class="week-nav">
    <button @click="navPrev()" title="이전">←</button>
    <div class="week-badge">
      <template x-if="viewMode==='weekly'">
        <div>
          <div class="label" x-text="data?.week_label || week"></div>
          <div class="key" x-text="week"></div>
        </div>
      </template>
      <template x-if="viewMode==='weekly-planner'">
        <div>
          <div class="label" x-text="(weeklyPlannerData?.week_label || data?.week_label || week) + ' 플래너'"></div>
          <div class="key" x-text="week"></div>
        </div>
      </template>
      <template x-if="viewMode==='planner'">
        <div>
          <div class="label" x-text="(plannerData?.month_label || month) + ' 플래너'"></div>
          <div class="key" x-text="month"></div>
        </div>
      </template>
    </div>
    <button @click="navNext()" :disabled="isCurrentPeriod()" title="다음">→</button>
    <button class="btn-today" x-show="!isCurrentPeriod()" @click="goNow()">
      <span x-text="viewMode==='planner' ? '이번 달' : '이번 주'"></span>
    </button>
  </div>

  <div class="actions">
    <!-- 주간 KPI / 주간 플래너 / 월간 플래너 -->
    <div style="display:flex;border:1px solid var(--border);border-radius:8px;overflow:hidden">
      <button class="btn" :class="viewMode==='weekly' ? 'btn-primary' : 'btn-outline'" style="border-radius:0;border:none;padding:5px 12px;font-size:12px" @click="setViewMode('weekly')">주간 KPI</button>
      <button class="btn" :class="viewMode==='weekly-planner' ? 'btn-primary' : 'btn-outline'" style="border-radius:0;border:none;border-left:1px solid var(--border);padding:5px 12px;font-size:12px" @click="setViewMode('weekly-planner')">📋 주간 플래너</button>
      <button class="btn" :class="viewMode==='planner' ? 'btn-primary' : 'btn-outline'" style="border-radius:0;border:none;border-left:1px solid var(--border);padding:5px 12px;font-size:12px" @click="setViewMode('planner')">📋 월간 플래너</button>
    </div>
    <button class="btn btn-outline" @click="showManual = true" x-show="viewMode==='weekly'">✏️ 데이터 입력</button>
    <button class="btn btn-primary" @click="showTarget = true" x-show="viewMode==='weekly'">🎯 목표 설정</button>
    <button class="btn btn-outline" @click="saveWeeklyPlanner()" :disabled="weeklyPlannerSaving" x-show="viewMode==='weekly-planner'" style="color:#6ee7b7;border-color:#065f46">
      <span x-text="weeklyPlannerSaving ? '저장 중...' : '💾 저장'"></span>
    </button>
    <button class="btn btn-primary" @click="generateWeeklyMd()" x-show="viewMode==='weekly-planner'" style="background:#7c3aed">
      📄 MD 생성
    </button>
    <button class="btn btn-outline" @click="savePlanner()" :disabled="plannerSaving" x-show="viewMode==='planner'" style="color:#6ee7b7;border-color:#065f46">
      <span x-text="plannerSaving ? '저장 중...' : '💾 저장'"></span>
    </button>
    <button class="btn btn-primary" @click="generateMd()" x-show="viewMode==='planner'" style="background:#7c3aed">
      📄 MD 생성
    </button>
    <button class="btn btn-outline btn-icon" @click="refreshAll()" :disabled="loading" title="새로고침">
      <span :class="loading ? 'spin-inline' : ''">↻</span>
    </button>
  </div>
</header>

<main>
  <!-- 주간 뷰 -->
  <div x-show="viewMode==='weekly'">

  <!-- 주차 타이틀 -->
  <div style="margin-bottom:20px" x-show="data">
    <h2 style="font-size:18px;font-weight:700" x-text="data?.week_label"></h2>
    <p style="font-size:12px;color:var(--muted);margin-top:2px">
      총 <span x-text="data?.entries?.length ?? 0"></span>개 KPI ·
      <span x-text="data?.entries?.filter(e => e.achievement_rate >= 100).length ?? 0"></span>개 목표 달성
    </p>
  </div>

  <!-- 카테고리 요약 -->
  <div class="summary-grid" x-show="data">
    <template x-for="cat in ['user','revenue','ads']" :key="cat">
      <div class="summary-card">
        <div class="cat-label" x-text="catLabel(cat)"></div>
        <template x-if="catSummary(cat)">
          <div>
            <span class="rate" :style="'color:'+rateColor(catSummary(cat).avg)" x-text="catSummary(cat).avg.toFixed(0)+'%'"></span>
            <span class="sub" x-text="' ' + catSummary(cat).achieved + '/' + catSummary(cat).total + ' 달성'"></span>
          </div>
        </template>
        <template x-if="!catSummary(cat)">
          <p class="sub">목표 미설정</p>
        </template>
      </div>
    </template>
  </div>

  <!-- 에러 -->
  <div class="error-banner" x-show="error" x-text="'⚠️ ' + error"></div>

  <!-- 로딩 -->
  <div class="spinner" x-show="loading"></div>

  <!-- 광고 위치별 성과 -->
  <div class="placement-section" x-show="!loading && placementData">
    <div class="placement-header">
      <div class="section-title" style="margin-bottom:0">📍 광고 위치별 성과 <span style="font-size:10px;font-weight:400;color:var(--dim);margin-left:4px">(클릭·노출 GA4 자동 · 매출·비고 셀 클릭 편집)</span></div>
      <button class="btn btn-outline" style="font-size:11px;padding:4px 10px" @click="showConvModal = true">전환율 입력</button>
    </div>
    <div class="placement-table-wrap">
      <table class="placement-table">
        <thead>
          <tr>
            <th>위치</th>
            <th>클릭수</th>
            <th>전주 대비</th>
            <th>노출수</th>
            <th>CTR <span style="font-weight:400;opacity:.6">(GA4)</span></th>
            <th>전환율 <span style="font-weight:400;opacity:.6">(카페24)</span></th>
            <th>매출(원)</th>
            <th>비고</th>
          </tr>
        </thead>
        <template x-for="p in placementData?.placements ?? []" :key="p.id">
        <tbody>
            <tr class="placement-row-clickable" :class="expandedPlacementId === p.id ? 'expanded' : ''" @click="togglePlacementDaily(p)">
              <td>
                <span class="placement-label" x-text="p.label"></span>
                <span class="placement-badge" :class="'badge-'+p.id" x-text="p.id"></span>
                <span style="font-size:10px;color:var(--dim);margin-left:6px" x-text="expandedPlacementId === p.id ? '▲' : '▼ 일별'"></span>
              </td>
              <td class="clicks-bar-cell">
                <div class="clicks-bar-wrap">
                  <div class="clicks-bar-bg">
                    <div class="clicks-bar-fill" :style="'width:'+placementBarWidth(p.clicks)+'%'"></div>
                  </div>
                  <span class="clicks-val" x-text="p.clicks.toLocaleString()"></span>
                </div>
              </td>
              <td>
                <template x-if="p.wow_change !== null && p.wow_change !== undefined">
                  <span :class="p.wow_change > 0 ? 'wow wow-up' : p.wow_change < 0 ? 'wow wow-down' : 'wow wow-flat'">
                    <span x-text="p.wow_change > 0 ? '▲' : p.wow_change < 0 ? '▼' : '─'"></span>
                    <span x-text="Math.abs(p.wow_change).toFixed(1)+'%'"></span>
                  </span>
                </template>
                <template x-if="p.wow_change === null || p.wow_change === undefined">
                  <span style="color:var(--dim);font-size:12px">—</span>
                </template>
              </td>
              <td>
                <template x-if="p.impressions !== null && p.impressions !== undefined">
                  <span x-text="p.impressions.toLocaleString()"></span>
                </template>
                <template x-if="p.impressions === null || p.impressions === undefined">
                  <span class="conv-none">—</span>
                </template>
              </td>
              <td>
                <template x-if="p.ctr !== null && p.ctr !== undefined">
                  <span class="conv-rate" x-text="p.ctr.toFixed(2)+'%'"></span>
                </template>
                <template x-if="p.ctr === null || p.ctr === undefined">
                  <span class="conv-none" title="노출 이벤트 미집계">—</span>
                </template>
              </td>
              <td>
                <template x-if="p.conversion_rate !== null && p.conversion_rate !== undefined">
                  <span class="conv-rate" :style="'color:'+rateColor(p.conversion_rate * 10)" x-text="p.conversion_rate.toFixed(2)+'%'"></span>
                </template>
                <template x-if="p.conversion_rate === null || p.conversion_rate === undefined">
                  <span class="conv-none">미입력</span>
                </template>
              </td>
              <td class="placement-inline-cell" @click.stop="startPlacementEdit(p, 'revenue')">
                <template x-if="!isPlacementEditing(p, 'revenue')">
                  <span x-show="p.revenue != null && p.revenue !== ''" x-text="Number(p.revenue).toLocaleString()"></span>
                  <span class="placeholder" x-show="p.revenue == null || p.revenue === ''">클릭하여 입력</span>
                </template>
                <input type="number" min="0" step="1000" class="placement-inline-input"
                  x-show="isPlacementEditing(p, 'revenue')"
                  x-model.number="placementEdits[p.id].revenue"
                  @click.stop @keydown.enter.prevent="commitPlacementMeta(p, 'revenue')"
                  @blur="commitPlacementMeta(p, 'revenue')"
                  :id="'placement-edit-'+p.id+'-revenue'">
              </td>
              <td class="placement-inline-cell" @click.stop="startPlacementEdit(p, 'note')">
                <template x-if="!isPlacementEditing(p, 'note')">
                  <span x-show="p.note" x-text="p.note"></span>
                  <span class="placeholder" x-show="!p.note">클릭하여 입력</span>
                </template>
                <input type="text" class="placement-inline-input note"
                  x-show="isPlacementEditing(p, 'note')"
                  x-model="placementEdits[p.id].note"
                  @click.stop @keydown.enter.prevent="commitPlacementMeta(p, 'note')"
                  @blur="commitPlacementMeta(p, 'note')"
                  :id="'placement-edit-'+p.id+'-note'">
              </td>
            </tr>
            <tr class="placement-daily-row" x-show="expandedPlacementId === p.id" x-cloak>
              <td colspan="8">
                <div class="placement-daily-inner">
                  <div class="spinner" x-show="dailyLoadingKey === 'placement-'+p.id" style="margin:12px auto"></div>
                  <template x-if="dailyCache['placement-'+p.id]?.error && dailyLoadingKey !== 'placement-'+p.id">
                    <div class="daily-empty">일별 데이터를 불러오지 못했습니다.</div>
                  </template>
                  <template x-if="expandedPlacementId === p.id && dailyCache['placement-'+p.id] && !dailyCache['placement-'+p.id]?.error && dailyLoadingKey !== 'placement-'+p.id">
                    <div>
                      <div class="daily-panel-title" x-text="(dailyCache['placement-'+p.id]?.week_label || '') + ' · 일별 (월~일)'"></div>
                      <div class="daily-chart-wrap" x-init="paintPlacementDailyChart(p)">
                        <canvas :id="'dailyChart-placement-'+p.id"></canvas>
                      </div>
                      <table class="daily-table daily-table-h">
                        <thead>
                          <tr>
                            <template x-for="d in (dailyCache['placement-'+p.id]?.days ?? [])" :key="d.date">
                              <th><span x-text="d.weekday"></span><span class="day-label" x-text="d.date_label"></span></th>
                            </template>
                            <th>합계</th>
                          </tr>
                        </thead>
                        <tbody>
                          <tr>
                            <template x-for="d in (dailyCache['placement-'+p.id]?.days ?? [])" :key="'c-'+d.date">
                              <td x-text="d.clicks.toLocaleString()"></td>
                            </template>
                            <td x-text="(dailyCache['placement-'+p.id]?.clicks_total ?? 0).toLocaleString()"></td>
                          </tr>
                          <template x-if="dailyCache['placement-'+p.id]?.has_impressions">
                            <tr>
                              <template x-for="d in (dailyCache['placement-'+p.id]?.days ?? [])" :key="'i-'+d.date">
                                <td x-text="d.impressions != null ? d.impressions.toLocaleString() : '—'"></td>
                              </template>
                              <td x-text="(dailyCache['placement-'+p.id]?.impressions_total ?? 0).toLocaleString()"></td>
                            </tr>
                          </template>
                        </tbody>
                      </table>
                    </div>
                  </template>
                </div>
              </td>
            </tr>
        </tbody>
        </template>
      </table>
      <!-- 클릭수 미니 바 차트 -->
      <div class="placement-chart-wrap" x-show="placementData?.placements?.some(p => p.clicks > 0)">
        <div class="placement-chart-label">위치별 클릭 비중</div>
        <div style="position:relative;height:120px">
          <canvas id="placementChart"></canvas>
        </div>
      </div>
    </div>
  </div>

  <!-- KPI 카드 그리드 -->
  <div x-show="!loading && data">
    <template x-for="cat in ['user','revenue','ads']" :key="cat">
      <div class="kpi-section">
        <div class="section-title" x-text="catLabel(cat)"></div>
        <div class="kpi-grid">
          <template x-for="entry in entriesByCategory(cat)" :key="entry.id">
            <div class="kpi-card-wrap" :class="expandedKpiId === entry.id ? 'expanded' : ''">
              <button type="button" class="kpi-card" :class="expandedKpiId === entry.id ? 'expanded' : ''" @click="toggleKpiDaily(entry)">
                <div class="kpi-card-header">
                  <div>
                    <div class="kpi-name" x-text="entry.name"></div>
                  </div>
                  <span class="ga4-badge" x-show="entry.source === 'ga4'">GA4</span>
                </div>

                <div>
                  <span class="kpi-value" x-text="formatVal(entry.value, entry.unit)"></span>
                  <span class="kpi-unit" x-text="entry.unit"></span>
                </div>

                <template x-if="entry.target > 0">
                  <div class="kpi-target">목표 <span x-text="formatVal(entry.target, entry.unit) + entry.unit"></span></div>
                </template>

                <template x-if="entry.target > 0">
                  <div>
                    <div class="progress-row">
                      <span class="progress-label">달성률</span>
                      <span class="progress-rate" :class="rateClass(entry.achievement_rate)">
                        <span x-text="entry.achievement_rate.toFixed(1) + '%'"></span>
                        <span x-show="entry.achievement_rate >= 100"> 🎯</span>
                      </span>
                    </div>
                    <div class="progress-bar-bg">
                      <div class="progress-bar-fill" :class="fillClass(entry.achievement_rate)"
                           :style="'width:' + Math.min(entry.achievement_rate, 100) + '%'"></div>
                    </div>
                  </div>
                </template>

                <template x-if="entry.wow_change !== null && entry.wow_change !== undefined">
                  <div class="wow" :class="entry.wow_change > 0 ? 'wow-up' : entry.wow_change < 0 ? 'wow-down' : 'wow-flat'">
                    <span x-text="entry.wow_change > 0 ? '▲' : entry.wow_change < 0 ? '▼' : '─'"></span>
                    <span x-text="Math.abs(entry.wow_change).toFixed(1) + '% 전주 대비'"></span>
                  </div>
                </template>

                <div class="no-data" x-text="expandedKpiId === entry.id ? '▲ 접기' : '▼ 클릭 → 이번 주 일별'"></div>
              </button>
              <div class="daily-panel" x-show="expandedKpiId === entry.id" x-cloak>
                <div class="spinner" x-show="dailyLoadingKey === 'kpi-'+entry.id" style="margin:12px auto"></div>
                <template x-if="dailyCache['kpi-'+entry.id]?.manual_only">
                  <div class="daily-empty">주 단위 수동 입력 지표 — 일별 데이터 없음</div>
                </template>
                <template x-if="dailyCache['kpi-'+entry.id]?.error && dailyLoadingKey !== ('kpi-'+entry.id)">
                  <div class="daily-empty">일별 데이터를 불러오지 못했습니다.</div>
                </template>
                <template x-if="expandedKpiId === entry.id && dailyCache['kpi-'+entry.id] && !dailyCache['kpi-'+entry.id]?.manual_only && !dailyCache['kpi-'+entry.id]?.error && dailyLoadingKey !== ('kpi-'+entry.id)">
                  <div>
                    <div class="daily-panel-title" x-text="(dailyCache['kpi-'+entry.id]?.daily_label || entry.name) + ' · ' + (dailyCache['kpi-'+entry.id]?.week_label || '')"></div>
                    <div class="daily-chart-wrap" x-init="paintKpiDailyChart(entry)">
                      <canvas :id="'dailyChart-kpi-'+entry.id"></canvas>
                    </div>
                    <table class="daily-table daily-table-h">
                      <thead>
                        <tr>
                          <template x-for="d in (dailyCache['kpi-'+entry.id]?.days ?? [])" :key="d.date">
                            <th><span x-text="d.weekday"></span><span class="day-label" x-text="d.date_label"></span></th>
                          </template>
                          <th>합계</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr>
                          <template x-for="d in (dailyCache['kpi-'+entry.id]?.days ?? [])" :key="d.date">
                            <td x-text="formatVal(d.value, entry.unit) + entry.unit"></td>
                          </template>
                          <td x-text="formatVal(dailyCache['kpi-'+entry.id]?.week_total ?? 0, entry.unit) + entry.unit"></td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </template>
              </div>
            </div>
          </template>
        </div>
      </div>
    </template>
  </div>

  <!-- 커스텀 이벤트 카운트 섹션 -->
  <div x-show="!loading && eventData" style="margin-bottom:28px">
    <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;margin-bottom:12px">
      <div class="section-title" style="margin-bottom:0">🎯 커스텀 이벤트 카운트 <span style="font-size:10px;font-weight:400;color:var(--dim);margin-left:4px">(GA4 자동 · 카드 클릭 → 이번 주 일별)</span></div>
      <div style="display:flex;gap:6px;flex-wrap:wrap">
        <template x-for="cat in eventCategories" :key="cat.id">
          <button class="evt-cat-btn" :class="selectedEventCat === cat.id ? 'active' : ''" @click="selectedEventCat = cat.id" x-text="cat.label + ' (' + eventsByCat(cat.id).length + ')'"></button>
        </template>
      </div>
    </div>
    <div class="kpi-grid">
      <template x-for="evt in eventsByCat(selectedEventCat)" :key="evt.event_name">
        <div class="kpi-card-wrap" :class="expandedEventName === evt.event_name ? 'expanded' : ''">
          <button type="button" class="kpi-card" :class="expandedEventName === evt.event_name ? 'expanded' : ''" @click="toggleEventDaily(evt)">
            <div class="kpi-card-header">
              <div class="kpi-name" x-text="evt.label"></div>
              <span class="ga4-badge">GA4</span>
            </div>
            <div>
              <span class="kpi-value" x-text="evt.count >= 1000000 ? (evt.count/1000000).toFixed(1)+'M' : evt.count >= 1000 ? (evt.count/1000).toFixed(1)+'K' : evt.count.toLocaleString()"></span>
              <span class="kpi-unit">회</span>
            </div>
            <template x-if="evt.wow_change !== null && evt.wow_change !== undefined">
              <div class="wow" :class="evt.wow_change > 0 ? 'wow-up' : evt.wow_change < 0 ? 'wow-down' : 'wow-flat'">
                <span x-text="evt.wow_change > 0 ? '▲' : evt.wow_change < 0 ? '▼' : '─'"></span>
                <span x-text="Math.abs(evt.wow_change).toFixed(1) + '% 전주 대비'"></span>
              </div>
            </template>
            <div class="no-data" x-text="expandedEventName === evt.event_name ? '▲ 접기' : '▼ 클릭 → 이번 주 일별'"></div>
          </button>
          <div class="daily-panel" x-show="expandedEventName === evt.event_name" x-cloak>
            <div class="spinner" x-show="dailyLoadingKey === 'event-'+evt.event_name" style="margin:12px auto"></div>
            <template x-if="dailyCache['event-'+evt.event_name]?.error && dailyLoadingKey !== 'event-'+evt.event_name">
              <div class="daily-empty">일별 데이터를 불러오지 못했습니다.</div>
            </template>
            <template x-if="expandedEventName === evt.event_name && dailyCache['event-'+evt.event_name] && !dailyCache['event-'+evt.event_name]?.error && dailyLoadingKey !== 'event-'+evt.event_name">
              <div>
                <div class="daily-panel-title" x-text="evt.label + ' · ' + (dailyCache['event-'+evt.event_name]?.week_label || '')"></div>
                <div class="daily-chart-wrap" x-init="paintEventDailyChart(evt)">
                  <canvas :id="'dailyChart-event-'+evt.event_name"></canvas>
                </div>
                <table class="daily-table daily-table-h">
                  <thead>
                    <tr>
                      <template x-for="d in (dailyCache['event-'+evt.event_name]?.days ?? [])" :key="d.date">
                        <th><span x-text="d.weekday"></span><span class="day-label" x-text="d.date_label"></span></th>
                      </template>
                      <th>합계</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <template x-for="d in (dailyCache['event-'+evt.event_name]?.days ?? [])" :key="d.date">
                        <td x-text="d.value.toLocaleString() + '회'"></td>
                      </template>
                      <td x-text="(dailyCache['event-'+evt.event_name]?.week_total ?? 0).toLocaleString() + '회'"></td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </template>
          </div>
        </div>
      </template>
    </div>
  </div>

  </div><!-- /주간 KPI 뷰 -->

  <!-- 주간 플래너 뷰 -->
  <div x-show="viewMode==='weekly-planner'">
    <div style="margin-bottom:20px" x-show="weeklyPlannerData">
      <h2 style="font-size:18px;font-weight:700" x-text="(weeklyPlannerData?.week_label || week) + ' Weekly Plan'"></h2>
      <p style="font-size:12px;color:var(--muted);margin-top:2px">
        지표는 <span style="color:#fcd34d" x-text="weeklyPlannerData?.data_week_label"></span> 실적 · 할일·노트·목표는 <span style="color:#6ee7b7" x-text="weeklyPlannerData?.week_label"></span> 계획
      </p>
    </div>
    <div class="spinner" x-show="weeklyPlannerLoading"></div>
    <div class="daily-empty" x-show="!weeklyPlannerLoading && !weeklyPlannerData" style="padding:24px 0">주간 플래너 데이터를 불러오지 못했습니다. 새로고침 후 다시 시도해 주세요.</div>

    <template x-if="!weeklyPlannerLoading && weeklyPlannerData">
    <div>

      <!-- 작성자 & North Star -->
      <div class="planner-section">
        <div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:16px">
          <div style="display:flex;align-items:center;gap:8px;flex:1;min-width:200px">
            <label style="font-size:13px;color:var(--muted);white-space:nowrap">작성자</label>
            <input class="planner-input" type="text" placeholder="이름" x-model="weeklyPlannerForm.author">
          </div>
          <div style="display:flex;align-items:center;gap:8px;flex:2;min-width:280px">
            <label style="font-size:13px;color:var(--muted);white-space:nowrap">🎯 North Star</label>
            <input class="planner-input" type="text" placeholder="예: 참가 완료율 5%p 개선" x-model="weeklyPlannerForm.north_star">
          </div>
        </div>
      </div>

      <!-- 자동 KPI -->
      <div class="planner-section">
        <div class="planner-section-title">
          📊 자동 불러온 KPI
          <span style="font-size:10px;font-weight:400;color:var(--dim)">(GA4 자동)</span>
          <span style="font-size:11px;font-weight:500;background:rgba(245,158,11,.15);color:#fcd34d;border:1px solid rgba(245,158,11,.3);border-radius:20px;padding:2px 8px;margin-left:4px" x-text="(weeklyPlannerData?.data_week_label || '') + ' 실적 기준'"></span>
        </div>
        <div class="planner-auto-grid">
          <div class="planner-auto-card">
            <div class="pac-label">MAU (주간 활성)</div>
            <div class="pac-value" x-text="fmtNum(weeklyPlannerData.auto_kpi.mau)"></div>
            <div class="pac-mom" :class="weeklyPlannerData.auto_kpi.mau_wow > 0 ? 'wow-up' : weeklyPlannerData.auto_kpi.mau_wow < 0 ? 'wow-down' : 'wow-flat'">
              <span x-text="fmtWow(weeklyPlannerData.auto_kpi.mau_wow)"></span>
              <span style="color:var(--muted)"> · 전전주 <span x-text="fmtNum(weeklyPlannerData.auto_kpi.mau_prev)"></span></span>
            </div>
          </div>
          <div class="planner-auto-card">
            <div class="pac-label">신규 가입자</div>
            <div class="pac-value" x-text="fmtNum(weeklyPlannerData.auto_kpi.new_users)"></div>
            <div class="pac-mom" :class="weeklyPlannerData.auto_kpi.new_users_wow > 0 ? 'wow-up' : weeklyPlannerData.auto_kpi.new_users_wow < 0 ? 'wow-down' : 'wow-flat'">
              <span x-text="fmtWow(weeklyPlannerData.auto_kpi.new_users_wow)"></span>
              <span style="color:var(--muted)"> · 전전주 <span x-text="fmtNum(weeklyPlannerData.auto_kpi.new_users_prev)"></span></span>
            </div>
          </div>
          <div class="planner-auto-card">
            <div class="pac-label">세션 수</div>
            <div class="pac-value" x-text="fmtNum(weeklyPlannerData.auto_kpi.sessions)"></div>
            <div class="pac-mom" :class="weeklyPlannerData.auto_kpi.sessions_wow > 0 ? 'wow-up' : weeklyPlannerData.auto_kpi.sessions_wow < 0 ? 'wow-down' : 'wow-flat'">
              <span x-text="fmtWow(weeklyPlannerData.auto_kpi.sessions_wow)"></span>
              <span style="color:var(--muted)"> · 전전주 <span x-text="fmtNum(weeklyPlannerData.auto_kpi.sessions_prev)"></span></span>
            </div>
          </div>
        </div>
      </div>

      <!-- 이번 주 목표 & 달성률 -->
      <div class="planner-section">
        <div class="planner-section-title">
          ① <span x-text="weeklyPlannerData?.week_label"></span> 목표 &amp; 달성률
          <span style="font-size:10px;font-weight:400;color:var(--dim)">· 이번 주 계획</span>
        </div>
        <div class="placement-table-wrap">
          <table class="planner-goals-table">
            <thead><tr>
              <th>핵심 목표</th><th>목표치</th><th>실적</th><th>달성률</th><th>상태</th><th></th>
            </tr></thead>
            <tbody>
              <template x-for="(goal, idx) in weeklyPlannerForm.goals" :key="idx">
                <tr>
                  <td><input type="text" placeholder="목표명" x-model="goal.name"></td>
                  <td><input type="text" placeholder="85,000" x-model="goal.target" style="width:90px"></td>
                  <td><input type="text" placeholder="실적" x-model="goal.actual" style="width:80px"></td>
                  <td><input type="text" placeholder="97%" x-model="goal.actual_rate" style="width:60px"></td>
                  <td>
                    <select x-model="goal.status">
                      <option value="🟢">🟢</option>
                      <option value="🟡">🟡</option>
                      <option value="🔴">🔴</option>
                    </select>
                  </td>
                  <td><button class="btn-del-row" @click="weeklyPlannerForm.goals.splice(idx,1)">×</button></td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
        <button class="btn-add-row" @click="weeklyPlannerForm.goals.push({name:'',target:'',actual:'',actual_rate:'',status:'🟡'})">+ 목표 추가</button>
      </div>

      <!-- 기능별 지표 -->
      <div class="planner-section">
        <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;margin-bottom:12px">
          <div class="planner-section-title" style="margin-bottom:0">② 기능별 지표 <span style="font-size:10px;font-weight:400;color:var(--dim)">(GA4 자동)</span> <span style="font-size:11px;font-weight:500;background:rgba(245,158,11,.15);color:#fcd34d;border:1px solid rgba(245,158,11,.3);border-radius:20px;padding:2px 8px" x-text="weeklyPlannerData?.data_week_label + ' 기준'"></span></div>
          <div style="display:flex;gap:6px;flex-wrap:wrap">
            <template x-for="cat in eventCategories" :key="'wpc'+cat.id">
              <button class="evt-cat-btn" :class="weeklyPlannerEventCat === cat.id ? 'active' : ''" @click="weeklyPlannerEventCat = cat.id" x-text="cat.label"></button>
            </template>
          </div>
        </div>
        <div class="planner-event-mini">
          <template x-for="evt in weeklyPlannerEventsByCat(weeklyPlannerEventCat)" :key="evt.event_name">
            <div class="planner-event-chip"
              :style="evt.wow_change >= 10 ? 'border-color:rgba(16,185,129,.45);background:rgba(16,185,129,.08)' :
                      evt.wow_change <= -10 ? 'border-color:rgba(239,68,68,.45);background:rgba(239,68,68,.08)' :
                      'border-color:rgba(245,158,11,.35);background:rgba(245,158,11,.07)'">
              <div style="position:absolute;top:6px;right:7px;font-size:11px;line-height:1"
                x-text="evt.wow_change >= 10 ? '🟢' : evt.wow_change <= -10 ? '🔴' : '🟡'"></div>
              <div class="pec-name" x-text="evt.label"></div>
              <div class="pec-val" x-text="evt.count >= 1000 ? (evt.count/1000).toFixed(1)+'K' : evt.count.toLocaleString()"></div>
              <div class="pec-mom" :class="evt.wow_change > 0 ? 'wow-up' : evt.wow_change < 0 ? 'wow-down' : 'wow-flat'" x-text="fmtWow(evt.wow_change)"></div>
            </div>
          </template>
        </div>
      </div>

      <!-- 광고별 지표 -->
      <div class="planner-section">
        <div class="planner-section-title">③ 광고별 지표 <span style="font-size:10px;font-weight:400;color:var(--dim)">(GA4 자동 + 매출 수동)</span> <span style="font-size:11px;font-weight:500;background:rgba(245,158,11,.15);color:#fcd34d;border:1px solid rgba(245,158,11,.3);border-radius:20px;padding:2px 8px" x-text="weeklyPlannerData?.data_week_label + ' 기준'"></span></div>
        <div class="placement-table-wrap">
          <table class="placement-table">
            <thead><tr>
              <th>위치</th><th>클릭수</th><th>WoW</th><th>노출수</th><th>CTR</th><th>매출(원)</th>
            </tr></thead>
            <tbody>
              <template x-for="p in weeklyPlannerData.ad_placements" :key="p.id">
                <tr>
                  <td>
                    <span class="placement-label" x-text="p.label"></span>
                    <span class="placement-badge" :class="'badge-'+p.id" x-text="p.id"></span>
                  </td>
                  <td><span x-text="p.clicks.toLocaleString()"></span></td>
                  <td>
                    <template x-if="p.wow_change !== null && p.wow_change !== undefined">
                      <span :class="p.wow_change > 0 ? 'wow wow-up' : p.wow_change < 0 ? 'wow wow-down' : 'wow wow-flat'">
                        <span x-text="p.wow_change > 0 ? '▲' : p.wow_change < 0 ? '▼' : '─'"></span>
                        <span x-text="Math.abs(p.wow_change).toFixed(1)+'%'"></span>
                      </span>
                    </template>
                    <template x-if="p.wow_change === null || p.wow_change === undefined"><span style="color:var(--dim)">—</span></template>
                  </td>
                  <td>
                    <template x-if="p.impressions !== null && p.impressions !== undefined"><span x-text="p.impressions.toLocaleString()"></span></template>
                    <template x-if="p.impressions === null || p.impressions === undefined"><span class="conv-none">—</span></template>
                  </td>
                  <td>
                    <template x-if="p.ctr !== null && p.ctr !== undefined"><span class="conv-rate" x-text="p.ctr.toFixed(2)+'%'"></span></template>
                    <template x-if="p.ctr === null || p.ctr === undefined"><span class="conv-none">—</span></template>
                  </td>
                  <td>
                    <input type="number" min="0" step="1000" placeholder="0"
                      x-model.number="weeklyPlannerForm.ad_revenues[p.id]"
                      style="width:110px;padding:6px 8px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:13px">
                  </td>
                </tr>
              </template>
              <tr style="background:rgba(16,185,129,.06)">
                <td colspan="5" style="font-weight:600;color:var(--muted)">매출 합계</td>
                <td style="font-weight:700;color:#6ee7b7" x-text="fmtNum(weeklyAdRevenueTotal()) + '원'"></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 주간 플래닝 노트 -->
      <div class="planner-section">
        <div class="planner-section-title">④ 주간 플래닝 노트</div>
        <div class="notes-grid">
          <div class="note-card">
            <div class="note-card-header">
              <div class="note-card-title">🎯 Weekly KPI Dashboard</div>
              <span class="note-save-badge" :class="noteSaved.kpi_summary ? 'visible' : ''">저장됨 ✓</span>
            </div>
            <div id="note-editor-kpi_summary"></div>
          </div>
          <div class="note-card">
            <div class="note-card-header">
              <div class="note-card-title">🔧 Project Progress</div>
              <span class="note-save-badge" :class="noteSaved.project_progress ? 'visible' : ''">저장됨 ✓</span>
            </div>
            <div id="note-editor-project_progress"></div>
          </div>
          <div class="note-card">
            <div class="note-card-header">
              <div class="note-card-title">📅 Next Week's Strategy</div>
              <span class="note-save-badge" :class="noteSaved.next_week_strategy ? 'visible' : ''">저장됨 ✓</span>
            </div>
            <div id="note-editor-next_week_strategy"></div>
          </div>
        </div>
      </div>

      <!-- 이번 주 할일 -->
      <div class="planner-section">
        <div class="planner-section-title" style="display:flex;align-items:center;justify-content:space-between">
          <span>⑤ <span x-text="weeklyPlannerData?.week_label"></span> 할일 <span style="font-size:10px;font-weight:400;color:var(--dim)">· 이번 주에 할 일</span></span>
          <span class="note-save-badge" :class="weeklyTasksSaved ? 'visible' : ''">저장됨 ✓</span>
        </div>
        <div class="feedback-card">
          <div class="task-progress" x-show="weeklyTasks.length" x-text="taskDoneCount(weeklyTasks) + '/' + weeklyTasks.length + ' 완료'" style="margin-bottom:8px"></div>
          <template x-if="!weeklyTasks.length">
            <div class="task-empty">할일을 추가하세요</div>
          </template>
          <template x-for="task in weeklyTasks" :key="task.id">
            <div class="task-row">
              <input type="checkbox" :checked="task.done" @change="toggleWeeklyTask(task.id)">
              <span class="task-row-text" :class="task.done ? 'done' : ''" x-text="task.text"></span>
              <button class="task-del" @click="removeWeeklyTask(task.id)" title="삭제">×</button>
            </div>
          </template>
          <div class="task-add-row">
            <input class="task-add-input" type="text" placeholder="할일 추가..." x-model="weeklyTaskNew" @keydown.enter.prevent="addWeeklyTask()">
            <button class="task-add-btn" @click="addWeeklyTask()">추가</button>
          </div>
        </div>
      </div>

      <!-- 핵심 액션 -->
      <div class="planner-section">
        <div class="planner-section-title">⑥ <span x-text="weeklyPlannerData?.week_label"></span> 핵심 액션</div>
        <div class="action-card-list">
          <template x-for="(action, idx) in weeklyPlannerForm.actions" :key="action.id">
            <div class="action-card">
              <div class="action-card-header">
                <span class="action-card-num" x-text="idx + 1"></span>
                <div class="action-move-btns">
                  <button type="button" class="action-move-btn" :disabled="idx === 0" @click="moveWeeklyActionUp(idx)" title="위로">▲</button>
                  <button type="button" class="action-move-btn" :disabled="idx === weeklyPlannerForm.actions.length - 1" @click="moveWeeklyActionDown(idx)" title="아래로">▼</button>
                </div>
                <div class="action-fields">
                  <input type="text" placeholder="채널" x-model="action.channel">
                  <input type="text" placeholder="핵심 액션" x-model="action.action">
                  <input type="text" placeholder="목표" x-model="action.goal">
                  <input type="text" placeholder="마감" x-model="action.deadline">
                </div>
                <button type="button" class="btn-del-row" @click="removeWeeklyAction(idx)" title="삭제">×</button>
              </div>
              <div class="action-card-tasks">
                <div class="action-card-tasks-label">구체적 할일</div>
                <div class="action-task-editor" :id="'weekly-action-task-editor-' + action.id"></div>
              </div>
            </div>
          </template>
        </div>
        <button type="button" class="btn-add-row" @click="addWeeklyAction()">+ 액션 추가</button>
      </div>

    </div>
    </template>
  </div><!-- /주간 플래너 뷰 -->

  <!-- 월간 플래너 뷰 -->
  <div x-show="viewMode==='planner'">
    <div style="margin-bottom:20px" x-show="plannerData">
      <h2 style="font-size:18px;font-weight:700" x-text="(plannerData?.month_label || month) + ' Monthly Plan'"></h2>
      <p style="font-size:12px;color:var(--muted);margin-top:2px">GA4 지표 자동 불러오기 · 목표/회고/다음달 플랜 작성 · MD 파일 생성</p>
    </div>
    <div class="spinner" x-show="plannerLoading"></div>
    <div class="daily-empty" x-show="!plannerLoading && !plannerData" style="padding:24px 0">플래너 데이터를 불러오지 못했습니다. 새로고침 후 다시 시도해 주세요.</div>

    <template x-if="!plannerLoading && plannerData">
    <div>

      <!-- 작성자 & North Star -->
      <div class="planner-section">
        <div style="display:flex;gap:16px;flex-wrap:wrap;margin-bottom:16px">
          <div style="display:flex;align-items:center;gap:8px;flex:1;min-width:200px">
            <label style="font-size:13px;color:var(--muted);white-space:nowrap">작성자</label>
            <input class="planner-input" type="text" placeholder="이름" x-model="plannerForm.author">
          </div>
          <div style="display:flex;align-items:center;gap:8px;flex:2;min-width:280px">
            <label style="font-size:13px;color:var(--muted);white-space:nowrap">🎯 North Star</label>
            <input class="planner-input" type="text" placeholder="예: 합계 MAU 85,000 달성" x-model="plannerForm.north_star">
          </div>
          <div style="display:flex;align-items:center;gap:8px;min-width:160px">
            <label style="font-size:13px;color:var(--muted);white-space:nowrap">MAU 목표</label>
            <input class="planner-input" type="number" placeholder="85000" x-model.number="plannerForm.mau_target" style="width:110px">
          </div>
        </div>
      </div>

      <!-- ① 자동 KPI 카드 -->
      <div class="planner-section">
        <div class="planner-section-title">
          📊 자동 불러온 KPI
          <span style="font-size:10px;font-weight:400;color:var(--dim)">(GA4 자동)</span>
          <span style="font-size:11px;font-weight:500;background:rgba(245,158,11,.15);color:#fcd34d;border:1px solid rgba(245,158,11,.3);border-radius:20px;padding:2px 8px;margin-left:4px" x-text="(plannerData?.data_month_label || '') + ' 실적 기준'"></span>
        </div>
        <div class="planner-auto-grid">
          <div class="planner-auto-card">
            <div class="pac-label">MAU (월간 활성 유저)</div>
            <div class="pac-value" x-text="fmtNum(plannerData.auto_kpi.mau)"></div>
            <div class="pac-mom" :class="plannerData.auto_kpi.mau_mom > 0 ? 'wow-up' : plannerData.auto_kpi.mau_mom < 0 ? 'wow-down' : 'wow-flat'">
              <span x-text="fmtMom(plannerData.auto_kpi.mau_mom)"></span>
              <span style="color:var(--muted)"> · 전월 <span x-text="fmtNum(plannerData.auto_kpi.mau_prev)"></span></span>
            </div>
          </div>
          <div class="planner-auto-card">
            <div class="pac-label">신규 가입자</div>
            <div class="pac-value" x-text="fmtNum(plannerData.auto_kpi.new_users)"></div>
            <div class="pac-mom" :class="plannerData.auto_kpi.new_users_mom > 0 ? 'wow-up' : plannerData.auto_kpi.new_users_mom < 0 ? 'wow-down' : 'wow-flat'">
              <span x-text="fmtMom(plannerData.auto_kpi.new_users_mom)"></span>
            </div>
            <div style="display:flex;gap:8px;margin-top:6px;flex-wrap:wrap">
              <span style="font-size:11px;background:rgba(99,102,241,.15);color:#a5b4fc;border-radius:20px;padding:1px 7px">
                🍎 iOS <span x-text="fmtNum(plannerData.auto_kpi.new_users_ios)"></span>
              </span>
              <span style="font-size:11px;background:rgba(16,185,129,.15);color:#6ee7b7;border-radius:20px;padding:1px 7px">
                🤖 Android <span x-text="fmtNum(plannerData.auto_kpi.new_users_android)"></span>
              </span>
            </div>
          </div>
          <div class="planner-auto-card" style="background:rgba(245,158,11,.08);border-color:rgba(245,158,11,.25)">
            <div class="pac-label">W1 리텐션 <span style="font-size:10px;color:var(--dim)">(CSV · 주차 평균)</span></div>
            <div class="pac-value" style="color:#fcd34d" x-text="plannerData.auto_kpi.d7_retention_rate !== null && plannerData.auto_kpi.d7_retention_rate !== undefined ? plannerData.auto_kpi.d7_retention_rate.toFixed(1) + '%' : '—'"></div>
            <div class="pac-mom" style="color:var(--muted);font-size:11px" x-text="'일~토 주차 · 전달 마지막주 포함'"></div>
          </div>
          <div class="planner-auto-card" style="background:rgba(16,185,129,.08);border-color:rgba(16,185,129,.25)">
            <div class="pac-label">누적 가입자 <span style="font-size:10px;color:var(--dim)">(출시~전달)</span></div>
            <div class="pac-value" style="color:#6ee7b7" x-text="fmtNum(plannerData.auto_kpi.cumulative_users)"></div>
            <div class="pac-mom" style="color:var(--muted);font-size:11px" x-text="'신규 +' + fmtNum(plannerData.auto_kpi.new_users) + '명 포함'"></div>
          </div>
        </div>
      </div>

      <!-- MAU 12개월 추이 -->
      <div class="planner-section" x-show="plannerData.trend && plannerData.trend.length">
        <div class="planner-section-title">📈 MAU 12개월 추이 <span style="font-size:10px;font-weight:400;color:var(--dim)">(GA4 + CSV · <span x-text="plannerData?.data_month_label"></span> 기준)</span></div>
        <div class="planner-chart-card">
          <div class="planner-chart-title">MAU <span style="color:#a5b4fc" x-text="plannerData?.data_month_label ? '(전달 ' + fmtNum(plannerData.auto_kpi.mau) + ')' : ''"></span></div>
          <div style="position:relative;height:200px">
            <canvas id="plannerMauChart"></canvas>
          </div>
          <div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:10px">
            <template x-for="d in plannerData.trend" :key="d.month">
              <div style="font-size:11px;background:rgba(99,102,241,.12);border:1px solid rgba(99,102,241,.25);border-radius:6px;padding:3px 9px;line-height:1.5">
                <span style="color:var(--muted)" x-text="d.month_label.replace(/\d{4}년 /, '')"></span><br>
                <span style="color:#a5b4fc;font-weight:700" x-text="fmtNum(d.mau)"></span>
              </div>
            </template>
          </div>
        </div>
      </div>

      <!-- 신규 가입자 12개월 추이 -->
      <div class="planner-section" x-show="plannerData.trend && plannerData.trend.length">
        <div class="planner-section-title">📈 신규 가입자 12개월 추이 <span style="font-size:10px;font-weight:400;color:var(--dim)">(iOS App Store + Android Firebase · <span x-text="plannerData?.data_month_label"></span> 기준)</span></div>
        <div class="planner-chart-card">
          <div class="planner-chart-title">신규 가입자 <span style="color:#6ee7b7" x-text="plannerData?.data_month_label ? '(전달 ' + fmtNum(plannerData.auto_kpi.new_users) + ')' : ''"></span></div>
          <div style="position:relative;height:200px">
            <canvas id="plannerNewUsersChart"></canvas>
          </div>
          <div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:10px">
            <template x-for="d in plannerData.trend" :key="d.month">
              <div style="font-size:11px;background:rgba(16,185,129,.12);border:1px solid rgba(16,185,129,.25);border-radius:6px;padding:3px 9px;line-height:1.5">
                <span style="color:var(--muted)" x-text="d.month_label.replace(/\d{4}년 /, '')"></span><br>
                <span style="color:#6ee7b7;font-weight:700" x-text="fmtNum(d.new_users)"></span>
              </div>
            </template>
          </div>
        </div>
      </div>

      <!-- W1 리텐션 주차별 추이 -->
      <div class="planner-section" x-show="plannerData.d7_weekly && plannerData.d7_weekly.length">
        <div class="planner-section-title">📉 W1 리텐션 주차별 추이 <span style="font-size:10px;font-weight:400;color:var(--dim)">(GA4 동질집단 CSV · data/cohort_retention.csv)</span></div>
        <div class="planner-chart-card">
          <div class="planner-chart-title">W1 Retention (%) — 주차 평균 <span style="color:#fcd34d" x-text="plannerData.auto_kpi.d7_retention_rate !== null && plannerData.auto_kpi.d7_retention_rate !== undefined ? plannerData.auto_kpi.d7_retention_rate.toFixed(1) + '%' : ''"></span></div>
          <div style="position:relative;height:180px">
            <canvas id="plannerD7Chart"></canvas>
          </div>
          <!-- 주차별 수치 요약 -->
          <div style="display:flex;flex-wrap:wrap;gap:6px;margin-top:10px">
            <template x-for="w in plannerData.d7_weekly" :key="w.week_start">
              <div style="font-size:11px;background:rgba(245,158,11,.12);border:1px solid rgba(245,158,11,.25);border-radius:6px;padding:3px 9px;line-height:1.5">
                <span style="color:var(--muted)" x-text="w.label"></span><br>
                <span style="color:#fcd34d;font-weight:700" x-text="w.rate !== null ? w.rate.toFixed(1) + '%' : '—'"></span>
                <span style="color:var(--dim);margin-left:4px" x-text="'(W1 ' + w.day7 + '/' + w.day0 + ')'"></span>
              </div>
            </template>
          </div>
        </div>
      </div>

      <!-- ② 이번 달 목표 & 달성률 -->
      <div class="planner-section">
        <div class="planner-section-title">① 이번 달 목표 &amp; 달성률</div>
        <div class="placement-table-wrap">
          <table class="planner-goals-table">
            <thead><tr>
              <th>핵심 목표</th><th>목표치</th><th>실적</th><th>달성률</th><th>상태</th><th></th>
            </tr></thead>
            <tbody>
              <template x-for="(goal, idx) in plannerForm.goals" :key="idx">
                <tr>
                  <td><input type="text" placeholder="목표명" x-model="goal.name"></td>
                  <td><input type="text" placeholder="85,000" x-model="goal.target" style="width:90px"></td>
                  <td><input type="text" placeholder="실적" x-model="goal.actual" style="width:80px"></td>
                  <td><input type="text" placeholder="97%" x-model="goal.actual_rate" style="width:60px"></td>
                  <td>
                    <select x-model="goal.status">
                      <option value="🟢">🟢</option>
                      <option value="🟡">🟡</option>
                      <option value="🔴">🔴</option>
                    </select>
                  </td>
                  <td><button class="btn-del-row" @click="plannerForm.goals.splice(idx,1)">×</button></td>
                </tr>
              </template>
            </tbody>
          </table>
        </div>
        <button class="btn-add-row" @click="plannerForm.goals.push({name:'',target:'',actual:'',actual_rate:'',status:'🟡'})">+ 목표 추가</button>
      </div>

      <!-- ③ 기능별 지표 -->
      <div class="planner-section">
        <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;margin-bottom:12px">
          <div class="planner-section-title" style="margin-bottom:0">③ 기능별 지표 <span style="font-size:10px;font-weight:400;color:var(--dim)">(GA4 자동)</span> <span style="font-size:11px;font-weight:500;background:rgba(245,158,11,.15);color:#fcd34d;border:1px solid rgba(245,158,11,.3);border-radius:20px;padding:2px 8px" x-text="plannerData?.data_month_label + ' 기준'"></span></div>
          <div style="display:flex;gap:6px;flex-wrap:wrap">
            <template x-for="cat in eventCategories" :key="'pc'+cat.id">
              <button class="evt-cat-btn" :class="plannerEventCat === cat.id ? 'active' : ''" @click="plannerEventCat = cat.id" x-text="cat.label"></button>
            </template>
          </div>
        </div>
        <div class="planner-event-mini">
          <template x-for="evt in plannerEventsByCat(plannerEventCat)" :key="evt.event_name">
            <div class="planner-event-chip"
              :style="evt.mom_change >= 10 ? 'border-color:rgba(16,185,129,.45);background:rgba(16,185,129,.08)' :
                      evt.mom_change <= -10 ? 'border-color:rgba(239,68,68,.45);background:rgba(239,68,68,.08)' :
                      'border-color:rgba(245,158,11,.35);background:rgba(245,158,11,.07)'">
              <div style="position:absolute;top:6px;right:7px;font-size:11px;line-height:1"
                x-text="evt.mom_change >= 10 ? '🟢' : evt.mom_change <= -10 ? '🔴' : '🟡'"></div>
              <div class="pec-name" x-text="evt.label"></div>
              <div class="pec-val" x-text="evt.count >= 1000 ? (evt.count/1000).toFixed(1)+'K' : evt.count.toLocaleString()"></div>
              <div class="pec-mom" :class="evt.mom_change > 0 ? 'wow-up' : evt.mom_change < 0 ? 'wow-down' : 'wow-flat'" x-text="fmtMom(evt.mom_change)"></div>
            </div>
          </template>
        </div>
      </div>

      <!-- ④ 광고별 지표 -->
      <div class="planner-section">
        <div class="planner-section-title">④ 광고별 지표 <span style="font-size:10px;font-weight:400;color:var(--dim)">(GA4 자동 + 매출 수동)</span> <span style="font-size:11px;font-weight:500;background:rgba(245,158,11,.15);color:#fcd34d;border:1px solid rgba(245,158,11,.3);border-radius:20px;padding:2px 8px" x-text="plannerData?.data_month_label + ' 기준'"></span></div>
        <div class="placement-table-wrap">
          <table class="placement-table">
            <thead><tr>
              <th>위치</th><th>클릭수</th><th>MoM</th><th>노출수</th><th>CTR</th><th>매출(원)</th>
            </tr></thead>
            <tbody>
              <template x-for="p in plannerData.ad_placements" :key="p.id">
                <tr>
                  <td>
                    <span class="placement-label" x-text="p.label"></span>
                    <span class="placement-badge" :class="'badge-'+p.id" x-text="p.id"></span>
                  </td>
                  <td><span x-text="p.clicks.toLocaleString()"></span></td>
                  <td>
                    <template x-if="p.mom_change !== null && p.mom_change !== undefined">
                      <span :class="p.mom_change > 0 ? 'wow wow-up' : p.mom_change < 0 ? 'wow wow-down' : 'wow wow-flat'">
                        <span x-text="p.mom_change > 0 ? '▲' : p.mom_change < 0 ? '▼' : '─'"></span>
                        <span x-text="Math.abs(p.mom_change).toFixed(1)+'%'"></span>
                      </span>
                    </template>
                    <template x-if="p.mom_change === null || p.mom_change === undefined"><span style="color:var(--dim)">—</span></template>
                  </td>
                  <td>
                    <template x-if="p.impressions !== null && p.impressions !== undefined"><span x-text="p.impressions.toLocaleString()"></span></template>
                    <template x-if="p.impressions === null || p.impressions === undefined"><span class="conv-none">—</span></template>
                  </td>
                  <td>
                    <template x-if="p.ctr !== null && p.ctr !== undefined"><span class="conv-rate" x-text="p.ctr.toFixed(2)+'%'"></span></template>
                    <template x-if="p.ctr === null || p.ctr === undefined"><span class="conv-none">—</span></template>
                  </td>
                  <td>
                    <input type="number" min="0" step="1000" placeholder="0"
                      x-model.number="plannerForm.ad_revenues[p.id]"
                      style="width:110px;padding:6px 8px;background:var(--bg);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:13px">
                  </td>
                </tr>
              </template>
              <tr style="background:rgba(16,185,129,.06)">
                <td colspan="5" style="font-weight:600;color:var(--muted)">매출 합계</td>
                <td style="font-weight:700;color:#6ee7b7" x-text="fmtNum(adRevenueTotal()) + '원'"></td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- ⑤ 월간 회고 (KPT) -->
      <div class="planner-section">
        <div class="planner-section-title">⑤ 월간 회고 (KPT)</div>
        <div class="planner-kpt-grid">
          <div class="planner-kpt-card">
            <div class="planner-kpt-title">👍 Keep <span style="font-weight:400;font-size:11px;color:var(--muted)">잘 된 것, 유지할 것</span></div>
            <div id="kpt-editor-keep"></div>
          </div>
          <div class="planner-kpt-card">
            <div class="planner-kpt-title">⚠️ Problem <span style="font-weight:400;font-size:11px;color:var(--muted)">아쉬운 점, 문제 원인</span></div>
            <div id="kpt-editor-problem"></div>
          </div>
          <div class="planner-kpt-card">
            <div class="planner-kpt-title">🚀 Try <span style="font-weight:400;font-size:11px;color:var(--muted)">다음 달 개선 시도</span></div>
            <div id="kpt-editor-try"></div>
          </div>
        </div>
      </div>

      <!-- ⑥ 이번 달 핵심 액션 -->
      <div class="planner-section">
        <div class="planner-section-title">⑥ 이번 달 핵심 액션</div>
        <div class="action-card-list">
          <template x-for="(action, idx) in plannerForm.next_actions" :key="action.id">
            <div class="action-card">
              <div class="action-card-header">
                <span class="action-card-num" x-text="idx + 1"></span>
                <div class="action-move-btns">
                  <button type="button" class="action-move-btn" :disabled="idx === 0" @click="moveActionUp(idx)" title="위로">▲</button>
                  <button type="button" class="action-move-btn" :disabled="idx === plannerForm.next_actions.length - 1" @click="moveActionDown(idx)" title="아래로">▼</button>
                </div>
                <div class="action-fields">
                  <input type="text" placeholder="채널" x-model="action.channel">
                  <input type="text" placeholder="핵심 액션" x-model="action.action">
                  <input type="text" placeholder="목표" x-model="action.goal">
                  <input type="text" placeholder="마감" x-model="action.deadline">
                </div>
                <button type="button" class="btn-del-row" @click="removeAction(idx)" title="삭제">×</button>
              </div>
              <div class="action-card-tasks">
                <div class="action-card-tasks-label">구체적 할일</div>
                <div class="action-task-editor" :id="'action-task-editor-' + action.id"></div>
              </div>
            </div>
          </template>
        </div>
        <button type="button" class="btn-add-row" @click="addAction()">+ 액션 추가</button>
      </div>

      <!-- ⑦ 주별 할일 (주간 플래너와 연동) -->
      <div class="planner-section" x-show="monthlyTasksWeeks.length">
        <div class="planner-section-title">⑦ 주별 할일 <span style="font-size:10px;font-weight:400;color:var(--dim)">· 주간 플래너와 동일 데이터</span></div>
        <div class="task-week-grid">
          <template x-for="w in monthlyTasksWeeks" :key="w.week">
            <div class="task-week-card" :class="w.is_current_week ? 'current' : ''">
              <div class="task-week-header">
                <div>
                  <div class="task-week-title" x-text="w.week_label"></div>
                  <div class="task-week-meta" x-text="w.week"></div>
                </div>
                <button class="task-go-week" @click="goToWeek(w.week)" title="주간 플래너로 이동">주간 보기</button>
              </div>
              <div class="task-progress" x-show="w.tasks.length" x-text="taskDoneCount(w.tasks) + '/' + w.tasks.length + ' 완료'"></div>
              <template x-if="!w.tasks.length">
                <div class="task-empty">할일 없음</div>
              </template>
              <template x-for="task in w.tasks" :key="task.id">
                <div class="task-row">
                  <input type="checkbox" :checked="task.done" @change="toggleMonthWeekTask(w.week, task.id)">
                  <span class="task-row-text" :class="task.done ? 'done' : ''" x-text="task.text"></span>
                  <button class="task-del" @click="removeMonthWeekTask(w.week, task.id)" title="삭제">×</button>
                </div>
              </template>
              <div class="task-add-row">
                <input class="task-add-input" type="text" placeholder="할일 추가..." :value="monthWeekTaskInputs[w.week] || ''" @input="monthWeekTaskInputs[w.week] = $event.target.value" @keydown.enter.prevent="addMonthWeekTask(w.week)">
                <button class="task-add-btn" @click="addMonthWeekTask(w.week)">추가</button>
              </div>
            </div>
          </template>
        </div>
      </div>

      <!-- ⑧ 월간 피드백 -->
      <div class="planner-section">
        <div class="planner-section-title" style="display:flex;align-items:center;justify-content:space-between">
          <span>⑧ 월간 피드백</span>
          <span class="note-save-badge" :class="monthlyFeedbackSaved ? 'visible' : ''">저장됨 ✓</span>
        </div>
        <div class="feedback-card">
          <div id="monthly-feedback-editor"></div>
        </div>
      </div>

    </div>
    </template>
  </div><!-- /플래너 뷰 -->

  <!-- 플래너 저장 토스트 -->
  <div class="planner-save-toast" x-show="plannerSavedToast || weeklyPlannerSavedToast" x-cloak>💾 저장 완료!</div>

</main>

<!-- 목표 설정 모달 -->
<div class="modal-backdrop" x-show="showTarget" x-cloak @click.self="showTarget = false">
  <div class="modal">
    <div class="modal-header">
      <div>
        <div class="modal-title">📊 주간 목표 설정</div>
        <div class="modal-sub" x-text="week"></div>
      </div>
      <button class="btn-close" @click="showTarget = false">✕</button>
    </div>
    <div class="modal-body">
      <template x-for="cat in ['user','revenue','ads']" :key="cat">
        <div>
          <div class="modal-section-title" x-text="catLabel(cat)"></div>
          <template x-for="kpi in kpiDefs.filter(k => k.category === cat)" :key="kpi.id">
            <div class="input-row">
              <label x-text="kpi.name + ' (' + kpi.unit + ')'"></label>
              <input type="number" :placeholder="'목표 ' + kpi.unit" x-model.number="targetInputs[kpi.id]">
            </div>
          </template>
        </div>
      </template>
    </div>
    <div class="modal-footer">
      <button class="btn btn-cancel" @click="showTarget = false">취소</button>
      <button class="btn btn-save-target" @click="saveTargets()" :disabled="saving">
        <span x-text="saving ? '저장 중...' : '목표 저장'"></span>
      </button>
    </div>
  </div>
</div>

<!-- 전환율 입력 모달 -->
<div class="modal-backdrop" x-show="showConvModal" x-cloak @click.self="showConvModal = false">
  <div class="modal">
    <div class="modal-header">
      <div>
        <div class="modal-title">📊 광고 위치별 전환율 입력</div>
        <div class="modal-sub" x-text="week + ' · 카페24 애널리틱스 기준'"></div>
      </div>
      <button class="btn-close" @click="showConvModal = false">✕</button>
    </div>
    <div class="modal-body">
      <p style="font-size:12px;color:var(--muted);margin-bottom:14px">카페24 애널리틱스에서 확인한 광고 위치별 전환율(%)을 입력하세요.</p>
      <template x-for="p in placements" :key="p.id">
        <div class="input-row">
          <label>
            <span x-text="p.label"></span>
            <span class="placement-badge" :class="'badge-'+p.id" x-text="p.id" style="margin-left:4px"></span>
          </label>
          <input type="number" step="0.01" min="0" max="100" placeholder="예: 3.25" x-model.number="convInputs[p.id]">
          <span style="font-size:12px;color:var(--muted);white-space:nowrap">%</span>
        </div>
      </template>
    </div>
    <div class="modal-footer">
      <button class="btn btn-cancel" @click="showConvModal = false">취소</button>
      <button class="btn btn-save-target" @click="saveConversions()" :disabled="saving">
        <span x-text="saving ? '저장 중...' : '저장'"></span>
      </button>
    </div>
  </div>
</div>

<!-- 수동 입력 모달 -->
<div class="modal-backdrop" x-show="showManual" x-cloak @click.self="showManual = false">
  <div class="modal">
    <div class="modal-header">
      <div>
        <div class="modal-title">✏️ 수동 데이터 입력</div>
        <div class="modal-sub" x-text="week + ' · GA4 미연동 항목'"></div>
      </div>
      <button class="btn-close" @click="showManual = false">✕</button>
    </div>
    <div class="modal-body">
      <template x-for="cat in ['user','revenue','ads']" :key="cat">
        <div>
          <template x-if="kpiDefs.filter(k => k.category === cat && k.source === 'manual').length > 0">
            <div>
              <div class="modal-section-title" x-text="catLabel(cat)"></div>
              <template x-for="kpi in kpiDefs.filter(k => k.category === cat && k.source === 'manual')" :key="kpi.id">
                <div class="input-row">
                  <label x-text="kpi.name + ' (' + kpi.unit + ')'"></label>
                  <input type="number" :placeholder="'값 입력'" x-model.number="manualInputs[kpi.id]">
                </div>
              </template>
            </div>
          </template>
        </div>
      </template>
    </div>
    <div class="modal-footer">
      <button class="btn btn-cancel" @click="showManual = false">취소</button>
      <button class="btn btn-save-manual" @click="saveManual()" :disabled="saving">
        <span x-text="saving ? '저장 중...' : '데이터 저장'"></span>
      </button>
    </div>
  </div>
</div>

<script>
// ──────────────────────────────
// 주차 유틸 (JS)
// ──────────────────────────────
function getISOWeekKey(d = new Date()) {
  const tmp = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  tmp.setUTCDate(tmp.getUTCDate() + 4 - (tmp.getUTCDay() || 7));
  const yearStart = new Date(Date.UTC(tmp.getUTCFullYear(), 0, 1));
  const week = Math.ceil((((tmp - yearStart) / 86400000) + 1) / 7);
  return `${tmp.getUTCFullYear()}-${String(week).padStart(2,'0')}`;
}

function weekKeyToMonday(key) {
  const [year, week] = key.split('-').map(Number);
  // ISO week 1의 월요일 = 1월 4일이 속한 주의 월요일
  const jan4 = new Date(year, 0, 4);
  const dow = jan4.getDay(); // 0=일, 1=월 ... 6=토
  const mondayOfWeek1 = new Date(jan4);
  mondayOfWeek1.setDate(jan4.getDate() - (dow === 0 ? 6 : dow - 1));
  // 목표 주차의 월요일
  mondayOfWeek1.setDate(mondayOfWeek1.getDate() + (week - 1) * 7);
  return mondayOfWeek1;
}

function offsetWeek(key, delta) {
  const monday = weekKeyToMonday(key);
  monday.setDate(monday.getDate() + delta * 7);
  return getISOWeekKey(monday);
}

function getCurrentMonthKey(d = new Date()) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  return `${y}-${m}`;
}

function offsetMonth(key, delta) {
  let [y, m] = key.split('-').map(Number);
  m += delta;
  while (m > 12) { m -= 12; y++; }
  while (m < 1)  { m += 12; y--; }
  return `${y}-${String(m).padStart(2,'0')}`;
}

// ──────────────────────────────
// Alpine.js 앱
// ──────────────────────────────
function kpiApp() {
  return {
    week: getISOWeekKey(),
    month: getCurrentMonthKey(),
    viewMode: 'weekly',
    data: null,
    loading: false,
    error: null,
    showTarget: false,
    showManual: false,
    showConvModal: false,
    saving: false,
    expandedKpiId: null,
    expandedEventName: null,
    expandedPlacementId: null,
    dailyCache: {},
    dailyLoadingKey: null,
    _dailyCharts: {},
    placementChart: null,
    targetInputs: {},
    manualInputs: {},
    convInputs: {},
    placementEdits: {},
    editingPlacement: null,
    placementData: null,
    eventData: null,
    selectedEventCat: 'contest',
    // 플래너
    plannerLoading: false,
    plannerData: null,
    plannerSaving: false,
    plannerSavedToast: false,
    plannerEventCat: 'contest',
    // 주간 플래너
    weeklyPlannerLoading: false,
    weeklyPlannerData: null,
    weeklyPlannerSaving: false,
    weeklyPlannerSavedToast: false,
    weeklyPlannerEventCat: 'contest',
    weeklyPlannerForm: {
      author: '',
      north_star: '',
      goals: [],
      actions: [],
      ad_revenues: { top: 0, center: 0, bottom: 0, popular_slot: 0, popup: 0 },
    },
    plannerForm: {
      author: '',
      north_star: '',
      mau_target: 0,
      goals: [],
      kpt_keep: '',
      kpt_problem: '',
      kpt_try: '',
      next_actions: [],
      ad_revenues: { top: 0, center: 0, bottom: 0, popular_slot: 0, popup: 0 },
    },
    eventCategories: [
      {id:'contest',       label:'대회'},
      {id:'home',          label:'홈'},
      {id:'shoes',         label:'슈즈'},
      {id:'myrun',         label:'마이런'},
      {id:'participation', label:'참가'},
      {id:'record',        label:'기록'},
      {id:'goal',          label:'목표'},
      {id:'funnel',        label:'펀넬'},
      {id:'etc',           label:'기타'},
    ],
    notes: { kpi_summary: '', project_progress: '', next_week_strategy: '' },
    noteSaved: { kpi_summary: false, project_progress: false, next_week_strategy: false },
    weeklyTasks: [],
    weeklyTaskNew: '',
    weeklyTasksSaved: false,
    monthlyTasksWeeks: [],
    monthWeekTaskInputs: {},
    monthlyFeedback: '',
    monthlyFeedbackSaved: false,

    placements: [
      {id:'top',          label:'상단 카테고리'},
      {id:'center',       label:'스타일'},
      {id:'bottom',       label:'매거진'},
      {id:'popular_slot', label:'인기 슬롯'},
      {id:'popup',        label:'팝업'},
    ],

    kpiDefs: [
      {id:'mau',           name:'MAU',        category:'user',    unit:'명', source:'ga4'},
      {id:'new_users',     name:'신규 가입자', category:'user',    unit:'명', source:'ga4'},
      {id:'sessions',      name:'세션 수',     category:'user',    unit:'회', source:'ga4'},
      {id:'app_downloads', name:'앱 다운로드', category:'user',    unit:'건', source:'manual'},
      {id:'total_revenue', name:'총 매출',     category:'revenue', unit:'원', source:'manual'},
      {id:'payment_count', name:'결제 건수',   category:'revenue', unit:'건', source:'manual'},
      {id:'avg_order_value',name:'평균 결제액', category:'revenue', unit:'원', source:'manual'},
      {id:'ad_impressions',name:'광고 노출',   category:'ads',     unit:'회', source:'manual'},
      {id:'ad_clicks',     name:'광고 클릭',   category:'ads',     unit:'건', source:'manual'},
      {id:'ad_revenue',    name:'광고 수익',   category:'ads',     unit:'원', source:'manual'},
      {id:'ctr',           name:'CTR',         category:'ads',     unit:'%',  source:'manual'},
    ],

    async init() {
      await Promise.all([this.loadKPI(), this.loadPlacements(), this.loadNotes(), this.loadEvents(), this.loadWeeklyTasks()]);
      await this.$nextTick();
      this.scheduleNoteEditors();
    },

    scheduleNoteEditors(retry = 0) {
      this.$nextTick(() => {
        requestAnimationFrame(() => {
          const probe = document.getElementById('note-editor-kpi_summary');
          if (!probe && retry < 15) {
            setTimeout(() => this.scheduleNoteEditors(retry + 1), 100);
            return;
          }
          if (probe) this.initNoteEditors();
        });
      });
    },

    NOTE_FIELDS: ['kpi_summary', 'project_progress', 'next_week_strategy'],
    NOTE_PLACEHOLDERS: {
      kpi_summary:        '이번 주 KPI 달성률 요약을 입력하세요...',
      project_progress:   '핵심 과제 진척도를 입력하세요...',
      next_week_strategy: '차주 KPI 목표 및 계획을 입력하세요...',
    },

    initNoteEditors() {
      if (!window.Quill) return;
      if (!window._noteEditors) window._noteEditors = {};
      const toolbar = [
        [{ header: [1, 2, 3, false] }],
        ['bold', 'italic'],
        [{ list: 'ordered' }, { list: 'bullet' }, { list: 'check' }],
        ['clean'],
      ];
      this.NOTE_FIELDS.forEach(field => {
        const el = document.getElementById(`note-editor-${field}`);
        if (!el) return;
        if (window._noteEditors[field]) {
          const quillRoot = window._noteEditors[field].root?.parentElement;
          if (quillRoot && el.contains(quillRoot)) {
            this._setQuillContent(window._noteEditors[field], this.notes[field]);
            return;
          }
          delete window._noteEditors[field];
        }
        const quill = new Quill(el, {
          theme: 'snow',
          modules: { toolbar },
          placeholder: this.NOTE_PLACEHOLDERS[field] ?? '내용을 입력하세요...',
        });
        // 초기 콘텐츠 설정
        this._setQuillContent(quill, this.notes[field]);
        // 변경 시 자동 저장 (800ms 디바운스)
        let timer;
        quill.on('text-change', () => {
          clearTimeout(timer);
          timer = setTimeout(() => this._saveNoteFromQuill(field), 800);
        });
        window._noteEditors[field] = quill;
      });
    },

    _setQuillContent(quill, raw) {
      if (!raw) { quill.setContents([]); return; }
      try {
        const delta = JSON.parse(raw);
        if (delta?.ops) { quill.setContents(delta); return; }
      } catch {}
      // 플레인 텍스트 fallback
      quill.setText(raw);
    },

    async _saveNoteFromQuill(field) {
      if (!window._noteEditors?.[field]) return;
      this.notes[field] = JSON.stringify(window._noteEditors[field].getContents());
      await this.saveNote(field);
    },

    KPT_EDITOR_KEYS: { keep: 'kpt_keep', problem: 'kpt_problem', 'try': 'kpt_try' },
    KPT_PLACEHOLDERS: {
      keep:    '- 유입 및 리텐션 KPI 세팅 완료\\n- 데이터 기반 의사결정 가능해짐',
      problem: '- 웹 유입 목표 & 전략 미수립\\n- 앱 → 매출 전환율 지표 파악 안됨',
      'try':   '- 명확한 웹 유입 KPI 수립\\n- 앱 내 광고 전환율 상/중/하단별 파악',
    },

    scheduleKptEditors(retry = 0) {
      if (this.viewMode !== 'planner' || !this.plannerData) return;
      this.$nextTick(() => {
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            const probe = document.getElementById('kpt-editor-keep');
            if (probe && probe.offsetParent === null && retry < 8) {
              setTimeout(() => this.scheduleKptEditors(retry + 1), 80);
              return;
            }
            this.initKptEditors();
          });
        });
      });
    },

    initKptEditors() {
      if (!window.Quill || this.viewMode !== 'planner' || !this.plannerData) return;
      if (!window._kptEditors) window._kptEditors = {};
      const toolbar = [
        [{ header: [1, 2, 3, false] }],
        ['bold', 'italic'],
        [{ list: 'ordered' }, { list: 'bullet' }, { list: 'check' }],
        ['clean'],
      ];
      Object.entries(this.KPT_EDITOR_KEYS).forEach(([key, formField]) => {
        const el = document.getElementById(`kpt-editor-${key}`);
        if (!el) return;
        const content = this.plannerForm?.[formField] ?? '';
        if (window._kptEditors[key]) {
          this._setQuillContent(window._kptEditors[key], content);
          return;
        }
        const quill = new Quill(el, {
          theme: 'snow',
          modules: { toolbar },
          placeholder: this.KPT_PLACEHOLDERS[key] ?? '내용을 입력하세요...',
        });
        this._setQuillContent(quill, content);
        window._kptEditors[key] = quill;
      });
    },

    syncKptFromEditors() {
      if (!window._kptEditors) return;
      Object.entries(this.KPT_EDITOR_KEYS).forEach(([key, formField]) => {
        const quill = window._kptEditors[key];
        if (quill) {
          this.plannerForm[formField] = JSON.stringify(quill.getContents());
        }
      });
    },

    newActionItem() {
      return {
        id: 'act_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8),
        channel: '', action: '', goal: '', deadline: '', tasks: '',
      };
    },

    normalizeNextActions(actions) {
      return (actions || []).map((a, i) => ({
        id: a.id || ('act_' + i + '_' + Date.now()),
        channel: a.channel ?? '',
        action: a.action ?? '',
        goal: a.goal ?? '',
        deadline: a.deadline ?? '',
        tasks: a.tasks ?? '',
      }));
    },

    addAction() {
      this.plannerForm.next_actions.push(this.newActionItem());
      this.$nextTick(() => this.scheduleActionTaskEditors());
    },

    removeAction(idx) {
      this.syncActionTasksFromEditors();
      const action = this.plannerForm.next_actions[idx];
      if (action?.id && window._actionTaskEditors?.[action.id]) {
        delete window._actionTaskEditors[action.id];
      }
      this.plannerForm.next_actions.splice(idx, 1);
    },

    moveActionUp(idx) {
      if (idx <= 0) return;
      this.syncActionTasksFromEditors();
      const arr = this.plannerForm.next_actions;
      [arr[idx - 1], arr[idx]] = [arr[idx], arr[idx - 1]];
      this.$nextTick(() => this.scheduleActionTaskEditors());
    },

    moveActionDown(idx) {
      const arr = this.plannerForm.next_actions;
      if (idx >= arr.length - 1) return;
      this.syncActionTasksFromEditors();
      [arr[idx], arr[idx + 1]] = [arr[idx + 1], arr[idx]];
      this.$nextTick(() => this.scheduleActionTaskEditors());
    },

    scheduleActionTaskEditors(retry = 0) {
      if (this.viewMode !== 'planner' || this.plannerLoading || !this.plannerData) return;
      this.$nextTick(() => {
        requestAnimationFrame(() => {
          const actions = this.plannerForm?.next_actions ?? [];
          if (!actions.length) return;
          const allReady = actions.every(a => {
            const el = document.getElementById('action-task-editor-' + a.id);
            return el && el.offsetParent !== null;
          });
          if (!allReady && retry < 25) {
            setTimeout(() => this.scheduleActionTaskEditors(retry + 1), 100);
            return;
          }
          this.initActionTaskEditors();
        });
      });
    },

    initActionTaskEditors() {
      if (!window.Quill) return;
      if (!window._actionTaskEditors) window._actionTaskEditors = {};
      const toolbar = [
        [{ header: [1, 2, 3, false] }],
        ['bold', 'italic'],
        [{ list: 'ordered' }, { list: 'bullet' }, { list: 'check' }],
        ['clean'],
      ];
      const currentIds = new Set((this.plannerForm.next_actions || []).map(a => a.id));
      Object.keys(window._actionTaskEditors).forEach(id => {
        if (!currentIds.has(id)) delete window._actionTaskEditors[id];
      });
      (this.plannerForm.next_actions || []).forEach(action => {
        const el = document.getElementById('action-task-editor-' + action.id);
        if (!el) return;
        if (window._actionTaskEditors[action.id]) {
          this._setQuillContent(window._actionTaskEditors[action.id], action.tasks ?? '');
          return;
        }
        const quill = new Quill(el, {
          theme: 'snow',
          modules: { toolbar },
          placeholder: '구체적인 할일을 적어주세요 (체크리스트, bullet, bold 등)',
        });
        this._setQuillContent(quill, action.tasks ?? '');
        window._actionTaskEditors[action.id] = quill;
      });
    },

    syncActionTasksFromEditors() {
      if (!window._actionTaskEditors) return;
      (this.plannerForm.next_actions || []).forEach(action => {
        const quill = window._actionTaskEditors[action.id];
        if (quill) action.tasks = JSON.stringify(quill.getContents());
      });
    },

    async loadNotes() {
      try {
        const r = await fetch(`/api/notes?week=${this.week}`);
        if (!r.ok) return;
        const data = await r.json();
        this.notes = {
          kpi_summary:        data.kpi_summary        ?? '',
          project_progress:   data.project_progress   ?? '',
          next_week_strategy: data.next_week_strategy ?? '',
        };
        this.noteSaved = { kpi_summary: false, project_progress: false, next_week_strategy: false };
        // 이미 에디터가 초기화된 경우 콘텐츠 업데이트
        if (window._noteEditors) {
          this.NOTE_FIELDS.forEach(field => {
            const q = window._noteEditors[field];
            if (q) this._setQuillContent(q, this.notes[field]);
          });
        }
      } catch(e) {
        console.error('[notes] 로드 실패:', e);
      }
    },

    async saveNote(field) {
      try {
        await fetch('/api/notes', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ week: this.week, ...this.notes }),
        });
        this.noteSaved[field] = true;
        setTimeout(() => { this.noteSaved[field] = false; }, 2000);
      } catch(e) {
        console.error('[notes] 저장 실패:', e);
      }
    },

    _newTaskId() {
      return 't_' + Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
    },

    taskDoneCount(tasks) {
      return (tasks ?? []).filter(t => t.done).length;
    },

    async loadWeeklyTasks() {
      try {
        const r = await fetch(`/api/weekly-tasks?week=${this.week}`);
        if (!r.ok) return;
        const data = await r.json();
        this.weeklyTasks = data.tasks ?? [];
        this.weeklyTaskNew = '';
        this.weeklyTasksSaved = false;
        this._syncMonthlyWeekTasks(this.week, this.weeklyTasks);
      } catch(e) {
        console.error('[weekly-tasks] 로드 실패:', e);
      }
    },

    _syncMonthlyWeekTasks(week, tasks) {
      const idx = this.monthlyTasksWeeks.findIndex(w => w.week === week);
      if (idx >= 0) {
        this.monthlyTasksWeeks[idx].tasks = [...tasks];
      }
    },

    async persistWeeklyTasks(week, tasks) {
      try {
        await fetch('/api/weekly-tasks', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ week, tasks }),
        });
        if (week === this.week) {
          this.weeklyTasksSaved = true;
          setTimeout(() => { this.weeklyTasksSaved = false; }, 2000);
        }
        this._syncMonthlyWeekTasks(week, tasks);
      } catch(e) {
        console.error('[weekly-tasks] 저장 실패:', e);
      }
    },

    addWeeklyTask() {
      const text = (this.weeklyTaskNew || '').trim();
      if (!text) return;
      const tasks = [...this.weeklyTasks, { id: this._newTaskId(), text, done: false }];
      this.weeklyTasks = tasks;
      this.weeklyTaskNew = '';
      this.persistWeeklyTasks(this.week, tasks);
    },

    toggleWeeklyTask(id) {
      const tasks = this.weeklyTasks.map(t => t.id === id ? { ...t, done: !t.done } : t);
      this.weeklyTasks = tasks;
      this.persistWeeklyTasks(this.week, tasks);
    },

    removeWeeklyTask(id) {
      const tasks = this.weeklyTasks.filter(t => t.id !== id);
      this.weeklyTasks = tasks;
      this.persistWeeklyTasks(this.week, tasks);
    },

    _getMonthWeekEntry(week) {
      return this.monthlyTasksWeeks.find(w => w.week === week);
    },

    addMonthWeekTask(week) {
      const text = (this.monthWeekTaskInputs[week] || '').trim();
      if (!text) return;
      const entry = this._getMonthWeekEntry(week);
      if (!entry) return;
      const tasks = [...(entry.tasks ?? []), { id: this._newTaskId(), text, done: false }];
      entry.tasks = tasks;
      this.monthWeekTaskInputs[week] = '';
      if (week === this.week) this.weeklyTasks = [...tasks];
      this.persistWeeklyTasks(week, tasks);
    },

    toggleMonthWeekTask(week, id) {
      const entry = this._getMonthWeekEntry(week);
      if (!entry) return;
      const tasks = (entry.tasks ?? []).map(t => t.id === id ? { ...t, done: !t.done } : t);
      entry.tasks = tasks;
      if (week === this.week) this.weeklyTasks = [...tasks];
      this.persistWeeklyTasks(week, tasks);
    },

    removeMonthWeekTask(week, id) {
      const entry = this._getMonthWeekEntry(week);
      if (!entry) return;
      const tasks = (entry.tasks ?? []).filter(t => t.id !== id);
      entry.tasks = tasks;
      if (week === this.week) this.weeklyTasks = [...tasks];
      this.persistWeeklyTasks(week, tasks);
    },

    goToWeek(weekKey) {
      this.viewMode = 'weekly-planner';
      this.week = weekKey;
      this.loadKPI();
      this.loadPlacements();
      this.loadNotes();
      this.loadEvents();
      this.loadWeeklyTasks();
      this.loadWeeklyPlanner();
    },

    scheduleMonthlyFeedbackEditor(retry = 0) {
      if (this.viewMode !== 'planner' || !this.plannerData) return;
      this.$nextTick(() => {
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            const probe = document.getElementById('monthly-feedback-editor');
            if (probe && probe.offsetParent === null && retry < 8) {
              setTimeout(() => this.scheduleMonthlyFeedbackEditor(retry + 1), 80);
              return;
            }
            this.initMonthlyFeedbackEditor();
          });
        });
      });
    },

    initMonthlyFeedbackEditor() {
      if (!window.Quill || this.viewMode !== 'planner' || !this.plannerData) return;
      const el = document.getElementById('monthly-feedback-editor');
      if (!el) return;
      if (window._monthlyFeedbackEditor) {
        this._setQuillContent(window._monthlyFeedbackEditor, this.monthlyFeedback);
        return;
      }
      const toolbar = [
        [{ header: [1, 2, 3, false] }],
        ['bold', 'italic'],
        [{ list: 'ordered' }, { list: 'bullet' }, { list: 'check' }],
        ['clean'],
      ];
      const quill = new Quill(el, {
        theme: 'snow',
        modules: { toolbar },
        placeholder: '이번 달 전체 회고, 피드백, 개선점을 작성하세요...',
      });
      this._setQuillContent(quill, this.monthlyFeedback);
      let timer;
      quill.on('text-change', () => {
        clearTimeout(timer);
        timer = setTimeout(() => this.saveMonthlyFeedbackFromQuill(), 800);
      });
      window._monthlyFeedbackEditor = quill;
    },

    async saveMonthlyFeedbackFromQuill() {
      if (!window._monthlyFeedbackEditor) return;
      this.monthlyFeedback = JSON.stringify(window._monthlyFeedbackEditor.getContents());
      try {
        await fetch('/api/monthly-feedback', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ month: this.month, feedback: this.monthlyFeedback }),
        });
        this.monthlyFeedbackSaved = true;
        setTimeout(() => { this.monthlyFeedbackSaved = false; }, 2000);
      } catch(e) {
        console.error('[monthly-feedback] 저장 실패:', e);
      }
    },

    async loadPlacements() {
      try {
        const r = await fetch(`/api/kpi/ad-placements?week=${this.week}`);
        if (!r.ok) return;
        this.placementData = await r.json();
        this.placementEdits = {};
        this.placementData.placements.forEach(p => {
          if (p.conversion_rate !== null && p.conversion_rate !== undefined)
            this.convInputs[p.id] = p.conversion_rate;
          this.placementEdits[p.id] = {
            revenue: p.revenue ?? '',
            note: p.note ?? '',
          };
        });
      } catch(e) {
        console.error('[placement] 데이터 로드 실패:', e);
        return;
      }
      // 차트 렌더링은 데이터 로드와 분리 — 에러가 나도 placementData는 유지
      await this.$nextTick();
      try { this.renderPlacementChart(); } catch(e) { console.error('[placement] 차트 렌더링 실패:', e); }
    },

    renderPlacementChart() {
      if (this.placementChart) { this.placementChart.destroy(); this.placementChart = null; }
      const canvas = document.getElementById('placementChart');
      if (!canvas || !this.placementData) return;
      const ps = this.placementData.placements;
      if (!ps.some(p => p.clicks > 0)) return;
      const colors = { top:'#6366f1', center:'#10b981', bottom:'#f59e0b', popular_slot:'#14b8a6', popup:'#ef4444' };
      this.placementChart = new Chart(canvas, {
        type: 'bar',
        data: {
          labels: ps.map(p => p.label),
          datasets: [{
            data: ps.map(p => p.clicks),
            backgroundColor: ps.map(p => colors[p.id] + 'cc'),
            borderColor: ps.map(p => colors[p.id]),
            borderWidth: 1.5,
            borderRadius: 4,
          }],
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: { legend: { display: false }, tooltip: {
            backgroundColor: '#1e293b', borderColor: '#334155', borderWidth: 1,
            titleColor: '#94a3b8', bodyColor: '#f1f5f9',
            callbacks: { label: ctx => ` 클릭 ${ctx.raw.toLocaleString()}회` }
          }},
          scales: {
            x: { grid: {display:false}, ticks: {color:'#94a3b8', font:{size:11}} },
            y: { grid: {color:'#334155'}, ticks: {color:'#94a3b8', font:{size:11}, callback: v => v >= 1000 ? (v/1000).toFixed(1)+'K' : v} },
          },
        },
      });
    },

    placementBarWidth(clicks) {
      const max = Math.max(...(this.placementData?.placements?.map(p => p.clicks) ?? [1]), 1);
      return Math.round(clicks / max * 100);
    },

    isPlacementEditing(p, field) {
      return this.editingPlacement === p.id + ':' + field;
    },

    startPlacementEdit(p, field) {
      if (!this.placementEdits[p.id]) {
        this.placementEdits[p.id] = { revenue: p.revenue ?? '', note: p.note ?? '' };
      }
      this.editingPlacement = p.id + ':' + field;
      this.$nextTick(() => {
        const el = document.getElementById('placement-edit-' + p.id + '-' + field);
        if (el) { el.focus(); if (el.select) el.select(); }
      });
    },

    async commitPlacementMeta(p, field) {
      if (!this.isPlacementEditing(p, field)) return;
      const edits = this.placementEdits[p.id] || {};
      let value = field === 'revenue' ? edits.revenue : edits.note;
      if (field === 'revenue') {
        value = (value === '' || value === null || Number.isNaN(Number(value))) ? null : Number(value);
      } else {
        value = String(value ?? '');
      }
      try {
        const r = await fetch('/api/kpi/ad-placements/meta', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ week: this.week, placement: p.id, field, value }),
        });
        if (!r.ok) throw new Error();
        this.editingPlacement = null;
        await this.loadPlacements();
      } catch (e) {
        console.error('[placement meta] 저장 실패:', e);
      }
    },

    setViewMode(mode) {
      this.viewMode = mode;
      if (mode === 'planner') {
        if (!this.plannerData) this.loadPlanner();
        else {
          this.schedulePlannerCharts();
          this.scheduleKptEditors();
          this.scheduleMonthlyFeedbackEditor();
          this.scheduleActionTaskEditors();
        }
      } else if (mode === 'weekly-planner') {
        this.loadNotes();
        this.loadWeeklyTasks();
        if (!this.weeklyPlannerData) this.loadWeeklyPlanner();
        else {
          this.scheduleNoteEditors();
          this.scheduleWeeklyActionTaskEditors();
        }
      } else if (mode === 'weekly') {
        this.loadWeeklyTasks();
      }
    },

    schedulePlannerCharts(retry = 0) {
      if (this.viewMode !== 'planner') return;
      this.$nextTick(() => {
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            if (!this._plannerChartsReady() && retry < 30) {
              setTimeout(() => this.schedulePlannerCharts(retry + 1), 100);
              return;
            }
            this.renderPlannerCharts();
          });
        });
      });
    },

    _plannerChartsReady() {
      if (this.plannerLoading || !this.plannerData) return false;
      const check = (id, needed) => {
        if (!needed) return true;
        const el = document.getElementById(id);
        return !!(el && el.offsetParent !== null && el.clientWidth > 0);
      };
      const hasTrend = !!(this.plannerData.trend && this.plannerData.trend.length);
      const hasD7 = !!(this.plannerData.d7_weekly && this.plannerData.d7_weekly.length);
      return check('plannerMauChart', hasTrend)
          && check('plannerNewUsersChart', hasTrend)
          && check('plannerD7Chart', hasD7);
    },

    async loadPlannerTasksAndFeedback() {
      try {
        const [tasksRes, fbRes] = await Promise.all([
          fetch(`/api/monthly-tasks?month=${this.month}`),
          fetch(`/api/monthly-feedback?month=${this.month}`),
        ]);
        if (tasksRes.ok) {
          const d = await tasksRes.json();
          this.monthlyTasksWeeks = d.weeks ?? [];
          this.monthWeekTaskInputs = {};
        }
        if (fbRes.ok) {
          const d = await fbRes.json();
          this.monthlyFeedback = d.feedback ?? '';
          this.monthlyFeedbackSaved = false;
          if (window._monthlyFeedbackEditor) {
            this._setQuillContent(window._monthlyFeedbackEditor, this.monthlyFeedback);
          }
        }
      } catch(e) {
        console.error('[planner-tasks] 로드 실패:', e);
      }
    },

    refreshAll() {
      if (this.viewMode === 'weekly') {
        this.closeAllDaily();
        this.dailyCache = {};
        this.loadKPI(); this.loadPlacements(); this.loadEvents(); this.loadWeeklyTasks();
      } else if (this.viewMode === 'weekly-planner') {
        this.weeklyPlannerData = null;
        this.loadNotes();
        this.loadWeeklyTasks();
        this.loadWeeklyPlanner();
      } else {
        this.loadPlanner();
      }
    },

    reloadWeekNav() {
      this.closeAllDaily();
      this.dailyCache = {};
      this.loadKPI();
      this.loadPlacements();
      this.loadNotes();
      this.loadEvents();
      this.loadWeeklyTasks();
      if (this.viewMode === 'weekly-planner') {
        this.weeklyPlannerData = null;
        this.loadWeeklyPlanner();
      }
    },

    navPrev() {
      if (this.viewMode === 'weekly' || this.viewMode === 'weekly-planner') {
        this.week = offsetWeek(this.week, -1);
        this.reloadWeekNav();
      } else {
        this.month = offsetMonth(this.month, -1); this.plannerData = null; this.loadPlanner();
      }
    },

    navNext() {
      if (this.viewMode === 'weekly' || this.viewMode === 'weekly-planner') {
        this.week = offsetWeek(this.week, 1);
        this.reloadWeekNav();
      } else {
        this.month = offsetMonth(this.month, 1); this.plannerData = null; this.loadPlanner();
      }
    },

    goNow() {
      if (this.viewMode === 'weekly' || this.viewMode === 'weekly-planner') {
        this.week = getISOWeekKey();
        this.reloadWeekNav();
      } else {
        this.month = getCurrentMonthKey(); this.plannerData = null; this.loadPlanner();
      }
    },

    isCurrentPeriod() {
      if (this.viewMode === 'weekly' || this.viewMode === 'weekly-planner') return this.week === getISOWeekKey();
      return this.month === getCurrentMonthKey();
    },

    async loadEvents() {
      try {
        const r = await fetch(`/api/kpi/events?week=${this.week}`);
        if (!r.ok) return;
        this.eventData = await r.json();
      } catch(e) {
        console.error('[events] 로드 실패:', e);
      }
    },

    eventsByCat(cat) {
      return this.eventData?.events?.filter(e => e.category === cat) ?? [];
    },

    closeAllDaily() {
      Object.keys(this._dailyCharts || {}).forEach(k => this.destroyDailyChart(k));
      this.expandedKpiId = null;
      this.expandedEventName = null;
      this.expandedPlacementId = null;
    },

    destroyDailyChart(key) {
      if (this._dailyCharts?.[key]) {
        this._dailyCharts[key].destroy();
        delete this._dailyCharts[key];
      }
    },

    _dailyChartReady(canvasId) {
      const el = document.getElementById(canvasId);
      return !!(el && el.offsetParent !== null && el.clientWidth > 0);
    },

    scheduleDailyChart(key, canvasId, renderFn, retry = 0) {
      this.$nextTick(() => {
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            if (!this._dailyChartReady(canvasId)) {
              if (retry < 50) {
                setTimeout(() => this.scheduleDailyChart(key, canvasId, renderFn, retry + 1), 80);
              }
              return;
            }
            renderFn();
            setTimeout(() => { if (this._dailyCharts?.[key]) this._dailyCharts[key].resize(); }, 150);
            setTimeout(() => { if (this._dailyCharts?.[key]) this._dailyCharts[key].resize(); }, 400);
          });
        });
      });
    },

    renderDailyBarChart(key, canvasId, labels, datasets, yFmt) {
      this.destroyDailyChart(key);
      const canvas = document.getElementById(canvasId);
      if (!canvas || !this._dailyChartReady(canvasId)) return;
      try {
      this._dailyCharts[key] = new Chart(canvas, {
        type: 'bar',
        data: { labels, datasets },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: {
            legend: { display: datasets.length > 1, labels: { color: '#94a3b8', font: { size: 11 } } },
            tooltip: {
              backgroundColor: '#1e293b', borderColor: '#334155', borderWidth: 1,
              titleColor: '#94a3b8', bodyColor: '#f1f5f9',
              callbacks: { label: ctx => ` ${ctx.dataset.label}: ${yFmt(ctx.raw)}` },
            },
          },
          scales: {
            x: { grid: { display: false }, ticks: { color: '#94a3b8', font: { size: 11 } } },
            y: { grid: { color: '#334155' }, ticks: { color: '#94a3b8', font: { size: 11 }, callback: yFmt }, beginAtZero: true },
          },
        },
      });
      } catch (e) {
        console.error('[daily chart]', key, e);
      }
    },

    paintKpiDailyChart(entry) {
      const key = 'kpi-' + entry.id;
      const data = this.dailyCache[key];
      if (!data || data.manual_only || data.error) return;
      const catColors = { user: '#6366f1', revenue: '#10b981', ads: '#f59e0b' };
      const color = catColors[entry.category] || '#6366f1';
      const unit = entry.unit || '';
      const canvasId = 'dailyChart-kpi-' + entry.id;
      this.scheduleDailyChart(key, canvasId, () => {
        this.renderDailyBarChart(key, canvasId, data.days.map(d => d.weekday), [{
          label: data.daily_label || entry.name,
          data: data.days.map(d => d.value),
          backgroundColor: color + '55',
          borderColor: color,
          borderWidth: 1.5,
          borderRadius: 4,
        }], v => this.formatVal(v, unit) + unit);
      });
    },

    paintEventDailyChart(evt) {
      const key = 'event-' + evt.event_name;
      const data = this.dailyCache[key];
      if (!data || data.error) return;
      const catColors = {
        contest: '#6366f1', home: '#10b981', shoes: '#f59e0b', myrun: '#14b8a6',
        participation: '#ec4899', record: '#3b82f6', goal: '#22c55e', funnel: '#f97316', etc: '#94a3b8',
      };
      const color = catColors[evt.category] || '#6366f1';
      const canvasId = 'dailyChart-event-' + evt.event_name;
      this.scheduleDailyChart(key, canvasId, () => {
        this.renderDailyBarChart(key, canvasId, data.days.map(d => d.weekday), [{
          label: evt.label,
          data: data.days.map(d => d.value),
          backgroundColor: color + '55',
          borderColor: color,
          borderWidth: 1.5,
          borderRadius: 4,
        }], v => v.toLocaleString() + '회');
      });
    },

    paintPlacementDailyChart(p) {
      const key = 'placement-' + p.id;
      const data = this.dailyCache[key];
      if (!data || data.error) return;
      const colors = { top: '#6366f1', center: '#10b981', bottom: '#f59e0b', popular_slot: '#14b8a6', popup: '#ef4444' };
      const color = colors[p.id] || '#6366f1';
      const canvasId = 'dailyChart-placement-' + p.id;
      this.scheduleDailyChart(key, canvasId, () => {
        const datasets = [{
          label: '클릭',
          data: data.days.map(d => d.clicks),
          backgroundColor: color + '55',
          borderColor: color,
          borderWidth: 1.5,
          borderRadius: 4,
        }];
        if (data.has_impressions) {
          datasets.push({
            label: '노출',
            data: data.days.map(d => d.impressions ?? 0),
            backgroundColor: 'rgba(148,163,184,.35)',
            borderColor: '#94a3b8',
            borderWidth: 1.5,
            borderRadius: 4,
          });
        }
        this.renderDailyBarChart(key, canvasId, data.days.map(d => d.weekday), datasets, v => v.toLocaleString());
      });
    },

    async toggleKpiDaily(entry) {
      if (this.expandedKpiId === entry.id) {
        this.destroyDailyChart('kpi-' + entry.id);
        this.expandedKpiId = null;
        return;
      }
      this.closeAllDaily();
      this.expandedKpiId = entry.id;
      const key = 'kpi-' + entry.id;
      if (!this.dailyCache[key]) {
        this.dailyLoadingKey = key;
        try {
          const r = await fetch(`/api/kpi/daily?week=${this.week}&kpi_id=${entry.id}`);
          if (!r.ok) throw new Error();
          const payload = await r.json();
          this.dailyCache = { ...this.dailyCache, [key]: payload };
        } catch (e) {
          console.error('[daily kpi]', e);
          this.dailyCache = { ...this.dailyCache, [key]: { error: true } };
        } finally {
          this.dailyLoadingKey = null;
        }
      }
    },

    async toggleEventDaily(evt) {
      if (this.expandedEventName === evt.event_name) {
        this.destroyDailyChart('event-' + evt.event_name);
        this.expandedEventName = null;
        return;
      }
      this.closeAllDaily();
      this.expandedEventName = evt.event_name;
      const key = 'event-' + evt.event_name;
      if (!this.dailyCache[key]) {
        this.dailyLoadingKey = key;
        try {
          const r = await fetch(`/api/kpi/events/daily?week=${this.week}&event_name=${encodeURIComponent(evt.event_name)}`);
          if (!r.ok) throw new Error();
          const payload = await r.json();
          this.dailyCache = { ...this.dailyCache, [key]: payload };
        } catch (e) {
          console.error('[daily event]', e);
          this.dailyCache = { ...this.dailyCache, [key]: { error: true } };
        } finally {
          this.dailyLoadingKey = null;
        }
      }
    },

    async togglePlacementDaily(p) {
      if (this.expandedPlacementId === p.id) {
        this.destroyDailyChart('placement-' + p.id);
        this.expandedPlacementId = null;
        return;
      }
      this.closeAllDaily();
      this.expandedPlacementId = p.id;
      const key = 'placement-' + p.id;
      if (!this.dailyCache[key]) {
        this.dailyLoadingKey = key;
        try {
          const r = await fetch(`/api/kpi/ad-placements/daily?week=${this.week}&placement=${p.id}`);
          if (!r.ok) throw new Error();
          const payload = await r.json();
          this.dailyCache = { ...this.dailyCache, [key]: payload };
        } catch (e) {
          console.error('[daily placement]', e);
          this.dailyCache = { ...this.dailyCache, [key]: { error: true } };
        } finally {
          this.dailyLoadingKey = null;
        }
      }
    },

    async saveConversions() {
      this.saving = true;
      try {
        const rates = {};
        Object.entries(this.convInputs).forEach(([k,v]) => { if (v >= 0) rates[k] = v; });
        await fetch('/api/kpi/ad-placements/conversion', {
          method:'PUT', headers:{'Content-Type':'application/json'},
          body: JSON.stringify({week: this.week, rates}),
        });
        this.showConvModal = false;
        await this.loadPlacements();
      } finally { this.saving = false; }
    },

    async loadKPI() {
      this.loading = true;
      this.error = null;
      try {
        const r = await fetch(`/api/kpi?week=${this.week}`);
        if (!r.ok) throw new Error(await r.text());
        this.data = await r.json();
        // 모달 입력 초기값 세팅
        this.data.entries.forEach(e => {
          if (e.target > 0) this.targetInputs[e.id] = e.target;
          if (e.source === 'manual' && e.value > 0) this.manualInputs[e.id] = e.value;
        });
      } catch(e) {
        this.error = e.message || '데이터 로드 실패';
      } finally {
        this.loading = false;
      }
    },

    async saveTargets() {
      this.saving = true;
      try {
        const targets = {};
        Object.entries(this.targetInputs).forEach(([k,v]) => { if (v > 0) targets[k] = v; });
        await fetch('/api/kpi/targets', {method:'PUT', headers:{'Content-Type':'application/json'}, body: JSON.stringify({week: this.week, targets})});
        this.showTarget = false;
        await this.loadKPI();
      } finally { this.saving = false; }
    },

    async saveManual() {
      this.saving = true;
      try {
        const data = {};
        Object.entries(this.manualInputs).forEach(([k,v]) => { if (v > 0) data[k] = v; });
        await fetch('/api/kpi/manual', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({week: this.week, data})});
        this.showManual = false;
        await this.loadKPI();
      } finally { this.saving = false; }
    },

    isCurrentWeek() { return this.week === getISOWeekKey(); },

    entriesByCategory(cat) { return this.data?.entries?.filter(e => e.category === cat) ?? []; },

    catLabel(cat) {
      return {user:'👤 유저 지표', revenue:'💰 매출 지표', ads:'📢 광고 지표'}[cat];
    },

    catSummary(cat) {
      const entries = this.data?.entries?.filter(e => e.category === cat && e.target > 0) ?? [];
      if (!entries.length) return null;
      const avg = entries.reduce((s,e) => s + e.achievement_rate, 0) / entries.length;
      const achieved = entries.filter(e => e.achievement_rate >= 100).length;
      return { avg, achieved, total: entries.length };
    },

    rateColor(rate) { return rate >= 100 ? '#10b981' : rate >= 80 ? '#f59e0b' : '#ef4444'; },
    rateClass(rate) { return rate >= 100 ? 'rate-green' : rate >= 80 ? 'rate-amber' : 'rate-red'; },
    fillClass(rate) { return rate >= 100 ? 'fill-green' : rate >= 80 ? 'fill-amber' : 'fill-red'; },

    formatVal(v, unit) {
      if (unit === '원') {
        if (v >= 100000000) return (v/100000000).toFixed(1)+'억';
        if (v >= 10000) return (v/10000).toFixed(0)+'만';
        return v.toLocaleString();
      }
      if (unit === '%') return v.toFixed(1)+'%';
      if (v >= 1000000) return (v/1000000).toFixed(1)+'M';
      if (v >= 1000) return (v/1000).toFixed(1)+'K';
      return v.toLocaleString();
    },

    // ── 플래너 차트 ──
    plannerMauChart: null,
    plannerNewUsersChart: null,
    plannerD7Chart: null,

    renderPlannerCharts() {
      if (this.viewMode !== 'planner') return;
      if (!this.plannerData?.trend?.length) return;
      const trend = this.plannerData.trend;
      const labels = trend.map(d => d.month_label.replace(/\d{4}년 /, ''));
      const mauVals = trend.map(d => d.mau);
      const newVals = trend.map(d => d.new_users);

      const chartOpts = (color) => ({
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: {
          backgroundColor: '#1e293b', borderColor: '#334155', borderWidth: 1,
          titleColor: '#94a3b8', bodyColor: '#f1f5f9',
        }},
        scales: {
          x: { grid: { display: false }, ticks: { color: '#94a3b8', font: { size: 9 }, maxRotation: 45, minRotation: 0 } },
          y: { grid: { color: '#334155' }, ticks: { color: '#94a3b8', font: { size: 10 },
            callback: v => v >= 1000 ? (v/1000).toFixed(1)+'K' : v } },
        },
      });

      const mkDataset = (data, color, label) => ({
        label, data,
        backgroundColor: color + '44',
        borderColor: color,
        borderWidth: 2,
        borderRadius: 4,
      });

      if (this.plannerMauChart) { this.plannerMauChart.destroy(); this.plannerMauChart = null; }
      const mauCanvas = document.getElementById('plannerMauChart');
      if (mauCanvas && mauCanvas.offsetParent) {
        try {
          this.plannerMauChart = new Chart(mauCanvas, {
            type: 'bar',
            data: { labels, datasets: [mkDataset(mauVals, '#6366f1', 'MAU')] },
            options: chartOpts('#6366f1'),
          });
          this.plannerMauChart.resize();
        } catch(e) { console.error('[planner] MAU 차트 렌더링 실패:', e); }
      }

      if (this.plannerNewUsersChart) { this.plannerNewUsersChart.destroy(); this.plannerNewUsersChart = null; }
      const nuCanvas = document.getElementById('plannerNewUsersChart');
      if (nuCanvas && nuCanvas.offsetParent) {
        try {
          this.plannerNewUsersChart = new Chart(nuCanvas, {
            type: 'bar',
            data: { labels, datasets: [mkDataset(newVals, '#10b981', '신규 가입자')] },
            options: chartOpts('#10b981'),
          });
          this.plannerNewUsersChart.resize();
        } catch(e) { console.error('[planner] 신규 가입자 차트 렌더링 실패:', e); }
      }

      // W1 리텐션 주차 차트
      if (this.plannerD7Chart) { this.plannerD7Chart.destroy(); this.plannerD7Chart = null; }
      const d7Canvas = document.getElementById('plannerD7Chart');
      const d7weeks  = this.plannerData?.d7_weekly ?? [];
      if (d7Canvas && d7Canvas.offsetParent && d7weeks.length) {
        const d7Labels = d7weeks.map(w => w.label);
        const d7Vals   = d7weeks.map(w => w.rate ?? null);
        const avgRate  = this.plannerData?.auto_kpi?.d7_retention_rate;
        try {
          this.plannerD7Chart = new Chart(d7Canvas, {
            type: 'line',
            data: {
              labels: d7Labels,
              datasets: [
                {
                  label: 'W1 리텐션 (%)',
                  data: d7Vals,
                  borderColor: '#f59e0b',
                  backgroundColor: '#f59e0b22',
                  borderWidth: 2,
                  pointBackgroundColor: '#f59e0b',
                  pointRadius: 5,
                  tension: 0.3,
                  fill: true,
                },
                ...(avgRate !== null && avgRate !== undefined ? [{
                  label: `평균 ${avgRate.toFixed(1)}%`,
                  data: d7Labels.map(() => avgRate),
                  borderColor: '#fcd34d88',
                  borderWidth: 1.5,
                  borderDash: [5, 4],
                  pointRadius: 0,
                  fill: false,
                }] : []),
              ],
            },
            options: {
              responsive: true, maintainAspectRatio: false,
              plugins: {
                legend: { display: true, labels: { color: '#94a3b8', font: { size: 10 } } },
                tooltip: {
                  backgroundColor: '#1e293b', borderColor: '#334155', borderWidth: 1,
                  titleColor: '#94a3b8', bodyColor: '#f1f5f9',
                  callbacks: {
                    afterBody: (items) => {
                      const w = d7weeks[items[0].dataIndex];
                      return w ? [`총 사용자: ${w.day0.toLocaleString()}명`, `W1 활성: ${w.day7.toLocaleString()}명`] : [];
                    },
                  },
                },
              },
              scales: {
                x: { grid: { display: false }, ticks: { color: '#94a3b8', font: { size: 10 } } },
                y: {
                  grid: { color: '#334155' },
                  ticks: { color: '#94a3b8', font: { size: 10 }, callback: v => v + '%' },
                  min: 0,
                },
              },
            },
          });
          this.plannerD7Chart.resize();
        } catch(e) { console.error('[planner] W1 리텐션 차트 렌더링 실패:', e); }
      }

      setTimeout(() => {
        this.plannerMauChart?.resize();
        this.plannerNewUsersChart?.resize();
        this.plannerD7Chart?.resize();
      }, 150);
    },

    // ── 플래너 전용 ──
    fmtNum(v) {
      if (v === null || v === undefined) return '—';
      if (v >= 1000000) return (v/1000000).toFixed(1)+'M';
      if (v >= 1000) return (v/1000).toFixed(1)+'K';
      return v.toLocaleString();
    },

    fmtMom(v) {
      if (v === null || v === undefined) return '—';
      const sign = v > 0 ? '▲' : v < 0 ? '▼' : '─';
      return `${sign} ${Math.abs(v).toFixed(1)}%`;
    },

    fmtWow(v) {
      return this.fmtMom(v);
    },

    plannerEventsByCat(cat) {
      return (this.plannerData?.events ?? []).filter(e => e.category === cat);
    },

    defaultAdRevenues() {
      return { top: 0, center: 0, bottom: 0, popular_slot: 0, popup: 0 };
    },

    adRevenueTotal() {
      const rev = this.plannerForm.ad_revenues ?? {};
      return Object.values(rev).reduce((sum, v) => sum + (Number(v) || 0), 0);
    },

    weeklyPlannerEventsByCat(cat) {
      return (this.weeklyPlannerData?.events ?? []).filter(e => e.category === cat);
    },

    weeklyAdRevenueTotal() {
      const rev = this.weeklyPlannerForm.ad_revenues ?? {};
      return Object.values(rev).reduce((sum, v) => sum + (Number(v) || 0), 0);
    },

    normalizeWeeklyActions(actions) {
      return (actions || []).map((a, i) => ({
        id: a.id || ('wact_' + i + '_' + Date.now()),
        channel: a.channel ?? '',
        action: a.action ?? '',
        goal: a.goal ?? '',
        deadline: a.deadline ?? '',
        tasks: a.tasks ?? '',
      }));
    },

    addWeeklyAction() {
      this.weeklyPlannerForm.actions.push(this.newActionItem());
      this.$nextTick(() => this.scheduleWeeklyActionTaskEditors());
    },

    removeWeeklyAction(idx) {
      this.syncWeeklyActionTasksFromEditors();
      const action = this.weeklyPlannerForm.actions[idx];
      if (action?.id && window._weeklyActionTaskEditors?.[action.id]) {
        delete window._weeklyActionTaskEditors[action.id];
      }
      this.weeklyPlannerForm.actions.splice(idx, 1);
    },

    moveWeeklyActionUp(idx) {
      if (idx <= 0) return;
      this.syncWeeklyActionTasksFromEditors();
      const arr = this.weeklyPlannerForm.actions;
      [arr[idx - 1], arr[idx]] = [arr[idx], arr[idx - 1]];
      this.$nextTick(() => this.scheduleWeeklyActionTaskEditors());
    },

    moveWeeklyActionDown(idx) {
      const arr = this.weeklyPlannerForm.actions;
      if (idx >= arr.length - 1) return;
      this.syncWeeklyActionTasksFromEditors();
      [arr[idx], arr[idx + 1]] = [arr[idx + 1], arr[idx]];
      this.$nextTick(() => this.scheduleWeeklyActionTaskEditors());
    },

    scheduleWeeklyActionTaskEditors(retry = 0) {
      if (this.viewMode !== 'weekly-planner' || this.weeklyPlannerLoading || !this.weeklyPlannerData) return;
      this.$nextTick(() => {
        requestAnimationFrame(() => {
          const actions = this.weeklyPlannerForm?.actions ?? [];
          if (!actions.length) return;
          const allReady = actions.every(a => {
            const el = document.getElementById('weekly-action-task-editor-' + a.id);
            return el && el.offsetParent !== null;
          });
          if (!allReady && retry < 25) {
            setTimeout(() => this.scheduleWeeklyActionTaskEditors(retry + 1), 100);
            return;
          }
          this.initWeeklyActionTaskEditors();
        });
      });
    },

    initWeeklyActionTaskEditors() {
      if (!window.Quill) return;
      if (!window._weeklyActionTaskEditors) window._weeklyActionTaskEditors = {};
      const toolbar = [
        [{ header: [1, 2, 3, false] }],
        ['bold', 'italic'],
        [{ list: 'ordered' }, { list: 'bullet' }, { list: 'check' }],
        ['clean'],
      ];
      const currentIds = new Set((this.weeklyPlannerForm.actions || []).map(a => a.id));
      Object.keys(window._weeklyActionTaskEditors).forEach(id => {
        if (!currentIds.has(id)) delete window._weeklyActionTaskEditors[id];
      });
      (this.weeklyPlannerForm.actions || []).forEach(action => {
        const el = document.getElementById('weekly-action-task-editor-' + action.id);
        if (!el) return;
        if (window._weeklyActionTaskEditors[action.id]) {
          this._setQuillContent(window._weeklyActionTaskEditors[action.id], action.tasks ?? '');
          return;
        }
        const quill = new Quill(el, {
          theme: 'snow',
          modules: { toolbar },
          placeholder: '구체적인 할일을 적어주세요 (체크리스트, bullet, bold 등)',
        });
        this._setQuillContent(quill, action.tasks ?? '');
        window._weeklyActionTaskEditors[action.id] = quill;
      });
    },

    syncWeeklyActionTasksFromEditors() {
      if (!window._weeklyActionTaskEditors) return;
      (this.weeklyPlannerForm.actions || []).forEach(action => {
        const quill = window._weeklyActionTaskEditors[action.id];
        if (quill) action.tasks = JSON.stringify(quill.getContents());
      });
    },

    async loadWeeklyPlanner() {
      this.weeklyPlannerLoading = true;
      try {
        const r = await fetch(`/api/weekly-plan?week=${this.week}`);
        if (!r.ok) throw new Error();
        this.weeklyPlannerData = await r.json();
        const p = this.weeklyPlannerData.plan;
        this.weeklyPlannerForm = {
          author:      p.author      ?? '',
          north_star:  p.north_star  ?? '',
          goals:       p.goals       ?? [],
          actions:     this.normalizeWeeklyActions(p.actions),
          ad_revenues: { ...this.defaultAdRevenues(), ...(p.ad_revenues ?? {}) },
        };
        this.weeklyTasks = this.weeklyPlannerData.tasks ?? [];
      } catch(e) {
        console.error('[weekly-planner] 로드 실패:', e);
        this.weeklyPlannerData = null;
      } finally {
        this.weeklyPlannerLoading = false;
        if (this.weeklyPlannerData && this.viewMode === 'weekly-planner') {
          this.scheduleNoteEditors();
          this.scheduleWeeklyActionTaskEditors();
        }
      }
    },

    async saveWeeklyPlanner() {
      this.syncWeeklyActionTasksFromEditors();
      this.weeklyPlannerSaving = true;
      try {
        await fetch('/api/weekly-plan', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ week: this.week, ...this.weeklyPlannerForm }),
        });
        this.weeklyPlannerSavedToast = true;
        setTimeout(() => { this.weeklyPlannerSavedToast = false; }, 2000);
      } catch(e) {
        console.error('[weekly-planner] 저장 실패:', e);
      } finally {
        this.weeklyPlannerSaving = false;
      }
    },

    generateWeeklyMd() {
      window.open(`/api/weekly-plan/generate-md?week=${this.week}`, '_blank');
    },

    async loadPlanner() {
      this.plannerLoading = true;
      try {
        const r = await fetch(`/api/monthly-plan?month=${this.month}`);
        if (!r.ok) throw new Error();
        this.plannerData = await r.json();
        const p = this.plannerData.plan;
        this.plannerForm = {
          author:       p.author       ?? '',
          north_star:   p.north_star   ?? '',
          mau_target:   p.mau_target   ?? 0,
          goals:        p.goals        ?? [],
          kpt_keep:     p.kpt_keep     ?? '',
          kpt_problem:  p.kpt_problem  ?? '',
          kpt_try:      p.kpt_try      ?? '',
          next_actions: this.normalizeNextActions(p.next_actions),
          ad_revenues:  { ...this.defaultAdRevenues(), ...(p.ad_revenues ?? {}) },
        };
        await this.loadPlannerTasksAndFeedback();
      } catch(e) {
        console.error('[planner] 로드 실패:', e);
      } finally {
        this.plannerLoading = false;
        if (this.plannerData && this.viewMode === 'planner') {
          this.scheduleKptEditors();
          this.scheduleMonthlyFeedbackEditor();
          this.scheduleActionTaskEditors();
          this.schedulePlannerCharts();
        }
      }
    },

    async savePlanner() {
      this.syncKptFromEditors();
      this.syncActionTasksFromEditors();
      this.plannerSaving = true;
      try {
        await fetch('/api/monthly-plan', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ month: this.month, ...this.plannerForm }),
        });
        this.plannerSavedToast = true;
        setTimeout(() => { this.plannerSavedToast = false; }, 2000);
      } catch(e) {
        console.error('[planner] 저장 실패:', e);
      } finally {
        this.plannerSaving = false;
      }
    },

    generateMd() {
      window.open(`/api/monthly-plan/generate-md?month=${this.month}`, '_blank');
    },
  };
}
</script>
</body>
</html>"""


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8000"))
    dev = not (os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RENDER"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=dev)
