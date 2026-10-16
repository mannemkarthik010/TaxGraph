"use client";

import Link from "next/link";
import { Fragment, useState } from "react";
import { ArrowRight, CheckCircle2, ChevronDown, ChevronRight, FlaskConical, GitCompare, XCircle } from "lucide-react";
import { useApi } from "@/lib/api";
import type { TimeMachine, WhatIf } from "@/lib/adjust-types";
import { date, dateTime, humanize } from "@/lib/format";
import type { VersionRow } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Chip, ErrorState, Loading, Panel } from "../primitives";
import { Amt, LineRef } from "../schedules/common";

export function TimeMachineTab() {
  const { data: versions } = useApi<{ current: string; versions: VersionRow[] }>("/api/return/versions");
  const ids = versions?.versions.map((v) => v.version) ?? [];
  const [from, setFrom] = useState<string | null>(null);
  const [to, setTo] = useState<string | null>(null);
  const a = from ?? ids[ids.length - 2] ?? "v2";
  const b = to ?? ids[ids.length - 1] ?? "v3";
  const { data, error } = useApi<TimeMachine>(a !== b ? `/api/return/time-machine?from=${a}&to=${b}` : null);
  const [openArea, setOpenArea] = useState<string | null>(null);

  const Picker = ({ value, onPick }: { value: string; onPick: (v: string) => void }) => (
    <div className="inline-flex rounded-md border bg-white p-0.5 text-xs">
      {ids.map((v) => <button key={v} onClick={() => onPick(v)} className={cn("rounded px-2 py-1", v === value ? "bg-slate-800 text-white" : "text-slate-600")}>{v}</button>)}
    </div>
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <GitCompare className="size-4 text-primary" /> Compare <Picker value={a} onPick={setFrom} /> <ArrowRight className="size-4" /> <Picker value={b} onPick={setTo} />
        {data?.consistency_with_engine && (data.consistency_with_engine.agrees
          ? <Chip tone="good"><CheckCircle2 className="size-3" />all {data.consistency_with_engine.computed_changes} changes match the engine&apos;s own change list</Chip>
          : <Chip tone="bad"><XCircle className="size-3" />differs from the engine&apos;s change list</Chip>)}
      </div>
      {a === b && <p className="text-sm text-muted-foreground">Pick two different versions.</p>}
      <ErrorState error={error} />
      {a !== b && !data && !error && <Loading rows={8} />}
      {data && (
        <>
          <div className="grid gap-4 lg:grid-cols-2">
            {(["federal", "california"] as const).map((j) => (
              <Panel key={j} dense title={<span>{j === "federal" ? "Federal" : "California"} · {data.from.version} → {data.to.version}
                <span className={cn("ml-2 font-normal", (data.tax_change[j] ?? 0) > 0 ? "text-rose-700" : "text-emerald-700")}>total tax <Amt v={data.tax_change[j]} sign /></span></span>}>
                <table className="w-full text-[12.5px]">
                  <tbody>
                    {data.summary[j].map((r) => (
                      <tr key={r.field} className={cn("border-b last:border-0", r.field === "total_tax" && "font-medium")}>
                        <td className="px-4 py-1">{humanize(r.field)}</td>
                        <td className="px-2 text-right text-muted-foreground"><Amt v={r.from} /></td>
                        <td className="px-2 text-right"><Amt v={r.to} /></td>
                        <td className="px-4 text-right">{r.change ? <Amt v={r.change} sign /> : <span className="text-slate-300">—</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Panel>
            ))}
          </div>

          <Panel title="Why it changed">
            <div className="space-y-3 text-[13px]">
              {data.why.triggers.map((t) => (
                <p key={t.version}><Chip tone="engine">{t.version} · {date(t.computed_at)}</Chip> <span className="text-slate-700">{t.trigger}</span></p>
              ))}
              <div>
                <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Where the change entered ({data.drivers.length} driver lines — changed lines whose own inputs did not change)</div>
                <ul className="divide-y rounded-md border">
                  {data.drivers.map((d) => (
                    <li key={d.key} className="flex flex-wrap items-center gap-2 px-3 py-1.5 text-xs">
                      <Chip tone={d.change === "added" ? "good" : d.change === "removed" ? "bad" : "info"}>{d.change}</Chip>
                      <LineRef k={d.key} /><span className="min-w-0 flex-1 truncate">{d.label}</span>
                      <span className="num"><Amt v={d.old} /> → <b><Amt v={d.new} /></b></span>
                      {d.new_source_documents.length > 0 && <span className="text-muted-foreground">new evidence: {d.new_source_documents.map((x) => <Link key={x} href={`/evidence?doc=${x}&page=1`} className="ml-1 text-sky-700 hover:underline">{x}</Link>)}</span>}
                    </li>
                  ))}
                </ul>
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                <div>
                  <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Season events between the runs</div>
                  <ul className="space-y-0.5 text-xs">{data.why.timeline.map((t) => <li key={t.id}><span className="num text-muted-foreground">{dateTime(t.at)}</span> {humanize(t.event)} {t.refs.slice(0, 3).map((r) => <code key={r} className="ml-1 text-[10.5px]">{r}</code>)}</li>)}</ul>
                </div>
                <div>
                  <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Documents</div>
                  <ul className="space-y-0.5 text-xs">
                    {data.documents.now_used.map((d) => <li key={d.id}><Chip tone="good">now used</Chip> <Link href={`/evidence?doc=${d.id}&page=1`} className="text-sky-700 hover:underline">{d.id}</Link> {d.title} <span className="text-muted-foreground">· received {date(d.received_at)}</span></li>)}
                    {data.documents.no_longer_used.map((d) => <li key={d.id}><Chip tone="muted">no longer used</Chip> {d.id} {d.title}</li>)}
                    {data.documents.newly_superseded.map((d) => <li key={d.id}><Chip tone="warn">superseded</Chip> {d.id} {d.title}</li>)}
                  </ul>
                  {(data.diagnostics.added.length + data.diagnostics.removed.length + data.diagnostics.changed.length) > 0 && (
                    <>
                      <div className="mb-1 mt-2 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Engine diagnostics</div>
                      <ul className="space-y-0.5 text-xs">
                        {data.diagnostics.added.map((d) => <li key={d.code}><Chip tone="engine">+ {d.code}</Chip> {d.message}</li>)}
                        {data.diagnostics.removed.map((d) => <li key={d.code}><Chip tone="muted">− {d.code}</Chip> {d.message}</li>)}
                        {data.diagnostics.changed.map((d) => <li key={d.code}><Chip tone="engine">~ {d.code}</Chip> {d.to}</li>)}
                      </ul>
                    </>
                  )}
                </div>
              </div>
            </div>
          </Panel>

          <Panel dense title={`All changed lines (${data.lines.total}) — by area`}>
            <ul className="divide-y">
              {Object.entries(data.lines.by_area).sort((x, y) => Object.values(y[1]).reduce((s, n) => s + n, 0) - Object.values(x[1]).reduce((s, n) => s + n, 0)).map(([area, counts]) => {
                const items = data.lines.changes.filter((c) => c.area === area);
                const open = openArea === area;
                return (
                  <li key={area}>
                    <button onClick={() => setOpenArea(open ? null : area)} className="flex w-full items-center gap-2 px-4 py-1.5 text-left text-[13px] hover:bg-slate-50">
                      {open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
                      <span className="flex-1">{humanize(area)}</span>
                      {Object.entries(counts).map(([k, n]) => <Chip key={k} tone={k === "added" ? "good" : k === "removed" ? "bad" : "neutral"}>{n} {k}</Chip>)}
                    </button>
                    {open && (
                      <ul className="max-h-72 divide-y overflow-y-auto border-t bg-slate-50/50 text-xs">
                        {items.map((c) => (
                          <li key={c.key} className="grid grid-cols-[120px_1fr_auto_auto] items-center gap-3 px-6 py-1">
                            <LineRef k={c.key} /><span className="truncate">{c.label}</span>
                            <span className="num text-muted-foreground"><Amt v={c.old} /> → <Amt v={c.new} /></span>
                            <span className="num w-20 text-right">{c.delta != null ? <Amt v={c.delta} sign /> : c.change}</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </li>
                );
              })}
            </ul>
          </Panel>
        </>
      )}
    </div>
  );
}

export function WhatIfTab() {
  const { data, error } = useApi<WhatIf>("/api/return/what-if");
  const [open, setOpen] = useState<string | null>(null);
  if (error) return <ErrorState error={error} />;
  if (!data) return <Loading rows={6} />;
  return (
    <div className="space-y-4">
      <p className="flex items-center gap-1.5 text-sm text-slate-700"><FlaskConical className="size-4 text-violet-600" />{data.note}</p>
      <div className="grid gap-3 xl:grid-cols-2">
        {data.alternatives.map((a) => (
          <div key={a.id} className="rounded-lg border bg-card p-3.5 shadow-xs">
            <div className="flex flex-wrap items-center gap-1.5">
              <Chip tone="engine">engine alternative · base {a.base_version}</Chip>
              {Object.entries(a.choices).map(([k, v]) => <Chip key={k}>{k}: {v}</Chip>)}
            </div>
            <p className="mt-1.5 text-[13.5px] font-medium">{a.description}</p>
            <table className="mt-2 w-full text-xs">
              <thead className="text-left text-[10.5px] uppercase text-muted-foreground"><tr><th className="font-medium" /><th className="text-right font-medium">Base total tax</th><th className="text-right font-medium">Alternative</th><th className="text-right font-medium">Change</th></tr></thead>
              <tbody>
                {(["federal", "california"] as const).map((j) => (
                  <tr key={j} className="border-t">
                    <td className="py-1">{j === "federal" ? "Federal" : "California"}</td>
                    <td className="text-right"><Amt v={a[j].base.total_tax} /></td>
                    <td className="text-right"><Amt v={a[j].alternative.total_tax} /></td>
                    <td className={cn("text-right font-semibold", a[j].total_tax_change > 0 ? "text-rose-700" : a[j].total_tax_change < 0 ? "text-emerald-700" : "")}><Amt v={a[j].total_tax_change} sign /></td>
                  </tr>
                ))}
              </tbody>
            </table>
            {a.related_findings.length > 0 && (
              <p className="mt-2 text-xs">Related Challenge finding: {a.related_findings.map((f) => <Link key={f.id} href={`/challenge?finding=${encodeURIComponent(f.id)}&show=all`} className="text-sky-700 hover:underline">{f.title}</Link>)}</p>
            )}
            <button onClick={() => setOpen(open === a.id ? null : a.id)} className="mt-2 inline-flex items-center gap-1 text-xs text-sky-700 hover:underline">
              {open === a.id ? <ChevronDown className="size-3" /> : <ChevronRight className="size-3" />}{a.changed_lines.length} lines change
            </button>
            {open === a.id && (
              <ul className="mt-1 max-h-60 divide-y overflow-y-auto rounded border text-xs">
                {a.changed_lines.map((c) => (
                  <li key={c.key} className="grid grid-cols-[130px_1fr_auto] gap-2 px-2 py-1"><LineRef k={c.key} /><span className="truncate">{c.label}</span><span className="num"><Amt v={c.old} /> → <Amt v={c.new} /></span></li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </div>
      {data.extension && (
        <Panel title={`April extension estimate (from ${data.extension.based_on_version}, ${date(data.extension.computed_at)})`}>
          <div className="grid gap-4 text-xs md:grid-cols-2">
            {(["federal", "california"] as const).map((j) => (
              <dl key={j} className="grid grid-cols-[1fr_auto] gap-y-0.5">
                <dt className="col-span-2 font-semibold">{j === "federal" ? "Federal (Form 4868)" : "California (FTB 3519)"}</dt>
                {Object.entries(data.extension![j]).map(([k, v]) => (
                  <Fragment key={k}><dt className="text-muted-foreground">{humanize(k)}</dt><dd className="text-right">{typeof v === "number" ? <Amt v={v} /> : String(v)}</dd></Fragment>
                ))}
              </dl>
            ))}
          </div>
        </Panel>
      )}
    </div>
  );
}
