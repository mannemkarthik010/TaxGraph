import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { SWRConfig } from "swr";
import type { Blocker, TrustReport, Twin } from "@/lib/twin-types";
import { AssuranceTwin, PreventFiling } from "../dashboard";
import TrustPage from "@/app/trust/page";

const json = (b: unknown) => new Response(JSON.stringify(b), { status: 200, headers: { "Content-Type": "application/json" } });
const fresh = (ui: React.ReactNode) => render(<SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>{ui}</SWRConfig>);

const assurance = {
  score: 48, level: "weak" as const, method: "Weighted sum; not a probability.",
  components: [
    { key: "documents", label: "Documents accounted for", weight: 10, ratio: 1, points: 10, reason: "74 of 74 documents used, superseded or not used for a recorded reason.", link: "/evidence" },
    { key: "review", label: "Areas reviewed", weight: 10, ratio: 0, points: 0, reason: "0 of 11 areas reviewed.", link: "/review?tab=signoffs" },
  ],
};
const blockers: Blocker[] = [
  { kind: "gate", key: "signoffs", label: "Every area prepared, reviewed and partner-signed", count: 11, items: ["Business: Reviewed reopened"], link: "/review?tab=signoffs" },
  { kind: "lifecycle", key: "Partner approval", label: "Partner approval", count: 1, items: ["The return is Preparing."], link: "/filing" },
];
const twin = {
  version: "v3", engine: { federal: { total_tax: 81962 }, california: { total_tax: 18874 } },
  workpaper: { applied_adjustments: 0, estimated: {}, note: "" }, filed: null,
  lifecycle: { state: "preparing", label: "Preparing", client_authorized: false, awaiting_client: false, jurisdictions: {} },
  assurance, documents: { total: 74, accounted: 74, issues: [], not_used: [] }, traceability: { material: 274, traceable: 272, threshold: 1000 },
  coverage: { values: 900, verified: 0, flagged: 10, flagged_verified: 0 },
  checks: { total: 61, passed: 39, failed: 14, attention: 8, dispositioned: 0, open: [{ id: "x", title: "x", status: "fail" }] },
  judgments: { items: 4, decided: 0, recorded: 0, approved: 0 },
  signoffs: { areas: 11, prepared: 0, reviewed: 0, partner: 0, complete: 0, reopened: [] },
  what_prevents_filing: blockers, can_file_now: false,
  critical: [{ key: "finding:card-in-books:D21:SchC.1", title: "Paywell card receipts may be counted twice", score: 80, areas: ["business"],
    components: [{ label: "Material tax impact", points: 25 }] }],
  critical_count: 10,
  inbox: { open: 25, blocking: 0 },
  since: { seen_at: "2026-10-15T10:00:00Z", first_visit: false, groups: [{ label: "Adjustments", count: 2 }],
    events: [{ seq: 9, at: "2026-10-15T11:00:00Z", action: "adjustment.apply", by: "Priya Raman", target_ref: "line:v3:SchC.44a" }] },
} as unknown as Twin;
const report: TrustReport = {
  generated_at: "2026-10-15T12:00:00Z", version: "v3", report_sha256: "abc123def456aaaa", verdict: "2 thing(s) prevent filing — listed exactly below.",
  closing: "Traditional workpapers document what the preparer did. TaxProof continuously proves why the filed return should be trusted.",
  lifecycle: twin.lifecycle, assurance, what_prevents_filing: blockers,
  sections: [{ key: "documents", question: "Are all documents accounted for?", answer: "74 of 74", status: "good", detail: "71 used.", items: [], link: "/evidence" },
             { key: "review", question: "Is the review complete?", answer: "0 of 11 areas reviewed", status: "bad", detail: "Active reviewed sign-offs.", items: [], link: "/review" }],
};

let posts: string[] = [];
beforeEach(() => {
  posts = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const u = new URL(url, "http://x");
    if (init?.method === "POST") posts.push(u.pathname);
    if (u.pathname === "/api/twin") return json(twin);
    if (u.pathname === "/api/twin/trust") return json(report);
    if (u.pathname === "/api/twin/trust/summary") return json({ id: 1, task: "trust_summary", provider: "grounded_template", model: null, is_ai: false,
      supported: 1, rejected: 0, error: null, context: [], context_sha256: "0123456789abcdef", created_by: "Helen", created_at: "2026-10-15T12:00:00Z",
      claims: [{ text: "Are all documents accounted for? 74 of 74.", refs: ["twin:documents"], status: "supported", problems: [] }] });
    return json({});
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("Return Assurance Twin dashboard", () => {
  it("shows the score with its components, what prevents filing, critical issues and changes since last look", async () => {
    fresh(<AssuranceTwin />);
    expect(await screen.findByRole("img", { name: "Return assurance score 48 of 100" })).toBeTruthy();
    expect(screen.getByText("Documents accounted for")).toBeTruthy();
    expect(screen.getByText("10/10")).toBeTruthy();
    expect(screen.getByText("Every area prepared, reviewed and partner-signed")).toBeTruthy();
    expect(screen.getByText("Paywell card receipts may be counted twice")).toBeTruthy();
    expect(screen.getByText("Critical issues (highest review risk) · 10")).toBeTruthy();   // every high-risk item, not just those listed
    expect(screen.getByRole("link", { name: "all 10 →" })).toBeTruthy();
    expect(screen.getByText("2 Adjustments")).toBeTruthy();
    expect(screen.getByRole("link", { name: /Why should I trust this return/ })).toBeTruthy();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Mark as seen" })); });
    expect(posts).toContain("/api/twin/seen");
  });

  it("says plainly when nothing prevents filing", () => {
    render(<PreventFiling blockers={[]} />);
    expect(screen.getByText("Nothing prevents filing.")).toBeTruthy();
  });
});

describe("Why should I trust this return?", () => {
  it("answers each question, lists the blockers, ends with the closing statement and summarizes on request", async () => {
    fresh(<TrustPage />);
    expect(await screen.findByText("2 thing(s) prevent filing — listed exactly below.")).toBeTruthy();
    expect(screen.getByText("Are all documents accounted for?")).toBeTruthy();
    expect(screen.getByText("0 of 11 areas reviewed")).toBeTruthy();
    expect(screen.getByText("Business: Reviewed reopened")).toBeTruthy();
    expect(screen.getByText(/TaxProof continuously proves why the filed return should be trusted/)).toBeTruthy();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Summarize" })); });
    expect(posts).toContain("/api/twin/trust/summary");
    expect(await screen.findByText("Are all documents accounted for? 74 of 74.")).toBeTruthy();
  });
});
