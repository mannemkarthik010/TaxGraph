import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { SWRConfig } from "swr";
import { useApi } from "@/lib/api";
import { NotesThread } from "../notes-thread";

// A tiny server: notes live in memory; the area summary counts open notes the way the API does.
type N = { id: number; target_ref: string; kind: string; body: string; blocking: boolean; status: string };
let notes: N[] = [];

function json(body: unknown) {
  return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
}

beforeEach(() => {
  notes = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    const u = new URL(url, "http://x");
    if (u.pathname === "/api/session/me") return json({ id: "st-02", role: "reviewer", role_label: "Reviewer", permissions: ["create_note", "create_review_note", "resolve_review_note", "view_internal_notes"] });
    if (u.pathname === "/api/workpaper/notes" && init?.method === "POST") {
      const b = JSON.parse(String(init.body));
      const n = { id: notes.length + 1, target_ref: b.target_ref, kind: b.kind, body: b.body, blocking: b.kind === "review_note", status: "open",
        author_name: "Daniel", author_role: "reviewer", created_at: "2026-10-15T00:00:00Z", visibility: "internal", area_key: null, author_id: "st-02",
        resolved_by_name: null, resolved_at: null, resolution: null };
      notes.push(n);
      return json(n);
    }
    const resolve = u.pathname.match(/^\/api\/workpaper\/notes\/(\d+)\/resolve$/);
    if (resolve) {
      const n = notes.find((x) => x.id === Number(resolve[1]))!;
      n.status = "resolved";
      return json({ ...n, resolution: "done" });
    }
    if (u.pathname === "/api/workpaper/notes") return json(notes.filter((n) => n.target_ref === u.searchParams.get("target_ref")));
    if (u.pathname === "/api/workpaper/area-summaries/business") {
      const open = notes.filter((n) => n.status === "open");
      return json({ issues: { open_notes: open.length, blocking_notes: open.filter((n) => n.blocking).length } });
    }
    return json({});
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function AreaCounts() {
  const { data } = useApi<{ issues: { open_notes: number; blocking_notes: number } }>("/api/workpaper/area-summaries/business");
  return <div data-testid="counts">{data ? `open ${data.issues.open_notes} · blocking ${data.issues.blocking_notes}` : "…"}</div>;
}

describe("area counts after note edits", () => {
  it("follow a new review note and its resolution without a reload", async () => {
    render(
      <SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}>
        <AreaCounts />
        <NotesThread targetRef="area:business" />
      </SWRConfig>,
    );
    await waitFor(() => expect(screen.getByTestId("counts").textContent).toBe("open 0 · blocking 0"));

    fireEvent.click(await screen.findByText("Review note (blocks filing)"));
    fireEvent.change(screen.getByPlaceholderText("Note on area:business…"), { target: { value: "Explain the 12,400" } });
    await act(async () => { fireEvent.click(screen.getByText("Save to workpaper")); });
    await waitFor(() => expect(screen.getByTestId("counts").textContent).toBe("open 1 · blocking 1"));

    fireEvent.click(await screen.findByText("Resolve…"));
    fireEvent.change(screen.getByPlaceholderText(/How was this resolved/), { target: { value: "Agreed to D15" } });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Resolve" })); });
    await waitFor(() => expect(screen.getByTestId("counts").textContent).toBe("open 0 · blocking 0"));
  });
});
