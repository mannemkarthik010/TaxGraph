"use client";

import { useState } from "react";
import Link from "next/link";
import { CheckCircle2, Clock, FastForward, ShieldAlert, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, useApi, useMutate } from "@/lib/api";
import type { Amendment, FilingEvent, FilingState } from "@/lib/filing-types";
import { dateTime, money } from "@/lib/format";
import { useRefreshAfter } from "@/lib/refresh";
import type { Me } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Chip, ErrorState, Loading, Panel } from "../primitives";

/** API errors may carry structured detail ({message, checks}); show them as words. */
export function errorText(e: unknown): string {
  if (!(e instanceof ApiError)) return "Failed";
  try {
    const d = JSON.parse(e.detail);
    if (d.message) return `${d.message} ${(d.checks ?? []).map((c: { label: string; count: number }) => `${c.label} (${c.count})`).join("; ")}`;
  } catch {}
  return e.detail;
}

const MAIN = ["preparing", "ready_for_review", "partner_approved", "client_approved", "ready_to_file", "submitted", "accepted", "filed", "frozen"];

export function Stepper({ s }: { s: FilingState }) {
  const at = MAIN.indexOf(s.state === "rejected" ? "submitted" : s.state);
  return (
    <ol className="flex flex-wrap items-center gap-1.5 text-xs" aria-label="Filing lifecycle">
      {MAIN.map((k, i) => {
        const label = s.states.find((x) => x.key === k)?.label ?? k;
        const current = k === s.state || (s.state === "rejected" && k === "submitted");
        return (
          <li key={k} className="flex items-center gap-1.5">
            <span aria-current={current ? "step" : undefined} className={cn("rounded-md px-2 py-1",
              current ? (s.state === "rejected" ? "bg-rose-600 text-white" : "bg-primary text-primary-foreground")
                : i < at ? "bg-emerald-50 text-emerald-800 ring-1 ring-emerald-200" : "bg-slate-100 text-slate-500")}>
              {s.state === "rejected" && k === "submitted" ? "Rejected" : label}
            </span>
            {i < MAIN.length - 1 && <span className="text-slate-300">→</span>}
          </li>
        );
      })}
    </ol>
  );
}

function EventDetail({ e }: { e: FilingEvent }) {
  const d = e.detail ?? {};
  return (
    <div className="mt-0.5 space-y-0.5 text-[11px] text-slate-600">
      {e.note && <div>{e.note}</div>}
      {d.submissions?.map((s) => (
        <div key={s.submission_id}>
          <Chip tone={s.status === "accepted" ? "good" : s.status === "rejected" ? "bad" : "warn"}>{s.jurisdiction} {s.status}</Chip>{" "}
          <span className="font-mono">{s.submission_id}</span>
          {s.errors?.map((x) => <div key={x.code} className="text-rose-700">{x.code}: {x.message}</div>)}
        </div>
      ))}
      {d.linked_findings && d.linked_findings.length > 0 && (
        <div>TaxProof had flagged this before filing:{" "}
          {d.linked_findings.map((f) => <Link key={f.id} className="text-sky-700 hover:underline" href={`/challenge?finding=${encodeURIComponent(f.id)}`}>{f.title}</Link>)}
        </div>
      )}
      {d.correction && <div>Correction: {d.correction.note} <span className="font-mono">({d.correction.evidence_refs.join(", ")})</span></div>}
      {d.amount && <div className="num">{Object.entries(d.amount).map(([k, v]) => `${k.replace(/_/g, " ")}: ${money(v)}`).join(" · ")}{d.basis && <span className="text-muted-foreground"> — {d.basis}</span>}</div>}
      {d.notices?.map((n) => <div key={n.id}><Link className="text-sky-700 hover:underline" href="/examiner">{n.id}</Link> · {n.type} dated {n.dated}, response due {n.response_due}</div>)}
      {d.fingerprint && <div className="font-mono text-slate-400">approved content {d.fingerprint.sha256.slice(0, 12)}…</div>}
      {d.content_sha256 && <div className="font-mono text-slate-400">snapshot #{d.snapshot_id} {d.content_sha256.slice(0, 12)}…</div>}
    </div>
  );
}

export function FilingLifecycle() {
  const { data: s, error, mutate: reload } = useApi<FilingState>("/api/filing/state");
  const mutate = useMutate();
  const refreshAfter = useRefreshAfter();
  const [open, setOpen] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [refs, setRefs] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (error) return <ErrorState error={error} />;
  if (!s) return <Loading />;

  const run = async (path: string, body?: unknown) => {
    setErr(null);
    setBusy(true);
    try {
      await mutate(path, body ?? {});
      setOpen(null);
      setNote("");
      setRefs("");
      refreshAfter("filing");
      reload();
    } catch (e) {
      setErr(errorText(e));
    } finally {
      setBusy(false);
    }
  };
  const available = (s.actions ?? []).filter((a) => a.available);
  const blocked = (s.actions ?? []).filter((a) => !a.available && a.why_not.length === 1 && !a.why_not[0].startsWith("needs"));
  const n = s.next_event;

  return (
    <div className="space-y-4">
      <Panel title="Lifecycle" actions={<span className="flex items-center gap-1 text-xs text-muted-foreground"><Clock className="size-3.5" />replay clock {dateTime(s.clock)}</span>}>
        <Stepper s={s} />
        {s.actions && (
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {available.map((a) => (
              <Button key={a.action} size="sm" disabled={busy} variant={a.action === "reopen" ? "outline" : "default"}
                onClick={() => (a.needs_note ? setOpen(open === a.action ? null : a.action) : run(`/api/filing/actions/${a.action}`))}>{a.label}</Button>
            ))}
            {available.length === 0 && <span className="text-xs text-muted-foreground">No firm action is open to you at this stage.</span>}
            {blocked.map((a) => <span key={a.action} className="text-[11px] text-muted-foreground">{a.label}: {a.why_not[0]}</span>)}
          </div>
        )}
        {open && (
          <div className="mt-2 space-y-1.5 rounded-md border bg-slate-50 p-2">
            <Textarea aria-label="Reason" value={note} onChange={(e) => setNote(e.target.value)} className="min-h-14 bg-white text-xs"
              placeholder={open === "resubmit" ? "What was corrected after the rejection?" : "Why is the return reopened?"} />
            {open === "resubmit" && <Input aria-label="Evidence" value={refs} onChange={(e) => setRefs(e.target.value)} placeholder="Evidence, e.g. D71 msg-10" className="h-8 bg-white font-mono text-xs" />}
            <div className="flex gap-2">
              <Button size="sm" disabled={busy || !note.trim()} onClick={() => run(`/api/filing/actions/${open}`, { note, evidence_refs: refs.split(/[\s,]+/).filter(Boolean) })}>Confirm</Button>
              <Button size="sm" variant="ghost" onClick={() => setOpen(null)}>Cancel</Button>
            </div>
          </div>
        )}
        {s.awaiting_client && (
          <p className="mt-2 text-[11px] text-amber-800">Waiting for the client to approve the re-approved return in TaxProof (the scripted approval was already used before the reopen).</p>
        )}
        {s.approval && s.approval.client && (
          <p className={cn("mt-2 text-[11px]", s.approval.client_matches ? "text-emerald-700" : "text-rose-700")}>
            {s.approval.client_matches ? "The return is exactly what the client approved." : "The return changed after the client approved it: approval must be given again."}
          </p>
        )}
        {err && <p className="mt-2 text-xs text-rose-700">{err}</p>}
      </Panel>

      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title={<span className="flex items-center gap-1.5"><FastForward className="size-4" />Replay the season</span>}>
          {!n ? <p className="text-xs text-muted-foreground">The scripted timeline is complete.</p> : (
            <div className="space-y-2 text-[13px]">
              <div className="rounded-md border p-2">
                <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground"><span className="font-mono">{n.id}</span> · {dateTime(n.at)}</div>
                <div className="font-medium">{n.label}</div>
                {n.detail && <div className="text-xs text-slate-600">{n.detail}</div>}
                {n.refs.length > 0 && <div className="font-mono text-[11px] text-slate-500">{n.refs.join(" · ")}</div>}
              </div>
              {n.possible ? (
                <Button size="sm" disabled={busy || !n.can_replay} onClick={() => run("/api/filing/replay")}>Replay this event</Button>
              ) : <p className="text-xs text-amber-800">Waiting: {n.needs}</p>}
              <details className="text-[11px] text-muted-foreground">
                <summary className="cursor-pointer">Still to come ({s.upcoming?.length ?? 0})</summary>
                <ul>{s.upcoming?.map((u) => <li key={u.id}>{dateTime(u.at)} · {u.label}</li>)}</ul>
              </details>
            </div>
          )}
        </Panel>
        <Panel title="History">
          {s.history.length === 0 ? <p className="text-xs text-muted-foreground">Nothing yet: the return is being prepared.</p> : (
            <ol className="space-y-2 text-[13px]">
              {s.history.slice().reverse().map((e) => (
                <li key={e.id} className="border-l-2 pl-2" data-testid={`filing-event-${e.action}`}>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Chip tone={e.kind === "replay" ? "engine" : "info"}>{e.kind === "replay" ? "replayed" : "firm"}</Chip>
                    <span className="font-medium">{e.label}</span>
                    <span className="text-[11px] text-muted-foreground">{dateTime(e.at)}{e.actor && ` · ${e.actor}`}</span>
                    {e.from_state !== e.to_state && <span className="text-[11px] text-muted-foreground">{e.from_state} → {e.to_state}</span>}
                  </div>
                  <EventDetail e={e} />
                </li>
              ))}
            </ol>
          )}
        </Panel>
      </div>

      {s.snapshots && s.snapshots.length > 0 && (
        <Panel title="Filed snapshots">
          <ul className="space-y-1 text-[13px]">
            {s.snapshots.map((x) => (
              <li key={x.id} className="flex flex-wrap items-center gap-2">
                {x.integrity ? <ShieldCheck className="size-4 text-emerald-600" /> : <ShieldAlert className="size-4 text-rose-600" />}
                <span className="font-medium">{x.kind === "original" ? "Original return" : `Amendment ${x.number}`}</span>
                <span className="text-xs text-muted-foreground">filed {dateTime(x.filed_at)}</span>
                <span className="font-mono text-[11px] text-slate-500">{x.content_sha256.slice(0, 16)}…</span>
                <Chip tone={x.integrity ? "good" : "bad"}>{x.integrity ? "hash verified" : "TAMPERED"}</Chip>
                <Link className="text-xs text-sky-700 hover:underline" href={`/filing/certificate?snapshot=${x.id}`}>certificate</Link>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-[11px] text-muted-foreground">A snapshot is written once and never changed; its hash is in the audit chain. Later changes are amendments.</p>
        </Panel>
      )}
      {s.snapshots && s.snapshots.length > 0 && <Amendments />}
    </div>
  );
}

function Amendments() {
  const { data, error, mutate: reload } = useApi<Amendment[]>("/api/amendments");
  const { data: me } = useApi<Me>("/api/session/me");
  const mutate = useMutate();
  const refreshAfter = useRefreshAfter();
  const [reason, setReason] = useState("");
  const [line, setLine] = useState("");
  const [value, setValue] = useState("");
  const [why, setWhy] = useState("");
  const [err, setErr] = useState<string | null>(null);
  if (error) return <ErrorState error={error} />;
  if (!data) return <Loading rows={2} />;
  const run = async (path: string, body?: unknown) => {
    setErr(null);
    try {
      await mutate(path, body ?? {});
      refreshAfter("filing");
      reload();
    } catch (e) {
      setErr(errorText(e));
    }
  };
  const draft = data.find((a) => a.status === "draft" || a.status === "approved");
  const can = !!me?.permissions.includes("adjust");
  return (
    <Panel title="Amendments">
      {data.map((a) => (
        <article key={a.id} className="mb-2 rounded-md border p-2 text-[13px]">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="font-medium">#{a.id}</span>
            <Chip tone={a.status === "filed" ? "good" : a.status === "approved" ? "info" : a.status === "withdrawn" ? "muted" : "warn"}>{a.status}</Chip>
            <span className="text-xs text-muted-foreground">{a.reason}</span>
          </div>
          <ul className="mt-1 text-xs">
            {a.changes.map((x) => (
              <li key={x.line}><span className="font-mono">{x.line}</span> {x.label}: {money(x.filed_value)} → {money(x.amended_value)}{" "}
                <span className="text-muted-foreground">(est. federal {money(x.effect?.federal ?? 0, { sign: true })} · CA {money(x.effect?.california ?? 0, { sign: true })}) — {x.reason}</span></li>
            ))}
          </ul>
          <div className="mt-1 flex gap-2">
            {a.status === "draft" && me?.role === "partner" && me.id !== a.created_by_id && a.changes.length > 0 &&
              <Button size="sm" className="h-7 text-xs" onClick={() => run(`/api/amendments/${a.id}/approve`)}>Partner approve</Button>}
            {a.status === "approved" && ["reviewer", "partner"].includes(me?.role ?? "") &&
              <Button size="sm" className="h-7 text-xs" onClick={() => run(`/api/amendments/${a.id}/file`)}>File amendment</Button>}
            {(a.status === "draft" || a.status === "approved") && can &&
              <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => run(`/api/amendments/${a.id}/withdraw`)}>Withdraw</Button>}
          </div>
          {a.status === "draft" && can && (
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <Input aria-label="Line" value={line} onChange={(e) => setLine(e.target.value)} placeholder="Line, e.g. F8283.A1.vehicle" className="h-7 w-48 font-mono text-xs" />
              <Input aria-label="Amended value" value={value} onChange={(e) => setValue(e.target.value)} placeholder="Amended value" type="number" className="h-7 w-32 text-xs" />
              <Input aria-label="Change reason" value={why} onChange={(e) => setWhy(e.target.value)} placeholder="Reason" className="h-7 w-64 text-xs" />
              <Button size="sm" className="h-7 text-xs" disabled={!line || value === "" || why.length < 3}
                onClick={() => run(`/api/amendments/${a.id}/changes`, { line, amended_value: Number(value), reason: why })}>Add change</Button>
            </div>
          )}
        </article>
      ))}
      {!draft && can && (
        <div className="flex gap-2">
          <Input aria-label="Amendment reason" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Why amend the filed return?" className="h-8 text-xs" />
          <Button size="sm" disabled={reason.length < 10} onClick={() => run("/api/amendments", { reason })}>Start amendment</Button>
        </div>
      )}
      <p className="mt-2 flex items-center gap-1 text-[11px] text-muted-foreground"><CheckCircle2 className="size-3.5" />Filing an amendment creates a new snapshot; the original return stays exactly as filed.</p>
      {err && <p className="mt-1 text-xs text-rose-700">{err}</p>}
    </Panel>
  );
}

/** The client's view: where the return is, and — after a reopen — their approval and Form 8879 signature. */
export function ClientLifecycle() {
  const { data: s, mutate: reload } = useApi<FilingState>("/api/filing/state");
  const mutate = useMutate();
  const [confirm, setConfirm] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  if (!s) return <Loading />;
  const approve = async () => {
    setErr(null);
    try {
      await mutate("/api/filing/client-approval", { confirm });
      reload();
    } catch (e) {
      setErr(errorText(e));
    }
  };
  return (
    <Panel title="Where your return is">
      <Stepper s={s} />
      {s.client_can_approve && (
        <div className="mt-3 space-y-2 rounded-md border border-sky-200 bg-sky-50/60 p-3 text-[13px]">
          <p>Your return changed after you approved it and your preparer&apos;s partner has approved the new version. Please review it and sign again.</p>
          <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={confirm} onChange={(e) => setConfirm(e.target.checked)} />
            I reviewed the return and authorize its e-filing (Form 8879 / FTB 8879).</label>
          <Button size="sm" disabled={!confirm} onClick={approve}>Approve and sign</Button>
          {err && <p className="text-xs text-rose-700">{err}</p>}
        </div>
      )}
    </Panel>
  );
}
