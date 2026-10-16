"use client";

import Link from "next/link";
import { Suspense, useCallback, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { mutate as revalidate } from "swr";
import { AlertTriangle, ArrowLeftRight, BadgeCheck, Copy, FileText, Link2, Radar, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, useApi, useMutate } from "@/lib/api";
import { humanize, money } from "@/lib/format";
import { hrefFor } from "@/lib/links";
import type { Impact, Me, NodeDetail, Subgraph } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Chip, ErrorState, Loading, Money, PageHeader, Panel } from "@/components/tp/primitives";
import { EDGE_STYLE, EvidenceGraph, KIND_STYLE } from "@/components/tp/graph/evidence-graph";

type Mode = "up" | "down" | "impact";

export default function ProvePage() {
  return <Suspense fallback={<Loading />}><Prove /></Suspense>;
}

function Prove() {
  const params = useSearchParams();
  const router = useRouter();
  const ref = params.get("ref") ?? "line:v3:SchC.9";
  const mode = (params.get("mode") as Mode) ?? "up";
  const expand = params.get("expand") ?? "";
  // Headline results sit on hundreds of lines: open them shallow and let the reviewer drill in.
  const [depthChoice, setDepth] = useState<number | null>(null);
  const depth = depthChoice ?? (/^(line:v\d+:)?(F1040|F540NR)\.\d/.test(ref) ? 2 : 4);
  const [rules, setRules] = useState(true);
  const [selected, setSelected] = useState<string | null>(null);

  const set = useCallback((patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params.toString());
    for (const [k, v] of Object.entries(patch)) {
      if (v === null || v === "") next.delete(k);
      else next.set(k, v);
    }
    router.replace(`/prove?${next.toString()}`, { scroll: false });
  }, [params, router]);

  // The return version is part of the question. A `line:vN:` ref carries its own; anything else
  // (documents, pages, values, bare keys) is read in the version chosen here — never silently v3.
  const lineVersion = /^line:(v\d+):/.exec(ref)?.[1] ?? null;
  const chosenVersion = params.get("v");
  const version = lineVersion ?? chosenVersion;
  const { data: versions } = useApi<{ current: string; versions: { version: string }[] }>("/api/return/versions");

  const q = new URLSearchParams({ ref, depth: String(depth), rules: String(rules) });
  if (expand) q.set("expand", expand);
  if (version) q.set("version", version);
  const vq = version ? `&version=${version}` : "";
  const { data: sg, error } = useApi<Subgraph>(mode === "impact" ? null : `/api/graph/${mode === "up" ? "prove" : "trace"}?${q}`);
  const { data: imp, error: impErr } = useApi<Impact>(mode === "impact" ? `/api/graph/impact?ref=${encodeURIComponent(ref)}${vq}` : null);
  const { data: rootNode } = useApi<NodeDetail>(`/api/graph/node?ref=${encodeURIComponent(ref)}${vq}`);
  const shownVersion = version ?? versions?.current;

  const onExpand = (id: string) => {
    const s = new Set(expand.split(",").filter(Boolean));
    s.add(id);
    set({ expand: [...s].join(",") });
  };
  const reroot = (id: string, m: Mode = mode) => {
    setSelected(null);
    setDepth(null);
    set({ ref: id, mode: m, expand: null, v: /^line:(v\d+):/.exec(id)?.[1] ?? version });
  };

  const st = rootNode ? KIND_STYLE[rootNode.kind] : undefined;
  const legend = useMemo(() => Object.entries(EDGE_STYLE).filter(([t]) => sg?.edges.some((e) => e.type === t)), [sg]);

  return (
    <div className="space-y-4">
      <PageHeader
        title="Prove It"
        subtitle="Every number traced to the exact page it came from — and every source traced to everything it touches."
      />

      {/* Subject */}
      <div className="flex flex-wrap items-center gap-4 rounded-lg border bg-white px-4 py-3 shadow-xs">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
            {st && <Chip>{st.label}</Chip>}
            <code>{ref}</code>
            {rootNode?.kind === "ReturnLine" && <Chip tone="engine">engine result · {rootNode.meta.version}</Chip>}
          </div>
          <div className="mt-0.5 truncate text-[15px] font-semibold">{rootNode?.label ?? "…"}</div>
          {rootNode?.value !== undefined && rootNode?.value !== null && (
            <div className="num text-2xl font-semibold tracking-tight">{typeof rootNode.value === "number" ? money(rootNode.value) : String(rootNode.value)}</div>
          )}
        </div>
        <div className="inline-flex rounded-lg border bg-slate-50 p-1 text-[13px]">
          {([
            ["up", "Prove it", ShieldCheck, "Walk back to the source pages"],
            ["down", "Where it goes", ArrowLeftRight, "Walk forward to the final tax"],
            ["impact", "Impact radius", Radar, "What would change if this changed"],
          ] as const).map(([m, label, Icon, tip]) => (
            <button key={m} title={tip} onClick={() => set({ mode: m, expand: null })}
              className={cn("flex items-center gap-1.5 rounded-md px-3 py-1.5", mode === m ? "bg-white font-medium text-primary shadow-xs" : "text-slate-600 hover:text-slate-900")}>
              <Icon className="size-4" /> {label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-1 text-[11px] text-muted-foreground" title={lineVersion ? "This line belongs to one return version" : "Which return version to read this in"}>
          Return
          {lineVersion ? (
            <Chip tone="info">{lineVersion}</Chip>
          ) : (
            versions?.versions.map((v) => (
              <button key={v.version} onClick={() => set({ v: v.version, expand: null })}
                className={cn("rounded px-1.5 py-0.5", shownVersion === v.version ? "bg-slate-800 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200")}>
                {v.version}
              </button>
            ))
          )}
        </div>
        {rootNode && hrefFor(rootNode.id, rootNode.meta) && (
          <Link href={hrefFor(rootNode.id, rootNode.meta)!} className="text-xs text-sky-700 hover:underline">Open in {rootNode.id.startsWith("line:") ? "return" : "evidence"} →</Link>
        )}
      </div>

      <ErrorState error={error ?? impErr} />

      {mode === "impact" ? (
        imp ? <ImpactView imp={imp} onPick={(id) => reroot(id, "up")} /> : !impErr && <Loading rows={6} />
      ) : (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
            <label className="flex items-center gap-2">Depth
              <input type="range" min={1} max={10} value={depth} onChange={(e) => setDepth(Number(e.target.value))} />
              <span className="num w-4 text-slate-700">{depth}</span>
            </label>
            {mode === "up" && <label className="flex items-center gap-1.5"><Switch checked={rules} onCheckedChange={setRules} /> rules</label>}
            {expand && <button onClick={() => set({ expand: null })} className="text-sky-700 hover:underline">collapse all</button>}
            <span className="ml-auto">Click a node to inspect · “N more” or double-click to open · scroll to pan, pinch or +/− to zoom</span>
          </div>
          <div className="relative">
            {!sg ? <div className="h-[600px] rounded-lg border bg-white p-4"><Loading rows={8} /></div> : (
              <EvidenceGraph data={sg} selected={selected} onSelect={setSelected} onExpand={onExpand} height={600} />
            )}
            {selected && (
              <div className="absolute top-3 right-3 z-10 max-h-[574px] w-[360px] overflow-y-auto rounded-lg shadow-lg">
                <Inspector id={selected} onReroot={reroot} onClose={() => setSelected(null)} />
              </div>
            )}
          </div>
          {legend.length > 0 && (
            <div className="flex flex-wrap gap-3 text-[11px] text-muted-foreground">
              {legend.map(([t, s]) => (
                <span key={t} className="inline-flex items-center gap-1">
                  <svg width="22" height="6"><line x1="0" y1="3" x2="22" y2="3" stroke={s.stroke} strokeWidth="2" strokeDasharray={s.dash} /></svg>
                  {humanize(t.toLowerCase())}
                </span>
              ))}
            </div>
          )}
          {mode === "up" && sg?.footprint && <FootprintPanel f={sg.footprint} />}
          {mode === "down" && sg?.impact && <ImpactSummary imp={sg.impact} onMode={() => set({ mode: "impact" })} />}
        </div>
      )}
    </div>
  );
}

function FootprintPanel({ f }: { f: NonNullable<Subgraph["footprint"]> }) {
  const conflicts = f.flags.filter((x) => x.severity === "conflict");
  const reviews = f.flags.filter((x) => x.severity === "review");
  return (
    <Panel title={<span className="flex items-center gap-1.5"><ShieldCheck className="size-4 text-primary" />What this number rests on</span>}>
      <p className="mb-3 text-[11px] text-muted-foreground">Complete, not just what is drawn: every path back to evidence.</p>
      <div className="grid grid-cols-3 gap-2 text-center md:max-w-md">
        <Fact n={f.lines} label="return lines" />
        <Fact n={f.values} label="extracted values" />
        <Fact n={f.documents.length} label="documents" />
      </div>
      <div className="mt-3 space-y-1.5 text-xs">
        <Row ok={f.values === 0 || f.verified_values === f.values}
          text={`${f.verified_values} of ${f.values} source values verified${f.lines ? ` · ${f.verified_lines} of ${f.lines} lines` : ""}`} icon={BadgeCheck} />
        <Row ok={f.duplicate_pages_in_evidence.length === 0}
          text={f.duplicate_pages_in_evidence.length ? `Duplicate pages in the evidence: ${f.duplicate_pages_in_evidence.map((d) => `${d.document_id} p${d.pages.join("/")}`).join(", ")}` : "No duplicate pages in the evidence"} icon={Copy} />
        <Row ok={conflicts.length === 0} text={conflicts.length ? `${conflicts.length} source value(s) disagree with the printed page or organizer` : "No source value conflicts with what is printed"} icon={AlertTriangle} />
        {reviews.length > 0 && <Row ok={false} warn text={`${reviews.length} source value(s) need a human look`} icon={AlertTriangle} />}
      </div>
      {f.flags.length > 0 && (
        <ul className="mt-3 max-h-48 space-y-1 overflow-y-auto">
          {f.flags.map((x, i) => (
            <li key={i} className={cn("rounded border px-2 py-1 text-[11px]", x.severity === "conflict" ? "border-rose-200 bg-rose-50" : "border-amber-200 bg-amber-50")}>
              <Link href={`/evidence?doc=${x.document_id}&page=${x.page}&ev=${x.ref}`} className="font-mono text-sky-700 hover:underline">{x.ref}</Link> {x.label} — {x.message}
            </li>
          ))}
        </ul>
      )}
      <div className="mt-3">
        <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Source documents ({f.documents.length})</div>
        <ul className="grid max-h-56 gap-x-6 gap-y-0.5 overflow-y-auto text-xs md:grid-cols-2">
          {f.documents.map((d) => (
            <li key={d.id} className="flex gap-1.5">
              <FileText className="mt-0.5 size-3 shrink-0 text-slate-400" />
              <Link href={`/evidence?doc=${d.id}&page=${d.pages[0]}`} className="text-sky-700 hover:underline">{d.id}</Link>
              <span className="truncate text-slate-600">{d.title}</span>
              <span className="ml-auto shrink-0 text-muted-foreground">p{d.pages.join(",")}</span>
            </li>
          ))}
        </ul>
      </div>
    </Panel>
  );
}

function ImpactSummary({ imp, onMode }: { imp: Impact; onMode: () => void }) {
  return (
    <Panel title={<span className="flex items-center gap-1.5"><Radar className="size-4 text-primary" />Downstream reach ({imp.version})</span>}
      actions={<button onClick={onMode} className="text-xs text-sky-700 hover:underline">Impact radius →</button>}>
      <div className="grid grid-cols-2 gap-2 text-center">
        <Fact n={imp.affected_lines} label={`lines in ${imp.version}`} />
        <Fact n={imp.headlines.length} label="results reached" />
      </div>
      <ul className="mt-3 space-y-1 text-xs">
        {imp.headlines.map((h) => (
          <li key={h.id} className="flex justify-between"><span>{h.label} <code className="text-muted-foreground">{h.key}</code></span><Money value={h.value} /></li>
        ))}
      </ul>
    </Panel>
  );
}

function ImpactView({ imp, onPick }: { imp: Impact; onPick: (id: string) => void }) {
  const maxRing = Math.max(...imp.rings.map((r) => r.lines.length), 1);
  return (
    <div className="grid gap-4 xl:grid-cols-[1fr_380px]">
      <Panel title={`If this changed: ${imp.affected_lines} lines in ${imp.version} would be recomputed`}>
        <p className="mb-3 text-xs text-muted-foreground">
          Rings are hops along the engine&apos;s own input chain. This is structural reach, not a tax estimate —
          estimated tax effects arrive with adjustments in Iteration 6.
        </p>
        <ol className="space-y-2">
          {imp.rings.map((r) => (
            <li key={r.distance} className="grid grid-cols-[64px_1fr] gap-3">
              <div className="pt-0.5 text-right text-[11px] text-muted-foreground">{r.distance} hop{r.distance > 1 ? "s" : ""}</div>
              <div>
                <div className="mb-1 h-1.5 rounded bg-indigo-100"><div className="h-1.5 rounded bg-indigo-500" style={{ width: `${(r.lines.length / maxRing) * 100}%` }} /></div>
                <div className="flex flex-wrap gap-1">
                  {r.lines.map((l) => {
                    const head = imp.headlines.some((h) => h.id === l.id);
                    return (
                      <button key={l.id} onClick={() => onPick(l.id)} title={`${l.label} — ${typeof l.value === "number" ? money(l.value) : l.value}`}
                        className={cn("rounded border px-1.5 py-0.5 font-mono text-[10.5px] hover:border-primary",
                          head ? "border-indigo-500 bg-indigo-600 text-white" : "bg-white text-slate-700")}>
                        {l.key}
                      </button>
                    );
                  })}
                </div>
              </div>
            </li>
          ))}
          {imp.rings.length === 0 && <li className="text-xs text-muted-foreground">Nothing downstream in {imp.version}.</li>}
        </ol>
      </Panel>
      <div className="space-y-4">
        <Panel title="Results reached">
          {imp.headlines.length === 0 ? <p className="text-xs text-muted-foreground">No headline result depends on this.</p> : (
            <ul className="space-y-1 text-[13px]">
              {imp.headlines.map((h) => (
                <li key={h.id} className="flex items-center justify-between gap-2">
                  <span>{h.label} <span className="text-[11px] text-muted-foreground">· {h.distance} hops</span></span><Money value={h.value} />
                </li>
              ))}
            </ul>
          )}
        </Panel>
        <Panel title="By area">
          <ul className="space-y-1 text-xs">
            {Object.entries(imp.by_area).map(([a, n]) => <li key={a} className="flex justify-between"><span>{humanize(a)}</span><span className="num">{n}</span></li>)}
          </ul>
          {Object.keys(imp.by_version).length > 1 && (
            <p className="mt-2 text-[11px] text-muted-foreground">Also feeds: {Object.entries(imp.by_version).map(([v, n]) => `${v} (${n})`).join(", ")}</p>
          )}
        </Panel>
      </div>
    </div>
  );
}

function Inspector({ id, onReroot, onClose }: { id: string; onReroot: (id: string, m?: Mode) => void; onClose: () => void }) {
  const { data: n, error, mutate: reload } = useApi<NodeDetail>(`/api/graph/node?ref=${encodeURIComponent(id)}`);
  const { data: me } = useApi<Me>("/api/session/me");
  if (error) return <ErrorState error={error} />;
  if (!n) return <Panel><Loading /></Panel>;
  const st = KIND_STYLE[n.kind];
  const notes = [...n.incoming, ...n.outgoing].filter((e) => !["SOURCE_OF", "INPUT_TO", "CALCULATED_FROM"].includes(e.type));
  const href = hrefFor(n.id, n.meta);
  const canLink = !!me?.permissions.includes("create_note");
  return (
    <Panel title={<span className="flex items-center gap-1.5">{st?.label ?? n.kind} <code className="text-[11px] font-normal text-muted-foreground">{n.id}</code></span>}
      actions={<button onClick={onClose} className="text-xs text-muted-foreground hover:text-slate-900">close</button>}>
      <div className="text-[13px] font-medium">{n.label}</div>
      {n.value !== null && n.value !== undefined && <div className="num text-lg font-semibold">{typeof n.value === "number" ? money(n.value) : String(n.value)}</div>}
      <dl className="mt-1 grid grid-cols-[96px_1fr] gap-y-0.5 text-xs">
        {Object.entries(n.meta).filter(([k, v]) => v !== null && v !== "" && !["flags"].includes(k) && typeof v !== "object").map(([k, v]) => (
          <FragmentRow key={k} k={humanize(k)} v={String(v)} />
        ))}
      </dl>
      {(n.meta.flags ?? []).map((f: { code: string; severity: string; message: string }) => (
        <div key={f.code} className={cn("mt-1.5 rounded px-2 py-1 text-[11px]", f.severity === "conflict" ? "bg-rose-50 text-rose-800" : "bg-amber-50 text-amber-800")}>{f.message}</div>
      ))}
      {notes.length > 0 && (
        <div className="mt-2">
          <div className="mb-0.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">Relationships</div>
          <ul className="space-y-0.5 text-[11px]">
            {notes.slice(0, 12).map((e, i) => (
              <li key={i}>
                <span className="font-medium" style={{ color: EDGE_STYLE[e.type]?.stroke }}>{humanize(e.type.toLowerCase())}</span>{" "}
                <button onClick={() => onReroot(e.other, "up")} className="font-mono text-sky-700 hover:underline">{e.other}</button>
                {e.detail && <span className="text-muted-foreground"> — {e.detail}</span>}
                {e.origin === "workpaper" && <Chip tone="info" className="ml-1">workpaper</Chip>}
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="mt-3 flex flex-wrap gap-1.5">
        <Button size="sm" variant="outline" onClick={() => onReroot(n.id, "up")}><ShieldCheck className="size-3.5" />Prove it</Button>
        <Button size="sm" variant="outline" onClick={() => onReroot(n.id, "down")}><ArrowLeftRight className="size-3.5" />Where it goes</Button>
        <Button size="sm" variant="outline" onClick={() => onReroot(n.id, "impact")}><Radar className="size-3.5" />Impact</Button>
        {href && <Link href={href} className="inline-flex items-center px-2 text-xs text-sky-700 hover:underline">Open →</Link>}
      </div>
      {canLink && <LinkForm src={n.id} onDone={() => {
        reload();
        // a new relationship can change the picture and the footprint: refresh every graph view
        revalidate((key) => Array.isArray(key) && String(key[0]).startsWith("/api/graph"));
      }} />}
    </Panel>
  );
}

function LinkForm({ src, onDone }: { src: string; onDone: () => void }) {
  const mutate = useMutate();
  const [open, setOpen] = useState(false);
  const [dst, setDst] = useState("");
  const [type, setType] = useState("RELATED_TO");
  const [note, setNote] = useState("");
  const [err, setErr] = useState<string | null>(null);
  if (!open) return <button onClick={() => setOpen(true)} className="mt-2 inline-flex items-center gap-1 text-xs text-sky-700 hover:underline"><Link2 className="size-3.5" />Link to another item…</button>;
  const submit = async () => {
    setErr(null);
    try {
      await mutate("/api/graph/links", { src_ref: src, dst_ref: dst.trim(), type, note });
      setOpen(false); setDst(""); setNote("");
      onDone();
    } catch (e) {
      setErr(e instanceof ApiError ? e.detail : "Failed");
    }
  };
  return (
    <div className="mt-2 space-y-1.5 rounded-md border bg-slate-50 p-2">
      <div className="flex gap-1.5">
        <select value={type} onChange={(e) => setType(e.target.value)} className="h-7 rounded border bg-white px-1 text-xs">
          {["RELATED_TO", "CONFIRMED_BY", "CONFLICTS_WITH", "SUPERSEDES", "DUPLICATE_OF"].map((t) => <option key={t} value={t}>{humanize(t.toLowerCase())}</option>)}
        </select>
        <Input value={dst} onChange={(e) => setDst(e.target.value)} placeholder="target ref, e.g. qa-14, D40, SchE.28A" className="h-7 bg-white font-mono text-[11px]" />
      </div>
      <Textarea value={note} onChange={(e) => setNote(e.target.value)} placeholder="Why are these related? (required)" className="min-h-12 bg-white text-xs" />
      <div className="flex gap-2">
        <Button size="sm" disabled={!dst.trim() || !note.trim()} onClick={submit}>Save link</Button>
        <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
      </div>
      {err && <div className="text-[11px] text-rose-700">{err}</div>}
    </div>
  );
}

function FragmentRow({ k, v }: { k: string; v: string }) {
  return (<><dt className="text-muted-foreground">{k}</dt><dd className="break-words text-slate-700">{v}</dd></>);
}

function Fact({ n, label }: { n: number; label: string }) {
  return <div className="rounded-md border px-2 py-1.5"><div className="num text-lg font-semibold">{n}</div><div className="text-[10.5px] text-muted-foreground">{label}</div></div>;
}

function Row({ ok, warn, text, icon: Icon }: { ok: boolean; warn?: boolean; text: string; icon: React.ComponentType<{ className?: string }> }) {
  return (
    <div className={cn("flex items-start gap-1.5", ok ? "text-emerald-700" : warn ? "text-amber-700" : "text-rose-700")}>
      <Icon className="mt-0.5 size-3.5 shrink-0" /><span>{text}</span>
    </div>
  );
}
