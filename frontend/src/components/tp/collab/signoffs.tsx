"use client";

import { useState } from "react";
import Link from "next/link";
import { CheckCircle2, Circle, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ApiError, useApi, useMutate } from "@/lib/api";
import type { SignoffArea, SignoffLevel } from "@/lib/collab-types";
import type { Me } from "@/lib/types";
import { dateTime } from "@/lib/format";
import { useRefreshAfter } from "@/lib/refresh";
import { cn } from "@/lib/utils";
import { Chip, ErrorState, Loading, Panel } from "../primitives";

const ICON = { signed: CheckCircle2, reopened: RotateCcw, not_signed: Circle } as const;
const TONE = { signed: "text-emerald-600", reopened: "text-rose-600", not_signed: "text-slate-300" } as const;

/** One level (Prepared / Reviewed / Partner): status, who, when — and exactly why it reopened. */
export function LevelCell({ area, lv, onSigned }: { area: string; lv: SignoffLevel; onSigned?: () => void }) {
  const mutate = useMutate();
  const refreshAfter = useRefreshAfter();
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const Icon = ICON[lv.status];
  const last = lv.reopen_reasons[lv.reopen_reasons.length - 1];
  const signNow = async () => {
    setErr(null);
    setBusy(true);
    try {
      await mutate("/api/signoffs", { area_key: area, level: lv.level });
      refreshAfter("collab");
      onSigned?.();
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : "Failed");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className={cn("rounded-md border px-2.5 py-2 text-xs", lv.status === "reopened" && "border-rose-200 bg-rose-50/50")}
         data-testid={`signoff-${area}-${lv.level}`}>
      <div className="flex items-center gap-1.5">
        <Icon className={cn("size-4", TONE[lv.status])} />
        <span className="font-medium text-slate-800">{lv.label}</span>
        {lv.status === "reopened" && <Chip tone="bad">REOPENED</Chip>}
        {lv.status === "signed" && lv.open_items_at_signing > 0 && (
          <Chip tone="warn" title="Open inbox items in this area when it was signed">{lv.open_items_at_signing} open at signing</Chip>
        )}
      </div>
      {lv.by && (
        <div className="mt-0.5 text-[11px] text-muted-foreground">
          {lv.status === "reopened" ? "was signed by " : ""}{lv.by} · {dateTime(lv.at)}
        </div>
      )}
      {lv.status === "reopened" && last && (
        <div className="mt-1 rounded bg-white/80 px-1.5 py-1 text-[11px] text-rose-900">
          <b className="font-medium">Why:</b> {last.scope === "downstream" && <Chip tone="warn" className="mr-1">downstream via {last.via}</Chip>}{last.detail}
          <div className="text-[10.5px] text-rose-700/80">{dateTime(last.at)}{lv.reopen_reasons.length > 1 && ` · ${lv.reopen_reasons.length} changes since signing`}</div>
        </div>
      )}
      {lv.status !== "signed" && (
        lv.can_sign ? (
          <Button size="sm" variant="outline" className="mt-1.5 h-7 w-full text-xs" disabled={busy} onClick={signNow}>
            {lv.status === "reopened" ? "Sign again" : `Sign ${lv.label.toLowerCase()}`}
          </Button>
        ) : lv.why_not.length > 0 && (
          <ul className="mt-1 list-disc pl-4 text-[10.5px] text-muted-foreground">{lv.why_not.map((w) => <li key={w}>{w}</li>)}</ul>
        )
      )}
      {err && <p className="mt-1 text-[11px] text-rose-700">{err}</p>}
    </div>
  );
}

/** Sign-offs for one area (used on the area page). */
export function AreaSignoffs({ areaKey }: { areaKey: string }) {
  const { data: me } = useApi<Me>("/api/session/me");
  const internal = !!me?.permissions.includes("view_internal_notes");
  const { data, error, mutate: reload } = useApi<{ areas: SignoffArea[] }>(internal ? "/api/signoffs" : null);
  if (!internal) return null;
  const a = data?.areas.find((x) => x.key === areaKey);
  return (
    <Panel title="Sign-offs" actions={<Link href="/review?tab=signoffs" className="text-xs text-sky-700 hover:underline">All areas</Link>}>
      <ErrorState error={error} />
      {!data ? <Loading rows={2} /> : !a ? null : (
        <>
          <div className="grid gap-2 sm:grid-cols-3">{a.levels.map((lv) => <LevelCell key={lv.level} area={a.key} lv={lv} onSigned={reload} />)}</div>
          <p className="mt-2 text-[11px] text-muted-foreground">
            A sign-off attests to the area as it stood. Applying, undoing or restoring an adjustment, recording or revising a judgment,
            accepting a client answer, withdrawing a verification or changing an evidence link reopens the reviewed and partner
            sign-offs of this area — and of every area whose lines are computed from what changed.
            {a.open_items.length > 0 && <> {a.open_items.length} open inbox item{a.open_items.length === 1 ? "" : "s"} in this area.</>}
          </p>
        </>
      )}
    </Panel>
  );
}

/** Every area × level. */
export function SignoffBoard() {
  const { data, error, mutate: reload } = useApi<{ areas: SignoffArea[] }>("/api/signoffs");
  if (error) return <ErrorState error={error} />;
  if (!data) return <Loading />;
  const done = data.areas.filter((a) => a.complete).length;
  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">
        {done} of {data.areas.length} areas fully signed. Order: prepared → reviewed → partner. Nobody reviews work they prepared;
        open blocking review notes stop the review sign-off; adjustments and judgments over 1,000 need partner approval before the partner signs.
      </p>
      <div className="overflow-hidden rounded-lg border bg-card">
        <table className="w-full text-[13px]">
          <thead className="bg-slate-50 text-left text-[10.5px] uppercase tracking-wide text-muted-foreground">
            <tr><th className="px-3 py-2 font-medium">Area</th><th className="px-2 font-medium">Prepared</th><th className="px-2 font-medium">Reviewed</th>
              <th className="px-2 font-medium">Partner</th></tr>
          </thead>
          <tbody>
            {data.areas.map((a) => (
              <tr key={a.key} className="border-t align-top">
                <td className="px-3 py-2">
                  <Link href={`/return/area/${a.key}`} className="font-medium text-slate-800 hover:underline">{a.title}</Link>
                  <div className="text-[11px] text-muted-foreground">{a.open_items.length} open item{a.open_items.length === 1 ? "" : "s"}</div>
                </td>
                {a.levels.map((lv) => <td key={lv.level} className="w-[28%] px-2 py-2"><LevelCell area={a.key} lv={lv} onSigned={reload} /></td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
