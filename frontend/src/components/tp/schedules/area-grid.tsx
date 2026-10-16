"use client";

import Link from "next/link";
import { AlertTriangle, BadgeCheck, MessageSquare, Network, Stethoscope, TrendingUp } from "lucide-react";
import { humanize, pct } from "@/lib/format";
import type { AreaSummary } from "@/lib/schedule-types";
import { cn } from "@/lib/utils";
import { Chip } from "../primitives";
import { Amt } from "./common";

function Meter({ value, tone }: { value: number | null; tone: "trace" | "verify" }) {
  const v = value ?? 0;
  return (
    <div className="h-1.5 w-full rounded bg-slate-100">
      <div className={cn("h-1.5 rounded", tone === "trace" ? "bg-indigo-400" : v > 0 ? "bg-emerald-500" : "bg-slate-200")} style={{ width: `${Math.round(v * 100)}%` }} />
    </div>
  );
}

const STATUS_TONE: Record<string, "muted" | "info" | "good" | "bad"> = { not_started: "muted", in_progress: "info", prepared: "good", reviewed: "good", reopened: "bad" };

/** One card per tax area: the numbers, the evidence behind them, what is open, who owns it. */
export function AreaCard({ a, version }: { a: AreaSummary; version: string }) {
  const head = a.figures[0];
  const issues = a.issues.open_notes + a.issues.conflicts + a.issues.needs_review + a.issues.engine_diagnostics;
  return (
    <Link href={`/return/area/${a.key}?v=${version}`} className="group flex flex-col rounded-lg border bg-card p-3.5 shadow-xs transition hover:border-primary/40 hover:shadow-sm">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="text-[13.5px] font-semibold">{a.title}</div>
          <div className="text-[10.5px] text-muted-foreground">{a.line_count} lines · {a.evidence.documents.length} documents{a.budget_hours ? ` · ${a.budget_hours}h budget` : ""}</div>
        </div>
        {issues > 0 ? <Chip tone={a.issues.conflicts || a.issues.blocking_notes ? "bad" : "warn"}><AlertTriangle className="size-3" />{issues} open</Chip> : <Chip tone="good">nothing open</Chip>}
      </div>
      {head && (
        <div className="mt-2">
          <div className="truncate text-[11px] text-muted-foreground">{head.label}</div>
          <div className="flex items-baseline gap-2">
            <span className="num text-xl font-semibold"><Amt v={head.value} /></span>
            {head.prior_year != null && (
              <span className={cn("text-[11px]", head.variance_flag ? "font-medium text-amber-700" : "text-muted-foreground")}>
                2024 <Amt v={head.prior_year} /> · {head.change != null ? pct(head.change_pct) : ""}
              </span>
            )}
          </div>
        </div>
      )}
      {a.figures.slice(1).map((f) => (
        <div key={f.key} className="flex justify-between text-[11px] text-slate-600"><span className="truncate pr-2">{f.label}</span><span><Amt v={f.value} />{f.variance_flag && <TrendingUp className="ml-1 inline size-3 text-amber-600" />}</span></div>
      ))}
      <div className="mt-3 space-y-1.5 text-[10.5px] text-muted-foreground">
        <div>
          <div className="flex justify-between"><span className="flex items-center gap-1"><Network className="size-3" />Traceable to evidence</span><span>{a.traceable_lines}/{a.line_count}</span></div>
          <Meter value={a.evidence.traceability} tone="trace" />
        </div>
        <div>
          <div className="flex justify-between"><span className="flex items-center gap-1"><BadgeCheck className="size-3" />Source values verified</span><span>{a.evidence.verified_values}/{a.evidence.values}</span></div>
          <Meter value={a.evidence.coverage} tone="verify" />
        </div>
      </div>
      <div className="mt-2.5 flex flex-wrap gap-1">
        {a.issues.conflicts > 0 && <Chip tone="bad">{a.issues.conflicts} conflict</Chip>}
        {a.issues.needs_review > 0 && <Chip tone="warn">{a.issues.needs_review} to review</Chip>}
        {a.issues.engine_diagnostics > 0 && <Chip tone="engine"><Stethoscope className="size-3" />{a.issues.engine_diagnostics} engine</Chip>}
        {a.issues.variances > 0 && <Chip tone="warn">{a.issues.variances} swings</Chip>}
        {a.issues.open_notes > 0 && <Chip tone="info"><MessageSquare className="size-3" />{a.issues.open_notes} notes</Chip>}
      </div>
      <div className="mt-auto flex gap-1 pt-2.5">
        {(["preparer", "reviewer", "partner"] as const).map((r) => (
          <Chip key={r} tone={STATUS_TONE[a.status[r]] ?? "muted"} title={r === "preparer" ? a.status.preparer_name ?? "" : r === "reviewer" ? a.status.reviewer_name ?? "" : ""}>
            {r[0].toUpperCase()} · {humanize(a.status[r])}
          </Chip>
        ))}
      </div>
    </Link>
  );
}
