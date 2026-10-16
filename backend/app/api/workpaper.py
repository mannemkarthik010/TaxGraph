"""Workpaper records (Iteration 1: notes and review notes on any packet reference) + firm + audit."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..deps import Ctx, ctx, require
from ..models import AccessLog, AuditEvent, User, WorkpaperArea, WorkpaperNote
from ..packet.refs import resolve
from ..security.masking import mask_payload, mask_pin
from ..security.roles import ROLE_LABELS, Perm, Role
from ..services import audit, standards
from ..services.area_summary import areas_for_ref
from ..services.areas import AREAS_BY_KEY, area_for_line
from .collaboration import guard_escalation
from .locks import assert_not_frozen

router = APIRouter(prefix="/api")


def validate_target(c: Ctx, ref: str) -> str:
    """Workpaper records may only point at things that exist (packet refs, areas, the engagement)."""
    if ref == "engagement":
        return ref
    if ref.startswith("area:"):
        if ref[5:] not in AREAS_BY_KEY:
            raise HTTPException(422, f"Unknown area '{ref[5:]}'.")
        return ref
    if not resolve(c.idx, ref).exists:
        raise HTTPException(422, f"Reference '{ref}' does not resolve to anything in the packet.")
    return ref


def _area_of(c: Ctx, ref: str) -> str | None:
    if ref.startswith("area:"):
        return ref[5:]
    r = resolve(c.idx, ref)
    if r.kind == "return_line" and r.exists:
        return area_for_line(c.idx.line(r.detail["version"], r.detail["key"]))
    return None


def _note_dict(n: WorkpaperNote, names: dict[str, str]) -> dict:
    return mask_payload({
        "id": n.id, "target_ref": n.target_ref, "area_key": n.area_key, "kind": n.kind, "body": n.body,
        "visibility": n.visibility, "blocking": n.blocking, "status": n.status,
        "author_id": n.author_id, "author_name": names.get(n.author_id), "author_role": n.author_role,
        "created_at": n.created_at, "resolved_by_id": n.resolved_by_id,
        "resolved_by_name": names.get(n.resolved_by_id or ""), "resolved_at": n.resolved_at, "resolution": n.resolution,
    })


def _names(c: Ctx) -> dict[str, str]:
    return {u.id: u.name for u in c.db.scalars(select(User)).all()}


class NoteCreate(BaseModel):
    target_ref: str = Field(min_length=1, max_length=120)
    kind: Literal["note", "review_note"] = "note"
    body: str = Field(min_length=1, max_length=5000)
    blocking: bool | None = None
    visibility: Literal["internal", "client"] = "internal"


class NoteResolve(BaseModel):
    resolution: str = Field(min_length=1, max_length=5000)


@router.get("/workpaper/notes")
def list_notes(target_ref: str | None = None, status: str | None = None, c: Ctx = Depends(ctx)):
    stmt = select(WorkpaperNote).where(WorkpaperNote.engagement_id == c.engagement.id)
    if not c.can(Perm.VIEW_INTERNAL_NOTES):
        stmt = stmt.where(WorkpaperNote.visibility == "client")
    if target_ref:
        stmt = stmt.where(WorkpaperNote.target_ref == target_ref)
    if status:
        stmt = stmt.where(WorkpaperNote.status == status)
    names = _names(c)
    return [_note_dict(n, names) for n in c.db.scalars(stmt.order_by(WorkpaperNote.created_at.desc())).all()]


@router.post("/workpaper/notes", status_code=201)
def create_note(body: NoteCreate, c: Ctx = Depends(require(Perm.CREATE_NOTE))):
    assert_not_frozen(c, "adding notes")
    if body.kind == "review_note" and not c.can(Perm.CREATE_REVIEW_NOTE):
        raise HTTPException(403, "Only reviewers, partners and quality reviewers raise review notes.")
    ref = validate_target(c, body.target_ref)
    # Firm rule: open review notes block filing. Plain notes never block.
    blocking = body.kind == "review_note" if body.blocking is None else (body.blocking and body.kind == "review_note")
    note = WorkpaperNote(engagement_id=c.engagement.id, target_ref=ref, area_key=_area_of(c, ref), kind=body.kind,
                         body=body.body, visibility=body.visibility, blocking=blocking, author_id=c.user.id,
                         author_role=c.user.role)
    c.db.add(note)
    c.db.flush()
    audit.record(c.db, c.engagement.id, f"{body.kind}.created", actor_id=c.user.id, actor_role=c.user.role,
                 target_ref=ref, payload={"note_id": note.id, "blocking": blocking, "visibility": body.visibility})
    c.db.commit()
    return _note_dict(note, _names(c))


@router.post("/workpaper/notes/{note_id}/resolve")
def resolve_note(note_id: int, body: NoteResolve, c: Ctx = Depends(ctx)):
    assert_not_frozen(c, "resolving notes")
    note = c.db.get(WorkpaperNote, note_id)
    if note is None or note.engagement_id != c.engagement.id:
        raise HTTPException(404, "Note not found.")
    if note.status == "resolved":
        raise HTTPException(409, "Note already resolved.")
    guard_escalation(c, [f"note:{note.id}"], "resolve this note")
    if note.kind == "review_note":
        if not c.can(Perm.RESOLVE_REVIEW_NOTE):
            raise HTTPException(403, "Review notes are cleared by a reviewer, partner or quality reviewer.")
    elif not (c.can(Perm.CREATE_NOTE) or note.author_id == c.user.id):
        raise HTTPException(403, "You cannot resolve this note.")
    note.status, note.resolution = "resolved", body.resolution
    note.resolved_by_id, note.resolved_at = c.user.id, datetime.now(timezone.utc)
    audit.record(c.db, c.engagement.id, f"{note.kind}.resolved", actor_id=c.user.id, actor_role=c.user.role,
                 target_ref=note.target_ref, payload={"note_id": note.id, "resolution": body.resolution})
    c.db.commit()
    return _note_dict(note, _names(c))


@router.get("/workpaper/areas")
def areas(c: Ctx = Depends(require(Perm.VIEW_RETURN))):
    rows = c.db.scalars(select(WorkpaperArea).where(WorkpaperArea.engagement_id == c.engagement.id)
                        .order_by(WorkpaperArea.sort_order)).all()
    # Same rule as the area summaries: a note counts in every area its target touches.
    open_counts: dict[str, int] = {}
    for n in c.db.scalars(select(WorkpaperNote).where(
            WorkpaperNote.engagement_id == c.engagement.id, WorkpaperNote.status == "open")).all():
        for k in areas_for_ref(c.idx, n.target_ref, c.idx.current_version) | ({n.area_key} if n.area_key else set()):
            open_counts[k] = open_counts.get(k, 0) + 1
    budget = c.idx.data["firm"]["budget_hours"]
    lines = c.idx.versions_by_id[c.idx.current_version]["lines"]
    line_counts: dict[str, int] = {}
    for ln in lines:
        k = area_for_line(ln)
        line_counts[k] = line_counts.get(k, 0) + 1
    return [
        {"key": a.key, "title": a.title, "forms": a.forms, "budget_key": a.budget_key,
         "budget_hours": budget.get(a.budget_key) if a.budget_key else None,
         "line_count": line_counts.get(a.key, 0), "open_notes": open_counts.get(a.key, 0),
         "preparer_status": a.preparer_status, "reviewer_status": a.reviewer_status,
         "partner_status": a.partner_status}
        for a in rows
    ]


@router.get("/firm")
def firm(c: Ctx = Depends(require(Perm.VIEW_FIRM))):
    f = c.idx.data["firm"]
    identity = dict(f["firm_identity"])
    identity["ero_pin"] = mask_pin(identity.get("ero_pin"))
    staff = c.db.scalars(select(User).where(User.kind == "staff").order_by(User.id)).all()
    return mask_payload({
        "name": f["name"], "identity": identity,
        "staff": [{"id": u.id, "name": u.name, "role": u.role, "role_label": ROLE_LABELS.get(Role(u.role), u.role),
                   "credential": u.credential, "sensitive_data_clearance": u.sensitive_data_clearance,
                   "active_from": u.active_from, "note": u.note} for u in staff],
        "standards": standards.effective(c.idx), "standards_version": standards.version(), "budget_hours": dict(f["budget_hours"]),
        "deadlines": list(f["deadlines"]),
    })


@router.get("/audit/events")
def audit_events(limit: int = Query(100, ge=1, le=1000), c: Ctx = Depends(require(Perm.VIEW_AUDIT_LOG))):
    rows = c.db.scalars(select(AuditEvent).where(AuditEvent.engagement_id == c.engagement.id)
                        .order_by(AuditEvent.seq.desc()).limit(limit)).all()
    # Payloads keep exactly what was hashed in the database; the response masks free text like every other view.
    return [{"seq": e.seq, "at": e.at, "actor_id": e.actor_id, "actor_role": e.actor_role, "action": e.action,
             "target_ref": e.target_ref, "payload": mask_payload(e.payload), "hash": e.hash, "prev_hash": e.prev_hash} for e in rows]


@router.get("/audit/verify")
def audit_verify(c: Ctx = Depends(require(Perm.VIEW_AUDIT_LOG))):
    return audit.verify_chain(c.db, c.engagement.id)


@router.get("/audit/access-logs")
def access_logs(c: Ctx = Depends(require(Perm.VIEW_ACCESS_LOG))):
    rows = c.db.scalars(select(AccessLog).where(AccessLog.engagement_id == c.engagement.id)
                        .order_by(AccessLog.at.desc())).all()
    return [{"id": r.id, "at": r.at, "user_id": r.user_id, "user_role": r.user_role, "field_ref": r.field_ref,
             "granted": r.granted, "reason": r.reason} for r in rows]
