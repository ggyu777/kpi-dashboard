import { handleApi } from "@/lib/api/router";

type Ctx = { params: Promise<{ path?: string[] }> };

async function dispatch(method: string, req: Request, ctx: Ctx) {
  const { path: segments } = await ctx.params;
  const pathname = "/api" + (segments?.length ? "/" + segments.join("/") : "");
  return handleApi(method, pathname, req);
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
