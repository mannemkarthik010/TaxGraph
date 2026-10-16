"use client";

import Link from "next/link";
import { Home, MapPin } from "lucide-react";
import { date } from "@/lib/format";
import type { Residency, StateAllocation } from "@/lib/schedule-types";
import { cn } from "@/lib/utils";
import { Panel } from "../primitives";
import { Amt, ChecksPanel, LineRef } from "./common";

const STATE_TONE: Record<string, string> = { CA: "bg-amber-200/80 text-amber-950", TX: "bg-sky-200/80 text-sky-950" };

/** The move from California to Texas laid out on the calendar, with what happened where. */
export function ResidencyTimeline({ data }: { data: Residency }) {
  const start = Date.UTC(data.year, 0, 1);
  const pos = (iso: string) => ((Date.parse(`${iso}T00:00:00Z`) - start) / 86400000 / data.days_in_year) * 100;
  const months = Array.from({ length: 12 }, (_, i) => new Date(Date.UTC(data.year, i, 1)).toLocaleString("en-US", { month: "short", timeZone: "UTC" }));
  const dated = data.events.filter((e) => e.date);
  return (
    <Panel title={<span className="flex items-center gap-1.5"><MapPin className="size-4" />Residency {data.year}: California → Texas</span>}>
      <div className="relative">
        <div className="flex h-9 overflow-hidden rounded-md text-xs font-medium">
          {data.periods.map((p) => (
            <div key={p.state} style={{ width: `${(p.days / data.days_in_year) * 100}%` }}
              className={cn("flex items-center justify-center", STATE_TONE[p.state] ?? "bg-slate-200")}>
              {p.state} resident · {p.days} days · {date(p.from)} – {date(p.to)}
            </div>
          ))}
        </div>
        <div className="mt-1 flex text-[10px] text-muted-foreground">{months.map((m) => <div key={m} className="flex-1">{m}</div>)}</div>
        <div className="relative mt-2 h-24">
          {dated.map((e, i) => (
            <div key={i} className="group absolute top-0" style={{ left: `${pos(e.date!)}%` }}>
              <div className={cn("h-3 w-0.5", e.kind === "address" ? "bg-slate-800" : e.kind.startsWith("closing") ? "bg-indigo-600" : "bg-slate-400")} />
              <div className={cn("size-2 -translate-x-[3px] rounded-full", e.kind === "address" ? "bg-slate-800" : e.kind.startsWith("closing") ? "bg-indigo-600" : "bg-slate-400")}
                style={{ marginTop: `${(i % 5) * 14}px` }} title={`${e.date} · ${e.label}`} />
            </div>
          ))}
        </div>
      </div>
      <ul className="mt-1 grid gap-x-6 gap-y-1 text-xs sm:grid-cols-2">
        {data.events.map((e, i) => (
          <li key={i} className="flex gap-2">
            <span className="num w-20 shrink-0 text-muted-foreground">{e.date ? date(e.date) : "organizer"}</span>
            {e.state && <span className={cn("rounded px-1 text-[10px] font-semibold", STATE_TONE[e.state])}>{e.state}</span>}
            {e.kind === "address" && <Home className="mt-0.5 size-3 shrink-0" />}
            <span className="text-slate-700">{e.document_id ? <Link href={`/evidence?doc=${e.document_id}&page=1&ev=${e.ref}`} className="hover:underline">{e.label}</Link> : e.label}</span>
          </li>
        ))}
      </ul>
      <div className="mt-3"><ChecksPanel checks={data.checks} /></div>
    </Panel>
  );
}

export function StateAllocationView({ data }: { data: StateAllocation }) {
  return (
    <div className="space-y-4">
      <ResidencyTimeline data={data.residency} />
      <Panel dense title="Income split — Schedule CA (540NR)">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[860px] text-[12.5px]">
            <thead className="text-left text-[10.5px] uppercase tracking-wide text-muted-foreground">
              <tr className="border-b"><th className="px-4 py-1.5 font-medium">Line</th>
                <th className="px-2 text-right font-medium">A Federal</th><th className="px-2 text-right font-medium">B Subtract</th><th className="px-2 text-right font-medium">C Add</th>
                <th className="px-2 text-right font-medium">D CA law</th><th className="px-2 text-right font-medium">E California</th><th className="w-48 px-4 font-medium">California share</th></tr>
            </thead>
            <tbody>
              {data.rows.map((r) => (
                <tr key={r.line} className="border-b last:border-0 align-top">
                  <td className="px-4 py-1.5"><div className="font-medium">{r.line}. {r.label}</div>{r.notes.map((n, i) => <div key={i} className="text-[11px] text-muted-foreground">{n}</div>)}</td>
                  {(["A", "B", "C", "D", "E"] as const).map((c) => (
                    <td key={c} className={cn("px-2 py-1.5 text-right", c === "E" && "font-medium")}>
                      {r.keys[c] ? <Amt v={r.columns[c]} /> : <span className="text-slate-300">—</span>}
                      {r.keys[c] && <div><LineRef k={r.keys[c]} className="text-[9.5px]" /></div>}
                    </td>
                  ))}
                  <td className="px-4 py-1.5">
                    {r.california_share != null && (
                      <div className="flex items-center gap-2">
                        <div className="h-2 flex-1 rounded bg-sky-100"><div className="h-2 rounded bg-amber-500" style={{ width: `${Math.min(100, Math.max(0, r.california_share * 100))}%` }} /></div>
                        <span className="num w-10 text-right text-[11px]">{(r.california_share * 100).toFixed(0)}%</span>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel dense title="Form 540NR computation">
          <ul className="divide-y text-[12.5px]">
            {data.form540nr.map((l) => (
              <li key={l.key} className="flex justify-between gap-2 px-4 py-1"><span><LineRef k={l.key} /> {l.label}</span>
                <span className="num"><Amt v={l.value} /></span></li>
            ))}
          </ul>
        </Panel>
        <ChecksPanel checks={data.checks} />
      </div>
    </div>
  );
}
