import type { Effect } from "./schedule-types";

export type AdjustmentEffect = Effect | { kind: "none"; federal: number; california: number; estimate: boolean; basis: string; category: null };

export type Adjustment = {
  id: number; version: string; target_line: string; original_value: number; adjusted_value: number; difference: number;
  unit: string; reason: string; evidence_refs: string[]; finding_id: string | null;
  status: "proposed" | "applied" | "undone"; review_required: "reviewer" | "partner"; effect: AdjustmentEffect;
  created_by: string; created_by_id: string; created_by_role: string; created_at: string;
  approved_by: string | null; approved_at: string | null;
  history: { action: string; by: string; by_name: string; role: string; at: string; note: string | null }[];
  line: { label: string; form: string } | null;
};

export type WorkpaperSummary = {
  version: string; applied_adjustments: number; note: string;
  engine: Record<"federal_total_tax" | "federal_balance_due" | "california_total_tax" | "california_balance_due", number>;
  estimated: Record<"federal_total_tax" | "federal_balance_due" | "california_total_tax" | "california_balance_due", number>;
};

export type Effective = { version: string; key: string; engine_value: number; effective_value: number; adjusted: boolean; adjustments: Adjustment[] };

export type LineChange = { key: string; change: "added" | "removed" | "changed"; label: string; form: string; area: string; old: unknown; new: unknown; delta: number | null };
export type TimeMachine = {
  from: { version: string; computed_at: string; trigger: string }; to: { version: string; computed_at: string; trigger: string };
  summary: Record<"federal" | "california", { field: string; from: number; to: number; change: number | null }[]>;
  tax_change: { federal: number; california: number };
  lines: { total: number; by_area: Record<string, Record<string, number>>; changes: LineChange[] };
  drivers: (LineChange & { new_sources: string[]; new_source_documents: string[]; lost_sources: string[] })[];
  documents: Record<"now_used" | "no_longer_used" | "newly_superseded" | "no_longer_superseded", { id: string; title: string; received_at: string }[]>;
  diagnostics: { added: { code: string; message: string }[]; removed: { code: string; message: string }[]; changed: { code: string; from: string; to: string }[] };
  why: { triggers: { version: string; computed_at: string; trigger: string }[]; timeline: { id: string; at: string; event: string; refs: string[]; detail: string | null }[];
    documents_received: { id: string; title: string; received_at: string }[] };
  consistency_with_engine: { agrees: boolean; packet_changes: number; computed_changes: number } | null;
};

export type WhatIf = {
  note: string;
  alternatives: {
    id: string; description: string; base_version: string; choices: Record<string, string>; source: string;
    federal: { base: Record<string, number>; alternative: Record<string, number>; total_tax_change: number; penalty_change?: number };
    california: { base: Record<string, number>; alternative: Record<string, number>; total_tax_change: number; penalty_change?: number };
    changed_lines: { key: string; change: string; old?: unknown; new?: unknown; label: string | null; area: string | null }[];
    related_findings: { id: string; title: string; status: string }[];
  }[];
  extension: { computed_at: string; based_on_version: string; federal: Record<string, unknown>; california: Record<string, unknown> } | null;
};
