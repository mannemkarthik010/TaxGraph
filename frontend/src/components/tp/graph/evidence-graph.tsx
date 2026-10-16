"use client";

import "@xyflow/react/dist/style.css";
import { useMemo } from "react";
import {
  Background, Controls, Handle, MarkerType, Position, ReactFlow, type Edge, type Node, type NodeProps,
} from "@xyflow/react";
import { AlertTriangle, BadgeCheck, Copy, Plus } from "lucide-react";
import { money } from "@/lib/format";
import type { GraphEdge, GraphGroup, GraphNode } from "@/lib/types";
import { cn } from "@/lib/utils";
import { layout } from "./layout";

export const KIND_STYLE: Record<string, { label: string; tone: string }> = {
  ReturnLine: { label: "Return line", tone: "border-indigo-300 bg-indigo-50/70 text-indigo-900" },
  ExtractedValue: { label: "Extracted value", tone: "border-amber-300 bg-amber-50/60 text-amber-950" },
  Page: { label: "Page", tone: "border-slate-300 bg-white text-slate-800" },
  Document: { label: "Document", tone: "border-slate-400 bg-slate-50 text-slate-900" },
  CalculationRule: { label: "Rule", tone: "border-violet-200 bg-violet-50/60 text-violet-900" },
  EngineParameter: { label: "Engine parameter", tone: "border-violet-200 bg-violet-50/60 text-violet-900" },
  EngineDiagnostic: { label: "Engine diagnostic", tone: "border-violet-300 bg-violet-50 text-violet-900" },
  PriorYearValue: { label: "Prior year", tone: "border-teal-300 bg-teal-50/60 text-teal-900" },
  AgencyRecord: { label: "Agency record", tone: "border-teal-300 bg-teal-50/60 text-teal-900" },
  ClientAnswer: { label: "Client", tone: "border-sky-300 bg-sky-50/60 text-sky-900" },
  HouseholdMember: { label: "Household", tone: "border-sky-300 bg-sky-50/60 text-sky-900" },
  Asset: { label: "Asset", tone: "border-teal-300 bg-teal-50/60 text-teal-900" },
  Verification: { label: "Verification", tone: "border-emerald-300 bg-emerald-50 text-emerald-900" },
  Adjustment: { label: "Adjustment", tone: "border-orange-300 bg-orange-50 text-orange-900" },
  Judgment: { label: "Judgment", tone: "border-fuchsia-300 bg-fuchsia-50 text-fuchsia-900" },
  TimelineEvent: { label: "Timeline", tone: "border-slate-300 bg-white text-slate-700" },
  AgencyNotice: { label: "Agency", tone: "border-teal-300 bg-teal-50/60 text-teal-900" },
};

export const EDGE_STYLE: Record<string, { stroke: string; dash?: string; label?: string }> = {
  SOURCE_OF: { stroke: "#94a3b8" },
  INPUT_TO: { stroke: "#6366f1" },
  CALCULATED_FROM: { stroke: "#a78bfa", dash: "4 3", label: "rule" },
  VERIFIED_BY: { stroke: "#10b981", label: "verified by" },
  ADJUSTED_BY: { stroke: "#ea580c", label: "adjusted by" },
  CONFIRMED_BY: { stroke: "#10b981", dash: "4 3", label: "confirmed by" },
  SUPERSEDES: { stroke: "#64748b", dash: "6 4", label: "supersedes" },
  DUPLICATE_OF: { stroke: "#e11d48", dash: "6 4", label: "duplicate of" },
  CONFLICTS_WITH: { stroke: "#e11d48", label: "conflicts with" },
  RELATED_TO: { stroke: "#0ea5e9", dash: "2 3", label: "related" },
};

type NodeData = {
  g?: GraphNode;
  group?: GraphGroup;
  root: boolean;
  selected: boolean;
  direction: "up" | "down";
  dupe: boolean;
  verified: boolean;
};

function fmt(v: unknown) {
  if (typeof v === "number") return money(v);
  if (v == null) return "";
  return String(v);
}

function GraphCard({ data }: NodeProps<Node<NodeData>>) {
  const { g, group, root, selected, direction, dupe, verified } = data;
  // up: evidence (right) flows into results (left) → outgoing on the left, incoming on the right
  const outSide = direction === "up" ? Position.Left : Position.Right;
  const inSide = direction === "up" ? Position.Right : Position.Left;
  if (group) {
    return (
      <div className="w-[230px] cursor-pointer rounded-md border border-dashed border-slate-400 bg-white/80 px-2.5 py-2 text-xs text-slate-600 hover:border-primary hover:text-primary">
        <Handle type="source" position={outSide} className="!opacity-0" />
        <Handle type="target" position={inSide} className="!opacity-0" />
        <div className="flex items-center gap-1 font-medium"><Plus className="size-3.5" /> {group.count} more</div>
        <div className="text-[10.5px]">{Object.entries(group.kinds).map(([k, n]) => `${n} ${KIND_STYLE[k]?.label.toLowerCase() ?? k}`).join(", ")} · click to open</div>
      </div>
    );
  }
  if (!g) return null;
  const st = KIND_STYLE[g.kind] ?? { label: g.kind, tone: "border-slate-300 bg-white" };
  const flags: { severity: string }[] = g.meta?.flags ?? [];
  const conflict = flags.some((f) => f.severity === "conflict");
  const review = flags.some((f) => f.severity === "review");
  const shortId = g.id.startsWith("line:") ? g.meta.key : g.id.replace(/^doc:/, "").replace(/^verification:/, "verif ");
  return (
    <div className={cn(
      "w-[230px] rounded-md border px-2.5 py-1.5 shadow-xs transition",
      st.tone,
      root && "ring-2 ring-primary ring-offset-1",
      selected && "ring-2 ring-sky-500",
      conflict && "border-rose-400",
      g.annotation && "opacity-90",
    )}>
      <Handle type="target" position={inSide} className="!size-1.5 !border-0 !bg-slate-400" />
      <Handle type="source" position={outSide} className="!size-1.5 !border-0 !bg-slate-400" />
      <div className="flex items-center gap-1 text-[9.5px] font-semibold uppercase tracking-wide opacity-70">
        <span>{st.label}</span>
        <span className="truncate font-mono normal-case tracking-normal">{shortId}</span>
        {g.meta?.headline && <span className="ml-auto rounded bg-indigo-600 px-1 text-[9px] text-white normal-case">result</span>}
      </div>
      <div className="line-clamp-2 text-[11.5px] leading-tight font-medium">{g.label}</div>
      <div className="mt-0.5 flex items-center gap-1">
        {g.value !== null && g.value !== undefined && g.value !== "" && (
          <span className="num truncate text-[12.5px] font-semibold">{fmt(g.value)}</span>
        )}
        <span className="ml-auto flex items-center gap-0.5">
          {typeof g.meta?.confidence === "number" && <span className="text-[9.5px] opacity-60">{Math.round(g.meta.confidence * 100)}%</span>}
          {conflict && <AlertTriangle className="size-3.5 text-rose-600" aria-label="conflict" />}
          {!conflict && review && <AlertTriangle className="size-3.5 text-amber-600" aria-label="needs review" />}
          {dupe && <Copy className="size-3.5 text-rose-600" aria-label="duplicate" />}
          {verified && <BadgeCheck className="size-3.5 text-emerald-600" aria-label="verified" />}
          {g.has_more && <span className="rounded bg-slate-800/80 px-1 text-[9px] text-white">+ more</span>}
        </span>
      </div>
    </div>
  );
}

const nodeTypes = { card: GraphCard };

export function EvidenceGraph({ data, selected, onSelect, onExpand, height = 640 }: {
  data: { root: string; direction: "up" | "down"; nodes: GraphNode[]; edges: GraphEdge[]; groups: GraphGroup[] };
  selected: string | null;
  onSelect: (id: string) => void;
  onExpand: (id: string) => void;
  height?: number;
}) {
  const { nodes, edges } = useMemo(() => {
    const pos = layout(data.nodes, data.edges, data.groups, data.direction);
    const dupes = new Set(data.edges.filter((e) => e.type === "DUPLICATE_OF").flatMap((e) => [e.src, e.dst]));
    const verified = new Set(data.edges.filter((e) => e.type === "VERIFIED_BY").map((e) => e.src));
    const visible = new Set(data.nodes.map((n) => n.id));
    const rfNodes: Node<NodeData>[] = [
      ...data.nodes.map((g) => ({
        id: g.id, type: "card", position: pos.get(g.id) ?? { x: 0, y: 0 },
        data: { g, root: g.id === data.root, selected: g.id === selected, direction: data.direction, dupe: dupes.has(g.id), verified: verified.has(g.id) },
      })),
      ...data.groups.map((group) => ({
        id: group.id, type: "card", position: pos.get(group.id) ?? { x: 0, y: 0 },
        data: { group, root: false, selected: false, direction: data.direction, dupe: false, verified: false },
      })),
    ];
    const rfEdges: Edge[] = data.edges
      .filter((e) => visible.has(e.src) && visible.has(e.dst))
      .map((e, i) => {
        const st = EDGE_STYLE[e.type] ?? { stroke: "#94a3b8" };
        return {
          id: `${e.src}->${e.dst}:${e.type}:${i}`, source: e.src, target: e.dst,
          label: st.label, labelStyle: { fontSize: 9, fill: st.stroke }, labelBgStyle: { fill: "white" },
          style: { stroke: st.stroke, strokeWidth: e.type === "INPUT_TO" || e.type === "SOURCE_OF" ? 1.4 : 1.8, strokeDasharray: st.dash },
          markerEnd: { type: MarkerType.ArrowClosed, color: st.stroke, width: 14, height: 14 },
          animated: e.type === "DUPLICATE_OF" || e.type === "CONFLICTS_WITH",
        };
      });
    for (const g of data.groups) {
      const [source, target] = data.direction === "up" ? [g.id, g.parent] : [g.parent, g.id];
      rfEdges.push({
        id: `${g.parent}->${g.id}`, source, target,
        style: { stroke: "#cbd5e1", strokeDasharray: "3 3" },
      });
    }
    return { nodes: rfNodes, edges: rfEdges };
  }, [data, selected]);

  return (
    <div style={{ height }} className="rounded-lg border bg-slate-50/60">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        fitView
        // Never shrink cards below legibility: tall traces are scrolled (wheel pans), not squeezed.
        fitViewOptions={{ padding: 0.12, minZoom: 0.6, maxZoom: 1.1 }}
        minZoom={0.2}
        panOnScroll
        zoomOnScroll={false}
        zoomOnPinch
        nodesDraggable={false}
        nodesConnectable={false}
        proOptions={{ hideAttribution: true }}
        onNodeClick={(_, n) => (n.id.startsWith("group:") ? onExpand(n.id.slice(6)) : onSelect(n.id))}
        onNodeDoubleClick={(_, n) => onExpand(n.id.startsWith("group:") ? n.id.slice(6) : n.id)}
      >
        <Background gap={18} size={1} color="#e2e8f0" />
        <Controls showInteractive={false} position="bottom-right" />
      </ReactFlow>
    </div>
  );
}
