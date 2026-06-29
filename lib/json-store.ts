import fs from "fs";
import path from "path";
import { defaultAdRevenues } from "./constants";

const BLOB_PATHNAME = "kpi-store.json";
const LOCAL_FILE = path.join(process.cwd(), "data", "kpi-store.json");
const STORE_WRITE_RETRIES = 6;

export type KpiStore = {
  targets: Array<{ week: string; kpi_id: string; target: number }>;
  manual_data: Array<{ week: string; kpi_id: string; value: number }>;
  ad_conversions: Array<{ week: string; placement: string; conversion_rate: number }>;
  ad_placement_meta: Array<{ week: string; placement: string; revenue: number | null; note: string }>;
  weekly_notes: Array<{ week: string; kpi_summary: string; project_progress: string; next_week_strategy: string }>;
  weekly_tasks: Array<{ week: string; tasks: Array<Record<string, unknown>> }>;
  weekly_plans: Array<Record<string, unknown>>;
  monthly_plans: Array<Record<string, unknown>>;
  monthly_feedback: Array<{ month: string; feedback: string }>;
};

function emptyStore(): KpiStore {
  return {
    targets: [],
    manual_data: [],
    ad_conversions: [],
    ad_placement_meta: [],
    weekly_notes: [],
    weekly_tasks: [],
    weekly_plans: [],
    monthly_plans: [],
    monthly_feedback: [],
  };
}

function hasBlobBackend(): boolean {
  return !!(process.env.BLOB_READ_WRITE_TOKEN?.trim() || process.env.BLOB_STORE_ID?.trim());
}

export function usingBlob(): boolean {
  return !process.env.DATABASE_URL?.trim() && !process.env.SUPABASE_DB_URL?.trim() && hasBlobBackend();
}

export function usingLocalJson(): boolean {
  return !process.env.DATABASE_URL?.trim() && !process.env.SUPABASE_DB_URL?.trim() && !usingBlob();
}

export function storageLabel(): "postgres" | "blob" | "json" {
  if (process.env.DATABASE_URL?.trim() || process.env.SUPABASE_DB_URL?.trim()) return "postgres";
  if (usingBlob()) return "blob";
  return "json";
}

function isPreconditionFailed(e: unknown): boolean {
  return e instanceof Error && (e.name === "BlobPreconditionFailedError" || e.message.includes("Precondition failed"));
}

async function readBlobMeta(): Promise<{ url: string; etag: string } | null> {
  try {
    const { head } = await import("@vercel/blob");
    const meta = await head(BLOB_PATHNAME);
    if (!meta?.url) return null;
    return { url: meta.url, etag: meta.etag ?? "" };
  } catch {
    return null;
  }
}

async function readBlobEtag(): Promise<string | null> {
  const meta = await readBlobMeta();
  return meta ? meta.etag || null : null;
}

async function readBlobText(): Promise<string | null> {
  // head() + direct fetch: avoids get(useCache:false) which appends ?cache=0 and causes 400
  const meta = await readBlobMeta();
  if (!meta) return null;
  try {
    const res = await fetch(`${meta.url}?t=${Date.now()}`, { cache: "no-store" });
    return res.ok ? res.text() : null;
  } catch (e) {
    console.error("[blob] fetch failed:", e);
    return null;
  }
}

async function readRaw(): Promise<string | null> {
  if (usingBlob()) {
    try {
      return await readBlobText();
    } catch (e) {
      console.error("[blob] read failed:", e);
      return null;
    }
  }
  if (!fs.existsSync(LOCAL_FILE)) return null;
  return fs.readFileSync(LOCAL_FILE, "utf8");
}

async function writeRaw(content: string, etag?: string | null): Promise<void> {
  if (usingBlob()) {
    const { put } = await import("@vercel/blob");
    await put(BLOB_PATHNAME, content, {
      access: "public",
      addRandomSuffix: false,
      allowOverwrite: true,
      cacheControlMaxAge: 0, // no CDN caching — always fetch from origin
      contentType: "application/json",
      ...(etag ? { ifMatch: etag } : {}),
    });
    return;
  }
  fs.mkdirSync(path.dirname(LOCAL_FILE), { recursive: true });
  const tmp = `${LOCAL_FILE}.tmp`;
  fs.writeFileSync(tmp, content, "utf8");
  fs.renameSync(tmp, LOCAL_FILE);
}

export async function readStore(): Promise<KpiStore> {
  const raw = await readRaw();
  if (!raw) return emptyStore();
  try {
    const store = JSON.parse(raw) as Partial<KpiStore>;
    return { ...emptyStore(), ...store };
  } catch (e) {
    console.error("[store] JSON parse failed:", e);
    if (!usingBlob() && fs.existsSync(LOCAL_FILE)) {
      fs.copyFileSync(LOCAL_FILE, `${LOCAL_FILE}.bak`);
    }
    return emptyStore();
  }
}

async function updateStore(mutator: (store: KpiStore) => void): Promise<void> {
  if (!usingBlob()) {
    const store = await readStore();
    mutator(store);
    await writeRaw(JSON.stringify(store, null, 2));
    return;
  }
  for (let attempt = 0; attempt < STORE_WRITE_RETRIES; attempt++) {
    if (attempt > 0) await new Promise((r) => setTimeout(r, 200 * attempt));
    const raw = await readRaw();
    const etag = await readBlobEtag();
    if (etag && !raw) {
      continue;
    }
    const store = raw
      ? ({ ...emptyStore(), ...(JSON.parse(raw) as Partial<KpiStore>) } as KpiStore)
      : emptyStore();
    mutator(store);
    try {
      await writeRaw(JSON.stringify(store, null, 2), etag);
      return;
    } catch (e) {
      if (!isPreconditionFailed(e) || attempt === STORE_WRITE_RETRIES - 1) throw e;
    }
  }
  throw new Error("store write failed after retries");
}

export async function writeStore(store: KpiStore, opts?: { force?: boolean }): Promise<void> {
  if (usingBlob()) {
    if (!opts?.force) {
      const etag = await readBlobEtag();
      if (etag) {
        const raw = await readRaw();
        if (!raw) throw new Error("refusing full store write: blob exists but read failed");
      }
      await writeRaw(JSON.stringify(store, null, 2), etag);
      return;
    }
    await writeRaw(JSON.stringify(store, null, 2));
    return;
  }
  await writeRaw(JSON.stringify(store, null, 2));
}

export async function getTargets(week: string) {
  const store = await readStore();
  return Object.fromEntries(store.targets.filter((t) => t.week === week).map((t) => [t.kpi_id, t.target]));
}

export async function saveTargets(week: string, targets: Record<string, number>) {
  await updateStore((store) => {
    store.targets = store.targets.filter((t) => t.week !== week);
    for (const [kpi_id, target] of Object.entries(targets)) {
      store.targets.push({ week, kpi_id, target });
    }
  });
}

export async function getManualData(week: string) {
  const store = await readStore();
  return Object.fromEntries(store.manual_data.filter((d) => d.week === week).map((d) => [d.kpi_id, d.value]));
}

export async function saveManualData(week: string, data: Record<string, number>) {
  await updateStore((store) => {
    store.manual_data = store.manual_data.filter((d) => d.week !== week);
    for (const [kpi_id, value] of Object.entries(data)) {
      store.manual_data.push({ week, kpi_id, value });
    }
  });
}

export async function getAdConversions(week: string) {
  const store = await readStore();
  return Object.fromEntries(
    store.ad_conversions.filter((r) => r.week === week).map((r) => [r.placement, r.conversion_rate]),
  );
}

export async function saveAdConversions(week: string, rates: Record<string, number>) {
  await updateStore((store) => {
    store.ad_conversions = store.ad_conversions.filter((r) => r.week !== week);
    for (const [placement, conversion_rate] of Object.entries(rates)) {
      store.ad_conversions.push({ week, placement, conversion_rate });
    }
  });
}

export async function getAdPlacementMeta(week: string) {
  const store = await readStore();
  const out: Record<string, { revenue: number | null; note: string }> = {};
  for (const r of store.ad_placement_meta.filter((x) => x.week === week)) {
    out[r.placement] = { revenue: r.revenue, note: r.note ?? "" };
  }
  return out;
}

export async function saveAdPlacementMetaField(week: string, placement: string, field: string, value: unknown) {
  await updateStore((store) => {
    let row = store.ad_placement_meta.find((r) => r.week === week && r.placement === placement);
    if (!row) {
      row = { week, placement, revenue: null, note: "" };
      store.ad_placement_meta.push(row);
    }
    if (field === "revenue") row.revenue = value === null || value === "" ? null : Number(value);
    if (field === "note") row.note = String(value ?? "");
  });
}

export async function getWeeklyNotes(week: string) {
  const store = await readStore();
  const note = store.weekly_notes.find((n) => n.week === week);
  return note ?? { week, kpi_summary: "", project_progress: "", next_week_strategy: "" };
}

export type WeeklyNotesPayload = {
  kpi_summary: string;
  project_progress: string;
  next_week_strategy: string;
};

const WEEKLY_PLAN_KEYS = ["author", "north_star", "goals", "actions", "ad_revenues", "went_well", "went_bad", "ad_note"] as const;

export async function saveWeeklyPlanWithNotes(
  week: string,
  planData: Record<string, unknown>,
  notes?: WeeklyNotesPayload,
) {
  await updateStore((store) => {
    const cleaned = { ...planData };
    delete cleaned.week;
    delete cleaned.kpi_summary;
    delete cleaned.project_progress;
    delete cleaned.next_week_strategy;

    if (WEEKLY_PLAN_KEYS.some((k) => k in cleaned)) {
      const existing = store.weekly_plans.find((p) => p.week === week) ?? {};
      store.weekly_plans = store.weekly_plans.filter((p) => p.week !== week);
      store.weekly_plans.push({ ...existing, ...cleaned, week });
    }

    if (notes) {
      store.weekly_notes = store.weekly_notes.filter((n) => n.week !== week);
      store.weekly_notes.push({ week, ...notes });
    }
  });
}

export async function saveWeeklyNotes(week: string, kpiSummary: string, projectProgress: string, nextWeekStrategy: string) {
  await saveWeeklyPlanWithNotes(week, {}, {
    kpi_summary: kpiSummary,
    project_progress: projectProgress,
    next_week_strategy: nextWeekStrategy,
  });
}

export async function getWeeklyTasks(week: string) {
  const store = await readStore();
  return store.weekly_tasks.find((t) => t.week === week)?.tasks ?? [];
}

export async function saveWeeklyTasks(week: string, tasks: Array<Record<string, unknown>>) {
  await updateStore((store) => {
    store.weekly_tasks = store.weekly_tasks.filter((t) => t.week !== week);
    store.weekly_tasks.push({ week, tasks });
  });
}

export async function getMonthlyFeedback(month: string) {
  const store = await readStore();
  return store.monthly_feedback.find((f) => f.month === month)?.feedback ?? "";
}

export async function saveMonthlyFeedback(month: string, feedback: string) {
  await updateStore((store) => {
    store.monthly_feedback = store.monthly_feedback.filter((f) => f.month !== month);
    store.monthly_feedback.push({ month, feedback });
  });
}

export async function getMonthlyPlan(month: string) {
  const store = await readStore();
  const plan = store.monthly_plans.find((p) => p.month === month);
  if (plan) return plan;
  return {
    month,
    author: "",
    north_star: "",
    mau_target: 0,
    goals: [],
    kpt_keep: "",
    kpt_problem: "",
    kpt_try: "",
    next_actions: [],
    ad_revenues: defaultAdRevenues(),
  };
}

export async function saveMonthlyPlan(month: string, data: Record<string, unknown>) {
  await updateStore((store) => {
    const existing = store.monthly_plans.find((p) => p.month === month) ?? {};
    store.monthly_plans = store.monthly_plans.filter((p) => p.month !== month);
    store.monthly_plans.push({ ...existing, ...data, month });
  });
}

export async function getWeeklyPlan(week: string) {
  const store = await readStore();
  const plan = store.weekly_plans.find((p) => p.week === week);
  if (plan) return plan;
  return { week, author: "", north_star: "", goals: [], actions: [], ad_revenues: defaultAdRevenues() };
}

export async function saveWeeklyPlan(week: string, data: Record<string, unknown>) {
  const cleaned = { ...data };
  delete cleaned.week;
  delete cleaned.kpi_summary;
  delete cleaned.project_progress;
  delete cleaned.next_week_strategy;
  await saveWeeklyPlanWithNotes(week, cleaned);
}
