"use client";

import { useState } from "react";
import Link from "next/link";
import { EyeOff, FileCheck2, Landmark } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, useApi, useMutate } from "@/lib/api";
import type { ExaminerItem, ExaminerNotice, ExaminerOverview, FiledBasis, NoticeResponse } from "@/lib/filing-types";
import { date, dateTime, money } from "@/lib/format";
import { proveHref } from "@/lib/links";
import { useRefreshAfter } from "@/lib/refresh";
import type { Me } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Chip, ErrorState, Loading, Panel } from "../primitives";
import { errorText } from "./lifecycle";

const BASIS: Record<FiledBasis, { label: string; tone: "neutral" | "info" | "good" | "warn" | "bad" }> = {
  engine: { label: "engine figure", tone: "neutral" },
  adjustment: { label: "adjusted", tone: "info" },
  amendment: { label: "amended", tone: "info" },
  derived: { label: "recomputed exactly", tone: "good" },
  estimate_rates: { label: "estimate (rates)", tone: "warn" },
  not_recomputed: { label: "NOT recomputed", tone: "bad" },
};

export function BasisChip({ basis }: { basis?: FiledBasis | null }) {
  if (!basis) return null;
  const b = BASIS[basis];
  return <Chip tone={b.tone}>{b.label}</Chip>;
}

function H({ children }: { children: React.ReactNode }) {
  return <h3 className="mb-1 mt-3 text-[11px] font-semibold uppercase tracking-wide text-slate-500">{children}</h3>;
}

/** One examined item: reported amount, evidence, calculation, adjustments, verification, judgment, filed result. */
export function ExaminedItem({ line }: { line: string }) {
  const { data: x, error } = useApi<ExaminerItem>(`/api/examiner/item?line=${encodeURIComponent(line)}`);
  if (error) return <ErrorState error={error} />;
  if (!x) return <Loading />;
  const docs = x.evidence.filter((e) => e.kind === "Document" || e.kind === "Page");
  const values = x.evidence.filter((e) => e.kind !== "Document" && e.kind !== "Page");
  return (
    <article className="rounded-lg border bg-card p-4 text-[13px]" data-testid={`examined-${line}`}>
      <header className="flex flex-wrap items-baseline justify-between gap-2">
        <div><span className="font-mono text-xs text-slate-500">{x.line.key}</span> <span className="text-base font-semibold">{x.line.label}</span></div>
        <div className="text-right">
          <div className="flex items-center justify-end gap-1.5"><BasisChip basis={x.reported.basis} /><span className="num text-xl font-semibold">{money(x.reported.filed_value)}</span></div>
          <div className="text-[11px] text-muted-foreground">reported{x.reported.original_filed_value !== x.reported.filed_value && x.reported.original_filed_value !== null
            ? ` (amended; originally ${money(x.reported.original_filed_value)})` : ""} · engine computed {money(x.reported.engine_value)}</div>
        </div>
      </header>
      {x.reported.basis !== "engine" && x.reported.basis_note && (
        <p className={cn("mt-2 rounded px-2 py-1 text-xs", x.reported.basis === "not_recomputed" ? "bg-rose-50 text-rose-800" : "bg-slate-50 text-slate-700")}>
          {x.reported.basis_note}{x.reported.affected_by.length > 0 && <> ({x.reported.affected_by.join(", ")})</>}
        </p>
      )}
      <H>Calculation</H>
      <p>{x.calculation.rule && <span className="font-mono text-xs">{x.calculation.rule}</span>} {x.calculation.description}</p>
      {x.calculation.engine_note && <p className="text-xs text-slate-600">{x.calculation.engine_note}</p>}
      {x.calculation.inputs.length > 0 && <ul className="text-xs">{x.calculation.inputs.map((i) => <li key={i.key}><span className="font-mono">{i.key}</span> {i.label}: <span className="num">{money(i.filed_value)}</span> {i.basis && i.basis !== "engine" && <BasisChip basis={i.basis} />}</li>)}</ul>}
      <H>Evidence ({x.evidence.length})</H>
      <div className="flex flex-wrap gap-1">{docs.map((d) => <Link key={d.ref} href={proveHref(d.ref)}><Chip tone="neutral">{d.ref} · {d.label}</Chip></Link>)}</div>
      <ul className="mt-1 max-h-48 overflow-auto text-xs">{values.map((v) => <li key={v.ref}><span className="font-mono text-slate-500">{v.ref}</span> {v.label}{v.value !== null && v.value !== undefined && <> · <span className="num">{String(typeof v.value === "number" ? money(v.value) : v.value)}</span></>}{v.cited_by_workpaper && <Chip tone="muted" className="ml-1">cited</Chip>}</li>)}</ul>
      {x.client_answers.length > 0 && <><H>Client confirmations</H><ul className="text-xs">{x.client_answers.map((q) => <li key={q.ref}><b>{q.answered_by}:</b> {q.answer}</li>)}</ul></>}
      <H>Adjustment history</H>
      {x.adjustment_history.length === 0 ? <p className="text-xs text-muted-foreground">Filed as the engine computed it.</p> : (
        <ul className="text-xs">{x.adjustment_history.map((a) => <li key={a.id}>#{a.id}: {money(a.original_value)} → {money(a.adjusted_value)} {a.unit !== "USD" && a.unit} — {a.reason} <span className="text-muted-foreground">(by {a.created_by}, approved by {a.approved_by ?? "—"})</span></li>)}</ul>)}
      <H>Verification</H>
      {x.verifications.length === 0 ? <p className="text-xs text-muted-foreground">No verification recorded on this line or its evidence.</p> : (
        <ul className="text-xs">{x.verifications.map((v) => <li key={v.id}>{v.method.replace(/_/g, " ")} of <span className="font-mono">{v.target_ref}</span> by {v.by}, {dateTime(v.at)}{v.note && ` — ${v.note}`}</li>)}</ul>)}
      {x.judgments.length > 0 && <><H>Professional judgment</H><ul className="text-xs">{x.judgments.map((j) => <li key={j.id}><b>{j.topic}</b>: {j.decision}. {j.rationale} <i>Authority: {j.authority}.</i> Reviewed by {j.reviewed_by}{j.partner_by && `, approved by ${j.partner_by}`}.</li>)}</ul></>}
      {x.independent_checks.length > 0 && <><H>Independent reconciliation</H><ul className="text-xs">{x.independent_checks.map((c) => (
        <li key={c.id}><Chip tone={c.status === "pass" ? "good" : "warn"}>{c.status}</Chip> {c.title}{c.breakdown.length > 0 && <>: {c.breakdown.map((b) => `${b.label} ${typeof b.value === "number" ? money(b.value) : b.value}`).join(" · ")}</>}</li>))}</ul></>}
      <H>Filed result</H>
      <p className="text-xs">Filed {dateTime(x.filed_result.filed_at)} · accepted {Object.entries(x.filed_result.accepted).map(([j, d]) => `${j} ${date(d)}`).join(", ")}
        {x.filed_result.amendments.map((a) => <span key={a.number}> · amendment {a.number}: {money(a.filed_value)} → {money(a.amended_value)} ({a.reason})</span>)}
        {" "}<Chip tone={x.filed_result.integrity ? "good" : "bad"}>{x.filed_result.integrity ? "snapshot verified" : "snapshot altered"}</Chip></p>
    </article>
  );
}

function ResponsePackage({ notice, onChange }: { notice: ExaminerNotice; onChange: () => void }) {
  const { data: r, error, mutate: reload } = useApi<NoticeResponse>(notice.response_id ? `/api/notices/${notice.id}/response` : null);
  const { data: me } = useApi<Me>("/api/session/me");
  const mutate = useMutate();
  const refreshAfter = useRefreshAfter();
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  const [err, setErr] = useState<string | null>(null);
  const run = async (path: string, body?: unknown) => {
    setErr(null);
    try {
      await mutate(path, body ?? {});
      refreshAfter("filing");
      reload();
      onChange();
    } catch (e) {
      setErr(e instanceof ApiError ? errorText(e) : "Failed");
    }
  };
  if (!notice.received_at) return <p className="text-xs text-muted-foreground">Not received yet (replay the season on the Filing page).</p>;
  if (!notice.response_id) return (
    <div className="space-y-1">
      <Button size="sm" onClick={() => run(`/api/notices/${notice.id}/response`)}>Assemble response package</Button>
      <p className="text-[11px] text-muted-foreground">Collects, for each item, the filed amounts, reconciliations and every exhibit connected to those lines in the filed workpaper.</p>
      {err && <p className="text-xs text-rose-700">{err}</p>}
    </div>
  );
  if (error) return <ErrorState error={error} />;
  if (!r) return <Loading rows={2} />;
  const draft = r.status === "draft";
  return (
    <div className="space-y-3 text-[13px]" data-testid="response-package">
      <div className="flex flex-wrap items-center gap-2">
        <Chip tone={draft ? "warn" : "good"}>{r.status}</Chip>
        <span className="text-xs text-muted-foreground">prepared by {r.prepared_by}{r.approved_by && ` · approved by ${r.approved_by} ${dateTime(r.approved_at)}`}</span>
        {r.content_sha256 && <span className="font-mono text-[11px] text-slate-500">{r.content_sha256.slice(0, 16)}…</span>}
      </div>
      <pre className="whitespace-pre-wrap rounded-md border bg-slate-50 p-2 font-sans text-xs">{r.cover_letter}</pre>
      {r.items.map((it, i) => (
        <section key={i} className="rounded-md border p-2">
          <div className="font-medium">Item {i + 1}. {it.text}</div>
          <div className="font-mono text-[11px] text-slate-500">{it.lines.join(" · ")}</div>
          {draft ? (
            <Textarea aria-label={`Explanation ${i + 1}`} value={drafts[i] ?? it.explanation} onChange={(e) => setDrafts((d) => ({ ...d, [i]: e.target.value }))} className="mt-1 min-h-16 text-xs" />
          ) : <p className="mt-1 text-xs">{it.explanation}</p>}
          <details className="mt-1 text-xs"><summary className="cursor-pointer text-sky-700">Exhibits ({it.exhibits.length})</summary>
            <ul className="mt-1 max-h-48 overflow-auto">{it.exhibits.map((e) => <li key={e.ref}><span className="font-mono text-slate-500">{e.ref}</span> <Chip tone="muted">{e.kind}</Chip> {e.label}</li>)}</ul>
          </details>
        </section>
      ))}
      {draft && (
        <div className="flex gap-2">
          <Button size="sm" variant="outline" disabled={Object.keys(drafts).length === 0} onClick={() => run(`/api/notice-responses/${r.id}/edit`, { explanations: drafts })}>Save edits</Button>
          {me?.role === "partner" && me.id !== r.prepared_by_id && <Button size="sm" onClick={() => run(`/api/notice-responses/${r.id}/approve`)}>Partner approve</Button>}
        </div>
      )}
      {err && <p className="text-xs text-rose-700">{err}</p>}
    </div>
  );
}

export function ExaminerMode() {
  const { data: ov, error, mutate: reload } = useApi<ExaminerOverview>("/api/examiner");
  const [line, setLine] = useState<string | null>(null);
  const [q, setQ] = useState("");
  if (error) return <ErrorState error={error} />;
  if (!ov) return <Loading />;
  const notice = ov.notices.find((n) => n.items.length > 0);
  const lines = notice?.items.flatMap((i) => i.lines) ?? [];
  const current = line ?? lines[lines.length - 1] ?? null;
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 rounded-md border border-slate-300 bg-slate-50 px-3 py-2 text-xs text-slate-700">
        <Landmark className="size-4" /><b>Examiner view</b> of the {ov.snapshot.kind === "original" ? "return as filed" : `return as amended (amendment ${ov.snapshot.number})`} on {date(ov.snapshot.filed_at)}.
        <Chip tone={ov.snapshot.integrity ? "good" : "bad"}>{ov.snapshot.integrity ? "snapshot hash verified" : "snapshot altered"}</Chip>
        <span className="flex items-center gap-1 text-muted-foreground"><EyeOff className="size-3.5" />Excluded: {ov.excluded.join("; ")}.</span>
      </div>
      <div className="grid gap-4 lg:grid-cols-[340px_1fr]">
        <div className="space-y-4">
          {ov.notices.map((n) => (
            <Panel key={n.id} title={<span className="flex items-center gap-1.5"><FileCheck2 className="size-4" />{n.agency} {n.type}</span>}>
              <p className="text-xs text-muted-foreground">Dated {date(n.dated)}{n.response_due && ` · response due ${date(n.response_due)}`}{n.received_at ? ` · received ${date(n.received_at)}` : " · not received yet"}</p>
              <ol className="mt-2 space-y-1.5 text-xs">
                {n.items.map((it, i) => (
                  <li key={i}>{it.text}
                    <div className="mt-0.5 flex flex-wrap gap-1">{it.lines.map((k) => (
                      <button key={k} onClick={() => setLine(k)} className={cn("rounded px-1.5 py-0.5 font-mono text-[11px]", current === k ? "bg-slate-800 text-white" : "bg-slate-100 hover:bg-slate-200")}>{k}</button>))}</div>
                  </li>
                ))}
              </ol>
            </Panel>
          ))}
          <Panel title="Examine any filed line">
            <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (q.trim()) setLine(q.trim()); }}>
              <Input aria-label="Line key" value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. SchC.44a" className="h-8 font-mono text-xs" />
              <Button size="sm" type="submit">Open</Button>
            </form>
          </Panel>
        </div>
        <div className="space-y-4">
          {current ? <ExaminedItem line={current} /> : <p className="text-sm text-muted-foreground">Choose a line to examine.</p>}
          {notice && <Panel title={`Response to ${notice.id}`}><ResponsePackage notice={notice} onChange={reload} /></Panel>}
        </div>
      </div>
    </div>
  );
}
