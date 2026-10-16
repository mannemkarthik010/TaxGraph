"use client";

import Link from "next/link";
import { BadgeCheck, Clock, GitCompareArrows, Landmark, OctagonAlert, ShieldCheck, Swords, Waypoints } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useApi, useMutate } from "@/lib/api";
import type { Blocker, Twin } from "@/lib/twin-types";
import { dateTime, money } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Chip, ErrorState, Loading, Panel } from "../primitives";

const LEVEL_TONE = { strong: "good", developing: "warn", weak: "bad" } as const;

export function ScoreDial({ score, level }: { score: number; level: string }) {
  const r = 34, c = 2 * Math.PI * r;
  const color = level === "strong" ? "#059669" : level === "developing" ? "#d97706" : "#e11d48";
  return (
    <svg viewBox="0 0 80 80" className="size-24" role="img" aria-label={`Return assurance score ${score} of 100`}>
      <circle cx="40" cy="40" r={r} fill="none" stroke="#e2e8f0" strokeWidth="8" />
      <circle cx="40" cy="40" r={r} fill="none" stroke={color} strokeWidth="8" strokeLinecap="round"
        strokeDasharray={`${(score / 100) * c} ${c}`} transform="rotate(-90 40 40)" />
      <text x="40" y="44" textAnchor="middle" className="fill-slate-900 text-[18px] font-semibold">{score}</text>
    </svg>
  );
}

function Tile({ label, value, sub, tone, href }: { label: string; value: string; sub?: string; tone?: "good" | "warn" | "bad"; href: string }) {
  return (
    <Link href={href} className="rounded-lg border bg-card p-3 transition hover:border-slate-300" data-testid={`tile-${label}`}>
      <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className={cn("num mt-0.5 text-lg font-semibold", tone === "bad" && "text-rose-700", tone === "warn" && "text-amber-700", tone === "good" && "text-emerald-700")}>{value}</div>
      {sub && <div className="text-[11px] text-muted-foreground">{sub}</div>}
    </Link>
  );
}

const ratioTone = (a: number, b: number) => (b === 0 || a === b ? "good" : a / b >= 0.6 ? "warn" : "bad");

export function PreventFiling({ blockers, compact }: { blockers: Blocker[]; compact?: boolean }) {
  if (!blockers.length) return <p className="flex items-center gap-1.5 text-[13px] text-emerald-700"><BadgeCheck className="size-4" />Nothing prevents filing.</p>;
  return (
    <ol className="space-y-1.5 text-[13px]" data-testid="prevent-filing">
      {blockers.map((b) => (
        <li key={b.key}>
          <Link href={b.link} className="flex items-center gap-1.5 hover:underline">
            <OctagonAlert className={cn("size-3.5", b.kind === "lifecycle" ? "text-amber-600" : "text-rose-600")} />
            <span className={cn("font-medium", b.kind === "integrity" && "text-rose-800")}>{b.label}</span>
            {b.kind !== "lifecycle" && <Chip tone="bad">{b.count}</Chip>}
          </Link>
          {!compact && b.items.length > 0 && <ul className="ml-5 list-disc text-xs text-slate-600">{b.items.slice(0, 6).map((x) => <li key={x}>{x}</li>)}</ul>}
        </li>
      ))}
    </ol>
  );
}

export const SIGNATURES = [
  { title: "Prove It", href: "/prove?ref=line%3Av3%3ASchC.44a&mode=up&v=v3", icon: Waypoints, text: "Trace any number to the exact page." },
  { title: "Challenge Return", href: "/challenge", icon: Swords, text: "Independent checks against the engine." },
  { title: "Return Assurance Twin", href: "/trust", icon: ShieldCheck, text: "Why should I trust this return?" },
  { title: "Tax Time Machine", href: "/return?tab=time", icon: GitCompareArrows, text: "What changed between versions, and why." },
  { title: "Living Sign-offs", href: "/review?tab=signoffs", icon: BadgeCheck, text: "Approvals that reopen when evidence changes." },
  { title: "Examiner Mode", href: "/examiner", icon: Landmark, text: "Reconstruct and defend the filed return." },
] as const;

export function SignatureFeatures() {
  return (
    <div className="grid gap-2 sm:grid-cols-3 lg:grid-cols-6">
      {SIGNATURES.map((s) => (
        <Link key={s.title} href={s.href} className="rounded-lg border bg-card p-3 hover:border-primary">
          <s.icon className="size-4 text-primary" />
          <div className="mt-1 text-[13px] font-semibold">{s.title}</div>
          <div className="text-[11px] text-muted-foreground">{s.text}</div>
        </Link>
      ))}
    </div>
  );
}

function SinceYouLooked({ t, onSeen }: { t: Twin; onSeen: () => void }) {
  const mutate = useMutate();
  const s = t.since;
  return (
    <Panel title={<span className="flex items-center gap-1.5"><Clock className="size-4" />Since you last looked</span>}
      actions={<Button size="sm" variant="ghost" className="h-7 text-xs" onClick={async () => { await mutate("/api/twin/seen"); onSeen(); }}>Mark as seen</Button>}>
      {s.first_visit ? <p className="text-xs text-muted-foreground">First visit: from now on this shows what others changed.</p>
        : s.groups.length === 0 ? <p className="text-xs text-muted-foreground">Nothing new since {dateTime(s.seen_at)}.</p> : (
          <div className="space-y-2 text-xs">
            <div className="flex flex-wrap gap-1">{s.groups.map((g) => <Chip key={g.label} tone="info">{g.count} {g.label}</Chip>)}</div>
            <ul className="space-y-0.5 text-slate-600">{s.events.slice(0, 8).map((e) => (
              <li key={e.seq}>{dateTime(e.at)} · {e.by} · {e.action.replace(/[._]/g, " ")}{e.target_ref && <code className="ml-1 text-[10.5px]">{e.target_ref}</code>}</li>))}</ul>
            <p className="text-muted-foreground">since {dateTime(s.seen_at)}</p>
          </div>
        )}
    </Panel>
  );
}

/** The dashboard's twin section: score, metrics, critical issues, what prevents filing, changes. */
export function AssuranceTwin() {
  const { data: t, error, mutate: reload } = useApi<Twin>("/api/twin");
  if (error) return <ErrorState error={error} />;
  if (!t) return <Loading rows={4} />;
  const a = t.assurance;
  const fileTone = t.lifecycle.state === "filed" || t.lifecycle.state === "frozen" ? "good" : t.what_prevents_filing.length ? "bad" : "good";
  return (
    <div className="space-y-4">
      <div className="grid gap-4 lg:grid-cols-[1fr_1fr]">
        <Panel title="Return assurance score" actions={<Link href="/trust"><Button size="sm"><ShieldCheck className="size-4" />Why should I trust this return?</Button></Link>}>
          <div className="flex gap-4">
            <div className="flex flex-col items-center"><ScoreDial score={a.score} level={a.level} /><Chip tone={LEVEL_TONE[a.level]}>{a.level}</Chip></div>
            <ul className="flex-1 space-y-1 text-xs" data-testid="score-components">
              {a.components.map((c) => (
                <li key={c.key} title={c.reason}>
                  <Link href={c.link} className="flex items-center gap-2 hover:underline">
                    <span className="w-48 truncate">{c.label}</span>
                    <span className="h-1.5 flex-1 rounded bg-slate-100"><span className={cn("block h-1.5 rounded", c.ratio >= 0.999 ? "bg-emerald-500" : c.ratio >= 0.6 ? "bg-amber-400" : "bg-rose-400")} style={{ width: `${c.ratio * 100}%` }} /></span>
                    <span className="num w-14 text-right text-muted-foreground">{c.points}/{c.weight}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </div>
          <p className="mt-2 text-[11px] text-muted-foreground">{a.method}</p>
        </Panel>
        <Panel title={<span className="flex items-center gap-1.5"><OctagonAlert className="size-4 text-rose-600" />What prevents filing?</span>}
          actions={<Chip tone={fileTone}>{t.lifecycle.label}</Chip>}>
          <PreventFiling blockers={t.what_prevents_filing} compact />
        </Panel>
      </div>
      <div className="grid gap-2 sm:grid-cols-4 lg:grid-cols-8">
        <Tile label="Evidence coverage" value={`${t.coverage.verified} / ${t.coverage.values}`} sub="values verified" tone={ratioTone(t.coverage.verified, t.coverage.values)} href="/evidence" />
        <Tile label="Independent checks" value={`${t.checks.passed} / ${t.checks.total}`} sub={`passed · ${t.checks.dispositioned} others decided`} tone={t.checks.open.length ? "warn" : "good"} href="/challenge" />
        <Tile label="Areas reviewed" value={`${t.signoffs.reviewed} / ${t.signoffs.areas}`} sub={t.signoffs.reopened.length ? `${t.signoffs.reopened.length} reopened` : "reviewed sign-offs"} tone={ratioTone(t.signoffs.reviewed, t.signoffs.areas)} href="/review?tab=signoffs" />
        <Tile label="Judgments" value={`${t.judgments.decided} / ${t.judgments.items}`} sub={`decided · ${t.judgments.approved} approved`} tone={ratioTone(t.judgments.decided, t.judgments.items)} href="/review?tab=judgments" />
        <Tile label="Documents" value={`${t.documents.accounted} / ${t.documents.total}`} sub="accounted for" tone={ratioTone(t.documents.accounted, t.documents.total)} href="/evidence" />
        <Tile label="Sign-offs complete" value={`${t.signoffs.complete} / ${t.signoffs.areas}`} sub={`partner ${t.signoffs.partner}`} tone={ratioTone(t.signoffs.complete, t.signoffs.areas)} href="/review?tab=signoffs" />
        <Tile label="Filing readiness" value={t.what_prevents_filing.length ? `${t.what_prevents_filing.length} blocker(s)` : "Ready"} sub={t.lifecycle.label} tone={fileTone} href="/filing" />
        <Tile label="Critical issues" value={String(t.critical_count)} sub={`${t.inbox.open} open · ${t.inbox.blocking} blocking`} tone={t.critical_count ? "bad" : "good"} href="/review?tab=brief" />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title={`Critical issues (highest review risk) · ${t.critical_count}`}
          actions={t.critical_count > t.critical.length && <Link href="/review?tab=brief" className="text-xs text-sky-700 hover:underline">all {t.critical_count} →</Link>}>
          {t.critical.length === 0 ? <p className="text-xs text-muted-foreground">No high-risk open items.</p> : (
            <ul className="space-y-1 text-[13px]">{t.critical.map((c) => (
              <li key={c.key} className="flex items-start gap-2"><span className="num w-7 text-right font-semibold text-rose-700">{c.score}</span>
                <span className="flex-1"><Link className="hover:underline" href="/review?tab=brief">{c.title}</Link>
                  <span className="block text-[11px] text-muted-foreground">{c.components.slice(0, 3).map((x) => x.label.toLowerCase()).join(" · ")}</span></span></li>))}</ul>
          )}
        </Panel>
        <SinceYouLooked t={t} onSeen={() => reload()} />
      </div>
    </div>
  );
}

/** The figures that matter beside the engine's: as filed (engine + adjustments, estimate) or the workpaper estimate. */
export function FiledFigures() {
  const { data: t } = useApi<Twin>("/api/twin");
  if (!t || (!t.filed && !t.workpaper.applied_adjustments)) return null;
  const e = t.filed ? null : t.workpaper.estimated;
  const f = t.filed?.summary;
  const val = (k: string) => (f ? f[k]?.value : e?.[k]);
  const fedBal = val("federal_balance_due") ?? 0, caBal = val("california_balance_due") ?? 0;
  return (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-1 rounded-lg border border-sky-200 bg-sky-50/50 px-4 py-2 text-[13px]" data-testid="filed-figures">
      <Chip tone="info">{t.filed ? `As filed ${dateTime(t.filed.filed_at)}` : `Workpaper (${t.workpaper.applied_adjustments} adjustment${t.workpaper.applied_adjustments === 1 ? "" : "s"})`}</Chip>
      <span>Federal tax <b className="num">{money(val("federal_total_tax"))}</b></span>
      <span>{fedBal >= 0 ? "Federal balance due" : "Federal refund"} <b className="num">{money(Math.abs(fedBal))}</b></span>
      <span>California tax <b className="num">{money(val("california_total_tax"))}</b></span>
      <span>{caBal >= 0 ? "California balance due" : "California refund"} <b className="num">{money(Math.abs(caBal))}</b></span>
      <span className="text-[11px] text-muted-foreground">engine figures plus applied adjustments — adjustment effects are estimates; the panels above show the engine&apos;s own output</span>
    </div>
  );
}
