export const PLACEMENTS = [
  { id: "top", label: "상단 카테고리" },
  { id: "center", label: "스타일" },
  { id: "bottom", label: "매거진" },
  { id: "popular_slot", label: "인기 슬롯" },
  { id: "popup", label: "팝업" },
] as const;

export const CLICK_EVENT_MAP: Record<string, string> = {
  top: "click_home_category_banner",
  center: "click_home_ad_banner",
  bottom: "click_home_magazine_banner",
  popular_slot: "click_home_popular_slot_ad",
  popup: "click_home_popup",
};

export const IMPRESSION_EVENT_MAP: Record<string, string> = {
  top: "view_home_category_banner",
  center: "view_home_styled_banner",
  bottom: "view_home_magazine_banner",
  popular_slot: "view_home_popular_slot_ad",
  popup: "view_home_popup",
};

export const KPI_GA4_METRIC: Record<string, string> = {
  mau: "activeUsers",
  new_users: "newUsers",
  sessions: "sessions",
};

export const WEEKDAY_KO = ["월", "화", "수", "목", "금", "토", "일"] as const;
export const ORDINAL_KO = ["첫째", "둘째", "셋째", "넷째", "다섯째", "여섯째"] as const;

export const APP_LAUNCH_DATE = process.env.APP_LAUNCH_DATE ?? "2022-01-01";
export const GA4_PROPERTY_ID = process.env.GA4_PROPERTY_ID ?? "410384180";

export const KPI_DEFINITIONS = [
  { id: "mau", name: "MAU", category: "user", unit: "명", source: "ga4" },
  { id: "new_users", name: "신규 가입자", category: "user", unit: "명", source: "ga4" },
  { id: "sessions", name: "세션 수", category: "user", unit: "회", source: "ga4" },
  { id: "app_downloads", name: "앱 다운로드", category: "user", unit: "건", source: "manual" },
  { id: "total_revenue", name: "총 매출", category: "revenue", unit: "원", source: "manual" },
  { id: "payment_count", name: "결제 건수", category: "revenue", unit: "건", source: "manual" },
  { id: "avg_order_value", name: "평균 결제액", category: "revenue", unit: "원", source: "manual" },
  { id: "ad_impressions", name: "광고 노출", category: "ads", unit: "회", source: "manual" },
  { id: "ad_clicks", name: "광고 클릭", category: "ads", unit: "건", source: "manual" },
  { id: "ad_revenue", name: "광고 수익", category: "ads", unit: "원", source: "manual" },
  { id: "ctr", name: "CTR", category: "ads", unit: "%", source: "manual" },
] as const;

export const CUSTOM_EVENT_DEFINITIONS = [
  { event_name: "view_contest_detail", label: "대회 상세 조회", category: "contest" },
  { event_name: "click_external_link", label: "외부 링크 클릭", category: "contest" },
  { event_name: "click_contest_share", label: "대회 공유", category: "contest" },
  { event_name: "click_contest_bookmark", label: "대회 북마크", category: "contest" },
  { event_name: "click_contest_review_more", label: "리뷰 더보기", category: "contest" },
  { event_name: "click_home_participation_more", label: "참가 더보기", category: "home" },
  { event_name: "click_home_popular_more", label: "인기 더보기", category: "home" },
  { event_name: "click_home_shoes_more", label: "슈즈 더보기", category: "home" },
  { event_name: "click_home_to_analysis", label: "분석 이동", category: "home" },
  { event_name: "view_shoes_detail", label: "슈즈 상세 조회", category: "shoes" },
  { event_name: "click_shoes_bookmark", label: "슈즈 북마크", category: "shoes" },
  { event_name: "apply_shoes_filter", label: "슈즈 필터 적용", category: "shoes" },
  { event_name: "view_shoes_tab", label: "슈즈 탭 진입", category: "shoes" },
  { event_name: "view_myrun_tab", label: "마이런 탭 진입", category: "myrun" },
  { event_name: "myrun_stay_time", label: "마이런 체류 이벤트", category: "myrun" },
  { event_name: "click_myrun_sync", label: "데이터 동기화", category: "myrun" },
  { event_name: "click_myrun_stats_goal_button", label: "목표 버튼 클릭", category: "myrun" },
  { event_name: "set_running_stat_goal", label: "러닝 목표 설정", category: "myrun" },
  { event_name: "participation_start", label: "참가 신청 시작", category: "participation" },
  { event_name: "participation_complete", label: "참가 신청 완료", category: "participation" },
  { event_name: "participation_abandon", label: "참가 신청 이탈", category: "participation" },
  { event_name: "participation_bookmark_usage", label: "북마크 대회 사용", category: "participation" },
  { event_name: "participation_submit_error", label: "참가 제출 오류", category: "participation" },
  { event_name: "record_start", label: "기록 시작", category: "record" },
  { event_name: "record_complete", label: "기록 완료", category: "record" },
  { event_name: "record_abandon", label: "기록 이탈", category: "record" },
  { event_name: "record_submit_error", label: "기록 제출 오류", category: "record" },
  { event_name: "upload_certificate", label: "완주증 업로드", category: "record" },
  { event_name: "extract_certificate_success", label: "완주증 추출 성공", category: "record" },
  { event_name: "extract_certificate_fail", label: "완주증 추출 실패", category: "record" },
  { event_name: "set_distance_goal", label: "거리 목표 설정", category: "goal" },
  { event_name: "recur_goal_setting", label: "반복 목표 설정", category: "goal" },
  { event_name: "achieve_distance_goal", label: "목표 달성", category: "goal" },
  { event_name: "click_share_celebration", label: "달성 공유", category: "goal" },
  { event_name: "set_next_goal_after_achieve", label: "다음 목표 설정", category: "goal" },
  { event_name: "funnel_step_complete", label: "펀넬 단계 완료", category: "funnel" },
  { event_name: "search_contest", label: "대회 검색", category: "funnel" },
  { event_name: "select_contest_in_funnel", label: "펀넬 대회 선택", category: "funnel" },
  { event_name: "select_course", label: "코스 선택", category: "funnel" },
  { event_name: "notification_open", label: "알림 열기", category: "etc" },
  { event_name: "complete_onboarding_sync", label: "온보딩 동기화", category: "etc" },
  { event_name: "view_growthbook_experiment", label: "A/B 실험 노출", category: "etc" },
] as const;

export function defaultAdRevenues(): Record<string, number> {
  return { top: 0, center: 0, bottom: 0, popular_slot: 0, popup: 0 };
}

export function placementImpressionCount(
  impressions: Record<string, number>,
  placementId: string,
): number | null {
  if (placementId in IMPRESSION_EVENT_MAP) return impressions[placementId] ?? 0;
  return impressions[placementId] ?? null;
}

export function placementCtr(clicks: number, impressions: number | null): number | null {
  if (impressions === null) return null;
  if (impressions <= 0) return 0;
  return Math.round((clicks / impressions) * 10000) / 100;
}

export function wow(cur: number, prev: number): number | null {
  return prev > 0 ? Math.round(((cur - prev) / prev) * 1000) / 10 : null;
}

export function mom(cur: number, prev: number): number | null {
  return wow(cur, prev);
}
