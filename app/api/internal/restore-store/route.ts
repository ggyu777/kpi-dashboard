import { NextResponse } from "next/server";
import type { KpiStore } from "@/lib/json-store";
import { writeStore } from "@/lib/json-store";

export async function POST(req: Request) {
  const key = req.headers.get("x-restore-key");
  if (!key || key !== process.env.GA4_PROPERTY_ID) {
    return NextResponse.json({ detail: "forbidden" }, { status: 403 });
  }
  const store = (await req.json()) as KpiStore;
  await writeStore(store, { force: true });
  return NextResponse.json({
    ok: true,
    weekly_plans: store.weekly_plans?.length ?? 0,
    weekly_notes: store.weekly_notes?.length ?? 0,
  });
}
