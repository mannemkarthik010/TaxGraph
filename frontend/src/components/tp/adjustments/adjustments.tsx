"use client";

import { useState } from "react";
import { CheckCircle2, History, RotateCcw, Undo2, Zap } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, useApi, useMutate } from "@/lib/api";
import type { Adjustment, Effective, WorkpaperSummary } from "@/lib/adjust-types";
import type { Reopened } from "@/lib/collab-types";
import { dateTime, humanize, money } from "@/lib/format";
import { useRefreshAfter } from "@/lib/refresh";
import type { Me } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Chip, ErrorState, Loading, Panel } from "../primitives";
import { Amt, LineRef } from "../schedules/common";

const STATUS_TONE = { proposed: "info", applied: "good", undone: "muted" } as const;

function errText(e: unknown) {
  if (!(e instanceof ApiError)) return "Failed";
  try {
    const d = JSON.parse(e.detail);
    return d.message ? `${d.message} ${(d.errors ?? []).map((x: { id: number; detail: string }) => `#${x.id}: ${x.detail}`).join(" ")}` : e.detail;
  } catch {
    return e.detail;
  }
}

/** "Sign-offs reopened: business reviewed, business partner" — so the person sees the consequence immediately. */
export function reopenedText(r: Reopened | undefined) {
  return r && r.length ? ` · Sign-offs reopened: ${r.map((x) => `${x.area} ${x.level}`).join(", ")}` : "";
}

export function fmtUnit(v: number, unit: string, sign = false) {
  return unit === "USD" ? money(v, { sign }) : `${money(v, { sign })} ${unit}`;
}

/** Engine totals beside the workpaper estimate after applied adjustments. */
export function WorkpaperEstimate({ s }: { s: WorkpaperSummary }) {
  const rows: [string, keyof WorkpaperSummary["engine"]][] = [
    ["Federal total tax", "federal_total_tax"], ["Federal balance due", "federal_balance_due"],
    ["California total tax", "california_total_tax"], ["California balance due", "california_balance_due"],
  ];
  return (
    <Panel title={`Engine vs workpaper estimate (${s.applied_adjustments} applied)`}>
      <table className="w-full text-[13px]">
        <thead className="text-left text-[10.5px] uppercase tracking-wide text-muted-foreground">
          <tr><th className="font-medium" /><th className="text-right font-medium text-violet-700">Supplied engine</th><th className="text-right font-medium">Workpaper estimate</th><th className="text-right font-medium">Δ</th></tr>
        </thead>
        <tbody>
          {rows.map(([label, k]) => (
            <tr key={k} className="border-t">
              <td className="py-1">{label}</td>
              <td className="text-right"><Amt v={s.engine[k]} /></td>
              <td className="text-right font-medium"><Amt v={s.estimated[k]} /></td>
              <td className="text-right text-muted-foreground"><Amt v={s.estimated[k] - s.engine[k]} sign /></td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-[11px] text-muted-foreground">{s.note}</p>
    </Panel>
  );
}

export function AdjustmentsTab() {
  const { data, error, mutate: reload } = useApi<{ version: string; adjustments: Adjustment[]; summary: WorkpaperSummary }>("/api/adjustments");
  const { data: me } = useApi<Me>("/api/session/me");
  const mutate = useMutate();
  const refreshAfter = useRefreshAfter();
  const [filter, setFilter] = useState<"active" | "all" | "undone">("active");
  const [sel, setSel] = useState<Set<number>>(new Set());
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [openHistory, setOpenHistory] = useState<number | null>(null);
  if (error) return <ErrorState error={error} />;
  if (!data) return <Loading rows={6} />;
  const canAdjust = !!me?.permissions.includes("adjust");
  const rows = data.adjustments.filter((a) => filter === "all" || (filter === "undone" ? a.status === "undone" : a.status !== "undone"));
  const toggle = (id: number) => setSel((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });

  const run = async (action: string, ids: number[]) => {
    setMsg(null);
    try {
      const r = ids.length === 1 ? await mutate<{ reopened_signoffs?: Reopened }>(`/api/adjustments/${ids[0]}/${action}`, {})
        : await mutate<{ reopened_signoffs?: Reopened }>("/api/adjustments/bulk", { action, ids });
      setMsg({ ok: true, text: `${humanize(action)}: ${ids.map((i) => `#${i}`).join(", ")}${reopenedText(r.reopened_signoffs)}` });
      setSel(new Set());
      reload();
      refreshAfter("adjustment");
    } catch (e) {
      setMsg({ ok: false, text: errText(e) });
    }
  };

  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-[1fr_440px]">
        <div className="space-y-2 text-sm text-slate-700">
          <p>Adjustments change the workpaper, never the engine output: each keeps the original value, the adjusted value, who, why, the evidence and an estimated effect. Undo and restore leave a full history.</p>
          <p className="text-xs text-muted-foreground">Firm rule: an adjustment whose estimated tax effect exceeds $1,000 (federal or California) needs partner approval; nobody approves their own adjustment.</p>
        </div>
        <WorkpaperEstimate s={data.summary} />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="inline-flex rounded-md border bg-white p-0.5 text-xs">
          {(["active", "undone", "all"] as const).map((f) => (
            <button key={f} onClick={() => setFilter(f)} className={cn("rounded px-2 py-1", filter === f ? "bg-slate-800 text-white" : "text-slate-600")}>{humanize(f)}</button>
          ))}
        </div>
        {canAdjust && sel.size > 0 && (
          <div role="group" aria-label="Bulk actions" className="flex flex-wrap items-center gap-1.5 rounded-md border bg-slate-50 px-2 py-1 text-xs">
            <span className="font-medium">{sel.size} selected:</span>
            <Button size="sm" variant="outline" onClick={() => run("apply", [...sel])}><Zap className="size-3.5" />Apply</Button>
            <Button size="sm" variant="outline" onClick={() => run("undo", [...sel])}><Undo2 className="size-3.5" />Undo</Button>
            <Button size="sm" variant="outline" onClick={() => run("restore", [...sel])}><RotateCcw className="size-3.5" />Restore</Button>
            <Button size="sm" variant="outline" onClick={() => run("approve", [...sel])}><CheckCircle2 className="size-3.5" />Approve</Button>
            <span className="text-muted-foreground">all or nothing</span>
          </div>
        )}
      </div>
      {msg && <div className={cn("rounded-md border px-3 py-1.5 text-xs", msg.ok ? "border-emerald-200 bg-emerald-50 text-emerald-900" : "border-rose-200 bg-rose-50 text-rose-900")}>{msg.text}</div>}

      <Panel dense>
        {rows.length === 0 ? <p className="p-4 text-sm text-muted-foreground">No adjustments{filter !== "all" ? ` (${filter})` : ""}. Create one from a Challenge finding or a line&apos;s detail drawer.</p> : (
          <ul className="divide-y">
            {rows.map((a) => (
              <li key={a.id} className="px-4 py-3 text-[13px]">
                <div className="flex flex-wrap items-start gap-3">
                  {canAdjust && <input type="checkbox" checked={sel.has(a.id)} onChange={() => toggle(a.id)} className="mt-1" aria-label={`Select adjustment ${a.id}`} />}
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="text-[11px] text-muted-foreground">#{a.id}</span>
                      <Chip tone={STATUS_TONE[a.status]}>{a.status}</Chip>
                      <LineRef k={a.target_line} />
                      <span className="text-slate-600">{a.line?.label}</span>
                      {a.review_required === "partner" ? <Chip tone="bad">partner approval</Chip> : <Chip>reviewer approval</Chip>}
                      {a.approved_by ? <Chip tone="good"><CheckCircle2 className="size-3" />approved by {a.approved_by}</Chip> : a.status !== "undone" && <Chip tone="warn">awaiting approval</Chip>}
                      {a.finding_id && <span className="text-[11px] text-muted-foreground">from finding {a.finding_id}</span>}
                    </div>
                    <div className="mt-1 flex flex-wrap items-baseline gap-x-5 gap-y-1">
                      <span className="num">Original <b>{fmtUnit(a.original_value, a.unit)}</b> → adjusted <b>{fmtUnit(a.adjusted_value, a.unit)}</b>
                        <span className="ml-1.5 text-muted-foreground">Δ {fmtUnit(a.difference, a.unit, true)}</span></span>
                      <span className="text-xs">{a.effect.kind === "none" ? <span className="text-muted-foreground">effect not estimable</span>
                        : <>{a.effect.kind === "balance" ? "Balance due" : "Est. tax"}: federal <b><Amt v={a.effect.federal} sign /></b> · California <b><Amt v={a.effect.california} sign /></b></>}</span>
                    </div>
                    <p className="mt-0.5 line-clamp-2 text-xs text-slate-600">{a.reason}</p>
                    <div className="mt-0.5 text-[11px] text-muted-foreground">
                      {a.created_by} ({humanize(a.created_by_role)}) · {dateTime(a.created_at)}
                      <button onClick={() => setOpenHistory(openHistory === a.id ? null : a.id)} className="ml-2 inline-flex items-center gap-0.5 text-sky-700 hover:underline"><History className="size-3" />history ({a.history.length})</button>
                    </div>
                    {openHistory === a.id && (
                      <ol className="mt-1 space-y-0.5 border-l-2 pl-3 text-[11px] text-slate-600">
                        {a.history.map((h, i) => <li key={i}><b>{h.action}</b> · {h.by_name} ({humanize(h.role)}) · {dateTime(h.at)}{h.note ? ` — ${h.note.slice(0, 120)}` : ""}</li>)}
                      </ol>
                    )}
                  </div>
                  {canAdjust && (
                    <div className="flex shrink-0 flex-wrap gap-1">
                      {a.status === "proposed" && <Button size="sm" onClick={() => run("apply", [a.id])}><Zap className="size-3.5" />Apply</Button>}
                      {a.status !== "undone" && <Button size="sm" variant="outline" onClick={() => run("undo", [a.id])}><Undo2 className="size-3.5" />Undo</Button>}
                      {a.status === "undone" && <Button size="sm" variant="outline" onClick={() => run("restore", [a.id])}><RotateCcw className="size-3.5" />Restore</Button>}
                      {a.status !== "undone" && !a.approved_by && <Button size="sm" variant="outline" onClick={() => run("approve", [a.id])}><CheckCircle2 className="size-3.5" />Approve</Button>}
                    </div>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}

/** In the line drawer: engine value vs effective workpaper value, and a form to adjust the line. */
export function LineAdjustment({ lineKey, version, currentVersion }: { lineKey: string; version: string; currentVersion: string }) {
  const isCurrent = version === currentVersion;
  const { data, mutate: reload } = useApi<Effective>(isCurrent ? `/api/adjustments/effective/${encodeURIComponent(lineKey)}` : null);
  const { data: me } = useApi<Me>("/api/session/me");
  const mutate = useMutate();
  const refreshAfter = useRefreshAfter();
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");
  const [reason, setReason] = useState("");
  const [refs, setRefs] = useState("");
  const [applyNow, setApplyNow] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  if (!isCurrent) return <p className="text-xs text-muted-foreground">Adjustments are made on the current return ({currentVersion}); {version} is superseded.</p>;
  if (!data) return <Loading rows={2} />;
  const canAdjust = !!me?.permissions.includes("adjust");
  const active = data.adjustments.find((a) => a.status !== "undone");
  const submit = async () => {
    setErr(null);
    try {
      await mutate("/api/adjustments", { target_line: lineKey, adjusted_value: Number(value), reason, evidence_refs: refs.split(/[\s,]+/).filter(Boolean), apply: applyNow });
      setOpen(false); setValue(""); setReason(""); setRefs("");
      reload();
      refreshAfter("adjustment");
    } catch (e) {
      setErr(errText(e));
    }
  };
  return (
    <div className="space-y-2 text-xs">
      <div className="grid grid-cols-2 gap-2">
        <div className="rounded-md border border-violet-200 bg-violet-50/50 px-2.5 py-1.5"><div className="text-[10.5px] text-violet-700">Engine value</div><div className="num text-base font-semibold"><Amt v={data.engine_value} /></div></div>
        <div className={cn("rounded-md border px-2.5 py-1.5", data.adjusted && "border-orange-300 bg-orange-50")}><div className="text-[10.5px] text-muted-foreground">Effective workpaper value</div><div className="num text-base font-semibold"><Amt v={data.effective_value} /></div></div>
      </div>
      {data.adjustments.map((a) => (
        <div key={a.id} className={cn("rounded border px-2 py-1", a.status === "undone" && "opacity-60")}>
          <Chip tone={STATUS_TONE[a.status]}>{a.status}</Chip> #{a.id} {fmtUnit(a.original_value, a.unit)} → {fmtUnit(a.adjusted_value, a.unit)} · {a.created_by}
          {a.effect.kind !== "none" && <> · est. federal <Amt v={a.effect.federal} sign /> / CA <Amt v={a.effect.california} sign /></>}
          <div className="text-muted-foreground">{a.reason.slice(0, 160)}</div>
        </div>
      ))}
      {canAdjust && !active && !open && <button onClick={() => setOpen(true)} className="text-sky-700 hover:underline">Adjust this line…</button>}
      {canAdjust && active && <p className="text-muted-foreground">Undo the active adjustment (Return → Adjustments) before making another.</p>}
      {open && (
        <div className="space-y-1.5 rounded-md border bg-slate-50 p-2">
          <Input type="number" value={value} onChange={(e) => setValue(e.target.value)} placeholder={`Adjusted value (engine ${data.engine_value})`} className="h-8 bg-white text-xs" />
          <Textarea value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason (required)" className="min-h-14 bg-white text-xs" />
          <Input value={refs} onChange={(e) => setRefs(e.target.value)} placeholder="Evidence refs, e.g. doc:D23#page3 ev-0404" className="h-7 bg-white font-mono text-[11px]" />
          <label className="flex items-center gap-1.5"><input type="checkbox" checked={applyNow} onChange={(e) => setApplyNow(e.target.checked)} /> apply now (otherwise proposed)</label>
          <div className="flex gap-2">
            <Button size="sm" disabled={value === "" || reason.trim().length < 3} onClick={submit}>Save adjustment</Button>
            <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
          </div>
          {err && <div className="text-rose-700">{err}</div>}
        </div>
      )}
    </div>
  );
}
