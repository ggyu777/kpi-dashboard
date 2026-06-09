import { NextResponse } from "next/server";

type Ctx = { params: Promise<{ path?: string[] }> };

async function dispatch(method: string, req: Request, ctx: Ctx) {
  try {
    const { handleApi } = await import("@/lib/api/router");
    const { path: segments } = await ctx.params;
    const pathname = "/api" + (segments?.length ? "/" + segments.join("/") : "");
    return await handleApi(method, pathname, req);
  } catch (e) {
    console.error("[api]", e);
    return NextResponse.json({ detail: String(e) }, { status: 500 });
  }
}

export async function GET(req: Request, ctx: Ctx) {
  return dispatch("GET", req, ctx);
}

export async function POST(req: Request, ctx: Ctx) {
  return dispatch("POST", req, ctx);
}

export async function PUT(req: Request, ctx: Ctx) {
  return dispatch("PUT", req, ctx);
}

export const maxDuration = 60;
