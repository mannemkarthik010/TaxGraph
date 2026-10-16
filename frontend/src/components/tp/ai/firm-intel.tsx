"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ApiError, useApi, useMutate } from "@/lib/api";
import type { AIRun, Budget, StandardsResponse } from "@/lib/ai-types";
import { dateTime, humanize } from "@/lib/format";
import type { Me } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Chip, ErrorState, Loading, Panel } from "../primitives";
import { ProviderBadge } from "./claims";

/** Firm standards: everyone reads them; the firm administrator saves new versions (never edits in place). */
export function StandardsPanel() {
  const { data, error, mutate: reload } = useApi<StandardsResponse>("/api/firm/standards");
  const { data: me } = useApi<Me>("/api/session/me");
  const mutate = useMutate();
  const [edit, setEdit] = useState(false);
  const [pct, setPct] = useState("");
  const [amt, setAmt] = useState("");
  const [thr, setThr] = useState("");
  const [methods, setMethods] = useState<string[]>([]);
  const [note, setNote] = useState("");
  const [err, setErr] = useState<string | null>(null);
  if (error) return <ErrorState error={error} />;
  if (!data) return <Loading />;
  const s = data.standards;
  const admin = !!me?.permissions.includes("manage_firm");
  const start = () => {
    setPct(String(s.variance_review.flag_if_change_over_percent));
    setAmt(String(s.variance_review.and_over_amount));
    setThr(String(s.partner_threshold));
    setMethods(s.verification_types);
    setEdit(true);
  };
  const save = async () => {
    setErr(null);
    try {
      await mutate("/api/firm/standards", { note, changes: {
        variance_review: { ...s.variance_review, flag_if_change_over_percent: Number(pct), and_over_amount: Number(amt) },
        partner_threshold: Number(thr), verification_types: methods } });
      setEdit(false);
      setNote("");
      reload();
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : "Failed");
    }
  };
  return (
    <Panel title={`Firm standards · version ${data.version}`} actions={admin && !edit && <Button size="sm" variant="outline" onClick={start}>Change</Button>}>
      {!edit ? (
        <div className="space-y-2 text-[13px]">
          <p>Variance review: flag a line that moves more than <b>{s.variance_review.flag_if_change_over_percent}%</b> and <b>{s.variance_review.and_over_amount.toLocaleString()}</b> from the prior year.</p>
          <p>Partner approval: adjustments and judgments with a tax effect over <b>{s.partner_threshold.toLocaleString()}</b>.</p>
          <div className="flex flex-wrap gap-1">{s.verification_types.map((v) => <Chip key={v}>{humanize(v)}</Chip>)}</div>
          <ul className="list-disc space-y-0.5 pl-4 text-xs text-slate-700">{s.rules.map((r) => <li key={r}>{r}</li>)}</ul>
        </div>
      ) : (
        <div className="space-y-2 text-xs">
          <div className="flex flex-wrap items-center gap-2">
            <label>Variance % <Input aria-label="Variance percent" type="number" value={pct} onChange={(e) => setPct(e.target.value)} className="h-7 w-20" /></label>
            <label>and over <Input aria-label="Variance amount" type="number" value={amt} onChange={(e) => setAmt(e.target.value)} className="h-7 w-24" /></label>
            <label>Partner threshold <Input aria-label="Partner threshold" type="number" value={thr} onChange={(e) => setThr(e.target.value)} className="h-7 w-24" /></label>
          </div>
          <div className="flex flex-wrap gap-2">{data.known_methods.map((m) => (
            <label key={m} className="flex items-center gap-1"><input type="checkbox" checked={methods.includes(m)}
              onChange={(e) => setMethods((x) => e.target.checked ? [...x, m] : x.filter((y) => y !== m))} />{humanize(m)}</label>))}</div>
          <Input aria-label="Reason for the change" value={note} onChange={(e) => setNote(e.target.value)} placeholder="Why (recorded with the new version)" className="h-8" />
          <div className="flex gap-2"><Button size="sm" disabled={note.trim().length < 5} onClick={save}>Save as version {data.version + 1}</Button>
            <Button size="sm" variant="ghost" onClick={() => setEdit(false)}>Cancel</Button></div>
          <p className="text-muted-foreground">Applies from now on; records already made keep the standard they were made under.</p>
        </div>
      )}
      <details className="mt-2 text-[11px] text-muted-foreground"><summary className="cursor-pointer">History ({data.history.length})</summary>
        <ul>{data.history.map((h) => <li key={h.version}>v{h.version} · {h.note}{h.by && ` · ${h.by} ${dateTime(h.at)}`}</li>)}</ul></details>
      {err && <p className="mt-1 text-xs text-rose-700">{err}</p>}
    </Panel>
  );
}

export function BudgetPanel() {
  const { data, error, mutate: reload } = useApi<Budget>("/api/time/budget");
  const { data: me } = useApi<Me>("/api/session/me");
  const mutate = useMutate();
  const [key, setKey] = useState("");
  const [hours, setHours] = useState("");
  const [day, setDay] = useState("");
  const [note, setNote] = useState("");
  const [err, setErr] = useState<string | null>(null);
  if (error) return <ErrorState error={error} />;
  if (!data) return <Loading />;
  const canLog = !!me?.permissions.includes("create_note");
  const log = async () => {
    setErr(null);
    try {
      await mutate("/api/time", { budget_key: key, hours: Number(hours), worked_on: day, note });
      setHours("");
      setNote("");
      reload();
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : "Failed");
    }
  };
  return (
    <Panel title="Budget vs actual (hours)" actions={<Chip tone={data.total.over ? "bad" : "good"}>{data.total.actual} of {data.total.budget} h</Chip>}>
      <ul className="space-y-1.5 text-[13px]">
        {data.lines.map((l) => (
          <li key={l.budget_key} data-testid={`budget-${l.budget_key}`}>
            <div className="flex items-center justify-between"><span>{l.label}</span>
              <span className={cn("num text-xs", l.over && "font-semibold text-rose-700")}>{l.actual} / {l.budget} h{l.over && " — over budget"}</span></div>
            <div className="h-1.5 rounded bg-slate-100"><div className={cn("h-1.5 rounded", l.over ? "bg-rose-500" : "bg-emerald-500")}
              style={{ width: `${Math.min(100, l.used_pct ?? 0)}%` }} /></div>
          </li>
        ))}
      </ul>
      {canLog && (
        <div className="mt-3 flex flex-wrap items-center gap-1.5 text-xs">
          <select aria-label="Budget line" value={key} onChange={(e) => setKey(e.target.value)} className="h-8 rounded border px-1">
            <option value="">Budget line…</option>{data.lines.map((l) => <option key={l.budget_key} value={l.budget_key}>{l.label}</option>)}</select>
          <Input aria-label="Hours" type="number" step="0.25" value={hours} onChange={(e) => setHours(e.target.value)} placeholder="Hours" className="h-8 w-20" />
          <Input aria-label="Date worked" type="date" value={day} onChange={(e) => setDay(e.target.value)} className="h-8 w-36" />
          <Input aria-label="Time note" value={note} onChange={(e) => setNote(e.target.value)} placeholder="What" className="h-8 w-40" />
          <Button size="sm" disabled={!key || !hours || !day} onClick={log}>Log time</Button>
        </div>
      )}
      {err && <p className="mt-1 text-xs text-rose-700">{err}</p>}
    </Panel>
  );
}

export function AIRunLog() {
  const { data, error } = useApi<AIRun[]>("/api/ai/runs");
  if (error) return null;
  if (!data) return <Loading rows={2} />;
  return (
    <Panel dense title="AI runs (every call, with what it was given and what was rejected)">
      {data.length === 0 ? <p className="p-4 text-xs text-muted-foreground">No AI runs yet.</p> : (
        <ul className="divide-y text-xs">
          {data.map((r) => (
            <li key={r.id} className="flex flex-wrap items-center gap-2 px-4 py-1.5">
              <span className="num w-40 text-muted-foreground">{dateTime(r.created_at)}</span>
              <span className="font-medium">{r.task.replace(/_/g, " ")}</span>
              {r.subject && <code className="text-slate-500">{r.subject}</code>}
              <ProviderBadge run={r} />
              <span>{r.supported} grounded{r.rejected > 0 && <span className="text-rose-700"> · {r.rejected} rejected</span>}</span>
              <span className="text-muted-foreground">by {r.created_by}</span>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
