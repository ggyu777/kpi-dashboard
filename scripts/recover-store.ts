/**
 * kpi-store.json.bak + Postgres → kpi-store.json 복구 후 Blob 업로드
 */
import fs from "fs";
import path from "path";
import postgres from "postgres";
import { put } from "@vercel/blob";
import type { KpiStore } from "../lib/json-store";

function loadEnvFile(name: string) {
  const p = path.join(process.cwd(), name);
  if (!fs.existsSync(p)) return;
  for (const line of fs.readFileSync(p, "utf8").split("\n")) {
    const m = line.match(/^([A-Z0-9_]+)=(.*)$/);
    if (!m || process.env[m[1]]) continue;
    let v = m[2];
    if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) {
      v = v.slice(1, -1);
    }
    process.env[m[1]] = v;
  }
}

function parseBakNotes24(bak: string) {
  const weekMatch = bak.match(/"week":\s*"2026-24"/);
  if (!weekMatch) return null;

  const pick = (field: string) => {
    const re = new RegExp(`"${field}":\\s*"(\\\\.|[^"\\\\])*"`, "s");
    const m = bak.match(re);
    if (!m) return "";
    try {
      return JSON.parse(`"${m[0].slice(m[0].indexOf('"', field.length + 3) + 1).replace(/^"|"$/g, "").replace(/\\"/g, '"').replace(/\\\\/g, "\\")}"`);
    } catch {
      const raw = m[0].replace(new RegExp(`^"${field}":\\s*`), "").replace(/^"|"$/g, "");
      return raw.replace(/\\"/g, '"').replace(/\\\\/g, "\\");
    }
  };

  const fieldRe = (name: string) => {
    const start = bak.indexOf(`"${name}":`);
    if (start < 0) return "";
    let i = bak.indexOf('"', start + name.length + 3) + 1;
    let out = "";
    while (i < bak.length) {
      const ch = bak[i];
      if (ch === "\\") {
        out += bak[i + 1] ?? "";
        i += 2;
        continue;
      }
      if (ch === '"') break;
      out += ch;
      i++;
    }
    return out;
  };

  return {
    week: "2026-24",
    kpi_summary: fieldRe("kpi_summary") || '{"ops":[{"insert":"\\n"}]}',
    project_progress: fieldRe("project_progress") || '{"ops":[{"insert":"\\n"}]}',
    next_week_strategy: fieldRe("next_week_strategy") || '{"ops":[{"insert":"\\n"}]}',
  };
}

function mergeNotes(store: KpiStore, recovered: { week: string; kpi_summary: string; project_progress: string; next_week_strategy: string }) {
  const idx = store.weekly_notes.findIndex((n) => n.week === recovered.week);
  const hasContent = (s: string) => s && !s.includes('{"ops":[{"insert":"\\n"}]}') && s.length > 30;
  if (idx >= 0) {
    const cur = store.weekly_notes[idx];
    store.weekly_notes[idx] = {
      week: recovered.week,
      kpi_summary: hasContent(recovered.kpi_summary) ? recovered.kpi_summary : cur.kpi_summary,
      project_progress: hasContent(recovered.project_progress) ? recovered.project_progress : cur.project_progress,
      next_week_strategy: hasContent(recovered.next_week_strategy) ? recovered.next_week_strategy : cur.next_week_strategy,
    };
  } else {
    store.weekly_notes.push(recovered);
  }
  store.weekly_notes.sort((a, b) => a.week.localeCompare(b.week));
}

async function mergeFromPostgres(store: KpiStore, url: string) {
  const sql = postgres(url);
  try {
    for (const row of await sql`SELECT * FROM weekly_plans`) {
      const week = row.week as string;
      if (store.weekly_plans.some((p) => p.week === week)) continue;
      store.weekly_plans.push({
        week,
        author: (row.author as string) ?? "",
        north_star: (row.north_star as string) ?? "",
        goals: (row.goals as unknown[]) ?? [],
        actions: (row.actions as unknown[]) ?? [],
        ad_revenues: (row.ad_revenues as Record<string, number>) ?? {},
      });
    }
    for (const row of await sql`SELECT * FROM monthly_plans`) {
      const month = row.month as string;
      if (store.monthly_plans.some((p) => p.month === month)) continue;
      store.monthly_plans.push({
        month,
        author: (row.author as string) ?? "",
        north_star: (row.north_star as string) ?? "",
        mau_target: Number(row.mau_target ?? 0),
        goals: (row.goals as unknown[]) ?? [],
        kpt_keep: (row.kpt_keep as string) ?? "",
        kpt_problem: (row.kpt_problem as string) ?? "",
        kpt_try: (row.kpt_try as string) ?? "",
        next_actions: (row.next_actions as unknown[]) ?? [],
        ad_revenues: (row.ad_revenues as Record<string, number>) ?? {},
      });
    }
    for (const row of await sql`SELECT week, kpi_summary, project_progress, next_week_strategy FROM weekly_notes`) {
      const week = row.week as string;
      const entry = {
        week,
        kpi_summary: (row.kpi_summary as string) ?? "",
        project_progress: (row.project_progress as string) ?? "",
        next_week_strategy: (row.next_week_strategy as string) ?? "",
      };
      const idx = store.weekly_notes.findIndex((n) => n.week === week);
      if (idx < 0) store.weekly_notes.push(entry);
      else {
        const cur = store.weekly_notes[idx];
        const rich = (s: string) => s && s.length > 20 && !s.includes('{"ops":[{"insert":"\\n"}]}');
        store.weekly_notes[idx] = {
          week,
          kpi_summary: rich(entry.kpi_summary) ? entry.kpi_summary : cur.kpi_summary,
          project_progress: rich(entry.project_progress) ? entry.project_progress : cur.project_progress,
          next_week_strategy: rich(entry.next_week_strategy) ? entry.next_week_strategy : cur.next_week_strategy,
        };
      }
    }
    for (const row of await sql`SELECT month, feedback FROM monthly_feedback`) {
      const month = row.month as string;
      if (!store.monthly_feedback.some((f) => f.month === month)) {
        store.monthly_feedback.push({ month, feedback: (row.feedback as string) ?? "" });
      }
    }
  } finally {
    await sql.end();
  }
}

async function main() {
  loadEnvFile(".env.production.local");
  loadEnvFile(".env.local");
  loadEnvFile(".env");

  const storePath = path.join(process.cwd(), "data", "kpi-store.json");
  const bakPath = path.join(process.cwd(), "data", "kpi-store.json.bak");
  const store = JSON.parse(fs.readFileSync(storePath, "utf8")) as KpiStore;

  if (fs.existsSync(bakPath)) {
    const bak = fs.readFileSync(bakPath, "utf8");
    const notes24 = parseBakNotes24(bak);
    if (notes24 && notes24.project_progress.length > 50) {
      mergeNotes(store, notes24);
      console.log("bak에서 2026-24 주간 노트 복구");
    }
  }

  const dbUrl = process.env.DATABASE_URL?.trim();
  if (dbUrl && !dbUrl.includes("supabase")) {
    await mergeFromPostgres(store, dbUrl);
    console.log("Postgres 병합 완료");
  }

  fs.writeFileSync(storePath, JSON.stringify(store, null, 2), "utf8");
  console.log("저장:", storePath);
  console.log(
    "counts:",
    Object.fromEntries(Object.entries(store).map(([k, v]) => [k, Array.isArray(v) ? v.length : 0])),
  );

  if (process.env.BLOB_STORE_ID || process.env.BLOB_READ_WRITE_TOKEN) {
    process.env.VERCEL_ENV = process.env.VERCEL_ENV || "production";
    const content = fs.readFileSync(storePath, "utf8");
    const result = await put("kpi-store.json", content, { access: "public", addRandomSuffix: false });
    console.log("Blob 업로드:", result.url);
  } else {
    console.log("Blob env 없음 — vercel --prod 배포로 반영");
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
