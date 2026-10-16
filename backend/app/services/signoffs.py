"""Living sign-offs: prepared → reviewed → partner, per tax area, that reopen when what they attest to changes.

A sign-off attests to an area *as it stood*. When something underneath it changes — an adjustment is
applied, undone or restored on one of the area's lines, a judgment about the area is recorded or
approved, a client answer is accepted as evidence, a verification is withdrawn, a person links or
retires evidence — the reviewed and partner sign-offs on that area reopen, each with the exact reason
(what changed, by whom, when). The prepared sign-off stays: the preparer owns the work in progress.

Rules (firm standards, enforced here, server-side):
- order: reviewed needs an active prepared sign-off; partner needs an active reviewed sign-off;
- independence: nobody reviews or partner-signs an area they prepared, nor one containing an applied
  adjustment or a judgment they made;
- open blocking review notes on the area block the reviewed and partner sign-offs;
- adjustments and judgments needing partner approval must be approved before the partner sign-off.
Other open items do not stop a sign-off; they are recorded on it (`open_items_at_signing`).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Adjustment, Judgment, Signoff, WorkpaperArea, WorkpaperNote
from ..packet.index import PacketIndex
from . import audit
from .area_summary import areas_for_ref
from .areas import AREAS, AREAS_BY_KEY, area_for_line

LEVELS = ("prepared", "reviewed", "partner")
REOPENS = ("reviewed", "partner")
LEVEL_LABEL = {"prepared": "Prepared", "reviewed": "Reviewed", "partner": "Partner"}
# Status words the area screens already understand.
STATUS_WORD = {"prepared": "prepared", "reviewed": "reviewed", "partner": "approved"}
COLUMN = {"prepared": "preparer_status", "reviewed": "reviewer_status", "partner": "partner_status"}


class SignoffError(ValueError):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def areas_touched(idx: PacketIndex, refs: list[str]) -> set[str]:
    """Areas whose sign-offs a change to these references affects (bare line keys allowed)."""
    v = idx.current_version
    lines = idx.return_lines_by_version[v]
    out: set[str] = set()
    for ref in refs:
        if ref in lines:
            ref = f"line:{v}:{ref}"
        out |= areas_for_ref(idx, ref, v)
    return {a for a in out if a in AREAS_BY_KEY}


def _seed_lines(idx: PacketIndex, ref: str) -> list[str]:
    """Current-version lines a reference changes directly: the line itself, or every line citing the evidence."""
    v = idx.current_version
    lines = idx.return_lines_by_version[v]
    if ref in lines:
        return [ref]
    if ref.startswith("line:"):
        key = ref.split(":", 2)[2]
        return [key] if key in lines else []
    if ref.startswith("doc:"):
        doc_id, _, page = ref[4:].partition("#page")
        cited = [ev["id"] for ev in idx.values_by_document.get(doc_id, []) if str(ev["page"]) == page]
    elif ref in idx.documents_by_id:
        cited = [ev["id"] for ev in idx.values_by_document.get(ref, [])] + [ref]
    else:
        cited = [ref]
    return sorted({k for cid in cited for ver, k in idx.lines_by_source.get(cid, ()) if ver == v})


def affected_areas(idx: PacketIndex, refs: list[str]) -> dict[str, dict[str, str | None]]:
    """Every area whose figures rest on these references: directly (the area of the changed line or evidence),
    or downstream (one of its lines is computed, at any depth, from a changed line). For a downstream area,
    `via` is the nearest of its lines the change flows into."""
    v = idx.current_version
    lines = idx.return_lines_by_version[v]
    out: dict[str, dict[str, str | None]] = {a: {"scope": "direct", "via": None} for a in sorted(areas_touched(idx, refs))}
    seen: set[str] = set()
    queue = [k for ref in refs for k in _seed_lines(idx, ref)]
    seen.update(queue)
    while queue:  # breadth-first: the first line reached in an area is the nearest
        nxt = []
        for key in queue:
            for d in sorted(idx.lines_by_input.get((v, key), ())):
                if d in seen:
                    continue
                seen.add(d)
                nxt.append(d)
                a = area_for_line(lines[d])
                if a in AREAS_BY_KEY and a not in out:
                    out[a] = {"scope": "downstream", "via": d}
        queue = nxt
    return out


def latest(db: Session, engagement_id: str) -> dict[tuple[str, str], Signoff]:
    """The most recent sign-off per (area, level) — active or reopened."""
    rows = db.scalars(select(Signoff).where(Signoff.engagement_id == engagement_id).order_by(Signoff.id)).all()
    return {(s.area_key, s.level): s for s in rows}


def _sync_area(db: Session, engagement_id: str, area_key: str) -> None:
    area = db.scalar(select(WorkpaperArea).where(WorkpaperArea.engagement_id == engagement_id, WorkpaperArea.key == area_key))
    if area is None:
        return
    cur = latest(db, engagement_id)
    for level in LEVELS:
        s = cur.get((area_key, level))
        setattr(area, COLUMN[level], "not_started" if s is None else STATUS_WORD[level] if s.status == "active" else "reopened")


def reopen(db: Session, idx: PacketIndex, engagement_id: str, refs: list[str], *, actor_id: str, actor_name: str | None,
           actor_role: str, action: str, detail: str, ref: str | None = None) -> list[dict[str, Any]]:
    """Reopen the reviewed and partner sign-offs of every area these references touch — directly or through
    the calculations that rest on them (see `affected_areas`). Returns what reopened, each with its reason."""
    areas = affected_areas(idx, refs)
    if not areas:
        return []
    base = {"at": datetime.now(timezone.utc).isoformat(), "by": actor_id, "by_name": actor_name, "role": actor_role,
            "action": action, "ref": ref or (refs[0] if refs else None)}
    lines = idx.return_lines_by_version[idx.current_version]
    reopened = []
    cur = latest(db, engagement_id)
    for area, how in sorted(areas.items()):
        via = how["via"]
        why = detail if how["scope"] == "direct" else (
            f"{detail} {AREAS_BY_KEY[area].title} is affected downstream: the change flows into {via} "
            f"({lines[via]['label']}).")
        reason = base | {"detail": why, "scope": how["scope"], "via": via}
        for level in REOPENS:
            s = cur.get((area, level))
            if s is None or s.status != "active":
                continue
            s.status, s.reopened_at = "reopened", datetime.now(timezone.utc)
            s.reopen_reasons = list(s.reopen_reasons) + [reason]
            reopened.append({"signoff_id": s.id, "area": area, "level": level, "reason": reason})
        _sync_area(db, engagement_id, area)
    if reopened:
        db.flush()
        audit.record(db, engagement_id, "signoff.reopened", actor_id=actor_id, actor_role=actor_role,
                     target_ref=base["ref"], payload={"reopened": [{"area": r["area"], "level": r["level"], "signoff_id": r["signoff_id"],
                                                                    "scope": r["reason"]["scope"], "via": r["reason"]["via"]}
                                                                   for r in reopened],
                                                      "action": action, "detail": detail})
    return reopened


def _blocking_notes(db: Session, idx: PacketIndex, engagement_id: str, area_key: str) -> list[WorkpaperNote]:
    notes = db.scalars(select(WorkpaperNote).where(WorkpaperNote.engagement_id == engagement_id, WorkpaperNote.status == "open",
                                                   WorkpaperNote.blocking.is_(True))).all()
    return [n for n in notes if area_key in (areas_for_ref(idx, n.target_ref, idx.current_version) | ({n.area_key} if n.area_key else set()))]


def _area_adjustments(db: Session, idx: PacketIndex, engagement_id: str, area_key: str) -> list[Adjustment]:
    rows = db.scalars(select(Adjustment).where(Adjustment.engagement_id == engagement_id,
                                               Adjustment.status.in_(("proposed", "applied")))).all()
    return [a for a in rows if area_key in areas_touched(idx, [f"line:{a.version}:{a.target_line}"])]


def _area_judgments(db: Session, engagement_id: str, area_key: str) -> list[Judgment]:
    rows = db.scalars(select(Judgment).where(Judgment.engagement_id == engagement_id, Judgment.status != "superseded")).all()
    return [j for j in rows if area_key in (j.area_keys or [])]


def blockers(db: Session, idx: PacketIndex, engagement_id: str, area_key: str, level: str, user_id: str | None,
             user_role: str | None) -> list[tuple[str, str]]:
    """Why `user` cannot sign `area` at `level` right now, as (kind, message); kind is "permission" (who you
    are) or "state" (what the area needs first). Empty = they can. Deterministic and explainable."""
    out: list[tuple[str, str]] = []
    allowed = {"prepared": ("preparer", "reviewer", "partner"), "reviewed": ("reviewer", "partner"), "partner": ("partner",)}[level]
    if user_role not in allowed:
        out.append(("permission", f"{LEVEL_LABEL[level]} sign-off needs a {' or '.join(allowed)}."))
    cur = latest(db, engagement_id)
    mine = cur.get((area_key, level))
    if mine and mine.status == "active":
        out.append(("state", f"Already signed {LEVEL_LABEL[level].lower()}."))
    prepared = cur.get((area_key, "prepared"))
    if level != "prepared":
        prev = "prepared" if level == "reviewed" else "reviewed"
        p = cur.get((area_key, prev))
        if p is None or p.status != "active":
            out.append(("state", f"Needs an active {LEVEL_LABEL[prev].lower()} sign-off first."))
        if user_id and prepared and prepared.status == "active" and prepared.signed_by_id == user_id:
            out.append(("permission", "A person may not review or sign off on work they prepared (you signed this area as preparer)."))
        adjs = _area_adjustments(db, idx, engagement_id, area_key)
        judgments = _area_judgments(db, engagement_id, area_key)
        if user_id:
            own = [f"adjustment #{a.id}" for a in adjs if a.status == "applied" and a.created_by_id == user_id]
            own += [f"judgment #{j.id}" for j in judgments if j.prepared_by_id == user_id]
            if own:
                out.append(("permission", f"You prepared {', '.join(own)} in this area; someone independent must sign it."))
        if notes := _blocking_notes(db, idx, engagement_id, area_key):
            out.append(("state", f"{len(notes)} open blocking review note{'s' if len(notes) != 1 else ''} on this area "
                                 f"({', '.join(f'#{n.id}' for n in notes[:5])})."))
        if level == "partner":
            pending = [f"adjustment #{a.id}" for a in adjs if a.review_required == "partner" and not a.approved_by_id]
            pending += [f"judgment #{j.id}" for j in judgments if j.review_required == "partner" and j.status != "approved"]
            if pending:
                out.append(("state", f"Partner approval still needed for {', '.join(pending)}."))
    return out


def sign(db: Session, idx: PacketIndex, engagement_id: str, area_key: str, level: str, *, user_id: str, user_role: str,
         note: str | None, open_items: list[str]) -> Signoff:
    if area_key not in AREAS_BY_KEY:
        raise SignoffError(f"Unknown area '{area_key}'.", 404)
    if level not in LEVELS:
        raise SignoffError(f"Unknown sign-off level '{level}'.", 422)
    if why := blockers(db, idx, engagement_id, area_key, level, user_id, user_role):
        raise SignoffError(" ".join(m for _, m in why), 403 if any(k == "permission" for k, _ in why) else 409)
    s = Signoff(engagement_id=engagement_id, area_key=area_key, level=level, version=idx.current_version,
                signed_by_id=user_id, signed_by_role=user_role, note=note, open_items_at_signing=open_items, reopen_reasons=[])
    db.add(s)
    db.flush()
    _sync_area(db, engagement_id, area_key)
    audit.record(db, engagement_id, "signoff.signed", actor_id=user_id, actor_role=user_role, target_ref=f"area:{area_key}",
                 payload={"signoff_id": s.id, "level": level, "version": s.version, "open_items": len(open_items)})
    return s


def board(db: Session, idx: PacketIndex, engagement_id: str, names: dict[str, str], user_id: str | None,
          user_role: str | None, open_by_area: dict[str, list[str]]) -> list[dict[str, Any]]:
    """Every area with its three levels: status, who, when, why reopened, and whether this user can sign."""
    cur = latest(db, engagement_id)
    history: dict[tuple[str, str], int] = {}
    for s in db.scalars(select(Signoff).where(Signoff.engagement_id == engagement_id)).all():
        history[(s.area_key, s.level)] = history.get((s.area_key, s.level), 0) + 1
    out = []
    for area in AREAS:
        levels = []
        for level in LEVELS:
            s = cur.get((area.key, level))
            why_not = blockers(db, idx, engagement_id, area.key, level, user_id, user_role)
            levels.append({
                "level": level, "label": LEVEL_LABEL[level],
                "status": "not_signed" if s is None else "signed" if s.status == "active" else "reopened",
                "signoff_id": s.id if s else None, "by": names.get(s.signed_by_id) if s else None,
                "by_id": s.signed_by_id if s else None, "at": s.signed_at if s else None,
                "reopened_at": s.reopened_at if s else None, "reopen_reasons": list(s.reopen_reasons) if s else [],
                "open_items_at_signing": len(s.open_items_at_signing) if s else 0, "signatures": history.get((area.key, level), 0),
                "can_sign": not why_not, "why_not": [m for _, m in why_not],
            })
        out.append({"key": area.key, "title": area.title, "levels": levels, "open_items": open_by_area.get(area.key, []),
                    "complete": all(lv["status"] == "signed" for lv in levels)})
    return out
