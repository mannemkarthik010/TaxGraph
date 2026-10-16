import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { SWRConfig } from "swr";
import type { ClientQuestion, InboxItem, Readiness, SignoffLevel } from "@/lib/collab-types";
import { UncertaintyInbox } from "../inbox";
import { LevelCell } from "../signoffs";
import { FilingReadiness } from "../readiness";
import { ClientQuestionsView } from "../client-questions";

const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { "Content-Type": "application/json" } });
const fresh = (ui: React.ReactNode) => render(<SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>{ui}</SWRConfig>);

const item = (over: Partial<InboxItem>): InboxItem => ({
  key: "finding:fx-period:SchB.1.6", source: "finding", group: "conflicts", group_label: "Conflicts", nature: "conflicts",
  nature_label: "Conflicts", title: "SchB.1.6 converted at the 2024 average rate", summary: "Wrong year's rate.", severity: "low",
  refs: ["line:v3:SchB.1.6"], areas: ["investments"], blocks_filing: false, blocking_reason: null, status: "open", handled: null,
  escalated: false, escalation_note: null, assignee_id: null, assignee: null, links: { finding_id: "fx-period:SchB.1.6", questions: [] },
  history: [], detail: {}, actions: ["resolve", "accept", "assign", "escalate"], ...over,
});

let accepted = false;
let posts: { url: string; body: unknown }[] = [];

beforeEach(() => {
  accepted = false;
  posts = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const u = new URL(url, "http://x");
    if (init?.method === "POST") posts.push({ url: u.pathname, body: JSON.parse(String(init.body ?? "{}")) });
    if (u.pathname === "/api/inbox/accept") {
      accepted = true;
      return json({});
    }
    if (u.pathname === "/api/inbox") {
      const blocker = item({ key: "diag:FORM_1099_FILING", source: "diagnostic", group: "blockers", group_label: "Filing blockers",
        nature: "judgment", nature_label: "Professional judgment", title: "Engine diagnostic FORM_1099_FILING", escalated: true,
        blocks_filing: true, blocking_reason: "Escalated to the partner: blocks filing until the partner decides.", actions: ["assign"] });
      const fx = accepted ? null : item({});
      return json({ version: "v3", totals: { open: fx ? 2 : 1, blocking: 1, handled: 0, mine: 0 }, groups: [
        { key: "blockers", label: "Filing blockers", open: 1, items: [blocker] },
        { key: "conflicts", label: "Conflicts", open: fx ? 1 : 0, items: fx ? [fx] : [] },
        { key: "missing", label: "Missing evidence", open: 0, items: [] }, { key: "judgment", label: "Professional judgment", open: 0, items: [] },
        { key: "questions", label: "Client questions", open: 0, items: [] }, { key: "review", label: "Review notes", open: 0, items: [] },
      ] });
    }
    if (u.pathname === "/api/client-questions") {
      const q: ClientQuestion = { id: 4, question: "Was Erik eligible for an employer health plan?", status: "asked", about: "Self-employed health insurance",
        asked_by: "Priya Raman", asked_at: "2026-10-15T00:00:00Z", addressed_to: "Ngozi Okafor", addressed_to_id: "cu-01", answer: null,
        answered_by: null, answered_at: null };
      return json([q]);
    }
    return json({});
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("Uncertainty Inbox", () => {
  it("puts blockers first with the reason, and records an acceptance with its explanation", async () => {
    fresh(<UncertaintyInbox />);
    expect(await screen.findByText("Filing blockers · 1 open")).toBeTruthy();
    expect(screen.getByText(/Escalated to the partner: blocks filing/)).toBeTruthy();
    expect(screen.getByText("Engine diagnostic")).toBeTruthy();          // engine output labelled as the engine's
    expect(screen.getByText("TaxProof finding")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Accept with explanation" }));
    fireEvent.change(screen.getByLabelText(/Why is it acceptable/), { target: { value: "Rate difference is immaterial." } });
    await act(async () => { fireEvent.click(screen.getAllByRole("button", { name: "Accept with explanation" }).at(-1)!); });
    expect(posts).toContainEqual({ url: "/api/inbox/accept", body: { key: "finding:fx-period:SchB.1.6", note: "Rate difference is immaterial." } });
    await waitFor(() => expect(screen.queryByText("SchB.1.6 converted at the 2024 average rate")).toBeNull());
  });
});

describe("living sign-offs", () => {
  const lv = (over: Partial<SignoffLevel>): SignoffLevel => ({
    level: "reviewed", label: "Reviewed", status: "reopened", signoff_id: 7, by: "Daniel Ortiz", by_id: "st-02", at: "2026-10-15T10:00:00Z",
    reopened_at: "2026-10-15T11:00:00Z", open_items_at_signing: 0, signatures: 1, can_sign: true, why_not: [],
    reopen_reasons: [{ at: "2026-10-15T11:00:00Z", by: "st-01", by_name: "Priya Raman", role: "preparer", action: "adjustment.apply",
      ref: "line:v3:SchC.44a", detail: "Adjustment #3 applied on SchC.44a (11,800 miles → 8,100 miles) by Priya Raman." }], ...over,
  });

  it("shows REOPENED and exactly why", () => {
    fresh(<LevelCell area="business" lv={lv({})} />);
    expect(screen.getByText("REOPENED")).toBeTruthy();
    expect(screen.getByText(/Adjustment #3 applied on SchC.44a \(11,800 miles → 8,100 miles\) by Priya Raman/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Sign again" })).toBeTruthy();
  });

  it("says when an area reopened because a calculation it rests on changed elsewhere", () => {
    fresh(<LevelCell area="california" lv={lv({ reopen_reasons: [{ at: "2026-10-15T11:00:00Z", by: "st-01", by_name: "Priya Raman",
      role: "preparer", action: "adjustment.apply", ref: "line:v3:SchC.44a", scope: "downstream", via: "SchCA540NR.3.E",
      detail: "Adjustment #3 applied on SchC.44a (11,800 miles → 8,100 miles) by Priya Raman. California is affected downstream: the change flows into SchCA540NR.3.E (Business income)." }] })} />);
    expect(screen.getByText("downstream via SchCA540NR.3.E")).toBeTruthy();
    expect(screen.getByText(/California is affected downstream/)).toBeTruthy();
  });

  it("explains why the acting user cannot sign instead of offering a button", () => {
    fresh(<LevelCell area="business" lv={lv({ status: "not_signed", by: null, reopen_reasons: [], can_sign: false,
      why_not: ["A person may not review or sign off on work they prepared (you signed this area as preparer)."] })} />);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText(/may not review or sign off on work they prepared/)).toBeTruthy();
  });
});

describe("filing readiness", () => {
  it("disables filing and names what blocks it", async () => {
    const r: Readiness = { can_file: false, note: "Client approval … (Iteration 8).", checks: [
      { key: "blocking_notes", label: "No open blocking review notes", ok: false, count: 1,
        items: [{ key: "note:3", title: "Review note on line:v3:F8606.2", reason: "Open review notes block filing (firm rule)." }] },
      { key: "escalations", label: "No escalations awaiting the partner", ok: true, count: 0, items: [] },
      { key: "signoffs", label: "Every area prepared, reviewed and partner-signed", ok: false, count: 1,
        areas: [{ key: "business", title: "Business", missing: ["Reviewed reopened"] }] },
    ] };
    vi.stubGlobal("fetch", vi.fn(async () => json(r)));
    fresh(<FilingReadiness />);
    expect(await screen.findByText("filing disabled · 2 checks failing")).toBeTruthy();
    expect(screen.getByText(/Open review notes block filing/)).toBeTruthy();
    expect(screen.getByText(/Reviewed reopened/)).toBeTruthy();
    expect(screen.getByText(/Filing is disabled while any check fails/)).toBeTruthy();
  });
});

describe("client questions (client view)", () => {
  it("shows the question without workpaper internals and sends the answer", async () => {
    fresh(<ClientQuestionsView />);
    expect(await screen.findByText("Was Erik eligible for an employer health plan?")).toBeTruthy();
    expect(document.body.textContent).not.toContain("finding:");
    fireEvent.change(screen.getByLabelText("Answer to question 4"), { target: { value: "No, he was not eligible." } });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Send answer" })); });
    expect(posts).toContainEqual({ url: "/api/client-questions/4/answer", body: { answer: "No, he was not eligible." } });
  });
});
