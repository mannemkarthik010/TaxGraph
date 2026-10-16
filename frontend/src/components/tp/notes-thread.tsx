"use client";

import { useState } from "react";
import { CheckCircle2, MessageSquarePlus, OctagonAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, useApi, useMutate } from "@/lib/api";
import { dateTime, humanize } from "@/lib/format";
import { useRefreshAfter } from "@/lib/refresh";
import type { Me, Note } from "@/lib/types";
import { Chip } from "./primitives";

/** Notes and review notes attached to any reference (line, value, document, area). */
export function NotesThread({ targetRef, compact }: { targetRef?: string; compact?: boolean }) {
  const path = targetRef ? `/api/workpaper/notes?target_ref=${encodeURIComponent(targetRef)}` : "/api/workpaper/notes";
  const { data: notes, mutate: reload } = useApi<Note[]>(path);
  const { data: me } = useApi<Me>("/api/session/me");
  const can = (p: string) => !!me?.permissions.includes(p);

  return (
    <div className="space-y-2">
      {notes?.length === 0 && <div className="text-xs text-muted-foreground">No notes yet.</div>}
      {notes?.map((n) => <NoteCard key={n.id} note={n} canResolve={n.kind === "review_note" ? can("resolve_review_note") : can("create_note")} onChange={reload} showTarget={!targetRef} />)}
      {targetRef && can("create_note") && <NoteComposer targetRef={targetRef} canReview={can("create_review_note")} onCreated={reload} compact={compact} />}
      {targetRef && me && !can("create_note") && (
        <div className="text-[11px] text-muted-foreground">Your role ({me.role_label}) can read client-visible notes but not add workpaper notes.</div>
      )}
    </div>
  );
}

export function NoteCard({ note: n, canResolve, onChange, showTarget }: {
  note: Note; canResolve: boolean; onChange: () => void; showTarget?: boolean;
}) {
  const mutate = useMutate();
  const refreshAfter = useRefreshAfter();
  const [resolving, setResolving] = useState(false);
  const [text, setText] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const submit = async () => {
    try {
      await mutate(`/api/workpaper/notes/${n.id}/resolve`, { resolution: text });
      setResolving(false);
      onChange();
      refreshAfter("note");
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : "Failed");
    }
  };
  return (
    <div className={`rounded-md border px-3 py-2 text-[13px] ${n.status === "open" && n.blocking ? "border-rose-200 bg-rose-50/40" : ""}`}>
      <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
        {n.kind === "review_note" ? <Chip tone="info">Review note</Chip> : <Chip>Note</Chip>}
        {n.blocking && n.status === "open" && <Chip tone="bad"><OctagonAlert className="size-3" />blocks filing</Chip>}
        {n.status === "resolved" && <Chip tone="good"><CheckCircle2 className="size-3" />resolved</Chip>}
        {showTarget && <code className="rounded bg-slate-100 px-1 text-[10.5px] text-slate-700">{n.target_ref}</code>}
        <span>{n.author_name} ({humanize(n.author_role)}) · {dateTime(n.created_at)}</span>
      </div>
      <p className="mt-1 whitespace-pre-wrap text-slate-800">{n.body}</p>
      {n.status === "resolved" && (
        <p className="mt-1 border-l-2 border-emerald-300 pl-2 text-xs text-slate-600">
          {n.resolution} — <span className="text-muted-foreground">{n.resolved_by_name}, {dateTime(n.resolved_at)}</span>
        </p>
      )}
      {n.status === "open" && canResolve && !resolving && (
        <button className="mt-1 text-[11px] text-sky-700 hover:underline" onClick={() => setResolving(true)}>Resolve…</button>
      )}
      {resolving && (
        <div className="mt-2 space-y-1.5">
          <Textarea value={text} onChange={(e) => setText(e.target.value)} placeholder="How was this resolved? (recorded in the audit trail)" className="min-h-14 text-[13px]" />
          <div className="flex gap-2">
            <Button size="sm" disabled={!text.trim()} onClick={submit}>Resolve</Button>
            <Button size="sm" variant="ghost" onClick={() => setResolving(false)}>Cancel</Button>
          </div>
          {err && <div className="text-[11px] text-rose-700">{err}</div>}
        </div>
      )}
    </div>
  );
}

function NoteComposer({ targetRef, canReview, onCreated, compact }: {
  targetRef: string; canReview: boolean; onCreated: () => void; compact?: boolean;
}) {
  const mutate = useMutate();
  const refreshAfter = useRefreshAfter();
  const [body, setBody] = useState("");
  const [kind, setKind] = useState<"note" | "review_note">("note");
  const [err, setErr] = useState<string | null>(null);
  const [open, setOpen] = useState(!compact);
  if (!open) {
    return <button onClick={() => setOpen(true)} className="inline-flex items-center gap-1 text-xs text-sky-700 hover:underline"><MessageSquarePlus className="size-3.5" />Add note</button>;
  }
  const submit = async () => {
    setErr(null);
    try {
      await mutate("/api/workpaper/notes", { target_ref: targetRef, kind, body });
      setBody("");
      onCreated();
      refreshAfter("note");
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : "Failed");
    }
  };
  return (
    <div className="space-y-1.5 rounded-md border bg-slate-50/60 p-2">
      <Textarea value={body} onChange={(e) => setBody(e.target.value)} placeholder={`Note on ${targetRef}…`} className="min-h-16 bg-white text-[13px]" />
      <div className="flex flex-wrap items-center gap-2">
        <div className="inline-flex rounded-md border bg-white p-0.5 text-[11px]">
          <button onClick={() => setKind("note")} className={`rounded px-2 py-0.5 ${kind === "note" ? "bg-slate-800 text-white" : ""}`}>Note</button>
          <button onClick={() => canReview && setKind("review_note")} disabled={!canReview}
            title={canReview ? "Review notes block filing until cleared" : "Only reviewers, partners and quality reviewers raise review notes"}
            className={`rounded px-2 py-0.5 ${kind === "review_note" ? "bg-slate-800 text-white" : ""} disabled:opacity-40`}>Review note (blocks filing)</button>
        </div>
        <Button size="sm" className="ml-auto" disabled={!body.trim()} onClick={submit}>Save to workpaper</Button>
      </div>
      {err && <div className="text-[11px] text-rose-700">{err}</div>}
    </div>
  );
}
