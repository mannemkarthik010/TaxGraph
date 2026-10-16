"""Session, engagement, household, sensitive-data reveal."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from ..deps import Ctx, ctx
from ..models import AccessLog, EngagementAssignment, User
from ..security.masking import is_sensitive_value, mask_household, mask_text
from ..security.roles import ROLE_LABELS, Role, can_reveal_sensitive, permissions_for
from ..services import audit

router = APIRouter(prefix="/api")


def _user_dict(u: User) -> dict:
    return {
        "id": u.id, "name": u.name, "role": u.role, "role_label": ROLE_LABELS.get(Role(u.role), u.role),
        "kind": u.kind, "credential": u.credential, "sensitive_data_clearance": u.sensitive_data_clearance,
        "active_from": u.active_from, "note": u.note,
    }


@router.get("/session/users")
def list_users(c: Ctx = Depends(ctx)):
    users = c.db.scalars(select(User).order_by(User.kind.desc(), User.id)).all()
    assignments = c.db.scalars(
        select(EngagementAssignment).where(EngagementAssignment.engagement_id == c.engagement.id)).all()
    by_user: dict[str, list[str]] = {}
    for a in assignments:
        by_user.setdefault(a.user_id, []).append(a.role)
    return [_user_dict(u) | {"engagement_roles": by_user.get(u.id, [])} for u in users]


@router.get("/session/me")
def me(c: Ctx = Depends(ctx)):
    return _user_dict(c.user) | {
        "permissions": sorted(p.value for p in permissions_for(c.user.role)),
        "can_reveal_sensitive": can_reveal_sensitive(c.user.role, c.user.kind, c.user.sensitive_data_clearance),
    }


@router.get("/engagement")
def engagement(c: Ctx = Depends(ctx)):
    d, idx, e = c.idx.data, c.idx, c.engagement
    assignments = c.db.scalars(
        select(EngagementAssignment).where(EngagementAssignment.engagement_id == e.id)).all()
    names = {u.id: u.name for u in c.db.scalars(select(User)).all()}
    return {
        "id": e.id, "client_id": e.client_id, "name": e.name, "tax_year": e.tax_year, "status": e.status,
        "current_return_version": e.current_return_version,
        "packet": {
            **dict(d["packet"]), "sha256": idx.packet.sha256, "size_bytes": idx.packet.size_bytes,
            "sha256_at_engagement_creation": e.packet_sha256, "immutable": True,
            "counts": {
                "documents": len(d["documents"]), "extracted_values": len(d["extracted_values"]),
                "return_versions": len(d["return_versions"]), "timeline_events": len(d["timeline"]),
                "questionnaire": len(d["client"]["questionnaire"]), "messages": len(d["client"]["messages"]),
            },
        },
        "assignments": [
            {"user_id": a.user_id, "name": names.get(a.user_id), "role": a.role, "assigned_at": a.assigned_at,
             "source": a.source} for a in assignments
        ],
        "deadlines": list(d["firm"]["deadlines"]),
    }


@router.get("/household")
def household(c: Ctx = Depends(ctx)):
    return mask_household(c.idx.data["household"])


class RevealRequest(BaseModel):
    field_ref: str
    reason: str | None = None


def _sensitive_value(c: Ctx, field_ref: str):
    if field_ref.startswith("household:"):
        target, _, attr = field_ref[len("household:"):].partition(".")
        if target == "bank" and attr in ("account", "routing"):
            return c.idx.data["household"]["bank_account_for_refund_or_payment"][attr]
        person = c.idx.people_by_id.get(target)
        if person and attr in ("ssn", "ip_pin") and person.get(attr):
            return person[attr]
    ev = c.idx.values_by_id.get(field_ref)
    if ev and is_sensitive_value(ev):
        return ev["value"]
    return None


@router.post("/sensitive/reveal")
def reveal(body: RevealRequest, c: Ctx = Depends(ctx)):
    value = _sensitive_value(c, body.field_ref)
    if value is None:
        raise HTTPException(404, "Not a sensitive field reference.")
    granted = can_reveal_sensitive(c.user.role, c.user.kind, c.user.sensitive_data_clearance)
    c.db.add(AccessLog(engagement_id=c.engagement.id, user_id=c.user.id, user_role=c.user.role,
                       field_ref=body.field_ref, granted=granted, reason=body.reason))
    audit.record(c.db, c.engagement.id, "sensitive.reveal" if granted else "sensitive.reveal_denied",
                 actor_id=c.user.id, actor_role=c.user.role, target_ref=body.field_ref)
    c.db.commit()
    if not granted:
        raise HTTPException(403, "No sensitive-data clearance. This attempt has been logged.")
    return {"field_ref": body.field_ref, "value": value, "logged": True}


@router.get("/timeline")
def timeline(c: Ctx = Depends(ctx)):
    as_of = c.idx.versions_by_id[c.idx.current_version]["computed_at"]
    return {
        "as_of": as_of,
        "events": [
            dict(t) | {"detail": mask_text(t["detail"]), "is_future": t["at"] > as_of}
            for t in c.idx.data["timeline"]
        ],
    }
