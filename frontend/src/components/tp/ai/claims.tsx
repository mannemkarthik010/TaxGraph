"use client";

import Link from "next/link";
import { Bot, FileText, ShieldX } from "lucide-react";
import type { AIRun } from "@/lib/ai-types";
import { proveHref } from "@/lib/links";
import { Chip } from "../primitives";

/** Where a cited reference opens. */
export function refHref(ref: string): string {
  const line = /^line:(v\d+):(.+)$/.exec(ref);
  if (line) return `/return?line=${encodeURIComponent(line[2])}&v=${line[1]}`;
  const page = /^doc:(D\d+)#page(\d+)$/.exec(ref);
  if (page) return `/evidence?doc=${page[1]}&page=${page[2]}`;
  if (/^D\d{2}$/.test(ref)) return `/evidence?doc=${ref}&page=1`;
  if (ref.startsWith("finding:")) return `/challenge?finding=${encodeURIComponent(ref.slice(8))}`;
  if (ref.startsWith("note:") || ref.startsWith("diag:") || ref.startsWith("question:") || ref.startsWith("adjustment:")) return "/review?tab=inbox";
  return proveHref(ref);
}

export function ProviderBadge({ run }: { run: Pick<AIRun, "is_ai" | "provider" | "model" | "error"> }) {
  return run.is_ai
    ? <Chip tone="info"><Bot className="size-3" />AI · {run.model}</Chip>
    : <Chip tone="muted" title="No AI model is configured (TAXPROOF_AI_API_KEY). TaxProof wrote these sentences from the same evidence.">
        <FileText className="size-3" />deterministic — no AI model</Chip>;
}

/** Supported claims, each with its evidence; rejected claims shown apart, with why. */
export function Claims({ run }: { run: AIRun }) {
  const ok = run.claims.filter((c) => c.status === "supported");
  const bad = run.claims.filter((c) => c.status === "rejected");
  return (
    <div className="space-y-2 text-[13px]" data-testid="ai-claims">
      <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
        <ProviderBadge run={run} />
        <span>{run.supported} grounded claim{run.supported === 1 ? "" : "s"}{run.rejected > 0 && ` · ${run.rejected} rejected`}</span>
        <span className="font-mono">context {run.context_sha256.slice(0, 10)}…</span>
        {run.error && <span className="text-amber-700">{run.error}</span>}
      </div>
      <ol className="space-y-1.5">
        {ok.map((c, i) => (
          <li key={i} className="rounded-md border bg-card px-2.5 py-1.5">
            <div>{c.text}</div>
            <div className="mt-0.5 flex flex-wrap gap-1">
              {c.refs.map((r) => <Link key={r} href={refHref(r)} className="font-mono text-[10.5px] text-sky-700 hover:underline">{r}</Link>)}
            </div>
          </li>
        ))}
      </ol>
      {bad.length > 0 && (
        <details className="rounded-md border border-rose-200 bg-rose-50/50 px-2.5 py-1.5 text-xs" open>
          <summary className="flex cursor-pointer items-center gap-1 font-medium text-rose-800"><ShieldX className="size-3.5" />Rejected — not supported by the evidence ({bad.length})</summary>
          <ul className="mt-1 space-y-1">
            {bad.map((c, i) => <li key={i}><s className="text-slate-500">{c.text}</s><div className="text-rose-700">{c.problems.join("; ")}</div></li>)}
          </ul>
        </details>
      )}
    </div>
  );
}
