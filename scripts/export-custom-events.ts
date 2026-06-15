/**
 * GA4 커스텀 이벤트 주차별 카운트 → data/ CSV·MD export
 * Usage: npx tsx --env-file=.env.local scripts/export-custom-events.ts
 */
import fs from "fs";
import path from "path";
import {
  CLICK_EVENT_MAP,
  CUSTOM_EVENT_DEFINITIONS,
  IMPRESSION_EVENT_MAP,
  PLACEMENTS,
  wow,
} from "../lib/constants";
import { fetchAdEventsByName } from "../lib/ga4";
import { getWeekDateRange, getWeekLabel, prevWeekKey } from "../lib/week";

const WEEKS = ["2026-23", "2026-24"];
const OUT_DIR = path.join(process.cwd(), "data");
const GENERATED_AT = new Date().toISOString().slice(0, 10);

function csvEscape(v: string | number | null | undefined) {
  const s = v == null ? "" : String(v);
  return s.includes(",") || s.includes('"') || s.includes("\n") ? `"${s.replace(/"/g, '""')}"` : s;
}

function writeCsv(filePath: string, headers: string[], rows: (string | number | null | undefined)[][]) {
  const lines = [headers.join(","), ...rows.map((r) => r.map(csvEscape).join(","))];
  fs.writeFileSync(filePath, lines.join("\n") + "\n", "utf8");
}

async function main() {
  type Row = {
    week: string;
    week_label: string;
    week_start: string;
    week_end: string;
    event_name: string;
    label: string;
    category: string;
    count: number;
    prev_count: number;
    wow_pct: number | null;
  };

  const rows: Row[] = [];

  for (const week of WEEKS) {
    const prev = prevWeekKey(week);
    const [start, end] = getWeekDateRange(week);
    const names = CUSTOM_EVENT_DEFINITIONS.map((e) => e.event_name);
    const [counts, prevCounts] = await Promise.all([
      fetchAdEventsByName(week, [...names]),
      fetchAdEventsByName(prev, [...names]),
    ]);

    for (const evt of CUSTOM_EVENT_DEFINITIONS) {
      const count = counts[evt.event_name] ?? 0;
      const prev_count = prevCounts[evt.event_name] ?? 0;
      rows.push({
        week,
        week_label: getWeekLabel(week),
        week_start: start,
        week_end: end,
        event_name: evt.event_name,
        label: evt.label,
        category: evt.category,
        count,
        prev_count,
        wow_pct: wow(count, prev_count),
      });
    }
  }

  // --- custom-events-list.csv (master + latest week counts)
  const latestWeek = WEEKS[WEEKS.length - 1];
  const latestByEvent = Object.fromEntries(
    rows.filter((r) => r.week === latestWeek).map((r) => [r.event_name, r]),
  );
  writeCsv(
    path.join(OUT_DIR, "custom-events-list.csv"),
    ["category", "event_name", "label", "csv_cumulative_count", "csv_period", `count_${latestWeek}`, "prev_count", "wow_pct"],
    CUSTOM_EVENT_DEFINITIONS.map((e) => {
      const r = latestByEvent[e.event_name];
      return [
        e.category,
        e.event_name,
        e.label,
        e.event_name === "view_contest_detail" ? 72829 : "",
        e.event_name === "view_contest_detail" ? "20250101-20260601" : "",
        r?.count ?? 0,
        r?.prev_count ?? 0,
        r?.wow_pct ?? "",
      ];
    }),
  );

  // --- custom-events-weekly.csv (all weeks)
  writeCsv(
    path.join(OUT_DIR, "custom-events-weekly.csv"),
    ["week", "week_label", "week_start", "week_end", "category", "event_name", "label", "count", "prev_count", "wow_pct"],
    rows.map((r) => [
      r.week,
      r.week_label,
      r.week_start,
      r.week_end,
      r.category,
      r.event_name,
      r.label,
      r.count,
      r.prev_count,
      r.wow_pct ?? "",
    ]),
  );

  // --- ad slot events weekly
  type AdRow = {
    week: string;
    placement: string;
    placement_label: string;
    event_type: string;
    event_name: string;
    count: number;
    prev_count: number;
    wow_pct: number | null;
  };
  const adRows: AdRow[] = [];
  for (const week of WEEKS) {
    const prev = prevWeekKey(week);
    const clickEvents = Object.values(CLICK_EVENT_MAP);
    const impEvents = Object.values(IMPRESSION_EVENT_MAP);
    const [clicks, prevClicks, imps, prevImps] = await Promise.all([
      fetchAdEventsByName(week, clickEvents),
      fetchAdEventsByName(prev, clickEvents),
      fetchAdEventsByName(week, impEvents),
      fetchAdEventsByName(prev, impEvents),
    ]);
    for (const p of PLACEMENTS) {
      const clickEvt = CLICK_EVENT_MAP[p.id];
      const impEvt = IMPRESSION_EVENT_MAP[p.id];
      const c = clicks[clickEvt] ?? 0;
      const pc = prevClicks[clickEvt] ?? 0;
      adRows.push({
        week,
        placement: p.id,
        placement_label: p.label,
        event_type: "click",
        event_name: clickEvt,
        count: c,
        prev_count: pc,
        wow_pct: wow(c, pc),
      });
      const i = imps[impEvt] ?? 0;
      const pi = prevImps[impEvt] ?? 0;
      adRows.push({
        week,
        placement: p.id,
        placement_label: p.label,
        event_type: "impression",
        event_name: impEvt,
        count: i,
        prev_count: pi,
        wow_pct: wow(i, pi),
      });
    }
  }
  writeCsv(
    path.join(OUT_DIR, "custom-events-ad-slots-weekly.csv"),
    ["week", "placement", "placement_label", "event_type", "event_name", "count", "prev_count", "wow_pct"],
    adRows.map((r) => [r.week, r.placement, r.placement_label, r.event_type, r.event_name, r.count, r.prev_count, r.wow_pct ?? ""]),
  );

  // --- markdown reference
  const categories = [
    { id: "contest", label: "대회" },
    { id: "home", label: "홈" },
    { id: "shoes", label: "슈즈" },
    { id: "myrun", label: "마이런" },
    { id: "participation", label: "참가" },
    { id: "record", label: "기록" },
    { id: "goal", label: "목표" },
    { id: "funnel", label: "펀넬" },
    { id: "etc", label: "기타" },
  ] as const;

  let md = `# 🎯 러닝라이프 커스텀 이벤트 카운트 자료

> 자동 생성: ${GENERATED_AT} (\`scripts/export-custom-events.ts\`)  
> GA4 속성 ID: ${process.env.GA4_PROPERTY_ID ?? "410384180"}  
> 포함 주차: ${WEEKS.map((w) => `${w} (${getWeekLabel(w)})`).join(", ")}

## 파일 목록

| 파일 | 설명 |
|------|------|
| \`custom-events-list.csv\` | 42개 이벤트 마스터 + 최신 주차 카운트 |
| \`custom-events-weekly.csv\` | 주차별 전체 커스텀 이벤트 카운트 |
| \`custom-events-ad-slots-weekly.csv\` | 광고 슬롯 노출/클릭 주차별 |
| \`custom-events-reference.md\` | 이 문서 |

재생성: \`npx tsx --env-file=.env.local scripts/export-custom-events.ts\`

---

`;

  for (const week of WEEKS) {
    const weekRows = rows.filter((r) => r.week === week);
    const total = weekRows.reduce((s, r) => s + r.count, 0);
    md += `## ${week} — ${getWeekLabel(week)}\n\n`;
    md += `**총 이벤트 수:** ${total.toLocaleString()}회 (42개 합계)\n\n`;

    for (const cat of categories) {
      const catRows = weekRows.filter((r) => r.category === cat.id);
      if (!catRows.length) continue;
      md += `### ${cat.label} (${cat.id})\n\n`;
      md += `| event_name | 라벨 | count | prev | WoW |\n`;
      md += `|------------|------|------:|-----:|----:|\n`;
      for (const r of catRows.sort((a, b) => b.count - a.count)) {
        const wowStr = r.wow_pct == null ? "—" : `${r.wow_pct > 0 ? "+" : ""}${r.wow_pct}%`;
        md += `| \`${r.event_name}\` | ${r.label} | ${r.count.toLocaleString()} | ${r.prev_count.toLocaleString()} | ${wowStr} |\n`;
      }
      md += `\n`;
    }
  }

  md += `## 광고 슬롯 이벤트\n\n`;
  for (const week of WEEKS) {
    md += `### ${week}\n\n`;
    md += `| 슬롯 | 유형 | event_name | count | prev | WoW |\n`;
    md += `|------|------|------------|------:|-----:|----:|\n`;
    for (const r of adRows.filter((x) => x.week === week)) {
      const wowStr = r.wow_pct == null ? "—" : `${r.wow_pct > 0 ? "+" : ""}${r.wow_pct}%`;
      md += `| ${r.placement_label} | ${r.event_type} | \`${r.event_name}\` | ${r.count.toLocaleString()} | ${r.prev_count.toLocaleString()} | ${wowStr} |\n`;
    }
    md += `\n`;
  }

  md += `## ga4_overview.csv 누적 (2025-01-01 ~ 2026-06-01)\n\n`;
  md += `| 이벤트 | 누적 |\n|--------|-----:|\n`;
  md += `| View_contest_detail | 72,829 |\n| form_start | 22,152 |\n| form_submit | 17,149 |\n`;

  fs.writeFileSync(path.join(OUT_DIR, "custom-events-reference.md"), md, "utf8");

  console.log(`Wrote ${rows.length} custom event rows for weeks ${WEEKS.join(", ")}`);
  console.log(`  data/custom-events-list.csv`);
  console.log(`  data/custom-events-weekly.csv`);
  console.log(`  data/custom-events-ad-slots-weekly.csv`);
  console.log(`  data/custom-events-reference.md`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
