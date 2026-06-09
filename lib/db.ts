import postgres from "postgres";
import { defaultAdRevenues } from "./constants";

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
CREATE TABLE IF NOT EXISTS weekly_plans (week VARCHAR(16) PRIMARY KEY, author VARCHAR(128) DEFAULT '', north_star TEXT DEFAULT '', goals JSONB DEFAULT '[]', actions JSONB DEFAULT '[]', ad_revenues JSONB DEFAULT '{}');
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

export async function getTargets(week: string) {
  const db = getSql();
  const rows = await db`SELECT kpi_id, target FROM kpi_targets WHERE week = ${week}`;
  return Object.fromEntries(rows.map((r) => [r.kpi_id, Number(r.target)]));
}

export async function saveTargets(week: string, targets: Record<string, number>) {
  const db = getSql();
  await db`DELETE FROM kpi_targets WHERE week = ${week}`;
  for (const [kpiId, target] of Object.entries(targets)) {
    await db`INSERT INTO kpi_targets (week, kpi_id, target) VALUES (${week}, ${kpiId}, ${target})`;
  }
}

export async function getManualData(week: string) {
  const db = getSql();
  const rows = await db`SELECT kpi_id, value FROM kpi_manual_data WHERE week = ${week}`;
  return Object.fromEntries(rows.map((r) => [r.kpi_id, Number(r.value)]));
}

export async function saveManualData(week: string, data: Record<string, number>) {
  const db = getSql();
  await db`DELETE FROM kpi_manual_data WHERE week = ${week}`;
  for (const [kpiId, value] of Object.entries(data)) {
    await db`INSERT INTO kpi_manual_data (week, kpi_id, value) VALUES (${week}, ${kpiId}, ${value})`;
  }
}

export async function getAdConversions(week: string) {
  const db = getSql();
  const rows = await db`SELECT placement, conversion_rate FROM ad_conversions WHERE week = ${week}`;
  return Object.fromEntries(rows.map((r) => [r.placement, Number(r.conversion_rate)]));
}

export async function saveAdConversions(week: string, rates: Record<string, number>) {
  const db = getSql();
  await db`DELETE FROM ad_conversions WHERE week = ${week}`;
  for (const [placement, rate] of Object.entries(rates)) {
    await db`INSERT INTO ad_conversions (week, placement, conversion_rate) VALUES (${week}, ${placement}, ${rate})`;
  }
}

export async function getAdPlacementMeta(week: string) {
  const db = getSql();
  const rows = await db`SELECT placement, revenue, note FROM ad_placement_meta WHERE week = ${week}`;
  return Object.fromEntries(
    rows.map((r) => [r.placement, { revenue: r.revenue, note: r.note ?? "" }]),
  );
}

export async function saveAdPlacementMetaField(
  week: string,
  placement: string,
  field: string,
  value: unknown,
) {
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

export async function getWeeklyNotes(week: string) {
  const db = getSql();
  const rows = await db`SELECT * FROM weekly_notes WHERE week = ${week}`;
  if (!rows.length) return { week, kpi_summary: "", project_progress: "", next_week_strategy: "" };
  const r = rows[0];
  return {
    week,
    kpi_summary: r.kpi_summary ?? "",
    project_progress: r.project_progress ?? "",
    next_week_strategy: r.next_week_strategy ?? "",
  };
}

export async function saveWeeklyNotes(
  week: string,
  kpiSummary: string,
  projectProgress: string,
  nextWeekStrategy: string,
) {
  const db = getSql();
  await db`
    INSERT INTO weekly_notes (week, kpi_summary, project_progress, next_week_strategy)
    VALUES (${week}, ${kpiSummary}, ${projectProgress}, ${nextWeekStrategy})
    ON CONFLICT (week) DO UPDATE SET
      kpi_summary = EXCLUDED.kpi_summary,
      project_progress = EXCLUDED.project_progress,
      next_week_strategy = EXCLUDED.next_week_strategy
  `;
}

export async function getWeeklyTasks(week: string) {
  const db = getSql();
  const rows = await db`SELECT tasks FROM weekly_tasks WHERE week = ${week}`;
  return (rows[0]?.tasks as Array<Record<string, unknown>>) ?? [];
}

export async function saveWeeklyTasks(week: string, tasks: Array<Record<string, unknown>>) {
  const db = getSql();
  await db`
    INSERT INTO weekly_tasks (week, tasks) VALUES (${week}, ${db.json(tasks as never)})
    ON CONFLICT (week) DO UPDATE SET tasks = EXCLUDED.tasks
  `;
}

export async function getMonthlyFeedback(month: string) {
  const db = getSql();
  const rows = await db`SELECT feedback FROM monthly_feedback WHERE month = ${month}`;
  return rows[0]?.feedback ?? "";
}

export async function saveMonthlyFeedback(month: string, feedback: string) {
  const db = getSql();
  await db`
    INSERT INTO monthly_feedback (month, feedback) VALUES (${month}, ${feedback})
    ON CONFLICT (month) DO UPDATE SET feedback = EXCLUDED.feedback
  `;
}

export async function getMonthlyPlan(month: string) {
  const db = getSql();
  const rows = await db`SELECT * FROM monthly_plans WHERE month = ${month}`;
  if (!rows.length) {
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
  const r = rows[0];
  return {
    month,
    author: r.author ?? "",
    north_star: r.north_star ?? "",
    mau_target: r.mau_target ?? 0,
    goals: r.goals ?? [],
    kpt_keep: r.kpt_keep ?? "",
    kpt_problem: r.kpt_problem ?? "",
    kpt_try: r.kpt_try ?? "",
    next_actions: r.next_actions ?? [],
    ad_revenues: { ...defaultAdRevenues(), ...(r.ad_revenues as Record<string, number>) },
  };
}

export async function saveMonthlyPlan(month: string, data: Record<string, unknown>) {
  const db = getSql();
  await db`
    INSERT INTO monthly_plans (month, author, north_star, mau_target, goals, kpt_keep, kpt_problem, kpt_try, next_actions, ad_revenues)
    VALUES (
      ${month}, ${String(data.author ?? "")}, ${String(data.north_star ?? "")},
      ${Number(data.mau_target ?? 0)}, ${db.json((data.goals ?? []) as never)},
      ${String(data.kpt_keep ?? "")}, ${String(data.kpt_problem ?? "")}, ${String(data.kpt_try ?? "")},
      ${db.json((data.next_actions ?? []) as never)}, ${db.json((data.ad_revenues ?? {}) as never)}
    )
    ON CONFLICT (month) DO UPDATE SET
      author = EXCLUDED.author, north_star = EXCLUDED.north_star, mau_target = EXCLUDED.mau_target,
      goals = EXCLUDED.goals, kpt_keep = EXCLUDED.kpt_keep, kpt_problem = EXCLUDED.kpt_problem,
      kpt_try = EXCLUDED.kpt_try, next_actions = EXCLUDED.next_actions, ad_revenues = EXCLUDED.ad_revenues
  `;
}

export async function getWeeklyPlan(week: string) {
  const db = getSql();
  const rows = await db`SELECT * FROM weekly_plans WHERE week = ${week}`;
  if (!rows.length) {
    return { week, author: "", north_star: "", goals: [], actions: [], ad_revenues: defaultAdRevenues() };
  }
  const r = rows[0];
  return {
    week,
    author: r.author ?? "",
    north_star: r.north_star ?? "",
    goals: r.goals ?? [],
    actions: r.actions ?? [],
    ad_revenues: { ...defaultAdRevenues(), ...(r.ad_revenues as Record<string, number>) },
  };
}

export async function saveWeeklyPlan(week: string, data: Record<string, unknown>) {
  const db = getSql();
  await db`
    INSERT INTO weekly_plans (week, author, north_star, goals, actions, ad_revenues)
    VALUES (
      ${week}, ${String(data.author ?? "")}, ${String(data.north_star ?? "")},
      ${db.json((data.goals ?? []) as never)}, ${db.json((data.actions ?? []) as never)}, ${db.json((data.ad_revenues ?? {}) as never)}
    )
    ON CONFLICT (week) DO UPDATE SET
      author = EXCLUDED.author, north_star = EXCLUDED.north_star,
      goals = EXCLUDED.goals, actions = EXCLUDED.actions, ad_revenues = EXCLUDED.ad_revenues
  `;
}
