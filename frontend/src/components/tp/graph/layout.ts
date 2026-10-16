import type { GraphEdge, GraphGroup, GraphNode } from "@/lib/types";

export const COL_W = 270;
export const ROW_H = 92;
const FLOW = new Set(["SOURCE_OF", "INPUT_TO"]);

export type Placed = { id: string; x: number; y: number };

/**
 * Layered layout: one column per distance from the root (root on the left). Within a column, nodes
 * are ordered by the average row of the nodes they connect to in the previous column, which keeps
 * most edges short and uncrossed. Collapsed groups sit right after their parent's children;
 * annotation nodes (rules, verifications, conflicts) go at the bottom of their anchor's column.
 */
export function layout(nodes: GraphNode[], edges: GraphEdge[], groups: GraphGroup[], direction: "up" | "down"): Map<string, Placed> {
  const flowNodes = nodes.filter((n) => !n.annotation);
  const byLevel = new Map<number, string[]>();
  for (const n of flowNodes) {
    if (!byLevel.has(n.level)) byLevel.set(n.level, []);
    byLevel.get(n.level)!.push(n.id);
  }
  // parents in the previous column, along flow edges
  const prevOf = new Map<string, string[]>();
  for (const e of edges) {
    if (!FLOW.has(e.type)) continue;
    const [near, far] = direction === "up" ? [e.dst, e.src] : [e.src, e.dst];
    if (!prevOf.has(far)) prevOf.set(far, []);
    prevOf.get(far)!.push(near);
  }
  const row = new Map<string, number>();
  const levels = [...byLevel.keys()].sort((a, b) => a - b);
  const columns = new Map<number, string[]>();
  for (const lv of levels) {
    const ids = byLevel.get(lv)!;
    const score = (id: string) => {
      const ps = (prevOf.get(id) ?? []).filter((p) => row.has(p));
      return ps.length ? ps.reduce((s, p) => s + row.get(p)!, 0) / ps.length : 0;
    };
    const ordered = [...ids].sort((a, b) => score(a) - score(b) || a.localeCompare(b));
    // groups belong at the end of their parent's block in this column
    const col: string[] = [];
    for (const id of ordered) col.push(id);
    for (const g of groups.filter((g) => g.level === lv)) {
      const parentRow = row.get(g.parent) ?? 0;
      const insertAt = col.findIndex((id) => score(id) > parentRow);
      if (insertAt === -1) col.push(g.id);
      else col.splice(insertAt, 0, g.id);
    }
    col.forEach((id, i) => row.set(id, i));
    columns.set(lv, col);
  }
  // annotations at the bottom of their anchor's column
  for (const n of nodes.filter((n) => n.annotation)) {
    const lv = n.level;
    if (!columns.has(lv)) columns.set(lv, []);
    columns.get(lv)!.push(n.id);
  }
  // groups whose level has no flow nodes
  for (const g of groups) {
    if (![...columns.values()].some((c) => c.includes(g.id))) {
      if (!columns.has(g.level)) columns.set(g.level, []);
      columns.get(g.level)!.push(g.id);
    }
  }
  const tallest = Math.max(...[...columns.values()].map((c) => c.length), 1);
  const placed = new Map<string, Placed>();
  for (const [lv, col] of columns) {
    const offset = ((tallest - col.length) * ROW_H) / 2; // centre short columns
    col.forEach((id, i) => placed.set(id, { id, x: lv * COL_W, y: offset + i * ROW_H }));
  }
  return placed;
}
