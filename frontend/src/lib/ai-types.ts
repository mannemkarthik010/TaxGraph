/** Iteration 9 API shapes: AI runs, Review Risk Score, search, firm standards, budget vs actual. */

export type Claim = { text: string; refs: string[]; status: "supported" | "rejected"; problems: string[] };

export type AIRun = {
  id: number; task: string; subject: string | null; provider: string; model: string | null; is_ai: boolean;
  claims: Claim[]; supported: number; rejected: number; error: string | null;
  context: { id: string; text: string; refs: string[] }[]; context_sha256: string; created_by: string | null; created_at: string;
  question?: string | null;
};

export type RiskComponent = { key: string; label: string; points: number; max: number; reason: string; refs: string[] };
export type RiskItem = { key: string; title: string; source: string; group: string; areas: string[]; score: number;
                         level: "high" | "medium" | "low"; components: RiskComponent[]; refs: string[] };
export type RiskResponse = { items: RiskItem[]; method: string; components: { key: string; label: string; max: number }[];
                             areas: { area: string; score: number; level: string; open_items: number; high: number; reason: string }[] };

/** `semantic`: cosine similarity in the packet's LSA space; `related`: the hit's words nearest the query there. */
export type SearchHit = { ref: string; kind: string; title: string; snippet: string; score: number; matched: string[];
  semantic?: number; related?: string[]; link: string | null };
export type SearchResponse = {
  query: string; terms: string[]; expanded_with: string[]; associated?: { term: string; weight: number }[]; results: SearchHit[]; method: string;
  answer: { intent: string; title: string; text: string; source: string; items: { ref: string; title: string; detail: string; link: string }[] } | null;
};

export type Standards = {
  variance_review: { compare_to?: string; flag_if_change_over_percent: number; and_over_amount: number };
  partner_threshold: number; verification_types: string[]; review_levels: string[]; rules: string[]; required_steps: string[];
};
export type StandardsResponse = { version: number; standards: Standards; known_methods: string[];
                                  history: { version: number; note: string; by: string | null; at: string | null }[] };

export type Budget = {
  lines: { budget_key: string; label: string; budget: number; actual: number; remaining: number; used_pct: number | null; over: boolean;
           by_person: Record<string, number> }[];
  total: { budget: number; actual: number; remaining: number; over: boolean };
  entries: { id: number; who: string; budget_key: string; hours: number; worked_on: string; note: string | null }[];
};
