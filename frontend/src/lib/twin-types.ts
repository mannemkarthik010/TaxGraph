/** Iteration 10 API shapes: the Return Assurance Twin dashboard and the trust report. */

export type AssuranceComponent = { key: string; label: string; weight: number; ratio: number; points: number; reason: string; link: string };
export type Assurance = { score: number; level: "strong" | "developing" | "weak"; components: AssuranceComponent[]; method: string };
export type Blocker = { kind: "gate" | "lifecycle" | "integrity"; key: string; label: string; count: number; items: string[]; link: string };

export type Twin = {
  version: string;
  engine: { federal: Record<string, number>; california: Record<string, number> };
  workpaper: { applied_adjustments: number; estimated: Record<string, number>; note: string };
  filed: { snapshot_id: number; kind: string; filed_at: string; integrity: boolean; broken?: number[]; summary: Record<string, { value: number; basis: string }> | null } | null;
  lifecycle: { state: string; label: string; client_authorized: boolean; awaiting_client: boolean; jurisdictions: Record<string, { status: string; submission_id: string }> };
  assurance: Assurance;
  documents: { total: number; accounted: number; issues: { id: string; label: string }[]; not_used: { id: string; reason: string }[] };
  traceability: { material: number; traceable: number; threshold: number };
  coverage: { values: number; verified: number; flagged: number; flagged_verified: number };
  checks: { total: number; passed: number; failed: number; attention: number; dispositioned: number; open: { id: string; title: string; status: string }[] };
  judgments: { items: number; decided: number; recorded: number; approved: number };
  signoffs: { areas: number; prepared: number; reviewed: number; partner: number; complete: number; reopened: { area: string; level: string; reason: string | null }[] };
  what_prevents_filing: Blocker[];
  can_file_now: boolean;
  critical: { key: string; title: string; score: number; areas: string[]; components: { label: string; points: number }[] }[];
  /** All high-risk open items; `critical` lists only the first few. */
  critical_count: number;
  inbox: { open: number; blocking: number };
  since: { seen_at: string | null; first_visit: boolean; groups: { label: string; count: number }[];
           events: { seq: number; at: string; action: string; by: string; target_ref: string | null }[] };
};

export type TrustSection = { key: string; question: string; answer: string; status: "good" | "warn" | "bad"; detail: string; items: string[]; link: string };
export type TrustReport = {
  generated_at: string; version: string; report_sha256: string; verdict: string; closing: string;
  lifecycle: Twin["lifecycle"]; assurance: Assurance; sections: TrustSection[]; what_prevents_filing: Blocker[];
};
