"""Adjustments API: create, apply, undo, restore, approve — one at a time or in bulk, with history."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..deps import Ctx, require
from ..models import Adjustment, User
from ..packet.refs import resolve
from ..security.masking import mask_payload
from ..security.roles import Perm
from ..services import audit
from ..services import adjustments as A
from ..services.assurance import challenge
from .collaboration import evidence_kind, guard_escalation, reopen
from .locks import assert_return_editable

router = APIRouter(prefix="/api/adjustments")


def _names(c: Ctx) -> dict[str, str]:
    return {u.id: u.name for u in c.db.scalars(select(User)).all()}


def _dict(a: Adjustment, names: dict[str, str]) -> dict:
    return mask_payload({
        "id": a.id, "version": a.version, "target_line": a.target_line, "original_value": a.original_value,
        "adjusted_value": a.adjusted_value, "difference": a.difference, "unit": a.unit, "reason": a.reason,
        "evidence_refs": a.evidence_refs, "finding_id": a.finding_id, "status": a.status,
        "review_required": a.review_required, "effect": a.effect,
        "created_by": names.get(a.created_by_id), "created_by_id": a.created_by_id, "created_by_role": a.created_by_role,
        "created_at": a.created_at, "approved_by": names.get(a.approved_by_id or ""), "approved_at": a.approved_at,
        "history": [h | {"by_name": names.get(h["by"])} for h in a.history], "line": None,
    })


def _active_for_line(c: Ctx, version: str, key: str, exclude: int | None = None) -> Adjustment | None:
    stmt = select(Adjustment).where(Adjustment.engagement_id == c.engagement.id, Adjustment.version == version,
                                    Adjustment.target_line == key, Adjustment.status.in_(A.ACTIVE))
    return next((a for a in c.db.scalars(stmt).all() if a.id != exclude), None)


def _overlapping(c: Ctx, version: str, key: str, exclude: int | None = None) -> Adjustment | None:
    """An active adjustment on a line in the same flow path as `key` (see `flow_related`)."""
    related = A.flow_related(c.idx, version, key)
    stmt = select(Adjustment).where(Adjustment.engagement_id == c.engagement.id, Adjustment.version == version,
                                    Adjustment.status.in_(A.ACTIVE), Adjustment.target_line.in_(related))
    return next((a for a in c.db.scalars(stmt.order_by(Adjustment.id)).all() if a.id != exclude), None)


def _overlap_message(key: str, other: Adjustment, c: Ctx) -> str:
    downstream = other.target_line in A.flows_into(c.idx, other.version, key)
    how = f"{other.target_line} is computed from {key}" if downstream else f"{key} is computed from {other.target_line}"
    return (f"{how}, and {other.target_line} already has active adjustment #{other.id} ({other.status}). Adjusting both "
            f"would count one correction twice; undo #{other.id} first or adjust only one of them.")


def _load(c: Ctx, adj_id: int) -> Adjustment:
    a = c.db.get(Adjustment, adj_id)
    if a is None or a.engagement_id != c.engagement.id:
        raise HTTPException(404, "Adjustment not found.")
    return a


class AdjustmentCreate(BaseModel):
    target_line: str = Field(min_length=1, max_length=60)
    adjusted_value: float
    reason: str = Field(min_length=3, max_length=4000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=30)
    finding_id: str | None = None
    apply: bool = False


class FromFinding(BaseModel):
    finding_id: str
    reason: str | None = Field(default=None, max_length=4000)
    apply: bool = False


class Action(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


class Bulk(BaseModel):
    action: Literal["apply", "undo", "restore", "approve"]
    ids: list[int] = Field(min_length=1, max_length=200)
    note: str | None = Field(default=None, max_length=2000)


def _create(c: Ctx, key: str, adjusted: float, reason: str, evidence: list[str], finding_id: str | None,
            apply: bool) -> tuple[Adjustment, list[dict]]:
    v = c.idx.current_version
    assert_return_editable(c, "adjusting the return")
    guard_escalation(c, [f"finding:{finding_id}" if finding_id else None], "act on this finding")
    try:
        line = A.validate_target(c.idx, v, key)
    except A.AdjustmentError as e:
        raise HTTPException(e.status, str(e))
    for ref in evidence:
        evidence_kind(c, ref)
    if _active_for_line(c, v, key):
        raise HTTPException(409, f"{key} already has an active adjustment; undo it first.")
    if other := _overlapping(c, v, key):
        raise HTTPException(409, _overlap_message(key, other, c))
    original = float(line["value"])
    diff = round(adjusted - original, 2)
    if diff == 0:
        raise HTTPException(422, "The adjusted value equals the engine value.")
    effect = A.estimate_effect(c.idx, v, key, diff)
    a = Adjustment(engagement_id=c.engagement.id, version=v, target_line=key, original_value=original, adjusted_value=adjusted,
                   difference=diff, unit=A.unit_of(c.idx, v, key), reason=reason, evidence_refs=evidence, finding_id=finding_id,
                   status="proposed", review_required=A.review_required(effect), effect=effect,
                   created_by_id=c.user.id, created_by_role=c.user.role,
                   history=[A.history_entry("create", c.user.id, c.user.role, reason)])
    c.db.add(a)
    c.db.flush()
    audit.record(c.db, c.engagement.id, "adjustment.created", actor_id=c.user.id, actor_role=c.user.role,
                 target_ref=f"line:{v}:{key}", payload={"adjustment_id": a.id, "original": original, "adjusted": adjusted,
                                                         "finding_id": finding_id, "effect": effect})
    return a, (_transition(c, a, "apply", None) if apply else [])


def _transition(c: Ctx, a: Adjustment, action: str, note: str | None) -> list[dict]:
    """Apply one state change. Returns the sign-offs it reopened."""
    previous = a.status
    assert_return_editable(c, f"{action} on an adjustment")
    # Applying or restoring handles the finding it came from; approving or undoing handles the approval item.
    guard_escalation(c, [f"finding:{a.finding_id}" if a.finding_id and action in ("apply", "restore") else None,
                         f"adjustment:{a.id}" if action in ("approve", "undo") else None], f"{action} this adjustment")
    if action == "approve":
        if a.status == "undone":
            raise HTTPException(409, f"Adjustment {a.id} is undone; restore it before approving.")
        if a.created_by_id == c.user.id:
            raise HTTPException(403, "A person may not review or sign off on work they prepared.")
        if not A.can_approve(c.user.role, a.review_required):
            raise HTTPException(403, f"Adjustment {a.id} needs {a.review_required} approval "
                                     f"(tax effect {'over' if a.review_required == 'partner' else 'within'} the firm's partner threshold).")
        if a.approved_by_id:
            raise HTTPException(409, f"Adjustment {a.id} is already approved.")
        a.approved_by_id, a.approved_at = c.user.id, datetime.now(timezone.utc)
    else:
        allowed, result = A.TRANSITIONS[action]
        if a.status not in allowed:
            raise HTTPException(409, f"Cannot {action} adjustment {a.id}: it is {a.status}.")
        if a.created_by_id != c.user.id and c.user.role not in ("reviewer", "partner"):
            raise HTTPException(403, "Only the preparer of an adjustment or a reviewer can change its state.")
        if result == "applied" and _active_for_line(c, a.version, a.target_line, exclude=a.id):
            raise HTTPException(409, f"{a.target_line} already has another active adjustment.")
        if result == "applied" and (other := _overlapping(c, a.version, a.target_line, exclude=a.id)):
            raise HTTPException(409, _overlap_message(a.target_line, other, c))
        if action == "restore" and a.version != c.idx.current_version:
            raise HTTPException(409, f"Adjustment {a.id} targets superseded {a.version}.")
        a.status = result
        if action == "restore":
            # A restored adjustment is a new decision: it needs approval again (the old one stays in history).
            a.approved_by_id, a.approved_at = None, None
    a.history = list(a.history) + [A.history_entry(action, c.user.id, c.user.role, note)]
    audit.record(c.db, c.engagement.id, f"adjustment.{action}", actor_id=c.user.id, actor_role=c.user.role,
                 target_ref=f"line:{a.version}:{a.target_line}", payload={"adjustment_id": a.id, "status": a.status, "note": note})
    if action in ("apply", "undo", "restore") and not (action == "undo" and previous == "proposed"):
        # The workpaper value of this line changed: sign-offs over its area no longer attest to it.
        verb = {"apply": "applied", "undo": "undone", "restore": "restored"}[action]
        diff = f"{A.fmt_unit(a.original_value, a.unit)} → {A.fmt_unit(a.adjusted_value, a.unit)}"
        return reopen(c, [f"line:{a.version}:{a.target_line}"], f"adjustment.{action}",
                      f"Adjustment #{a.id} {verb} on {a.target_line} ({diff}) by {c.user.name}.", f"line:{a.version}:{a.target_line}")
    return []


def _summary(c: Ctx, version: str) -> dict:
    applied = c.db.scalars(select(Adjustment).where(Adjustment.engagement_id == c.engagement.id,
                                                    Adjustment.version == version, Adjustment.status == "applied")).all()
    return A.workpaper_summary(c.idx, version, list(applied))


@router.get("")
def list_adjustments(status: str | None = None, line: str | None = None, c: Ctx = Depends(require(Perm.VIEW_INTERNAL_NOTES))):
    v = c.idx.current_version
    stmt = select(Adjustment).where(Adjustment.engagement_id == c.engagement.id)
    if status:
        stmt = stmt.where(Adjustment.status == status)
    if line:
        stmt = stmt.where(Adjustment.target_line == line)
    names = _names(c)
    rows = [_dict(a, names) for a in c.db.scalars(stmt.order_by(Adjustment.id.desc())).all()]
    for r in rows:
        ln = c.idx.line(r["version"], r["target_line"])
        r["line"] = {"label": ln["label"], "form": ln["form"]} if ln else None
    return {"version": v, "adjustments": rows, "summary": _summary(c, v)}


@router.get("/effective/{key}")
def effective(key: str, c: Ctx = Depends(require(Perm.VIEW_RETURN))):
    """The engine value, the effective workpaper value, and the adjustment that bridges them."""
    v = c.idx.current_version
    line = c.idx.line(v, key)
    if line is None:
        raise HTTPException(404, f"Line '{key}' is not in {v}.")
    names = _names(c)
    adjs = c.db.scalars(select(Adjustment).where(Adjustment.engagement_id == c.engagement.id, Adjustment.version == v,
                                                 Adjustment.target_line == key).order_by(Adjustment.id.desc())).all()
    applied = next((a for a in adjs if a.status == "applied"), None)
    internal = c.can(Perm.VIEW_INTERNAL_NOTES)
    return {"version": v, "key": key, "engine_value": line["value"],
            "effective_value": applied.adjusted_value if applied else line["value"],
            "adjusted": applied is not None,
            "adjustments": [_dict(a, names) for a in adjs] if internal else []}


@router.post("", status_code=201)
def create(body: AdjustmentCreate, c: Ctx = Depends(require(Perm.ADJUST))):
    a, reopened = _create(c, body.target_line, body.adjusted_value, body.reason, body.evidence_refs, body.finding_id, body.apply)
    c.db.commit()
    return _dict(a, _names(c)) | {"reopened_signoffs": mask_payload(reopened)}


@router.post("/from-finding", status_code=201)
def from_finding(body: FromFinding, c: Ctx = Depends(require(Perm.ADJUST))):
    """Turn a Challenge finding into an adjustment: its independent value becomes the proposed value."""
    v = c.idx.current_version
    f = next((x for x in challenge(c.idx, v) if x.id == body.finding_id), None)
    if f is None:
        raise HTTPException(404, f"No finding '{body.finding_id}' in {v}.")
    proposal = f.proposed_adjustment
    if proposal is None:
        raise HTTPException(422, "This finding cannot be expressed as a change to one line: judgment items need a recorded "
                                 "judgment (Iteration 7), and findings like a missing sale need the engine input corrected.")
    line = c.idx.line(v, proposal["line"])
    if not f.adjust and (line is None or not isinstance(line["value"], (int, float))
                         or abs(float(line["value"]) - float(f.engine["value"])) > 0.5):
        # Guard: a derived proposal must replace exactly the value the finding says the engine has on that line.
        raise HTTPException(422, f"The finding's engine value does not match {proposal['line']}; adjust the line directly.")
    reason = body.reason or f"{f.title}. {f.summary}"
    a, reopened = _create(c, proposal["line"], float(proposal["value"]), reason[:4000], [r for r in f.evidence if resolve(c.idx, r, v).exists],
                          f.id, body.apply)
    c.db.commit()
    return _dict(a, _names(c)) | {"reopened_signoffs": mask_payload(reopened)}


@router.post("/{adj_id}/{action}")
def act(adj_id: int, action: Literal["apply", "undo", "restore", "approve"], body: Action | None = None,
        c: Ctx = Depends(require(Perm.ADJUST))):
    a = _load(c, adj_id)
    reopened = _transition(c, a, action, body.note if body else None)
    c.db.commit()
    return _dict(a, _names(c)) | {"reopened_signoffs": mask_payload(reopened)}


@router.post("/bulk")
def bulk(body: Bulk, c: Ctx = Depends(require(Perm.ADJUST))):
    """All or nothing: if any adjustment cannot take the action, none of them changes."""
    if len(set(body.ids)) != len(body.ids):
        raise HTTPException(422, "Each adjustment may appear only once in a bulk action.")
    # One transaction, no savepoints: `_transition` raises before it changes anything, so a failed item
    # leaves no trace, and rolling back the whole transaction undoes the items that succeeded before it.
    # (Savepoints were unsafe here: under pysqlite a SAVEPOINT opened outside a transaction is released
    # as a commit, so an earlier item survived the rollback.)
    errors, reopened = [], []
    for adj_id in body.ids:
        try:
            reopened += _transition(c, _load(c, adj_id), body.action, body.note)
        except HTTPException as e:
            errors.append({"id": adj_id, "status": e.status_code, "detail": e.detail})
    if errors:
        c.db.rollback()
        raise HTTPException(409, {"message": f"No adjustments changed: {len(errors)} of {len(body.ids)} cannot take '{body.action}'.",
                                  "errors": errors})
    audit.record(c.db, c.engagement.id, "adjustment.bulk", actor_id=c.user.id, actor_role=c.user.role,
                 payload={"action": body.action, "ids": body.ids})
    c.db.commit()
    names = _names(c)
    return {"action": body.action, "changed": [_dict(c.db.get(Adjustment, i), names) for i in body.ids], "reopened_signoffs": mask_payload(reopened)}
