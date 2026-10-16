"use client";

import Link from "next/link";
import { Suspense, use } from "react";
import { useSearchParams } from "next/navigation";
import { ArrowLeft, ShieldCheck } from "lucide-react";
import { useApi } from "@/lib/api";
import { humanize, pct } from "@/lib/format";
import { proveHref } from "@/lib/links";
import type { AreaDetail } from "@/lib/schedule-types";
import { Chip, ErrorState, Loading, Panel } from "@/components/tp/primitives";
import { AreaSignoffs } from "@/components/tp/collab/signoffs";
import { NotesThread } from "@/components/tp/notes-thread";
import { Amt, LineDrawerProvider, LineRef, SCHEDULE_TITLES, SectionTitle } from "@/components/tp/schedules/common";
import { ScheduleView } from "@/components/tp/schedules/schedule-view";

export default function AreaPage({ params }: { params: Promise<{ key: string }> }) {
  const { key } = use(params);
  return <Suspense fallback={<Loading />}><Area areaKey={key} /></Suspense>;
}

function Area({ areaKey }: { areaKey: string }) {
  const sp = useSearchParams();
  const version = sp.get("v") ?? "v3";
  const { data: a, error } = useApi<AreaDetail>(`/api/workpaper/area-summaries/${areaKey}?version=${version}`);
  if (error) return <ErrorState error={error} />;
  if (!a) return <Loading rows={8} />;
  return (
    <LineDrawerProvider version={version}>
      <div className="space-y-5">
        <div>
          <Link href={`/return?tab=areas&v=${version}`} className="inline-flex items-center gap-1 text-xs text-sky-700 hover:underline"><ArrowLeft className="size-3" />All areas</Link>
          <div className="mt-1 flex flex-wrap items-end justify-between gap-3">
            <div>
              <h1 className="text-xl font-semibold tracking-tight">{a.title}</h1>
              <p className="text-sm text-muted-foreground">Return {a.version} · forms {a.forms.join(", ") || "—"} · {a.line_count} lines · {a.evidence.documents.length} source documents</p>
            </div>
            <div className="flex gap-1 text-[11px]">
              <Chip>Preparer: {a.status.preparer_name ?? "—"} · {humanize(a.status.preparer)}</Chip>
              <Chip>Reviewer: {a.status.reviewer_name ?? "—"} · {humanize(a.status.reviewer)}</Chip>
            </div>
          </div>
        </div>

        {/* Figures + posture */}
        <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
          <Panel dense title="Key figures vs 2024">
            <table className="w-full text-[13px]">
              <tbody>
                {a.figures.map((f) => (
                  <tr key={f.key} className="border-b last:border-0">
                    <td className="px-4 py-2"><LineRef k={f.key} /> {f.label}</td>
                    <td className="px-2 text-right text-base font-semibold"><Amt v={f.value} /></td>
                    <td className="px-2 text-right text-muted-foreground">{f.prior_year != null ? <>2024 <Amt v={f.prior_year} /></> : "no 2024 line"}</td>
                    <td className="px-2 text-right">{f.change != null && <><Amt v={f.change} sign /> <span className="text-[11px] text-muted-foreground">{pct(f.change_pct)}</span></>}</td>
                    <td className="px-4 text-right">
                      {f.variance_flag && <Chip tone="warn">explain variance</Chip>}
                      <Link href={proveHref(`line:${a.version}:${f.key}`)} className="ml-2 inline-flex items-center gap-0.5 text-[11px] text-sky-700 hover:underline"><ShieldCheck className="size-3" />Prove</Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
          <Panel title="Assurance posture">
            <dl className="grid grid-cols-[1fr_auto] gap-y-1 text-xs">
              <dt>Lines traceable to evidence</dt><dd className="num font-medium">{a.traceable_lines} / {a.line_count}</dd>
              <dt>Source values verified</dt><dd className="num font-medium">{a.evidence.verified_values} / {a.evidence.values}</dd>
              <dt>Lines verified</dt><dd className="num font-medium">{a.evidence.verified_lines}</dd>
              <dt>Evidence conflicts</dt><dd className={a.issues.conflicts ? "font-medium text-rose-700" : ""}>{a.issues.conflicts}</dd>
              <dt>Values needing review</dt><dd className={a.issues.needs_review ? "font-medium text-amber-700" : ""}>{a.issues.needs_review}</dd>
              <dt>Prior-year swings to explain</dt><dd className={a.issues.variances ? "font-medium text-amber-700" : ""}>{a.issues.variances}</dd>
              <dt>Open notes (blocking)</dt><dd>{a.issues.open_notes} ({a.issues.blocking_notes})</dd>
              {a.budget_hours != null && <><dt>Budget</dt><dd>{a.budget_hours}h</dd></>}
            </dl>
            {a.diagnostics.length > 0 && (
              <div className="mt-3 space-y-1">
                {a.diagnostics.map((d) => (
                  <div key={d.code} className="rounded border border-violet-200 bg-violet-50/60 px-2 py-1 text-[11px]">
                    <Chip tone="engine">ENGINE</Chip> <code>{d.code}</code> {d.message}
                  </div>
                ))}
              </div>
            )}
          </Panel>
        </div>

        {/* Schedules for this area */}
        {a.schedules.map((s) => (
          <section key={s} className="space-y-2">
            <SectionTitle id={s}>{SCHEDULE_TITLES[s] ?? s}</SectionTitle>
            <ScheduleView name={s} version={a.version}
              activity={s === "depreciation" ? (areaKey === "business" ? "Business" : areaKey === "rentals" ? "Rental" : undefined) : undefined} />
          </section>
        ))}

        <div className="grid gap-4 lg:grid-cols-[1fr_380px]">
          <Panel dense title={`Lines in ${a.title}`} actions={a.lots_hidden > 0 && <span className="text-[11px] text-muted-foreground">{a.lots_hidden} individual sales are in the brokerage schedule above</span>}>
            <ul className="max-h-[420px] divide-y overflow-y-auto">
              {a.lines_preview.map((l) => (
                <li key={l.key} className="grid grid-cols-[120px_1fr_auto] items-center gap-3 px-4 py-1 text-[12.5px]">
                  <LineRef k={l.key} /><span className="truncate">{l.label}</span><Amt v={l.value} />
                </li>
              ))}
            </ul>
          </Panel>
          <div className="space-y-4">
            {a.open_notes.some((n) => n.via !== "area") && (
              <Panel dense title={`Open notes on this area's lines and evidence (${a.open_notes.filter((n) => n.via !== "area").length})`}>
                <ul className="divide-y text-[12.5px]">
                  {a.open_notes.filter((n) => n.via !== "area").map((n) => (
                    <li key={n.id} className="px-4 py-2">
                      <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
                        {n.kind === "review_note" ? <Chip tone="info">Review note</Chip> : <Chip>Note</Chip>}
                        {n.blocking && <Chip tone="bad">blocks filing</Chip>}
                        <code className="text-slate-700">{n.target_ref}</code> · {n.author_name}
                      </div>
                      <p className="mt-0.5 text-slate-800">{n.body}</p>
                    </li>
                  ))}
                </ul>
              </Panel>
            )}
            <Panel title="Area notes">
              <NotesThread targetRef={`area:${areaKey}`} compact />
            </Panel>
          </div>
        </div>
        <AreaSignoffs areaKey={areaKey} />
      </div>
    </LineDrawerProvider>
  );
}
