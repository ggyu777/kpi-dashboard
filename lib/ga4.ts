import { BetaAnalyticsDataClient } from "@google-analytics/data";
import { JWT, OAuth2Client } from "google-auth-library";
import path from "path";
import fs from "fs";
import {
  CLICK_EVENT_MAP,
  GA4_PROPERTY_ID,
  IMPRESSION_EVENT_MAP,
  KPI_GA4_METRIC,
  APP_LAUNCH_DATE,
} from "./constants";
import { getMonthDateRange } from "./month";
import { getWeekDateRange } from "./week";

const GA4_SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"];
const TOKEN_FILE = path.join(process.cwd(), "token.json");

let clientPromise: Promise<BetaAnalyticsDataClient | null> | null = null;

async function getGa4Client(): Promise<BetaAnalyticsDataClient | null> {
  if (!clientPromise) clientPromise = createClient();
  return clientPromise;
}

async function createClient(): Promise<BetaAnalyticsDataClient | null> {
  try {
    if (fs.existsSync(TOKEN_FILE)) {
      const raw = JSON.parse(fs.readFileSync(TOKEN_FILE, "utf8"));
      const oauth = new OAuth2Client();
      oauth.setCredentials(raw);
      if (raw.expiry_date && raw.expiry_date < Date.now()) {
        const { credentials } = await oauth.refreshAccessToken();
        oauth.setCredentials(credentials);
        fs.writeFileSync(TOKEN_FILE, JSON.stringify(credentials));
      }
      return new BetaAnalyticsDataClient({ auth: oauth as never });
    }

    const tokenJson = process.env.GOOGLE_TOKEN_JSON?.trim();
    if (tokenJson) {
      const oauth = new OAuth2Client();
      oauth.setCredentials(JSON.parse(tokenJson));
      if (oauth.credentials.expiry_date && oauth.credentials.expiry_date < Date.now()) {
        await oauth.refreshAccessToken();
      }
      return new BetaAnalyticsDataClient({ auth: oauth as never });
    }

    const credsJson = process.env.GOOGLE_CREDENTIALS_JSON?.trim();
    if (credsJson) {
      const info = JSON.parse(credsJson);
      const auth = new JWT({
        email: info.client_email,
        key: info.private_key,
        scopes: GA4_SCOPES,
      });
      return new BetaAnalyticsDataClient({ auth: auth as never });
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
