"use client";

import { useState } from "react";
import { Eye, Lock, ShieldAlert, Sparkles } from "lucide-react";
import { cn } from "@/lib/utils";
import { useMutate, ApiError } from "@/lib/api";
import { money } from "@/lib/format";

type Tone = "neutral" | "good" | "warn" | "bad" | "info" | "muted" | "engine";

const TONES: Record<Tone, string> = {
  neutral: "bg-slate-100 text-slate-700 ring-slate-200",
  good: "bg-emerald-50 text-emerald-700 ring-emerald-200",
  warn: "bg-amber-50 text-amber-800 ring-amber-200",
  bad: "bg-rose-50 text-rose-700 ring-rose-200",
  info: "bg-sky-50 text-sky-700 ring-sky-200",
  muted: "bg-transparent text-slate-500 ring-slate-200",
  // Supplied-engine output is always visually distinct from TaxProof's own findings.
  engine: "bg-violet-50 text-violet-700 ring-violet-200",
};

export function Chip({ tone = "neutral", children, className, title }: {
  tone?: Tone; children: React.ReactNode; className?: string; title?: string;
}) {
  return (
    <span title={title} className={cn(
      "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset whitespace-nowrap",
      TONES[tone], className)}>
      {children}
    </span>
  );
}

export function Money({ value, className, sign }: { value: unknown; className?: string; sign?: boolean }) {
  return <span className={cn("num", typeof value === "number" && value < 0 && "text-rose-700", className)}>{money(value, { sign })}</span>;
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: React.ReactNode; actions?: React.ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="mt-0.5 text-sm text-muted-foreground">{subtitle}</p>}
      </div>
      {actions}
    </div>
  );
}

export function Panel({ title, children, className, actions, dense }: {
  title?: React.ReactNode; children: React.ReactNode; className?: string; actions?: React.ReactNode; dense?: boolean;
}) {
  return (
    <section className={cn("rounded-lg border bg-card shadow-xs", className)}>
      {title && (
        <header className="flex items-center justify-between gap-2 border-b px-4 py-2.5">
          <h2 className="text-[13px] font-semibold text-slate-800">{title}</h2>
          {actions}
        </header>
      )}
      <div className={dense ? "" : "p-4"}>{children}</div>
    </section>
  );
}

/** Honest placeholder for functionality scheduled in a later iteration. */
export function FutureBanner({ iteration, children }: { iteration: number; children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-2 rounded-md border border-dashed border-slate-300 bg-slate-50 px-3 py-2 text-xs text-slate-600">
      <Sparkles className="mt-0.5 size-3.5 shrink-0 text-slate-400" />
      <div><span className="font-semibold text-slate-700">Planned — Iteration {iteration}.</span> {children}</div>
    </div>
  );
}

export function ErrorState({ error }: { error: ApiError | Error | undefined }) {
  if (!error) return null;
  const forbidden = error instanceof ApiError && error.status === 403;
  return (
    <div className={cn("flex items-start gap-2 rounded-md border px-3 py-2.5 text-sm",
      forbidden ? "border-amber-200 bg-amber-50 text-amber-900" : "border-rose-200 bg-rose-50 text-rose-800")}>
      {forbidden ? <Lock className="mt-0.5 size-4" /> : <ShieldAlert className="mt-0.5 size-4" />}
      <div>
        <div className="font-medium">{forbidden ? "Not available for your role" : "Could not load"}</div>
        <div className="text-xs opacity-80">{error.message} {forbidden && "(enforced by the server)"}</div>
      </div>
    </div>
  );
}

export function Loading({ rows = 3 }: { rows?: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: rows }).map((_, i) => <div key={i} className="h-4 animate-pulse rounded bg-slate-100" />)}
    </div>
  );
}

/** A masked value with a logged, permission-checked reveal. */
export function SensitiveValue({ masked, fieldRef, canReveal }: { masked: string | null; fieldRef: string; canReveal: boolean }) {
  const mutate = useMutate();
  const [value, setValue] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  if (!masked) return <span className="text-muted-foreground">—</span>;
  const reveal = async () => {
    setErr(null);
    try {
      const r = await mutate<{ value: string }>("/api/sensitive/reveal", { field_ref: fieldRef });
      setValue(r.value);
    } catch (e) {
      setErr(e instanceof ApiError && e.status === 403 ? "Denied — no clearance. Attempt logged." : "Reveal failed");
    }
  };
  return (
    <span className="inline-flex flex-wrap items-center gap-x-1.5">
      <span className="num font-mono text-[12px] whitespace-nowrap">{value ?? masked}</span>
      {value ? (
        <Chip tone="warn" title="This view was written to the access log">viewed · logged</Chip>
      ) : (
        <button
          onClick={reveal}
          title={canReveal ? "Reveal (logged to the access log)" : "Your role has no sensitive-data clearance; attempts are logged"}
          className={cn("inline-flex items-center gap-0.5 rounded px-1 text-[11px]",
            canReveal ? "text-sky-700 hover:bg-sky-50" : "text-slate-400 hover:bg-slate-50")}>
          {canReveal ? <Eye className="size-3" /> : <Lock className="size-3" />} reveal
        </button>
      )}
      {err && <span className="basis-full text-[11px] leading-tight text-rose-700">{err}</span>}
    </span>
  );
}

export function Stat({ label, value, sub, tone }: { label: string; value: React.ReactNode; sub?: React.ReactNode; tone?: "bad" | "good" }) {
  return (
    <div>
      <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className={cn("num mt-0.5 text-2xl font-semibold tracking-tight", tone === "bad" && "text-rose-700", tone === "good" && "text-emerald-700")}>{value}</div>
      {sub && <div className="mt-0.5 text-xs text-muted-foreground">{sub}</div>}
    </div>
  );
}
