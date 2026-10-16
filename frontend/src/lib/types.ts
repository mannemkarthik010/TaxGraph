export type Me = {
  id: string;
  name: string;
  role: string;
  role_label: string;
  kind: "staff" | "client";
  credential: string | null;
  sensitive_data_clearance: boolean;
  permissions: string[];
  can_reveal_sensitive: boolean;
};

export type UserRow = Omit<Me, "permissions" | "can_reveal_sensitive"> & {
  engagement_roles: string[];
  note: string | null;
  active_from: string | null;
};

export type Engagement = {
  id: string;
  client_id: string;
  name: string;
  tax_year: number;
  status: string;
  current_return_version: string;
  packet: {
    name: string;
    version: string;
    generated: string;
    client_id: string;
    sha256: string;
    sha256_at_engagement_creation: string;
    size_bytes: number;
    immutable: boolean;
    counts: Record<string, number>;
  };
  assignments: { user_id: string; name: string; role: string; assigned_at: string; source: string }[];
  deadlines: { what: string; date: string }[];
};

export type Person = {
  id: string;
  role: string;
  name: string;
  ssn: string | null;
  dob: string;
  occupation?: string;
  ip_pin?: string | null;
  relationship?: string;
  months_lived_with_you?: number;
  full_time_student?: boolean;
  note?: string;
  own_income?: string;
  masked_fields: string[];
};

export type Household = {
  filing_status: string;
  tax_year: number;
  entered_by: string;
  people: Person[];
  addresses: { from: string; to: string | null; address: string; type: string }[];
  residency: { state: string; from: string; to: string; status: string }[];
  bank_account_for_refund_or_payment: { routing: string; account: string; type: string; bank: string };
  prior_year_agi_for_esignature: number;
  related_returns: { who: string; return: string; prepared_by: string; in_this_packet: string | boolean }[];
};

export type Headline = {
  jurisdiction: "federal" | "california";
  field: string;
  label: string;
  value: number;
  line_key: string | null;
  prior_year: number | null;
  change: number | null;
  change_pct: number | null;
  variance_flag: boolean;
};

export type ReturnSummary = {
  version: string;
  computed_at: string;
  trigger: string;
  headlines: Headline[];
  documents_used: number;
  documents_superseded: string[];
  diagnostics: { total: number; by_severity: Record<string, number> };
  line_count: number;
  variance_standard: { percent: number; amount: number };
};

export type VersionRow = {
  version: string;
  computed_at: string;
  trigger: string;
  federal_total_tax: number;
  federal_balance_due: number;
  california_total_tax: number;
  california_balance_due: number;
  documents_used: number;
  lines: number;
  changes_from_previous: number;
  is_current: boolean;
};

export type LineGroup = { area: string; title: string; line_count: number; forms: { form: string; count: number }[] };

export type LineBrief = {
  key: string;
  version: string;
  form: string;
  line: string;
  label: string;
  value: number | string | null;
  jurisdiction: string;
  rule: string | null;
  source_count: number;
  input_count: number;
  area: string;
};

export type SourceRef = {
  ref: string;
  kind: string;
  exists: boolean;
  label: string | null;
  value: unknown;
  document_id: string | null;
  page: number | null;
  detail: Record<string, unknown>;
};

export type Diagnostic = { code: string; severity: string; message: string; refs: string[] };

export type LineDetail = LineBrief & {
  note: string | null;
  rule_description: string | null;
  inputs: { key: string; label: string | null; value: unknown }[];
  sources: SourceRef[];
  used_by: { key: string; label: string; value: unknown }[];
  values_by_version: Record<string, unknown>;
  prior_year: { key: string; value: unknown; label: string | null; source: string | null } | null;
  variance: { change: number | null; change_pct: number | null; flagged: boolean };
  engine_diagnostics: Diagnostic[];
};

export type Note = {
  id: number;
  target_ref: string;
  area_key: string | null;
  kind: "note" | "review_note";
  body: string;
  visibility: string;
  blocking: boolean;
  status: "open" | "resolved";
  author_id: string;
  author_name: string;
  author_role: string;
  created_at: string;
  resolved_by_name: string | null;
  resolved_at: string | null;
  resolution: string | null;
};

export type Area = {
  key: string;
  title: string;
  forms: string[];
  budget_hours: number | null;
  line_count: number;
  open_notes: number;
  preparer_status: string;
  reviewer_status: string;
  partner_status: string;
};

export type DocumentRow = {
  id: string;
  title: string;
  document_type: string;
  issuer: string;
  belongs_to: string;
  received_at: string;
  uploaded_by: string;
  page_count: number;
  extraction_status: string;
  extraction_reason: string | null;
  marked_corrected: boolean;
  value_count: number;
  used_in_current: boolean;
  superseded_in_current: boolean;
  used_in_versions: string[];
  statuses: DocStatus[];
  conflict_count: number;
  review_count: number;
  consumed_value_count: number;
  verified_value_count: number;
};

export type TimelineEvent = {
  id: string;
  at: string;
  event: string;
  actor: string | null;
  detail: string | null;
  refs: string[];
  is_future: boolean;
};

export type DocStatus = { code: string; label: string; detail: string };
export type EvidenceFlag = { code: string; severity: "conflict" | "review"; message: string };

export type Verification = {
  id: number;
  target_ref: string;
  method: string;
  method_label: string;
  note: string | null;
  evidence_refs: string[];
  acknowledged_flags: string[];
  verified_by_id: string;
  verified_by_name: string;
  verified_by_role: string;
  verified_at: string;
  status: "active" | "withdrawn";
  withdrawn_by_name: string | null;
  withdrawn_at: string | null;
  withdrawn_reason: string | null;
};

export type ExtractedValue = {
  id: string;
  document_id: string;
  page: number;
  field: string;
  label: string;
  value: unknown;
  value_type: string;
  text_as_read: string;
  position: { x0: number; y0: number; x1: number; y1: number };
  confidence: number;
  masked: boolean;
  span: [number, number] | null;
  flags: EvidenceFlag[];
  used_in_versions: string[];
  line_count_current: number;
  verifications?: Verification[];
};

export type DocumentDetail = {
  id: string;
  title: string;
  document_type: string;
  issuer: string;
  belongs_to: string;
  received_at: string;
  uploaded_by: string;
  file_name: string;
  page_count: number;
  extraction: { status: string; values: number; reason?: string };
  marked_corrected: boolean;
  renderer: string;
  statuses: DocStatus[];
  relations: {
    duplicates: { duplicate_of?: string; duplicated_by?: string; overlap: number }[];
    corrections: { corrected_by?: string; corrects?: string };
    duplicate_pages: { pages: [number, number]; value_overlap: number; text_similarity: number }[];
  };
  used_in_versions: string[];
  why_not_used: string | null;
  where_used: {
    version: string;
    lines: { key: string; label: string; value: unknown; via: string[] }[];
    references: { kind: string; id: string; label: string; at: string }[];
  };
  pages: { page: number; printed_content: string; extracted: boolean; values: ExtractedValue[] }[];
  verifications: Verification[];
};

export type ValueDetail = ExtractedValue & {
  document_title: string;
  where_used: {
    lines: { version: string; key: string; label: string; value: unknown }[];
    diagnostics: { version: string; code: string; severity: string; message: string }[];
    prior_year_lines: { key: string; label: string | null; value: unknown }[];
  };
};

export type GraphNode = {
  id: string;
  kind: string;
  label: string;
  value: unknown;
  meta: Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
  level: number;
  annotation: boolean;
  anchor: string | null;
  has_more: boolean;
};
export type GraphEdge = { src: string; dst: string; type: string; origin: string; detail: string | null };
export type GraphGroup = { id: string; parent: string; count: number; kinds: Record<string, number>; level: number };

export type Footprint = {
  counts: Record<string, number>;
  lines: number;
  values: number;
  documents: { id: string; title: string; pages: number[] }[];
  verified_values: number;
  verified_lines: number;
  flags: { ref: string; label: string; document_id: string; page: number; code: string; severity: string; message: string }[];
  duplicate_pages_in_evidence: { document_id: string; pages: number[] }[];
  low_confidence_values: string[];
  max_depth: number;
};

export type Impact = {
  root: string;
  version: string;
  affected_lines: number;
  by_version: Record<string, number>;
  by_area: Record<string, number>;
  headlines: { id: string; key: string; label: string; value: unknown; version: string; distance: number }[];
  rings: { distance: number; lines: { id: string; key: string; label: string; value: unknown; area: string }[] }[];
};

export type Subgraph = {
  root: string;
  direction: "up" | "down";
  nodes: GraphNode[];
  edges: GraphEdge[];
  groups: GraphGroup[];
  footprint?: Footprint;
  impact?: Impact;
};

export type NodeDetail = Omit<GraphNode, "level" | "annotation" | "anchor" | "has_more"> & {
  outgoing: (GraphEdge & { other: string; other_kind: string | null; other_label: string | null; other_value: unknown })[];
  incoming: (GraphEdge & { other: string; other_kind: string | null; other_label: string | null; other_value: unknown })[];
  outgoing_total: number;
  incoming_total: number;
};
