import { NextRequest } from "next/server";

// Server-side proxy to the control plane. The session token lives in an
// httpOnly cookie and is attached here as a Bearer — it never reaches
// browser JS. In development, with no auth configured, the backend
// dev-fallback authenticates without a token.
const API = process.env.SRE_API_URL ?? "http://localhost:8000";
const SESSION_COOKIE = "sre_session";

async function forward(req: NextRequest, path: string[]): Promise<Response> {
  const url = `${API}/${path.join("/")}${req.nextUrl.search}`;
  const headers: Record<string, string> = { "content-type": "application/json" };
  const correlation = req.headers.get("x-correlation-id");
  if (correlation) headers["x-correlation-id"] = correlation;
  const token = req.cookies.get(SESSION_COOKIE)?.value;
  if (token) headers["authorization"] = `Bearer ${token}`;

  const init: RequestInit = { method: req.method, headers, cache: "no-store" };
  if (req.method !== "GET" && req.method !== "HEAD") {
    init.body = await req.text();
  }

  const resp = await fetch(url, init);
  const body = await resp.text();
  return new Response(body, {
    status: resp.status,
    headers: { "content-type": resp.headers.get("content-type") ?? "application/json" },
  });
}

type Ctx = { params: Promise<{ path: string[] }> };

export async function GET(req: NextRequest, ctx: Ctx) {
  return forward(req, (await ctx.params).path);
}
export async function POST(req: NextRequest, ctx: Ctx) {
  return forward(req, (await ctx.params).path);
}
export async function PUT(req: NextRequest, ctx: Ctx) {
  return forward(req, (await ctx.params).path);
}
export async function DELETE(req: NextRequest, ctx: Ctx) {
  return forward(req, (await ctx.params).path);
}
