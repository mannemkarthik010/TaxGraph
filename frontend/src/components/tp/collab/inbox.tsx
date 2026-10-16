"use client";

import { useState } from "react";
import Link from "next/link";
import { AlertOctagon, ArrowUpRight, CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, useApi, useMutate } from "@/lib/api";
import type { InboxAction, InboxGroupKey, InboxItem, InboxResponse, Reopened } from "@/lib/collab-types";
import { dateTime, money } from "@/lib/format";
import { proveHref } from "@/lib/links";
import { useRefreshAfter } from "@/lib/refresh";
import type { UserRow } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Chip, ErrorState, Loading } from "../primitives";
import { AskClientForm } from "./client-questions";
import { JudgmentForm } from "./judgments";

const SOURCE: Record<InboxItem["source"], { label: string; tone: "info" | "engine" | "neutral" | "warn" }> = {
  finding: { label: "TaxProof finding", tone: "info" },
  diagnostic: { label: "Engine diagnostic", tone: "engine" },
  note: { label: "Review note", tone: "neutral" },
  adjustment: { label: "Approval", tone: "warn" },
  judgment: { label: "Judgment review", tone: "warn" },
  question: { label: "Client question", tone: "neutral" },
};
const SEVERITY_TONE: Record<string, "bad" | "warn" | "neutral" | "muted"> = { critical: "bad", high: "bad", medium: "warn", low: "neutral", info: "muted" };
const ACTION_LABEL: Record<InboxAction, string> = {
  resolve: "Resolve", accept: "Accept with explanation", assign: "Assign", escalate: "Escalate", ask_client: "Ask client",
  record_judgment: "Record judgment", create_adjustment: "Create adjustment",
};

function ReopenedNote({ r }: { r: Reopened }) {
  if (!r.length) return null;
  return (
    <p className="mt-1 rounded bg-rose-50 px-2 py-1 text-xs text-rose-800">
      Sign-offs reopened: {r.map((x) => `${x.area} ${x.level}`).join(", ")} — {r[0].reason.detail}
    </p>
  );
}

function TextAction({ action, item, onDone, onCancel }: { action: "resolve" | "accept" | "escalate"; item: InboxItem; onDone: () => void; onCancel: () => void }) {
  const mutate = useMutate();
  const [note, setNote] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const placeholder = { resolve: "How was it resolved?", accept: "Why is it acceptable as it stands? (recorded for the reviewer and the file)",
                        escalate: "What does the partner need to decide?" }[action];
  const submit = async () => {
    setErr(null);
    try {
      await mutate(`/api/inbox/${action}`, { key: item.key, note });
      onDone();
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : "Failed");
    }
  };
  return (
    <div className="space-y-1.5 rounded-md border bg-slate-50 p-2">
      <Textarea aria-label={placeholder} value={note} onChange={(e) => setNote(e.target.value)} placeholder={placeholder} className="min-h-14 bg-white text-xs" />
      <div className="flex gap-2">
        <Button size="sm" onClick={submit} disabled={!note.trim()}>{ACTION_LABEL[action]}</Button>
        <Button size="sm" variant="ghost" onClick={onCancel}>Cancel</Button>
      </div>
      {err && <p className="text-xs text-rose-700">{err}</p>}
    </div>
  );
}

function AssignAction({ item, onDone, onCancel }: { item: InboxItem; onDone: () => void; onCancel: () => void }) {
  const mutate = useMutate();
  const { data: users } = useApi<UserRow[]>("/api/session/users");
  const staff = (users ?? []).filter((u) => u.kind === "staff" && ["preparer", "reviewer", "partner", "quality_reviewer"].includes(u.role));
  const [who, setWho] = useState(item.assignee_id ?? "");
  const [err, setErr] = useState<string | null>(null);
  const submit = async () => {
    setErr(null);
    try {
      await mutate("/api/inbox/assign", { key: item.key, assignee_id: who });
      onDone();
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : "Failed");
    }
  };
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-md border bg-slate-50 p-2 text-xs">
      <select aria-label="Assignee" value={who} onChange={(e) => setWho(e.target.value)} className="rounded border bg-white px-1 py-1">
        <option value="">Choose…</option>
        {staff.map((u) => <option key={u.id} value={u.id}>{u.name} ({u.role_label})</option>)}
      </select>
      <Button size="sm" disabled={!who} onClick={submit}>Assign</Button>
      <Button size="sm" variant="ghost" onClick={onCancel}>Cancel</Button>
      {err && <span className="text-rose-700">{err}</span>}
    </div>
  );
}

export function InboxCard({ item, onChange }: { item: InboxItem; onChange: () => void }) {
  const mutate = useMutate();
  const refreshAfter = useRefreshAfter();
  const [open, setOpen] = useState<InboxAction | null>(null);
  const [reopened, setReopened] = useState<Reopened>([]);
  const [err, setErr] = useState<string | null>(null);
  const done = (r: Reopened = []) => {
    setOpen(null);
    setReopened(r);
    refreshAfter("collab");
    onChange();
  };
  const createAdjustment = async () => {
    setErr(null);
    try {
      const r = await mutate<{ id: number; reopened_signoffs: Reopened }>("/api/adjustments/from-finding",
        { finding_id: item.links.finding_id, apply: true });
      refreshAfter("adjustment");
      done(r.reopened_signoffs);
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : "Failed");
    }
  };
  const src = SOURCE[item.source];
  const lineRefs = item.refs.filter((r) => r.startsWith("line:"));
  return (
    <article className={cn("rounded-lg border bg-card p-3 text-[13px]", item.blocks_filing && "border-rose-200", item.status === "handled" && "opacity-75")}
             data-testid={`inbox-item-${item.key}`}>
      <header className="flex flex-wrap items-center gap-1.5">
        <Chip tone={src.tone}>{src.label}</Chip>
        <Chip tone={SEVERITY_TONE[item.severity] ?? "neutral"}>{item.severity}</Chip>
        {item.group === "blockers" && <Chip tone="muted">{item.nature_label}</Chip>}
        {item.escalated && item.status === "open" && <Chip tone="bad">escalated</Chip>}
        {item.areas.map((a) => <Link key={a} href={`/return/area/${a}`}><Chip tone="muted">{a}</Chip></Link>)}
        {item.assignee && <Chip tone="info">→ {item.assignee}</Chip>}
        {item.status === "handled" && <Chip tone="good"><CheckCircle2 className="size-3" />{item.handled?.label}</Chip>}
      </header>
      <h3 className="mt-1 font-medium text-slate-900">{item.title}</h3>
      <p className="mt-0.5 line-clamp-3 text-xs text-slate-600">{item.summary}</p>
      {item.blocks_filing && item.blocking_reason && (
        <p className="mt-1 flex items-center gap-1 text-[11px] text-rose-700"><AlertOctagon className="size-3.5" />{item.blocking_reason}</p>
      )}
      {item.escalation_note && item.status === "open" && <p className="mt-1 text-[11px] text-rose-800">Escalation: {item.escalation_note}</p>}
      <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
        {item.detail.effect && typeof item.detail.effect.federal === "number" && (
          <span className="num">est. federal {money(item.detail.effect.federal, { sign: true })} · CA {money(item.detail.effect.california, { sign: true })}</span>
        )}
        {lineRefs.slice(0, 3).map((r) => <Link key={r} href={proveHref(r)} className="font-mono text-sky-700 hover:underline">{r.split(":")[2]}</Link>)}
        {item.links.finding_id && <Link href={`/challenge?finding=${encodeURIComponent(item.links.finding_id)}`} className="inline-flex items-center gap-0.5 text-sky-700 hover:underline">finding<ArrowUpRight className="size-3" /></Link>}
        {item.source === "adjustment" && <Link href="/return?tab=adjustments" className="text-sky-700 hover:underline">open in Adjustments</Link>}
        {item.source === "judgment" && <Link href="/review?tab=judgments" className="text-sky-700 hover:underline">open in Judgment Ledger</Link>}
        {item.source === "question" && <Link href="/review?tab=questions" className="text-sky-700 hover:underline">open question</Link>}
        {(item.links.questions ?? []).map((q) => <span key={q.id}>client question #{q.id} ({q.status})</span>)}
        {item.handled?.note && <span>“{item.handled.note}”</span>}
      </div>
      {item.actions.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {item.actions.map((a) => (
            <Button key={a} size="sm" variant={a === "create_adjustment" || a === "record_judgment" ? "default" : "outline"} className="h-7 text-xs"
              onClick={() => (a === "create_adjustment" ? createAdjustment() : setOpen(open === a ? null : a))}>{ACTION_LABEL[a]}</Button>
          ))}
        </div>
      )}
      <div className="mt-2 empty:hidden">
        {(open === "resolve" || open === "accept" || open === "escalate") && <TextAction action={open} item={item} onDone={() => done()} onCancel={() => setOpen(null)} />}
        {open === "assign" && <AssignAction item={item} onDone={() => done()} onCancel={() => setOpen(null)} />}
        {open === "ask_client" && <AskClientForm itemKey={item.key} title={item.title} onDone={() => done()} onCancel={() => setOpen(null)} />}
        {open === "record_judgment" && <JudgmentForm itemKey={item.key} onDone={(j) => done(j.reopened_signoffs)} onCancel={() => setOpen(null)} />}
      </div>
      <ReopenedNote r={reopened} />
      {err && <p className="mt-1 text-xs text-rose-700">{err}</p>}
      {item.history.length > 0 && (
        <details className="mt-1 text-[11px] text-muted-foreground">
          <summary className="cursor-pointer">history ({item.history.length})</summary>
          <ul>{item.history.map((h, i) => <li key={i}>{dateTime(h.at)} · {h.by_name ?? h.by} · {h.action}{h.note ? ` — ${h.note}` : ""}</li>)}</ul>
        </details>
      )}
    </article>
  );
}

export function UncertaintyInbox() {
  const [group, setGroup] = useState<InboxGroupKey | "all">("all");
  const [mine, setMine] = useState(false);
  const [handled, setHandled] = useState(false);
  const { data, error, mutate: reload } = useApi<InboxResponse>(`/api/inbox?include_handled=${handled}&mine=${mine}`);
  if (error) return <ErrorState error={error} />;
  if (!data) return <Loading />;
  const groups = data.groups.filter((g) => group === "all" || g.key === group);
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-1.5" role="tablist" aria-label="Inbox groups">
        <button onClick={() => setGroup("all")} className={cn("rounded-md px-2 py-1 text-xs", group === "all" ? "bg-slate-800 text-white" : "bg-slate-100 text-slate-700")}>
          All <span className="num">{data.totals.open}</span></button>
        {data.groups.map((g) => (
          <button key={g.key} onClick={() => setGroup(g.key)} role="tab" aria-selected={group === g.key}
            className={cn("rounded-md px-2 py-1 text-xs", group === g.key ? "bg-slate-800 text-white" : g.key === "blockers" && g.open ? "bg-rose-50 text-rose-800 ring-1 ring-rose-200" : "bg-slate-100 text-slate-700")}>
            {g.label} <span className="num">{g.open}</span></button>
        ))}
        <span className="ml-auto flex items-center gap-3 text-xs text-muted-foreground">
          <label className="flex items-center gap-1"><input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} /> assigned to me ({data.totals.mine})</label>
          <label className="flex items-center gap-1"><input type="checkbox" checked={handled} onChange={(e) => setHandled(e.target.checked)} /> show handled ({data.totals.handled})</label>
        </span>
      </div>
      {groups.every((g) => g.items.length === 0) && <p className="py-8 text-center text-xs text-muted-foreground">Nothing here.</p>}
      {groups.filter((g) => g.items.length > 0).map((g) => (
        <section key={g.key}>
          <h3 className={cn("mb-1.5 text-xs font-semibold uppercase tracking-wide", g.key === "blockers" ? "text-rose-700" : "text-slate-500")}>
            {g.label} · {g.open} open
          </h3>
          <div className="space-y-2">{g.items.map((i) => <InboxCard key={i.key} item={i} onChange={reload} />)}</div>
        </section>
      ))}
    </div>
  );
}
