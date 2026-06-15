import fs from "fs";
import path from "path";
import { OAuth2Client } from "google-auth-library";
import { BetaAnalyticsDataClient } from "@google-analytics/data";

function normalizeCredentials(raw: Record<string, unknown>) {
  const creds = { ...raw } as Record<string, unknown>;
  if (!creds.access_token && creds.token) creds.access_token = creds.token;
  if (!creds.expiry_date && creds.expiry) {
    creds.expiry_date = new Date(String(creds.expiry)).getTime();
  }
  return creds;
}

async function main() {
  const tokenPath = path.join(process.cwd(), "token.json");
  const raw = JSON.parse(fs.readFileSync(tokenPath, "utf8")) as Record<string, unknown>;
  const creds = normalizeCredentials(raw);
  const oauth = new OAuth2Client(
    creds.client_id as string | undefined,
    creds.client_secret as string | undefined,
  );
  oauth.setCredentials(creds as never);
  if (oauth.credentials.expiry_date && oauth.credentials.expiry_date < Date.now()) {
    console.log("refreshing token...");
    const { credentials } = await oauth.refreshAccessToken();
    oauth.setCredentials(credentials);
    fs.writeFileSync(tokenPath, JSON.stringify({ ...raw, ...credentials }, null, 2));
  }
  const client = new BetaAnalyticsDataClient({ authClient: oauth });
  const propertyId = process.env.GA4_PROPERTY_ID ?? "410384180";
  const [res] = await client.runReport({
    property: `properties/${propertyId}`,
    dateRanges: [{ startDate: "2026-06-01", endDate: "2026-06-07" }],
    metrics: [{ name: "activeUsers" }, { name: "newUsers" }, { name: "sessions" }],
  });
  const vals = res.rows?.[0]?.metricValues?.map((v) => v.value) ?? [];
  console.log("GA4 metrics (2026-06-01~07):", vals);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
