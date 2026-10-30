import { NextRequest, NextResponse } from "next/server";

// Exchanges email+password for a backend session token and stores it in an
// httpOnly cookie. The token is never exposed to browser JS.
const API = process.env.SRE_API_URL ?? "http://localhost:8000";
const SESSION_COOKIE = "sre_session";

export async function POST(req: NextRequest): Promise<Response> {
  const { email, password } = await req.json().catch(() => ({}));
  if (!email || !password) {
    return NextResponse.json({ detail: "email and password required" }, { status: 400 });
  }

  const upstream = await fetch(`${API}/v1/auth/login`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ email, password }),
    cache: "no-store",
  });

  if (!upstream.ok) {
    const detail =
      upstream.status === 404
        ? "local login is not enabled on the server"
        : "invalid credentials";
    return NextResponse.json({ detail }, { status: upstream.status === 404 ? 404 : 401 });
  }

  const data = await upstream.json();
  const res = NextResponse.json({ user: data.user });
  res.cookies.set(SESSION_COOKIE, data.token, {
    httpOnly: true,
    sameSite: "lax",
    secure: req.nextUrl.protocol === "https:",
    path: "/",
    maxAge: data.expires_in,
  });
  return res;
}
