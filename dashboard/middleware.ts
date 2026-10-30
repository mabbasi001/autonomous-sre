import { NextRequest, NextResponse } from "next/server";

const SESSION_COOKIE = "sre_session";

// Gate page navigation: without a session cookie, redirect to /login.
// All /api/* routes are excluded — the proxy and auth routes handle their
// own auth and must return JSON (a 401 from the backend), never an HTML
// redirect. The cookie is only presence-checked here; the backend is the
// real validator.
export function middleware(req: NextRequest) {
  const hasSession = Boolean(req.cookies.get(SESSION_COOKIE)?.value);
  if (hasSession) return NextResponse.next();

  const url = req.nextUrl.clone();
  url.pathname = "/login";
  url.searchParams.set("next", req.nextUrl.pathname);
  return NextResponse.redirect(url);
}

export const config = {
  // Everything except the login page, all API routes, and static assets.
  matcher: ["/((?!login|api|_next/static|_next/image|favicon.ico).*)"],
};
