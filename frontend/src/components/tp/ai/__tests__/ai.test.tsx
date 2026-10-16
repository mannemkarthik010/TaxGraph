import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { SWRConfig } from "swr";
import type { AIRun, Budget, RiskResponse } from "@/lib/ai-types";
import { Claims } from "../claims";
import { ExplainFinding, RiskBoard } from "../reviewer";
import { BudgetPanel } from "../firm-intel";

const json = (b: unknown) => new Response(JSON.stringify(b), { status: 200, headers: { "Content-Type": "application/json" } });
const fresh = (ui: React.ReactNode) => render(<SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>{ui}</SWRConfig>);

const run: AIRun = {
  id: 1, task: "explain_finding", subject: "finding:dup-page:D23#p3:SchC.44a", provider: "grounded_template", model: null, is_ai: false,
  supported: 1, rejected: 1, error: null, context: [], context_sha256: "abc123def4567890", created_by: "Daniel Ortiz", created_at: "2026-10-15T00:00:00Z",
  claims: [
    { text: "D23 page 3 duplicates page 2: 3,700 miles counted twice.", refs: ["doc:D23#page3", "line:v3:SchC.44a"], status: "supported", problems: [] },
    { text: "Mileage is overstated by 4,100 miles.", refs: ["doc:D23#page3"], status: "rejected", problems: ["number(s) not in the cited evidence: 4,100"] },
  ],
};

let posts: string[] = [];
let bodies: unknown[] = [];
beforeEach(() => {
  posts = [];
  bodies = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const u = new URL(url, "http://x");
    if (init?.method === "POST") { posts.push(u.pathname); bodies.push(JSON.parse(String(init.body ?? "{}"))); }
    if (u.pathname === "/api/ai/explain") return json(run);
    if (u.pathname === "/api/session/me") return json({ permissions: ["create_note"], role: "preparer" });
    if (u.pathname === "/api/review/risk") {
      const r: RiskResponse = { method: "Sum of named components", components: [], areas: [{ area: "business", score: 80, level: "high", open_items: 4, high: 3, reason: "Highest item" }],
        items: [{ key: "finding:card-in-books:D21:SchC.1", title: "Paywell card receipts may be counted twice", source: "finding", group: "conflicts",
          areas: ["business"], score: 80, level: "high", refs: [], components: [
            { key: "material_tax_impact", label: "Material tax impact", points: 25, max: 25, reason: "Estimated effect up to 4,402 (partner threshold 1,000).", refs: ["line:v3:SchC.1"] },
            { key: "duplicate_evidence", label: "Duplicate evidence", points: 20, max: 20, reason: "Card receipts may be counted twice.", refs: ["D21"] }] }] };
      return json(r);
    }
    if (u.pathname === "/api/time/budget") {
      const b: Budget = { total: { budget: 22, actual: 4, remaining: 18, over: false }, entries: [],
        lines: [{ budget_key: "business", label: "Business", budget: 3.5, actual: 4, remaining: -0.5, used_pct: 114, over: true, by_person: { "Priya Raman": 2.5 } }] };
      return json(b);
    }
    return json({});
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("AI output", () => {
  it("shows grounded claims with their evidence, and rejected claims apart with the reason", () => {
    fresh(<Claims run={run} />);
    expect(screen.getByText(/3,700 miles counted twice/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "doc:D23#page3" }).getAttribute("href")).toBe("/evidence?doc=D23&page=3");
    expect(screen.getByRole("link", { name: "line:v3:SchC.44a" }).getAttribute("href")).toBe("/return?line=SchC.44a&v=v3");
    expect(screen.getByText(/Rejected — not supported by the evidence/)).toBeTruthy();
    expect(screen.getByText(/not in the cited evidence: 4,100/)).toBeTruthy();
    expect(screen.getByText(/deterministic — no AI model/)).toBeTruthy();         // never passes itself off as AI
  });

  it("explains a finding on request", async () => {
    fresh(<ExplainFinding findingId="ca-wages:SchCA540NR.1.E" version="v1" />);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: /Explain this finding/ })); });
    expect(posts).toContain("/api/ai/explain");
    expect(bodies.at(-1)).toEqual({ finding_id: "ca-wages:SchCA540NR.1.E", version: "v1" });     // the version on screen
    expect(await screen.findByText(/3,700 miles counted twice/)).toBeTruthy();
  });
});

describe("Review Risk Score", () => {
  it("shows the score and, on demand, every component with its reason", async () => {
    fresh(<RiskBoard />);
    expect(await screen.findByText("Paywell card receipts may be counted twice")).toBeTruthy();
    fireEvent.click(screen.getByText("Paywell card receipts may be counted twice"));
    expect(screen.getByText(/Estimated effect up to 4,402/)).toBeTruthy();
    expect(screen.getByText("25/25")).toBeTruthy();
  });
});

describe("budget vs actual", () => {
  it("flags a line that is over budget", async () => {
    fresh(<BudgetPanel />);
    expect(await screen.findByText(/4 \/ 3.5 h — over budget/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Log time" })).toBeTruthy();
  });
});
