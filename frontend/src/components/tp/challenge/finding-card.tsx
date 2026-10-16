"use client";

import { AlertOctagon, CheckCircle2, Gavel, ShieldQuestion } from "lucide-react";
import { money } from "@/lib/format";
import type { Finding } from "@/lib/schedule-types";
import { cn } from "@/lib/utils";
import { Chip } from "../primitives";
import { Amt } from "../schedules/common";

export const SEV_TONE = { critical: "bad", high: "bad", medium: "warn", low: "neutral", info: "muted" } as const;
export const STATUS_META = {
  fail: { label: "Failed", icon: AlertOctagon, tone: "text-rose-600" },
  attention: { label: "Needs judgment", icon: ShieldQuestion, tone: "text-amber-600" },
  explained: { label: "Explained", icon: CheckCircle2, tone: "text-sky-600" },
  pass: { label: "Passed", icon: CheckCircle2, tone: "text-emerald-600" },
} as const;

export function unitFmt(v: number | null | undefined, unit: string) {
  if (v == null) return "—";
  return unit === "USD" ? money(v) : `${money(v)} ${unit === "ratio" ? "" : unit}`;
}

export function FindingCard({ f, onOpen }: { f: Finding; onOpen: () => void }) {
  const M = STATUS_META[f.status];
  return (
    <button onClick={onOpen} className={cn("w-full rounded-lg border bg-card p-3.5 text-left shadow-xs transition hover:border-primary/40",
      f.status === "fail" && (f.severity === "critical" || f.severity === "high") && "border-rose-200")}>
      <div className="flex flex-wrap items-center gap-1.5">
        <M.icon className={cn("size-4", M.tone)} />
        <Chip tone="info">TAXPROOF INDEPENDENT FINDING</Chip>
        <Chip tone={SEV_TONE[f.severity]}>{f.severity}</Chip>
        <span className="text-[11px] text-muted-foreground">{f.family_label}</span>
        {f.partner_review && <Chip tone="bad">partner review (&gt;$1,000)</Chip>}
        {f.judgment && <Chip tone="warn"><Gavel className="size-3" />judgment</Chip>}
        {f.engine_diagnostics.length > 0 ? <Chip tone="engine">engine also flagged</Chip> : f.status !== "pass" ? <Chip tone="muted">engine silent</Chip> : null}
      </div>
      <div className="mt-1.5 text-[14px] font-semibold">{f.title}</div>
      <p className="mt-0.5 line-clamp-2 text-[12.5px] text-slate-600">{f.summary}</p>
      {(f.engine || f.effect) && (
        <div className="mt-2 flex flex-wrap items-center gap-x-5 gap-y-1 text-xs">
          {f.engine && f.independent && (
            <span><span className="text-violet-700">Engine</span> <b className="num">{unitFmt(f.engine.value, f.unit)}</b>
              <span className="mx-1.5 text-slate-300">→</span>
              <span className="text-primary">TaxProof</span> <b className="num">{unitFmt(f.independent.value, f.unit)}</b>
              {f.difference != null && <span className="ml-1.5 text-muted-foreground">(Δ {unitFmt(f.difference, f.unit)})</span>}</span>
          )}
          {f.effect && (
            <span className={cn(f.effect.potential && "text-muted-foreground")}>
              {f.effect.potential ? "If disallowed, est." : f.effect.estimate ? "Est. tax effect" : "Balance effect"}: federal <b><Amt v={f.effect.federal} sign /></b> · California <b><Amt v={f.effect.california} sign /></b>
            </span>
          )}
        </div>
      )}
    </button>
  );
}

