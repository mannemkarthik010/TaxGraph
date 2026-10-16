"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import {
  Building2, ClipboardCheck, Landmark, Search, FileSearch, FileText, GitCommitVertical, LayoutDashboard, Send, ShieldCheck, Swords,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useApi } from "@/lib/api";
import type { Engagement } from "@/lib/types";
import { RoleSwitcher } from "./role-switcher";

export const NAV = [
  { href: "/overview", label: "Overview", icon: LayoutDashboard, key: "o" },
  { href: "/evidence", label: "Evidence", icon: FileSearch, key: "e" },
  { href: "/return", label: "Return", icon: FileText, key: "r" },
  // Signature feature (Iteration 5): independent assurance checks against the supplied engine.
  { href: "/challenge", label: "Challenge", icon: Swords, key: "c" },
  { href: "/review", label: "Review", icon: ClipboardCheck, key: "v" },
  { href: "/timeline", label: "Timeline", icon: GitCommitVertical, key: "t" },
  { href: "/filing", label: "Filing", icon: Send, key: "f" },
  // Signature feature (Iteration 8): the filed return reconstructed for an examiner.
  { href: "/examiner", label: "Examiner", icon: Landmark, key: "x" },
  { href: "/search", label: "Search", icon: Search, key: "s" },
  { href: "/firm", label: "Firm", icon: Building2, key: "m" },
] as const;

/** Keyboard: press g, then the item's letter (g o = Overview, g r = Return …). */
function useGoKeys() {
  const router = useRouter();
  const armed = useRef(false);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName) || e.metaKey || e.ctrlKey) return;
      if (armed.current) {
        armed.current = false;
        const item = NAV.find((n) => n.key === e.key);
        if (item) router.push(item.href);
      } else if (e.key === "g") {
        armed.current = true;
        setTimeout(() => (armed.current = false), 1200);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [router]);
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { data: eng } = useApi<Engagement>("/api/engagement");
  useGoKeys();

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-56 shrink-0 flex-col border-r bg-white md:flex">
        <div className="flex items-center gap-2 px-4 py-4">
          <span className="flex size-8 items-center justify-center rounded-md bg-primary text-primary-foreground">
            <ShieldCheck className="size-4.5" />
          </span>
          <div className="leading-tight">
            <div className="text-[15px] font-semibold tracking-tight">TaxProof</div>
            <div className="text-[10.5px] text-muted-foreground">Return Assurance Twin</div>
          </div>
        </div>
        <nav className="flex-1 space-y-0.5 px-2">
          {NAV.map(({ href, label, icon: Icon, key }) => {
            const active = pathname.startsWith(href);
            return (
              <Link key={href} href={href}
                className={cn("group flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[13px]",
                  active ? "bg-primary/8 font-medium text-primary" : "text-slate-600 hover:bg-slate-50 hover:text-slate-900")}>
                <Icon className="size-4" />
                <span className="flex-1">{label}</span>
                <kbd className="hidden rounded border px-1 font-mono text-[10px] text-slate-400 group-hover:inline">g {key}</kbd>
              </Link>
            );
          })}
        </nav>
        <div className="border-t px-4 py-3 text-[11px] leading-snug text-muted-foreground">
          AI investigates. Code calculates.<br />Evidence proves. CPAs decide.
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex items-center justify-between gap-3 border-b bg-white/90 px-4 py-2.5 backdrop-blur md:px-6">
          <div className="min-w-0">
            <div className="truncate text-[13px] font-semibold">
              {eng ? `Okafor-Lindqvist · Tax year ${eng.tax_year}` : "Loading engagement…"}
            </div>
            <div className="flex flex-wrap items-center gap-x-3 text-[11px] text-muted-foreground">
              {eng && (
                <>
                  <span>Client {eng.client_id}</span>
                  <span>Current return <b className="font-medium text-slate-700">{eng.current_return_version}</b></span>
                  <span title={`SHA-256 ${eng.packet.sha256}`} className="inline-flex items-center gap-1">
                    <ShieldCheck className="size-3 text-emerald-600" />
                    Source packet immutable · {eng.packet.sha256.slice(0, 10)}…
                  </span>
                </>
              )}
            </div>
          </div>
          <div className="flex items-center gap-3">
            <ProveBox />
            <RoleSwitcher />
          </div>
        </header>
        {/* Mobile nav */}
        <nav className="flex gap-1 overflow-x-auto border-b bg-white px-3 py-1.5 md:hidden">
          {NAV.map(({ href, label }) => (
            <Link key={href} href={href} className={cn("rounded px-2 py-1 text-xs whitespace-nowrap",
              pathname.startsWith(href) ? "bg-primary/10 text-primary" : "text-slate-600")}>{label}</Link>
          ))}
        </nav>
        <main className="mx-auto w-full max-w-[1400px] flex-1 px-4 py-5 md:px-6">{children}</main>
      </div>
    </div>
  );
}

/** Jump to Prove It for any reference: a line key (SchC.9), value (ev-0315), document (D23) or page. */
function ProveBox() {
  const router = useRouter();
  const [ref, setRef] = useState("");
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (ref.trim()) router.push(`/prove?ref=${encodeURIComponent(ref.trim())}&mode=up`);
      }}
      className="hidden items-center gap-1.5 rounded-md border bg-white px-2 py-1 shadow-xs lg:flex"
    >
      <ShieldCheck className="size-3.5 text-primary" />
      <input value={ref} onChange={(e) => setRef(e.target.value)} placeholder="Prove any number — SchC.9, F1040.24, ev-0315"
        className="w-64 bg-transparent text-xs outline-none placeholder:text-slate-400" aria-label="Prove a number" />
    </form>
  );
}
