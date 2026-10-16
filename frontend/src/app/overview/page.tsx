"use client";

import Link from "next/link";
import { ArrowRight, Home, MapPin, ShieldCheck, Users } from "lucide-react";
import { useApi } from "@/lib/api";
import { date, humanize, money, pct } from "@/lib/format";
import type { Area, Engagement, Household, Me, ReturnSummary } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { AssuranceTwin, FiledFigures, SignatureFeatures } from "@/components/tp/twin/dashboard";
import { Chip, ErrorState, Loading, Money, PageHeader, Panel, SensitiveValue, Stat } from "@/components/tp/primitives";
import { cn } from "@/lib/utils";

export default function OverviewPage() {
  const { data: eng } = useApi<Engagement>("/api/engagement");
  const { data: me } = useApi<Me>("/api/session/me");
  const { data: sum, error: sumErr } = useApi<ReturnSummary>("/api/return/summary");
  const { data: hh, error: hhErr } = useApi<Household>("/api/household");
  const { data: areas } = useApi<Area[]>("/api/workpaper/areas");
  const internal = !!me?.permissions.includes("view_internal_notes");

  const fed = (f: string) => sum?.headlines.find((h) => h.jurisdiction === "federal" && h.field === f);
  const ca = (f: string) => sum?.headlines.find((h) => h.jurisdiction === "california" && h.field === f);

  return (
    <div className="space-y-5">
      <PageHeader
        title="Okafor-Lindqvist household — 2025 · Return Assurance Twin"
        subtitle={<>The return engine says the return is computed. <b className="font-medium text-slate-700">TaxProof asks whether it is proven.</b></>}
        actions={internal ? <Link href="/trust"><Button><ShieldCheck className="size-4" />Why should I trust this return?</Button></Link> : undefined}
      />
      <ErrorState error={sumErr} />

      {/* Headline numbers */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title={<span className="flex items-center gap-2">Federal · Form 1040 <Chip tone="engine">engine {sum?.version}</Chip></span>}
          actions={<Link href="/return" className="text-xs text-sky-700 hover:underline">Open return →</Link>}>
          {!sum ? <Loading /> : (
            <div className="grid grid-cols-3 gap-4">
              <Stat label="Total tax" value={money(fed("total_tax")?.value)}
                sub={<>2024: {money(fed("total_tax")?.prior_year)} · {pct(fed("total_tax")?.change_pct)}</>} />
              <Stat label="AGI" value={money(fed("agi")?.value)} sub={<>2024: {money(fed("agi")?.prior_year)}</>} />
              <Stat label={(fed("balance_due")?.value ?? 0) >= 0 ? "Balance due" : "Refund"}
                value={money(Math.abs(fed("balance_due")?.value ?? 0))} tone={(fed("balance_due")?.value ?? 0) > 0 ? "bad" : "good"}
                sub={<>incl. penalty {money(fed("penalty")?.value)}</>} />
            </div>
          )}
        </Panel>
        <Panel title={<span className="flex items-center gap-2">California · Form 540NR (part-year) <Chip tone="engine">engine {sum?.version}</Chip></span>}>
          {!sum ? <Loading /> : (
            <div className="grid grid-cols-3 gap-4">
              <Stat label="CA total tax" value={money(ca("total_tax")?.value)}
                sub={<>2024: {money(ca("total_tax")?.prior_year)} · {pct(ca("total_tax")?.change_pct)}</>} />
              <Stat label="CA AGI" value={money(ca("ca_agi")?.value)} sub={<>of {money(ca("total_agi")?.value)} total</>} />
              <Stat label={(ca("balance_due")?.value ?? 0) >= 0 ? "Balance due" : "Refund"}
                value={money(Math.abs(ca("balance_due")?.value ?? 0))} tone={(ca("balance_due")?.value ?? 0) > 0 ? "bad" : "good"} />
            </div>
          )}
        </Panel>
      </div>

      {internal && <FiledFigures />}

      {/* The Return Assurance Twin: is the return proven? */}
      {internal && <AssuranceTwin />}

      <div className="grid gap-4 lg:grid-cols-3">
        <Panel title={<span className="flex items-center gap-1.5"><ShieldCheck className="size-4 text-emerald-600" /> Source packet integrity</span>}>
          {!eng ? <Loading /> : (
            <dl className="space-y-1.5 text-xs">
              <Row k="Packet" v={`${eng.packet.name}`} />
              <Row k="Generated" v={date(eng.packet.generated)} />
              <Row k="SHA-256 now" v={<code className="text-[10.5px]">{eng.packet.sha256.slice(0, 20)}…</code>} />
              <Row k="At engagement" v={eng.packet.sha256 === eng.packet.sha256_at_engagement_creation
                ? <Chip tone="good">unchanged</Chip> : <Chip tone="bad">changed on disk</Chip>} />
              <Row k="Contents" v={`${eng.packet.counts.documents} docs · ${eng.packet.counts.extracted_values.toLocaleString()} values · ${eng.packet.counts.return_versions} versions`} />
            </dl>
          )}
        </Panel>
        {internal && (
          <Panel title="Signature features" className="lg:col-span-2">
            <SignatureFeatures />
          </Panel>
        )}
      </div>

      {/* Prior-year comparison */}
      <Panel title="Return summary vs 2024 (as filed by prior preparer)" dense
        actions={sum && <span className="text-[11px] text-muted-foreground">Flag: change &gt; {sum.variance_standard.percent}% and &gt; {money(sum.variance_standard.amount)} (firm standard)</span>}>
        {!sum ? <div className="p-4"><Loading /></div> : (
          <table className="w-full text-[13px]">
            <thead className="text-left text-[11px] uppercase tracking-wide text-muted-foreground">
              <tr className="border-b"><th className="px-4 py-2 font-medium">Item</th><th className="px-2 font-medium">Line</th>
                <th className="px-2 text-right font-medium">2025 ({sum.version})</th><th className="px-2 text-right font-medium">2024</th>
                <th className="px-2 text-right font-medium">Change</th><th className="px-4 font-medium" /></tr>
            </thead>
            <tbody>
              {sum.headlines.map((h) => (
                <tr key={`${h.jurisdiction}.${h.field}`} className="border-b last:border-0 hover:bg-slate-50/60">
                  <td className="px-4 py-1.5">{h.label} <span className="text-[11px] text-muted-foreground">{h.jurisdiction === "california" ? "CA" : ""}</span></td>
                  <td className="px-2 font-mono text-[11px] text-muted-foreground">
                    {h.line_key ? <Link className="hover:text-sky-700 hover:underline" href={`/return?line=${encodeURIComponent(h.line_key)}`}>{h.line_key}</Link> : "summary"}
                  </td>
                  <td className="px-2 text-right"><Money value={h.value} /></td>
                  <td className="px-2 text-right text-muted-foreground"><Money value={h.prior_year} /></td>
                  <td className="px-2 text-right"><Money value={h.change} sign /> <span className="text-[11px] text-muted-foreground">{h.change != null ? pct(h.change_pct) : ""}</span></td>
                  <td className="px-4 text-right whitespace-nowrap">
                    {h.variance_flag && <Chip tone="warn">explain variance</Chip>}
                    {h.line_key && <Link href={`/prove?ref=${encodeURIComponent(h.line_key)}&mode=up`} className="ml-2 text-[11px] text-sky-700 hover:underline">Prove it</Link>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>

      <div className="grid gap-4 lg:grid-cols-3">
        {/* Household */}
        <Panel title={<span className="flex items-center gap-1.5"><Users className="size-4" /> Household</span>} className="lg:col-span-2"
          actions={hh && <Chip>{humanize(hh.filing_status)}</Chip>}>
          <ErrorState error={hhErr} />
          {!hh ? <Loading /> : (
            <div className="space-y-4">
              <div className="grid gap-2 sm:grid-cols-2">
                {hh.people.map((p) => (
                  <div key={p.id} className="rounded-md border px-3 py-2">
                    <div className="flex items-center justify-between">
                      <div className="text-[13px] font-medium">{p.name}</div>
                      <Chip tone={p.role === "dependent" ? "info" : "neutral"}>{p.relationship ?? p.role}</Chip>
                    </div>
                    <div className="mt-1 grid grid-cols-[64px_1fr] gap-y-0.5 text-xs text-slate-600">
                      <span className="text-muted-foreground">SSN</span>
                      <SensitiveValue masked={p.ssn} fieldRef={`household:${p.id}.ssn`} canReveal={!!me?.can_reveal_sensitive} />
                      <span className="text-muted-foreground">Born</span><span>{date(p.dob)}</span>
                      {p.ip_pin !== undefined && p.ip_pin !== null && (<>
                        <span className="text-muted-foreground">IP PIN</span>
                        <SensitiveValue masked={p.ip_pin} fieldRef={`household:${p.id}.ip_pin`} canReveal={!!me?.can_reveal_sensitive} />
                      </>)}
                      {p.occupation && (<><span className="text-muted-foreground">Work</span><span>{p.occupation}</span></>)}
                      {p.note && (<><span className="text-muted-foreground">Note</span><span>{p.note}</span></>)}
                      {p.own_income && (<><span className="text-muted-foreground">Own return</span><span>{p.own_income}</span></>)}
                    </div>
                  </div>
                ))}
              </div>
              <ResidencyBar hh={hh} />
              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Refund / payment account</div>
                  <div className="text-xs text-slate-700">{hh.bank_account_for_refund_or_payment.bank} · {hh.bank_account_for_refund_or_payment.type}</div>
                  <div className="text-xs">Routing <SensitiveValue masked={hh.bank_account_for_refund_or_payment.routing} fieldRef="household:bank.routing" canReveal={!!me?.can_reveal_sensitive} /></div>
                  <div className="text-xs">Account <SensitiveValue masked={hh.bank_account_for_refund_or_payment.account} fieldRef="household:bank.account" canReveal={!!me?.can_reveal_sensitive} /></div>
                </div>
                <div>
                  <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Related returns (outside this engagement)</div>
                  <ul className="space-y-1 text-xs text-slate-700">
                    {hh.related_returns.map((r) => (
                      <li key={r.who}><b className="font-medium">{r.who}</b> — {r.return}
                        <span className="text-muted-foreground"> · in packet: {typeof r.in_this_packet === "string" ? r.in_this_packet : r.in_this_packet ? "yes" : "no"}</span></li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>
          )}
        </Panel>

        {/* Team + deadlines */}
        <div className="space-y-4">
          <Panel title="Engagement team">
            {!eng ? <Loading /> : (
              <ul className="space-y-1.5 text-[13px]">
                {eng.assignments.map((a) => (
                  <li key={`${a.user_id}.${a.role}`} className="flex items-center justify-between gap-2">
                    <span className="whitespace-nowrap">{a.name}</span>
                    <span className="text-right text-[11px] text-muted-foreground">{humanize(a.role)} · since {date(a.assigned_at)}</span>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
          <Panel title="Deadlines">
            {!eng ? <Loading /> : (
              <ul className="space-y-1.5 text-xs">
                {[...eng.deadlines].sort((a, b) => a.date.localeCompare(b.date)).map((d) => (
                  <li key={d.what} className="flex justify-between gap-3">
                    <span className="text-slate-700">{d.what}</span>
                    <span className="num shrink-0 text-muted-foreground">{date(d.date)}</span>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>
      </div>

      {/* Areas */}
      <Panel title="Tax areas" actions={<Link href="/review?tab=signoffs" className="text-[11px] text-sky-700 hover:underline">Sign-offs →</Link>}>
        {!areas ? <Loading /> : (
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
            {areas.map((a) => (
              <Link key={a.key} href={`/return?area=${a.key}`} className="group rounded-md border px-3 py-2 hover:border-primary/40 hover:bg-slate-50">
                <div className="flex items-center justify-between">
                  <span className="text-[13px] font-medium">{a.title}</span>
                  <ArrowRight className="size-3.5 text-slate-300 group-hover:text-primary" />
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-1 text-[11px] text-muted-foreground">
                  <span>{a.line_count} lines</span>
                  {a.budget_hours != null && <span>· {a.budget_hours}h budget</span>}
                  {a.open_notes > 0 && <Chip tone="warn">{a.open_notes} open</Chip>}
                </div>
                <div className="mt-1.5 flex gap-1">
                  {(["preparer_status", "reviewer_status", "partner_status"] as const).map((k) => (
                    <Chip key={k} tone="muted">{k.split("_")[0][0].toUpperCase()} · {humanize(a[k])}</Chip>
                  ))}
                </div>
              </Link>
            ))}
          </div>
        )}
      </Panel>
    </div>
  );
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <dt className="text-muted-foreground">{k}</dt>
      <dd className="text-right text-slate-700">{v}</dd>
    </div>
  );
}

function ResidencyBar({ hh }: { hh: Household }) {
  const start = Date.UTC(hh.tax_year, 0, 1);
  const end = Date.UTC(hh.tax_year, 11, 31);
  const total = (end - start) / 86400000 + 1;
  const segs = hh.residency.map((r) => {
    const a = Date.parse(`${r.from}T00:00:00Z`);
    const b = Date.parse(`${r.to}T00:00:00Z`);
    return { ...r, days: (b - a) / 86400000 + 1 };
  });
  return (
    <div>
      <div className="mb-1 flex items-center gap-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
        <MapPin className="size-3" /> Residency {hh.tax_year}
      </div>
      <div className="flex h-7 overflow-hidden rounded-md border text-[11px] font-medium">
        {segs.map((s) => (
          <div key={s.state} style={{ width: `${(s.days / total) * 100}%` }}
            className={cn("flex items-center justify-center", s.state === "CA" ? "bg-amber-100 text-amber-900" : "bg-sky-100 text-sky-900")}>
            {s.state} · {s.days} days
          </div>
        ))}
      </div>
      <div className="mt-1 flex flex-wrap gap-x-4 text-[11px] text-muted-foreground">
        {hh.addresses.map((a) => (
          <span key={a.address} className="inline-flex items-center gap-1"><Home className="size-3" />{a.address} · {date(a.from)} → {a.to ? date(a.to) : "present"}</span>
        ))}
      </div>
    </div>
  );
}

