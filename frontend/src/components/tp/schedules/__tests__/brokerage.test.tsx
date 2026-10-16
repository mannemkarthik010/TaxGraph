import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { SWRConfig } from "swr";
import type { Brokerage, Lot } from "@/lib/schedule-types";
import { BrokerageView } from "../brokerage";
import { EvRef, LineDrawerProvider } from "../common";

// Two groups: a big one (60 lots → three pages) and a small one (3 lots).
const lotsFor = (doc: string, n: number): Lot[] =>
  Array.from({ length: n }, (_, i) => ({
    key: `F8949.A.${doc}${i}`, box: "A", lot: `${doc}${i}`, term: "short", description: `${doc} lot ${i}`,
    acquired: "2025-01-01", sold: "2025-02-01", proceeds: 100, basis: 50, wash_sale: 0, gain: 50 - i,
    adjustment: 0, basis_missing: false, computed_line: false, document_id: doc, broker: doc, flags: [], sources: [],
  }));
const LOTS: Record<string, Lot[]> = { D74: lotsFor("D74", 60), D31: lotsFor("D31", 3) };

const data: Brokerage = {
  version: "v1", lot_count: 63, by_term: { short: 1, long: 0 }, checks: [],
  attention: { lots: 0, basis_missing: 0, flagged: 0 },
  groups: [
    { document_id: "D74", document_title: null, broker: "Big Broker", box: "A", term: "short", lots: 60, proceeds: 0, basis: 0, gain: 0, basis_missing: 0, flagged: 0, largest_gain: null },
    { document_id: "D31", document_title: null, broker: "Small Broker", box: "A", term: "short", lots: 3, proceeds: 0, basis: 0, gain: 0, basis_missing: 0, flagged: 0, largest_gain: null },
  ],
};

const requested: URLSearchParams[] = [];

beforeEach(() => {
  requested.length = 0;
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    const p = new URL(url, "http://x").searchParams;
    requested.push(p);
    const all = (LOTS[p.get("document_id") ?? ""] ?? []).filter((l) => !p.get("q") || l.description.includes(p.get("q")!));
    const offset = Number(p.get("offset") ?? 0);
    const body = { total: all.length, offset, limit: 25, items: all.slice(offset, offset + 25) };
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function renderView() {
  return render(
    <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
      <LineDrawerProvider version="v1"><BrokerageView data={data} /></LineDrawerProvider>
    </SWRConfig>,
  );
}

describe("brokerage lots", () => {
  it("starts a newly selected group on page 1 with an empty search", async () => {
    renderView();
    fireEvent.click(screen.getByText("Big Broker"));
    await screen.findByText("D74 lot 0");

    // page forward twice and type a search in the big group
    fireEvent.click(screen.getByText("Next"));
    await screen.findByText("D74 lot 25");
    fireEvent.click(screen.getByText("Next"));
    await screen.findByText("D74 lot 50");

    // switch to the small group: it must show its lots, not an empty page 3
    await act(async () => { fireEvent.click(screen.getByText("Small Broker")); });
    await waitFor(() => expect(screen.getByText("D31 lot 0")).toBeTruthy());
    const last = requested[requested.length - 1];
    expect(last.get("document_id")).toBe("D31");
    expect(last.get("offset")).toBe("0");
    expect(last.get("q")).toBeNull();
    expect(last.get("version")).toBe("v1");
  });

  it("does not carry a search from one group into the next", async () => {
    renderView();
    fireEvent.click(screen.getByText("Big Broker"));
    await screen.findByText("D74 lot 0");
    fireEvent.change(screen.getByPlaceholderText("Filter lots…"), { target: { value: "lot 4" } });
    await screen.findByText("D74 lot 4");
    await act(async () => { fireEvent.click(screen.getByText("Small Broker")); });
    await waitFor(() => expect(screen.getByText("D31 lot 2")).toBeTruthy());
    expect((screen.getByPlaceholderText("Filter lots…") as HTMLInputElement).value).toBe("");
  });

});

describe("evidence links inside schedules", () => {
  it("carry the schedule's return version", () => {
    render(<LineDrawerProvider version="v2"><EvRef id="ev-0315" /></LineDrawerProvider>);
    expect(screen.getByText("ev-0315").closest("a")?.getAttribute("href")).toBe("/prove?ref=ev-0315&mode=down&v=v2");
  });
});
