"use client";

import { useState } from "react";
import { BadgeCheck, Undo2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, useApi, useMutate } from "@/lib/api";
import { dateTime, humanize } from "@/lib/format";
import { useRefreshAfter } from "@/lib/refresh";
import type { EvidenceFlag, Me, Verification } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Chip } from "./primitives";

// Mirrors the server rule (METHOD_EVIDENCE_KINDS): each method cites the kind of evidence its name claims.
const REF_HINTS: Record<string, string> = {
  confirmed_with_client: "Required: client answer, message or call — e.g. qa-14 msg-08 call-01",
  agreed_to_prior_year: "Required: prior-year source — e.g. py:/return_2024/lines/F1040.24",
  agreed_to_agency_record: "Required: agency record — e.g. agency:/irs_account_transcript_2025/0",
  agreed_to_third_party_record: "Optional: document, page or value — e.g. D62 doc:D62#page1",
};

/** Shows how an item was verified and lets permitted users record or withdraw a verification. */
export function VerificationPanel({ targetRef, flags = [], onChange }: {
  targetRef: string; flags?: EvidenceFlag[]; onChange?: () => void;
}) {
  const { data: me } = useApi<Me>("/api/session/me");
  const canSee = !!me?.permissions.includes("view_internal_notes");
  const canVerify = !!me?.permissions.includes("verify");
  const { data: list, mutate: reload } = useApi<Verification[]>(
    canSee ? `/api/verifications?target_ref=${encodeURIComponent(targetRef)}&include_withdrawn=true` : null,
  );
  const { data: methods } = useApi<{ code: string; label: string }[]>("/api/verification-methods");
  const mutate = useMutate();
  const refreshAfter = useRefreshAfter();
  const [method, setMethod] = useState("agreed_to_source_document");
  const [note, setNote] = useState("");
  const [refs, setRefs] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [withdrawing, setWithdrawing] = useState<number | null>(null);
  const [reason, setReason] = useState("");

  if (me && !canSee) {
    return <p className="text-xs text-muted-foreground">Verification records are internal to the firm.</p>;
  }
  const refresh = () => { reload(); onChange?.(); refreshAfter("verification"); };
  const active = list?.filter((v) => v.status === "active") ?? [];
  const noteRequired = method !== "agreed_to_source_document" || flags.length > 0;

  const submit = async () => {
    setErr(null);
    try {
      await mutate("/api/verifications", {
        target_ref: targetRef, method, note: note.trim() || null,
        evidence_refs: refs.split(/[\s,]+/).filter(Boolean),
      });
      setNote(""); setRefs("");
      refresh();
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : "Failed");
    }
  };
  const withdraw = async (id: number) => {
    setErr(null);
    try {
      await mutate(`/api/verifications/${id}/withdraw`, { reason });
      setWithdrawing(null); setReason("");
      refresh();
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : "Failed");
    }
  };

  return (
    <div className="space-y-2">
      {list?.length === 0 && <div className="text-xs text-muted-foreground">Not verified yet.</div>}
      {list?.map((v) => (
        <div key={v.id} className={cn("rounded-md border px-2.5 py-1.5 text-xs", v.status === "withdrawn" && "opacity-55")}>
          <div className="flex flex-wrap items-center gap-1.5">
            {v.status === "active" ? <Chip tone="good"><BadgeCheck className="size-3" />{v.method_label}</Chip>
              : <Chip tone="muted">withdrawn · {v.method_label}</Chip>}
            <span className="text-muted-foreground">{v.verified_by_name} ({humanize(v.verified_by_role)}) · {dateTime(v.verified_at)}</span>
          </div>
          {v.note && <p className="mt-1 text-slate-700">{v.note}</p>}
          {v.evidence_refs.length > 0 && (
            <div className="mt-1 flex flex-wrap gap-1">{v.evidence_refs.map((r) => <code key={r} className="rounded bg-slate-100 px-1 text-[10.5px]">{r}</code>)}</div>
          )}
          {v.acknowledged_flags.length > 0 && <div className="mt-1 text-[11px] text-amber-700">Acknowledged flags: {v.acknowledged_flags.join(", ")}</div>}
          {v.status === "withdrawn" && <div className="mt-1 text-[11px] text-muted-foreground">Withdrawn by {v.withdrawn_by_name}: {v.withdrawn_reason}</div>}
          {v.status === "active" && canVerify && withdrawing !== v.id && (
            <button onClick={() => setWithdrawing(v.id)} className="mt-1 inline-flex items-center gap-1 text-[11px] text-slate-500 hover:text-rose-700"><Undo2 className="size-3" />Withdraw</button>
          )}
          {withdrawing === v.id && (
            <div className="mt-1.5 flex gap-1.5">
              <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Reason (required)" className="h-7 text-xs" />
              <Button size="sm" variant="outline" disabled={!reason.trim()} onClick={() => withdraw(v.id)}>Withdraw</Button>
            </div>
          )}
        </div>
      ))}

      {canVerify ? (
        <div className="space-y-1.5 rounded-md border bg-slate-50/70 p-2">
          <select value={method} onChange={(e) => setMethod(e.target.value)}
            className="h-8 w-full rounded-md border bg-white px-2 text-xs">
            {methods?.map((m) => <option key={m.code} value={m.code}>{m.label}</option>)}
          </select>
          <Textarea value={note} onChange={(e) => setNote(e.target.value)}
            placeholder={noteRequired ? (flags.length ? "Note required: explain why the flag does not change the value" : "Note required for this method") : "Note (optional)"}
            className="min-h-14 bg-white text-xs" />
          {(method === "confirmed_with_client" || method === "agreed_to_prior_year" || method === "agreed_to_agency_record" || method === "agreed_to_third_party_record") && (
            <Input value={refs} onChange={(e) => setRefs(e.target.value)} placeholder={REF_HINTS[method] ?? "Evidence refs"}
              className="h-7 bg-white font-mono text-[11px]" />
          )}
          <Button size="sm" className="w-full" disabled={noteRequired && !note.trim()} onClick={submit}>
            <BadgeCheck className="size-3.5" /> Record verification{active.length > 0 ? " (additional)" : ""}
          </Button>
          {err && <div className="text-[11px] text-rose-700">{err}</div>}
        </div>
      ) : me && <p className="text-[11px] text-muted-foreground">Your role ({me.role_label}) cannot record verifications.</p>}
    </div>
  );
}
