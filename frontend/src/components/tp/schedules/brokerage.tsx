"use client";

import { useState } from "react";
import { AlertTriangle, ChevronDown, ChevronRight, Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import { useApi } from "@/lib/api";
import type { Brokerage, Lot } from "@/lib/schedule-types";
import { cn } from "@/lib/utils";
import { Chip, Loading, Panel } from "../primitives";
import { Amt, ChecksPanel, EvRef, LineRef, useLineDrawer } from "./common";

/** Hundreds of sales: summary by source and Form 8949 box first; lots only when asked for. */
export function BrokerageView({ data }: { data: Brokerage }) {
  const [open, setOpen] = useState<{ box?: string; document_id?: string | null; attention?: boolean } | null>(null);
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-4">
        <Box label="Sales (lots)" value={data.lot_count.toLocaleString()} />
        <Box label="Short-term gain" value={<Amt v={data.by_term.short} />} />
        <Box label="Long-term gain" value={<Amt v={data.by_term.long} />} />
        <button onClick={() => setOpen({ attention: true })} className="rounded-lg border bg-card px-4 py-3 text-left shadow-xs hover:border-amber-300">
          <div className="text-[11px] text-muted-foreground">Need attention</div>
          <div className="num text-xl font-semibold text-amber-700">{data.attention.lots} lots</div>
          <div className="text-[10.5px] text-muted-foreground">{data.attention.basis_missing} missing basis · {data.attention.flagged} with evidence flags</div>
        </button>
      </div>
      <Panel dense title="By source and Form 8949 box">
        <table className="w-full text-[12.5px]">
          <thead className="text-left text-[10.5px] uppercase tracking-wide text-muted-foreground">
            <tr className="border-b"><th className="px-4 py-1.5 font-medium">Source</th><th className="font-medium">Box</th><th className="px-2 text-right font-medium">Lots</th>
              <th className="px-2 text-right font-medium">Proceeds</th><th className="px-2 text-right font-medium">Basis</th><th className="px-2 text-right font-medium">Gain / (loss)</th>
              <th className="px-2 font-medium">Largest</th><th className="px-4" /></tr>
          </thead>
          <tbody>
            {data.groups.map((g) => {
              const isOpen = open?.box === g.box && open?.document_id === g.document_id && !open?.attention;
              return (
                <tr key={`${g.document_id}-${g.box}`} className={cn("border-b last:border-0 hover:bg-slate-50/70", isOpen && "bg-sky-50/50")}>
                  <td className="px-4 py-1.5">
                    <button onClick={() => setOpen(isOpen ? null : { box: g.box, document_id: g.document_id })} className="flex items-center gap-1 text-left">
                      {isOpen ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
                      <span className="font-medium">{g.broker}</span>
                      {g.document_id && <span className="font-mono text-[10.5px] text-muted-foreground">{g.document_id}</span>}
                    </button>
                  </td>
                  <td><Chip>{g.box} · {g.term}</Chip></td>
                  <td className="px-2 text-right num">{g.lots}</td>
                  <td className="px-2 text-right"><Amt v={g.proceeds} /></td>
                  <td className="px-2 text-right"><Amt v={g.basis} /></td>
                  <td className="px-2 text-right font-medium"><Amt v={g.gain} /></td>
                  <td className="max-w-[220px] truncate px-2 text-[11px] text-muted-foreground" title={g.largest_gain?.description}>{g.largest_gain && <>{g.largest_gain.description} <Amt v={g.largest_gain.gain} /></>}</td>
                  <td className="px-4 text-right">
                    {g.basis_missing > 0 && <Chip tone="warn">{g.basis_missing} no basis</Chip>}
                    {g.flagged > 0 && <Chip tone="warn" className="ml-1">{g.flagged} flagged</Chip>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Panel>
      {/* Keyed by the selection: switching groups starts on page 1 with an empty search. */}
      {open && <LotsTable key={JSON.stringify(open)} filter={open} onClose={() => setOpen(null)} />}
      <ChecksPanel checks={data.checks} />
    </div>
  );
}

function LotsTable({ filter, onClose }: { filter: { box?: string; document_id?: string | null; attention?: boolean }; onClose: () => void }) {
  const { version } = useLineDrawer();
  const [q, setQ] = useState("");
  const [offset, setOffset] = useState(0);
  const p = new URLSearchParams({ version, offset: String(offset), limit: "25", sort: "gain" });
  if (filter.box) p.set("box", filter.box);
  if (filter.document_id) p.set("document_id", filter.document_id);
  if (filter.attention) p.set("attention", "true");
  if (q) p.set("q", q);
  const { data } = useApi<{ total: number; items: Lot[] }>(`/api/workpaper/schedules/brokerage/lots?${p}`);
  return (
    <Panel dense title={<span>{filter.attention ? "Lots needing attention" : `Lots — box ${filter.box}${filter.document_id ? ` · ${filter.document_id}` : ""}`}
      <span className="ml-2 font-normal text-muted-foreground">{data ? `${data.total} · largest gains first` : ""}</span></span>}
      actions={<div className="flex items-center gap-2">
        <div className="relative w-48"><Search className="absolute top-1/2 left-2 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input value={q} onChange={(e) => { setQ(e.target.value); setOffset(0); }} placeholder="Filter lots…" className="h-7 pl-7 text-xs" /></div>
        <button onClick={onClose} className="text-xs text-muted-foreground hover:text-slate-900">close</button>
      </div>}>
      {!data ? <div className="p-4"><Loading /></div> : (
        <>
          <table className="w-full text-[12px]">
            <thead className="text-left text-[10.5px] uppercase tracking-wide text-muted-foreground">
              <tr className="border-b"><th className="px-4 py-1.5 font-medium">Lot</th><th className="font-medium">Description</th><th className="font-medium">Acquired</th><th className="font-medium">Sold</th>
                <th className="px-2 text-right font-medium">Proceeds</th><th className="px-2 text-right font-medium">Basis</th><th className="px-2 text-right font-medium">Adj.</th><th className="px-2 text-right font-medium">Gain</th><th className="px-4">Evidence</th></tr>
            </thead>
            <tbody>
              {data.items.map((l) => (
                <tr key={l.key} className="border-b last:border-0 align-top">
                  <td className="px-4 py-1"><LineRef k={l.key} /></td>
                  <td className="max-w-[220px] truncate py-1" title={l.description}>{l.description}</td>
                  <td className="py-1">{l.acquired ?? <span className="text-amber-700">—</span>}</td>
                  <td className="py-1">{l.sold ?? "—"}</td>
                  <td className="px-2 py-1 text-right"><Amt v={l.proceeds} /></td>
                  <td className="px-2 py-1 text-right">{l.basis_missing ? <Chip tone="warn">missing</Chip> : <Amt v={l.basis} />}</td>
                  <td className="px-2 py-1 text-right text-muted-foreground"><Amt v={l.adjustment || null} /></td>
                  <td className="px-2 py-1 text-right font-medium"><Amt v={l.gain} /></td>
                  <td className="px-4 py-1">
                    {l.computed_line ? <span className="text-[11px] text-muted-foreground">computed line</span> : <span className="font-mono text-[10.5px] text-muted-foreground">{l.document_id}</span>}
                    {l.flags.map((f, i) => (
                      <div key={i} className="flex items-start gap-1 text-[10.5px] text-amber-800"><AlertTriangle className="mt-0.5 size-3" /><EvRef id={f.ref} /> {f.message}</div>
                    ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {data.total > 25 && (
            <div className="flex items-center justify-between border-t px-4 py-2 text-xs text-muted-foreground">
              <span>{offset + 1}–{Math.min(offset + 25, data.total)} of {data.total}</span>
              <div className="flex gap-2">
                <button disabled={offset === 0} onClick={() => setOffset(offset - 25)} className="rounded border px-2 py-0.5 disabled:opacity-40">Prev</button>
                <button disabled={offset + 25 >= data.total} onClick={() => setOffset(offset + 25)} className="rounded border px-2 py-0.5 disabled:opacity-40">Next</button>
              </div>
            </div>
          )}
        </>
      )}
    </Panel>
  );
}

function Box({ label, value }: { label: string; value: React.ReactNode }) {
  return <div className="rounded-lg border bg-card px-4 py-3 shadow-xs"><div className="text-[11px] text-muted-foreground">{label}</div><div className="num text-xl font-semibold">{value}</div></div>;
}
