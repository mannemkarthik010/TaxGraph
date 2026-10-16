"use client";

import Link from "next/link";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { AlertTriangle, ArrowLeftRight, ArrowUpRight, BadgeCheck, ChevronLeft, ChevronRight, Copy, FileText, Radar, Search } from "lucide-react";
import { proveHref } from "@/lib/links";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { useApi } from "@/lib/api";
import { date, humanize, money } from "@/lib/format";
import type { DocStatus, DocumentDetail, DocumentRow, ExtractedValue, ValueDetail } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Chip, ErrorState, Loading, Money } from "@/components/tp/primitives";
import { PageSurface, type PageLayout } from "@/components/tp/page-surface";
import { VerificationPanel } from "@/components/tp/verification-panel";

const STATUS_TONE: Record<string, "good" | "warn" | "bad" | "info" | "muted" | "neutral"> = {
  used: "good", unused: "warn", superseded: "muted", corrected: "info", partial: "warn",
  not_extracted: "muted", conflict: "bad", duplicate: "bad", needs_review: "warn",
};
const FILTERS = ["all", "conflict", "duplicate", "needs_review", "unused", "superseded", "corrected", "partial", "not_extracted"];

export default function EvidencePage() {
  return <Suspense fallback={<Loading />}><Explorer /></Suspense>;
}

function StatusChips({ statuses, compact }: { statuses: DocStatus[]; compact?: boolean }) {
  return (
    <>
      {statuses.filter((s) => !compact || s.code !== "used").map((s, i) => (
        <Chip key={`${s.code}${i}`} tone={STATUS_TONE[s.code] ?? "neutral"} title={s.detail}>{s.label}</Chip>
      ))}
    </>
  );
}

function fmtValue(v: ExtractedValue | ValueDetail) {
  if (v.value === null || v.value === undefined) return "—";
  if (v.value_type === "money" && typeof v.value === "number") return money(v.value);
  return String(v.value);
}

function Explorer() {
  const params = useSearchParams();
  const router = useRouter();
  const docId = params.get("doc");
  const pageNo = Number(params.get("page") ?? 1);
  const evId = params.get("ev");
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState("all");
  const [showBox, setShowBox] = useState(true);
  const [layout, setLayout] = useState<PageLayout>("itemized");

  const set = useCallback((patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params.toString());
    for (const [k, v] of Object.entries(patch)) {
      if (v === null) next.delete(k);
      else next.set(k, v);
    }
    router.replace(`/evidence?${next.toString()}`, { scroll: false });
  }, [params, router]);

  const { data: index, error: indexErr, mutate: reloadIndex } = useApi<{ counts: Record<string, number>; documents: DocumentRow[] }>("/api/documents");
  const { data: doc, error: docErr, mutate: reloadDoc } = useApi<DocumentDetail>(docId ? `/api/documents/${docId}` : null);
  const { data: value, mutate: reloadValue } = useApi<ValueDetail>(evId ? `/api/values/${evId}` : null);

  const docs = useMemo(() => (index?.documents ?? []).filter((d) => {
    const ql = q.toLowerCase();
    const match = !ql || [d.id, d.title, d.issuer, d.document_type].some((s) => s.toLowerCase().includes(ql));
    return match && (filter === "all" || d.statuses.some((s) => s.code === filter));
  }), [index, q, filter]);

  const page = doc?.pages.find((p) => p.page === pageNo) ?? doc?.pages[0];
  const dupPages = new Set(doc?.relations.duplicate_pages.flatMap((d) => d.pages) ?? []);

  // Keyboard: ←/→ pages, j/k values on the page.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (!doc || !page || ["INPUT", "TEXTAREA", "SELECT"].includes(t.tagName) || e.metaKey || e.ctrlKey) return;
      if (e.key === "ArrowRight" && page.page < doc.page_count) set({ page: String(page.page + 1), ev: null });
      if (e.key === "ArrowLeft" && page.page > 1) set({ page: String(page.page - 1), ev: null });
      if (e.key === "j" || e.key === "k") {
        const vals = page.values;
        if (!vals.length) return;
        const i = vals.findIndex((v) => v.id === evId);
        const next = e.key === "j" ? Math.min(vals.length - 1, i + 1) : Math.max(0, i - 1);
        set({ ev: vals[next].id });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [doc, page, evId, set]);

  const onVerified = () => { reloadDoc(); reloadValue(); reloadIndex(); };

  return (
    <div className="-mx-4 -my-5 grid min-h-[calc(100vh-57px)] grid-cols-1 md:-mx-6 lg:grid-cols-[300px_1fr] xl:grid-cols-[300px_1fr_380px]">
      {/* Document index */}
      <aside className="border-r bg-white lg:sticky lg:top-[57px] lg:h-[calc(100vh-57px)] lg:overflow-y-auto">
        <div className="sticky top-0 z-10 space-y-2 border-b bg-white p-3">
          <div className="flex items-baseline justify-between">
            <h1 className="text-[15px] font-semibold">Evidence</h1>
            <span className="text-[11px] text-muted-foreground">{index?.documents.length ?? "…"} documents</span>
          </div>
          <div className="relative">
            <Search className="absolute top-1/2 left-2 size-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search id, title, issuer…" className="h-8 pl-7 text-xs" />
          </div>
          <div className="flex flex-wrap gap-1">
            {FILTERS.map((f) => {
              const n = f === "all" ? index?.documents.length : index?.counts[f] ?? 0;
              if (f !== "all" && !n) return null;
              return (
                <button key={f} onClick={() => setFilter(f)}
                  className={cn("rounded px-1.5 py-0.5 text-[11px]", filter === f ? "bg-slate-800 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200")}>
                  {f === "all" ? "All" : humanize(f)} <span className="opacity-60">{n}</span>
                </button>
              );
            })}
          </div>
        </div>
        <ErrorState error={indexErr} />
        {!index ? <div className="p-3"><Loading rows={10} /></div> : (
          <ul className="divide-y">
            {docs.map((d) => (
              <li key={d.id}>
                <button onClick={() => set({ doc: d.id, page: "1", ev: null })}
                  className={cn("w-full px-3 py-2 text-left hover:bg-slate-50", d.id === docId && "bg-primary/6 ring-1 ring-inset ring-primary/30")}>
                  <div className="flex items-start gap-2">
                    <code className="mt-0.5 text-[11px] text-slate-500">{d.id}</code>
                    <div className="min-w-0 flex-1">
                      <div className="line-clamp-2 text-[12.5px] leading-snug font-medium text-slate-800">{d.title}</div>
                      <div className="mt-1 flex flex-wrap items-center gap-1">
                        <StatusChips statuses={d.statuses} compact />
                        {d.verified_value_count > 0 && <Chip tone="good"><BadgeCheck className="size-3" />{d.verified_value_count}</Chip>}
                        <span className="text-[10.5px] text-muted-foreground">{d.page_count}p · {d.value_count} values</span>
                      </div>
                    </div>
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </aside>

      {/* Document + page */}
      <section className="min-w-0 bg-slate-100/60 px-4 py-4 md:px-6">
        {!docId && <EmptyState />}
        <ErrorState error={docErr} />
        {docId && !doc && !docErr && <Loading rows={8} />}
        {doc && page && (
          <div className="space-y-3">
            <div className="rounded-lg border bg-white px-4 py-3 shadow-xs">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                    <code>{doc.id}</code><span>{humanize(doc.document_type)}</span><span>·</span><span>{doc.issuer}</span>
                  </div>
                  <h2 className="text-[15px] font-semibold">{doc.title}</h2>
                  <div className="text-[11px] text-muted-foreground">
                    {doc.file_name} · received {date(doc.received_at)} from {doc.uploaded_by} · belongs to {doc.belongs_to} · extraction {doc.extraction.status}
                    {doc.used_in_versions.length > 0 && ` · used in ${doc.used_in_versions.join(", ")}`}
                  </div>
                </div>
                <div className="flex flex-col items-end gap-1.5">
                  <div className="flex flex-wrap justify-end gap-1"><StatusChips statuses={doc.statuses} /></div>
                  <Link href={proveHref(doc.id, "down")} className="inline-flex items-center gap-1 text-xs text-sky-700 hover:underline">
                    <ArrowLeftRight className="size-3.5" /> Trace this document to the final tax
                  </Link>
                </div>
              </div>
              <ul className="mt-2 space-y-0.5 text-xs text-slate-600">
                {doc.statuses.filter((s) => s.code !== "used").map((s, i) => (
                  <li key={i} className="flex gap-1.5"><AlertTriangle className={cn("mt-0.5 size-3 shrink-0", s.code === "conflict" || s.code === "duplicate" ? "text-rose-500" : "text-amber-500")} />{s.detail}</li>
                ))}
                {doc.relations.duplicates.map((r, i) => {
                  const other = r.duplicate_of ?? r.duplicated_by;
                  return <li key={`d${i}`} className="flex gap-1.5"><Copy className="mt-0.5 size-3 text-slate-400" />
                    {r.duplicate_of ? "Second copy of " : "Has a second copy: "}
                    <button className="text-sky-700 hover:underline" onClick={() => set({ doc: other!, page: "1", ev: null })}>{other}</button></li>;
                })}
                {(doc.relations.corrections.corrected_by || doc.relations.corrections.corrects) && (
                  <li className="flex gap-1.5"><FileText className="mt-0.5 size-3 text-slate-400" />
                    {doc.relations.corrections.corrected_by ? "Corrected version: " : "Corrects: "}
                    <button className="text-sky-700 hover:underline" onClick={() => set({ doc: (doc.relations.corrections.corrected_by ?? doc.relations.corrections.corrects)!, page: "1", ev: null })}>
                      {doc.relations.corrections.corrected_by ?? doc.relations.corrections.corrects}
                    </button></li>
                )}
              </ul>
            </div>

            {/* Page navigation */}
            <div className="flex flex-wrap items-center gap-2">
              <button disabled={page.page <= 1} onClick={() => set({ page: String(page.page - 1), ev: null })}
                className="rounded-md border bg-white p-1 disabled:opacity-40" aria-label="Previous page"><ChevronLeft className="size-4" /></button>
              <div className="flex max-w-full flex-1 gap-1 overflow-x-auto">
                {doc.pages.map((p) => (
                  <button key={p.page} onClick={() => set({ page: String(p.page), ev: null })}
                    title={!p.extracted ? "Not extracted" : dupPages.has(p.page) ? "Possible duplicate page" : undefined}
                    className={cn("min-w-8 rounded-md border px-2 py-1 text-xs",
                      p.page === page.page ? "border-primary bg-primary text-primary-foreground" : "bg-white hover:bg-slate-50",
                      !p.extracted && p.page !== page.page && "border-dashed text-slate-400",
                      dupPages.has(p.page) && p.page !== page.page && "border-rose-300 text-rose-700")}>
                    {p.page}{dupPages.has(p.page) && " ⧉"}
                  </button>
                ))}
              </div>
              <button disabled={page.page >= doc.page_count} onClick={() => set({ page: String(page.page + 1), ev: null })}
                className="rounded-md border bg-white p-1 disabled:opacity-40" aria-label="Next page"><ChevronRight className="size-4" /></button>
              <div className="ml-auto flex items-center gap-3 text-[11px] text-muted-foreground">
                <div className="inline-flex rounded-md border bg-white p-0.5">
                  {(["itemized", "continuous"] as const).map((l) => (
                    <button key={l} onClick={() => setLayout(l)}
                      className={cn("rounded px-1.5 py-0.5", layout === l && "bg-slate-800 text-white")}>
                      {l === "itemized" ? "One item per line" : "As one block"}
                    </button>
                  ))}
                </div>
                <label className="flex items-center gap-1.5">
                  <Switch checked={showBox} onCheckedChange={setShowBox} /> location box
                </label>
              </div>
            </div>

            {evId && page.values.some((v) => v.id === evId && !v.span) && (
              <div className="mx-auto max-w-[680px] rounded-md border border-amber-200 bg-amber-50 px-3 py-1.5 text-xs text-amber-900">
                {evId} could not be located in this page&apos;s printed text
                {page.values.find((v) => v.id === evId)?.flags.length ? " — see the evidence checks: the reading does not match what is printed." : " (for example a checkbox printed as a word)."}
              </div>
            )}
            <PageSurface
              text={page.printed_content}
              values={page.values}
              selectedId={evId}
              onSelect={(id) => set({ ev: id })}
              showBox={showBox}
              layout={layout}
              title={`${doc.id} · ${doc.title}`}
              pageLabel={`Page ${page.page} of ${doc.page_count}`}
            />
            <p className="text-center text-[10.5px] text-muted-foreground">
              Simulated page: the issuer&apos;s printed content, verbatim. Highlights and the location box mark where each value is printed;
              with a real page image the box would come from the value&apos;s recorded position instead. Keys: ←/→ pages · j/k values.
            </p>

            {/* Page values */}
            <div className="rounded-lg border bg-white shadow-xs">
              <div className="flex items-center justify-between border-b px-4 py-2 text-[13px] font-semibold">
                Extracted on this page <span className="text-[11px] font-normal text-muted-foreground">{page.values.length} values</span>
              </div>
              {page.values.length === 0 ? (
                <div className="px-4 py-3 text-xs text-muted-foreground">{doc.extraction.reason ?? "No values were extracted from this page."}</div>
              ) : (
                <ul className="max-h-80 divide-y overflow-y-auto">
                  {page.values.map((v) => (
                    <li key={v.id}>
                      <button onClick={() => set({ ev: v.id })}
                        className={cn("grid w-full grid-cols-[72px_1fr_auto_auto] items-center gap-2 px-4 py-1.5 text-left text-xs hover:bg-slate-50", v.id === evId && "bg-sky-50")}>
                        <code className="text-[10.5px] text-slate-500">{v.id}</code>
                        <span className="truncate">{v.label}</span>
                        <span className="flex items-center gap-1">
                          {v.flags.map((f) => <Chip key={f.code} tone={f.severity === "conflict" ? "bad" : "warn"}>{humanize(f.code.toLowerCase())}</Chip>)}
                          {(v.verifications?.length ?? 0) > 0 && <BadgeCheck className="size-3.5 text-emerald-600" />}
                          {v.line_count_current > 0 && <Chip tone="info">→ {v.line_count_current} line{v.line_count_current > 1 ? "s" : ""}</Chip>}
                        </span>
                        <span className="num text-right font-medium">{fmtValue(v)}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {/* Document reverse trace */}
            <div className="rounded-lg border bg-white shadow-xs">
              <div className="border-b px-4 py-2 text-[13px] font-semibold">Where this document landed ({doc.where_used.version})</div>
              <div className="px-4 py-3 text-xs">
                {doc.why_not_used && <p className="mb-2 rounded bg-amber-50 px-2 py-1.5 text-amber-900">Not used: {doc.why_not_used}</p>}
                {doc.where_used.lines.length === 0 ? (
                  <p className="text-muted-foreground">No {doc.where_used.version} return line cites values from this document.</p>
                ) : (
                  <ul className="divide-y rounded border">
                    {doc.where_used.lines.map((l) => (
                      <li key={l.key}>
                        <Link href={`/return?line=${encodeURIComponent(l.key)}&v=${doc.where_used.version}`} className="flex items-center gap-2 px-2.5 py-1.5 hover:bg-slate-50">
                          <ArrowUpRight className="size-3.5 text-slate-400" />
                          <code className="text-sky-700">{l.key}</code>
                          <span className="flex-1 truncate text-slate-600">{l.label}</span>
                          <span className="text-[10.5px] text-muted-foreground">via {l.via.length} value{l.via.length > 1 ? "s" : ""}</span>
                          <Money value={l.value} />
                        </Link>
                      </li>
                    ))}
                  </ul>
                )}
                {doc.where_used.references.length > 0 && (
                  <p className="mt-2 text-muted-foreground">Also referenced by: {doc.where_used.references.map((r) => `${r.id} (${humanize(r.label)})`).join(", ")}</p>
                )}
              </div>
            </div>
          </div>
        )}
      </section>

      {/* Selected value */}
      <aside className="border-l bg-white xl:sticky xl:top-[57px] xl:h-[calc(100vh-57px)] xl:overflow-y-auto">
        {!evId ? (
          <div className="p-4 text-xs text-muted-foreground">
            {doc ? "Select a highlighted value on the page (or press j) to see its reading, flags, verification and where it was used." : ""}
          </div>
        ) : !value ? <div className="p-4"><Loading rows={6} /></div> : (
          <ValuePanel v={value} onVerified={onVerified} />
        )}
      </aside>
    </div>
  );
}

function ValuePanel({ v, onVerified }: { v: ValueDetail; onVerified: () => void }) {
  const byVersion = v.where_used.lines.reduce<Record<string, ValueDetail["where_used"]["lines"]>>((acc, l) => {
    (acc[l.version] ??= []).push(l);
    return acc;
  }, {});
  return (
    <div className="space-y-4 p-4 text-[13px]">
      <div>
        <div className="flex flex-wrap items-center gap-1.5">
          <code className="rounded bg-slate-100 px-1.5 py-0.5 text-xs">{v.id}</code>
          <Chip>extracted value</Chip>
          <Chip tone={v.confidence >= 0.9 ? "good" : v.confidence >= 0.7 ? "warn" : "bad"}>conf {(v.confidence * 100).toFixed(0)}%</Chip>
          {v.masked && <Chip tone="warn">masked</Chip>}
        </div>
        <div className="mt-2 text-slate-600">{v.label}</div>
        <div className="num mt-0.5 text-2xl font-semibold tracking-tight">{fmtValue(v)}</div>
        <dl className="mt-2 grid grid-cols-[92px_1fr] gap-y-0.5 text-xs">
          <dt className="text-muted-foreground">Read as</dt><dd className="font-mono">{v.text_as_read ? `“${v.text_as_read}”` : <i className="text-rose-700">nothing read</i>}</dd>
          <dt className="text-muted-foreground">Field</dt><dd className="font-mono">{v.field}</dd>
          <dt className="text-muted-foreground">Type</dt><dd>{v.value_type}</dd>
          <dt className="text-muted-foreground">Source</dt><dd>{v.document_id} · page {v.page} — {v.document_title}</dd>
          <dt className="text-muted-foreground">In text</dt><dd>{v.span ? `characters ${v.span[0]}–${v.span[1]}` : <span className="text-amber-700">not located in printed text</span>}</dd>
          <dt className="text-muted-foreground">Recorded position</dt>
          <dd className="text-[11px]"><span className="font-mono">x {v.position.x0.toFixed(2)}–{v.position.x1.toFixed(2)}, y {v.position.y0.toFixed(2)}–{v.position.y1.toFixed(2)}</span>
            <span className="block text-muted-foreground">synthetic in this packet; locates the field on a real page image</span></dd>
        </dl>
      </div>

      {v.flags.length > 0 && (
        <section>
          <H>TaxProof evidence checks</H>
          <div className="space-y-1.5">
            {v.flags.map((f) => (
              <div key={f.code} className={cn("rounded-md border px-2.5 py-1.5 text-xs", f.severity === "conflict" ? "border-rose-200 bg-rose-50 text-rose-900" : "border-amber-200 bg-amber-50 text-amber-900")}>
                <div className="font-medium">{humanize(f.code.toLowerCase())} · {f.severity}</div>
                <div>{f.message}</div>
              </div>
            ))}
          </div>
          <p className="mt-1 text-[10.5px] text-muted-foreground">Deterministic comparison of the reading against the printed page and the organizer — independent of extraction confidence.</p>
        </section>
      )}

      <div className="flex flex-wrap gap-1.5">
        <Link href={proveHref(v.id, "down")} className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs hover:bg-slate-50"><ArrowLeftRight className="size-3.5" />Where it goes</Link>
        <Link href={proveHref(v.id, "impact")} className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs hover:bg-slate-50"><Radar className="size-3.5" />Impact radius</Link>
      </div>

      <section>
        <H>Where was this used?</H>
        {v.where_used.lines.length === 0 && v.where_used.prior_year_lines.length === 0 && v.where_used.diagnostics.length === 0 ? (
          <p className="text-xs text-muted-foreground">No return line, prior-year line or engine diagnostic cites this value.</p>
        ) : (
          <div className="space-y-2 text-xs">
            {Object.entries(byVersion).map(([ver, lines]) => (
              <div key={ver}>
                <div className="mb-0.5 text-[11px] font-medium text-muted-foreground">Return {ver}</div>
                <ul className="divide-y rounded border">
                  {lines.map((l) => (
                    <li key={l.key}>
                      <Link href={`/return?line=${encodeURIComponent(l.key)}&v=${ver}`} className="flex items-center gap-2 px-2 py-1 hover:bg-slate-50">
                        <code className="text-sky-700">{l.key}</code>
                        <span className="flex-1 truncate text-slate-600">{l.label}</span>
                        <Money value={l.value} />
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
            {v.where_used.prior_year_lines.map((l) => (
              <div key={l.key} className="flex justify-between rounded border px-2 py-1"><span>2024 <code>{l.key}</code> {l.label}</span><Money value={l.value} /></div>
            ))}
            {v.where_used.diagnostics.map((d, i) => (
              <div key={i} className="rounded border border-violet-200 bg-violet-50/50 px-2 py-1">
                <Chip tone="engine">ENGINE DIAGNOSTIC</Chip> <code>{d.code}</code> ({d.version}) — {d.message}
              </div>
            ))}
          </div>
        )}
      </section>

      <section>
        <H>Verification</H>
        <VerificationPanel targetRef={v.id} flags={v.flags} onChange={onVerified} />
      </section>
    </div>
  );
}

function EmptyState() {
  return (
    <div className="mx-auto mt-16 max-w-md text-center text-sm text-slate-600">
      <FileText className="mx-auto mb-2 size-8 text-slate-300" />
      <p className="font-medium">Pick a document to inspect its pages.</p>
      <p className="mt-1 text-xs text-muted-foreground">
        Every extracted value is checked against the printed page. Red marks a reading that disagrees with what is printed,
        amber one that needs a human look, green one already verified.
      </p>
    </div>
  );
}

function H({ children }: { children: React.ReactNode }) {
  return <h3 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{children}</h3>;
}
