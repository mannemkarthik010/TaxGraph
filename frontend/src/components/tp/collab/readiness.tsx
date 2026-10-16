"use client";

import Link from "next/link";
import { CheckCircle2, OctagonAlert, XCircle } from "lucide-react";
import { useApi } from "@/lib/api";
import type { Readiness } from "@/lib/collab-types";
import { Chip, ErrorState, Loading, Panel } from "../primitives";

/** What prevents filing — deterministic checks, each naming exactly what fails. */
export function FilingReadiness() {
  const { data, error } = useApi<Readiness>("/api/filing/readiness");
  const failing = data?.checks.filter((c) => !c.ok).length ?? 0;
  return (
    <Panel title={<span className="flex items-center gap-1.5"><OctagonAlert className="size-4 text-rose-600" />What prevents filing</span>}
      actions={data && (data.can_file ? <Chip tone="good">ready for the filing steps</Chip> : <Chip tone="bad">filing disabled · {failing} check{failing === 1 ? "" : "s"} failing</Chip>)}>
      <ErrorState error={error} />
      {!data ? <Loading /> : (
        <div className="space-y-2">
          <ul className="space-y-2 text-[13px]">
            {data.checks.map((c) => (
              <li key={c.key} data-testid={`check-${c.key}`}>
                <div className="flex items-center gap-2">
                  {c.ok ? <CheckCircle2 className="size-4 text-emerald-600" /> : <XCircle className="size-4 text-rose-600" />}
                  <span className={c.ok ? "text-slate-600" : "font-medium text-slate-900"}>{c.label}</span>
                  {!c.ok && <Chip tone="bad">{c.count}</Chip>}
                </div>
                {!c.ok && c.items && (
                  <ul className="ml-6 mt-0.5 space-y-0.5 text-xs text-slate-600">
                    {c.items.slice(0, 6).map((i) => <li key={i.key}>{i.title}{i.reason && <span className="text-rose-700"> — {i.reason}</span>}</li>)}
                    {c.items.length > 6 && <li className="text-muted-foreground">… {c.items.length - 6} more in the <Link className="text-sky-700 hover:underline" href="/review">Uncertainty Inbox</Link></li>}
                  </ul>
                )}
                {!c.ok && c.areas && (
                  <ul className="ml-6 mt-0.5 space-y-0.5 text-xs text-slate-600">
                    {c.areas.map((a) => <li key={a.key}><Link href={`/return/area/${a.key}`} className="hover:underline">{a.title}</Link>: {a.missing.join(", ")}</li>)}
                  </ul>
                )}
              </li>
            ))}
          </ul>
          <p className="border-t pt-2 text-[11px] text-muted-foreground">
            {data.can_file ? "All workpaper gates pass. " : "Filing is disabled while any check fails. "}
            Partner approval, ready-to-file and every submission re-check these gates on the server.
          </p>
        </div>
      )}
    </Panel>
  );
}
