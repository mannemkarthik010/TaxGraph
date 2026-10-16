"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { BookOpen, ChevronRight, Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { useApi } from "@/lib/api";
import { date, money } from "@/lib/format";
import type { LineBrief, LineGroup, VersionRow } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Chip, ErrorState, Loading, Money, PageHeader, Panel } from "@/components/tp/primitives";
import { LineDetail } from "@/components/tp/line-detail";
import type { AreaSummary } from "@/lib/schedule-types";
import { AreaCard } from "@/components/tp/schedules/area-grid";
import { LineDrawerProvider, SCHEDULE_TITLES } from "@/components/tp/schedules/common";
import { ScheduleView } from "@/components/tp/schedules/schedule-view";
import { AdjustmentsTab } from "@/components/tp/adjustments/adjustments";
import { TimeMachineTab, WhatIfTab } from "@/components/tp/adjustments/time-machine";

type Tab = "areas" | "summary" | "prior" | "records" | "adjustments" | "time" | "whatif" | "lines";
const TABS: [Tab, string][] = [["areas", "Areas"], ["summary", "Return summary"], ["prior", "Prior year"], ["records", "Records"],
  ["adjustments", "Adjustments"], ["time", "Tax Time Machine"], ["whatif", "What-If Lab"], ["lines", "All lines"]];

/** The records a CPA expects, each with where it lives. */
const RECORDS: { title: string; href: (v: string) => string; what: string }[] = [
  { title: "Return summary & tax computation", href: (v) => `/return?tab=summary&v=${v}`, what: "Form 1040 and 540NR top to bottom, against 2024" },
  { title: "Prior-year comparison", href: (v) => `/return?tab=prior&v=${v}`, what: "Every line with a 2024 counterpart; swings flagged by firm standard" },
  { title: "Area summaries", href: (v) => `/return?tab=areas&v=${v}`, what: "Eleven tax areas: figures, evidence coverage, open items, owners" },
  { title: "Document index", href: () => "/evidence", what: "74 documents with status, extraction and where each one landed" },
  { title: SCHEDULE_TITLES["books-to-tax"], href: (v) => `/return/records/books-to-tax?v=${v}`, what: "Client P&L walked to Schedule C net profit, reconciled to the dollar" },
  { title: SCHEDULE_TITLES.depreciation, href: (v) => `/return/records/depreciation?v=${v}`, what: "Method, life, federal vs California vs AMT, disposals and recapture" },
  { title: SCHEDULE_TITLES.brokerage, href: (v) => `/return/records/brokerage?v=${v}`, what: "295 sales summarised by source and box; lots on demand" },
  { title: SCHEDULE_TITLES.rentals, href: (v) => `/return/records/rentals?v=${v}`, what: "Two properties, Form 8582, the condo sale on Form 4797" },
  { title: SCHEDULE_TITLES["k1-basis"], href: (v) => `/return/records/k1-basis?v=${v}`, what: "K-1 lines and S-corp basis rolled forward by year" },
  { title: SCHEDULE_TITLES["state-allocation"], href: (v) => `/return/records/state-allocation?v=${v}`, what: "Residency timeline and the Schedule CA (540NR) split" },
  { title: SCHEDULE_TITLES.carryovers, href: (v) => `/return/records/carryovers?v=${v}`, what: "Into 2025, used, and out to 2026 — federal and California" },
];

const PAGE = 100;

export default function ReturnPage() {
  return <Suspense fallback={<Loading />}><ReturnView /></Suspense>;
}

function ReturnView() {
  const params = useSearchParams();
  const router = useRouter();
  const { data: versions, error } = useApi<{ current: string; versions: VersionRow[] }>("/api/return/versions");
  const version = params.get("v") ?? versions?.current ?? "v3";
  const area = params.get("area");
  const form = params.get("form");
  const openLine = params.get("line");
  const tab = (params.get("tab") as Tab) ?? (area || form || openLine ? "lines" : "areas");
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [offset, setOffset] = useState(0);

  useEffect(() => {
    const t = setTimeout(() => { setDebounced(q); setOffset(0); }, 200);
    return () => clearTimeout(t);
  }, [q]);
  useEffect(() => setOffset(0), [area, form, version]);

  const set = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params.toString());
    for (const [k, v] of Object.entries(patch)) {
      if (v === null) next.delete(k);
      else next.set(k, v);
    }
    router.replace(`/return?${next.toString()}`, { scroll: false });
  };

  const { data: groups } = useApi<LineGroup[]>(`/api/return/groups?version=${version}`);
  const qs = useMemo(() => {
    const s = new URLSearchParams({ version, offset: String(offset), limit: String(PAGE) });
    if (area) s.set("area", area);
    if (form) s.set("form", form);
    if (debounced) s.set("q", debounced);
    return s.toString();
  }, [version, area, form, debounced, offset]);
  const { data: lines } = useApi<{ total: number; items: LineBrief[] }>(`/api/return/lines?${qs}`);

  return (
    <div>
      <PageHeader title="Return" subtitle="The supplied engine's return as a workpaper: areas first, records on demand, every number one click from its evidence." />
      <ErrorState error={error} />

      {/* Versions */}
      <div className="mb-4 grid gap-2 sm:grid-cols-3">
        {versions?.versions.map((v) => (
          <button key={v.version} onClick={() => set({ v: v.version })}
            className={cn("rounded-lg border bg-card px-3 py-2 text-left shadow-xs transition",
              v.version === version ? "border-primary ring-1 ring-primary" : "hover:border-slate-300")}>
            <div className="flex items-center justify-between">
              <span className="text-[13px] font-semibold">{v.version} <span className="font-normal text-muted-foreground">· {date(v.computed_at)}</span></span>
              {v.is_current ? <Chip tone="info">current</Chip> : <Chip tone="muted">superseded</Chip>}
            </div>
            <div className="mt-1 flex gap-4 text-xs">
              <span>Fed tax <b className="num font-medium">{money(v.federal_total_tax)}</b></span>
              <span>CA tax <b className="num font-medium">{money(v.california_total_tax)}</b></span>
            </div>
            <div className="mt-1 line-clamp-2 text-[11px] text-muted-foreground">{v.trigger}</div>
          </button>
        ))}
      </div>
      <div className="mb-4 flex flex-wrap items-center gap-1 border-b">
        {TABS.map(([t, label]) => (
          <button key={t} onClick={() => set({ tab: t, area: null, form: null })}
            className={cn("-mb-px border-b-2 px-3 py-2 text-[13px]", tab === t ? "border-primary font-medium text-primary" : "border-transparent text-slate-600 hover:text-slate-900")}>
            {label}
          </button>
        ))}
      </div>

      <LineDrawerProvider version={version}>
        {tab === "areas" && <AreasTab version={version} />}
        {tab === "summary" && <ScheduleView name="tax-computation" version={version} />}
        {tab === "prior" && <ScheduleView name="prior-year" version={version} />}
        {tab === "records" && <RecordsTab version={version} />}
        {tab === "adjustments" && <AdjustmentsTab />}
        {tab === "time" && <TimeMachineTab />}
        {tab === "whatif" && <WhatIfTab />}
      </LineDrawerProvider>


      {tab === "lines" && (
      <div className="grid gap-4 lg:grid-cols-[260px_1fr]">
        {/* Areas */}
        <Panel title="Areas" dense>
          {!groups ? <div className="p-3"><Loading /></div> : (
            <ul className="py-1 text-[13px]">
              <li>
                <button onClick={() => set({ area: null, form: null })}
                  className={cn("flex w-full justify-between px-3 py-1.5 hover:bg-slate-50", !area && "font-medium text-primary")}>
                  All lines <span className="num text-muted-foreground">{groups.reduce((a, g) => a + g.line_count, 0)}</span>
                </button>
              </li>
              {groups.map((g) => (
                <li key={g.area}>
                  <button onClick={() => set({ area: g.area, form: null })}
                    className={cn("flex w-full justify-between px-3 py-1.5 hover:bg-slate-50", area === g.area && !form && "font-medium text-primary")}>
                    {g.title} <span className="num text-muted-foreground">{g.line_count}</span>
                  </button>
                  {area === g.area && (
                    <ul className="pb-1">
                      {g.forms.map((f) => (
                        <li key={f.form}>
                          <button onClick={() => set({ form: f.form })}
                            className={cn("flex w-full justify-between py-1 pr-3 pl-7 text-xs hover:bg-slate-50", form === f.form && "font-medium text-primary")}>
                            <code>{f.form}</code><span className="num text-muted-foreground">{f.count}</span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Panel>

        {/* Lines */}
        <Panel dense title={
          <span className="flex items-center gap-2">
            Lines {lines && <span className="font-normal text-muted-foreground">· {lines.total} {area ? `in ${groups?.find((g) => g.area === area)?.title ?? area}` : ""}{form ? ` / ${form}` : ""}</span>}
          </span>}
          actions={
            <div className="relative w-56">
              <Search className="absolute top-1/2 left-2 size-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search key or label…" className="h-7 pl-7 text-xs" />
            </div>}>
          {!lines ? <div className="p-4"><Loading rows={8} /></div> : (
            <>
              <ul className="divide-y">
                {lines.items.map((l) => (
                  <li key={l.key}>
                    <button onClick={() => set({ line: l.key })}
                      className={cn("grid w-full grid-cols-[110px_1fr_auto] items-center gap-3 px-4 py-1.5 text-left text-[13px] hover:bg-slate-50",
                        openLine === l.key && "bg-primary/5")}>
                      <code className="truncate text-[11.5px] text-slate-500">{l.key}</code>
                      <span className="truncate">
                        {l.label}
                        <span className="ml-2 text-[11px] text-muted-foreground">
                          {l.source_count > 0 && `${l.source_count} source${l.source_count > 1 ? "s" : ""}`}
                          {l.source_count > 0 && l.input_count > 0 && " · "}
                          {l.input_count > 0 && `${l.input_count} input${l.input_count > 1 ? "s" : ""}`}
                        </span>
                      </span>
                      <Money value={l.value} className="text-right" />
                    </button>
                  </li>
                ))}
              </ul>
              {lines.total > PAGE && (
                <div className="flex items-center justify-between border-t px-4 py-2 text-xs text-muted-foreground">
                  <span>{offset + 1}–{Math.min(offset + PAGE, lines.total)} of {lines.total}</span>
                  <div className="flex gap-2">
                    <button disabled={offset === 0} onClick={() => setOffset(offset - PAGE)} className="rounded border px-2 py-0.5 disabled:opacity-40">Prev</button>
                    <button disabled={offset + PAGE >= lines.total} onClick={() => setOffset(offset + PAGE)} className="rounded border px-2 py-0.5 disabled:opacity-40">Next</button>
                  </div>
                </div>
              )}
            </>
          )}
        </Panel>
      </div>
      )}

      <Sheet open={!!openLine} onOpenChange={(o) => !o && set({ line: null })}>
        <SheetContent className="w-full overflow-y-auto sm:max-w-xl">
          <SheetHeader className="pb-0">
            <SheetTitle>Line detail</SheetTitle>
            <SheetDescription>Supplied engine output with its cited evidence. Nothing here is recomputed.</SheetDescription>
          </SheetHeader>
          <div className="px-4 pb-6">
            {openLine && <LineDetail version={version} lineKey={openLine} onOpenLine={(k) => set({ line: k })} />}
          </div>
        </SheetContent>
      </Sheet>
    </div>
  );
}

function AreasTab({ version }: { version: string }) {
  const { data, error } = useApi<{ version: string; areas: AreaSummary[] }>(`/api/workpaper/area-summaries?version=${version}`);
  if (error) return <ErrorState error={error} />;
  if (!data) return <Loading rows={8} />;
  const totals = data.areas.reduce((t, a) => ({
    lines: t.lines + a.line_count, traceable: t.traceable + a.traceable_lines, values: t.values + a.evidence.values,
    verified: t.verified + a.evidence.verified_values,
    open: t.open + a.issues.open_notes + a.issues.conflicts + a.issues.needs_review + a.issues.engine_diagnostics,
  }), { lines: 0, traceable: 0, values: 0, verified: 0, open: 0 });
  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">
        {totals.traceable} of {totals.lines} lines trace to evidence · {totals.verified} of {totals.values} cited source values verified · {totals.open} open items across areas.
        Lines that only total other lines (AGI, total tax…) sit in the return summary.
      </p>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
        {data.areas.map((a) => <AreaCard key={a.key} a={a} version={version} />)}
      </div>
    </div>
  );
}

function RecordsTab({ version }: { version: string }) {
  return (
    <Panel dense title={<span className="flex items-center gap-1.5"><BookOpen className="size-4" />Records a CPA expects</span>}>
      <ul className="divide-y">
        {RECORDS.map((r) => (
          <li key={r.title}>
            <Link href={r.href(version)} className="flex items-center gap-3 px-4 py-2.5 hover:bg-slate-50">
              <div className="flex-1">
                <div className="text-[13px] font-medium">{r.title}</div>
                <div className="text-xs text-muted-foreground">{r.what}</div>
              </div>
              <ChevronRight className="size-4 text-slate-400" />
            </Link>
          </li>
        ))}
      </ul>
    </Panel>
  );
}
