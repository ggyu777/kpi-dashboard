import fs from "fs";
import path from "path";
import { getMonthLabel } from "./month";

const DATA_DIR = path.join(process.cwd(), "data");

function dataPath(name: string) {
  return path.join(DATA_DIR, name);
}

function monthKeyFromDate(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function sundayOfWeek(d: Date) {
  const copy = new Date(d);
  copy.setDate(d.getDate() - ((d.getDay() + 6) % 7));
  return copy;
}

function weekKey(ws: Date, we: Date) {
  const fmt = (x: Date) =>
    `${x.getFullYear()}${String(x.getMonth() + 1).padStart(2, "0")}${String(x.getDate()).padStart(2, "0")}`;
  return `${fmt(ws)}-${fmt(we)}`;
}

export function parseCohortRetentionCsv(filePath = dataPath("cohort_retention.csv")) {
  const result: Record<string, { cohort_total: number; w1_active: number; rate: number }> = {};
  if (!fs.existsSync(filePath)) return result;
  for (const line of fs.readFileSync(filePath, "utf8").split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#") || trimmed.startsWith("주간")) continue;
    const parts = trimmed.split(",");
    if (parts.length < 5) continue;
    const [nth, dateRange, col3, col4, col5] = parts;
    if (nth !== "0001" || dateRange.length !== 17 || dateRange[8] !== "-") continue;
    if (dateRange.includes("RESERVED") || !/^\d+$/.test(col3)) continue;
    result[dateRange] = {
      cohort_total: Number(col3),
      w1_active: Number(col4),
      rate: Math.round(Number(col5) * 1000) / 10,
    };
  }
  return result;
}

function ga4CohortWeeksForDataMonth(monthKey: string): Array<[Date, Date]> {
  const [year, month] = monthKey.split("-").map(Number);
  const prevYear = month > 1 ? year : year - 1;
  const prevMonth = month > 1 ? month - 1 : 12;
  const prevLast = new Date(prevYear, prevMonth, 0);
  const lastDay = new Date(year, month, 0).getDate();
  const last = new Date(year, month - 1, lastDay);

  const prevWs = sundayOfWeek(prevLast);
  const prevWe = new Date(prevWs);
  prevWe.setDate(prevWs.getDate() + 6);

  const weeksInMonth: Array<[Date, Date]> = [];
  let ws = new Date(year, month - 1, 1);
  const firstSun = sundayOfWeek(ws);
  ws = firstSun < new Date(year, month - 1, 1) ? new Date(firstSun.getTime() + 7 * 86400000) : firstSun;
  while (ws <= last) {
    const we = new Date(ws);
    we.setDate(Math.min(ws.getDate() + 6, last.getDate() + (we.getMonth() !== last.getMonth() ? 31 : 0)));
    weeksInMonth.push([new Date(ws), we]);
    ws = new Date(ws.getTime() + 7 * 86400000);
  }

  let thisWeeks: Array<[Date, Date]> = [];
  if (weeksInMonth.length >= 2 && weeksInMonth[weeksInMonth.length - 1][1].getDate() - weeksInMonth[weeksInMonth.length - 1][0].getDate() < 6) {
    thisWeeks = weeksInMonth.slice(0, -2);
  } else if (weeksInMonth.length >= 1) {
    thisWeeks = weeksInMonth.slice(0, -1);
  }

  if (thisWeeks.length && prevWs.getTime() === thisWeeks[0][0].getTime()) return thisWeeks;
  return [[prevWs, prevWe], ...thisWeeks];
}

export function fetchD7RetentionWeekly(monthKey: string) {
  const csvData = parseCohortRetentionCsv();
  const targetWeeks = ga4CohortWeeksForDataMonth(monthKey);
  const resultWeeks = [];
  const validRates: number[] = [];
  for (const [ws, we] of targetWeeks) {
    const key = weekKey(ws, we);
    const entry = csvData[key];
    const label = `${ws.getMonth() + 1}/${ws.getDate()}~${we.getMonth() + 1}/${we.getDate()}`;
    if (entry) {
      resultWeeks.push({
        label,
        week_start: ws.toISOString().slice(0, 10),
        rate: entry.rate,
        day0: entry.cohort_total,
        day7: entry.w1_active,
      });
      validRates.push(entry.rate);
    } else {
      resultWeeks.push({ label, week_start: ws.toISOString().slice(0, 10), rate: null, day0: 0, day7: 0 });
    }
  }
  return {
    weeks: resultWeeks,
    avg_rate: validRates.length ? Math.round((validRates.reduce((a, b) => a + b, 0) / validRates.length) * 10) / 10 : null,
  };
}

export function parseGa4OverviewCsv(filePath = dataPath("ga4_overview.csv")) {
  const result: Record<string, { mau?: number; new_users?: number }> = {};
  if (!fs.existsSync(filePath)) return result;
  let section: string | null = null;
  let sectionStart: Date | null = null;
  const monthlyMau: Record<string, number> = {};
  const monthlyNew: Record<string, number> = {};

  for (const line of fs.readFileSync(filePath, "utf8").split("\n")) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    if (trimmed.startsWith("#")) {
      const m = trimmed.match(/시작일:\s*(\d{8})/);
      if (m) {
        const raw = m[1];
        sectionStart = new Date(Number(raw.slice(0, 4)), Number(raw.slice(4, 6)) - 1, Number(raw.slice(6, 8)));
      }
      if (trimmed.includes("활성 사용자 추이")) section = "daily";
      continue;
    }
    if (trimmed === "N주,새 사용자 수") { section = "weekly_new"; continue; }
    if (trimmed === "N일,30일,7일,1일") { section = "daily"; continue; }
    const parts = trimmed.split(",");
    if (section === "weekly_new" && parts.length >= 2 && sectionStart) {
      if (!/^\d+$/.test(parts[0]) || !/^\d+$/.test(parts[1])) continue;
      const weekStart = new Date(sectionStart);
      weekStart.setDate(sectionStart.getDate() + Number(parts[0]) * 7);
      monthlyNew[monthKeyFromDate(weekStart)] = (monthlyNew[monthKeyFromDate(weekStart)] ?? 0) + Number(parts[1]);
    } else if (section === "daily" && parts.length >= 2 && sectionStart) {
      if (!/^\d+$/.test(parts[0]) || !/^\d+$/.test(parts[1])) continue;
      const d = new Date(sectionStart);
      d.setDate(sectionStart.getDate() + Number(parts[0]));
      monthlyMau[monthKeyFromDate(d)] = Number(parts[1]);
    }
  }
  const allMonths = new Set([...Object.keys(monthlyMau), ...Object.keys(monthlyNew)]);
  for (const mk of allMonths) {
    result[mk] = {};
    if (monthlyMau[mk]) result[mk].mau = monthlyMau[mk];
    if (monthlyNew[mk]) result[mk].new_users = monthlyNew[mk];
  }
  return result;
}

function parseKoreanDate(s: string) {
  const m = s.trim().match(/(\d+)년\s*(\d+)월\s*(\d+)일/);
  return m ? new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3])) : null;
}

function parseDotDate(s: string) {
  const parts = s.trim().replace(/\.$/, "").split(".").map((p) => p.trim()).filter(Boolean);
  if (parts.length !== 3) return null;
  let y = Number(parts[0]);
  if (y < 100) y += 2000;
  return new Date(y, Number(parts[1]) - 1, Number(parts[2]));
}

export function parseUserAcquisitionCsv(filePath = dataPath("user_acquisition.csv")) {
  const monthly: Record<string, number> = {};
  if (!fs.existsSync(filePath)) return monthly;
  for (const line of fs.readFileSync(filePath, "utf8").split("\n")) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("날짜,")) continue;
    const parts = trimmed.split(",");
    if (parts.length < 2) continue;
    const d = parseKoreanDate(parts[0]);
    if (!d) continue;
    monthly[monthKeyFromDate(d)] = (monthly[monthKeyFromDate(d)] ?? 0) + Number(parts[1]);
  }
  return monthly;
}

export function parseAppDownloadsCsv(filePath = dataPath("app_downloads.csv")) {
  const monthly: Record<string, number> = {};
  if (!fs.existsSync(filePath)) return monthly;
  let started = false;
  for (const line of fs.readFileSync(filePath, "utf8").split("\n")) {
    const trimmed = line.trim();
    if (trimmed.startsWith("날짜,")) { started = true; continue; }
    if (!started || !trimmed) continue;
    const parts = trimmed.split(",");
    if (parts.length < 2) continue;
    const d = parseDotDate(parts[0]);
    if (!d) continue;
    monthly[monthKeyFromDate(d)] = (monthly[monthKeyFromDate(d)] ?? 0) + Number(parts[1]);
  }
  return monthly;
}

export function getCsvNewUsersByPlatform(monthKey: string) {
  // user_acquisition.csv의 전체 합계(parts[1])를 총 신규 가입자로 사용
  // app_downloads.csv는 iOS 플랫폼 구분 표시용으로만 활용
  const total = parseUserAcquisitionCsv()[monthKey] ?? 0;
  const ios = parseAppDownloadsCsv()[monthKey] ?? 0;
  const android = Math.max(0, total - ios);
  if (total) return { ios, android };
  return null;
}

export function getCsvNewUsers(monthKey: string) {
  // user_acquisition.csv의 전체(모든 국가/지역) 합계만 사용 (이중 계산 방지)
  const total = parseUserAcquisitionCsv()[monthKey];
  return total ?? null;
}

export function mergeTrendWithOverview(
  trendData: Array<{ month: string; month_label: string; mau: number; new_users: number }>,
) {
  const overview = parseGa4OverviewCsv();
  return trendData.map((item) => {
    const ov = overview[item.month] ?? {};
    const csvNew = getCsvNewUsers(item.month);
    return {
      ...item,
      mau: item.mau || ov.mau || 0,
      new_users: csvNew ?? (item.new_users || ov.new_users || 0),
    };
  });
}
