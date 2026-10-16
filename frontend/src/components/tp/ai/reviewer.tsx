"use client";

import { useState } from "react";
import Link from "next/link";
import { Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ApiError, useApi, useMutate } from "@/lib/api";
import type { AIRun, RiskResponse } from "@/lib/ai-types";
import { dateTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Chip, ErrorState, Loading, Panel } from "../primitives";
import { Claims, refHref } from "./claims";

const TONE = { high: "bad", medium: "warn", low: "neutral" } as const;

/** Generate (and re-read) the reviewer brief. Not a chat: one structured, evidence-grounded brief. */
export function ReviewerBrief() {
  const { data: runs, mutate: reload } = useApi<AIRun[]>("/api/ai/runs");
  const mutate = useMutate();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const latest = runs?.find((r) => r.task === "reviewer_brief");
  const generate = async () => {
    setErr(null);
    setBusy(true);
    try {
      await mutate("/api/ai/brief");
      reload();
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : "Failed");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Panel title={<span className="flex items-center gap-1.5"><Sparkles className="size-4 text-violet-600" />Reviewer brief</span>}
      actions={<Button size="sm" disabled={busy} onClick={generate}>{latest ? "Regenerate" : "Generate brief"}</Button>}>
      {!runs ? <Loading rows={2} /> : latest ? (
        <>
          <p className="mb-2 text-[11px] text-muted-foreground">Generated {dateTime(latest.created_at)} by {latest.created_by}. Ranked from the
            Review Risk Score; every sentence cites its evidence, and anything the evidence does not support is rejected below.</p>
          <Claims run={latest} />
        </>
      ) : <p className="text-xs text-muted-foreground">No brief yet. It ranks what to review first — suspicious evidence, missing documents,
        unexplained differences, prior-year variances, conflicts, incomplete verification and risky judgments — from the open items.</p>}
      {err && <p className="mt-2 text-xs text-rose-700">{err}</p>}
    </Panel>
  );
}

export function RiskBoard() {
  const { data, error } = useApi<RiskResponse>("/api/review/risk");
  const [open, setOpen] = useState<string | null>(null);
  if (error) return <ErrorState error={error} />;
  if (!data) return <Loading />;
  return (
    <div className="grid gap-4 lg:grid-cols-[260px_1fr]">
      <Panel title="Risk by area">
        <ul className="space-y-1 text-[13px]">
          {data.areas.map((a) => (
            <li key={a.area} className="flex items-center gap-2" title={a.reason}>
              <span className="num w-8 text-right font-semibold">{a.score}</span>
              <Chip tone={TONE[a.level as keyof typeof TONE] ?? "neutral"}>{a.level}</Chip>
              <Link className="flex-1 hover:underline" href={`/return/area/${a.area}`}>{a.area}</Link>
              <span className="text-[11px] text-muted-foreground">{a.open_items} open</span>
            </li>
          ))}
        </ul>
        <p className="mt-2 text-[11px] text-muted-foreground">{data.method}</p>
      </Panel>
      <Panel dense title={`Review Risk Score — ${data.items.length} open items`}>
        <ul className="divide-y text-[13px]">
          {data.items.map((it) => (
            <li key={it.key} className="px-4 py-2" data-testid={`risk-${it.key}`}>
              <button className="flex w-full items-center gap-2 text-left" onClick={() => setOpen(open === it.key ? null : it.key)}>
                <span className="num w-8 text-right text-base font-semibold">{it.score}</span>
                <Chip tone={TONE[it.level]}>{it.level}</Chip>
                <span className="flex-1">{it.title}</span>
                <span className="flex gap-0.5">{it.components.map((c) => (
                  <span key={c.key} title={`${c.label}: ${c.points}/${c.max}`} className={cn("h-3 rounded-sm bg-slate-300", c.points >= c.max * 0.8 ? "bg-rose-400" : c.points >= c.max / 2 ? "bg-amber-400" : "bg-slate-300")}
                    style={{ width: `${Math.max(4, c.points)}px` }} />))}</span>
              </button>
              {open === it.key && (
                <ul className="mt-1.5 space-y-1 pl-10 text-xs">
                  {it.components.map((c) => (
                    <li key={c.key}><b className="font-medium">{c.label}</b> <span className="num text-muted-foreground">{c.points}/{c.max}</span> — {c.reason}{" "}
                      {c.refs.slice(0, 4).map((r) => <Link key={r} href={refHref(r)} className="ml-1 font-mono text-[10.5px] text-sky-700 hover:underline">{r}</Link>)}</li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ul>
      </Panel>
    </div>
  );
}

/** "Explain this finding" in the Challenge drawer, grounded only in the finding's evidence. */
export function ExplainFinding({ findingId, version }: { findingId: string; version?: string }) {
  const mutate = useMutate();
  const [run, setRun] = useState<AIRun | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const go = async () => {
    setErr(null);
    setBusy(true);
    try {
      setRun(await mutate<AIRun>("/api/ai/explain", { finding_id: findingId, version }));
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : "Failed");
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="rounded-md border border-violet-200 bg-violet-50/40 p-3 text-xs">
      {!run ? (
        <div className="flex items-center gap-2">
          <Button size="sm" variant="outline" disabled={busy} onClick={go}><Sparkles className="size-3.5" />Explain this finding</Button>
          <span className="text-muted-foreground">Uses only the evidence listed above{version && ` (return ${version})`}; unsupported sentences are rejected.</span>
        </div>
      ) : <Claims run={run} />}
      {err && <p className="mt-1 text-rose-700">{err}</p>}
    </section>
  );
}
