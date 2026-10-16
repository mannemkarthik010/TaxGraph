"use client";

import Link from "next/link";
import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { AlertTriangle, ArrowLeftRight, Cpu, Play, Radar, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { ApiError, useApi, useMutate } from "@/lib/api";
import { useRefreshAfter } from "@/lib/refresh";
import { dateTime } from "@/lib/format";
import { proveHref } from "@/lib/links";
import type { ChallengeOverview, FindingDetail } from "@/lib/schedule-types";
import type { Me, VersionRow } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Chip, ErrorState, Loading, Panel } from "@/components/tp/primitives";
import { Amt, LineDrawerProvider, LineRef } from "@/components/tp/schedules/common";
import { FindingCard, SEV_TONE, STATUS_META, unitFmt } from "@/components/tp/challenge/finding-card";
import { reopenedText } from "@/components/tp/adjustments/adjustments";
import { ExplainFinding } from "@/components/tp/ai/reviewer";
import type { Reopened } from "@/lib/collab-types";

type Filter = "fail" | "attention" | "pass" | "all";

export default function ChallengePage() {
  return <Suspense fallback={<Loading />}><Challenge /></Suspense>;
}

function Challenge() {
  const params = useSearchParams();
  const router = useRouter();
  const { data: versions } = useApi<{ current: string; versions: VersionRow[] }>("/api/return/versions");
  const version = params.get("v") ?? versions?.current ?? "v3";
  const filter = (params.get("show") as Filter) ?? "fail";
  const open = params.get("finding");
  const set = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params.toString());
    for (const [k, v] of Object.entries(patch)) {
      if (v === null) next.delete(k);
      else next.set(k, v);
    }
    router.replace(`/challenge?${next.toString()}`, { scroll: false });
  };
  const { data, error, mutate: reload } = useApi<ChallengeOverview>(`/api/challenge?version=${version}`);
  const { data: me } = useApi<Me>("/api/session/me");
  const mutate = useMutate();
  const [runMsg, setRunMsg] = useState<string | null>(null);

  const run = async () => {
    try {
      const r = await mutate<{ id: number; changes: { new: string[]; gone: string[]; changed: string[]; since_run: number | null } }>(`/api/challenge/runs?version=${version}`);
      setRunMsg(r.changes.since_run
        ? `Run #${r.id} recorded · since run #${r.changes.since_run}: ${r.changes.new.length} new, ${r.changes.gone.length} resolved, ${r.changes.changed.length} changed`
        : `Run #${r.id} recorded — first run for ${version}.`);
      reload();
    } catch (e) {
      setRunMsg(e instanceof ApiError ? e.detail : "Run failed");
    }
  };

  if (error) return <ErrorState error={error} />;
  if (!data) return <Loading rows={10} />;
  const s = data.summary;
  const shown = data.findings.filter((f) => filter === "all" || f.status === filter || (filter === "attention" && f.status === "explained"));
  const eng = s.engine.summary;

  return (
    <LineDrawerProvider version={version}>
      <div className="space-y-5">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold tracking-tight">Challenge Return</h1>
            <p className="text-sm text-muted-foreground">The supplied engine says the return is computed. TaxProof checks — independently, from the evidence — whether it is proven.</p>
          </div>
          <div className="flex items-center gap-2">
            <div className="inline-flex rounded-md border bg-white p-0.5 text-xs">
              {versions?.versions.map((v) => (
                <button key={v.version} onClick={() => set({ v: v.version, finding: null })}
                  className={cn("rounded px-2 py-1", v.version === version ? "bg-slate-800 text-white" : "text-slate-600 hover:bg-slate-100")}>{v.version}</button>
              ))}
            </div>
            {me?.permissions.includes("create_note") && <Button size="sm" onClick={run}><Play className="size-3.5" />Record run</Button>}
          </div>
        </div>
        {runMsg && <div className="rounded-md border border-sky-200 bg-sky-50 px-3 py-1.5 text-xs text-sky-900">{runMsg}</div>}

        {/* Engine vs TaxProof */}
        <div className="grid gap-4 lg:grid-cols-2">
          <div className="rounded-lg border border-violet-200 bg-violet-50/40 p-4">
            <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-violet-700"><Cpu className="size-4" />Supplied return engine · {version}</div>
            <div className="mt-2 grid grid-cols-3 gap-3 text-sm">
              <Mini label="Federal total tax" v={eng.federal.total_tax} />
              <Mini label="California total tax" v={eng.california.total_tax} />
              <Mini label="Federal balance due" v={eng.federal.balance_due} />
            </div>
            <p className="mt-3 text-xs text-violet-900">Status: <b>computed</b>. The engine reports {s.engine.diagnostics} diagnostics of its own (listed separately below).</p>
          </div>
          <div className="rounded-lg border border-primary/30 bg-white p-4 shadow-xs">
            <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide text-primary"><ShieldCheck className="size-4" />TaxProof independent assurance</div>
            <div className="mt-2 grid grid-cols-3 gap-3">
              {(["fail", "attention", "pass"] as const).map((st) => {
                const M = STATUS_META[st];
                return (
                  <button key={st} onClick={() => set({ show: st })} className={cn("rounded-md border px-3 py-2 text-left hover:bg-slate-50", filter === st && "border-primary ring-1 ring-primary")}>
                    <div className={cn("flex items-center gap-1 text-[11px]", M.tone)}><M.icon className="size-3.5" />{M.label}</div>
                    <div className="num text-2xl font-semibold">{(s.by_status[st] ?? 0) + (st === "attention" ? s.by_status.explained ?? 0 : 0)}</div>
                  </button>
                );
              })}
            </div>
            <p className="mt-3 text-xs text-slate-700">{s.checks} deterministic checks across {Object.keys(s.families).length} families. If every failed finding were adjusted:</p>
            <div className="mt-1.5 grid grid-cols-2 gap-2 text-xs">
              <div className="rounded-md border px-2.5 py-1.5" title={s.estimated_effect.tax.note}>
                <div className="text-[10.5px] text-muted-foreground">Estimated change in tax ({s.estimated_effect.tax.findings} findings)</div>
                <div>federal <b className="num"><Amt v={s.estimated_effect.tax.federal} sign /></b> · California <b className="num"><Amt v={s.estimated_effect.tax.california} sign /></b></div>
                <div className="text-[10px] text-muted-foreground">estimate from {version}&apos;s tax_effect_rates — not an engine result</div>
              </div>
              <div className="rounded-md border px-2.5 py-1.5" title={s.estimated_effect.balance.note}>
                <div className="text-[10.5px] text-muted-foreground">Change in balance due from payment corrections ({s.estimated_effect.balance.findings})</div>
                <div>federal <b className="num"><Amt v={s.estimated_effect.balance.federal} sign /></b> · California <b className="num"><Amt v={s.estimated_effect.balance.california} sign /></b></div>
                <div className="text-[10px] text-muted-foreground">dollar for dollar; tax itself unchanged</div>
              </div>
            </div>
          </div>
        </div>

        {/* Since last run */}
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          {data.last_run ? <>Last recorded run #{data.last_run.id} by {data.last_run.run_by} · {dateTime(data.last_run.run_at)}.
            {data.changes_since_last_run.new.length + data.changes_since_last_run.changed.length + data.changes_since_last_run.gone.length === 0
              ? " Nothing has changed since."
              : ` Since then: ${data.changes_since_last_run.new.length} new, ${data.changes_since_last_run.changed.length} changed, ${data.changes_since_last_run.gone.length} resolved.`}
            {Object.entries(data.changes_since_last_run.changed_detail).map(([id, d]) => (
              <span key={id} className="rounded bg-amber-50 px-1.5 py-0.5 text-amber-900">
                {id}: {Object.entries(d).map(([k, [a, b]]) => `${k} ${String(a)} → ${String(b)}`).join(", ")}
              </span>
            ))}</>
            : "No run recorded for this version yet — findings shown are live."}
        </div>

        {/* Coverage */}
        <Panel dense title="What TaxProof checked">
          <div className="flex flex-wrap gap-1.5 p-3">
            {Object.entries(s.families).map(([k, f]) => (
              <span key={k} className="inline-flex items-center gap-1 rounded-md border bg-white px-2 py-1 text-[11px]">
                {f.label}
                {f.fail ? <Chip tone="bad">{f.fail}</Chip> : null}
                {f.attention ? <Chip tone="warn">{f.attention}</Chip> : null}
                {f.pass ? <Chip tone="good">{f.pass}</Chip> : null}
              </span>
            ))}
          </div>
        </Panel>

        {/* Findings */}
        <div className="flex items-center gap-1 border-b">
          {(["fail", "attention", "pass", "all"] as const).map((k) => (
            <button key={k} onClick={() => set({ show: k })}
              className={cn("-mb-px border-b-2 px-3 py-2 text-[13px]", filter === k ? "border-primary font-medium text-primary" : "border-transparent text-slate-600 hover:text-slate-900")}>
              {k === "all" ? "All" : STATUS_META[k].label}
            </button>
          ))}
        </div>
        <div className="space-y-2">
          {shown.map((f) => <FindingCard key={f.id} f={f} onOpen={() => set({ finding: f.id })} />)}
          {shown.length === 0 && <p className="text-sm text-muted-foreground">Nothing here.</p>}
        </div>

        {/* Engine diagnostics — kept apart */}
        <Panel dense title={<span className="flex items-center gap-1.5"><Cpu className="size-4 text-violet-600" />Supplied engine&apos;s own diagnostics ({data.engine_diagnostics.length})</span>}>
          <ul className="divide-y">
            {data.engine_diagnostics.map((d) => (
              <li key={d.code} className="flex flex-wrap items-start gap-2 px-4 py-2 text-[12.5px]">
                <Chip tone="engine">ENGINE DIAGNOSTIC</Chip>
                <code className="text-[11px]">{d.code}</code>
                <span className="min-w-0 flex-1 text-slate-700">{d.message}</span>
                {d.related_findings.length > 0
                  ? <span className="text-[11px] text-muted-foreground">TaxProof: {d.related_findings.map((id) => <button key={id} onClick={() => set({ finding: id, show: "all" })} className="ml-1 text-sky-700 hover:underline">{id}</button>)}</span>
                  : <span className="text-[11px] text-muted-foreground">no related TaxProof finding</span>}
              </li>
            ))}
          </ul>
        </Panel>
      </div>

      <Sheet open={!!open} onOpenChange={(o) => !o && set({ finding: null })}>
        <SheetContent className="w-full overflow-y-auto sm:max-w-2xl">
          <SheetHeader className="pb-0">
            <SheetTitle>Independent finding</SheetTitle>
            <SheetDescription>Deterministic check by TaxProof — not the supplied engine. Nothing has been changed on the return.</SheetDescription>
          </SheetHeader>
          <div className="px-4 pb-6">{open && <FindingDetailView id={open} version={version} />}</div>
        </SheetContent>
      </Sheet>
    </LineDrawerProvider>
  );
}

function Mini({ label, v }: { label: string; v: number }) {
  return <div><div className="text-[11px] text-muted-foreground">{label}</div><div className="num text-lg font-semibold"><Amt v={v} /></div></div>;
}

function evidenceHref(e: FindingDetail["evidence_resolved"][number]): string | null {
  if (e.kind === "extracted_value" && e.document_id) return `/evidence?doc=${e.document_id}&page=${e.page}&ev=${e.ref}`;
  if ((e.kind === "page" || e.kind === "document") && e.document_id) return `/evidence?doc=${e.document_id}&page=${e.page ?? 1}`;
  return null;
}

function FindingDetailView({ id, version }: { id: string; version: string }) {
  const { data: f, error } = useApi<FindingDetail>(`/api/challenge/finding?id=${encodeURIComponent(id)}&version=${version}`);
  if (error) return <ErrorState error={error} />;
  if (!f) return <Loading rows={8} />;
  const first = f.lines[0];
  return (
    <div className="space-y-5 text-[13px]">
      <div>
        <div className="flex flex-wrap items-center gap-1.5">
          <Chip tone="info">TAXPROOF INDEPENDENT FINDING</Chip><Chip tone={SEV_TONE[f.severity]}>{f.severity}</Chip>
          <Chip>{STATUS_META[f.status].label}</Chip><span className="text-[11px] text-muted-foreground">{f.family_label} · rule <code>{f.rule}</code></span>
        </div>
        <h3 className="mt-2 text-base font-semibold">{f.title}</h3>
        <p className="mt-1 text-slate-700">{f.summary}</p>
      </div>

      {f.engine && f.independent && (
        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-lg border border-violet-200 bg-violet-50/50 p-3">
            <div className="text-[10.5px] font-semibold uppercase tracking-wide text-violet-700">Supplied engine result</div>
            <div className="num mt-1 text-2xl font-semibold">{unitFmt(f.engine.value, f.unit)}</div>
            <div className="text-[11px] text-slate-600">{f.engine.label} {f.engine.ref && <LineRef k={f.engine.ref.includes(".") ? f.engine.ref : null} />}</div>
          </div>
          <div className="rounded-lg border border-primary/30 bg-white p-3">
            <div className="text-[10.5px] font-semibold uppercase tracking-wide text-primary">TaxProof independent result</div>
            <div className="num mt-1 text-2xl font-semibold">{unitFmt(f.independent.value, f.unit)}</div>
            <div className="text-[11px] text-slate-600">{f.independent.label} — {f.independent.method}</div>
          </div>
        </div>
      )}

      {f.breakdown.length > 0 && (
        <section>
          <H>Breakdown</H>
          <table className="w-full text-xs">
            <tbody>
              {f.breakdown.map((b, i) => (
                <tr key={i} className={cn("border-b last:border-0", b.duplicate === true && "bg-rose-50 text-rose-900")}>
                  {Object.entries(b).filter(([k]) => !["duplicate", "text"].includes(k)).map(([k, v]) => (
                    <td key={k} className="px-2 py-1">{k === "ref" && typeof v === "string" ? <code className="text-[10.5px]">{v}</code> : typeof v === "number" ? <Amt v={v} /> : String(v ?? "")}</td>
                  ))}
                  {b.duplicate === true && <td className="px-2 py-1"><Chip tone="bad">duplicate page</Chip></td>}
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {f.effect && (
        <section>
          <H>{f.effect.potential ? "Potential effect (only if the judgment goes that way)" : f.effect.estimate ? "Estimated downstream tax effect" : "Effect on balance due"}</H>
          <div className="rounded-md border bg-slate-50 p-3">
            <div className="flex gap-6 text-sm"><span>Federal <b className="num"><Amt v={f.effect.federal} sign /></b></span><span>California <b className="num"><Amt v={f.effect.california} sign /></b></span>
              {f.partner_review && <Chip tone="bad">over $1,000 — partner review required</Chip>}</div>
            <p className="mt-1 text-[11px] text-muted-foreground">{f.effect.basis}</p>
          </div>
        </section>
      )}

      {f.impact && (
        <section>
          <H>Affected return lines</H>
          <p className="text-xs text-slate-700">{f.lines.map((k) => <LineRef key={k} k={k} className="mr-2" />)} → {f.impact.affected_lines} downstream lines, reaching {f.impact.headlines.map((h) => h.label).join(", ") || "no headline result"}.</p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {first && <Link href={proveHref(`line:${version}:${first}`)} className="inline-flex items-center gap-1 rounded-md bg-primary px-2.5 py-1 text-xs text-primary-foreground"><ShieldCheck className="size-3.5" />Prove it</Link>}
            {first && <Link href={proveHref(`line:${version}:${first}`, "impact")} className="inline-flex items-center gap-1 rounded-md border px-2.5 py-1 text-xs"><Radar className="size-3.5" />Impact radius</Link>}
            {first && <Link href={proveHref(`line:${version}:${first}`, "down")} className="inline-flex items-center gap-1 rounded-md border px-2.5 py-1 text-xs"><ArrowLeftRight className="size-3.5" />Where it goes</Link>}
          </div>
        </section>
      )}

      <section>
        <H>Evidence ({f.evidence_resolved.length})</H>
        <ul className="divide-y rounded-md border text-xs">
          {f.evidence_resolved.map((e) => {
            const href = evidenceHref(e);
            return (
              <li key={e.ref} className="flex items-center gap-2 px-3 py-1.5">
                <code className="text-[10.5px] text-slate-500">{e.ref}</code>
                <span className="min-w-0 flex-1 truncate text-slate-700">{e.label}</span>
                {e.value != null && typeof e.value !== "object" && <span className="num"><Amt v={e.value} /></span>}
                {href && <Link href={href} className="text-sky-700 hover:underline">open</Link>}
              </li>
            );
          })}
        </ul>
      </section>

      {f.engine_diagnostics.length > 0 && <p className="text-xs text-violet-800"><Chip tone="engine">ENGINE</Chip> The engine also raised {f.engine_diagnostics.join(", ")} — see its own diagnostic for its wording.</p>}
      {f.status === "fail" && <AdjustFromFinding f={f} version={version} />}
      <ExplainFinding findingId={f.id} version={version} />
    </div>
  );
}

function H({ children }: { children: React.ReactNode }) {
  return <h4 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{children}</h4>;
}

function AdjustFromFinding({ f, version }: { f: FindingDetail; version: string }) {
  const { data: me } = useApi<Me>("/api/session/me");
  const { data: adj, mutate: reload } = useApi<{ adjustments: { id: number; finding_id: string | null; status: string; adjusted_value: number; unit: string }[] }>("/api/adjustments");
  const mutate = useMutate();
  const refreshAfter = useRefreshAfter();
  const [err, setErr] = useState<string | null>(null);
  const [reopened, setReopened] = useState("");
  const existing = adj?.adjustments.filter((a) => a.finding_id === f.id) ?? [];
  const active = existing.find((a) => a.status !== "undone");
  const canAdjust = !!me?.permissions.includes("adjust") && !!f.engine && !!f.independent && version === f.version;
  const create = async (apply: boolean) => {
    setErr(null);
    try {
      const r = await mutate<{ reopened_signoffs?: Reopened }>("/api/adjustments/from-finding", { finding_id: f.id, apply });
      setReopened(reopenedText(r.reopened_signoffs));
      reload();
      refreshAfter("adjustment");
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : "Failed");
    }
  };
  return (
    <section className="rounded-md border border-orange-200 bg-orange-50/50 p-3 text-xs">
      <div className="flex items-start gap-1.5 text-orange-900"><AlertTriangle className="mt-0.5 size-3.5" />
        <span>Acting on this means an adjustment with a reason and evidence; a reviewer (or partner, over $1,000) approves it. TaxProof never changes a tax number by itself.</span></div>
      {active ? (
        <>
          <p className="mt-2">Adjustment #{active.id} is <b>{active.status}</b> → <Link href="/return?tab=adjustments" className="text-sky-700 hover:underline">open in Adjustments</Link></p>
          {reopened && <p className="mt-1 text-rose-700">{reopened.replace(/^ · /, "")} → <Link href="/review?tab=signoffs" className="underline">see why</Link></p>}
        </>
      ) : canAdjust ? (
        <div className="mt-2 flex gap-2">
          <Button size="sm" onClick={() => create(true)}>Create &amp; apply adjustment</Button>
          <Button size="sm" variant="outline" onClick={() => create(false)}>Propose adjustment</Button>
        </div>
      ) : <p className="mt-2 text-muted-foreground">{f.engine && f.independent ? "Your role cannot create adjustments." : "This finding has no single replacement value; it needs a judgment."}</p>}
      {err && <p className="mt-1 text-rose-700">{err}</p>}
    </section>
  );
}
