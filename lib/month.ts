import { getIsoWeekKey, getPlannerWeekLabel, isoWeekKeysInMonth } from "./week";

function pad2(n: number) {
  return String(n).padStart(2, "0");
}

export function getMonthKey(d: Date = new Date()): string {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}`;
}

export function getMonthLabel(monthKey: string): string {
  const [year, month] = monthKey.split("-");
  return `${year}년 ${Number(month)}월`;
}

export function getMonthDateRange(monthKey: string): [string, string] {
  const [year, month] = monthKey.split("-").map(Number);
  const start = new Date(year, month - 1, 1);
  const lastDay = new Date(year, month, 0).getDate();
  const end = new Date(year, month - 1, lastDay);
  return [toIso(start), toIso(end)];
}

function toIso(d: Date) {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

export function prevMonthKey(monthKey: string): string {
  const [year, month] = monthKey.split("-").map(Number);
  if (month === 1) return `${year - 1}-12`;
  return `${year}-${pad2(month - 1)}`;
}

export function recentMonthKeys(n: number, fromMonth?: string): string[] {
  const [baseYear, baseMonth] = (fromMonth ?? getMonthKey()).split("-").map(Number);
  return Array.from({ length: n }, (_, i) => {
    let m = baseMonth - (n - 1 - i);
    let y = baseYear;
    while (m <= 0) {
      m += 12;
      y -= 1;
    }
    return `${y}-${pad2(m)}`;
  });
}

export function getIsoWeeksInMonth(monthKey: string) {
  return isoWeekKeysInMonth(monthKey).map((wk) => ({
    week: wk,
    week_label: getPlannerWeekLabel(wk),
  }));
}
