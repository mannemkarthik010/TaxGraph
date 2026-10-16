import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { SWRConfig } from "swr";
import type { ExaminerItem, FilingState } from "@/lib/filing-types";
import { ClientLifecycle, FilingLifecycle, Stepper } from "../lifecycle";
import { ExaminedItem } from "../examiner";

const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { "Content-Type": "application/json" } });
const fresh = (ui: React.ReactNode) => render(<SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>{ui}</SWRConfig>);
const STATES = ["preparing", "ready_for_review", "partner_approved", "client_approved", "ready_to_file", "submitted", "rejected", "accepted", "filed", "frozen"]
  .map((k) => ({ key: k, label: k.replace(/_/g, " ") }));

const rejected: FilingState = {
  state: "rejected", label: "Rejected", states: STATES, clock: "2026-07-13T17:04:00Z", jurisdictions: {},
  history: [{ id: 9, at: "2026-07-13T17:04:00Z", kind: "replay", action: "efile_rejected", timeline_id: "tl-21", label: "E-file rejected",
    from_state: "submitted", to_state: "rejected", actor: "Priya Raman", actor_role: "preparer", note: null,
    detail: { submissions: [{ date: "2026-07-13T17:04:00Z", jurisdiction: "federal", submission_id: "71530420261940012345", status: "rejected",
      errors: [{ code: "R0000-504-02", message: "Dependent's TIN must match (dependent 2: Theo Lindqvist-Okafor)." }] }],
      linked_findings: [{ id: "identity:theo:ev-0012", title: "Theo Lindqvist-Okafor's SSN in the organizer differs from D06", status: "fail" }] } }],
  actions: [{ action: "resubmit", label: "Correct and resubmit", available: true, why_not: [], needs_note: true, needs_refs: true },
            { action: "freeze", label: "Freeze the workpaper", available: false, why_not: ["needs Filed"], needs_note: false, needs_refs: false }],
  next_event: { id: "tl-22", at: "2026-07-13T19:02:00Z", event: "document_received", label: "Document received", refs: ["D71", "msg-10"],
    detail: null, possible: true, needs: null, can_replay: true },
  upcoming: [], approval: { current: "abc", partner: "abc", client: "abc", client_matches: true }, snapshots: [],
};

let posts: { url: string; body: unknown }[] = [];
let current: FilingState = rejected;
beforeEach(() => {
  posts = [];
  current = rejected;
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const u = new URL(url, "http://x");
    if (init?.method === "POST") posts.push({ url: u.pathname, body: JSON.parse(String(init.body ?? "{}")) });
    if (u.pathname === "/api/filing/state") return json(current);
    return json({});
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("filing lifecycle", () => {
  it("shows a rejection in the lifecycle and links it to what TaxProof had already flagged", async () => {
    fresh(<FilingLifecycle />);
    expect(await screen.findByText("R0000-504-02: Dependent's TIN must match (dependent 2: Theo Lindqvist-Okafor).")).toBeTruthy();
    expect(screen.getByText("TaxProof had flagged this before filing:", { exact: false })).toBeTruthy();
    const step = document.querySelector('[aria-current="step"]');
    expect(step?.textContent).toBe("Rejected");
  });

  it("asks for the correction and its evidence before resubmitting", async () => {
    fresh(<FilingLifecycle />);
    fireEvent.click(await screen.findByRole("button", { name: "Correct and resubmit" }));
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Theo's SSN corrected to the card." } });
    fireEvent.change(screen.getByLabelText("Evidence"), { target: { value: "D71 msg-10" } });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Confirm" })); });
    expect(posts).toContainEqual({ url: "/api/filing/actions/resubmit", body: { note: "Theo's SSN corrected to the card.", evidence_refs: ["D71", "msg-10"] } });
  });

  it("replays the next scripted event, or says what it is waiting for", async () => {
    fresh(<FilingLifecycle />);
    await act(async () => { fireEvent.click(await screen.findByRole("button", { name: "Replay this event" })); });
    expect(posts.map((p) => p.url)).toContain("/api/filing/replay");
    cleanup();
    current = { ...rejected, state: "preparing", next_event: { ...rejected.next_event!, label: "Client approves and signs Forms 8879 / FTB 8879",
      possible: false, needs: "needs the partner's approval of the return (the return is Preparing)" } };
    fresh(<FilingLifecycle />);
    expect(await screen.findByText(/Waiting: needs the partner's approval/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Replay this event" })).toBeNull();
  });

  it("renders every main state", () => {
    render(<Stepper s={{ ...rejected, state: "filed" }} />);
    expect(document.querySelector('[aria-current="step"]')?.textContent).toBe("filed");
  });
});

describe("Examiner Mode", () => {
  it("shows the reported amount, its calculation, the adjustment history and what is excluded", async () => {
    const item: ExaminerItem = {
      line: { key: "SchC.1", label: "Gross receipts", form: "SchC" },
      reported: { filed_value: 151300, original_filed_value: 151300, engine_value: 163700, snapshot_id: 1, snapshot_sha256: "f".repeat(64),
                  basis: "adjustment", basis_note: "Changed by an approved workpaper adjustment.", affected_by: ["adjustment:2"] },
      calculation: { rule: "R-SCHC-GROSS", description: "Books revenue plus unmatched 1099-K amounts.", engine_note: null, inputs: [] },
      evidence: [{ ref: "D21", kind: "Document", label: "Form 1099-K Paywell", value: null }, { ref: "ev-0103", kind: "ExtractedValue", label: "Total income", value: 151300 }],
      client_answers: [], verifications: [], judgments: [],
      adjustment_history: [{ id: 2, original_value: 163700, adjusted_value: 151300, difference: -12400, unit: "USD", reason: "1099-K already in books",
        approved_by: "Helen Strand", created_by: "Priya Raman", effect: { federal: -4402, california: -384 } }],
      independent_checks: [{ id: "card-in-books:D21:SchC.1", title: "Paywell card receipts may be counted twice", status: "fail", summary: "",
        breakdown: [{ label: "Forms 1099-NEC received", value: 142000 }] }],
      filed_result: { filed_at: "2026-07-15T02:10:00Z", accepted: { federal: "2026-07-14T16:22:00Z" }, amendments: [], integrity: true },
      excluded: ["review notes"],
    };
    vi.stubGlobal("fetch", vi.fn(async () => json(item)));
    fresh(<ExaminedItem line="SchC.1" />);
    expect((await screen.findAllByText("151,300")).length).toBeGreaterThan(0);
    expect(screen.getByText(/engine computed 163,700/)).toBeTruthy();
    expect(screen.getByText(/Books revenue plus unmatched 1099-K amounts/)).toBeTruthy();
    expect(screen.getByText(/1099-K already in books/)).toBeTruthy();
    expect(screen.getByText(/Forms 1099-NEC received 142,000/)).toBeTruthy();
    expect(screen.getByText("snapshot verified")).toBeTruthy();
  });
});

describe("review follow-ups", () => {
  it("never shows an affected figure as if it were the engine's: a line that was not recomputed says so", async () => {
    const base = { line: { key: "F1040.16", label: "Tax", form: "F1040" }, evidence: [], client_answers: [], adjustment_history: [], verifications: [],
      judgments: [], independent_checks: [], excluded: [],
      calculation: { rule: "R-TAX-SCHD-WORKSHEET", description: "Tax computation", engine_note: null, inputs: [{ key: "F1040.15", label: "Taxable income", filed_value: 344300, basis: "derived" }] },
      filed_result: { filed_at: "2026-07-15T02:10:00Z", accepted: {}, amendments: [], integrity: true } };
    const item = { ...base, reported: { filed_value: 59727, original_filed_value: 59727, engine_value: 59727, snapshot_id: 1, snapshot_sha256: "a",
      basis: "not_recomputed", basis_note: "Affected by an adjustment but not recomputed: the engine's figure is shown and was NOT recomputed.",
      affected_by: ["adjustment:1"] } } as unknown as ExaminerItem;
    vi.stubGlobal("fetch", vi.fn(async () => json(item)));
    fresh(<ExaminedItem line="F1040.16" />);
    expect(await screen.findByText("NOT recomputed")).toBeTruthy();
    expect(screen.getByText(/was NOT recomputed/)).toBeTruthy();
    expect(screen.getByText("recomputed exactly")).toBeTruthy();          // its input was recomputed exactly
  });

  it("lets the client approve again after a reopen, only with explicit confirmation", async () => {
    current = { ...rejected, state: "partner_approved", awaiting_client: true, client_can_approve: true };
    fresh(<ClientLifecycle />);
    const btn = await screen.findByRole("button", { name: "Approve and sign" });
    expect((btn as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("checkbox"));
    await act(async () => { fireEvent.click(btn); });
    expect(posts).toContainEqual({ url: "/api/filing/client-approval", body: { confirm: true } });
  });
});
