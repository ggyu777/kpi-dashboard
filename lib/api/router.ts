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

function parseWeeklyPlanPut(body: Record<string, unknown>) {
  const week = String(body.week ?? "");
  const hasNotes =
    "kpi_summary" in body || "project_progress" in body || "next_week_strategy" in body;
  const planData = { ...body };
  delete planData.week;
  delete planData.kpi_summary;
  delete planData.project_progress;
  delete planData.next_week_strategy;
  const notes = hasNotes
    ? {
        kpi_summary: String(body.kpi_summary ?? ""),
        project_progress: String(body.project_progress ?? ""),
        next_week_strategy: String(body.next_week_strategy ?? ""),
      }
    : undefined;
  return { week, planData, notes };
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
    const { week, notes } = parseWeeklyPlanPut(body);
    if (!notes) {
      return NextResponse.json({ detail: "notes fields required" }, { status: 400 });
    }
    await db.saveWeeklyPlanWithNotes(week, {}, notes);
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
      prevPlan: db.getMonthlyPlan(dataMonth),
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
      prev_plan: results.prevPlan,
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
    const { week, planData, notes } = parseWeeklyPlanPut(body);
    await db.saveWeeklyPlanWithNotes(week, planData, notes);
    return NextResponse.json({ ok: true });
  }

  if (pathname.startsWith("/api/") && (pathname.endsWith("/generate-md"))) {
    const isMonthly = pathname.includes("monthly");
    const target = isMonthly ? q.get("month") ?? getMonthKey() : q.get("week") ?? getIsoWeekKey();
    const proxyUrl = isMonthly
      ? `${url.origin}/api/monthly-plan?month=${target}`
      : `${url.origin}/api/weekly-plan?week=${target}`;
    const data = await fetch(proxyUrl).then((r) => r.json());
    const md = isMonthly ? buildMonthlyMd(data) : buildWeeklyMd(data);
    return new NextResponse(md, {
      headers: {
        "Content-Type": "text/markdown; charset=utf-8",
        "Content-Disposition": `attachment; filename="${target}_plan.md"`,
      },
    });
  }

  return NextResponse.json({ detail: "Not found" }, { status: 404 });
}

// ── MD builders ──────────────────────────────────────────────────────────────

function fmtPct(v: number | string | null | undefined): string {
  if (v == null || v === "") return "—";
  const n = typeof v === "string" ? parseFloat(v) : v;
  if (!isFinite(n)) return "—";
  return (n >= 0 ? "+" : "") + n.toFixed(1) + "%";
}

function fmtNum(v: number | null | undefined): string {
  if (v == null) return "0";
  return v.toLocaleString("ko-KR");
}

function statusEmoji(rate: number | string | null | undefined): string {
  const n = typeof rate === "string" ? parseFloat(rate) : (rate ?? 0);
  if (n >= 80) return "🟢";
  if (n >= 30) return "🟡";
  return "🔴";
}

interface WPlanGoal { goal?: string; target?: string | number; actual?: string | number; rate?: number | string; status?: string }
interface WPlanAction { channel?: string; action?: string; target?: string; deadline?: string }
interface WPlanNotes { kpi_summary?: string; project_progress?: string; next_week_strategy?: string }
interface WPlanKpi { mau?: number; mau_prev?: number; mau_wow?: number; new_users?: number; new_users_prev?: number; new_users_wow?: number; sessions?: number; sessions_prev?: number; sessions_wow?: number }
interface WPlanPlan { goals?: WPlanGoal[]; actions?: WPlanAction[]; north_star?: string }
interface WPlanEvent { category?: string; label?: string; count: number; wow_change?: number | null }
interface WPlanAd { label?: string; clicks: number; wow_change?: number | null; impressions?: number; ctr?: number; revenue?: number }
interface WPlanDateRange { start?: string; end?: string }
interface WeeklyData { week?: string; week_label?: string; data_week?: string; data_week_label?: string; date_range?: WPlanDateRange; data_date_range?: WPlanDateRange; auto_kpi?: WPlanKpi; plan?: WPlanPlan; notes?: WPlanNotes; tasks?: string[]; events?: WPlanEvent[]; ad_placements?: WPlanAd[] }

function buildWeeklyMd(d: WeeklyData): string {
  const weekLabel = d.week_label ?? d.week ?? "";
  const dataLabel = d.data_week_label ?? d.data_week ?? "";
  const dr = d.date_range ?? {};
  const ddr = d.data_date_range ?? {};
  const planStart = dr.start ?? "";
  const planEnd = dr.end ?? "";
  const dataStart = ddr.start ?? "";
  const dataEnd = ddr.end ?? "";
  const today = new Date().toISOString().slice(0, 10).replace(/-/g, ".");
  const kpi: WPlanKpi = d.auto_kpi ?? {};
  const plan: WPlanPlan = d.plan ?? {};
  const notes: WPlanNotes = d.notes ?? {};
  const tasks: string[] = d.tasks ?? [];
  const events: WPlanEvent[] = d.events ?? [];
  const adPlacements: WPlanAd[] = d.ad_placements ?? [];

  // ① 목표
  const goals: WPlanGoal[] = plan.goals ?? [];
  const goalRows = goals.length > 0
    ? goals.map((g) => {
        const emoji = statusEmoji(g.rate);
        return `| ${g.goal ?? ""} | ${g.target ?? ""} | ${g.actual ?? ""} | ${g.rate ?? 0}% | ${emoji} |`;
      }).join("\n")
    : "| (목표 미입력) | — | — | — | — |";

  // ③ 이벤트 — 카테고리별 그룹
  const catMap = new Map<string, typeof events>();
  for (const e of events) {
    const cat = e.category ?? "기타";
    if (!catMap.has(cat)) catMap.set(cat, []);
    catMap.get(cat)!.push(e);
  }
  let eventsSection = "";
  for (const [cat, rows] of catMap) {
    eventsSection += `\n### ${cat}\n| 이벤트 | 실적 | WoW |\n|--------|------|-----|\n`;
    eventsSection += rows.map((r) => `| ${r.label ?? r.category ?? ""} | ${fmtNum(r.count)} | ${fmtPct(r.wow_change)} |`).join("\n");
    eventsSection += "\n";
  }

  // ④ 광고 지표
  const totalRevenue = adPlacements.reduce((s, p) => s + (p.revenue ?? 0), 0);
  const adRows = adPlacements.map((p) => {
    const rev = p.revenue != null ? fmtNum(p.revenue) : "—";
    const ctr = p.ctr != null ? (p.ctr * 100).toFixed(2) + "%" : "—";
    return `| ${p.label ?? ""} | ${fmtNum(p.clicks)} | ${fmtPct(p.wow_change)} | ${fmtNum(p.impressions ?? 0)} | ${ctr} | ${rev} |`;
  });
  adRows.push(`| **합계** | — | — | — | — | **${fmtNum(totalRevenue)}** |`);

  // ⑤ 노트
  const noteKpi = notes.kpi_summary ?? "(미입력)";
  const noteProject = notes.project_progress ?? "(미입력)";
  const noteNext = notes.next_week_strategy ?? "(미입력)";

  // ⑥ 태스크
  const taskList = tasks.length > 0
    ? tasks.map((t: string) => `- [ ] ${t}`).join("\n")
    : "- (할일 없음)";

  // ⑦ 핵심 액션
  const actions: WPlanAction[] = plan.actions ?? [];
  const northStar: string = plan.north_star ?? "(미입력)";
  const actionRows = actions.length > 0
    ? actions.map((a, i) => `| ${i + 1} | ${a.channel ?? "—"} | ${a.action ?? "—"} | ${a.target ?? "—"} | ${a.deadline ?? "—"} |`).join("\n")
    : "| 1 | — | — | — | — |";
  const actionDetail = actions.length > 0
    ? actions.map((a) => `- [${a.channel ?? ""}] ${a.action ?? ""}`).join("\n")
    : "(액션 없음)";

  // 슬랙 공유용
  const slackGoals = goals.map((g) => `• ${g.goal ?? ""} — ${g.actual ?? ""} / 목표 ${g.target ?? ""} (${statusEmoji(g.rate)})`).join("\n");
  const slackTasks = tasks.map((t: string) => `⬜ ${t}`).join("\n");

  return `# 📋 ${weekLabel} | Weekly Plan | 플랫폼팀

> 작성일: ${today}  |  작성자: 조규준
> 📌 플래너 주차: **${weekLabel}** (${planStart} ~ ${planEnd})
> 📌 KPI 기준: **${dataLabel} 실적** (${dataStart} ~ ${dataEnd} · 전주 기준)

---

## ① ${weekLabel} 목표 & 달성률

| 핵심 목표 | 목표치 | 실적 | 달성률 | 상태 |
|--------|------|-----|------|-----|
${goalRows}

> 상태 기준: 🟢 달성 / 🟡 진행중 / 🔴 미달성

---

## ② KPI 현황 (${dataLabel} 실적)

| 구분 | 전전주 | 전주 실적 | WoW |
|-----|------|---------|-----|
| MAU (주간 활성) | ${fmtNum(kpi.mau_prev)} | ${fmtNum(kpi.mau)} | ${fmtPct(kpi.mau_wow)} |
| 신규 가입자 | ${fmtNum(kpi.new_users_prev)} | ${fmtNum(kpi.new_users)} | ${fmtPct(kpi.new_users_wow)} |
| 세션 수 | ${fmtNum(kpi.sessions_prev)} | ${fmtNum(kpi.sessions)} | ${fmtPct(kpi.sessions_wow)} |

---

## ③ 기능별 지표 (${dataLabel} 실적 · GA4 자동 · WoW)
${eventsSection}
---

## ④ 광고별 지표 (${dataLabel} 실적 · GA4 자동 + 매출 수동)

| 위치 | 클릭수 | WoW | 노출수 | CTR | 매출(원) |
|-----|-------|-----|------|-----|---------|
${adRows.join("\n")}

---

## ⑤ 주간 플래닝 노트

### 🎯 Weekly KPI Dashboard
${noteKpi}

### 🔧 Project Progress
${noteProject.split("\n").map((l: string) => l.startsWith("-") ? l : `- ${l}`).join("\n")}

### 📅 Next Week's Strategy
${noteNext}

---

## ⑥ ${weekLabel} 할일

${taskList}

---

## ⑦ ${weekLabel} 핵심 액션

### 🎯 North Star
> **${northStar}**

| # | 채널 | 액션 | 목표 | 마감 |
|---|-----|-----|-----|-----|
${actionRows}

### 구체적 할일
${actionDetail}

---

# 📣 슬랙 공유용 (복붙)

\`\`\`
📋 *${weekLabel} Weekly Plan* | 플랫폼팀

*① 이번 주 목표*
${slackGoals || "(목표 없음)"}

*② KPI (${dataLabel} 실적)*
MAU: ${fmtNum(kpi.mau_prev)} → ${fmtNum(kpi.mau)} (WoW ${fmtPct(kpi.mau_wow)})
신규: ${fmtNum(kpi.new_users)} (WoW ${fmtPct(kpi.new_users_wow)})

*③ 할일 (${weekLabel})*
${slackTasks || "(할일 없음)"}

*④ 핵심 액션*
${actions.map((a) => `• [${a.channel ?? ""}] ${a.action ?? ""}`).join("\n") || ""}

🎯 North Star: ${northStar}
\`\`\`
`;
}

interface MPlanGoal { name?: string; target?: string | number; actual?: string | number; actual_rate?: number | string; status?: string }
interface MKpi { mau?: number; mau_prev?: number; mau_mom?: number; new_users?: number; new_users_prev?: number; new_users_mom?: number; cumulative_users?: number; d7_retention_rate?: number }
interface MPlanNextAction { channel?: string; action?: string; goal?: string; deadline?: string; tasks?: string }

function quillToText(raw: string | undefined | null, fallback = "(미입력)"): string {
  if (!raw) return fallback;
  try {
    const delta = JSON.parse(raw);
    if (delta?.ops) {
      const text = (delta.ops as Array<{ insert?: unknown }>)
        .map((op) => (typeof op.insert === "string" ? op.insert : ""))
        .join("")
        .trim();
      return text || fallback;
    }
  } catch {}
  return raw.trim() || fallback;
}
interface MPlan {
  author?: string; north_star?: string; mau_target?: number;
  prev_goals?: MPlanGoal[]; goals?: MPlanGoal[];
  kpt_keep?: string; kpt_problem?: string; kpt_try?: string;
  next_actions?: MPlanNextAction[];
  d7_retention_manual?: number | null; d7_note?: string;
  d7_weeks?: Array<{ label?: string; rate?: number | null; note?: string }>;
  monthly_note?: string;
  ad_revenues?: Record<string, number>;
}
interface MEvent { category?: string; label?: string; count: number; mom_change?: number | null }
interface MAd { id?: string; label?: string; clicks: number; mom_change?: number | null; impressions?: number; ctr?: number }
interface MonthlyData { month?: string; month_label?: string; data_month?: string; data_month_label?: string; auto_kpi?: MKpi; plan?: MPlan; events?: MEvent[]; ad_placements?: MAd[] }

function buildMonthlyMd(d: MonthlyData): string {
  const monthLabel = d.month_label ?? d.month ?? "";
  const dataLabel = d.data_month_label ?? d.data_month ?? "";
  const today = new Date().toISOString().slice(0, 10).replace(/-/g, ".");
  const kpi: MKpi = d.auto_kpi ?? {};
  const plan: MPlan = d.plan ?? {};
  const events: MEvent[] = d.events ?? [];
  const adPlacements: MAd[] = d.ad_placements ?? [];

  const author = plan.author || "조규준";
  const northStar = plan.north_star || "(미입력)";
  const mauTarget = plan.mau_target ? fmtNum(plan.mau_target) : "—";

  // 지난달 계획
  const prevGoals: MPlanGoal[] = plan.prev_goals ?? [];
  const prevGoalRows = prevGoals.length > 0
    ? prevGoals.map((g) =>
        `| ${g.name ?? ""} | ${g.target ?? ""} | ${g.actual ?? ""} | ${g.actual_rate ?? "—"} | ${g.status ?? "—"} |`
      ).join("\n")
    : "| (데이터 없음) | — | — | — | — |";

  // 이번달 목표
  const goals: MPlanGoal[] = plan.goals ?? [];
  const goalRows = goals.length > 0
    ? goals.map((g) =>
        `| ${g.name ?? ""} | ${g.target ?? ""} | ${g.actual ?? ""} | ${g.actual_rate ?? "—"} | ${g.status ?? statusEmoji(g.actual_rate)} |`
      ).join("\n")
    : "| (목표 미입력) | — | — | — | — |";

  // KPT (Quill Delta → plain text)
  const kptKeep = quillToText(plan.kpt_keep);
  const kptProblem = quillToText(plan.kpt_problem);
  const kptTry = quillToText(plan.kpt_try);

  // 핵심 액션 (tasks는 Quill Delta → plain text)
  const nextActions: MPlanNextAction[] = plan.next_actions ?? [];
  const actionRows = nextActions.length > 0
    ? nextActions.map((a, i) => {
        const taskText = quillToText(a.tasks, "—").replace(/\n/g, " / ");
        return `| ${i + 1} | ${a.channel ?? "—"} | ${a.action ?? "—"} | ${a.goal ?? "—"} | ${a.deadline ?? "—"} | ${taskText} |`;
      }).join("\n")
    : "| — | — | — | — | — | — |";

  // 이벤트 카테고리별
  const catMap = new Map<string, typeof events>();
  for (const e of events) {
    const cat = e.category ?? "기타";
    if (!catMap.has(cat)) catMap.set(cat, []);
    catMap.get(cat)!.push(e);
  }
  let eventsSection = "";
  for (const [cat, rows] of catMap) {
    eventsSection += `\n### ${cat}\n| 이벤트 | 실적 | MoM |\n|--------|------|-----|\n`;
    eventsSection += rows.map((r) => `| ${r.label ?? ""} | ${fmtNum(r.count)} | ${fmtPct(r.mom_change)} |`).join("\n");
    eventsSection += "\n";
  }

  // 광고 지표 (매출은 plan.ad_revenues에서 가져옴)
  const adRevenues: Record<string, number> = plan.ad_revenues ?? {};
  const totalRevenue = Object.values(adRevenues).reduce((s, v) => s + (v ?? 0), 0);
  const adRows = adPlacements.map((p) => {
    const rev = p.id && adRevenues[p.id] != null ? fmtNum(adRevenues[p.id]) : "—";
    const ctr = p.ctr != null ? p.ctr.toFixed(2) + "%" : "—";
    return `| ${p.label ?? ""} | ${fmtNum(p.clicks)} | ${fmtPct(p.mom_change)} | ${fmtNum(p.impressions ?? 0)} | ${ctr} | ${rev} |`;
  });
  adRows.push(`| **합계** | — | — | — | — | **${fmtNum(totalRevenue)}원** |`);

  // 종합 특이사항
  const monthlyNote = plan.monthly_note || "(미입력)";

  // D7 리텐션
  const d7Rate = kpi.d7_retention_rate != null
    ? kpi.d7_retention_rate.toFixed(1) + "%"
    : (plan.d7_retention_manual != null ? plan.d7_retention_manual.toFixed(1) + "% (수동)" : "—");
  const d7Note = plan.d7_note ? ` · ${plan.d7_note}` : "";
  const d7Weeks = plan.d7_weeks ?? [];
  const d7WeekRows = d7Weeks.length > 0
    ? d7Weeks.map((w) => `| ${w.label ?? ""} | ${w.rate != null ? w.rate.toFixed(1) + "%" : "—"} | ${w.note ?? ""} |`).join("\n")
    : "";

  return `# 📅 ${monthLabel} | Monthly Plan | 플랫폼팀

> 작성일: ${today}  |  작성자: ${author}
> 🎯 North Star: **${northStar}**
> 📌 플래너: **${monthLabel}** · KPI 기준: **${dataLabel} 실적** (전월 기준)
> 🎯 MAU 목표: **${mauTarget}**

---

## ① 지난달 계획 (${dataLabel} 달성률)

| 핵심 목표 | 목표치 | 실적 | 달성률 | 상태 |
|--------|------|-----|------|-----|
${prevGoalRows}

---

## ② 월간 회고 (KPT)

### 👍 Keep — 잘 된 것, 유지할 것
${kptKeep}

### ⚠️ Problem — 아쉬운 점, 문제 원인
${kptProblem}

### 🚀 Try — 다음 달 개선 시도
${kptTry}

---

## ③ KPI 현황 (${dataLabel} 실적)

| 구분 | 전월 | 이번달 실적 | MoM |
|-----|------|-----------|-----|
| MAU | ${fmtNum(kpi.mau_prev)} | ${fmtNum(kpi.mau)} | ${fmtPct(kpi.mau_mom)} |
| 신규 가입자 | ${fmtNum(kpi.new_users_prev)} | ${fmtNum(kpi.new_users)} | ${fmtPct(kpi.new_users_mom)} |
| 누적 사용자 | — | ${fmtNum(kpi.cumulative_users)} | — |
| W1 리텐션 | — | ${d7Rate}${d7Note} | — |

${d7WeekRows ? `\n**W1 리텐션 주차별 상세**\n\n| 주차 | W1 리텐션 | 메모 |\n|------|---------|-----|\n${d7WeekRows}\n` : ""}
---

## ④ 기능별 지표 (${dataLabel} 실적 · GA4 자동 · MoM)
${eventsSection}
---

## ⑤ 광고별 지표 (${dataLabel} 실적 · GA4 자동 + 매출 수동)

| 위치 | 클릭수 | MoM | 노출수 | CTR | 매출(원) |
|-----|-------|-----|------|-----|---------|
${adRows.join("\n")}

---

## 📝 종합 특이사항

${monthlyNote}

---

## ⑥ 이번달 목표

| 핵심 목표 | 목표치 | 실적 | 달성률 | 상태 |
|--------|------|-----|------|-----|
${goalRows}

> 상태 기준: 🟢 달성 / 🟡 진행중 / 🔴 미달성

---

## ⑦ 이번 달 핵심 액션

| # | 채널 | 핵심 액션 | 목표 | 마감 | 구체적 할일 |
|---|------|---------|-----|------|----------|
${actionRows}
`;
}
