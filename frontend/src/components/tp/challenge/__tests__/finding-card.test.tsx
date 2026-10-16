import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { Finding } from "@/lib/schedule-types";
import { LineDrawerProvider } from "../../schedules/common";
import { FindingCard } from "../finding-card";

afterEach(cleanup);

const base: Finding = {
  id: "dup-page:D23#p3:SchC.44a", rule: "dup-page", family: "duplicate_page", family_label: "Duplicate page detection",
  subject: "D23#p3:SchC.44a", title: "D23 page 3 duplicates page 2 and both feed SchC.44a", status: "fail", severity: "high",
  summary: "Page 3 is a second scan of page 2.",
  engine: { label: "Supplied engine", value: 11800, ref: "SchC.44a" },
  independent: { label: "Unique pages only", value: 8100, method: "excluding page 3" },
  difference: -3700, unit: "miles", lines: ["SchC.44a", "SchC.9"], evidence: [], breakdown: [],
  effect: { kind: "tax", category: "schc_profit", federal: 919, california: 80, estimate: true, basis: "" },
  judgment: false, engine_diagnostics: [], partner_review: false,
};

const show = (f: Finding, onOpen = () => {}) =>
  render(<LineDrawerProvider version="v3"><FindingCard f={f} onOpen={onOpen} /></LineDrawerProvider>);

describe("FindingCard", () => {
  it("labels the finding as TaxProof's own and shows engine vs independent with units", () => {
    show(base);
    expect(screen.getByText("TAXPROOF INDEPENDENT FINDING")).toBeTruthy();
    const text = document.body.textContent ?? "";
    expect(text).toContain("Engine 11,800 miles");
    expect(text).toContain("TaxProof 8,100 miles");
    expect(text).toContain("(Δ (3,700) miles)");
    expect(text).toContain("Est. tax effect: federal +919 · California +80");
    expect(screen.getByText("engine silent")).toBeTruthy();
  });

  it("says when the engine also flagged it, and when partner review is needed", () => {
    show({ ...base, engine_diagnostics: ["BROKER_SUMMARY_DETAIL_MISMATCH"], partner_review: true });
    expect(screen.getByText("engine also flagged")).toBeTruthy();
    expect(screen.getByText(/partner review/)).toBeTruthy();
  });

  it("presents a judgment item's effect as potential, not as an error", () => {
    show({ ...base, status: "attention", judgment: true, engine: null, independent: null,
      effect: { ...base.effect!, potential: true, federal: 4464, california: 605 } });
    expect(document.body.textContent).toContain("If disallowed, est.: federal +4,464");
    expect(screen.getByText("judgment")).toBeTruthy();
  });

  it("opens the detail on click", () => {
    const onOpen = vi.fn();
    show(base, onOpen);
    fireEvent.click(screen.getByText(base.title));
    expect(onOpen).toHaveBeenCalledOnce();
  });
});
