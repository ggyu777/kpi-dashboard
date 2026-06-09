import { NextResponse } from "next/server";
import { storageBackend } from "@/lib/db";

export async function GET() {
  return NextResponse.json({ ok: true, storage: storageBackend() });
}
