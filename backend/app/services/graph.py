"""Evidence graph: every packet object and workpaper record as a node, every relationship as an edge.

Node ids are the packet's own reference strings (`D23`, `doc:D23#page2`, `ev-0315`, `line:v3:SchC.44a`,
`py:/return_2024/lines/SchC.9`, `qa-14`, `rule:R-MILEAGE-PAGE-TOTALS`, `verification:12`, …), so
workpaper records join the graph without any id mapping.

The packet part of the graph is built once per packet hash. Workpaper overlays (verifications,
human-made links) are small and added per request. No graph database: adjacency lists in memory,
relationships persisted in PostgreSQL where people create them.

Edge direction follows evidence flow: source → what it supports
    Document ─SOURCE_OF→ Page ─SOURCE_OF→ ExtractedValue ─SOURCE_OF→ ReturnLine ─INPUT_TO→ ReturnLine
"Prove it" walks these edges backwards; "where it goes" and "impact radius" walk them forwards.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Iterable

from ..packet.index import PacketIndex
from ..packet.refs import resolve
from ..security.masking import is_sensitive_value, mask_extracted_value
from .areas import area_for_line
from .evidence import get_analysis
from .schedules import prior_value

# Edges that carry evidence/computation. Traversals follow only these.
FLOW = frozenset({"SOURCE_OF", "INPUT_TO"})
# Everything else annotates nodes that are already in view.
EDGE_TYPES = ("SOURCE_OF", "INPUT_TO", "CALCULATED_FROM", "VERIFIED_BY", "SUPERSEDES", "DUPLICATE_OF",
              "CONFLICTS_WITH", "ADJUSTED_BY", "CONFIRMED_BY", "SIGNED_BY", "RELATED_TO")
USER_LINK_TYPES = ("RELATED_TO", "CONFIRMED_BY", "CONFLICTS_WITH", "SUPERSEDES", "DUPLICATE_OF")

# Lines a reviewer thinks of as "the result". Impact radius reports which of these a change reaches.
HEADLINE_KEYS = {
    "F1040.11": "Federal AGI", "F1040.15": "Federal taxable income", "F1040.24": "Federal total tax",
    "F1040.33": "Federal payments", "F1040.37": "Federal balance due", "F1040.38": "Federal penalty",
    "F540NR.17": "California total AGI", "F540NR.32": "California AGI", "F540NR.64": "California total tax",
    "F540NR.97": "California overpayment",
}


@dataclass
class Node:
    id: str
    kind: str
    label: str
    value: Any = None
    meta: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "label": self.label, "value": self.value, "meta": self.meta}


@dataclass(frozen=True)
class Edge:
    src: str
    dst: str
    type: str
    origin: str = "packet"  # packet | analysis | workpaper
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"src": self.src, "dst": self.dst, "type": self.type, "origin": self.origin, "detail": self.detail}


@dataclass
class Graph:
    nodes: dict[str, Node] = field(default_factory=dict)
    out_edges: dict[str, list[Edge]] = field(default_factory=lambda: defaultdict(list))
    in_edges: dict[str, list[Edge]] = field(default_factory=lambda: defaultdict(list))

    def add_node(self, node: Node) -> None:
        self.nodes.setdefault(node.id, node)

    def add_edge(self, edge: Edge) -> None:
        self.out_edges[edge.src].append(edge)
        self.in_edges[edge.dst].append(edge)

    def edge_count(self) -> int:
        return sum(len(v) for v in self.out_edges.values())


class GraphView:
    """Base packet graph plus a per-request overlay (verifications, user links)."""

    def __init__(self, base: Graph, overlay_nodes: Iterable[Node] = (), overlay_edges: Iterable[Edge] = ()):
        self.base = base
        self.extra_nodes = {n.id: n for n in overlay_nodes}
        self.extra_out: dict[str, list[Edge]] = defaultdict(list)
        self.extra_in: dict[str, list[Edge]] = defaultdict(list)
        for e in overlay_edges:
            self.extra_out[e.src].append(e)
            self.extra_in[e.dst].append(e)

    def node(self, ref: str) -> Node | None:
        return self.base.nodes.get(ref) or self.extra_nodes.get(ref)

    def outgoing(self, ref: str) -> list[Edge]:
        return self.base.out_edges.get(ref, []) + self.extra_out.get(ref, [])

    def incoming(self, ref: str) -> list[Edge]:
        return self.base.in_edges.get(ref, []) + self.extra_in.get(ref, [])


# ---- building the packet graph ---------------------------------------------------------------------

def _value_display(ev: Any) -> Any:
    return mask_extracted_value(ev)["value"] if is_sensitive_value(ev) else ev["value"]


def ref_node(idx: PacketIndex, ref: str, version: str) -> Node | None:
    """A standalone node for any resolvable reference (used for links to things the base graph lacks)."""
    tmp = Graph()
    nid = _ensure_ref_node(tmp, idx, ref, version)
    return tmp.nodes.get(nid) if nid else None


def _ensure_ref_node(g: Graph, idx: PacketIndex, ref: str, version: str) -> str | None:
    """Make sure a cited ref exists as a node (packet citations can point at many kinds of things)."""
    if ref in g.nodes:
        return ref
    r = resolve(idx, ref, version)
    if not r.exists:
        return None
    kind = {
        "prior_year_value": "PriorYearValue", "agency_record": "AgencyRecord", "asset": "Asset",
        "client_answer": "ClientAnswer", "client_message": "ClientAnswer", "call_note": "ClientAnswer",
        "household_member": "HouseholdMember", "household_bank": "HouseholdMember",
        "engine_parameter": "EngineParameter", "fx_rate": "EngineParameter", "timeline_event": "TimelineEvent",
        "return_version": "ReturnVersion", "document": "Document", "page": "Page",
    }.get(r.kind, r.kind)
    if r.kind == "return_line":  # bare key cited by a diagnostic
        return f"line:{version}:{ref}"
    label = r.label or ref
    meta: dict[str, Any] = {}
    if r.kind in ("client_answer", "client_message", "call_note"):
        meta["subkind"] = r.kind
    g.add_node(Node(ref, kind, str(label)[:160], r.value, meta))
    return ref


def build_graph(idx: PacketIndex) -> Graph:
    g = Graph()
    a = get_analysis(idx)
    d = idx.data

    for doc in d["documents"]:
        g.add_node(Node(doc["id"], "Document", doc["title"], None, {
            "document_type": doc["document_type"], "page_count": doc["page_count"],
            "extraction": doc["extraction"]["status"], "marked_corrected": bool(doc.get("marked_corrected")),
        }))
        for p in doc["pages"]:
            pid = f"doc:{doc['id']}#page{p['page']}"
            g.add_node(Node(pid, "Page", f"{doc['id']} page {p['page']}", None,
                            {"document_id": doc["id"], "page": p["page"]}))
            g.add_edge(Edge(doc["id"], pid, "SOURCE_OF"))

    for ev in d["extracted_values"]:
        flags = [f.as_dict() for f in a.value_flags.get(ev["id"], ())]
        g.add_node(Node(ev["id"], "ExtractedValue", ev["label"], _value_display(ev), {
            "document_id": ev["document_id"], "page": ev["page"], "field": ev["field"],
            "confidence": ev["confidence"], "value_type": ev["value_type"], "flags": flags,
        }))
        g.add_edge(Edge(f"doc:{ev['document_id']}#page{ev['page']}", ev["id"], "SOURCE_OF"))

    rules = d["engine_reference"]["rules"]
    for rid, desc in rules.items():
        g.add_node(Node(f"rule:{rid}", "CalculationRule", rid, None, {"description": desc}))

    for version in d["return_versions"]:
        vid = version["version"]
        for line in version["lines"]:
            lid = f"line:{vid}:{line['key']}"
            g.add_node(Node(lid, "ReturnLine", line["label"], line["value"], {
                "version": vid, "key": line["key"], "form": line["form"], "jurisdiction": line["jurisdiction"],
                "rule": line.get("rule"), "area": area_for_line(line), "note": line.get("note"),
                "headline": HEADLINE_KEYS.get(line["key"]),
            }))
        for line in version["lines"]:
            lid = f"line:{vid}:{line['key']}"
            for inp in line.get("inputs", ()):
                g.add_edge(Edge(f"line:{vid}:{inp}", lid, "INPUT_TO"))
            for src in line.get("sources", ()):
                node = _ensure_ref_node(g, idx, src, vid)
                if node:
                    g.add_edge(Edge(node, lid, "SOURCE_OF"))
            if line.get("rule") and f"rule:{line['rule']}" in g.nodes:
                g.add_edge(Edge(lid, f"rule:{line['rule']}", "CALCULATED_FROM"))
            counterpart = prior_value(idx, line["key"])
            if counterpart:
                py = f"py:/return_2024/lines/{counterpart['key']}"
                same = counterpart["key"] == line["key"]
                if _ensure_ref_node(g, idx, py, vid):
                    g.add_edge(Edge(py, lid, "RELATED_TO", "packet",
                                    "same line on the 2024 return" if same else f"2024 counterpart ({counterpart['key']}, matched by meaning)"))
        for dg in version["diagnostics"]:
            did = f"diag:{vid}:{dg['code']}"
            g.add_node(Node(did, "EngineDiagnostic", dg["code"], None,
                            {"version": vid, "severity": dg["severity"], "message": dg["message"]}))
            for ref in dg["refs"]:
                node = _ensure_ref_node(g, idx, ref, vid)
                if node:
                    g.add_edge(Edge(did, node, "RELATED_TO", "packet", "engine diagnostic"))

    # Things people cite even when no engine line does: everything the client said, the household,
    # the season's events, the whole 2024 return, agency notices and e-file submissions.
    cur = idx.current_version
    for ref in [*idx.questions_by_id, *idx.messages_by_id, *idx.call_notes_by_id,
                *(f"household:{pid}" for pid in idx.people_by_id),
                *(f"py:/return_2024/lines/{k}" for k in idx.prior_year_values),
                *(f"agency:/notices/{i}" for i in range(len(d["tax_agency_records"].get("notices", ())))),
                *(f"agency:/efile/{i}" for i in range(len(d["tax_agency_records"].get("efile", ()))))]:
        _ensure_ref_node(g, idx, ref, cur)
    for t in d["timeline"]:
        tid = f"timeline:{t['id']}"
        g.add_node(Node(tid, "TimelineEvent", t["event"], None, {"at": t["at"], "actor": t["actor"]}))
        for ref in t["refs"]:
            target = f"line:{ref}:F1040.24" if ref in idx.versions_by_id else ref
            if target.startswith("line:") or _ensure_ref_node(g, idx, ref, cur):
                g.add_edge(Edge(tid, target, "RELATED_TO", "packet", "timeline reference"))
    for i, n in enumerate(d["tax_agency_records"].get("notices", ())):
        if n.get("document") in g.nodes:
            g.add_edge(Edge(n["document"], f"agency:/notices/{i}", "SOURCE_OF"))

    # Prior-year return lines are supported by the 2024 return's extracted values (D06).
    for key, pv in idx.prior_year_values.items():
        if pv["source"] and pv["source"] in g.nodes:
            py = f"py:/return_2024/lines/{key}"
            if _ensure_ref_node(g, idx, py, idx.current_version):
                g.add_edge(Edge(pv["source"], py, "SOURCE_OF"))

    # Deterministic evidence analysis (Iteration 2) becomes edges.
    for doc_id, rel in a.corrected_pairs.items():
        if "corrects" in rel:
            g.add_edge(Edge(doc_id, rel["corrects"], "SUPERSEDES", "analysis", "issuer-corrected form"))
    for doc_id, rels in a.duplicate_documents.items():
        for rel in rels:
            if "duplicate_of" in rel:
                g.add_edge(Edge(doc_id, rel["duplicate_of"], "DUPLICATE_OF", "analysis",
                                f"{rel['overlap']:.0%} of readings identical"))
    for doc_id, dups in a.duplicate_pages.items():
        for dp in dups:
            p1, p2 = dp["pages"]
            g.add_edge(Edge(f"doc:{doc_id}#page{p2}", f"doc:{doc_id}#page{p1}", "DUPLICATE_OF", "analysis",
                            f"same sheet: values {dp['value_overlap']:.0%}, text {dp['text_similarity']:.0%} alike"))
    ssn_owner = {p["ssn"]: p["id"] for p in d["household"]["people"] if p.get("ssn")}
    for ev_id, flags in a.value_flags.items():
        ev = idx.values_by_id[ev_id]
        for f in flags:
            if f.code == "IDENTITY_MISMATCH":
                # Match the person by last four of the organizer SSN where possible, else by name on the page.
                owner = next((pid for s, pid in ssn_owner.items() if s[:6] == str(ev["value"])[:6]), None)
                target = f"household:{owner}" if owner else None
                if target and _ensure_ref_node(g, idx, target, idx.current_version):
                    g.add_edge(Edge(ev_id, target, "CONFLICTS_WITH", "analysis", f.message))
            elif f.severity == "conflict":
                g.add_edge(Edge(ev_id, f"doc:{ev['document_id']}#page{ev['page']}", "CONFLICTS_WITH",
                                "analysis", f.message))
    return g


_CACHE: dict[str, Graph] = {}


def get_graph(idx: PacketIndex) -> Graph:
    if idx.packet.sha256 not in _CACHE:
        _CACHE[idx.packet.sha256] = build_graph(idx)
    return _CACHE[idx.packet.sha256]


# ---- traversal -------------------------------------------------------------------------------------

def closure(view: GraphView, root: str, direction: str) -> dict[str, int]:
    """Every node reachable along evidence-flow edges, with its shortest distance from the root."""
    dist = {root: 0}
    q = deque([root])
    while q:
        n = q.popleft()
        edges = view.incoming(n) if direction == "up" else view.outgoing(n)
        for e in edges:
            if e.type not in FLOW:
                continue
            nxt = e.src if direction == "up" else e.dst
            if nxt not in dist:
                dist[nxt] = dist[n] + 1
                q.append(nxt)
    return dist


def subgraph(view: GraphView, root: str, direction: str, *, depth: int = 3, max_children: int = 10,
             max_per_level: int = 14, expand: set[str] | None = None,
             include_rules: bool = True) -> dict[str, Any]:
    """A bounded, explorable slice of the graph around `root`.

    Breadth-first along flow edges up to `depth`; a node with more than `max_children` flow neighbours
    shows the first few and one collapsed group node with the rest, and no column grows past
    `max_per_level` (overflow joins the parent's group) so the picture stays legible. Nodes in
    `expand` are always opened fully, whatever the budgets (that is how the UI drills down). Annotation edges between visible nodes are added,
    plus verification, rule, duplicate, supersession and conflict neighbours of visible nodes.
    """
    expand = expand or set()
    level = {root: 0}
    per_level: dict[int, int] = defaultdict(int)
    visible = [root]
    edges: list[Edge] = []
    groups: list[dict[str, Any]] = []
    q = deque([root])
    while q:
        n = q.popleft()
        opened = n in expand
        if level[n] >= depth and not opened:
            continue
        flow = [e for e in (view.incoming(n) if direction == "up" else view.outgoing(n)) if e.type in FLOW]
        flow.sort(key=lambda e: _sort_key(view, e.src if direction == "up" else e.dst))
        limit = len(flow) if opened else max_children
        hidden = []
        for i, e in enumerate(flow):
            nxt = e.src if direction == "up" else e.dst
            if nxt in level:  # already drawn elsewhere: just connect it
                edges.append(e)
                continue
            if not opened and (i >= limit or per_level[level[n] + 1] >= max_per_level):
                hidden.append(e)
                continue
            edges.append(e)
            level[nxt] = level[n] + 1
            per_level[level[nxt]] += 1
            visible.append(nxt)
            q.append(nxt)
        if hidden:
            gid = f"group:{n}"
            kinds = defaultdict(int)
            for e in hidden:
                other = view.node(e.src if direction == "up" else e.dst)
                kinds[other.kind if other else "unknown"] += 1
            groups.append({"id": gid, "parent": n, "count": len(hidden), "kinds": dict(kinds), "level": level[n] + 1})

    vis = set(visible)
    # Annotations among / around visible nodes; each remembers the visible node it hangs off.
    extra: list[str] = []
    anchor: dict[str, str] = {}
    for n in list(visible):
        for e in view.outgoing(n) + view.incoming(n):
            if e.type in FLOW:
                continue
            other = e.dst if e.src == n else e.src
            if e.type == "CALCULATED_FROM" and not include_rules:
                continue
            if e.type == "RELATED_TO" and e.origin == "packet" and other not in vis:
                continue  # diagnostics / prior-year counterparts only when already in view
            if other not in vis and other not in extra:
                extra.append(other)
                anchor[other] = n
            if e not in edges:
                edges.append(e)
    for x in extra:
        level[x] = level[anchor[x]]
    nodes = []
    for nid in visible + extra:
        node = view.node(nid)
        if node is None:
            continue
        d = node.as_dict()
        d["level"] = level[nid]
        d["annotation"] = nid in extra
        d["anchor"] = anchor.get(nid)
        d["has_more"] = _has_unshown(view, nid, direction, vis) if nid not in extra else False
        nodes.append(d)
    return {"root": root, "direction": direction, "nodes": nodes, "edges": [e.as_dict() for e in _dedupe(edges)],
            "groups": groups}


def _dedupe(edges: list[Edge]) -> list[Edge]:
    seen, out = set(), []
    for e in edges:
        k = (e.src, e.dst, e.type)
        if k not in seen:
            seen.add(k)
            out.append(e)
    return out


def _has_unshown(view: GraphView, nid: str, direction: str, vis: set[str]) -> bool:
    flow = view.incoming(nid) if direction == "up" else view.outgoing(nid)
    return any(e.type in FLOW and (e.src if direction == "up" else e.dst) not in vis for e in flow)


_KIND_ORDER = {"ReturnLine": 0, "ExtractedValue": 1, "Page": 2, "Document": 3}


def _sort_key(view: GraphView, ref: str) -> tuple:
    n = view.node(ref)
    return (_KIND_ORDER.get(n.kind, 5) if n else 9, ref)


# ---- proof footprint / impact ----------------------------------------------------------------------

def footprint(idx: PacketIndex, view: GraphView, root: str) -> dict[str, Any]:
    """What a number ultimately rests on — untruncated, so it can be trusted even when the picture is not."""
    dist = closure(view, root, "up")
    a = get_analysis(idx)
    kinds = defaultdict(int)
    docs: dict[str, set[int]] = defaultdict(set)
    values = []
    for ref in dist:
        node = view.node(ref)
        if not node or ref == root:
            continue
        kinds[node.kind] += 1
        if node.kind == "ExtractedValue":
            values.append(ref)
            docs[node.meta["document_id"]].add(node.meta["page"])
    flagged = [
        {"ref": v, "label": view.node(v).label, "document_id": view.node(v).meta["document_id"],
         "page": view.node(v).meta["page"], **f.as_dict()}
        for v in values for f in a.value_flags.get(v, ())
    ]
    dup_pages = [
        {"document_id": doc, "pages": dp["pages"]}
        for doc, pages in docs.items() for dp in a.duplicate_pages.get(doc, ())
        if set(dp["pages"]) <= pages
    ]
    verified = {v for v in values if any(e.type == "VERIFIED_BY" for e in view.outgoing(v))}
    lines = [r for r in dist if r.startswith("line:") and r != root]
    verified_lines = {r for r in lines if any(e.type == "VERIFIED_BY" for e in view.outgoing(r))}
    low_conf = [v for v in values if view.node(v).meta["confidence"] < 0.9]
    return {
        "counts": dict(kinds),
        "lines": len(lines),
        "values": len(values),
        "documents": [{"id": doc, "title": idx.documents_by_id[doc]["title"], "pages": sorted(p)}
                      for doc, p in sorted(docs.items())],
        "verified_values": len(verified),
        "verified_lines": len(verified_lines),
        "flags": flagged,
        "duplicate_pages_in_evidence": dup_pages,
        "low_confidence_values": low_conf,
        "max_depth": max(dist.values()) if dist else 0,
    }


def impact(idx: PacketIndex, view: GraphView, root: str, version: str) -> dict[str, Any]:
    """Every return line in `version` that would have to be recomputed if `root` changed, ring by ring.
    (An extracted value can feed several versions; `by_version` reports all of them.)"""
    dist = closure(view, root, "down")
    rings: dict[int, list[dict[str, Any]]] = defaultdict(list)
    by_area: dict[str, int] = defaultdict(int)
    by_version: dict[str, int] = defaultdict(int)
    headlines = []
    for ref, dd in dist.items():
        if ref == root or not ref.startswith("line:"):
            continue
        node = view.node(ref)
        by_version[node.meta["version"]] += 1
        if node.meta["version"] != version:
            continue
        rings[dd].append({"id": ref, "key": node.meta["key"], "label": node.label, "value": node.value,
                          "version": node.meta["version"], "area": node.meta["area"]})
        by_area[node.meta["area"]] += 1
        if node.meta.get("headline"):
            headlines.append({"id": ref, "key": node.meta["key"], "label": node.meta["headline"],
                              "value": node.value, "version": node.meta["version"], "distance": dd})
    total = sum(len(v) for v in rings.values())
    return {
        "root": root,
        "version": version,
        "affected_lines": total,
        "by_version": dict(by_version),
        "by_area": dict(sorted(by_area.items(), key=lambda kv: -kv[1])),
        "headlines": sorted(headlines, key=lambda h: h["distance"]),
        "rings": [{"distance": dd, "lines": sorted(v, key=lambda x: x["id"])} for dd, v in sorted(rings.items())],
    }


def graph_stats(g: Graph) -> dict[str, Any]:
    kinds: dict[str, int] = defaultdict(int)
    for n in g.nodes.values():
        kinds[n.kind] += 1
    etypes: dict[str, int] = defaultdict(int)
    for es in g.out_edges.values():
        for e in es:
            etypes[e.type] += 1
    return {"nodes": len(g.nodes), "edges": g.edge_count(), "node_kinds": dict(kinds), "edge_types": dict(etypes)}
