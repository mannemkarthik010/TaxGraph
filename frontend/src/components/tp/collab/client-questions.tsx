"use client";

import { useState } from "react";
import Link from "next/link";
import { MessageCircleQuestion } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, useApi, useMutate } from "@/lib/api";
import type { ClientQuestion, Reopened } from "@/lib/collab-types";
import { dateTime } from "@/lib/format";
import { proveHref } from "@/lib/links";
import { useRefreshAfter } from "@/lib/refresh";
import type { Me, UserRow } from "@/lib/types";
import { Chip, ErrorState, Loading } from "../primitives";

const TONE = { asked: "warn", answered: "info", accepted: "good", withdrawn: "muted" } as const;

/** Ask the client from an inbox item. A deterministic first draft; the preparer edits it. */
export function AskClientForm({ itemKey, title, targetRef, onDone, onCancel }: {
  itemKey?: string; title: string; targetRef?: string; onDone: () => void; onCancel: () => void;
}) {
  const mutate = useMutate();
  const refreshAfter = useRefreshAfter();
  const { data: users } = useApi<UserRow[]>("/api/session/users");
  const clients = (users ?? []).filter((u) => u.kind === "client");
  const [text, setText] = useState(`We are finalizing your 2025 return and need your help with: ${title}. Could you confirm the facts?`);
  const [to, setTo] = useState("");
  const [blocking, setBlocking] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [drafting, setDrafting] = useState(false);
  const draft = async () => {
    setErr(null);
    setDrafting(true);
    try {
      const r = await mutate<{ question: string | null; rejected: number }>("/api/ai/draft-question", { item_key: itemKey });
      if (r.question) setText(r.question);
      else setErr("The draft was rejected by the evidence check; write the question yourself.");
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : "Failed");
    } finally {
      setDrafting(false);
    }
  };
  const submit = async () => {
    setErr(null);
    try {
      await mutate("/api/client-questions", { item_key: itemKey ?? null, target_ref: targetRef ?? null, question: text, blocking,
                                              addressed_to_id: to || null });
      refreshAfter("collab");
      onDone();
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : "Failed");
    }
  };
  return (
    <div className="space-y-2 rounded-md border bg-slate-50 p-3 text-xs">
      <Textarea value={text} onChange={(e) => setText(e.target.value)} className="min-h-20 bg-white text-xs" aria-label="Question for the client" />
      {itemKey && (
        <button type="button" disabled={drafting} onClick={draft} className="text-[11px] text-violet-700 hover:underline disabled:opacity-50">
          {drafting ? "Drafting…" : "Draft with AI (grounded in this item; you review before sending)"}
        </button>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <label className="flex items-center gap-1">To
          <select value={to} onChange={(e) => setTo(e.target.value)} className="rounded border bg-white px-1 py-0.5">
            <option value="">the household</option>
            {clients.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}
          </select>
        </label>
        <label className="flex items-center gap-1"><input type="checkbox" checked={blocking} onChange={(e) => setBlocking(e.target.checked)} /> needed before filing</label>
      </div>
      <div className="flex gap-2">
        <Button size="sm" disabled={text.trim().length < 10} onClick={submit}>Send to client</Button>
        <Button size="sm" variant="ghost" onClick={onCancel}>Cancel</Button>
      </div>
      {err && <p className="text-rose-700">{err}</p>}
    </div>
  );
}

function StaffQuestion({ q, canAsk, onChange }: { q: ClientQuestion; canAsk: boolean; onChange: () => void }) {
  const mutate = useMutate();
  const refreshAfter = useRefreshAfter();
  const [note, setNote] = useState("");
  const [resolves, setResolves] = useState(true);
  const [err, setErr] = useState<string | null>(null);
  const [reopened, setReopened] = useState<Reopened>([]);
  const act = async (path: string, body: unknown) => {
    setErr(null);
    try {
      const r = await mutate<{ reopened_signoffs?: Reopened }>(`/api/client-questions/${q.id}/${path}`, body);
      setReopened(r.reopened_signoffs ?? []);
      refreshAfter("collab");
      onChange();
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : "Failed");
    }
  };
  return (
    <article className="rounded-lg border bg-card p-3 text-[13px]">
      <header className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
        <MessageCircleQuestion className="size-4 text-sky-700" />
        <span className="font-medium text-slate-800">#{q.id}</span>
        <Chip tone={TONE[q.status]}>{q.status}</Chip>
        {q.blocking && q.status !== "accepted" && q.status !== "withdrawn" && <Chip tone="bad">needed before filing</Chip>}
        <span>about <code>{q.target_ref}</code> ({q.about})</span>
        <span>· asked by {q.asked_by} {dateTime(q.asked_at)} to {q.addressed_to ?? "the household"}</span>
      </header>
      <p className="mt-1">{q.question}</p>
      {q.answer && (
        <div className="mt-2 rounded-md border-l-2 border-sky-400 bg-sky-50/60 px-2 py-1 text-xs">
          <b className="font-medium">{q.answered_by}</b> · {dateTime(q.answered_at)}<div>{q.answer}</div>
        </div>
      )}
      {q.status === "accepted" && (
        <p className="mt-1 text-xs text-emerald-800">
          Accepted as evidence by {q.accepted_by} {dateTime(q.accepted_at)}{q.acceptance_note && ` — ${q.acceptance_note}`}.{" "}
          {q.target_ref && <Link className="text-sky-700 hover:underline" href={proveHref(q.target_ref)}>See it on the graph</Link>}
        </p>
      )}
      {canAsk && q.status === "answered" && (
        <div className="mt-2 space-y-1.5">
          <Textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder="Why the answer settles the fact (optional)" className="min-h-10 text-xs" />
          {q.item_key && <label className="flex items-center gap-1 text-xs"><input type="checkbox" checked={resolves} onChange={(e) => setResolves(e.target.checked)} /> resolves <code>{q.item_key}</code></label>}
          <div className="flex gap-2">
            <Button size="sm" onClick={() => act("accept", { note, resolves_item: resolves })}>Accept answer as evidence</Button>
            <Button size="sm" variant="ghost" onClick={() => act("withdraw", { note: note || "Not needed" })}>Withdraw</Button>
          </div>
        </div>
      )}
      {canAsk && q.status === "asked" && (
        <Button size="sm" variant="ghost" className="mt-1 h-7 text-xs" onClick={() => act("withdraw", { note: "Not needed" })}>Withdraw question</Button>
      )}
      {reopened.length > 0 && <p className="mt-1 text-xs text-rose-700">Reopened: {reopened.map((r) => `${r.area} ${r.level}`).join(", ")}</p>}
      {err && <p className="mt-1 text-xs text-rose-700">{err}</p>}
    </article>
  );
}

export function StaffQuestions() {
  const { data, error, mutate: reload } = useApi<ClientQuestion[]>("/api/client-questions");
  const { data: me } = useApi<Me>("/api/session/me");
  if (error) return <ErrorState error={error} />;
  if (!data) return <Loading />;
  const canAsk = !!me?.permissions.includes("ask_client");
  return (
    <div className="space-y-2">
      <p className="text-xs text-muted-foreground">
        Questions sent to the client. An accepted answer becomes a ClientAnswer node on the graph (CONFIRMED_BY the line or document it is about),
        can resolve the inbox item it came from, and reopens the sign-offs it affects.
      </p>
      {data.length === 0 ? <p className="py-6 text-center text-xs text-muted-foreground">No questions yet. Ask from an inbox item.</p>
        : data.map((q) => <StaffQuestion key={q.id} q={q} canAsk={canAsk} onChange={reload} />)}
    </div>
  );
}

/** What a client sees: their questions, and a box to answer. No internal workpaper detail. */
export function ClientQuestionsView() {
  const { data, error, mutate: reload } = useApi<ClientQuestion[]>("/api/client-questions");
  const mutate = useMutate();
  const [drafts, setDrafts] = useState<Record<number, string>>({});
  const [err, setErr] = useState<string | null>(null);
  if (error) return <ErrorState error={error} />;
  if (!data) return <Loading />;
  const send = async (id: number) => {
    setErr(null);
    try {
      await mutate(`/api/client-questions/${id}/answer`, { answer: drafts[id] });
      setDrafts((d) => ({ ...d, [id]: "" }));
      reload();
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : "Failed");
    }
  };
  return (
    <div className="space-y-2">
      {data.length === 0 && <p className="py-6 text-center text-xs text-muted-foreground">Your preparer has no questions for you right now.</p>}
      {data.map((q) => (
        <article key={q.id} className="rounded-lg border bg-card p-3 text-[13px]">
          <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
            <Chip tone={TONE[q.status]}>{q.status === "accepted" ? "thank you — received" : q.status}</Chip>
            <span>{q.asked_by} · {dateTime(q.asked_at)} · about {q.about}</span>
          </div>
          <p className="mt-1">{q.question}</p>
          {q.answer && <p className="mt-1 rounded bg-slate-50 px-2 py-1 text-xs">Your answer: {q.answer}</p>}
          {(q.status === "asked" || q.status === "answered") && (
            <div className="mt-2 space-y-1.5">
              <Textarea aria-label={`Answer to question ${q.id}`} value={drafts[q.id] ?? ""} onChange={(e) => setDrafts((d) => ({ ...d, [q.id]: e.target.value }))}
                placeholder={q.status === "answered" ? "Add to or correct your answer" : "Your answer"} className="min-h-16 text-xs" />
              <Button size="sm" disabled={!(drafts[q.id] ?? "").trim()} onClick={() => send(q.id)}>Send answer</Button>
            </div>
          )}
        </article>
      ))}
      {err && <p className="text-xs text-rose-700">{err}</p>}
    </div>
  );
}
