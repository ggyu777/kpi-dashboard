import { NextResponse } from "next/server";
import {
  BANNER_COPY_MODE_LABELS,
  BANNER_UTM_DEFAULT_SOURCE,
  CUSTOM_EVENT_DEFINITIONS,
  KPI_DEFINITIONS,
  PLACEMENTS,
  mom,
  placementCtr,
  placementImpressionCount,
  wow,
} from "../constants";
import {
  fetchD7RetentionWeekly,
  getCsvNewUsers,
  getCsvNewUsersByPlatform,
  mergeTrendWithOverview,
} from "../csv";
import * as db from "../db";
import {
  fetchAdEventsByName,
  fetchAdEventsMonthly,
  fetchBannerAbReport,
  fetchBannerUtmReport,
  fetchAdPlacementClicks,
  fetchAdPlacementClicksMonthly,
  fetchAdPlacementImpressions,
  fetchAdPlacementImpressionsMonthly,
  fetchCumulativeUsers,
  fetchEventCountDaily,
  fetchGa4MetricDaily,
  fetchGa4Metrics,
  fetchGa4MetricsMonthly,
  fetchNewUsersByPlatform,
} from "../ga4";
import {
  getIsoWeeksInMonth,
  getMonthKey,
  getMonthLabel,
  prevMonthKey,
  recentMonthKeys,
} from "../month";
import {
  buildDailySeries,
  getIsoWeekKey,
  getPlannerWeekLabel,
  getWeekDateRange,
  getWeekDays,
  getWeekLabel,
  prevWeekKey,
  recentWeekKeys,
} from "../week";

async function parallel<T extends Record<string, Promise<unknown>>>(tasks: T) {
  const entries = Object.entries(tasks);
  const results = await Promise.all(entries.map(([, p]) => p));
  return Object.fromEntries(entries.map(([k], i) => [k, results[i]])) as {
    [K in keyof T]: Awaited<T[K]>;
  };
}

export async function handleApi(method: string, pathname: string, req: Request) {
  await db.initDb();
  const url = new URL(req.url);
  const q = url.searchParams;

  if (pathname === "/api/health") {
    return NextResponse.json({ ok: true, storage: db.usingPostgres() ? "postgres" : "none" });
  }

  if (pathname === "/api/kpi" && method === "GET") {
    const week = q.get("week") ?? getIsoWeekKey();
    const prev = prevWeekKey(week);
    const [targets, manual, prevManual, ga4, ga4Prev] = await Promise.all([
      db.getTargets(week),
      db.getManualData(week),
      db.getManualData(prev),
      fetchGa4Metrics(week),
      fetchGa4Metrics(prev),
    ]);
    const entries = KPI_DEFINITIONS.map((kpi) => {
      const value = kpi.source === "ga4" ? (ga4 as Record<string, number>)[kpi.id] ?? 0 : manual[kpi.id] ?? 0;
      const prevValue = kpi.source === "ga4" ? (ga4Prev as Record<string, number>)[kpi.id] ?? 0 : prevManual[kpi.id] ?? 0;
      const target = targets[kpi.id] ?? 0;
      return {
        ...kpi,
        week,
        value,
        target,
        prev_value: prevValue,
        achievement_rate: target > 0 ? Math.round((value / target) * 1000) / 10 : 0,
        wow_change: wow(value, prevValue),
      };
    });
    return NextResponse.json({ week, week_label: getWeekLabel(week), entries });
  }

  if (pathname === "/api/kpi/trend" && method === "GET") {
    const kpiId = q.get("kpi_id") ?? "";
    const kpiDef = KPI_DEFINITIONS.find((k) => k.id === kpiId);
    if (!kpiDef) return NextResponse.json({ detail: "KPI not found" }, { status: 404 });
    const weekList = recentWeekKeys(Number(q.get("weeks") ?? 8), q.get("from_week") ?? undefined);
    const trend = await Promise.all(
      weekList.map(async (wk) => {
        const value =
          kpiDef.source === "ga4"
            ? ((await fetchGa4Metrics(wk)) as Record<string, number>)[kpiId] ?? 0
            : (await db.getManualData(wk))[kpiId] ?? 0;
        const target = (await db.getTargets(wk))[kpiId] ?? 0;
        return {
          week: wk,
          week_label: getWeekLabel(wk),
          value,
          target,
          achievement_rate: target > 0 ? Math.round((value / target) * 1000) / 10 : 0,
        };
      }),
    );
    return NextResponse.json({ kpi_id: kpiId, kpi_def: kpiDef, trend });
  }

  if (pathname === "/api/kpi/daily" && method === "GET") {
    const week = q.get("week") ?? getIsoWeekKey();
    const kpiId = q.get("kpi_id") ?? "";
    const kpiDef = KPI_DEFINITIONS.find((k) => k.id === kpiId);
    if (!kpiDef) return NextResponse.json({ detail: "KPI not found" }, { status: 404 });
    if (kpiDef.source !== "ga4") {
      return NextResponse.json({
        week,
        week_label: getWeekLabel(week),
        kpi_id: kpiId,
        kpi_def: kpiDef,
        days: getWeekDays(week),
        week_total: 0,
        manual_only: true,
      });
    }
    const raw = await fetchGa4MetricDaily(week, kpiId);
    const { days, total } = buildDailySeries(week, raw);
    return NextResponse.json({
      week,
      week_label: getWeekLabel(week),
      kpi_id: kpiId,
      kpi_def: kpiDef,
      daily_label: kpiId === "mau" ? "일 활성" : kpiDef.name,
      days,
      week_total: total,
      manual_only: false,
    });
  }

  if (pathname === "/api/kpi/targets" && method === "PUT") {
    const body = await req.json();
    await db.saveTargets(body.week, body.targets);
    return NextResponse.json({ ok: true, saved: Object.keys(body.targets ?? {}).length });
  }

  if (pathname === "/api/kpi/manual" && method === "POST") {
    const body = await req.json();
    await db.saveManualData(body.week, body.data);
    return NextResponse.json({ ok: true, saved: Object.keys(body.data ?? {}).length });
  }

  if (pathname === "/api/kpi/banner-ab" && method === "GET") {
    const week = q.get("week") ?? getIsoWeekKey();
    const abOnly = q.get("ab_only") !== "0";
    const report = await fetchBannerAbReport(week);
    let ads = report.ads;
    if (abOnly) {
      ads = ads.filter((a) => a.banner_copy_mode === "ab_test" || a.variants.length >= 2);
    }
    return NextResponse.json({
      week,
      week_label: getWeekLabel(week),
      ab_only: abOnly,
      has_data: report.has_data,
      setup_hint: report.has_data
        ? null
        : "GA4 Admin에서 ad_id, copy_variant, banner_copy_mode, ad_name 이벤트 파라미터를 커스텀 dimension(이벤트 스코프)으로 등록해 주세요.",
      copy_mode_labels: BANNER_COPY_MODE_LABELS,
      ads: ads.map((a) => ({
        ...a,
        banner_copy_mode_label: BANNER_COPY_MODE_LABELS[a.banner_copy_mode] ?? (a.banner_copy_mode || "—"),
      })),
    });
  }

  if (pathname === "/api/kpi/banner-utm" && method === "GET") {
    const week = q.get("week") ?? getIsoWeekKey();
    const utmSource = q.get("utm_source")?.trim() || BANNER_UTM_DEFAULT_SOURCE;
    const pairsOnly = q.get("pairs_only") !== "0";
    const report = await fetchBannerUtmReport(week, utmSource);
    let campaigns = report.campaigns;
    if (pairsOnly) {
      campaigns = campaigns.filter((c) => c.variants.length >= 2);
    }
    return NextResponse.json({
      week,
      week_label: getWeekLabel(week),
      utm_source: utmSource,
      pairs_only: pairsOnly,
      has_data: report.has_data,
      note: report.note,
      setup_hint: report.has_data
        ? null
        : `utm_source=${utmSource} 로 유입된 세션이 없습니다. 배너 링크 UTM 또는 GA4 연결(GOOGLE_TOKEN_JSON)을 확인해 주세요.`,
      campaigns,
    });
  }

  if (pathname === "/api/kpi/ad-placements" && method === "GET") {
    const week = q.get("week") ?? getIsoWeekKey();
    const prev = prevWeekKey(week);
    const { clicks, prevClicks, impressions, conversions, meta } = await parallel({
      clicks: fetchAdPlacementClicks(week),
      prevClicks: fetchAdPlacementClicks(prev),
      impressions: fetchAdPlacementImpressions(week),
      conversions: db.getAdConversions(week),
      meta: db.getAdPlacementMeta(week),
    });
    const placements = PLACEMENTS.map((p) => {
      const c = (clicks as Record<string, number>)[p.id] ?? 0;
      const cPrev = (prevClicks as Record<string, number>)[p.id] ?? 0;
      const imp = placementImpressionCount(impressions as Record<string, number>, p.id);
      const m = (meta as Record<string, { revenue: number | null; note: string }>)[p.id] ?? {};
      return {
        ...p,
        clicks: c,
        prev_clicks: cPrev,
        wow_change: wow(c, cPrev),
        impressions: imp,
        ctr: placementCtr(c, imp),
        conversion_rate: (conversions as Record<string, number>)[p.id] ?? null,
        revenue: m.revenue,
        note: m.note ?? "",
      };
    });
    return NextResponse.json({ week, week_label: getWeekLabel(week), placements });
  }

  if (pathname === "/api/kpi/ad-placements/daily" && method === "GET") {
    const week = q.get("week") ?? getIsoWeekKey();
    const placement = q.get("placement") ?? "";
    const pDef = PLACEMENTS.find((p) => p.id === placement);
    if (!pDef) return NextResponse.json({ detail: "Placement not found" }, { status: 404 });
    const { CLICK_EVENT_MAP, IMPRESSION_EVENT_MAP } = await import("../constants");
    const clickEvt = CLICK_EVENT_MAP[placement];
    const impEvt = IMPRESSION_EVENT_MAP[placement];
    const clicksRaw = clickEvt ? await fetchEventCountDaily(week, clickEvt) : {};
    const imprRaw = impEvt ? await fetchEventCountDaily(week, impEvt) : {};
    let clicksTotal = 0;
    let imprTotal = 0;
    const days = getWeekDays(week).map((d) => {
      const c = clicksRaw[d.date] ?? 0;
      const imp = impEvt ? imprRaw[d.date] ?? 0 : null;
      clicksTotal += c;
      if (imp !== null) imprTotal += imp;
      return {
        ...d,
        clicks: c,
        impressions: imp,
        ctr: imp && imp > 0 ? Math.round((c / imp) * 10000) / 100 : null,
      };
    });
    return NextResponse.json({
      week,
      week_label: getWeekLabel(week),
      placement,
      label: pDef.label,
      has_impressions: !!impEvt,
      days,
      clicks_total: clicksTotal,
      impressions_total: impEvt ? imprTotal : null,
    });
  }

  if (pathname === "/api/kpi/ad-placements/conversion" && method === "PUT") {
    const body = await req.json();
    await db.saveAdConversions(body.week, body.rates);
    return NextResponse.json({ ok: true, saved: Object.keys(body.rates ?? {}).length });
  }

  if (pathname === "/api/kpi/ad-placements/meta" && method === "PUT") {
    const body = await req.json();
    if (!["revenue", "note"].includes(body.field)) {
      return NextResponse.json({ detail: "field must be revenue or note" }, { status: 400 });
    }
    await db.saveAdPlacementMetaField(body.week, body.placement, body.field, body.value);
    return NextResponse.json({ ok: true });
  }

  if (pathname === "/api/kpi/events" && method === "GET") {
    const week = q.get("week") ?? getIsoWeekKey();
    const prev = prevWeekKey(week);
    const names = CUSTOM_EVENT_DEFINITIONS.map((e) => e.event_name);
    const [counts, prevCounts] = await Promise.all([
      fetchAdEventsByName(week, [...names]),
      fetchAdEventsByName(prev, [...names]),
    ]);
    const events = CUSTOM_EVENT_DEFINITIONS.map((evt) => {
      const c = counts[evt.event_name] ?? 0;
      const p = prevCounts[evt.event_name] ?? 0;
      return { ...evt, count: c, prev_count: p, wow_change: wow(c, p) };
    });
    return NextResponse.json({ week, week_label: getWeekLabel(week), events });
  }

  if (pathname === "/api/kpi/events/daily" && method === "GET") {
    const week = q.get("week") ?? getIsoWeekKey();
    const eventName = q.get("event_name") ?? "";
    const evt = CUSTOM_EVENT_DEFINITIONS.find((e) => e.event_name === eventName);
    if (!evt) return NextResponse.json({ detail: "Event not found" }, { status: 404 });
    const raw = await fetchEventCountDaily(week, eventName);
    const { days, total } = buildDailySeries(week, raw);
    return NextResponse.json({
      week,
      week_label: getWeekLabel(week),
      event_name: eventName,
      label: evt.label,
      category: evt.category,
      days,
      week_total: total,
    });
  }

  if (pathname === "/api/kpi/events/trend" && method === "GET") {
    const eventName = q.get("event_name") ?? "";
    const evt = CUSTOM_EVENT_DEFINITIONS.find((e) => e.event_name === eventName);
    if (!evt) return NextResponse.json({ detail: "Event not found" }, { status: 404 });
    const weekList = recentWeekKeys(Number(q.get("weeks") ?? 8), q.get("from_week") ?? undefined);
    const trend = await Promise.all(
      weekList.map(async (wk) => {
        const counts = await fetchAdEventsByName(wk, [eventName]);
        return { week: wk, week_label: getWeekLabel(wk), count: counts[eventName] ?? 0 };
      }),
    );
    return NextResponse.json({ event_name: eventName, label: evt.label, category: evt.category, trend });
  }

  if (pathname === "/api/kpi/monthly" && method === "GET") {
    const month = q.get("month") ?? getMonthKey();
    const prev = prevMonthKey(month);
    const [ga4, ga4Prev, manual, prevManual] = await Promise.all([
      fetchGa4MetricsMonthly(month),
      fetchGa4MetricsMonthly(prev),
      db.getManualData(month),
      db.getManualData(prev),
    ]);
    const entries = KPI_DEFINITIONS.map((kpi) => {
      const value = kpi.source === "ga4" ? (ga4 as Record<string, number>)[kpi.id] ?? 0 : manual[kpi.id] ?? 0;
      const prevValue = kpi.source === "ga4" ? (ga4Prev as Record<string, number>)[kpi.id] ?? 0 : prevManual[kpi.id] ?? 0;
      return { ...kpi, month, value, prev_value: prevValue, mom_change: mom(value, prevValue) };
    });
    return NextResponse.json({ month, month_label: getMonthLabel(month), entries });
  }

  if (pathname === "/api/kpi/monthly/trend" && method === "GET") {
    const kpiId = q.get("kpi_id") ?? "";
    const kpiDef = KPI_DEFINITIONS.find((k) => k.id === kpiId);
    if (!kpiDef) return NextResponse.json({ detail: "KPI not found" }, { status: 404 });
    const monthList = recentMonthKeys(Number(q.get("months") ?? 6), q.get("from_month") ?? undefined);
    const trend = await Promise.all(
      monthList.map(async (mk) => {
        const value =
          kpiDef.source === "ga4"
            ? ((await fetchGa4MetricsMonthly(mk)) as Record<string, number>)[kpiId] ?? 0
            : (await db.getManualData(mk))[kpiId] ?? 0;
        return { month: mk, month_label: getMonthLabel(mk), value };
      }),
    );
    return NextResponse.json({ kpi_id: kpiId, kpi_def: kpiDef, trend });
  }

  if (pathname === "/api/kpi/events/monthly" && method === "GET") {
    const month = q.get("month") ?? getMonthKey();
    const prev = prevMonthKey(month);
    const names = CUSTOM_EVENT_DEFINITIONS.map((e) => e.event_name);
    const [counts, prevCounts] = await Promise.all([
      fetchAdEventsMonthly(month, [...names]),
      fetchAdEventsMonthly(prev, [...names]),
    ]);
    const events = CUSTOM_EVENT_DEFINITIONS.map((evt) => {
      const c = counts[evt.event_name] ?? 0;
      const p = prevCounts[evt.event_name] ?? 0;
      return { ...evt, count: c, prev_count: p, mom_change: mom(c, p) };
    });
    return NextResponse.json({ month, month_label: getMonthLabel(month), events });
  }

  if (pathname === "/api/kpi/events/monthly-trend" && method === "GET") {
    const eventName = q.get("event_name") ?? "";
    const evt = CUSTOM_EVENT_DEFINITIONS.find((e) => e.event_name === eventName);
    if (!evt) return NextResponse.json({ detail: "Event not found" }, { status: 404 });
    const monthList = recentMonthKeys(Number(q.get("months") ?? 6), q.get("from_month") ?? undefined);
    const trend = await Promise.all(
      monthList.map(async (mk) => {
        const counts = await fetchAdEventsMonthly(mk, [eventName]);
        return { month: mk, month_label: getMonthLabel(mk), count: counts[eventName] ?? 0 };
      }),
    );
    return NextResponse.json({ event_name: eventName, label: evt.label, category: evt.category, trend });
  }

  if (pathname === "/api/notes" && method === "GET") {
    const week = q.get("week") ?? getIsoWeekKey();
    return NextResponse.json(await db.getWeeklyNotes(week));
  }

  if (pathname === "/api/notes" && method === "PUT") {
    const body = await req.json();
    await db.saveWeeklyNotes(body.week, body.kpi_summary ?? "", body.project_progress ?? "", body.next_week_strategy ?? "");
    return NextResponse.json({ ok: true });
  }

  if (pathname === "/api/weekly-tasks" && method === "GET") {
    const week = q.get("week") ?? getIsoWeekKey();
    return NextResponse.json({
      week,
      week_label: getWeekLabel(week),
      tasks: await db.getWeeklyTasks(week),
    });
  }

  if (pathname === "/api/weekly-tasks" && method === "PUT") {
    const body = await req.json();
    await db.saveWeeklyTasks(body.week, body.tasks ?? []);
    return NextResponse.json({ ok: true, saved: (body.tasks ?? []).length });
  }

  if (pathname === "/api/monthly-tasks" && method === "GET") {
    const month = q.get("month") ?? getMonthKey();
    const weeks = await Promise.all(
      getIsoWeeksInMonth(month).map(async (w) => ({
        ...w,
        tasks: await db.getWeeklyTasks(w.week),
        is_current_week: w.week === getIsoWeekKey(),
      })),
    );
    return NextResponse.json({ month, month_label: getMonthLabel(month), weeks });
  }

  if (pathname === "/api/monthly-feedback" && method === "GET") {
    const month = q.get("month") ?? getMonthKey();
    return NextResponse.json({
      month,
      month_label: getMonthLabel(month),
      feedback: await db.getMonthlyFeedback(month),
    });
  }

  if (pathname === "/api/monthly-feedback" && method === "PUT") {
    const body = await req.json();
    await db.saveMonthlyFeedback(body.month, body.feedback ?? "");
    return NextResponse.json({ ok: true });
  }

  if (pathname === "/api/monthly-plan" && method === "GET") {
    const month = q.get("month") ?? getMonthKey();
    const dataMonth = prevMonthKey(month);
    const prevDataMonth = prevMonthKey(dataMonth);
    const names = CUSTOM_EVENT_DEFINITIONS.map((e) => e.event_name);
    const trendMonths = recentMonthKeys(12, dataMonth);
    const d7Data = fetchD7RetentionWeekly(dataMonth);

    const results = await parallel({
      ga4: fetchGa4MetricsMonthly(dataMonth),
      ga4Prev: fetchGa4MetricsMonthly(prevDataMonth),
      events: fetchAdEventsMonthly(dataMonth, [...names]),
      eventsPrev: fetchAdEventsMonthly(prevDataMonth, [...names]),
      clicks: fetchAdPlacementClicksMonthly(dataMonth),
      clicksPrev: fetchAdPlacementClicksMonthly(prevDataMonth),
      impressions: fetchAdPlacementImpressionsMonthly(dataMonth),
      cumulative: fetchCumulativeUsers(dataMonth),
      platform: fetchNewUsersByPlatform(dataMonth),
      d7: Promise.resolve(d7Data),
      trend: Promise.all(
        trendMonths.map(async (mk) => {
          const r = await fetchGa4MetricsMonthly(mk);
          return { month: mk, month_label: getMonthLabel(mk), mau: r.mau, new_users: r.new_users };
        }),
      ),
      plan: db.getMonthlyPlan(month),
    });

    const trendData = mergeTrendWithOverview(results.trend as Array<{ month: string; month_label: string; mau: number; new_users: number }>);
    const ga4 = results.ga4 as Record<string, number>;
    const ga4Prev = results.ga4Prev as Record<string, number>;
    const eventCounts = results.events as Record<string, number>;
    const eventPrev = results.eventsPrev as Record<string, number>;
    const clicks = results.clicks as Record<string, number>;
    const prevClicks = results.clicksPrev as Record<string, number>;
    const impressions = results.impressions as Record<string, number>;
    const platformUsers = results.platform as Record<string, number>;
    const d7 = results.d7 as Awaited<ReturnType<typeof fetchD7RetentionWeekly>>;

    const events = CUSTOM_EVENT_DEFINITIONS.map((evt) => {
      const c = eventCounts[evt.event_name] ?? 0;
      const p = eventPrev[evt.event_name] ?? 0;
      return { ...evt, count: c, prev_count: p, mom_change: mom(c, p) };
    });

    const adPlacements = PLACEMENTS.map((pDef) => {
      const c = clicks[pDef.id] ?? 0;
      const cP = prevClicks[pDef.id] ?? 0;
      const imp = placementImpressionCount(impressions, pDef.id);
      return {
        ...pDef,
        clicks: c,
        prev_clicks: cP,
        mom_change: mom(c, cP),
        impressions: imp,
        ctr: placementCtr(c, imp),
      };
    });

    const csvPlat = getCsvNewUsersByPlatform(dataMonth);
    const csvPlatPrev = getCsvNewUsersByPlatform(prevDataMonth);
    const csvNew = getCsvNewUsers(dataMonth);
    const csvNewPrev = getCsvNewUsers(prevDataMonth);
    const newUsers = csvNew ?? ga4.new_users ?? 0;
    const newUsersPrev = csvNewPrev ?? ga4Prev.new_users ?? 0;

    return NextResponse.json({
      month,
      month_label: getMonthLabel(month),
      data_month: dataMonth,
      data_month_label: getMonthLabel(dataMonth),
      auto_kpi: {
        mau: ga4.mau ?? 0,
        mau_prev: ga4Prev.mau ?? 0,
        mau_mom: mom(ga4.mau ?? 0, ga4Prev.mau ?? 0),
        new_users: newUsers,
        new_users_prev: newUsersPrev,
        new_users_mom: mom(newUsers, newUsersPrev),
        cumulative_users: results.cumulative,
        d7_retention_rate: d7.avg_rate,
        d7_day0: 0,
        d7_day7: 0,
        new_users_ios: csvPlat?.ios ?? platformUsers.iOS ?? 0,
        new_users_android: csvPlat?.android ?? platformUsers.Android ?? 0,
        new_users_web: platformUsers.web ?? platformUsers.Web ?? 0,
      },
      trend: trendData,
      d7_weekly: d7.weeks,
      events,
      ad_placements: adPlacements,
      plan: results.plan,
    });
  }

  if (pathname === "/api/monthly-plan" && method === "PUT") {
    const body = await req.json();
    await db.saveMonthlyPlan(body.month, body);
    return NextResponse.json({ ok: true });
  }

  if (pathname === "/api/weekly-plan" && method === "GET") {
    const week = q.get("week") ?? getIsoWeekKey();
    const dataWeek = prevWeekKey(week);
    const prevDataWeek = prevWeekKey(dataWeek);
    const names = CUSTOM_EVENT_DEFINITIONS.map((e) => e.event_name);
    const [planStart, planEnd] = getWeekDateRange(week);
    const [dataStart, dataEnd] = getWeekDateRange(dataWeek);

    const r = await parallel({
      ga4: fetchGa4Metrics(dataWeek),
      ga4Prev: fetchGa4Metrics(prevDataWeek),
      events: fetchAdEventsByName(dataWeek, [...names]),
      eventsPrev: fetchAdEventsByName(prevDataWeek, [...names]),
      clicks: fetchAdPlacementClicks(dataWeek),
      clicksPrev: fetchAdPlacementClicks(prevDataWeek),
      impressions: fetchAdPlacementImpressions(dataWeek),
      plan: db.getWeeklyPlan(week),
      notes: db.getWeeklyNotes(week),
      tasks: db.getWeeklyTasks(week),
    });

    const events = CUSTOM_EVENT_DEFINITIONS.map((evt) => {
      const c = (r.events as Record<string, number>)[evt.event_name] ?? 0;
      const p = (r.eventsPrev as Record<string, number>)[evt.event_name] ?? 0;
      return { ...evt, count: c, prev_count: p, wow_change: wow(c, p) };
    });

    const adPlacements = PLACEMENTS.map((pDef) => {
      const c = (r.clicks as Record<string, number>)[pDef.id] ?? 0;
      const cP = (r.clicksPrev as Record<string, number>)[pDef.id] ?? 0;
      const imp = placementImpressionCount(r.impressions as Record<string, number>, pDef.id);
      return {
        ...pDef,
        clicks: c,
        prev_clicks: cP,
        wow_change: wow(c, cP),
        impressions: imp,
        ctr: placementCtr(c, imp),
      };
    });

    const ga4 = r.ga4 as Record<string, number>;
    const ga4Prev = r.ga4Prev as Record<string, number>;

    return NextResponse.json({
      week,
      week_label: getPlannerWeekLabel(week),
      date_range: { start: planStart, end: planEnd },
      data_week: dataWeek,
      data_week_label: getPlannerWeekLabel(dataWeek),
      data_date_range: { start: dataStart, end: dataEnd },
      auto_kpi: {
        mau: ga4.mau ?? 0,
        mau_prev: ga4Prev.mau ?? 0,
        mau_wow: wow(ga4.mau ?? 0, ga4Prev.mau ?? 0),
        new_users: ga4.new_users ?? 0,
        new_users_prev: ga4Prev.new_users ?? 0,
        new_users_wow: wow(ga4.new_users ?? 0, ga4Prev.new_users ?? 0),
        sessions: ga4.sessions ?? 0,
        sessions_prev: ga4Prev.sessions ?? 0,
        sessions_wow: wow(ga4.sessions ?? 0, ga4Prev.sessions ?? 0),
      },
      events,
      ad_placements: adPlacements,
      plan: r.plan,
      notes: r.notes,
      tasks: r.tasks,
    });
  }

  if (pathname === "/api/weekly-plan" && method === "PUT") {
    const body = await req.json();
    await db.saveWeeklyPlan(body.week, body);
    return NextResponse.json({ ok: true });
  }

  if (pathname.startsWith("/api/") && (pathname.endsWith("/generate-md"))) {
    const target = pathname.includes("monthly") ? q.get("month") ?? getMonthKey() : q.get("week") ?? getIsoWeekKey();
    const proxyUrl = pathname.includes("monthly")
      ? `${url.origin}/api/monthly-plan?month=${target}`
      : `${url.origin}/api/weekly-plan?week=${target}`;
    const data = await fetch(proxyUrl).then((r) => r.json());
    const md = `# KPI Plan export\n\n> Auto-generated stub for ${target}\n\n\`\`\`json\n${JSON.stringify(data, null, 2).slice(0, 8000)}\n\`\`\``;
    return new NextResponse(md, {
      headers: {
        "Content-Type": "text/markdown; charset=utf-8",
        "Content-Disposition": `attachment; filename="${target}_plan.md"`,
      },
    });
  }

  return NextResponse.json({ detail: "Not found" }, { status: 404 });
}
