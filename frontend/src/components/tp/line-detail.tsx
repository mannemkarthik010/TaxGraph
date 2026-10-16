"use client";

import Link from "next/link";
import { ArrowDownRight, ArrowLeftRight, ArrowUpRight, FileText, Radar, ShieldCheck } from "lucide-react";
import { proveHref } from "@/lib/links";
import { useApi } from "@/lib/api";
import { money, pct } from "@/lib/format";
import type { EvidenceFlag, LineDetail as LD } from "@/lib/types";
import { Chip, ErrorState, Loading, Money } from "./primitives";
import { NotesThread } from "./notes-thread";
import { VerificationPanel } from "./verification-panel";
import { LineAdjustment } from "./adjustments/adjustments";
import type { VersionRow } from "@/lib/types";

const KIND_LABEL: Record<string, string> = {
  extracted_value: "Extracted value",
  engine_parameter: "Engine parameter",
  prior_year_value: "Prior year",
  asset: "Asset record",
  client_answer: "Client answer",
  household_member: "Household",
  fx_rate: "FX rate",
  agency_record: "Agency record",
  return_line: "Return line",
};

function confTone(c: number) {
  return c >= 0.9 ? "good" : c >= 0.7 ? "warn" : "bad";
}

export function LineDetail({ version, lineKey, onOpenLine }: { version: string; lineKey: string; onOpenLine: (k: string) => void }) {
  const { data: d, error } = useApi<LD>(`/api/return/lines/${encodeURIComponent(lineKey)}?version=${version}`);
  const { data: versions } = useApi<{ current: string; versions: VersionRow[] }>("/api/return/versions");
  if (error) return <ErrorState error={error} />;
  if (!d) return <Loading rows={6} />;

  return (
    <div className="space-y-5 text-[13px]">
      <div>
        <div className="flex flex-wrap items-center gap-1.5">
          <code className="rounded bg-slate-100 px-1.5 py-0.5 text-[12px]">{d.key}</code>
          <Chip tone="engine">engine result · {d.version}</Chip>
          <Chip>{d.jurisdiction}</Chip>
          {d.variance.flagged && <Chip tone="warn">variance vs 2024</Chip>}
        </div>
        <div className="mt-2 text-slate-600">{d.label}</div>
        <div className="num mt-1 text-3xl font-semibold tracking-tight">{money(d.value)}</div>
        <div className="mt-2 flex flex-wrap gap-1.5">
          <Link href={proveHref(`line:${d.version}:${d.key}`)} className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary/90">
            <ShieldCheck className="size-3.5" /> Prove it
          </Link>
          <Link href={proveHref(`line:${d.version}:${d.key}`, "down")} className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs hover:bg-slate-50">
            <ArrowLeftRight className="size-3.5" /> Where it goes
          </Link>
          <Link href={proveHref(`line:${d.version}:${d.key}`, "impact")} className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs hover:bg-slate-50">
            <Radar className="size-3.5" /> Impact radius
          </Link>
        </div>
        {d.note && <p className="mt-2 rounded-md bg-slate-50 px-2 py-1.5 text-xs text-slate-600">Engine note: {d.note}</p>}
      </div>

      <section>
        <H>How it was built</H>
        <div className="rounded-md border px-3 py-2">
          <div className="text-[11px] text-muted-foreground">Rule <code>{d.rule}</code></div>
          <div className="text-slate-700">{d.rule_description ?? "—"}</div>
        </div>
        {d.inputs.length > 0 && (
          <ul className="mt-2 divide-y rounded-md border">
            {d.inputs.map((i) => (
              <li key={i.key}>
                <button onClick={() => onOpenLine(i.key)} className="flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-slate-50">
                  <ArrowDownRight className="size-3.5 text-slate-400" />
                  <code className="text-[11.5px] text-sky-700">{i.key}</code>
                  <span className="flex-1 truncate text-slate-600">{i.label}</span>
                  <Money value={i.value} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <H>Evidence cited by the engine ({d.sources.length})</H>
        {d.sources.length === 0 ? (
          <div className="text-xs text-muted-foreground">No direct sources — this line is computed from the inputs above.</div>
        ) : (
          <ul className="divide-y rounded-md border">
            {d.sources.map((s) => (
              <li key={s.ref} className="px-3 py-2">
                <div className="flex items-center gap-2">
                  <Chip tone={s.exists ? "neutral" : "bad"}>{KIND_LABEL[s.kind] ?? s.kind}</Chip>
                  <code className="text-[11.5px]">{s.ref}</code>
                  <span className="ml-auto"><Money value={s.value} /></span>
                </div>
                <div className="mt-0.5 text-xs text-slate-600">{s.label}</div>
                {s.document_id && (
                  <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
                    <FileText className="size-3" />
                    <Link className="text-sky-700 hover:underline"
                      href={`/evidence?doc=${s.document_id}&page=${s.page ?? 1}${s.kind === "extracted_value" ? `&ev=${s.ref}` : ""}`}>
                      {s.document_id} · page {s.page}
                    </Link>
                    <span>— {String(s.detail.document_title ?? "")}</span>
                    {typeof s.detail.confidence === "number" && (
                      <Chip tone={confTone(s.detail.confidence)}>conf {(s.detail.confidence * 100).toFixed(0)}%</Chip>
                    )}
                    {s.detail.text_as_read !== undefined && <span>read as “{String(s.detail.text_as_read)}”</span>}
                  </div>
                )}
                {((s.detail.flags as EvidenceFlag[] | undefined) ?? []).map((f) => (
                  <div key={f.code} className={`mt-1 rounded px-1.5 py-0.5 text-[11px] ${f.severity === "conflict" ? "bg-rose-50 text-rose-800" : "bg-amber-50 text-amber-800"}`}>
                    <b className="font-medium">TaxProof check:</b> {f.message}
                  </div>
                ))}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <H>Workpaper value</H>
        <LineAdjustment lineKey={d.key} version={d.version} currentVersion={versions?.current ?? d.version} />
      </section>

      <section>
        <H>Verification of this line</H>
        <VerificationPanel targetRef={`line:${d.version}:${d.key}`} />
      </section>

      {d.used_by.length > 0 && (
        <section>
          <H>Flows into</H>
          <ul className="divide-y rounded-md border">
            {d.used_by.map((u) => (
              <li key={u.key}>
                <button onClick={() => onOpenLine(u.key)} className="flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-slate-50">
                  <ArrowUpRight className="size-3.5 text-slate-400" />
                  <code className="text-[11.5px] text-sky-700">{u.key}</code>
                  <span className="flex-1 truncate text-slate-600">{u.label}</span>
                  <Money value={u.value} />
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section className="grid grid-cols-2 gap-3">
        <div>
          <H>Across versions</H>
          <ul className="space-y-0.5 text-xs">
            {Object.entries(d.values_by_version).map(([v, val]) => (
              <li key={v} className="flex justify-between"><span className="text-muted-foreground">{v}</span><Money value={val} /></li>
            ))}
          </ul>
        </div>
        <div>
          <H>2024 as filed</H>
          {d.prior_year ? (
            <div className="text-xs">
              <div className="flex justify-between"><span className="text-muted-foreground">Prior year</span><Money value={d.prior_year.value} /></div>
              <div className="flex justify-between"><span className="text-muted-foreground">Change</span><span><Money value={d.variance.change} sign /> {d.variance.change != null && pct(d.variance.change_pct)}</span></div>
              <div className="mt-0.5 text-[11px] text-muted-foreground">
                2024 line {d.prior_year.key}{d.prior_year.key !== d.key && " (2024 Form 540, matched by meaning)"}
                {d.prior_year.source && <> · source {d.prior_year.source} (D06)</>}
              </div>
            </div>
          ) : <div className="text-xs text-muted-foreground">No 2024 counterpart.</div>}
        </div>
      </section>

      {d.engine_diagnostics.length > 0 && (
        <section>
          <H>Engine diagnostics</H>
          {d.engine_diagnostics.map((g) => (
            <div key={g.code} className="mb-1.5 rounded-md border border-violet-200 bg-violet-50/50 px-3 py-2 text-xs">
              <div className="flex items-center gap-1.5"><Chip tone="engine">ENGINE DIAGNOSTIC</Chip><code>{g.code}</code><Chip tone={g.severity === "warning" ? "warn" : "info"}>{g.severity}</Chip></div>
              <p className="mt-1 text-slate-700">{g.message}</p>
            </div>
          ))}
        </section>
      )}

      <section>
        <H>Workpaper notes</H>
        <NotesThread targetRef={`line:${d.version}:${d.key}`} />
      </section>
    </div>
  );
}

function H({ children }: { children: React.ReactNode }) {
  return <h3 className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{children}</h3>;
}
