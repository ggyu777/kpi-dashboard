import { ORDINAL_KO, WEEKDAY_KO } from "./constants";

function pad2(n: number) {
  return String(n).padStart(2, "0");
}

export function getIsoWeekKey(d: Date = new Date()): string {
  const iso = getIsoCalendar(d);
  return `${iso.year}-${pad2(iso.week)}`;
}

function getIsoCalendar(d: Date) {
  const date = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const day = date.getUTCDay() || 7;
  date.setUTCDate(date.getUTCDate() + 4 - day);
  const yearStart = new Date(Date.UTC(date.getUTCFullYear(), 0, 1));
  const week = Math.ceil(((date.getTime() - yearStart.getTime()) / 86400000 + 1) / 7);
  return { year: date.getUTCFullYear(), week };
}

export function weekKeyToMonday(weekKey: string): Date {
  const [year, week] = weekKey.split("-").map(Number);
  const jan4 = new Date(year, 0, 4);
  const jan4Day = jan4.getDay() || 7;
  const thursday = new Date(jan4);
  thursday.setDate(jan4.getDate() + (week - getIsoCalendar(jan4).week) * 7 + (3 - (jan4Day - 1)));
  const monday = new Date(thursday);
  monday.setDate(thursday.getDate() - 3);
  return monday;
}

export function getWeekLabel(weekKey: string): string {
  const monday = weekKeyToMonday(weekKey);
  const sunday = new Date(monday);
  sunday.setDate(monday.getDate() + 6);
  const [, week] = weekKey.split("-");
  return `${weekKey.split("-")[0]}년 ${Number(week)}주차 (${monday.getMonth() + 1}/${monday.getDate()}~${sunday.getMonth() + 1}/${sunday.getDate()})`;
}

function referenceMonthKey(weekKey: string): string {
  const monday = weekKeyToMonday(weekKey);
  const counts: Record<string, number> = {};
  for (let i = 0; i < 7; i++) {
    const d = new Date(monday);
    d.setDate(monday.getDate() + i);
    const mk = `${d.getFullYear()}-${pad2(d.getMonth() + 1)}`;
    counts[mk] = (counts[mk] ?? 0) + 1;
  }
  return Object.entries(counts).sort((a, b) => b[1] - a[1])[0][0];
}

export function isoWeekKeysInMonth(monthKey: string): string[] {
  const [year, month] = monthKey.split("-").map(Number);
  const first = new Date(year, month - 1, 1);
  const lastDay = new Date(year, month, 0).getDate();
  const last = new Date(year, month - 1, lastDay);
  const seen = new Set<string>();
  const keys: string[] = [];
  const d = new Date(first);
  while (d <= last) {
    const wk = getIsoWeekKey(d);
    if (!seen.has(wk)) {
      seen.add(wk);
      keys.push(wk);
    }
    d.setDate(d.getDate() + 1);
  }
  return keys;
}

export function getPlannerWeekLabel(weekKey: string): string {
  const monday = weekKeyToMonday(weekKey);
  const sunday = new Date(monday);
  sunday.setDate(monday.getDate() + 6);
  const dateRange = `(${monday.getMonth() + 1}/${monday.getDate()}~${sunday.getMonth() + 1}/${sunday.getDate()})`;
  const monthKey = referenceMonthKey(weekKey);
  const weekKeys = isoWeekKeysInMonth(monthKey);
  const idx = weekKeys.indexOf(weekKey);
  if (idx < 0) return getWeekLabel(weekKey);
  const monthNum = Number(monthKey.split("-")[1]);
  const ordLabel = idx < ORDINAL_KO.length ? ORDINAL_KO[idx] : `${idx + 1}째`;
  return `${monthNum}월 ${ordLabel}주 ${dateRange}`;
}

export function getWeekDateRange(weekKey: string): [string, string] {
  const monday = weekKeyToMonday(weekKey);
  const sunday = new Date(monday);
  sunday.setDate(monday.getDate() + 6);
  return [toIso(monday), toIso(sunday)];
}

function toIso(d: Date) {
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
}

export function getWeekDays(weekKey: string) {
  const monday = weekKeyToMonday(weekKey);
  return Array.from({ length: 7 }, (_, i) => {
    const d = new Date(monday);
    d.setDate(monday.getDate() + i);
    return {
      date: toIso(d),
      weekday: WEEKDAY_KO[i],
      date_label: `${d.getMonth() + 1}/${d.getDate()}`,
    };
  });
}

export function prevWeekKey(weekKey: string): string {
  const monday = weekKeyToMonday(weekKey);
  monday.setDate(monday.getDate() - 7);
  return getIsoWeekKey(monday);
}

export function recentWeekKeys(n: number, fromWeek?: string): string[] {
  const base = weekKeyToMonday(fromWeek ?? getIsoWeekKey());
  return Array.from({ length: n }, (_, i) => {
    const d = new Date(base);
    d.setDate(base.getDate() - (n - 1 - i) * 7);
    return getIsoWeekKey(d);
  });
}

export function buildDailySeries(weekKey: string, valuesByDate: Record<string, number>) {
  const days = getWeekDays(weekKey).map((d) => {
    const v = valuesByDate[d.date] ?? 0;
    return { ...d, value: v };
  });
  const total = days.reduce((s, d) => s + d.value, 0);
  return { days, total };
}
