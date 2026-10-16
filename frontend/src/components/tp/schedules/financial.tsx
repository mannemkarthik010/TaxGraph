"use client";

import { useMemo, useState } from "react";
import { ArrowDown, ArrowUp, Minus } from "lucide-react";
import { humanize, pct } from "@/lib/format";
import type { BooksToTax, Carryovers, Depreciation, PriorYear, TaxComputation, TaxRow } from "@/lib/schedule-types";
import { cn } from "@/lib/utils";
import { Chip, Panel } from "../primitives";
import { Amt, ChecksPanel, EvRef, LineRef } from "./common";

// ---- Return summary & tax computation ---------------------------------------------------------------

export function TaxComputationView({ data }: { data: TaxComputation }) {
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <ComputationTable title="Federal — Form 1040" rows={data.federal} />
      <ComputationTable title="California — Form 540NR (part-year)" rows={data.california}
        note="2024 was a full-year resident Form 540; only lines with the same meaning are compared." />
    </div>
  );
}

const MILESTONES = new Set(["9", "11", "15", "24", "33", "37", "17", "19", "32", "35", "64", "78", "97"]);

function ComputationTable({ title, rows, note }: { title: string; rows: TaxRow[]; note?: string }) {
  return (
    <Panel title={title} dense>
      {note && <p className="px-4 pt-2 text-[11px] text-muted-foreground">{note}</p>}
      <table className="w-full text-[12.5px]">
        <thead className="text-left text-[10.5px] uppercase tracking-wide text-muted-foreground">
          <tr className="border-b"><th className="px-4 py-1.5 font-medium">Line</th><th className="font-medium" />
            <th className="px-2 text-right font-medium">2025</th><th className="px-2 text-right font-medium">2024</th><th className="px-4 text-right font-medium">Change</th></tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key} className={cn("border-b last:border-0", MILESTONES.has(r.line) && "bg-slate-50 font-medium")}>
              <td className="px-4 py-1"><LineRef k={r.key} /></td>
              <td className="max-w-[260px] truncate pr-2" title={r.note ?? r.label}>{r.label}</td>
              <td className="px-2 text-right"><Amt v={r.value} /></td>
              <td className="px-2 text-right text-muted-foreground"><Amt v={r.prior_year} /></td>
              <td className="px-4 text-right">{r.change != null && <Amt v={r.change} sign className={r.variance_flag ? "font-medium text-amber-700" : "text-muted-foreground"} />}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </Panel>
  );
}

// ---- Prior-year comparison ----------------------------------------------------------------------------

export function PriorYearView({ data }: { data: PriorYear }) {
  const [onlyFlagged, setOnlyFlagged] = useState(true);
  const rows = onlyFlagged ? data.rows.filter((r) => r.variance_flag) : data.rows;
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <Fact label="Lines with a 2024 counterpart" value={data.rows.length} />
        <Fact label={`Swings over ${data.standard.percent}% and $${data.standard.amount.toLocaleString()}`} value={data.flagged} tone="warn" />
        <Fact label="New lines this year (excluding lots)" value={data.new_this_year.count} />
      </div>
      <Panel dense title={
        <span className="flex items-center gap-2">2025 vs 2024 as filed
          <button onClick={() => setOnlyFlagged(!onlyFlagged)} className="rounded bg-slate-100 px-1.5 py-0.5 text-[11px] font-normal text-slate-600 hover:bg-slate-200">
            {onlyFlagged ? `Showing ${rows.length} flagged — show all ${data.rows.length}` : "Show flagged only"}
          </button>
        </span>}>
        <table className="w-full text-[12.5px]">
          <thead className="text-left text-[10.5px] uppercase tracking-wide text-muted-foreground">
            <tr className="border-b"><th className="px-4 py-1.5 font-medium">Line</th><th className="font-medium" /><th className="font-medium">Area</th>
              <th className="px-2 text-right font-medium">2025</th><th className="px-2 text-right font-medium">2024</th><th className="px-2 text-right font-medium">Change</th><th className="px-4" /></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key} className="border-b last:border-0 hover:bg-slate-50/60">
                <td className="px-4 py-1"><LineRef k={r.key} />{r.prior_year_key !== r.key && <span className="ml-1 font-mono text-[10px] text-muted-foreground">↔ {r.prior_year_key}</span>}</td>
                <td className="max-w-[300px] truncate pr-2">{r.label}</td>
                <td className="text-[11px] text-muted-foreground">{humanize(r.area)}</td>
                <td className="px-2 text-right"><Amt v={r.value} /></td>
                <td className="px-2 text-right text-muted-foreground"><Amt v={r.prior_year} /></td>
                <td className="px-2 text-right"><Amt v={r.change} sign /> <span className="text-[10.5px] text-muted-foreground">{r.change != null ? pct(r.change_pct) : ""}</span></td>
                <td className="px-4 text-right">{r.variance_flag && <Chip tone="warn">explain</Chip>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
      {data.only_prior_year.length > 0 && (
        <Panel title={`On the 2024 return but not on this one (${data.only_prior_year.length})`}>
          <ul className="grid gap-x-6 gap-y-0.5 text-xs sm:grid-cols-2">
            {data.only_prior_year.map((r) => (
              <li key={r.key} className="flex justify-between gap-2"><span><code className="text-[11px]">{r.key}</code> {r.label}</span><Amt v={r.prior_year} /></li>
            ))}
          </ul>
        </Panel>
      )}
    </div>
  );
}

// ---- Books to tax ------------------------------------------------------------------------------------

export function BooksToTaxView({ data }: { data: BooksToTax }) {
  const moving = data.rows.filter((r) => !r.unchanged);
  const same = data.rows.filter((r) => r.unchanged);
  let running = data.start.value;
  return (
    <div className="space-y-4">
      <Panel dense title="From the client's books to Schedule C net profit"
        actions={<span className="text-[11px] text-muted-foreground">books: {data.books_documents.join(", ")}</span>}>
        <table className="w-full text-[12.5px]">
          <thead className="text-left text-[10.5px] uppercase tracking-wide text-muted-foreground">
            <tr className="border-b"><th className="px-4 py-1.5 font-medium">Item</th><th className="px-2 text-right font-medium">Books</th>
              <th className="px-2 text-right font-medium">Schedule C</th><th className="px-2 text-right font-medium">Effect on profit</th><th className="px-4 text-right font-medium">Running</th></tr>
          </thead>
          <tbody>
            <tr className="border-b bg-slate-50 font-medium">
              <td className="px-4 py-1.5">{data.start.label} {data.start.ref && <EvRef id={data.start.ref} />}</td><td /><td /><td />
              <td className="px-4 text-right"><Amt v={data.start.value} /></td>
            </tr>
            {moving.map((r, i) => {
              running += r.effect;
              return (
                <tr key={i} className="border-b align-top">
                  <td className="px-4 py-1.5">
                    <div className="flex items-center gap-1.5">
                      {r.effect > 0 ? <ArrowUp className="size-3 text-emerald-600" /> : <ArrowDown className="size-3 text-rose-600" />}
                      {r.key ? <LineRef k={r.key} /> : <Chip tone="muted">not on Sch C</Chip>}
                      <span>{r.label}</span>
                    </div>
                    <div className="ml-4.5 text-[11px] text-muted-foreground">
                      {r.kind === "removed"
                        ? (r.used_elsewhere?.length ? `Used elsewhere: ${r.used_elsewhere.map((u) => u.key).join(", ")}` : "Books expense not deducted on Schedule C")
                        : r.books_refs.length === 0 ? "No books amount — added by the engine" : null}
                      {r.note && <span> · engine note: {r.note}</span>}
                      {r.books_refs.length > 0 && <span className="ml-1">books {r.books_refs.map((x) => <EvRef key={x} id={x} />)}</span>}
                    </div>
                  </td>
                  <td className="px-2 py-1.5 text-right text-muted-foreground"><Amt v={r.books} /></td>
                  <td className="px-2 py-1.5 text-right"><Amt v={r.tax} /></td>
                  <td className="px-2 py-1.5 text-right font-medium"><Amt v={r.effect} sign /></td>
                  <td className="px-4 py-1.5 text-right text-muted-foreground"><Amt v={running} /></td>
                </tr>
              );
            })}
            <tr className="bg-slate-50 font-semibold">
              <td className="px-4 py-1.5"><LineRef k={data.end.key} /> {data.end.label}</td><td /><td /><td />
              <td className="px-4 text-right"><Amt v={data.end.value} /></td>
            </tr>
          </tbody>
        </table>
        {same.length > 0 && (
          <div className="flex flex-wrap items-center gap-1 border-t px-4 py-2 text-[11px] text-muted-foreground">
            <Minus className="size-3" /> Carried unchanged from books:
            {same.map((r) => <span key={r.key ?? r.label} className="rounded bg-slate-100 px-1"><LineRef k={r.key} /> <Amt v={r.tax} /></span>)}
          </div>
        )}
      </Panel>
      <ChecksPanel checks={data.checks} />
    </div>
  );
}

// ---- Depreciation ------------------------------------------------------------------------------------

export function DepreciationView({ data, activity }: { data: Depreciation; activity?: "Business" | "Rental" }) {
  const assets = activity ? data.assets.filter((a) => a.activity.startsWith(activity)) : data.assets;
  const groups = useMemo(() => {
    const m = new Map<string, typeof assets>();
    for (const a of assets) m.set(a.activity, [...(m.get(a.activity) ?? []), a]);
    return [...m.entries()];
  }, [assets]);
  const checks = data.checks.filter((c) => !activity || c.refs.some((r) => assets.some((a) => r === `asset:${a.asset_id}`)));
  return (
    <div className="space-y-4">
      {groups.map(([act, list]) => (
        <Panel key={act} dense title={act} actions={
          <span className="text-[11px] text-muted-foreground">2025: federal <Amt v={data.by_activity[act]?.federal} /> · CA <Amt v={data.by_activity[act]?.california} /> · AMT <Amt v={data.by_activity[act]?.amt} /></span>}>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[900px] text-[12px]">
              <thead className="text-left text-[10.5px] uppercase tracking-wide text-muted-foreground">
                <tr className="border-b">
                  <th className="px-4 py-1.5 font-medium">Asset</th><th className="font-medium">In service</th><th className="font-medium">Method / life</th>
                  <th className="px-2 text-right font-medium">Cost</th><th className="px-2 text-right font-medium">Prior accum.</th>
                  <th className="px-2 text-right font-medium">2025 federal</th><th className="px-2 text-right font-medium">2025 CA</th><th className="px-2 text-right font-medium">2025 AMT</th>
                  <th className="px-2 text-right font-medium">Accum. end</th><th className="px-4 font-medium">Status</th>
                </tr>
              </thead>
              <tbody>
                {list.map((a) => (
                  <tr key={a.asset_id} className="border-b last:border-0 align-top">
                    <td className="px-4 py-1.5"><div className="font-medium">{a.description}</div><div className="font-mono text-[10.5px] text-muted-foreground">{a.asset_id}</div></td>
                    <td className="py-1.5">{a.placed_in_service}</td>
                    <td className="py-1.5">{a.method}{a.life_years ? ` · ${a.life_years}y` : ""}</td>
                    <td className="px-2 py-1.5 text-right"><Amt v={a.cost} />{a.land ? <div className="text-[10.5px] text-muted-foreground">land <Amt v={a.land} /></div> : null}</td>
                    <td className="px-2 py-1.5 text-right"><Amt v={a.federal.prior_accumulated} /></td>
                    <td className="px-2 py-1.5 text-right font-medium"><Amt v={a.federal.depreciation_2025} /></td>
                    <td className={cn("px-2 py-1.5 text-right", a.federal_vs_california !== 0 && "text-amber-700")}><Amt v={a.california.depreciation_2025} /></td>
                    <td className="px-2 py-1.5 text-right"><Amt v={a.amt.depreciation_2025} /></td>
                    <td className="px-2 py-1.5 text-right"><Amt v={a.federal.accumulated_end} /></td>
                    <td className="px-4 py-1.5">
                      <div className="flex flex-wrap gap-1">
                        {a.new_in_year && <Chip tone="info">new 2025</Chip>}
                        {a.disposed && <Chip tone="warn">disposed {a.disposed}</Chip>}
                        {a.continuity_agrees === true && <Chip tone="good">agrees to prior schedule</Chip>}
                        {a.continuity_agrees === false && <Chip tone="bad">breaks from prior schedule</Chip>}
                        {a.federal_vs_california !== 0 && <Chip tone="warn">fed ≠ CA</Chip>}
                      </div>
                      {a.disposition && (
                        <div className="mt-0.5 text-[10.5px] text-muted-foreground">
                          unrecaptured §1250 <Amt v={a.disposition.unrecaptured_1250_depreciation} /> · §1250 ordinary <Amt v={a.disposition.section_1250_ordinary_recapture} />
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      ))}
      {Object.keys(data.california_basis_differences).length > 0 && !activity && (
        <p className="text-xs text-muted-foreground">California basis differences carried forward: {Object.entries(data.california_basis_differences).map(([k, v]) => `${k} ${v.toLocaleString()}`).join(" · ")}</p>
      )}
      <ChecksPanel checks={checks} />
    </div>
  );
}

// ---- Carryovers --------------------------------------------------------------------------------------

export function CarryoversView({ data }: { data: Carryovers }) {
  const rows = data.rows.filter((r) => r.status !== "none" || r.into_year || r.out_of_year);
  return (
    <div className="space-y-4">
      <Panel dense title="Into 2025 → used → out to 2026" actions={data.source && <span className="text-[11px] text-muted-foreground">into-year source: {data.source}</span>}>
        <table className="w-full text-[12.5px]">
          <thead className="text-left text-[10.5px] uppercase tracking-wide text-muted-foreground">
            <tr className="border-b"><th className="px-4 py-1.5 font-medium">Item</th><th className="px-2 text-right font-medium">From 2024</th>
              <th className="px-2 font-medium">Used by</th><th className="px-2 text-right font-medium">To 2026</th><th className="px-2 text-right font-medium">CA from 2024</th><th className="px-4 font-medium">Status</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.item} className="border-b last:border-0">
                <td className="px-4 py-1.5">{humanize(r.item)}</td>
                <td className="px-2 text-right"><Amt v={r.into_year} /></td>
                <td className="px-2">{r.used_by.length ? r.used_by.map((u) => <span key={u.key} className="mr-2"><LineRef k={u.key} /> <Amt v={u.value} /></span>) : <span className="text-muted-foreground">—</span>}</td>
                <td className="px-2 text-right"><Amt v={r.out_of_year} /></td>
                <td className="px-2 text-right text-muted-foreground"><Amt v={r.california_into} /></td>
                <td className="px-4"><Chip tone={r.status === "used" ? "good" : r.status === "new" ? "info" : r.status === "not used" ? "warn" : "muted"}>{r.status}</Chip></td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
      <Panel title="California carryovers out">
        <pre className="overflow-x-auto text-[11px] text-slate-700">{JSON.stringify(data.california_out, null, 2)}</pre>
        {data.california_note && <p className="mt-2 text-xs text-muted-foreground">{data.california_note}</p>}
      </Panel>
    </div>
  );
}

function Fact({ label, value, tone }: { label: string; value: number; tone?: "warn" }) {
  return (
    <div className="rounded-lg border bg-card px-4 py-3 shadow-xs">
      <div className="text-[11px] text-muted-foreground">{label}</div>
      <div className={cn("num text-2xl font-semibold", tone === "warn" && value > 0 && "text-amber-700")}>{value}</div>
    </div>
  );
}
