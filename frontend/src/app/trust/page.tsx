"use client";

import { useState } from "react";
import Link from "next/link";
import { CheckCircle2, CircleAlert, OctagonAlert, ShieldCheck, Sparkles, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ApiError, useApi, useMutate } from "@/lib/api";
import type { AIRun } from "@/lib/ai-types";
import type { TrustReport } from "@/lib/twin-types";
import { dateTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Chip, ErrorState, Loading, PageHeader, Panel } from "@/components/tp/primitives";
import { PreventFiling, ScoreDial } from "@/components/tp/twin/dashboard";
import { Claims } from "@/components/tp/ai/claims";

const ICON = { good: CheckCircle2, warn: CircleAlert, bad: XCircle } as const;
const TONE = { good: "text-emerald-600", warn: "text-amber-600", bad: "text-rose-600" } as const;

export default function TrustPage() {
  const { data: r, error } = useApi<TrustReport>("/api/twin/trust");
  const mutate = useMutate();
  const [summary, setSummary] = useState<AIRun | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const summarize = async () => {
    setErr(null);
    try {
      setSummary(await mutate<AIRun>("/api/twin/trust/summary"));
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : "Failed");
    }
  };
  return (
    <div className="space-y-4">
      <PageHeader title="Why should I trust this return?" subtitle="The Return Assurance Twin's answer, computed from the packet and the workpaper — every answer links to its proof."
        actions={<div className="flex gap-2 print:hidden"><Button size="sm" variant="outline" onClick={() => window.print()}>Print</Button>
          <Link href="/overview" className="self-center text-sm text-sky-700 hover:underline">Back to the dashboard</Link></div>} />
      <ErrorState error={error} />
      {!r ? <Loading rows={6} /> : (
        <>
          <div className={cn("flex flex-wrap items-center gap-4 rounded-lg border p-4",
            r.what_prevents_filing.length ? "border-amber-200 bg-amber-50/50" : "border-emerald-200 bg-emerald-50/50")}>
            <ScoreDial score={r.assurance.score} level={r.assurance.level} />
            <div className="flex-1">
              <div className="flex items-center gap-2 text-lg font-semibold"><ShieldCheck className="size-5 text-primary" />{r.verdict}</div>
              <p className="text-xs text-muted-foreground">Return {r.version} · {r.lifecycle.label} · generated {dateTime(r.generated_at)} ·
                <span className="font-mono"> report {r.report_sha256.slice(0, 12)}…</span></p>
            </div>
          </div>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {r.sections.map((s) => {
              const Icon = ICON[s.status];
              return (
                <Link key={s.key} href={s.link} className="rounded-lg border bg-card p-3 hover:border-slate-300" data-testid={`trust-${s.key}`}>
                  <div className="flex items-start gap-2">
                    <Icon className={cn("mt-0.5 size-4 shrink-0", TONE[s.status])} />
                    <div className="flex-1">
                      <div className="text-[13px] font-medium">{s.question}</div>
                      <div className="num text-lg font-semibold">{s.answer}</div>
                      <p className="text-[11px] text-muted-foreground">{s.detail}</p>
                      {s.items.length > 0 && <ul className="mt-1 list-disc pl-4 text-[11px] text-slate-600">{s.items.slice(0, 5).map((x) => <li key={x}>{x}</li>)}</ul>}
                    </div>
                  </div>
                </Link>
              );
            })}
          </div>
          <Panel title={<span className="flex items-center gap-1.5"><OctagonAlert className="size-4 text-rose-600" />What prevents filing?</span>}>
            <PreventFiling blockers={r.what_prevents_filing} />
          </Panel>
          <Panel title={<span className="flex items-center gap-1.5"><Sparkles className="size-4 text-violet-600" />Summary for the partner</span>}
            actions={!summary && <Button size="sm" variant="outline" onClick={summarize}>Summarize</Button>}>
            {summary ? <Claims run={summary} /> : <p className="text-xs text-muted-foreground">A short narrative of this report; every sentence cites the section it rests on, anything else is rejected.</p>}
            {err && <p className="text-xs text-rose-700">{err}</p>}
          </Panel>
          <Panel title="How the assurance score is made">
            <ul className="grid gap-1 text-xs sm:grid-cols-2">{r.assurance.components.map((c) => (
              <li key={c.key}><b className="font-medium">{c.label}</b> <Chip tone="muted">{c.points}/{c.weight}</Chip> — {c.reason}</li>))}</ul>
            <p className="mt-2 text-[11px] text-muted-foreground">{r.assurance.method}</p>
          </Panel>
          <blockquote className="rounded-lg border-l-4 border-primary bg-slate-50 px-4 py-3 text-[15px] font-medium text-slate-800">{r.closing}</blockquote>
        </>
      )}
    </div>
  );
}
