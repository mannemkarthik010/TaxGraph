"use client";

import { Circle } from "lucide-react";
import { useApi } from "@/lib/api";
import { date } from "@/lib/format";
import type { Engagement, Me } from "@/lib/types";
import { ErrorState, Loading, PageHeader, Panel } from "@/components/tp/primitives";
import { ClientLifecycle, FilingLifecycle } from "@/components/tp/filing/lifecycle";
import { FilingReadiness } from "@/components/tp/collab/readiness";

export default function FilingPage() {
  const { data: eng } = useApi<Engagement>("/api/engagement");
  const { data: me } = useApi<Me>("/api/session/me");
  const internal = !!me?.permissions.includes("view_internal_notes");
  const { data: firm, error: firmErr } = useApi<{ standards: { required_steps: string[] } }>(internal ? "/api/firm" : null);

  return (
    <div className="space-y-4">
      <PageHeader title="Filing" subtitle="Filing lifecycle, the season replayed from the packet, the immutable filed snapshot and amendments." />
      {internal ? <FilingLifecycle /> : <ClientLifecycle />}

      {internal && (
      <div className="grid gap-4 lg:grid-cols-2">
        <FilingReadiness />
        <Panel title="Firm required steps (from starter standards)">
          {firmErr ? <ErrorState error={firmErr} /> : !firm ? <Loading /> : (
            <ul className="space-y-1 text-[13px]">
              {firm.standards.required_steps.map((s) => (
                <li key={s} className="flex items-center gap-2 text-slate-600"><Circle className="size-3 text-slate-300" />{s}</li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
      )}

      <Panel title="Deadlines">
        <ul className="grid gap-1 text-xs sm:grid-cols-2">
          {eng?.deadlines.map((d) => <li key={d.what} className="flex justify-between gap-3 rounded border px-2 py-1"><span>{d.what}</span><span className="num text-muted-foreground">{date(d.date)}</span></li>)}
        </ul>
      </Panel>
    </div>
  );
}

