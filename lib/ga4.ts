import type { BetaAnalyticsDataClient as BetaAnalyticsDataClientType } from "@google-analytics/data";
import { JWT, OAuth2Client } from "google-auth-library";
import path from "path";
import fs from "fs";
import {
  BANNER_AB_SOURCES,
  CLICK_EVENT_MAP,
  GA4_PROPERTY_ID,
  IMPRESSION_EVENT_MAP,
  KPI_GA4_METRIC,
  APP_LAUNCH_DATE,
  placementCtr,
} from "./constants";
import { getMonthDateRange } from "./month";
import { getWeekDateRange, prevWeekKey } from "./week";

const GA4_SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"];
const TOKEN_FILE = path.join(process.cwd(), "token.json");

let clientPromise: Promise<BetaAnalyticsDataClientType | null> | null = null;

type OAuthRaw = Record<string, unknown>;

function normalizeOAuthCredentials(raw: OAuthRaw) {
  const creds = { ...raw };
  if (!creds.access_token && creds.token) creds.access_token = creds.token;
  if (!creds.expiry_date && creds.expiry) {
    creds.expiry_date = new Date(String(creds.expiry)).getTime();
  }
  return creds;
}

async function createOAuthClient(raw: OAuthRaw, persistPath?: string) {
  const creds = normalizeOAuthCredentials(raw);
  const oauth = new OAuth2Client(
    creds.client_id as string | undefined,
    creds.client_secret as string | undefined,
  );
  oauth.setCredentials(creds as never);
  if (oauth.credentials.expiry_date && oauth.credentials.expiry_date < Date.now()) {
    const { credentials } = await oauth.refreshAccessToken();
    oauth.setCredentials(credentials);
    if (persistPath) {
      fs.writeFileSync(persistPath, JSON.stringify({ ...raw, ...credentials }, null, 2));
    }
  }
  return oauth;
}

async function getGa4Client(): Promise<BetaAnalyticsDataClientType | null> {
  if (!clientPromise) clientPromise = createClient();
  return clientPromise;
}

async function createClient(): Promise<BetaAnalyticsDataClientType | null> {
  try {
    const { BetaAnalyticsDataClient } = await import("@google-analytics/data");
    if (fs.existsSync(TOKEN_FILE)) {
      const raw = JSON.parse(fs.readFileSync(TOKEN_FILE, "utf8")) as OAuthRaw;
      const oauth = await createOAuthClient(raw, TOKEN_FILE);
      return new BetaAnalyticsDataClient({ authClient: oauth as never });
    }

    const tokenJson = process.env.GOOGLE_TOKEN_JSON?.trim();
    if (tokenJson) {
      const raw = JSON.parse(tokenJson) as OAuthRaw;
      const oauth = await createOAuthClient(raw);
      return new BetaAnalyticsDataClient({ authClient: oauth as never });
    }

    const credsJson = process.env.GOOGLE_CREDENTIALS_JSON?.trim();
    if (credsJson) {
      const info = JSON.parse(credsJson);
      const auth = new JWT({
        email: info.client_email,
        key: info.private_key,
        scopes: GA4_SCOPES,
      });
      return new BetaAnalyticsDataClient({ authClient: auth as never });
    }

    const svcPath = process.env.GOOGLE_APPLICATION_CREDENTIALS;
    if (svcPath && fs.existsSync(svcPath)) {
      return new BetaAnalyticsDataClient({ keyFilename: svcPath });
    }
    return null;
  } catch (e) {
    console.error("[GA4] client error:", e);
    return null;
  }
}

function ga4DateToIso(ga4Date: string) {
  const s = ga4Date.trim();
  if (s.length === 8 && /^\d+$/.test(s)) {
    return `${s.slice(0, 4)}-${s.slice(4, 6)}-${s.slice(6, 8)}`;
  }
  return s;
}

export async function fetchGa4Metrics(weekKey: string) {
  const client = await getGa4Client();
  if (!client) return { mau: 0, new_users: 0, sessions: 0 };
  const [startDate, endDate] = getWeekDateRange(weekKey);
  try {
    const [response] = await client.runReport({
      property: `properties/${GA4_PROPERTY_ID}`,
      dateRanges: [{ startDate, endDate }],
      metrics: [{ name: "activeUsers" }, { name: "newUsers" }, { name: "sessions" }],
    });
    const row = response.rows?.[0];
    const vals = row?.metricValues?.map((v) => Number(v.value ?? 0)) ?? [0, 0, 0];
    return { mau: vals[0], new_users: vals[1], sessions: vals[2] };
  } catch (e) {
    console.error("[GA4] weekly metrics:", e);
    return { mau: 0, new_users: 0, sessions: 0 };
  }
}

export async function fetchGa4MetricsMonthly(monthKey: string) {
  const client = await getGa4Client();
  if (!client) return { mau: 0, new_users: 0, sessions: 0 };
  const [startDate, endDate] = getMonthDateRange(monthKey);
  try {
    const [response] = await client.runReport({
      property: `properties/${GA4_PROPERTY_ID}`,
      dateRanges: [{ startDate, endDate }],
      metrics: [{ name: "activeUsers" }, { name: "newUsers" }, { name: "sessions" }],
    });
    const row = response.rows?.[0];
    const vals = row?.metricValues?.map((v) => Number(v.value ?? 0)) ?? [0, 0, 0];
    return { mau: vals[0], new_users: vals[1], sessions: vals[2] };
  } catch (e) {
    console.error("[GA4] monthly metrics:", e);
    return { mau: 0, new_users: 0, sessions: 0 };
  }
}

export async function fetchGa4MetricDaily(weekKey: string, metricKey: string) {
  const ga4Metric = KPI_GA4_METRIC[metricKey];
  if (!ga4Metric) return {};
  const client = await getGa4Client();
  if (!client) return {};
  const [startDate, endDate] = getWeekDateRange(weekKey);
  try {
    const [response] = await client.runReport({
      property: `properties/${GA4_PROPERTY_ID}`,
      dateRanges: [{ startDate, endDate }],
      dimensions: [{ name: "date" }],
      metrics: [{ name: ga4Metric }],
    });
    const out: Record<string, number> = {};
    for (const row of response.rows ?? []) {
      out[ga4DateToIso(row.dimensionValues?.[0]?.value ?? "")] = Number(row.metricValues?.[0]?.value ?? 0);
    }
    return out;
  } catch (e) {
    console.error("[GA4] daily metric:", e);
    return {};
  }
}

function eventFilter(eventNames: string[]) {
  return {
    orGroup: {
      expressions: eventNames.map((evt) => ({
        filter: { fieldName: "eventName", stringFilter: { value: evt } },
      })),
    },
  };
}

export async function fetchAdEventsByName(weekKey: string, eventNames: string[]) {
  const client = await getGa4Client();
  if (!client || !eventNames.length) return {};
  const [startDate, endDate] = getWeekDateRange(weekKey);
  try {
    const [response] = await client.runReport({
      property: `properties/${GA4_PROPERTY_ID}`,
      dateRanges: [{ startDate, endDate }],
      dimensions: [{ name: "eventName" }],
      metrics: [{ name: "eventCount" }],
      dimensionFilter: eventFilter(eventNames),
    });
    return Object.fromEntries(
      (response.rows ?? []).map((row) => [
        row.dimensionValues?.[0]?.value ?? "",
        Number(row.metricValues?.[0]?.value ?? 0),
      ]),
    );
  } catch (e) {
    console.error("[GA4] events:", e);
    return {};
  }
}

export async function fetchAdEventsMonthly(monthKey: string, eventNames: string[]) {
  const client = await getGa4Client();
  if (!client || !eventNames.length) return {};
  const [startDate, endDate] = getMonthDateRange(monthKey);
  try {
    const [response] = await client.runReport({
      property: `properties/${GA4_PROPERTY_ID}`,
      dateRanges: [{ startDate, endDate }],
      dimensions: [{ name: "eventName" }],
      metrics: [{ name: "eventCount" }],
      dimensionFilter: eventFilter(eventNames),
    });
    return Object.fromEntries(
      (response.rows ?? []).map((row) => [
        row.dimensionValues?.[0]?.value ?? "",
        Number(row.metricValues?.[0]?.value ?? 0),
      ]),
    );
  } catch (e) {
    console.error("[GA4] monthly events:", e);
    return {};
  }
}

export async function fetchEventCountDaily(weekKey: string, eventName: string) {
  const client = await getGa4Client();
  if (!client) return {};
  const [startDate, endDate] = getWeekDateRange(weekKey);
  try {
    const [response] = await client.runReport({
      property: `properties/${GA4_PROPERTY_ID}`,
      dateRanges: [{ startDate, endDate }],
      dimensions: [{ name: "date" }],
      metrics: [{ name: "eventCount" }],
      dimensionFilter: {
        filter: { fieldName: "eventName", stringFilter: { value: eventName } },
      },
    });
    const out: Record<string, number> = {};
    for (const row of response.rows ?? []) {
      out[ga4DateToIso(row.dimensionValues?.[0]?.value ?? "")] = Number(row.metricValues?.[0]?.value ?? 0);
    }
    return out;
  } catch (e) {
    console.error("[GA4] daily event:", e);
    return {};
  }
}

export async function fetchAdPlacementClicks(weekKey: string) {
  const raw = await fetchAdEventsByName(weekKey, Object.values(CLICK_EVENT_MAP));
  const inverted = Object.fromEntries(Object.entries(CLICK_EVENT_MAP).map(([k, v]) => [v, k]));
  return Object.fromEntries(
    Object.entries(raw)
      .filter(([evt]) => evt in inverted)
      .map(([evt, cnt]) => [inverted[evt], cnt]),
  ) as Record<string, number>;
}

export async function fetchAdPlacementImpressions(weekKey: string) {
  const raw = await fetchAdEventsByName(weekKey, Object.values(IMPRESSION_EVENT_MAP));
  const inverted = Object.fromEntries(Object.entries(IMPRESSION_EVENT_MAP).map(([k, v]) => [v, k]));
  return Object.fromEntries(
    Object.entries(raw)
      .filter(([evt]) => evt in inverted)
      .map(([evt, cnt]) => [inverted[evt], cnt]),
  ) as Record<string, number>;
}

export async function fetchAdPlacementClicksMonthly(monthKey: string) {
  const raw = await fetchAdEventsMonthly(monthKey, Object.values(CLICK_EVENT_MAP));
  const inverted = Object.fromEntries(Object.entries(CLICK_EVENT_MAP).map(([k, v]) => [v, k]));
  return Object.fromEntries(
    Object.entries(raw)
      .filter(([evt]) => evt in inverted)
      .map(([evt, cnt]) => [inverted[evt], cnt]),
  ) as Record<string, number>;
}

export async function fetchAdPlacementImpressionsMonthly(monthKey: string) {
  const raw = await fetchAdEventsMonthly(monthKey, Object.values(IMPRESSION_EVENT_MAP));
  const inverted = Object.fromEntries(Object.entries(IMPRESSION_EVENT_MAP).map(([k, v]) => [v, k]));
  return Object.fromEntries(
    Object.entries(raw)
      .filter(([evt]) => evt in inverted)
      .map(([evt, cnt]) => [inverted[evt], cnt]),
  ) as Record<string, number>;
}

export async function fetchNewUsersByPlatform(monthKey: string) {
  const client = await getGa4Client();
  if (!client) return {};
  const [startDate, endDate] = getMonthDateRange(monthKey);
  try {
    const [response] = await client.runReport({
      property: `properties/${GA4_PROPERTY_ID}`,
      dateRanges: [{ startDate, endDate }],
      dimensions: [{ name: "operatingSystem" }],
      metrics: [{ name: "newUsers" }],
    });
    const result: Record<string, number> = {};
    for (const row of response.rows ?? []) {
      const os = row.dimensionValues?.[0]?.value ?? "";
      result[os] = (result[os] ?? 0) + Number(row.metricValues?.[0]?.value ?? 0);
    }
    return result;
  } catch (e) {
    console.error("[GA4] platform:", e);
    return {};
  }
}

const BANNER_AB_DIMENSION_SETS = [
  [
    "customEvent:ad_id",
    "customEvent:copy_variant",
    "customEvent:banner_copy_mode",
    "customEvent:ad_name",
  ],
  ["customEvent:ad_id", "customEvent:copy_variant"],
] as const;

export type BannerAbRawRow = {
  ad_id: string;
  copy_variant: string;
  banner_copy_mode: string;
  ad_name: string;
  count: number;
};

function parseBannerAbRows(
  rows: Array<{ dimensionValues?: Array<{ value?: string | null }> | null; metricValues?: Array<{ value?: string | null }> | null }>,
  dimCount: number,
): BannerAbRawRow[] {
  return rows
    .map((row) => {
      const dv = row.dimensionValues ?? [];
      const ad_id = dv[0]?.value ?? "";
      const copy_variant = dv[1]?.value ?? "";
      const banner_copy_mode = dimCount > 2 ? (dv[2]?.value ?? "") : "";
      const ad_name = dimCount > 3 ? (dv[3]?.value ?? "") : "";
      return {
        ad_id,
        copy_variant,
        banner_copy_mode,
        ad_name,
        count: Number(row.metricValues?.[0]?.value ?? 0),
      };
    })
    .filter((r) => r.ad_id && r.copy_variant);
}

async function fetchBannerEventBreakdown(weekKey: string, eventName: string): Promise<BannerAbRawRow[]> {
  const client = await getGa4Client();
  if (!client) return [];
  const [startDate, endDate] = getWeekDateRange(weekKey);
  for (const dims of BANNER_AB_DIMENSION_SETS) {
    try {
      const [response] = await client.runReport({
        property: `properties/${GA4_PROPERTY_ID}`,
        dateRanges: [{ startDate, endDate }],
        dimensions: dims.map((name) => ({ name })),
        metrics: [{ name: "eventCount" }],
        dimensionFilter: {
          filter: { fieldName: "eventName", stringFilter: { value: eventName } },
        },
        limit: 10000,
      });
      const parsed = parseBannerAbRows(response.rows ?? [], dims.length);
      if (parsed.length > 0) return parsed;
    } catch (e) {
      console.error(`[GA4] banner breakdown (${eventName}, dims=${dims.length}):`, e);
    }
  }
  return [];
}

export type BannerAbVariantMetrics = {
  copy_variant: string;
  variant_label: string;
  impressions: number;
  clicks: number;
  ctr: number | null;
  prev_impressions: number;
  prev_clicks: number;
  impressions_wow: number | null;
  clicks_wow: number | null;
};

export type BannerAbAdMetrics = {
  ad_id: string;
  ad_name: string;
  placement: string;
  placement_label: string;
  banner_copy_mode: string;
  variants: BannerAbVariantMetrics[];
  total_impressions: number;
  total_clicks: number;
};

function variantLabel(v: string): string {
  if (v === "A") return "A안";
  if (v === "B") return "B안";
  return v;
}

function wowPct(cur: number, prev: number): number | null {
  return prev > 0 ? Math.round(((cur - prev) / prev) * 1000) / 10 : null;
}

function mergeBannerRows(
  views: BannerAbRawRow[],
  clicks: BannerAbRawRow[],
  prevViews: BannerAbRawRow[],
  prevClicks: BannerAbRawRow[],
  placement: string,
  placementLabel: string,
): BannerAbAdMetrics[] {
  type Key = string;
  const adMeta = new Map<Key, { ad_name: string; banner_copy_mode: string }>();

  const ingest = (rows: BannerAbRawRow[]) => {
    for (const r of rows) {
      const key = `${r.ad_id}|${r.banner_copy_mode || "unknown"}`;
      const prev = adMeta.get(key);
      if (!prev || (!prev.ad_name && r.ad_name)) {
        adMeta.set(key, {
          ad_name: r.ad_name || prev?.ad_name || "",
          banner_copy_mode: r.banner_copy_mode || prev?.banner_copy_mode || "",
        });
      }
    }
  };
  ingest(views);
  ingest(clicks);
  ingest(prevViews);
  ingest(prevClicks);

  const countMap = (rows: BannerAbRawRow[]) => {
    const m = new Map<string, number>();
    for (const r of rows) {
      const key = `${r.ad_id}|${r.banner_copy_mode || "unknown"}|${r.copy_variant}`;
      m.set(key, (m.get(key) ?? 0) + r.count);
    }
    return m;
  };

  const viewMap = countMap(views);
  const clickMap = countMap(clicks);
  const prevViewMap = countMap(prevViews);
  const prevClickMap = countMap(prevClicks);

  const ads: BannerAbAdMetrics[] = [];

  for (const [adKey, meta] of adMeta) {
    const [ad_id, banner_copy_mode] = adKey.split("|");
    const variants: BannerAbVariantMetrics[] = [];
    const variantSet = new Set<string>();
    for (const map of [viewMap, clickMap, prevViewMap, prevClickMap]) {
      for (const k of map.keys()) {
        if (k.startsWith(`${ad_id}|${banner_copy_mode}|`)) {
          variantSet.add(k.split("|")[2]);
        }
      }
    }

    for (const copy_variant of [...variantSet].sort()) {
      const k = `${ad_id}|${banner_copy_mode}|${copy_variant}`;
      const impressions = viewMap.get(k) ?? 0;
      const clickCount = clickMap.get(k) ?? 0;
      const prevImpressions = prevViewMap.get(k) ?? 0;
      const prevClickCount = prevClickMap.get(k) ?? 0;
      variants.push({
        copy_variant,
        variant_label: variantLabel(copy_variant),
        impressions,
        clicks: clickCount,
        ctr: placementCtr(clickCount, impressions),
        prev_impressions: prevImpressions,
        prev_clicks: prevClickCount,
        impressions_wow: wowPct(impressions, prevImpressions),
        clicks_wow: wowPct(clickCount, prevClickCount),
      });
    }

    variants.sort((a, b) => a.copy_variant.localeCompare(b.copy_variant));
    const total_impressions = variants.reduce((s, v) => s + v.impressions, 0);
    const total_clicks = variants.reduce((s, v) => s + v.clicks, 0);

    ads.push({
      ad_id,
      ad_name: meta.ad_name,
      placement,
      placement_label: placementLabel,
      banner_copy_mode,
      variants,
      total_impressions,
      total_clicks,
    });
  }

  return ads.sort((a, b) => b.total_impressions - a.total_impressions);
}

export async function fetchBannerAbReport(weekKey: string) {
  const prev = prevWeekKey(weekKey);
  const blocks = await Promise.all(
    BANNER_AB_SOURCES.map(async (src) => {
      const [views, clicks, prevViews, prevClicks] = await Promise.all([
        fetchBannerEventBreakdown(weekKey, src.view_event),
        fetchBannerEventBreakdown(weekKey, src.click_event),
        fetchBannerEventBreakdown(prev, src.view_event),
        fetchBannerEventBreakdown(prev, src.click_event),
      ]);
      return mergeBannerRows(views, clicks, prevViews, prevClicks, src.placement, src.label);
    }),
  );

  const ads = blocks.flat();
  const hasData = ads.some((a) => a.total_impressions > 0 || a.total_clicks > 0);

  return {
    ads,
    has_data: hasData,
    dimensions_required: [...BANNER_AB_DIMENSION_SETS[0]],
  };
}

type BannerUtmRawRow = {
  utm_campaign: string;
  utm_content: string;
  sessions: number;
  users: number;
};

async function fetchBannerUtmRows(weekKey: string, utmSource: string): Promise<BannerUtmRawRow[]> {
  const client = await getGa4Client();
  if (!client) return [];
  const [startDate, endDate] = getWeekDateRange(weekKey);
  try {
    const [response] = await client.runReport({
      property: `properties/${GA4_PROPERTY_ID}`,
      dateRanges: [{ startDate, endDate }],
      dimensions: [{ name: "sessionManualCampaignName" }, { name: "sessionManualAdContent" }],
      metrics: [{ name: "sessions" }, { name: "activeUsers" }],
      dimensionFilter: {
        filter: {
          fieldName: "sessionManualSource",
          stringFilter: { value: utmSource, matchType: "EXACT" },
        },
      },
      limit: 10000,
    });
    return (response.rows ?? [])
      .map((row) => ({
        utm_campaign: row.dimensionValues?.[0]?.value ?? "",
        utm_content: row.dimensionValues?.[1]?.value ?? "",
        sessions: Number(row.metricValues?.[0]?.value ?? 0),
        users: Number(row.metricValues?.[1]?.value ?? 0),
      }))
      .filter((r) => r.utm_campaign && r.utm_content && r.utm_campaign !== "(not set)" && r.utm_content !== "(not set)");
  } catch (e) {
    console.error("[GA4] banner utm rows:", e);
    return [];
  }
}

export type BannerUtmVariantMetrics = {
  utm_content: string;
  sessions: number;
  users: number;
  prev_sessions: number;
  prev_users: number;
  sessions_wow: number | null;
  users_wow: number | null;
};

export type BannerUtmCampaignMetrics = {
  utm_campaign: string;
  utm_source: string;
  variants: BannerUtmVariantMetrics[];
  total_sessions: number;
  total_users: number;
};

function mergeBannerUtmCampaigns(
  current: BannerUtmRawRow[],
  previous: BannerUtmRawRow[],
  utmSource: string,
): BannerUtmCampaignMetrics[] {
  const campaigns = new Set<string>();
  for (const r of [...current, ...previous]) campaigns.add(r.utm_campaign);

  const curMap = new Map<string, BannerUtmRawRow>();
  const prevMap = new Map<string, BannerUtmRawRow>();
  for (const r of current) curMap.set(`${r.utm_campaign}|${r.utm_content}`, r);
  for (const r of previous) prevMap.set(`${r.utm_campaign}|${r.utm_content}`, r);

  const contentsByCampaign = new Map<string, Set<string>>();
  for (const key of [...curMap.keys(), ...prevMap.keys()]) {
    const [campaign, content] = key.split("|");
    if (!contentsByCampaign.has(campaign)) contentsByCampaign.set(campaign, new Set());
    contentsByCampaign.get(campaign)!.add(content);
  }

  const result: BannerUtmCampaignMetrics[] = [];
  for (const utm_campaign of [...campaigns].sort()) {
    const contents = [...(contentsByCampaign.get(utm_campaign) ?? [])].sort();
    const variants: BannerUtmVariantMetrics[] = contents.map((utm_content) => {
      const key = `${utm_campaign}|${utm_content}`;
      const cur = curMap.get(key);
      const prev = prevMap.get(key);
      const sessions = cur?.sessions ?? 0;
      const users = cur?.users ?? 0;
      const prev_sessions = prev?.sessions ?? 0;
      const prev_users = prev?.users ?? 0;
      return {
        utm_content,
        sessions,
        users,
        prev_sessions,
        prev_users,
        sessions_wow: wowPct(sessions, prev_sessions),
        users_wow: wowPct(users, prev_users),
      };
    });
    result.push({
      utm_campaign,
      utm_source: utmSource,
      variants,
      total_sessions: variants.reduce((s, v) => s + v.sessions, 0),
      total_users: variants.reduce((s, v) => s + v.users, 0),
    });
  }

  return result.sort((a, b) => b.total_sessions - a.total_sessions);
}

export async function fetchBannerUtmReport(weekKey: string, utmSource = "banner") {
  const prev = prevWeekKey(weekKey);
  const [current, previous] = await Promise.all([
    fetchBannerUtmRows(weekKey, utmSource),
    fetchBannerUtmRows(prev, utmSource),
  ]);
  const campaigns = mergeBannerUtmCampaigns(current, previous, utmSource);
  const has_data = campaigns.some((c) => c.total_sessions > 0);
  return {
    utm_source: utmSource,
    campaigns,
    has_data,
    note: "배너 클릭 후 랜딩(utm) 유입 세션 기준입니다. 앱 내 배너 노출·CTR은 상단 「배너 A/B 비교」를 참고하세요.",
  };
}

export async function fetchCumulativeUsers(untilMonth: string) {
  const client = await getGa4Client();
  if (!client) return 0;
  const [, endDate] = getMonthDateRange(untilMonth);
  try {
    const [response] = await client.runReport({
      property: `properties/${GA4_PROPERTY_ID}`,
      dateRanges: [{ startDate: APP_LAUNCH_DATE, endDate }],
      metrics: [{ name: "totalUsers" }],
    });
    return Number(response.rows?.[0]?.metricValues?.[0]?.value ?? 0);
  } catch (e) {
    console.error("[GA4] cumulative:", e);
    return 0;
  }
}
