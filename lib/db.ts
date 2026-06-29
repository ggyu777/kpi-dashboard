import postgres from "postgres";
import * as jsonStore from "./json-store";

let sql: ReturnType<typeof postgres> | null = null;
let initialized = false;

function databaseUrl(): string | null {
  const url = (process.env.DATABASE_URL ?? process.env.SUPABASE_DB_URL ?? "").trim();
  if (!url) return null;
  return url.startsWith("postgres://") ? url.replace("postgres://", "postgresql://") : url;
}

export function usingPostgres(): boolean {
  return databaseUrl() !== null;
}

export function storageBackend(): "postgres" | "blob" | "json" {
  return jsonStore.storageLabel();
}

function getSql() {
  const url = databaseUrl();
  if (!url) throw new Error("DATABASE_URL or SUPABASE_DB_URL is not set");
  if (!sql) sql = postgres(url, { ssl: url.includes("supabase") ? "require" : undefined });
  return sql;
}

const SCHEMA_SQL = `
CREATE TABLE IF NOT EXISTS kpi_targets (week VARCHAR(16), kpi_id VARCHAR(64), target DOUBLE PRECISION, PRIMARY KEY (week, kpi_id));
CREATE TABLE IF NOT EXISTS kpi_manual_data (week VARCHAR(16), kpi_id VARCHAR(64), value DOUBLE PRECISION, PRIMARY KEY (week, kpi_id));
CREATE TABLE IF NOT EXISTS ad_conversions (week VARCHAR(16), placement VARCHAR(32), conversion_rate DOUBLE PRECISION, PRIMARY KEY (week, placement));
CREATE TABLE IF NOT EXISTS ad_placement_meta (week VARCHAR(16), placement VARCHAR(32), revenue INTEGER, note TEXT DEFAULT '', PRIMARY KEY (week, placement));
CREATE TABLE IF NOT EXISTS weekly_notes (week VARCHAR(16) PRIMARY KEY, kpi_summary TEXT DEFAULT '', project_progress TEXT DEFAULT '', next_week_strategy TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS weekly_tasks (week VARCHAR(16) PRIMARY KEY, tasks JSONB DEFAULT '[]');
CREATE TABLE IF NOT EXISTS weekly_plans (week VARCHAR(16) PRIMARY KEY, author VARCHAR(128) DEFAULT '', north_star TEXT DEFAULT '', goals JSONB DEFAULT '[]', actions JSONB DEFAULT '[]', ad_revenues JSONB DEFAULT '{}', went_well TEXT DEFAULT '', went_bad TEXT DEFAULT '', ad_note TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS monthly_plans (month VARCHAR(16) PRIMARY KEY, author VARCHAR(128) DEFAULT '', north_star TEXT DEFAULT '', mau_target INTEGER DEFAULT 0, goals JSONB DEFAULT '[]', kpt_keep TEXT DEFAULT '', kpt_problem TEXT DEFAULT '', kpt_try TEXT DEFAULT '', next_actions JSONB DEFAULT '[]', ad_revenues JSONB DEFAULT '{}');
CREATE TABLE IF NOT EXISTS monthly_feedback (month VARCHAR(16) PRIMARY KEY, feedback TEXT DEFAULT '');
`;

export async function initDb() {
  if (!usingPostgres() || initialized) return;
  const db = getSql();
  for (const stmt of SCHEMA_SQL.split(";").filter((s) => s.trim())) {
    await db.unsafe(stmt);
  }
  initialized = true;
}

export const getTargets = (week: string) => (usingPostgres() ? pgGetTargets(week) : jsonStore.getTargets(week));
export const saveTargets = (week: string, targets: Record<string, number>) =>
  usingPostgres() ? pgSaveTargets(week, targets) : jsonStore.saveTargets(week, targets);
export const getManualData = (week: string) => (usingPostgres() ? pgGetManualData(week) : jsonStore.getManualData(week));
export const saveManualData = (week: string, data: Record<string, number>) =>
  usingPostgres() ? pgSaveManualData(week, data) : jsonStore.saveManualData(week, data);
export const getAdConversions = (week: string) => (usingPostgres() ? pgGetAdConversions(week) : jsonStore.getAdConversions(week));
export const saveAdConversions = (week: string, rates: Record<string, number>) =>
  usingPostgres() ? pgSaveAdConversions(week, rates) : jsonStore.saveAdConversions(week, rates);
export const getAdPlacementMeta = (week: string) => (usingPostgres() ? pgGetAdPlacementMeta(week) : jsonStore.getAdPlacementMeta(week));
export const saveAdPlacementMetaField = (week: string, placement: string, field: string, value: unknown) =>
  usingPostgres() ? pgSaveAdPlacementMetaField(week, placement, field, value) : jsonStore.saveAdPlacementMetaField(week, placement, field, value);
export const getWeeklyNotes = (week: string) => (usingPostgres() ? pgGetWeeklyNotes(week) : jsonStore.getWeeklyNotes(week));
export const saveWeeklyNotes = (week: string, a: string, b: string, c: string) =>
  usingPostgres() ? pgSaveWeeklyNotes(week, a, b, c) : jsonStore.saveWeeklyNotes(week, a, b, c);
export const getWeeklyTasks = (week: string) => (usingPostgres() ? pgGetWeeklyTasks(week) : jsonStore.getWeeklyTasks(week));
export const saveWeeklyTasks = (week: string, tasks: Array<Record<string, unknown>>) =>
  usingPostgres() ? pgSaveWeeklyTasks(week, tasks) : jsonStore.saveWeeklyTasks(week, tasks);
export const getMonthlyFeedback = (month: string) => (usingPostgres() ? pgGetMonthlyFeedback(month) : jsonStore.getMonthlyFeedback(month));
export const saveMonthlyFeedback = (month: string, feedback: string) =>
  usingPostgres() ? pgSaveMonthlyFeedback(month, feedback) : jsonStore.saveMonthlyFeedback(month, feedback);
export const getMonthlyPlan = (month: string) => (usingPostgres() ? pgGetMonthlyPlan(month) : jsonStore.getMonthlyPlan(month));
export const saveMonthlyPlan = (month: string, data: Record<string, unknown>) =>
  usingPostgres() ? pgSaveMonthlyPlan(month, data) : jsonStore.saveMonthlyPlan(month, data);
export const getWeeklyPlan = (week: string) => (usingPostgres() ? pgGetWeeklyPlan(week) : jsonStore.getWeeklyPlan(week));
export const saveWeeklyPlan = (week: string, data: Record<string, unknown>) =>
  usingPostgres() ? pgSaveWeeklyPlan(week, data) : jsonStore.saveWeeklyPlan(week, data);
export const saveWeeklyPlanWithNotes = (
  week: string,
  planData: Record<string, unknown>,
  notes?: jsonStore.WeeklyNotesPayload,
) => (usingPostgres() ? pgSaveWeeklyPlanWithNotes(week, planData, notes) : jsonStore.saveWeeklyPlanWithNotes(week, planData, notes));

async function pgGetTargets(week: string) {
  const db = getSql();
  const rows = await db`SELECT kpi_id, target FROM kpi_targets WHERE week = ${week}`;
  return Object.fromEntries(rows.map((r) => [r.kpi_id, Number(r.target)]));
}

async function pgSaveTargets(week: string, targets: Record<string, number>) {
  const db = getSql();
  await db`DELETE FROM kpi_targets WHERE week = ${week}`;
  for (const [kpiId, target] of Object.entries(targets)) {
    await db`INSERT INTO kpi_targets (week, kpi_id, target) VALUES (${week}, ${kpiId}, ${target})`;
  }
}

async function pgGetManualData(week: string) {
  const db = getSql();
  const rows = await db`SELECT kpi_id, value FROM kpi_manual_data WHERE week = ${week}`;
  return Object.fromEntries(rows.map((r) => [r.kpi_id, Number(r.value)]));
}

async function pgSaveManualData(week: string, data: Record<string, number>) {
  const db = getSql();
  await db`DELETE FROM kpi_manual_data WHERE week = ${week}`;
  for (const [kpiId, value] of Object.entries(data)) {
    await db`INSERT INTO kpi_manual_data (week, kpi_id, value) VALUES (${week}, ${kpiId}, ${value})`;
  }
}

async function pgGetAdConversions(week: string) {
  const db = getSql();
  const rows = await db`SELECT placement, conversion_rate FROM ad_conversions WHERE week = ${week}`;
  return Object.fromEntries(rows.map((r) => [r.placement, Number(r.conversion_rate)]));
}

async function pgSaveAdConversions(week: string, rates: Record<string, number>) {
  const db = getSql();
  await db`DELETE FROM ad_conversions WHERE week = ${week}`;
  for (const [placement, rate] of Object.entries(rates)) {
    await db`INSERT INTO ad_conversions (week, placement, conversion_rate) VALUES (${week}, ${placement}, ${rate})`;
  }
}

async function pgGetAdPlacementMeta(week: string) {
  const db = getSql();
  const rows = await db`SELECT placement, revenue, note FROM ad_placement_meta WHERE week = ${week}`;
  return Object.fromEntries(rows.map((r) => [r.placement, { revenue: r.revenue, note: r.note ?? "" }]));
}

async function pgSaveAdPlacementMetaField(week: string, placement: string, field: string, value: unknown) {
  const db = getSql();
  const existing = await db`SELECT * FROM ad_placement_meta WHERE week = ${week} AND placement = ${placement}`;
  let revenue = existing[0]?.revenue ?? null;
  let note = existing[0]?.note ?? "";
  if (field === "revenue") revenue = value === null || value === "" ? null : Number(value);
  if (field === "note") note = String(value ?? "");
  await db`
    INSERT INTO ad_placement_meta (week, placement, revenue, note)
    VALUES (${week}, ${placement}, ${revenue}, ${note})
    ON CONFLICT (week, placement) DO UPDATE SET revenue = EXCLUDED.revenue, note = EXCLUDED.note
  `;
}

async function pgGetWeeklyNotes(week: string) {
  const db = getSql();
  const rows = await db`SELECT * FROM weekly_notes WHERE week = ${week}`;
  if (!rows.length) return { week, kpi_summary: "", project_progress: "", next_week_strategy: "" };
  const r = rows[0];
  return { week, kpi_summary: r.kpi_summary ?? "", project_progress: r.project_progress ?? "", next_week_strategy: r.next_week_strategy ?? "" };
}

async function pgSaveWeeklyNotes(week: string, kpiSummary: string, projectProgress: string, nextWeekStrategy: string) {
  await pgSaveWeeklyPlanWithNotes(week, {}, {
    kpi_summary: kpiSummary,
    project_progress: projectProgress,
    next_week_strategy: nextWeekStrategy,
  });
}

async function pgGetWeeklyTasks(week: string) {
  const db = getSql();
  const rows = await db`SELECT tasks FROM weekly_tasks WHERE week = ${week}`;
  return (rows[0]?.tasks as Array<Record<string, unknown>>) ?? [];
}

async function pgSaveWeeklyTasks(week: string, tasks: Array<Record<string, unknown>>) {
  const db = getSql();
  await db`INSERT INTO weekly_tasks (week, tasks) VALUES (${week}, ${db.json(tasks as never)}) ON CONFLICT (week) DO UPDATE SET tasks = EXCLUDED.tasks`;
}

async function pgGetMonthlyFeedback(month: string) {
  const db = getSql();
  const rows = await db`SELECT feedback FROM monthly_feedback WHERE month = ${month}`;
  return rows[0]?.feedback ?? "";
}

async function pgSaveMonthlyFeedback(month: string, feedback: string) {
  const db = getSql();
  await db`INSERT INTO monthly_feedback (month, feedback) VALUES (${month}, ${feedback}) ON CONFLICT (month) DO UPDATE SET feedback = EXCLUDED.feedback`;
}

async function pgGetMonthlyPlan(month: string) {
  const { defaultAdRevenues } = await import("./constants");
  const db = getSql();
  const rows = await db`SELECT * FROM monthly_plans WHERE month = ${month}`;
  if (!rows.length) {
    return { month, author: "", north_star: "", mau_target: 0, goals: [], kpt_keep: "", kpt_problem: "", kpt_try: "", next_actions: [], ad_revenues: defaultAdRevenues() };
  }
  const r = rows[0];
  return {
    month, author: r.author ?? "", north_star: r.north_star ?? "", mau_target: r.mau_target ?? 0,
    goals: r.goals ?? [], kpt_keep: r.kpt_keep ?? "", kpt_problem: r.kpt_problem ?? "", kpt_try: r.kpt_try ?? "",
    next_actions: r.next_actions ?? [], ad_revenues: { ...defaultAdRevenues(), ...(r.ad_revenues as Record<string, number>) },
  };
}

async function pgSaveMonthlyPlan(month: string, data: Record<string, unknown>) {
  const db = getSql();
  await db`
    INSERT INTO monthly_plans (month, author, north_star, mau_target, goals, kpt_keep, kpt_problem, kpt_try, next_actions, ad_revenues)
    VALUES (${month}, ${String(data.author ?? "")}, ${String(data.north_star ?? "")}, ${Number(data.mau_target ?? 0)},
      ${db.json((data.goals ?? []) as never)}, ${String(data.kpt_keep ?? "")}, ${String(data.kpt_problem ?? "")}, ${String(data.kpt_try ?? "")},
      ${db.json((data.next_actions ?? []) as never)}, ${db.json((data.ad_revenues ?? {}) as never)})
    ON CONFLICT (month) DO UPDATE SET author = EXCLUDED.author, north_star = EXCLUDED.north_star, mau_target = EXCLUDED.mau_target,
      goals = EXCLUDED.goals, kpt_keep = EXCLUDED.kpt_keep, kpt_problem = EXCLUDED.kpt_problem, kpt_try = EXCLUDED.kpt_try,
      next_actions = EXCLUDED.next_actions, ad_revenues = EXCLUDED.ad_revenues
  `;
}

async function pgGetWeeklyPlan(week: string) {
  const { defaultAdRevenues } = await import("./constants");
  const db = getSql();
  const rows = await db`SELECT * FROM weekly_plans WHERE week = ${week}`;
  if (!rows.length) return { week, author: "", north_star: "", goals: [], actions: [], ad_revenues: defaultAdRevenues(), went_well: "", went_bad: "", ad_note: "" };
  const r = rows[0];
  return { week, author: r.author ?? "", north_star: r.north_star ?? "", goals: r.goals ?? [], actions: r.actions ?? [], ad_revenues: { ...defaultAdRevenues(), ...(r.ad_revenues as Record<string, number>) }, went_well: r.went_well ?? "", went_bad: r.went_bad ?? "", ad_note: r.ad_note ?? "" };
}

async function pgSaveWeeklyPlan(week: string, data: Record<string, unknown>) {
  const cleaned = { ...data };
  delete cleaned.week;
  delete cleaned.kpi_summary;
  delete cleaned.project_progress;
  delete cleaned.next_week_strategy;
  await pgSaveWeeklyPlanWithNotes(week, cleaned);
}

async function pgSaveWeeklyPlanWithNotes(
  week: string,
  planData: Record<string, unknown>,
  notes?: jsonStore.WeeklyNotesPayload,
) {
  const db = getSql();
  const planKeys = ["author", "north_star", "goals", "actions", "ad_revenues", "went_well", "went_bad", "ad_note"] as const;
  const touchesPlan = planKeys.some((k) => k in planData);

  await db.begin(async (sql) => {
    if (touchesPlan) {
      await sql`
        INSERT INTO weekly_plans (week, author, north_star, goals, actions, ad_revenues, went_well, went_bad, ad_note)
        VALUES (${week}, ${String(planData.author ?? "")}, ${String(planData.north_star ?? "")}, ${sql.json((planData.goals ?? []) as never)}, ${sql.json((planData.actions ?? []) as never)}, ${sql.json((planData.ad_revenues ?? {}) as never)}, ${String(planData.went_well ?? "")}, ${String(planData.went_bad ?? "")}, ${String(planData.ad_note ?? "")})
        ON CONFLICT (week) DO UPDATE SET author = EXCLUDED.author, north_star = EXCLUDED.north_star, goals = EXCLUDED.goals, actions = EXCLUDED.actions, ad_revenues = EXCLUDED.ad_revenues, went_well = EXCLUDED.went_well, went_bad = EXCLUDED.went_bad, ad_note = EXCLUDED.ad_note
      `;
    }
    if (notes) {
      await sql`
        INSERT INTO weekly_notes (week, kpi_summary, project_progress, next_week_strategy)
        VALUES (${week}, ${notes.kpi_summary}, ${notes.project_progress}, ${notes.next_week_strategy})
        ON CONFLICT (week) DO UPDATE SET kpi_summary = EXCLUDED.kpi_summary, project_progress = EXCLUDED.project_progress, next_week_strategy = EXCLUDED.next_week_strategy
      `;
    }
  });
}
