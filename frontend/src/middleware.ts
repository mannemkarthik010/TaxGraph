import { NextResponse, type NextRequest } from "next/server";

/**
 * Optional access gate for a shared deployment. With TAXPROOF_ACCESS_CODE set, every page and API call needs
 * the tp_access cookie (set once on /access); without it, the app is open (local development).
 */
export function middleware(req: NextRequest) {
  const code = process.env.TAXPROOF_ACCESS_CODE;
  if (!code) return NextResponse.next();
  const path = req.nextUrl.pathname;
  if (path.startsWith("/access") || req.cookies.get("tp_access")?.value === code) return NextResponse.next();
  if (path.startsWith("/api/")) return NextResponse.json({ detail: "Access code required." }, { status: 401 });
  const url = req.nextUrl.clone();
  url.pathname = "/access";
  url.search = `?next=${encodeURIComponent(path + req.nextUrl.search)}`;
  return NextResponse.redirect(url);
}

export const config = { matcher: ["/((?!_next/|favicon.ico).*)"] };
