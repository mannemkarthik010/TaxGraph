"use client";

import Link from "next/link";
import { humanize } from "@/lib/format";
import type { K1Basis, Rentals } from "@/lib/schedule-types";
import { cn } from "@/lib/utils";
import { Chip, Panel } from "../primitives";
import { Amt, ChecksPanel, EvRef, LineRef } from "./common";

export function RentalsView({ data }: { data: Rentals }) {
  return (
    <div className="space-y-4">
      <div className="grid gap-4 xl:grid-cols-2">
        {data.properties.map((p) => (
          <Panel key={p.letter} dense title={<span>Property {p.letter} · {p.address}</span>}
            actions={<div className="flex gap-1">{p.disposed && <Chip tone="warn">sold {p.disposed}</Chip>}<Chip>{p.days} days rented / personal</Chip></div>}>
            <table className="w-full text-[12.5px]">
              <tbody>
                <tr className="border-b font-medium"><td className="px-4 py-1"><LineRef k={p.rents_key} /> Rents received</td><td className="px-4 text-right"><Amt v={p.rents} /></td><td /></tr>
                {p.expenses.map((e) => (
                  <tr key={e.key} className="border-b"><td className="px-4 py-1"><LineRef k={e.key} /> {e.label}</td><td className="px-4 text-right"><Amt v={-e.value} /></td>
                    <td className="pr-4 text-right text-[11px] text-muted-foreground">{e.prior_year != null && <>2024 <Amt v={e.prior_year} /></>}</td></tr>
                ))}
                <tr className="border-b bg-slate-50 font-medium"><td className="px-4 py-1"><LineRef k={`SchE.21${p.letter}`} /> Income or (loss)</td><td className="px-4 text-right"><Amt v={p.net} /></td>
                  <td className="pr-4 text-right text-[11px] font-normal text-muted-foreground">{p.prior_year_net != null && <>2024 <Amt v={p.prior_year_net} /></>}</td></tr>
                <tr className="font-semibold"><td className="px-4 py-1"><LineRef k={`SchE.22${p.letter}`} /> Deductible after passive limits</td><td className="px-4 text-right"><Amt v={p.allowed} /></td><td /></tr>
              </tbody>
            </table>
            <div className="border-t px-4 py-2 text-[11px] text-muted-foreground">
              Assets: {p.assets.map((a) => <span key={a.asset_id} className="mr-2">{a.asset_id} <Amt v={a.federal} />{a.disposed ? " (disposed)" : ""}</span>)}
            </div>
          </Panel>
        ))}
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Panel dense title="Passive activity loss (Form 8582)">
          <ul className="divide-y text-[12.5px]">
            {data.passive_activity.map((l) => <li key={l.key} className="flex justify-between gap-2 px-4 py-1"><span><LineRef k={l.key} /> {l.label}</span><Amt v={l.value} /></li>)}
          </ul>
        </Panel>
        <Panel dense title="Sale of the Austin condo (Form 4797)">
          <ul className="divide-y text-[12.5px]">
            {data.sale.map((l) => <li key={l.key} className="flex justify-between gap-2 px-4 py-1"><span><LineRef k={l.key} /> {l.label}</span><Amt v={l.value} /></li>)}
          </ul>
        </Panel>
        <Panel title="Suspended passive losses">
          <table className="w-full text-[12.5px]">
            <thead className="text-left text-[10.5px] uppercase text-muted-foreground"><tr><th className="font-medium">Activity</th><th className="text-right font-medium">From 2024</th><th className="text-right font-medium">To 2026</th></tr></thead>
            <tbody>
              {Object.keys(data.suspended_losses.into_year).map((k) => (
                <tr key={k}><td className="py-0.5">{humanize(k.replace("passive_", ""))}</td><td className="text-right"><Amt v={data.suspended_losses.into_year[k]} /></td><td className="text-right"><Amt v={data.suspended_losses.out_of_year[k]} /></td></tr>
              ))}
            </tbody>
          </table>
          <p className="mt-2 text-[11px] text-muted-foreground">Released by the sale of property B and passive income from the K-1s.</p>
        </Panel>
      </div>
      <ChecksPanel checks={data.checks} />
    </div>
  );
}

export function K1BasisView({ data }: { data: K1Basis }) {
  return (
    <div className="space-y-4">
      <Panel dense title="S corporation stock basis by year — Lindqvist Family Woodworks (TaxProof roll-forward)">
        <table className="w-full text-[12.5px]">
          <thead className="text-left text-[10.5px] uppercase tracking-wide text-muted-foreground">
            <tr className="border-b"><th className="px-4 py-1.5 font-medium">Year</th><th className="px-2 text-right font-medium">Beginning</th><th className="px-2 text-right font-medium">+ Income</th>
              <th className="px-2 text-right font-medium">− Distributions</th><th className="px-2 text-right font-medium">Ending</th><th className="px-2 text-right font-medium">Excess (gain)</th><th className="px-4 font-medium">Source</th></tr>
          </thead>
          <tbody>
            {data.scorp_basis.map((r) => (
              <tr key={r.year} className={cn("border-b last:border-0", r.gap && "bg-rose-50")}>
                <td className="px-4 py-1.5 font-medium">{r.year}</td>
                <td className="px-2 text-right"><Amt v={r.beginning} /></td>
                <td className="px-2 text-right"><Amt v={r.income} /></td>
                <td className="px-2 text-right"><Amt v={r.distributions != null ? -r.distributions : null} /></td>
                <td className="px-2 text-right font-medium"><Amt v={r.ending} /></td>
                <td className="px-2 text-right">{r.excess_distribution ? <span className="font-medium text-amber-700"><Amt v={r.excess_distribution} /></span> : "—"}</td>
                <td className="px-4 text-[11px] text-muted-foreground">{r.gap ? <Chip tone="bad">gap — no K-1</Chip> : r.source} {r.refs.map((x) => <span key={x} className="ml-1"><EvRef id={x} /></span>)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="border-t px-4 py-2 text-[11px] text-muted-foreground">
          Basis cannot go below zero; distributions beyond basis are capital gain. The 2023 year was a gap in the prior preparer&apos;s file until the client found the 2023 K-1 (D40).
        </p>
      </Panel>
      {data.gap ? (
        <div className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-[13px] text-amber-950">
          <div className="font-semibold">Basis can&apos;t be proven for {data.version}: evidence gap in {data.gap.year}</div>
          <p className="mt-0.5 text-xs">{data.gap.detail} The engine starts at <Amt v={data.gap.engine_beginning} /> (<LineRef k="F7203.1" />). Nothing is compared until the missing K-1 is in the file.</p>
        </div>
      ) : <ChecksPanel checks={data.checks} title="TaxProof roll-forward vs the engine's Form 7203" />}
      <div className="grid gap-4 xl:grid-cols-2">
        {data.k1s.map((k) => (
          <Panel key={k.document_id} dense title={<span>{k.title}</span>}
            actions={<div className="flex gap-1"><Chip>{k.type}</Chip>
              {k.received_after_version && <Chip tone="muted">received after {data.version}</Chip>}
              <Chip tone={k.used_in_versions.length ? "good" : "warn"}>{k.used_in_versions.length ? `used ${k.used_in_versions.join(", ")}` : "not used"}</Chip></div>}>
            <div className="px-4 pt-1.5 text-[11px] text-muted-foreground">Tax year {k.tax_year} · received {k.received_at.slice(0, 10)} · <Link className="text-sky-700 hover:underline" href={`/evidence?doc=${k.document_id}&page=1`}>{k.document_id}</Link></div>
            <ul className="divide-y text-[12.5px]">
              {k.items.map((i) => (
                <li key={i.ref} className="flex items-center justify-between gap-2 px-4 py-1">
                  <span><EvRef id={i.ref} /> {i.label}</span>
                  <span className="flex items-center gap-2">{i.lines.map((l) => <LineRef key={l} k={l} />)}
                    {i.value_type === "percent" && typeof i.value === "number"
                      ? <span className="num">{(i.value * 100).toFixed(0)}%</span>
                      : <Amt v={i.value} />}</span>
                </li>
              ))}
            </ul>
          </Panel>
        ))}
      </div>
      <Panel title="Ridgeline partnership">
        <p className="text-xs text-slate-700">Capital account end of 2025: <Amt v={data.partnership.capital_account_end} />.
          {!data.partnership.outside_basis_known && <span className="text-amber-700"> Outside basis has never been computed (gap carried from the prior preparer).</span>}</p>
      </Panel>
    </div>
  );
}
