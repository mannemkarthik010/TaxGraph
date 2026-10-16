"""Evidence graph API: Prove It (upstream), where-it-goes (downstream), impact radius, human links."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..deps import Ctx, require
from ..models import Adjustment, ClientQuestion, EvidenceLink, Judgment, User, Verification
from ..security.masking import mask_payload, mask_text
from ..security.roles import Perm
from ..services import audit
from .collaboration import evidence_kind, reopen
from .locks import assert_not_frozen
from ..services.graph import (
    USER_LINK_TYPES, Edge, GraphView, Node, footprint, get_graph, graph_stats, impact, ref_node, subgraph,
)

router = APIRouter(prefix="/api/graph")


def _view(c: Ctx) -> GraphView:
    """Packet graph plus this engagement's workpaper overlay. Internal records only for firm staff."""
    base = get_graph(c.idx)
    nodes: list[Node] = []
    edges: list[Edge] = []
    if c.can(Perm.VIEW_INTERNAL_NOTES):
        names = {u.id: u.name for u in c.db.scalars(select(User)).all()}
        for v in c.db.scalars(select(Verification).where(Verification.engagement_id == c.engagement.id,
                                                         Verification.status == "active")).all():
            target = _normalize(c, v.target_ref, None, must_exist=False)
            if target not in base.nodes:
                continue
            vid = f"verification:{v.id}"
            nodes.append(Node(vid, "Verification", v.method.replace("_", " "), None, {
                "method": v.method, "by": names.get(v.verified_by_id), "role": v.verified_by_role,
                "at": v.verified_at.isoformat(), "note": v.note, "acknowledged_flags": v.acknowledged_flags,
            }))
            edges.append(Edge(target, vid, "VERIFIED_BY", "workpaper"))
            for ref in v.evidence_refs:
                edges.append(Edge(vid, ref, "CONFIRMED_BY", "workpaper"))  # kept if `ref` is in view (filtered below)
        # Adjustments: the line they change is ADJUSTED_BY them; they rest on their evidence.
        for adj in c.db.scalars(select(Adjustment).where(Adjustment.engagement_id == c.engagement.id,
                                                         Adjustment.status.in_(("proposed", "applied")))).all():
            target = f"line:{adj.version}:{adj.target_line}"
            if target not in base.nodes:
                continue
            aid = f"adjustment:{adj.id}"
            nodes.append(Node(aid, "Adjustment", f"{adj.status}: {adj.original_value:,.0f} → {adj.adjusted_value:,.0f}", adj.difference, {
                "status": adj.status, "reason": adj.reason[:200], "review_required": adj.review_required,
                "federal_effect": (adj.effect or {}).get("federal"), "california_effect": (adj.effect or {}).get("california"),
                "finding_id": adj.finding_id, "by": names.get(adj.created_by_id),
            }))
            edges.append(Edge(target, aid, "ADJUSTED_BY", "workpaper", adj.reason[:120]))
            for ref in adj.evidence_refs:
                edges.append(Edge(aid, ref, "RELATED_TO", "workpaper", "adjustment evidence"))
        # Judgments rest on the nodes they decide about; accepted client answers confirm the node they are about.
        for j in c.db.scalars(select(Judgment).where(Judgment.engagement_id == c.engagement.id,
                                                     Judgment.status != "superseded")).all():
            jid = f"judgment:{j.id}"
            targets = [_normalize(c, r, None, must_exist=False) for r in j.target_refs]
            targets = [t for t in targets if t in base.nodes]
            if not targets:
                continue
            nodes.append(Node(jid, "Judgment", j.topic[:80], None, {
                "status": j.status, "decision": j.decision[:200], "authority": j.authority[:200],
                "review_required": j.review_required, "federal_effect": (j.tax_effect or {}).get("federal"),
                "california_effect": (j.tax_effect or {}).get("california"), "by": names.get(j.prepared_by_id),
            }))
            for t in targets:
                edges.append(Edge(t, jid, "RELATED_TO", "workpaper", "professional judgment"))
            for ref in j.evidence_refs:
                edges.append(Edge(jid, ref, "RELATED_TO", "workpaper", "judgment evidence"))
        for q in c.db.scalars(select(ClientQuestion).where(ClientQuestion.engagement_id == c.engagement.id,
                                                           ClientQuestion.status == "accepted")).all():
            target = _normalize(c, q.target_ref, None, must_exist=False)
            if target not in base.nodes:
                continue
            qid = f"client_answer:{q.id}"
            nodes.append(Node(qid, "ClientAnswer", f"Client answer #{q.id}", None, {
                "question": mask_text(q.question[:300]), "answer": mask_text((q.answer or "")[:500]),
                "answered_by": names.get(q.answered_by_id or ""), "accepted_by": names.get(q.accepted_by_id or ""),
            }))
            edges.append(Edge(target, qid, "CONFIRMED_BY", "workpaper", "client answer accepted as evidence"))
        for link in c.db.scalars(select(EvidenceLink).where(EvidenceLink.engagement_id == c.engagement.id,
                                                            EvidenceLink.status == "active")).all():
            for end in (link.src_ref, link.dst_ref):
                if end not in base.nodes and (extra := ref_node(c.idx, end, c.idx.current_version)):
                    nodes.append(extra)
            edges.append(Edge(link.src_ref, link.dst_ref, link.type, "workpaper", link.note))
    # Evidence may be another overlay record (an accepted client answer); drop edges whose ends are not in view.
    present = set(base.nodes) | {n.id for n in nodes}
    edges = [e for e in edges if e.src in present and e.dst in present]
    # Overlay labels and metadata carry text people typed: mask all of it, whatever the record type.
    nodes = [replace(n, label=mask_text(n.label), meta=mask_payload(n.meta)) for n in nodes]
    edges = [replace(e, detail=mask_text(e.detail)) for e in edges]
    return GraphView(base, nodes, edges)


def _normalize(c: Ctx, ref: str, version: str | None, must_exist: bool = True) -> str:
    """Accept bare line keys (`SchC.9`) and `ev-…`/`D23`/… refs; return a graph node id."""
    version = version or c.idx.current_version
    if version not in c.idx.versions_by_id:
        raise HTTPException(404, f"Unknown return version '{version}'.")
    node_id = ref
    if not ref.startswith("line:") and ref in c.idx.return_lines_by_version.get(version, {}):
        node_id = f"line:{version}:{ref}"
    elif ref.startswith(("R-",)):
        node_id = f"rule:{ref}"
    if must_exist and node_id not in get_graph(c.idx).nodes and ref_node(c.idx, node_id, version) is None:
        raise HTTPException(404, f"'{ref}' is not a node in the evidence graph.")
    return node_id


def _ref_version(c: Ctx, ref: str, version: str | None) -> str:
    """The return version a reference should be read in.

    A `line:vN:KEY` reference carries its own version, which wins over the default. An explicit
    `version` that contradicts it is an error rather than a silent switch to another return.
    """
    m = re.match(r"^line:(v\d+):", ref)
    if m:
        if version and version != m.group(1):
            raise HTTPException(422, f"'{ref}' is a {m.group(1)} line but version={version} was requested.")
        return m.group(1)
    return version or c.idx.current_version


def _scope(c: Ctx, ref: str, version: str | None, view: GraphView) -> tuple[str, str]:
    """Resolve a traversal root against the same view the caller is shown — base packet graph plus this
    caller's workpaper overlay (verifications, links). A verification node is a valid root for staff;
    for a client, who has no overlay, it does not exist."""
    version = _ref_version(c, ref, version)
    nid = _normalize(c, ref, version, must_exist=False)
    if view.node(nid) is None:
        extra = ref_node(c.idx, nid, version)  # resolvable packet ref the graph has no node for yet
        if extra is None:
            raise HTTPException(404, f"'{ref}' is not a node in the evidence graph.")
        view.extra_nodes[nid] = extra
    return nid, version


def _expand(expand: str | None) -> set[str]:
    return {x for x in (expand or "").split(",") if x}


@router.get("/stats")
def stats(c: Ctx = Depends(require(Perm.VIEW_RETURN))):
    return graph_stats(get_graph(c.idx))


@router.get("/node")
def node(ref: str, version: str | None = None, c: Ctx = Depends(require(Perm.VIEW_RETURN))):
    view = _view(c)
    nid, _version_used = _scope(c, ref, version, view)
    n = view.node(nid)

    def neighbour(e: Edge, other: str) -> dict:
        o = view.node(other)
        return {**e.as_dict(), "other": other, "other_kind": o.kind if o else None,
                "other_label": o.label if o else None, "other_value": o.value if o else None}

    out = [neighbour(e, e.dst) for e in view.outgoing(nid)]
    inc = [neighbour(e, e.src) for e in view.incoming(nid)]
    return {**n.as_dict(), "outgoing": out[:200], "incoming": inc[:200],
            "outgoing_total": len(out), "incoming_total": len(inc)}


@router.get("/prove")
def prove(ref: str, version: str | None = None, depth: int = Query(4, ge=1, le=12),
          max_children: int = Query(8, ge=1, le=100), max_per_level: int = Query(14, ge=2, le=200),
          expand: str | None = None, rules: bool = True,
          c: Ctx = Depends(require(Perm.VIEW_RETURN))):
    view = _view(c)
    root, version = _scope(c, ref, version, view)
    sg = subgraph(view, root, "up", depth=depth, max_children=max_children, max_per_level=max_per_level,
                  expand=_expand(expand), include_rules=rules)
    return {**sg, "version": version, "footprint": footprint(c.idx, view, root)}


@router.get("/trace")
def trace(ref: str, version: str | None = None, depth: int = Query(4, ge=1, le=20),
          max_children: int = Query(8, ge=1, le=100), max_per_level: int = Query(14, ge=2, le=200),
          expand: str | None = None, c: Ctx = Depends(require(Perm.VIEW_RETURN))):
    view = _view(c)
    root, version = _scope(c, ref, version, view)
    sg = subgraph(view, root, "down", depth=depth, max_children=max_children, max_per_level=max_per_level,
                  expand=_expand(expand), include_rules=False)
    return {**sg, "version": version, "impact": impact(c.idx, view, root, version)}


@router.get("/impact")
def impact_radius(ref: str, version: str | None = None, c: Ctx = Depends(require(Perm.VIEW_RETURN))):
    view = _view(c)
    root, version = _scope(c, ref, version, view)
    return impact(c.idx, view, root, version)


# ---- human links -----------------------------------------------------------------------------------

class LinkCreate(BaseModel):
    src_ref: str = Field(min_length=1, max_length=160)
    dst_ref: str = Field(min_length=1, max_length=160)
    type: Literal["RELATED_TO", "CONFIRMED_BY", "CONFLICTS_WITH", "SUPERSEDES", "DUPLICATE_OF"]
    note: str = Field(min_length=1, max_length=2000)


class LinkRetire(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


def _link_dict(link: EvidenceLink, names: dict[str, str]) -> dict:
    return mask_payload({"id": link.id, "src_ref": link.src_ref, "dst_ref": link.dst_ref, "type": link.type, "note": link.note,
            "created_by": names.get(link.created_by_id), "created_by_role": link.created_by_role,
            "created_at": link.created_at, "status": link.status, "retired_reason": link.retired_reason})


@router.get("/links")
def list_links(ref: str | None = None, c: Ctx = Depends(require(Perm.VIEW_INTERNAL_NOTES))):
    stmt = select(EvidenceLink).where(EvidenceLink.engagement_id == c.engagement.id)
    if ref:
        stmt = stmt.where((EvidenceLink.src_ref == ref) | (EvidenceLink.dst_ref == ref))
    names = {u.id: u.name for u in c.db.scalars(select(User)).all()}
    return [_link_dict(x, names) for x in c.db.scalars(stmt.order_by(EvidenceLink.created_at.desc())).all()]


def _link_end(c: Ctx, ref: str, version: str | None) -> str:
    """A link end is a graph node, or an accepted client answer (workpaper evidence)."""
    if ref.startswith("client_answer:"):
        evidence_kind(c, ref)
        return ref
    return _normalize(c, ref, version)


@router.post("/links", status_code=201)
def create_link(body: LinkCreate, version: str | None = None, c: Ctx = Depends(require(Perm.CREATE_NOTE))):
    assert_not_frozen(c, "linking evidence")
    assert body.type in USER_LINK_TYPES
    src, dst = (_link_end(c, r, version) for r in (body.src_ref, body.dst_ref))
    if src == dst:
        raise HTTPException(422, "A node cannot be linked to itself.")
    dup = c.db.scalar(select(EvidenceLink).where(
        EvidenceLink.engagement_id == c.engagement.id, EvidenceLink.status == "active",
        EvidenceLink.src_ref == src, EvidenceLink.dst_ref == dst, EvidenceLink.type == body.type))
    if dup:
        raise HTTPException(409, "That link already exists.")
    link = EvidenceLink(engagement_id=c.engagement.id, src_ref=src, dst_ref=dst, type=body.type, note=body.note,
                        created_by_id=c.user.id, created_by_role=c.user.role)
    c.db.add(link)
    c.db.flush()
    audit.record(c.db, c.engagement.id, "evidence_link.created", actor_id=c.user.id, actor_role=c.user.role,
                 target_ref=src, payload={"link_id": link.id, "dst_ref": dst, "type": body.type})
    reopen(c, [src, dst], "evidence_link.created", f"{c.user.name} linked {src} {body.type} {dst}: {body.note}", src)
    c.db.commit()
    return _link_dict(link, {c.user.id: c.user.name})


@router.post("/links/{link_id}/retire")
def retire_link(link_id: int, body: LinkRetire, c: Ctx = Depends(require(Perm.CREATE_NOTE))):
    assert_not_frozen(c, "retiring evidence links")
    link = c.db.get(EvidenceLink, link_id)
    if link is None or link.engagement_id != c.engagement.id:
        raise HTTPException(404, "Link not found.")
    if link.status != "active":
        raise HTTPException(409, "Link already retired.")
    if link.created_by_id != c.user.id and not c.can(Perm.RESOLVE_REVIEW_NOTE):
        raise HTTPException(403, "Only the person who made the link or a reviewer can retire it.")
    link.status, link.retired_by_id, link.retired_at, link.retired_reason = (
        "retired", c.user.id, datetime.now(timezone.utc), body.reason)
    audit.record(c.db, c.engagement.id, "evidence_link.retired", actor_id=c.user.id, actor_role=c.user.role,
                 target_ref=link.src_ref, payload={"link_id": link.id, "reason": body.reason})
    reopen(c, [link.src_ref, link.dst_ref], "evidence_link.retired",
           f"{c.user.name} retired the link {link.src_ref} {link.type} {link.dst_ref}: {body.reason}", link.src_ref)
    c.db.commit()
    return _link_dict(link, {u.id: u.name for u in c.db.scalars(select(User)).all()})
