"use client";

import { ShieldCheck, ShieldOff } from "lucide-react";
import { useApi } from "@/lib/api";
import { dateTime } from "@/lib/format";
import { Chip, ErrorState, Loading, PageHeader, Panel } from "@/components/tp/primitives";
import { AIRunLog, BudgetPanel, StandardsPanel } from "@/components/tp/ai/firm-intel";

type Firm = {
  name: string;
  identity: Record<string, unknown>;
  staff: { id: string; name: string; role_label: string; credential: string | null; sensitive_data_clearance: boolean; active_from: string; note: string | null }[];
  standards: { rules: string[]; verification_types: string[]; review_levels: string[]; variance_review: Record<string, unknown> };
  budget_hours: Record<string, number>;
};
type AuditRow = { seq: number; at: string; actor_id: string | null; actor_role: string | null; action: string; target_ref: string | null; hash: string };
type AccessRow = { id: number; at: string; user_id: string; user_role: string; field_ref: string; granted: boolean };

export default function FirmPage() {
  const { data: firm, error } = useApi<Firm>("/api/firm");
  const { data: events, error: auditErr } = useApi<AuditRow[]>("/api/audit/events?limit=50");
  const { data: chain } = useApi<{ valid: boolean; events: number }>(auditErr ? null : "/api/audit/verify");
  const { data: access, error: accessErr } = useApi<AccessRow[]>("/api/audit/access-logs");

  return (
    <div className="space-y-4">
      <PageHeader title="Firm" subtitle="Staff, firm standards, budget vs actual, AI runs, the audit trail and sensitive-data access." />
      <ErrorState error={error} />
      {firm && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Panel title={`${firm.name} staff`} dense>
            <ul className="divide-y text-[13px]">
              {firm.staff.map((s) => (
                <li key={s.id} className="flex items-center gap-3 px-4 py-2">
                  {s.sensitive_data_clearance ? <ShieldCheck className="size-4 text-emerald-600" /> : <ShieldOff className="size-4 text-amber-600" />}
                  <div className="flex-1">
                    <div className="font-medium">{s.name} <span className="text-[11px] font-normal text-muted-foreground">{s.credential}</span></div>
                    <div className="text-[11px] text-muted-foreground">{s.role_label} · since {s.active_from}{s.note ? ` · ${s.note}` : ""}</div>
                  </div>
                  <code className="text-[11px] text-slate-400">{s.id}</code>
                </li>
              ))}
            </ul>
          </Panel>
          <StandardsPanel />
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <BudgetPanel />
        <AIRunLog />
      </div>

      <Panel dense title={<span className="flex items-center gap-2">Audit trail
        {chain && (chain.valid ? <Chip tone="good">hash chain verified · {chain.events} events</Chip> : <Chip tone="bad">chain broken</Chip>)}</span>}>
        <div className="p-3"><ErrorState error={auditErr} /></div>
        {events && (
          <ul className="divide-y text-xs">
            {events.map((e) => (
              <li key={e.seq} className="grid grid-cols-[40px_170px_1fr_auto] items-center gap-3 px-4 py-1.5">
                <span className="num text-muted-foreground">#{e.seq}</span>
                <span className="num text-muted-foreground">{dateTime(e.at)}</span>
                <span><b className="font-medium">{e.action}</b> {e.target_ref && <code className="ml-1 text-slate-500">{e.target_ref}</code>} <span className="text-muted-foreground">{e.actor_id ? `by ${e.actor_id} (${e.actor_role})` : "system"}</span></span>
                <code className="text-[10px] text-slate-400" title={e.hash}>{e.hash.slice(0, 10)}</code>
              </li>
            ))}
          </ul>
        )}
        {!events && !auditErr && <div className="p-4"><Loading /></div>}
      </Panel>

      <Panel dense title="Sensitive-data access log">
        <div className="p-3"><ErrorState error={accessErr} /></div>
        {access && access.length === 0 && <div className="px-4 pb-4 text-xs text-muted-foreground">No reveals yet.</div>}
        {access && access.length > 0 && (
          <ul className="divide-y text-xs">
            {access.map((a) => (
              <li key={a.id} className="flex items-center gap-3 px-4 py-1.5">
                <span className="num w-44 text-muted-foreground">{dateTime(a.at)}</span>
                <span className="flex-1">{a.user_id} ({a.user_role}) → <code>{a.field_ref}</code></span>
                {a.granted ? <Chip tone="warn">revealed</Chip> : <Chip tone="bad">denied</Chip>}
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}
