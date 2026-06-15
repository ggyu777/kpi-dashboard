/**
 * 로컬 Postgres → data/kpi-store.json보내기
 * 사용: DATABASE_URL=postgresql://... npx tsx scripts/export-pg-to-json.ts
 */
import fs from "fs";
import path from "path";
import postgres from "postgres";
import type { KpiStore } from "../lib/json-store";

const url = process.env.DATABASE_URL?.trim();
if (!url) {
  console.error("DATABASE_URL 필요");
  process.exit(1);
}

async function main() {
const sql = postgres(url);
const out = path.join(process.cwd(), "data", "kpi-store.json");

const store: KpiStore = {
  targets: (await sql`SELECT week, kpi_id, target FROM kpi_targets`).map((r) => ({
    week: r.week,
    kpi_id: r.kpi_id,
    target: Number(r.target),
  })),
  manual_data: (await sql`SELECT week, kpi_id, value FROM kpi_manual_data`).map((r) => ({
    week: r.week,
    kpi_id: r.kpi_id,
    value: Number(r.value),
  })),
  ad_conversions: (await sql`SELECT week, placement, conversion_rate FROM ad_conversions`).map((r) => ({
    week: r.week,
    placement: r.placement,
    conversion_rate: Number(r.conversion_rate),
  })),
  ad_placement_meta: (await sql`SELECT week, placement, revenue, note FROM ad_placement_meta`).map((r) => ({
    week: r.week,
    placement: r.placement,
    revenue: r.revenue == null ? null : Number(r.revenue),
    note: r.note ?? "",
  })),
  weekly_notes: (await sql`SELECT week, kpi_summary, project_progress, next_week_strategy FROM weekly_notes`).map(
    (r) => ({
      week: r.week,
      kpi_summary: r.kpi_summary ?? "",
      project_progress: r.project_progress ?? "",
      next_week_strategy: r.next_week_strategy ?? "",
    }),
  ),
  weekly_tasks: (await sql`SELECT week, tasks FROM weekly_tasks`).map((r) => ({
    week: r.week,
    tasks: (r.tasks as Array<Record<string, unknown>>) ?? [],
  })),
  weekly_plans: (await sql`SELECT * FROM weekly_plans`).map((r) => ({
    week: r.week,
    author: r.author ?? "",
    north_star: r.north_star ?? "",
    goals: r.goals ?? [],
    actions: r.actions ?? [],
    ad_revenues: r.ad_revenues ?? {},
  })),
  monthly_plans: (await sql`SELECT * FROM monthly_plans`).map((r) => ({
    month: r.month,
    author: r.author ?? "",
    north_star: r.north_star ?? "",
    mau_target: Number(r.mau_target ?? 0),
    goals: r.goals ?? [],
    kpt_keep: r.kpt_keep ?? "",
    kpt_problem: r.kpt_problem ?? "",
    kpt_try: r.kpt_try ?? "",
    next_actions: r.next_actions ?? [],
    ad_revenues: r.ad_revenues ?? {},
  })),
  monthly_feedback: (await sql`SELECT month, feedback FROM monthly_feedback`).map((r) => ({
    month: r.month,
    feedback: r.feedback ?? "",
  })),
};

await sql.end();
fs.mkdirSync(path.dirname(out), { recursive: true });
fs.writeFileSync(out, JSON.stringify(store, null, 2), "utf8");
console.log("exported:", out);
console.log(
  "counts:",
  Object.fromEntries(
    Object.entries(store).map(([k, v]) => [k, Array.isArray(v) ? v.length : 0]),
  ),
);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
