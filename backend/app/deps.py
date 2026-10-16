"""Request dependencies: acting user, engagement, permission checks (all server-side)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .bootstrap import engagement_id_for
from .db import get_db
from .models import Engagement, User
from .packet import get_index
from .packet.index import PacketIndex
from .security.roles import Perm, has_perm
from .services import audit

USER_HEADER = "X-TaxProof-User"
DEFAULT_USER = "st-01"


@dataclass
class Ctx:
    db: Session
    idx: PacketIndex
    user: User
    engagement: Engagement

    def can(self, perm: Perm) -> bool:
        return has_perm(self.user.role, perm)


def packet_index() -> PacketIndex:
    return get_index()


def ctx(
    x_taxproof_user: str | None = Header(default=None, alias=USER_HEADER),
    db: Session = Depends(get_db),
    idx: PacketIndex = Depends(packet_index),
) -> Ctx:
    user = db.get(User, x_taxproof_user or DEFAULT_USER)
    if user is None:
        raise HTTPException(status_code=401, detail=f"Unknown user '{x_taxproof_user}'.")
    eng = db.get(Engagement, engagement_id_for(idx))
    if eng is None:
        raise HTTPException(status_code=503, detail="Engagement not initialised.")
    return Ctx(db=db, idx=idx, user=user, engagement=eng)


def require(perm: Perm) -> Callable[[Ctx], Ctx]:
    def checker(c: Ctx = Depends(ctx)) -> Ctx:
        if not c.can(perm):
            audit.record(c.db, c.engagement.id, "permission.denied", actor_id=c.user.id, actor_role=c.user.role,
                         payload={"permission": perm.value})
            c.db.commit()
            raise HTTPException(status_code=403, detail=f"Role '{c.user.role}' lacks permission '{perm.value}'.")
        return c

    return checker
