export type Check = {
  check: string;
  taxproof: number;
  engine: number;
  difference: number;
  agrees: boolean;
  refs: string[];
  detail: string;
};

export type AreaFigure = {
  key: string; label: string; value: number | string; prior_year: number | string | null;
  change: number | null; change_pct: number | null; variance_flag: boolean;
};

export type AreaSummary = {
  key: string;
  title: string;
  forms: string[];
  figures: AreaFigure[];
  line_count: number;
  traceable_lines: number;
  evidence: { documents: string[]; values: number; verified_values: number; verified_lines: number; coverage: number | null; traceability: number | null };
  issues: { open_notes: number; blocking_notes: number; conflicts: number; needs_review: number; engine_diagnostics: number; variances: number };
  diagnostics: { code: string; severity: string; message: string }[];
  status: { preparer: string; reviewer: string; partner: string; preparer_name: string | null; reviewer_name: string | null };
  budget_hours: number | null;
  schedules: string[];
};

export type AreaDetail = AreaSummary & {
  version: string;
  open_notes: { id: number; target_ref: string; kind: string; body: string; blocking: boolean; author_name: string | null; created_at: string; via: "area" | "line" | "evidence" }[];
  lines_preview: { key: string; label: string; value: unknown }[];
  lots_hidden: number;
};

export type TaxRow = { key: string; line: string; label: string; value: number | string; prior_year: number | null; prior_year_key: string | null; change: number | null; variance_flag: boolean; rule: string | null; note: string | null };
export type TaxComputation = { version: string; federal: TaxRow[]; california: TaxRow[] };

export type PriorYear = {
  version: string;
  standard: { percent: number; amount: number };
  rows: { key: string; prior_year_key: string; label: string; area: string; value: number | string; prior_year: number | string; prior_source: string | null; change: number | null; change_pct: number | null; variance_flag: boolean }[];
  flagged: number;
  only_prior_year: { key: string; label: string | null; prior_year: unknown; source: string | null }[];
  new_this_year: { count: number; by_area: Record<string, number> };
};

export type BridgeRow = { kind: "income" | "expense" | "removed"; key: string | null; label: string; books: number; tax: number; effect: number; books_refs: string[]; note: string | null; unchanged?: boolean; used_elsewhere?: { version: string; key: string }[] };
export type BooksToTax = { version: string; books_documents: string[]; start: { label: string; value: number; ref: string | null }; rows: BridgeRow[]; end: { label: string; value: number; key: string }; checks: Check[] };

export type Asset = {
  asset_id: string; description: string; activity: string; cost: number | null; land: number | null; placed_in_service: string;
  method: string; life_years: number | null;
  federal: { prior_accumulated: number; depreciation_2025: number; accumulated_end: number };
  california: { prior_accumulated: number; depreciation_2025: number; accumulated_end: number };
  amt: { depreciation_2025: number; difference_from_regular: number };
  federal_vs_california: number; disposed: string | null;
  disposition: { date: string; unrecaptured_1250_depreciation?: number; section_1250_ordinary_recapture?: number; sold_with?: string } | null;
  new_in_year: boolean; continuity_agrees: boolean | null; refs: string[];
};
export type Depreciation = { version: string; assets: Asset[]; by_activity: Record<string, { federal: number; california: number; amt: number }>; checks: Check[]; california_basis_differences: Record<string, number> };

export type BrokerGroup = { document_id: string | null; document_title: string | null; broker: string; box: string; term: string; lots: number; proceeds: number; basis: number; gain: number; basis_missing: number; flagged: number; largest_gain: { key: string; description: string; gain: number } | null };
export type Brokerage = { version: string; lot_count: number; groups: BrokerGroup[]; by_term: { short: number; long: number }; checks: Check[]; attention: { lots: number; basis_missing: number; flagged: number } };
export type Lot = { key: string; box: string; lot: string; term: string; description: string; acquired: string | null; sold: string | null; proceeds: number | null; basis: number | null; wash_sale: number | null; gain: number; adjustment: number | null; basis_missing: boolean; computed_line: boolean; document_id: string | null; broker: string; flags: { code: string; severity: string; message: string; ref: string }[]; sources: string[] };

export type Property = {
  letter: string; address: string; days: string | null; rents: number | null; rents_key: string;
  expenses: { key: string; label: string; value: number; prior_year: number | null }[];
  total_expenses: number | null; net: number | null; allowed: number | null;
  assets: { asset_id: string; description: string; federal: number; disposed: string | null }[];
  disposed: string | null; prior_year_net: number | null;
};
export type Rentals = { version: string; properties: Property[]; passive_activity: { key: string; label: string; value: number }[]; sale: { key: string; label: string; value: number | string }[]; suspended_losses: { into_year: Record<string, number>; out_of_year: Record<string, number> }; checks: Check[]; total: number };

export type K1Basis = {
  version: string;
  k1s: { document_id: string; title: string; type: string; tax_year: number; received_at: string; received_after_version: boolean; used_in_versions: string[]; items: { ref: string; field: string; label: string; value: unknown; value_type: string; lines: string[] }[] }[];
  scorp_basis: { year: number; beginning: number | null; income: number | null; distributions: number | null; ending: number | null; excess_distribution: number; refs: string[]; source: string; gap: boolean }[];
  checks: Check[];
  gap: { year: number; last_known: { year: number; ending: number } | null; engine_beginning: number | null; detail: string } | null;
  partnership: { records: Record<string, unknown>[]; capital_account_end: number | null; outside_basis_known: boolean };
  form7203: { key: string; label: string; value: number }[];
};

export type Residency = {
  year: number; days_in_year: number;
  periods: { state: string; from: string; to: string; status: string; days: number }[];
  events: { date: string | null; kind: string; label: string; ref: string; document_id?: string; state?: string | null }[];
  checks: Check[];
};
export type StateAllocation = {
  version: string;
  rows: { line: string; label: string; columns: Record<string, number>; keys: Record<string, string>; notes: string[]; california_share: number | null }[];
  form540nr: { key: string; line: string; label: string; value: number | string }[];
  checks: Check[];
  residency: Residency;
};

export type Carryovers = {
  version: string;
  rows: { item: string; into_year: number | null; into_ref: string | null; used_by: { key: string; label: string; value: unknown }[]; out_of_year: number | null; california_into: number | null; status: string }[];
  california_out: Record<string, unknown>; california_note: string | null; source: string | null;
};

export type Effect = {
  kind: "tax" | "balance"; category: string; ca_category?: string; federal: number; california: number;
  federal_rate?: number; california_rate?: number; estimate: boolean; basis: string; potential?: boolean;
};

export type Finding = {
  id: string; rule: string; family: string; family_label: string; subject: string; title: string;
  status: "fail" | "attention" | "explained" | "pass"; severity: "critical" | "high" | "medium" | "low" | "info";
  summary: string;
  engine: { label: string; value: number; ref: string | null } | null;
  independent: { label: string; value: number; method: string } | null;
  difference: number | null; unit: string; lines: string[]; evidence: string[];
  breakdown: Record<string, unknown>[]; effect: Effect | null; judgment: boolean; engine_diagnostics: string[];
  partner_review: boolean;
};

export type FindingDetail = Finding & {
  version: string;
  evidence_resolved: { ref: string; kind: string; exists: boolean; label: string | null; value: unknown; document_id: string | null; page: number | null }[];
  lines_resolved: { key: string; label: string; value: unknown }[];
  impact: { affected_lines: number; headlines: { key: string; label: string; value: unknown; distance: number }[] } | null;
};

export type ChallengeOverview = {
  summary: {
    version: string; checks: number; by_status: Record<string, number>;
    families: Record<string, { label: string; fail?: number; attention?: number; pass?: number; explained?: number }>;
    estimated_effect: {
      tax: { federal: number; california: number; findings: number; note: string };
      balance: { federal: number; california: number; findings: number; note: string };
    };
    engine: { diagnostics: number; summary: { federal: Record<string, number>; california: Record<string, number> } };
  };
  findings: Finding[];
  engine_diagnostics: { code: string; severity: string; message: string; refs: string[]; related_findings: string[] }[];
  last_run: { id: number; run_at: string; run_by: string; run_by_role: string } | null;
  changes_since_last_run: {
    since_run: number | null; new: string[]; gone: string[]; changed: string[];
    changed_detail: Record<string, Record<string, [unknown, unknown]>>;
  };
};
