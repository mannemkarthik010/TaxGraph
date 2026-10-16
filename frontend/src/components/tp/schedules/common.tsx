"use client";

import Link from "next/link";
import { createContext, useContext, useState } from "react";
import { CheckCircle2, ShieldCheck, XCircle } from "lucide-react";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { money } from "@/lib/format";
import { evidenceTraceHref } from "@/lib/links";
import type { Check } from "@/lib/schedule-types";
import { cn } from "@/lib/utils";
import { LineDetail } from "../line-detail";
import { Panel } from "../primitives";

/** Any schedule can open a return line in a side drawer without leaving the page. */
const LineCtx = createContext<{ open: (key: string) => void; version: string }>({ open: () => {}, version: "v3" });
export const useLineDrawer = () => useContext(LineCtx);

export function LineDrawerProvider({ version, children }: { version: string; children: React.ReactNode }) {
  const [key, setKey] = useState<string | null>(null);
  return (
    <LineCtx.Provider value={{ open: setKey, version }}>
      {children}
      <Sheet open={!!key} onOpenChange={(o) => !o && setKey(null)}>
        <SheetContent className="w-full overflow-y-auto sm:max-w-xl">
          <SheetHeader className="pb-0">
            <SheetTitle>Line detail</SheetTitle>
            <SheetDescription>Supplied engine output with its cited evidence. Nothing here is recomputed.</SheetDescription>
          </SheetHeader>
          <div className="px-4 pb-6">{key && <LineDetail version={version} lineKey={key} onOpenLine={setKey} />}</div>
        </SheetContent>
      </Sheet>
    </LineCtx.Provider>
  );
}

/** A line key that opens the line drawer. */
export function LineRef({ k, className }: { k: string | null | undefined; className?: string }) {
  const { open } = useLineDrawer();
  if (!k) return null;
  return (
    <button onClick={() => open(k)} className={cn("font-mono text-[11px] text-sky-700 hover:underline", className)}>{k}</button>
  );
}

/** An evidence reference that opens its page in the Evidence Explorer. */
export function EvRef({ id }: { id: string }) {
  const { version } = useLineDrawer();
  if (!id.startsWith("ev-")) return <code className="text-[10.5px] text-muted-foreground">{id}</code>;
  return (
    <Link href={evidenceTraceHref(id, version)} className="font-mono text-[10.5px] text-sky-700 hover:underline"
      title={`Where this value goes in ${version}`}>{id}</Link>
  );
}

export function Amt({ v, className, sign }: { v: unknown; className?: string; sign?: boolean }) {
  return <span className={cn("num", typeof v === "number" && v < 0 && "text-rose-700", className)}>{money(v, { sign })}</span>;
}

/** Recomputations TaxProof did itself — always visually separate from the engine's figures. */
export function ChecksPanel({ checks, title = "TaxProof recalculation" }: { checks: Check[]; title?: string }) {
  if (!checks.length) return null;
  const failing = checks.filter((c) => !c.agrees);
  return (
    <Panel dense title={
      <span className="flex items-center gap-1.5"><ShieldCheck className="size-4 text-primary" />{title}
        <span className={cn("ml-1 text-[11px] font-normal", failing.length ? "text-rose-700" : "text-emerald-700")}>
          {failing.length ? `${failing.length} of ${checks.length} disagree with the engine` : `all ${checks.length} agree with the engine`}
        </span>
      </span>}>
      <ul className="divide-y text-xs">
        {checks.map((c, i) => (
          <li key={i} className="grid grid-cols-[18px_1fr_auto_auto] items-center gap-3 px-4 py-1.5">
            {c.agrees ? <CheckCircle2 className="size-3.5 text-emerald-600" /> : <XCircle className="size-3.5 text-rose-600" />}
            <span title={c.detail}>{c.check}</span>
            <span className="text-muted-foreground">TaxProof <b className="num font-medium text-slate-700">{fmtCheck(c.taxproof)}</b></span>
            <span className="text-muted-foreground">engine <b className="num font-medium text-slate-700">{fmtCheck(c.engine)}</b>
              {!c.agrees && <span className="ml-1 text-rose-700">Δ {fmtCheck(c.difference)}</span>}</span>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

const fmtCheck = (n: number) => money(n);

export function SectionTitle({ id, children, sub }: { id?: string; children: React.ReactNode; sub?: React.ReactNode }) {
  return (
    <div id={id} className="scroll-mt-20">
      <h2 className="text-[15px] font-semibold">{children}</h2>
      {sub && <p className="text-xs text-muted-foreground">{sub}</p>}
    </div>
  );
}

export const SCHEDULE_TITLES: Record<string, string> = {
  "tax-computation": "Return summary & tax computation",
  "prior-year": "Prior-year comparison",
  "books-to-tax": "Books to tax (Schedule C)",
  depreciation: "Depreciation by asset",
  brokerage: "Brokerage & digital asset sales",
  rentals: "Rentals & passive losses",
  "k1-basis": "K-1s & basis by year",
  "state-allocation": "California / Texas allocation",
  carryovers: "Carryovers",
};
