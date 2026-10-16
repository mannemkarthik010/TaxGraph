"""Append-only, hash-chained audit log.

Each event's hash covers its content and the previous event's hash, so any later edit or deletion of
a row breaks the chain and is detectable by `verify_chain`. This is the foundation for
"every filing can be reconstructed".
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AuditEvent

GENESIS = "0" * 64


def _canonical(engagement_id: str, at: datetime, actor_id: str | None, actor_role: str | None, action: str,
               target_ref: str | None, payload: dict[str, Any], prev_hash: str) -> str:
    return json.dumps(
        {
            "engagement_id": engagement_id,
            "at": at.astimezone(timezone.utc).isoformat(timespec="microseconds"),
            "actor_id": actor_id,
            "actor_role": actor_role,
            "action": action,
            "target_ref": target_ref,
            "payload": payload,
            "prev_hash": prev_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _storable(value: Any) -> Any:
    """Normalise a payload to what every JSON store round-trips exactly, *before* hashing it.

    PostgreSQL JSONB stores numbers as `numeric`, which has no negative zero: `-0.0` comes back as `0`.
    Hashing the un-normalised value would make a stored event fail verification.
    """
    if isinstance(value, float):
        return 0.0 if value == 0 else value
    if isinstance(value, dict):
        return {k: _storable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_storable(v) for v in value]
    return value


def _last_hash(db: Session, engagement_id: str) -> str:
    last = db.scalar(
        select(AuditEvent.hash).where(AuditEvent.engagement_id == engagement_id).order_by(AuditEvent.seq.desc()).limit(1)
    )
    return last or GENESIS


def record(db: Session, engagement_id: str, action: str, *, actor_id: str | None = None,
           actor_role: str | None = None, target_ref: str | None = None,
           payload: dict[str, Any] | None = None) -> AuditEvent:
    """Append an event. The caller owns the transaction (commit together with the change it describes)."""
    payload = _storable(json.loads(json.dumps(payload or {}, default=str)))
    at = datetime.now(timezone.utc)
    prev = _last_hash(db, engagement_id)
    digest = hashlib.sha256(
        _canonical(engagement_id, at, actor_id, actor_role, action, target_ref, payload, prev).encode()
    ).hexdigest()
    ev = AuditEvent(engagement_id=engagement_id, at=at, actor_id=actor_id, actor_role=actor_role, action=action,
                    target_ref=target_ref, payload=payload, prev_hash=prev, hash=digest)
    db.add(ev)
    db.flush()
    return ev


def verify_chain(db: Session, engagement_id: str) -> dict[str, Any]:
    events = db.scalars(
        select(AuditEvent).where(AuditEvent.engagement_id == engagement_id).order_by(AuditEvent.seq)
    ).all()
    prev = GENESIS
    for ev in events:
        at = ev.at if ev.at.tzinfo else ev.at.replace(tzinfo=timezone.utc)  # SQLite drops tzinfo
        expected = hashlib.sha256(
            _canonical(ev.engagement_id, at, ev.actor_id, ev.actor_role, ev.action, ev.target_ref, ev.payload, prev).encode()
        ).hexdigest()
        if ev.prev_hash != prev or ev.hash != expected:
            return {"valid": False, "events": len(events), "broken_at_seq": ev.seq}
        prev = ev.hash
    return {"valid": True, "events": len(events), "head": prev}
