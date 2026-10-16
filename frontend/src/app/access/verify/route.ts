import { NextResponse } from "next/server";

/** Checks the access code and sets the cookie the gate (and the API) look for. */
export async function POST(req: Request) {
  const form = await req.formData();
  const given = String(form.get("code") ?? "");
  const next = String(form.get("next") ?? "/overview");
  const target = next.startsWith("/") && !next.startsWith("//") ? next : "/overview";
  const code = process.env.TAXPROOF_ACCESS_CODE;
  if (!code || given !== code) return NextResponse.redirect(new URL(`/access?error=1&next=${encodeURIComponent(target)}`, req.url), 303);
  const res = NextResponse.redirect(new URL(target, req.url), 303);
  res.cookies.set("tp_access", code, { httpOnly: true, secure: true, sameSite: "lax", path: "/", maxAge: 60 * 60 * 24 * 30 });
  return res;
}
