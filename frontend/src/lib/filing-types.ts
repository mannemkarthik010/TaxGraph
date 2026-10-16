/** Iteration 8 API shapes: filing lifecycle, replay, snapshots, certificate, amendments, Examiner Mode. */

export type FilingEvent = {
  id: number; at: string; kind: "action" | "replay" | "client"; action: string; timeline_id: string | null; label: string;
  from_state: string; to_state: string; actor: string | null; actor_role: string | null;
  note?: string | null; recorded_at?: string;
  detail?: {
    submissions?: Submission[]; linked_findings?: { id: string; title: string; status: string }[];
    correction?: { note: string; evidence_refs: string[] }; amount?: Record<string, number>; basis?: string;
    notices?: { id: string; type: string; dated: string; response_due?: string }[]; refs?: string[];
    fingerprint?: { sha256: string }; package_sha256?: string; snapshot_id?: number; content_sha256?: string;
  };
};

export type Submission = { date: string; jurisdiction: string; submission_id: string; status: string; errors?: { code: string; message: string }[] };

export type FilingState = {
  state: string; label: string; states: { key: string; label: string }[]; clock: string; history: FilingEvent[];
  jurisdictions: Record<string, Submission>;
  /** The scripted client approval is spent; after a reopen the client approves again in TaxProof. */
  awaiting_client?: boolean; client_can_approve?: boolean;
  actions?: { action: string; label: string; available: boolean; why_not: string[]; needs_note: boolean; needs_refs: boolean }[];
  next_event?: { id: string; at: string; event: string; label: string; refs: string[]; detail: string | null; possible: boolean;
                 needs: string | null; can_replay: boolean } | null;
  upcoming?: { id: string; at: string; event: string; label: string }[];
  approval?: { current: string; partner: string | null; client: string | null; client_matches: boolean };
  snapshots?: { id: number; kind: string; number: number; filed_at: string; content_sha256: string; integrity: boolean }[];
};

export type Signers = { by: string[]; complete: boolean };

export type Certificate = {
  snapshot_id: number; kind: string; number: number; content_sha256: string; integrity: { valid: boolean; stored: string; computed: string };
  filed_at: string; return_version: string;
  engine_summary: { federal: Record<string, number>; california: Record<string, number> };
  workpaper_summary: { estimated: Record<string, number>; engine: Record<string, number>; applied_adjustments: number; note: string };
  basis: string;
  effective_adjustments: { id: number; line: string; original_value: number; adjusted_value: number; difference: number; unit: string;
                           reason: string; effect: { federal: number; california: number }; approved_by: string | null }[];
  documents_used: string[]; documents_superseded: string[];
  signoffs: Record<"prepared" | "reviewed" | "partner", Signers>;
  client_approval: { at: string; detail: string | null; refs: string[]; fingerprint: string } | null;
  efile_submissions: Submission[]; accepted: Record<string, string>;
  post_filing: { at: string; event: string; label: string; detail: string | null }[];
  unresolved_items: { key: string; title: string; group: string }[];
  accepted_with_explanation: { key: string; title: string; explanation: string | null }[];
  judgments: { id: number; topic: string; decision: string; authority: string }[];
};

export type AmendmentChange = { line: string; label: string; filed_value: number; amended_value: number; difference: number; unit: string;
                                effect: { kind: string; federal: number; california: number }; reason: string; evidence_refs: string[] };
export type Amendment = { id: number; base_snapshot_id: number; reason: string; changes: AmendmentChange[]; status: string;
                          created_by: string; created_by_id: string; approved_by: string | null; filed_snapshot_id: number | null;
                          total_effect: { federal: number; california: number } };

export type ExaminerNotice = { id: string; agency: string; type: string; dated: string; response_due: string | null; document: string | null;
                               received_at: string | null; items: { text: string; lines: string[] }[]; response_id: number | null;
                               response_status: string | null };
export type ExaminerOverview = { snapshot: { id: number; kind: string; number: number; filed_at: string; content_sha256: string; integrity: boolean };
                                 clock: string; notices: ExaminerNotice[]; excluded: string[] };

export type ExaminerItem = {
  line: { key: string; label: string; form: string };
  reported: { filed_value: number; original_filed_value: number | null; engine_value: number; snapshot_id: number; snapshot_sha256: string;
              basis: FiledBasis; basis_note: string | null; affected_by: string[] };
  calculation: { rule: string | null; description: string | null; engine_note: string | null;
                 inputs: { key: string; label: string; filed_value: number | null; basis?: FiledBasis | null }[] };
  evidence: { ref: string; kind: string; label: string; value: unknown; cited_by_workpaper?: boolean }[];
  client_answers: { ref: string; question: string; answer: string; answered_by: string }[];
  adjustment_history: { id: number; original_value: number; adjusted_value: number; difference: number; unit: string; reason: string;
                        approved_by: string | null; created_by: string | null; effect: { federal: number; california: number } }[];
  verifications: { id: number; method: string; by: string; at: string; note: string | null; target_ref: string }[];
  judgments: { id: number; topic: string; decision: string; authority: string; rationale: string; reviewed_by: string; partner_by: string }[];
  independent_checks: { id: string; title: string; status: string; summary: string; breakdown: { label: string; value: unknown }[] }[];
  filed_result: { filed_at: string; accepted: Record<string, string>; amendments: { number: number; filed_at: string; filed_value: number; amended_value: number; reason: string }[]; integrity: boolean };
  excluded: string[];
};

export type NoticeResponse = {
  id: number; notice_id: string; snapshot_id: number; status: string; cover_letter: string; prepared_by: string; prepared_by_id: string;
  approved_by: string | null; approved_at: string | null; content_sha256: string | null;
  items: { text: string; lines: string[]; explanation: string; exhibits: { ref: string; kind: string; label: string; value: unknown; lines: string[] }[] }[];
};

/** How a filed figure was obtained (see services/filing.BASIS_NOTE). */
export type FiledBasis = "engine" | "adjustment" | "amendment" | "derived" | "estimate_rates" | "not_recomputed";
