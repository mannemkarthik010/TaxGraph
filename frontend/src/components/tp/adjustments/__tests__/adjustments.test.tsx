import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { SWRConfig } from "swr";
import type { Adjustment, WorkpaperSummary } from "@/lib/adjust-types";
import { LineDrawerProvider } from "../../schedules/common";
import { AdjustmentsTab, WorkpaperEstimate } from "../adjustments";

const summary: WorkpaperSummary = {
  version: "v3", applied_adjustments: 1, note: "Engine figures plus estimated effects — not an engine recomputation.",
  engine: { federal_total_tax: 81962, federal_balance_due: 4220, california_total_tax: 18874, california_balance_due: -8256 },
  estimated: { federal_total_tax: 82881, federal_balance_due: 5139, california_total_tax: 18954, california_balance_due: -8176 },
};

const adj = (id: number, status: Adjustment["status"]): Adjustment => ({
  id, version: "v3", target_line: id === 1 ? "SchC.44a" : "SchC.1", original_value: 11800, adjusted_value: 8100, difference: -3700,
  unit: id === 1 ? "miles" : "USD", reason: "Duplicate page", evidence_refs: [], finding_id: null, status, review_required: "reviewer",
  effect: { kind: "tax", category: "schc_profit", federal: 919, california: 80, estimate: true, basis: "" },
  created_by: "Priya Raman", created_by_id: "st-01", created_by_role: "preparer", created_at: "2026-10-15T00:00:00Z",
  approved_by: null, approved_at: null, history: [], line: { label: "Business miles", form: "SchC" },
});

let bulkCalls = 0;
beforeEach(() => {
  bulkCalls = 0;
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const u = new URL(url, "http://x");
    const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status, headers: { "Content-Type": "application/json" } });
    if (u.pathname === "/api/session/me") return json({ permissions: ["adjust"], role: "preparer" });
    if (u.pathname === "/api/adjustments/bulk" && init?.method === "POST") {
      bulkCalls += 1;
      return json({ detail: { message: "No adjustments changed: 1 of 2 cannot take 'undo'.", errors: [{ id: 2, status: 409, detail: "Cannot undo adjustment 2: it is undone." }] } }, 409);
    }
    if (u.pathname === "/api/adjustments") return json({ version: "v3", adjustments: [adj(1, "applied"), adj(2, "undone")], summary });
    return json({});
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("adjustments UI", () => {
  it("shows engine figures beside the workpaper estimate, labelled as an estimate", () => {
    render(<WorkpaperEstimate s={summary} />);
    const text = document.body.textContent ?? "";
    expect(text).toContain("Supplied engine");
    expect(text).toContain("Workpaper estimate");
    expect(text).toContain("81,962");
    expect(text).toContain("82,881");
    expect(text).toContain("+919");
    expect(text).toContain("not an engine recomputation");
  });

  it("reports which adjustment blocked an all-or-nothing bulk action", async () => {
    render(
      <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
        <LineDrawerProvider version="v3"><AdjustmentsTab /></LineDrawerProvider>
      </SWRConfig>,
    );
    fireEvent.click(await screen.findByText("All"));
    fireEvent.click(await screen.findByLabelText("Select adjustment 1"));
    fireEvent.click(screen.getByLabelText("Select adjustment 2"));
    expect(screen.getByText("2 selected:")).toBeTruthy();
    const bulkBar = screen.getByRole("group", { name: "Bulk actions" });
    await act(async () => { fireEvent.click(within(bulkBar).getByRole("button", { name: "Undo" })); });
    await waitFor(() => expect(document.body.textContent).toContain("No adjustments changed: 1 of 2 cannot take 'undo'."));
    expect(document.body.textContent).toContain("#2: Cannot undo adjustment 2: it is undone.");
    expect(bulkCalls).toBe(1);
    expect(screen.getByText("2 selected:")).toBeTruthy();       // selection kept so the user can fix it
  });

  it("shows a negative difference once, not double-bracketed", async () => {
    render(
      <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
        <LineDrawerProvider version="v3"><AdjustmentsTab /></LineDrawerProvider>
      </SWRConfig>,
    );
    await screen.findByText(/Original/);
    expect(document.body.textContent).toContain("Δ (3,700) miles");
    expect(document.body.textContent).not.toContain("((3,700))");
  });
});
