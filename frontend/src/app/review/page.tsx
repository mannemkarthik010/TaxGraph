"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, useApi, useMutate } from "@/lib/api";
import type { InboxResponse } from "@/lib/collab-types";
import { useRefreshAfter } from "@/lib/refresh";
import type { Me, Note } from "@/lib/types";
import { cn } from "@/lib/utils";
import { ErrorState, Loading, PageHeader, Panel } from "@/components/tp/primitives";
import { NoteCard } from "@/components/tp/notes-thread";
import { UncertaintyInbox } from "@/components/tp/collab/inbox";
import { ReviewerBrief, RiskBoard } from "@/components/tp/ai/reviewer";
import { JudgmentLedger } from "@/components/tp/collab/judgments";
import { SignoffBoard } from "@/components/tp/collab/signoffs";
import { ClientQuestionsView, StaffQuestions } from "@/components/tp/collab/client-questions";

const EXAMPLES = ["line:v3:SchC.44a", "line:v3:SchC.1", "D23", "doc:D23#page3", "ev-0315", "area:business", "engagement"];
const TABS = [["inbox", "Uncertainty Inbox"], ["brief", "AI Reviewer"], ["judgments", "Judgment Ledger"], ["signoffs", "Sign-offs"],
              ["questions", "Client questions"], ["notes", "Notes"]] as const;
type Tab = (typeof TABS)[number][0];

export default function ReviewPage() {
  return <Suspense fallback={<Loading />}><ReviewView /></Suspense>;
}

function ReviewView() {
  const params = useSearchParams();
  const router = useRouter();
  const { data: me } = useApi<Me>("/api/session/me");
  const internal = !!me?.permissions.includes("view_internal_notes");
  const { data: inbox } = useApi<InboxResponse>(internal ? "/api/inbox" : null);
  const tab = ((params.get("tab") as Tab) ?? "inbox");

  if (!me) return <Loading />;
  if (!internal) {
    return (
      <div className="space-y-4">
        <PageHeader title="Questions from your preparer" subtitle="Answer here; your preparer reviews each answer before it is used on your return." />
        {me.permissions.includes("answer_client_question") ? <ClientQuestionsView />
          : <p className="text-sm text-muted-foreground">Your role ({me.role_label}) has no access to review work.</p>}
      </div>
    );
  }
  return (
    <div className="space-y-4">
      <PageHeader title="Review" subtitle="Everything that still needs a human decision, every judgment, every sign-off. Every action is permission-checked and written to the audit chain." />
      <div className="flex flex-wrap items-center gap-1 border-b">
        {TABS.map(([t, label]) => (
          <button key={t} onClick={() => router.replace(`/review?tab=${t}`, { scroll: false })}
            className={cn("-mb-px border-b-2 px-3 py-2 text-[13px]", tab === t ? "border-primary font-medium text-primary" : "border-transparent text-slate-600 hover:text-slate-900")}>
            {label}
            {t === "inbox" && inbox && <span className={cn("ml-1.5 rounded px-1 text-[11px]", inbox.totals.blocking ? "bg-rose-100 text-rose-800" : "bg-slate-100 text-slate-600")}>
              {inbox.totals.open}{inbox.totals.blocking ? ` · ${inbox.totals.blocking} blocking` : ""}</span>}
          </button>
        ))}
      </div>
      {tab === "inbox" && <UncertaintyInbox />}
      {tab === "brief" && <div className="space-y-4"><ReviewerBrief /><RiskBoard /></div>}
      {tab === "judgments" && <JudgmentLedger />}
      {tab === "signoffs" && <SignoffBoard />}
      {tab === "questions" && <StaffQuestions />}
      {tab === "notes" && <NotesTab me={me} />}
    </div>
  );
}

function NotesTab({ me }: { me: Me }) {
  const [status, setStatus] = useState<"open" | "resolved" | "">("open");
  const { data: notes, error, mutate: reload } = useApi<Note[]>(`/api/workpaper/notes${status ? `?status=${status}` : ""}`);
  const can = (p: string) => me.permissions.includes(p);
  const blocking = notes?.filter((n) => n.status === "open" && n.blocking).length ?? 0;

  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_360px]">
      <Panel dense title={
        <div className="flex items-center gap-1">
          {([["open", "Open"], ["resolved", "Resolved"], ["", "All"]] as const).map(([k, l]) => (
            <button key={k} onClick={() => setStatus(k)}
              className={cn("rounded-md px-2 py-0.5 text-xs font-normal", status === k ? "bg-slate-800 text-white" : "text-slate-600 hover:bg-slate-100")}>{l}</button>
          ))}
          {status === "open" && blocking > 0 && <span className="ml-2 text-xs font-normal text-rose-700">{blocking} blocking filing</span>}
        </div>}>
        <div className="space-y-2 p-3">
          <ErrorState error={error} />
          {!notes ? <Loading /> : notes.length === 0 ? (
            <div className="py-6 text-center text-xs text-muted-foreground">Nothing here.</div>
          ) : notes.map((n) => (
            <NoteCard key={n.id} note={n} showTarget onChange={reload}
              canResolve={n.kind === "review_note" ? can("resolve_review_note") : can("create_note")} />
          ))}
        </div>
      </Panel>
      <Panel title="New note">
        {!can("create_note") ? (
          <p className="text-xs text-muted-foreground">Your role ({me.role_label}) cannot add workpaper notes.</p>
        ) : <Composer canReview={can("create_review_note")} onCreated={reload} />}
      </Panel>
    </div>
  );
}

function Composer({ canReview, onCreated }: { canReview: boolean; onCreated: () => void }) {
  const mutate = useMutate();
  const refreshAfter = useRefreshAfter();
  const [target, setTarget] = useState("line:v3:SchC.44a");
  const [body, setBody] = useState("");
  const [kind, setKind] = useState<"note" | "review_note">(canReview ? "review_note" : "note");
  const [err, setErr] = useState<Error | null>(null);
  const submit = async () => {
    setErr(null);
    try {
      await mutate("/api/workpaper/notes", { target_ref: target, kind, body });
      setBody("");
      onCreated();
      refreshAfter("note");
    } catch (e) {
      setErr(e as ApiError);
    }
  };
  return (
    <div className="space-y-2 text-[13px]">
      <label className="block text-[11px] font-medium text-muted-foreground">Attach to (any packet reference)</label>
      <Input value={target} onChange={(e) => setTarget(e.target.value)} className="h-8 font-mono text-xs" />
      <div className="flex flex-wrap gap-1">
        {EXAMPLES.map((x) => (
          <button key={x} onClick={() => setTarget(x)} className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10.5px] text-slate-600 hover:bg-slate-200">{x}</button>
        ))}
      </div>
      <Textarea value={body} onChange={(e) => setBody(e.target.value)} placeholder="What needs attention?" className="min-h-24" />
      <div className="inline-flex rounded-md border p-0.5 text-[11px]">
        <button onClick={() => setKind("note")} className={cn("rounded px-2 py-0.5", kind === "note" && "bg-slate-800 text-white")}>Note</button>
        <button disabled={!canReview} onClick={() => setKind("review_note")}
          className={cn("rounded px-2 py-0.5 disabled:opacity-40", kind === "review_note" && "bg-slate-800 text-white")}>Review note (blocks filing)</button>
      </div>
      <Button className="w-full" disabled={!body.trim() || !target.trim()} onClick={submit}>Save to workpaper</Button>
      <ErrorState error={err ?? undefined} />
    </div>
  );
}
