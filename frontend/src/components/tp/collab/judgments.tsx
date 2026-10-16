"use client";

import { useEffect, useState } from "react";
import { Scale } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, useApi, useMutate } from "@/lib/api";
import type { Judgment, JudgmentOption, Reopened } from "@/lib/collab-types";
import { dateTime, money } from "@/lib/format";
import { useRefreshAfter } from "@/lib/refresh";
import type { Me } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Chip, ErrorState, Loading } from "../primitives";

const STATUS_TONE = { recorded: "warn", reviewed: "info", approved: "good", superseded: "muted" } as const;

export function Effect({ federal, california, source }: { federal: number | null; california: number | null; source?: string }) {
  if (federal === null && california === null) return <span className="text-muted-foreground">not computed</span>;
  return (
    <span className="num">
      federal {money(federal, { sign: true })} · CA {money(california, { sign: true })}
      {source === "engine_alternative" && <Chip tone="engine" className="ml-1">engine run</Chip>}
    </span>
  );
}

type Alt = { option: string; description: string; why_not: string };

/** Record a judgment. Options and their effects come from the packet (engine alternatives); nothing is invented. */
export function JudgmentForm({ itemKey, onDone, onCancel }: { itemKey?: string; onDone: (r: Judgment & { reopened_signoffs: Reopened }) => void; onCancel: () => void }) {
  const { data } = useApi<{ options: JudgmentOption[]; suggestion: { topic: string; target_refs: string[]; evidence_refs: string[] } | null }>(
    `/api/judgments/options${itemKey ? `?item_key=${encodeURIComponent(itemKey)}` : ""}`);
  const mutate = useMutate();
  const refreshAfter = useRefreshAfter();
  const [topic, setTopic] = useState("");
  const [targets, setTargets] = useState("");
  const [option, setOption] = useState("keep_engine");
  const [decision, setDecision] = useState("");
  const [alts, setAlts] = useState<Alt[]>([]);
  const [rationale, setRationale] = useState("");
  const [authority, setAuthority] = useState("");
  const [evidence, setEvidence] = useState("");
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!data) return;
    const s = data.suggestion;
    if (s) {
      setTopic((t) => t || s.topic);
      setTargets((t) => t || s.target_refs.join(" "));
      setEvidence((e) => e || s.evidence_refs.join(" "));
    }
    const related = data.options.filter((o) => o.related && o.option !== "keep_engine");
    setAlts((a) => (a.length ? a : related.map((o) => ({ option: o.option, description: o.label, why_not: "" }))));
  }, [data]);

  if (!data) return <Loading rows={2} />;
  const byOption = Object.fromEntries(data.options.map((o) => [o.option, o]));
  const chosen = byOption[option];
  const stake = Math.max(0, ...alts.flatMap((a) => {
    const o = byOption[a.option];
    return ["federal", "california"].map((j) => {
      const x = o?.[j as "federal"], y = chosen?.[j as "federal"];
      return typeof x === "number" && typeof y === "number" ? Math.abs(x - y) : 0;
    });
  }));

  const submit = async () => {
    setErr(null);
    try {
      const r = await mutate<Judgment & { reopened_signoffs: Reopened }>("/api/judgments", {
        item_key: itemKey ?? null, topic, target_refs: targets.split(/[\s,]+/).filter(Boolean), decision, decision_option: option,
        alternatives: alts, rationale, authority, evidence_refs: evidence.split(/[\s,]+/).filter(Boolean),
      });
      refreshAfter("collab");
      onDone(r);
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : "Failed");
    }
  };

  const field = "block text-[11px] font-medium text-muted-foreground";
  return (
    <div className="space-y-2 rounded-md border bg-slate-50 p-3 text-[13px]">
      <label className={field}>Topic<Input value={topic} onChange={(e) => setTopic(e.target.value)} className="mt-0.5 h-8 bg-white text-xs" /></label>
      <label className={field}>About (return lines or evidence refs)
        <Input value={targets} onChange={(e) => setTargets(e.target.value)} className="mt-0.5 h-8 bg-white font-mono text-xs" /></label>
      <fieldset>
        <legend className={field}>Decision</legend>
        <div className="mt-1 space-y-1">
          {data.options.map((o) => (
            <label key={o.option} className={cn("flex items-start gap-2 rounded border bg-white px-2 py-1 text-xs", option === o.option && "border-primary")}>
              <input type="radio" name="decision" aria-label={o.label} checked={option === o.option} onChange={() => {
                setOption(o.option);
                setAlts((a) => a.filter((x) => x.option !== o.option));
              }} />
              <span className="flex-1">{o.label} {o.related && o.option !== "keep_engine" && <Chip tone="info">related</Chip>}
                <span className="block text-[11px] text-muted-foreground"><Effect federal={o.federal} california={o.california} source={o.source} /></span></span>
              {option !== o.option && o.option !== "other" && (
                <button type="button" className="text-[11px] text-sky-700 hover:underline" onClick={(e) => {
                  e.preventDefault();
                  setAlts((a) => a.some((x) => x.option === o.option) ? a.filter((x) => x.option !== o.option) : [...a, { option: o.option, description: o.label, why_not: "" }]);
                }}>{alts.some((x) => x.option === o.option) ? "− considered" : "+ considered"}</button>
              )}
            </label>
          ))}
        </div>
      </fieldset>
      <label className={field}>Decision in words<Textarea value={decision} onChange={(e) => setDecision(e.target.value)} className="mt-0.5 min-h-12 bg-white text-xs" /></label>
      <div>
        <div className={field}>Alternatives considered ({alts.length})</div>
        {alts.length === 0 && <p className="text-[11px] text-rose-700">Mark at least one alternative as considered.</p>}
        {alts.map((a, i) => (
          <div key={a.option} className="mt-1 rounded border bg-white px-2 py-1 text-xs">
            <div className="font-medium">{byOption[a.option]?.label ?? a.option}</div>
            <Input value={a.why_not} placeholder="Why not this one?" onChange={(e) => setAlts((all) => all.map((x, j) => j === i ? { ...x, why_not: e.target.value } : x))}
              className="mt-1 h-7 text-xs" />
          </div>
        ))}
      </div>
      <label className={field}>Rationale<Textarea value={rationale} onChange={(e) => setRationale(e.target.value)} className="mt-0.5 min-h-16 bg-white text-xs" /></label>
      <label className={field}>Authority relied on (required by firm rule)
        <Input value={authority} onChange={(e) => setAuthority(e.target.value)} placeholder="e.g. Treas. Reg. 1.263(a)-3" className="mt-0.5 h-8 bg-white text-xs" /></label>
      <label className={field}>Evidence refs<Input value={evidence} onChange={(e) => setEvidence(e.target.value)} className="mt-0.5 h-8 bg-white font-mono text-xs" /></label>
      <p className="text-[11px] text-muted-foreground">
        Tax at stake {money(stake)} → {stake > 1000 ? <b>partner approval required</b> : "reviewer approval"}. Effects are the engine&apos;s own alternative runs from the packet.
      </p>
      <div className="flex gap-2">
        <Button size="sm" disabled={!topic || !decision || rationale.length < 10 || authority.trim().length < 3 || !alts.length || !targets.trim()}
          onClick={submit}>Record judgment</Button>
        <Button size="sm" variant="ghost" onClick={onCancel}>Cancel</Button>
      </div>
      {err && <p className="text-xs text-rose-700">{err}</p>}
    </div>
  );
}

function JudgmentCard({ j, me, onChange }: { j: Judgment; me?: Me; onChange: () => void }) {
  const mutate = useMutate();
  const refreshAfter = useRefreshAfter();
  const [err, setErr] = useState<string | null>(null);
  const canReview = !!me?.permissions.includes("review_judgment") && me.id !== j.prepared_by_id &&
    (j.status === "recorded" || (j.status === "reviewed" && me.role === "partner"));
  const review = async () => {
    setErr(null);
    try {
      await mutate(`/api/judgments/${j.id}/review`, {});
      refreshAfter("collab");
      onChange();
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : "Failed");
    }
  };
  return (
    <article className={cn("rounded-lg border bg-card p-3 text-[13px]", j.status === "superseded" && "opacity-60")}>
      <header className="flex flex-wrap items-center gap-1.5">
        <Scale className="size-4 text-fuchsia-700" />
        <span className="font-semibold">#{j.id} {j.topic}</span>
        <Chip tone={STATUS_TONE[j.status]}>{j.status}</Chip>
        <Chip tone={j.review_required === "partner" ? "bad" : "neutral"}>{j.review_required} approval</Chip>
        {j.areas.map((a) => <Chip key={a} tone="muted">{a}</Chip>)}
        {j.supersedes_id && <Chip tone="muted">revises #{j.supersedes_id}</Chip>}
      </header>
      <dl className="mt-2 grid gap-x-4 gap-y-1 text-xs sm:grid-cols-[130px_1fr]">
        <dt className="text-muted-foreground">Decision</dt><dd>{j.decision}</dd>
        <dt className="text-muted-foreground">Tax effect</dt>
        <dd><Effect federal={j.tax_effect.federal} california={j.tax_effect.california} source={j.tax_effect.source} />
          {typeof j.tax_effect.tax_at_stake === "number" && <span className="text-muted-foreground"> · at stake {money(j.tax_effect.tax_at_stake)}</span>}
          <div className="text-[11px] text-muted-foreground">{j.tax_effect.basis}</div></dd>
        <dt className="text-muted-foreground">Alternatives</dt>
        <dd><ul className="space-y-0.5">{j.alternatives.map((a) => (
          <li key={a.option}>{a.description} — <Effect federal={a.federal} california={a.california} source={a.source} />
            {a.why_not && <span className="text-muted-foreground"> · not chosen: {a.why_not}</span>}</li>))}</ul></dd>
        <dt className="text-muted-foreground">Rationale</dt><dd className="whitespace-pre-wrap">{j.rationale}</dd>
        <dt className="text-muted-foreground">Authority</dt><dd>{j.authority}</dd>
        <dt className="text-muted-foreground">Evidence</dt><dd className="font-mono text-[11px]">{[...j.target_refs, ...j.evidence_refs].join(" · ")}</dd>
        <dt className="text-muted-foreground">Preparer</dt><dd>{j.prepared_by} · {dateTime(j.prepared_at)}</dd>
        <dt className="text-muted-foreground">Reviewer</dt><dd>{j.reviewed_by ? `${j.reviewed_by} · ${dateTime(j.reviewed_at)}` : "—"}</dd>
        {j.review_required === "partner" && <><dt className="text-muted-foreground">Partner</dt><dd>{j.partner_by ? `${j.partner_by} · ${dateTime(j.partner_at)}` : "—"}</dd></>}
      </dl>
      {canReview && <Button size="sm" className="mt-2" onClick={review}>{j.status === "reviewed" ? "Partner approve" : "Review & approve"}</Button>}
      {err && <p className="mt-1 text-xs text-rose-700">{err}</p>}
    </article>
  );
}

export function JudgmentLedger() {
  const [all, setAll] = useState(false);
  const { data, error, mutate: reload } = useApi<Judgment[]>(`/api/judgments${all ? "?include_superseded=true" : ""}`);
  const { data: me } = useApi<Me>("/api/session/me");
  if (error) return <ErrorState error={error} />;
  if (!data) return <Loading />;
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>Each judgment records topic, decision, alternatives, rationale, authority, evidence, tax effect, preparer and reviewer. Revisions supersede; nothing is edited.</span>
        <label className="flex items-center gap-1"><input type="checkbox" checked={all} onChange={(e) => setAll(e.target.checked)} /> show superseded</label>
      </div>
      {data.length === 0 ? <p className="py-6 text-center text-xs text-muted-foreground">No judgments yet. Record one from a Professional judgment item in the inbox.</p>
        : data.map((j) => <JudgmentCard key={j.id} j={j} me={me} onChange={reload} />)}
    </div>
  );
}
