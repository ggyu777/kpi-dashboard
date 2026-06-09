import { NextResponse } from "next/server";
import { usingPostgres } from "@/lib/db";

export async function GET() {
  return NextResponse.json({ ok: true, storage: usingPostgres() ? "postgres" : "none" });
}
