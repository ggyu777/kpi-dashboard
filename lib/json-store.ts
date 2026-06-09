import fs from "fs";
import path from "path";
import { defaultAdRevenues } from "./constants";

const BLOB_PATHNAME = "kpi-store.json";
const LOCAL_FILE = path.join(process.cwd(), "data", "kpi-store.json");

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

export function usingBlob(): boolean {
  return !process.env.DATABASE_URL?.trim() && !process.env.SUPABASE_DB_URL?.trim() && !!process.env.BLOB_READ_WRITE_TOKEN?.trim();
}

export function usingLocalJson(): boolean {
  return !process.env.DATABASE_URL?.trim() && !process.env.SUPABASE_DB_URL?.trim() && !usingBlob();
}

export function storageLabel(): "postgres" | "blob" | "json" {
  if (process.env.DATABASE_URL?.trim() || process.env.SUPABASE_DB_URL?.trim()) return "postgres";
  if (usingBlob()) return "blob";
  return "json";
}

async function readRaw(): Promise<string | null> {
  if (usingBlob()) {
    const { list } = await import("@vercel/blob");
    const { blobs } = await list({ prefix: BLOB_PATHNAME, limit: 1 });
    const blob = blobs.find((b) => b.pathname === BLOB_PATHNAME);
    if (!blob) return null;
    const res = await fetch(blob.downloadUrl);
    return res.ok ? res.text() : null;
  }
  if (!fs.existsSync(LOCAL_FILE)) return null;
  return fs.readFileSync(LOCAL_FILE, "utf8");
}

async function writeRaw(content: string): Promise<void> {
  if (usingBlob()) {
    const { del, list, put } = await import("@vercel/blob");
    const { blobs } = await list({ prefix: BLOB_PATHNAME, limit: 1 });
    const existing = blobs.find((b) => b.pathname === BLOB_PATHNAME);
    if (existing) await del(existing.url);
    await put(BLOB_PATHNAME, content, { access: "public", addRandomSuffix: false });
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

export async function writeStore(store: KpiStore): Promise<void> {
  await writeRaw(JSON.stringify(store, null, 2));
}

export async function getTargets(week: string) {
  const store = await readStore();
  return Object.fromEntries(store.targets.filter((t) => t.week === week).map((t) => [t.kpi_id, t.target]));
}

export async function saveTargets(week: string, targets: Record<string, number>) {
  const store = await readStore();
  store.targets = store.targets.filter((t) => t.week !== week);
  for (const [kpi_id, target] of Object.entries(targets)) {
    store.targets.push({ week, kpi_id, target });
  }
  await writeStore(store);
}

export async function getManualData(week: string) {
  const store = await readStore();
  return Object.fromEntries(store.manual_data.filter((d) => d.week === week).map((d) => [d.kpi_id, d.value]));
}

export async function saveManualData(week: string, data: Record<string, number>) {
  const store = await readStore();
  store.manual_data = store.manual_data.filter((d) => d.week !== week);
  for (const [kpi_id, value] of Object.entries(data)) {
    store.manual_data.push({ week, kpi_id, value });
  }
  await writeStore(store);
}

export async function getAdConversions(week: string) {
  const store = await readStore();
  return Object.fromEntries(
    store.ad_conversions.filter((r) => r.week === week).map((r) => [r.placement, r.conversion_rate]),
  );
}

export async function saveAdConversions(week: string, rates: Record<string, number>) {
  const store = await readStore();
  store.ad_conversions = store.ad_conversions.filter((r) => r.week !== week);
  for (const [placement, conversion_rate] of Object.entries(rates)) {
    store.ad_conversions.push({ week, placement, conversion_rate });
  }
  await writeStore(store);
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
  const store = await readStore();
  let row = store.ad_placement_meta.find((r) => r.week === week && r.placement === placement);
  if (!row) {
    row = { week, placement, revenue: null, note: "" };
    store.ad_placement_meta.push(row);
  }
  if (field === "revenue") row.revenue = value === null || value === "" ? null : Number(value);
  if (field === "note") row.note = String(value ?? "");
  await writeStore(store);
}

export async function getWeeklyNotes(week: string) {
  const store = await readStore();
  const note = store.weekly_notes.find((n) => n.week === week);
  return note ?? { week, kpi_summary: "", project_progress: "", next_week_strategy: "" };
}

export async function saveWeeklyNotes(week: string, kpiSummary: string, projectProgress: string, nextWeekStrategy: string) {
  const store = await readStore();
  store.weekly_notes = store.weekly_notes.filter((n) => n.week !== week);
  store.weekly_notes.push({ week, kpi_summary: kpiSummary, project_progress: projectProgress, next_week_strategy: nextWeekStrategy });
  await writeStore(store);
}

export async function getWeeklyTasks(week: string) {
  const store = await readStore();
  return store.weekly_tasks.find((t) => t.week === week)?.tasks ?? [];
}

export async function saveWeeklyTasks(week: string, tasks: Array<Record<string, unknown>>) {
  const store = await readStore();
  store.weekly_tasks = store.weekly_tasks.filter((t) => t.week !== week);
  store.weekly_tasks.push({ week, tasks });
  await writeStore(store);
}

export async function getMonthlyFeedback(month: string) {
  const store = await readStore();
  return store.monthly_feedback.find((f) => f.month === month)?.feedback ?? "";
}

export async function saveMonthlyFeedback(month: string, feedback: string) {
  const store = await readStore();
  store.monthly_feedback = store.monthly_feedback.filter((f) => f.month !== month);
  store.monthly_feedback.push({ month, feedback });
  await writeStore(store);
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
  const store = await readStore();
  store.monthly_plans = store.monthly_plans.filter((p) => p.month !== month);
  store.monthly_plans.push({ ...data, month });
  await writeStore(store);
}

export async function getWeeklyPlan(week: string) {
  const store = await readStore();
  const plan = store.weekly_plans.find((p) => p.week === week);
  if (plan) return plan;
  return { week, author: "", north_star: "", goals: [], actions: [], ad_revenues: defaultAdRevenues() };
}

export async function saveWeeklyPlan(week: string, data: Record<string, unknown>) {
  const store = await readStore();
  store.weekly_plans = store.weekly_plans.filter((p) => p.week !== week);
  store.weekly_plans.push({ ...data, week });
  await writeStore(store);
}
