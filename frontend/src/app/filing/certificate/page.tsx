"use client";

import { Suspense } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { ShieldAlert, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useApi } from "@/lib/api";
import type { Certificate } from "@/lib/filing-types";
import { dateTime, money } from "@/lib/format";
import { Chip, ErrorState, Loading, PageHeader, Panel } from "@/components/tp/primitives";

export default function CertificatePage() {
  return <Suspense fallback={<Loading />}><CertificateView /></Suspense>;
}

function Row({ k, children }: { k: string; children: React.ReactNode }) {
  return <><dt className="text-muted-foreground">{k}</dt><dd>{children}</dd></>;
}

function CertificateView() {
  const params = useSearchParams();
  const sid = params.get("snapshot");
  const { data: c, error } = useApi<Certificate>(`/api/filing/certificate${sid ? `?snapshot_id=${sid}` : ""}`);
  if (error) return <ErrorState error={error} />;
  if (!c) return <Loading />;
  const lv = (k: "prepared" | "reviewed" | "partner") => `${c.signoffs[k].complete ? "complete" : "INCOMPLETE"} — ${c.signoffs[k].by.join(", ") || "—"}`;
  return (
    <div className="space-y-4">
      <PageHeader title="Filing certificate" subtitle="What was filed, on what evidence, with whose approval — reconstructed from the immutable snapshot."
        actions={<div className="flex gap-2 print:hidden"><Button size="sm" variant="outline" onClick={() => window.print()}>Print</Button><Link href="/filing" className="text-sm text-sky-700 hover:underline">Back to Filing</Link></div>} />
      <Panel title={<span className="flex items-center gap-1.5">{c.integrity.valid ? <ShieldCheck className="size-4 text-emerald-600" /> : <ShieldAlert className="size-4 text-rose-600" />}
        {c.kind === "original" ? "Original return" : `Amendment ${c.number}`} · snapshot #{c.snapshot_id}</span>}
        actions={<Chip tone={c.integrity.valid ? "good" : "bad"}>{c.integrity.valid ? "content hash verified" : "content does not match its hash"}</Chip>}>
        <dl className="grid gap-x-6 gap-y-1.5 text-[13px] sm:grid-cols-[200px_1fr]">
          <Row k="Return version">{c.return_version} (supplied engine output)</Row>
          <Row k="Filed">{dateTime(c.filed_at)}</Row>
          <Row k="Content hash"><span className="font-mono text-xs">{c.content_sha256}</span></Row>
          <Row k="Federal total tax">{money(c.engine_summary.federal.total_tax)} engine · {money(c.workpaper_summary.estimated.federal_total_tax)} as filed (estimate)</Row>
          <Row k="California total tax">{money(c.engine_summary.california.total_tax)} engine · {money(c.workpaper_summary.estimated.california_total_tax)} as filed (estimate)</Row>
          <Row k="Basis"><span className="text-xs text-slate-600">{c.basis}</span></Row>
          <Row k="Effective adjustments">
            <ul className="text-xs">{c.effective_adjustments.map((a) => (
              <li key={a.id}><span className="font-mono">{a.line}</span> {money(a.original_value)} → {money(a.adjusted_value)}{a.unit !== "USD" && ` ${a.unit}`} · est. federal {money(a.effect.federal, { sign: true })} / CA {money(a.effect.california, { sign: true })} · approved by {a.approved_by ?? "—"}</li>))}
              {c.effective_adjustments.length === 0 && <li>None</li>}</ul>
          </Row>
          <Row k="Documents used"><span className="font-mono text-xs">{c.documents_used.join(" ")}</span></Row>
          <Row k="Documents superseded"><span className="font-mono text-xs">{c.documents_superseded.join(" ") || "—"}</span></Row>
          <Row k="Preparer sign-off">{lv("prepared")}</Row>
          <Row k="Reviewer sign-off">{lv("reviewed")}</Row>
          <Row k="Partner sign-off">{lv("partner")}</Row>
          <Row k="Client approval">{c.client_approval ? <>{dateTime(c.client_approval.at)} — {c.client_approval.detail} <span className="font-mono text-xs">({c.client_approval.refs.join(", ")})</span></> : "—"}</Row>
          <Row k="E-file submissions">
            <ul className="text-xs">{c.efile_submissions.map((s) => (
              <li key={s.submission_id}><span className="font-mono">{s.submission_id}</span> · {s.jurisdiction} · <b>{s.status}</b> · {dateTime(s.date)}
                {s.errors?.map((e) => <span key={e.code} className="text-rose-700"> — {e.code}: {e.message}</span>)}</li>))}</ul>
          </Row>
          <Row k="Accepted">{Object.entries(c.accepted).map(([j, d]) => `${j} ${dateTime(d)}`).join(" · ")}</Row>
          <Row k="After filing">{c.post_filing.length ? c.post_filing.map((p) => `${p.label} ${dateTime(p.at)}`).join(" · ") : "—"}</Row>
          <Row k="Judgments">{c.judgments.length ? c.judgments.map((j) => `#${j.id} ${j.topic} — ${j.decision} (${j.authority})`).join("; ") : "—"}</Row>
          <Row k="Accepted as they stood">{c.accepted_with_explanation.length} item{c.accepted_with_explanation.length === 1 ? "" : "s"}, each with a recorded explanation</Row>
          <Row k="Unresolved at filing">{c.unresolved_items.length ? c.unresolved_items.map((u) => u.title).join("; ") : "None"}</Row>
        </dl>
      </Panel>
    </div>
  );
}
