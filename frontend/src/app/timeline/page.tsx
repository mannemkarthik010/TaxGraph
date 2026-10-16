"use client";

import { useApi } from "@/lib/api";
import { dateTime, humanize } from "@/lib/format";
import type { TimelineEvent } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Chip, ErrorState, FutureBanner, Loading, PageHeader, Panel } from "@/components/tp/primitives";

export default function TimelinePage() {
  const { data, error } = useApi<{ as_of: string; events: TimelineEvent[] }>("/api/timeline");
  const { data: users } = useApi<{ id: string; name: string }[]>("/api/session/users");
  const name = (id: string | null) => (id ? users?.find((u) => u.id === id)?.name ?? id : null);

  return (
    <div className="space-y-4">
      <PageHeader title="Timeline" subtitle="The engagement season as supplied by the packet. “Now” is the latest engine run (v3)." />
      <FutureBanner iteration={8}>Replay of approval, e-file rejection/acceptance, payments, refunds and the 2028 examination letter against the filing lifecycle.</FutureBanner>
      <ErrorState error={error} />
      <Panel>
        {!data ? <Loading rows={10} /> : (
          <ol className="relative ml-2 border-l">
            {data.events.map((t, i) => {
              const nowMarker = t.is_future && (i === 0 || !data.events[i - 1].is_future);
              return (
                <li key={t.id}>
                  {nowMarker && (
                    <div className="relative -ml-px mb-3 flex items-center gap-2 border-l-2 border-primary py-1 pl-4 text-xs font-semibold text-primary">
                      NOW — {dateTime(data.as_of)} (return v3). Events below are scripted for replay.
                    </div>
                  )}
                  <div className={cn("relative mb-3 pl-5", t.is_future && "opacity-55")}>
                    <span className={cn("absolute top-1.5 -left-[5px] size-2.5 rounded-full border-2 border-white",
                      t.event.startsWith("return_computed") ? "bg-primary" : t.event.includes("reject") ? "bg-rose-500" : t.event.includes("accepted") ? "bg-emerald-500" : "bg-slate-400")} />
                    <div className="flex flex-wrap items-center gap-2 text-[13px]">
                      <span className="font-medium">{humanize(t.event)}</span>
                      <span className="num text-[11px] text-muted-foreground">{dateTime(t.at)}</span>
                      {t.actor && <Chip>{name(t.actor)}</Chip>}
                      {t.refs.map((r) => <code key={r} className="rounded bg-slate-100 px-1 text-[10.5px] text-slate-600">{r}</code>)}
                    </div>
                    {t.detail && <p className="mt-0.5 text-xs text-slate-600">{t.detail}</p>}
                  </div>
                </li>
              );
            })}
          </ol>
        )}
      </Panel>
    </div>
  );
}
