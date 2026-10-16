"""Idempotent startup: migrate the workpaper DB and seed it from the (read-only) packet."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import BACKEND
from .models import Engagement, EngagementAssignment, User, WorkpaperArea
from .packet.index import PacketIndex
from .services import audit
from .services.areas import AREAS


def run_migrations(database_url: str) -> None:
    cfg = Config(str(Path(BACKEND) / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(BACKEND) / "alembic"))
    cfg.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")


def engagement_id_for(idx: PacketIndex) -> str:
    d = idx.data
    return f"{d['packet']['client_id']}-{d['household']['tax_year']}"


def seed(db: Session, idx: PacketIndex) -> Engagement:
    d = idx.data
    eid = engagement_id_for(idx)
    eng = db.get(Engagement, eid)
    if eng is None:
        eng = Engagement(
            id=eid, client_id=d["packet"]["client_id"], name=d["packet"]["name"], tax_year=d["household"]["tax_year"],
            packet_sha256=idx.packet.sha256, packet_version=d["packet"]["version"], status="preparing",
            current_return_version=idx.current_version,
        )
        db.add(eng)
        db.flush()
        audit.record(db, eid, "engagement.created", payload={"packet_sha256": idx.packet.sha256,
                                                               "packet_generated": d["packet"]["generated"]})
    elif eng.packet_sha256 != idx.packet.sha256:
        # The source packet changed on disk. The workpaper keeps its records but must say so loudly.
        audit.record(db, eid, "packet.hash_changed", payload={"previous": eng.packet_sha256, "current": idx.packet.sha256})
        eng.packet_sha256 = idx.packet.sha256

    for s in d["firm"]["staff"]:
        if db.get(User, s["id"]) is None:
            db.add(User(id=s["id"], name=s["name"], role=s["role"], kind="staff", credential=s.get("credential"),
                        sensitive_data_clearance=bool(s.get("sensitive_data_clearance")),
                        active_from=s.get("active_from"), note=s.get("note")))
    for c in d["firm"]["client_users"]:
        if db.get(User, c["id"]) is None:
            db.add(User(id=c["id"], name=c["name"], role="client", kind="client", sensitive_data_clearance=False))
    db.flush()

    existing = {(a.user_id, a.role) for a in db.scalars(
        select(EngagementAssignment).where(EngagementAssignment.engagement_id == eid))}
    wanted = [(uid, role, "2026-01-12", "firm.assignment_at_start")
              for role, uid in d["firm"]["assignment_at_start"].items()]
    for t in d["timeline"]:
        if t["event"] == "staff_joined_engagement" and t["actor"]:
            staff = idx.staff_by_id.get(t["actor"])
            if staff:
                wanted.append((t["actor"], staff["role"], t["at"][:10], f"timeline:{t['id']}"))
    for uid, role, at, source in wanted:
        if (uid, role) not in existing:
            db.add(EngagementAssignment(engagement_id=eid, user_id=uid, role=role, assigned_at=at, source=source))

    have_areas = {a.key for a in db.scalars(select(WorkpaperArea).where(WorkpaperArea.engagement_id == eid))}
    for i, area in enumerate(AREAS):
        if area.key not in have_areas:
            db.add(WorkpaperArea(engagement_id=eid, key=area.key, title=area.title, sort_order=i,
                                 forms=list(area.forms), budget_key=area.budget_key))
    db.commit()
    return eng
