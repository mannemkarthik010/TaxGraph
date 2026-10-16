"""Uncertainty Inbox: everything that still needs a human decision, in one place.

Items are *derived* — nothing is copied — from:
  review notes · TaxProof Challenge findings (fail / needs judgment) · engine diagnostics no finding
  already covers · adjustments and judgments awaiting approval · client questions.
Each item has a stable key (`finding:<id>`, `note:<id>`, `diag:<code>`, `adjustment:<id>`,
`judgment:<id>`, `question:<id>`). People's decisions about an item live in `issues` (assignment,
escalation, resolution); some dispositions are derived — an applied adjustment made from a finding, a
judgment recorded about it, an accepted client answer that resolves it.

Groups (each open item is in exactly one):
  blockers   – firm rules that stop filing outright: open blocking review notes, escalations, adjustments
               needing partner approval, client questions marked as needed before filing;
  conflicts  – sources or the engine disagree (TaxProof findings that failed, questionnaire contradictions);
  missing    – evidence that is not in the file (unread pages, absent documents, unprovable basis);
  judgment   – professional judgment calls (findings that need judgment, engine diagnostics asking for a
               decision, recorded judgments awaiting review);
  questions  – client questions awaiting an answer or the firm's acceptance;
  review     – review notes and adjustments awaiting reviewer approval.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Adjustment, ClientQuestion, Issue, Judgment, WorkpaperNote
from ..packet.index import PacketIndex
from ..security.masking import mask_payload, mask_text
from ..security.roles import Perm
from .area_summary import areas_for_ref
from .assurance import challenge
from .signoffs import areas_touched

GROUPS = (
    ("blockers", "Filing blockers"),
    ("conflicts", "Conflicts"),
    ("missing", "Missing evidence"),
    ("judgment", "Professional judgment"),
    ("questions", "Client questions"),
    ("review", "Review notes"),
)
GROUP_LABEL = dict(GROUPS)
MISSING_FAMILIES = {"completeness", "broker_detail"}
MISSING_CODE_WORDS = ("NOT_RECEIVED", "MISSING", "NOT_COMPUTED", "INCOMPLETE")


@dataclass
class Item:
    key: str
    source: str              # note | finding | diagnostic | adjustment | judgment | question
    nature: str              # the group it belongs to by its nature (before the blocker rule)
    title: str
    summary: str
    severity: str
    refs: list[str]
    areas: list[str]
    blocks_filing: bool = False
    blocking_reason: str | None = None
    status: str = "open"     # open | handled
    handled: dict[str, Any] | None = None   # {kind, label, id}
    escalated: bool = False
    escalation_note: str | None = None
    assignee_id: str | None = None
    links: dict[str, Any] = field(default_factory=dict)
    history: list[dict[str, Any]] = field(default_factory=list)
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def group(self) -> str:
        return "blockers" if self.blocks_filing and self.status == "open" else self.nature


def _finding_nature(f: Any) -> str:
    if f.family in MISSING_FAMILIES or (f.family == "basis" and f.status == "attention"):
        return "missing"
    if f.family == "questionnaire" or f.status == "fail":
        return "conflicts"
    return "judgment"


def _diag_nature(code: str) -> str:
    return "missing" if any(w in code for w in MISSING_CODE_WORDS) else "judgment"


def _line_refs(idx: PacketIndex, keys: list[str]) -> list[str]:
    v = idx.current_version
    lines = idx.return_lines_by_version[v]
    return [f"line:{v}:{k}" if k in lines else k for k in keys]


def build(db: Session, idx: PacketIndex, engagement_id: str) -> list[Item]:
    v = idx.current_version
    issues = {i.item_key: i for i in db.scalars(select(Issue).where(Issue.engagement_id == engagement_id)).all()}
    adjustments = db.scalars(select(Adjustment).where(Adjustment.engagement_id == engagement_id)).all()
    judgments = db.scalars(select(Judgment).where(Judgment.engagement_id == engagement_id)).all()
    questions = db.scalars(select(ClientQuestion).where(ClientQuestion.engagement_id == engagement_id)).all()
    q_by_item: dict[str, list[ClientQuestion]] = {}
    for q in questions:
        if q.item_key:
            q_by_item.setdefault(q.item_key, []).append(q)
    j_by_item: dict[str, list[Judgment]] = {}
    for j in judgments:
        if j.item_key and j.status != "superseded":
            j_by_item.setdefault(j.item_key, []).append(j)
    applied_by_finding = {a.finding_id: a for a in adjustments if a.finding_id and a.status == "applied"}

    items: list[Item] = []

    def disposition(item: Item) -> None:
        """Derived and recorded dispositions, in order of precedence."""
        issue = issues.get(item.key)
        if issue:
            item.escalated, item.escalation_note = issue.escalated, issue.escalation_note
            item.assignee_id, item.history = issue.assignee_id, list(issue.history)
            if issue.status in ("resolved", "accepted"):
                label = {"accepted": "Accepted with explanation", "client_answer": "Resolved by client answer"}.get(
                    issue.resolution_kind or issue.status, "Resolved")
                item.status, item.handled = "handled", {"kind": issue.resolution_kind or issue.status, "label": label,
                                                        "note": issue.resolution, "by": issue.resolved_by_id,
                                                        "at": issue.resolved_at.isoformat() if issue.resolved_at else None}
                return
        fid = item.links.get("finding_id")
        if fid and (a := applied_by_finding.get(fid)):
            item.status, item.handled = "handled", {"kind": "adjustment", "id": a.id, "label": f"Adjustment #{a.id} applied"}
            return
        if js := j_by_item.get(item.key):
            j = js[-1]
            item.status, item.handled = "handled", {"kind": "judgment", "id": j.id, "label": f"Judgment #{j.id} recorded ({j.status})"}

    def attach_links(item: Item) -> None:
        qs = q_by_item.get(item.key, [])
        item.links["questions"] = [{"id": q.id, "status": q.status} for q in qs]
        item.links["judgments"] = [{"id": j.id, "status": j.status} for j in j_by_item.get(item.key, [])]

    # Review notes (plain notes are conversation, not uncertainty).
    for n in db.scalars(select(WorkpaperNote).where(WorkpaperNote.engagement_id == engagement_id,
                                                    WorkpaperNote.kind == "review_note")).all():
        areas = areas_for_ref(idx, n.target_ref, v) | ({n.area_key} if n.area_key else set())
        it = Item(f"note:{n.id}", "note", "review", f"Review note on {n.target_ref}", n.body, "high" if n.blocking else "medium",
                  [n.target_ref], sorted(a for a in areas if a), blocks_filing=n.blocking,
                  blocking_reason="Open review notes block filing (firm rule)." if n.blocking else None,
                  detail={"note_id": n.id, "author_id": n.author_id, "created_at": n.created_at.isoformat()})
        attach_links(it)
        disposition(it)
        if n.status == "resolved":
            it.status, it.handled = "handled", {"kind": "resolved", "label": "Review note resolved", "note": n.resolution,
                                                "by": n.resolved_by_id, "at": n.resolved_at.isoformat() if n.resolved_at else None}
        items.append(it)

    # TaxProof findings and the engine diagnostics they do not already cover.
    findings = [f for f in challenge(idx, v) if f.status in ("fail", "attention")]
    covered = {d for f in challenge(idx, v) for d in f.engine_diagnostics}
    active_adj_by_finding = {a.finding_id: a for a in adjustments if a.finding_id and a.status in ("proposed", "applied")}
    for f in findings:
        refs = _line_refs(idx, f.lines) or list(f.evidence[:3])
        areas = areas_touched(idx, list(f.lines)) or areas_touched(idx, list(f.evidence))
        it = Item(f"finding:{f.id}", "finding", _finding_nature(f), f.title, f.summary, f.severity, refs, sorted(areas),
                  links={"finding_id": f.id},
                  detail={"status": f.status, "family": f.family, "lines": list(f.lines), "evidence": list(f.evidence[:8]),
                          "effect": f.effect, "proposed_adjustment": f.proposed_adjustment,
                          "active_adjustment": active_adj_by_finding[f.id].id if f.id in active_adj_by_finding else None,
                          "engine_diagnostics": list(f.engine_diagnostics)})
        attach_links(it)
        disposition(it)
        items.append(it)
    for d in idx.versions_by_id[v]["diagnostics"]:
        if d["severity"] != "warning" or d["code"] in covered:
            continue
        refs = _line_refs(idx, list(d["refs"]))
        it = Item(f"diag:{d['code']}", "diagnostic", _diag_nature(d["code"]), f"Engine diagnostic {d['code']}", d["message"],
                  "medium", refs, sorted(areas_touched(idx, list(d["refs"]))), detail={"code": d["code"]})
        attach_links(it)
        disposition(it)
        items.append(it)

    # Approvals the firm rules require.
    for a in adjustments:
        if a.status not in ("proposed", "applied") or a.approved_by_id:
            continue
        partner = a.review_required == "partner"
        eff = a.effect or {}
        it = Item(f"adjustment:{a.id}", "adjustment", "review",
                  f"Adjustment #{a.id} on {a.target_line} needs {a.review_required} approval",
                  f"{a.original_value:,.0f} → {a.adjusted_value:,.0f} ({a.status}). Estimated effect: federal "
                  f"{eff.get('federal', 0):+,.0f}, California {eff.get('california', 0):+,.0f}.",
                  "high" if partner else "medium", [f"line:{a.version}:{a.target_line}"],
                  sorted(areas_touched(idx, [f"line:{a.version}:{a.target_line}"])), blocks_filing=partner,
                  blocking_reason="Any adjustment with a tax effect over 1,000 requires partner sign-off (firm rule)." if partner else None,
                  links={"adjustment_id": a.id, "finding_id": None},
                  detail={"adjustment_id": a.id, "review_required": a.review_required, "created_by_id": a.created_by_id})
        disposition(it)
        items.append(it)
    for j in judgments:
        if j.status in ("superseded", "approved"):
            continue
        need = "reviewer" if j.status == "recorded" else "partner"
        it = Item(f"judgment:{j.id}", "judgment", "judgment", f"Judgment #{j.id} needs {need} review: {j.topic}",
                  j.decision, "high" if j.review_required == "partner" else "medium", list(j.target_refs), list(j.area_keys),
                  links={"judgment_id": j.id}, detail={"judgment_id": j.id, "status": j.status, "review_required": j.review_required,
                                                       "prepared_by_id": j.prepared_by_id})
        disposition(it)
        items.append(it)

    # Client questions.
    for q in questions:
        open_ = q.status in ("asked", "answered")
        it = Item(f"question:{q.id}", "question", "questions",
                  f"Client question #{q.id}" + (" — answered, awaiting review" if q.status == "answered" else ""),
                  q.question, "medium", [q.target_ref], sorted(areas_touched(idx, [q.target_ref])),
                  blocks_filing=q.blocking and open_,
                  blocking_reason="Marked as needed before filing when asked." if q.blocking else None,
                  links={"question_id": q.id, "item_key": q.item_key},
                  detail={"question_id": q.id, "status": q.status, "answer": q.answer, "blocking": q.blocking})
        if not open_:
            it.status, it.handled = "handled", {"kind": q.status, "label": "Answer accepted as evidence" if q.status == "accepted"
                                                else "Question withdrawn"}
        else:
            disposition(it)
        items.append(it)

    # Escalation turns any open item into a filing blocker until a partner decides it.
    for it in items:
        if it.escalated and it.status == "open":
            it.blocks_filing = True
            it.blocking_reason = "Escalated to the partner: blocks filing until the partner decides."
    return items


def actions_for(item: Item, perms: frozenset[Perm] | set[Perm], role: str) -> list[str]:
    """What this user may do with the item (the API enforces the same rules)."""
    if item.status != "open":
        return []
    out = []
    partner_only = item.escalated and role != "partner"
    can = lambda p: p in perms  # noqa: E731
    if item.source in ("finding", "diagnostic", "note"):
        if not partner_only:
            if item.source == "note":
                if can(Perm.RESOLVE_REVIEW_NOTE):
                    out.append("resolve")
            else:
                if can(Perm.CREATE_NOTE):
                    out.append("resolve")
                if can(Perm.RESOLVE_REVIEW_NOTE):
                    out.append("accept")
        if can(Perm.ASK_CLIENT):
            out.append("ask_client")
        if can(Perm.RECORD_JUDGMENT):
            out.append("record_judgment")
        if item.source == "finding" and can(Perm.ADJUST) and item.detail.get("proposed_adjustment") \
                and not item.detail.get("active_adjustment"):
            out.append("create_adjustment")
    if can(Perm.CREATE_NOTE):
        out.append("assign")
        if not item.escalated:
            out.append("escalate")
    return out


def as_dict(item: Item, names: dict[str, str], actions: list[str]) -> dict[str, Any]:
    return mask_payload({
        "key": item.key, "source": item.source, "group": item.group, "group_label": GROUP_LABEL[item.group],
        "nature": item.nature, "nature_label": GROUP_LABEL[item.nature], "title": mask_text(item.title),
        "summary": mask_text(item.summary), "severity": item.severity, "refs": item.refs, "areas": item.areas,
        "blocks_filing": item.blocks_filing and item.status == "open", "blocking_reason": item.blocking_reason,
        "status": item.status, "handled": item.handled, "escalated": item.escalated, "escalation_note": item.escalation_note,
        "assignee_id": item.assignee_id, "assignee": names.get(item.assignee_id or ""), "links": item.links,
        "history": [h | {"by_name": names.get(h.get("by"))} for h in item.history],
        "detail": item.detail, "actions": actions,
    })


def open_by_area(items: list[Item]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for it in items:
        if it.status == "open":
            for a in it.areas:
                out.setdefault(a, []).append(it.key)
    return out


def readiness(items: list[Item], board: list[dict[str, Any]]) -> dict[str, Any]:
    """Can this return be filed? Deterministic checks; every failing check names its items."""
    open_ = [i for i in items if i.status == "open"]

    def check(key: str, label: str, rows: list[Item]) -> dict[str, Any]:
        return {"key": key, "label": label, "ok": not rows, "count": len(rows),
                "items": [{"key": i.key, "title": mask_text(i.title), "reason": i.blocking_reason} for i in rows[:50]]}

    blocking_notes = [i for i in open_ if i.source == "note" and i.blocks_filing and not i.escalated]
    escalated = [i for i in open_ if i.escalated]
    approvals = [i for i in open_ if i.source in ("adjustment", "judgment") and not i.escalated]
    questions = [i for i in open_ if i.source == "question" and i.blocks_filing and not i.escalated]
    rest = [i for i in open_ if i not in blocking_notes + escalated + approvals + questions]
    incomplete = [{"key": a["key"], "title": a["title"],
                   "missing": [f"{lv['label']} {'reopened' if lv['status'] == 'reopened' else 'not signed'}"
                               for lv in a["levels"] if lv["status"] != "signed"]}
                  for a in board if not a["complete"]]
    checks = [
        check("blocking_notes", "No open blocking review notes", blocking_notes),
        check("escalations", "No escalations awaiting the partner", escalated),
        check("approvals", "Adjustments and judgments approved as the firm rules require", approvals),
        check("client_questions", "Client questions needed before filing are answered and accepted", questions),
        check("open_items", "Every finding, conflict, missing item and diagnostic dispositioned", rest),
        {"key": "signoffs", "label": "Every area prepared, reviewed and partner-signed", "ok": not incomplete,
         "count": len(incomplete), "areas": incomplete},
    ]
    return {"can_file": all(c["ok"] for c in checks), "checks": checks,
            "note": "Partner approval, ready-to-file and every e-file submission re-check these gates; the client must then approve exactly what the partner approved."}
