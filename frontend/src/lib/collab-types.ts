/** Iteration 7 API shapes: Uncertainty Inbox, client questions, Judgment Ledger, sign-offs, filing readiness. */

export type HistoryEntry = { action: string; by: string; by_name?: string | null; role: string; at: string; note?: string | null };

export type InboxGroupKey = "blockers" | "conflicts" | "missing" | "judgment" | "questions" | "review";
export type InboxAction = "resolve" | "accept" | "assign" | "escalate" | "ask_client" | "record_judgment" | "create_adjustment";

export type InboxItem = {
  key: string;
  source: "note" | "finding" | "diagnostic" | "adjustment" | "judgment" | "question";
  group: InboxGroupKey;
  group_label: string;
  nature: InboxGroupKey;
  nature_label: string;
  title: string;
  summary: string;
  severity: string;
  refs: string[];
  areas: string[];
  blocks_filing: boolean;
  blocking_reason: string | null;
  status: "open" | "handled";
  handled: { kind: string; label: string; id?: number; note?: string | null; by?: string | null; at?: string | null } | null;
  escalated: boolean;
  escalation_note: string | null;
  assignee_id: string | null;
  assignee: string | null;
  links: { finding_id?: string | null; questions?: { id: number; status: string }[]; judgments?: { id: number; status: string }[];
           adjustment_id?: number; judgment_id?: number; question_id?: number };
  history: HistoryEntry[];
  detail: Record<string, unknown> & {
    proposed_adjustment?: { line: string; value: number } | null;
    active_adjustment?: number | null;
    effect?: { federal: number; california: number; kind?: string } | null;
    evidence?: string[];
  };
  actions: InboxAction[];
};

export type InboxResponse = {
  version: string;
  groups: { key: InboxGroupKey; label: string; open: number; items: InboxItem[] }[];
  totals: { open: number; blocking: number; handled: number; mine: number };
};

export type ClientQuestion = {
  id: number;
  question: string;
  status: "asked" | "answered" | "accepted" | "withdrawn";
  about: string;
  asked_by: string | null;
  asked_at: string;
  addressed_to: string | null;
  addressed_to_id: string | null;
  answer: string | null;
  answered_by: string | null;
  answered_at: string | null;
  // staff only
  target_ref?: string;
  item_key?: string | null;
  blocking?: boolean;
  accepted_by?: string | null;
  accepted_at?: string | null;
  acceptance_note?: string | null;
  resolves_item?: boolean;
  history?: HistoryEntry[];
  evidence_node?: string | null;
};

export type TaxEffect = { federal: number | null; california: number | null; source: string; basis: string; tax_at_stake?: number | null };

export type JudgmentOption = TaxEffect & { option: string; label: string; related: boolean; choices?: Record<string, string> };

export type Judgment = {
  id: number;
  item_key: string | null;
  topic: string;
  target_refs: string[];
  areas: string[];
  decision: string;
  decision_option: string;
  alternatives: { option: string; description: string; federal: number | null; california: number | null; source: string; why_not: string }[];
  rationale: string;
  authority: string;
  evidence_refs: string[];
  tax_effect: TaxEffect;
  review_required: "reviewer" | "partner";
  status: "recorded" | "reviewed" | "approved" | "superseded";
  prepared_by: string | null;
  prepared_by_id: string;
  prepared_at: string;
  reviewed_by: string | null;
  reviewed_at: string | null;
  partner_by: string | null;
  partner_at: string | null;
  supersedes_id: number | null;
  history: HistoryEntry[];
};

export type ReopenReason = {
  at: string; by: string; by_name: string | null; role: string; action: string; ref: string | null; detail: string;
  /** direct: the change is in this area; downstream: one of this area's lines is computed from it (`via`). */
  scope?: "direct" | "downstream"; via?: string | null;
};

export type SignoffLevel = {
  level: "prepared" | "reviewed" | "partner";
  label: string;
  status: "not_signed" | "signed" | "reopened";
  signoff_id: number | null;
  by: string | null;
  by_id: string | null;
  at: string | null;
  reopened_at: string | null;
  reopen_reasons: ReopenReason[];
  open_items_at_signing: number;
  signatures: number;
  can_sign: boolean;
  why_not: string[];
};

export type SignoffArea = { key: string; title: string; levels: SignoffLevel[]; open_items: string[]; complete: boolean };

export type ReadinessCheck = {
  key: string;
  label: string;
  ok: boolean;
  count: number;
  items?: { key: string; title: string; reason: string | null }[];
  areas?: { key: string; title: string; missing: string[] }[];
};

export type Readiness = { can_file: boolean; checks: ReadinessCheck[]; note: string };

export type Reopened = { signoff_id: number; area: string; level: string; reason: ReopenReason }[];
