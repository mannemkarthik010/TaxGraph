"""Workpaper areas and the records a CPA expects (read models with provenance)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from ..deps import Ctx, require
from ..models import EngagementAssignment, User, Verification, WorkpaperArea, WorkpaperNote
from ..security.roles import Perm
from ..services import schedules as S
from ..services.area_summary import area_summaries, areas_for_ref
from ..services.areas import AREAS_BY_KEY, area_for_line

router = APIRouter(prefix="/api/workpaper")


def _version(c: Ctx, version: str | None) -> str:
    v = version or c.idx.current_version
    if v not in c.idx.versions_by_id:
        raise HTTPException(404, f"Unknown return version '{v}'.")
    return v


def _open_notes(c: Ctx) -> list[WorkpaperNote]:
    return list(c.db.scalars(select(WorkpaperNote).where(
        WorkpaperNote.engagement_id == c.engagement.id, WorkpaperNote.status == "open")).all())


def _note_areas(c: Ctx, note: WorkpaperNote, version: str) -> set[str]:
    areas = areas_for_ref(c.idx, note.target_ref, version)
    if note.area_key:
        areas.add(note.area_key)
    return areas


def _summaries(c: Ctx, version: str) -> list[dict]:
    verified = set()
    open_notes: dict[str, dict[str, int]] = {}
    if c.can(Perm.VIEW_INTERNAL_NOTES):
        verified = set(c.db.scalars(select(Verification.target_ref).where(
            Verification.engagement_id == c.engagement.id, Verification.status == "active")).all())
        # A note counts in every area it touches: its stored area plus every area whose lines cite
        # the evidence it points at (e.g. a review note on a mileage value belongs to Business).
        for note in _open_notes(c):
            for area_key in _note_areas(c, note, version):
                d = open_notes.setdefault(area_key, {"open": 0, "blocking": 0})
                d["open"] += 1
                if note.blocking:
                    d["blocking"] += 1
    areas_db = {a.key: a for a in c.db.scalars(select(WorkpaperArea).where(WorkpaperArea.engagement_id == c.engagement.id))}
    names = {u.id: u.name for u in c.db.scalars(select(User)).all()}
    assignments = {}
    for a in c.db.scalars(select(EngagementAssignment).where(EngagementAssignment.engagement_id == c.engagement.id)
                          .order_by(EngagementAssignment.id)):
        assignments.setdefault(a.role, names.get(a.user_id))
    return area_summaries(c.idx, version, verified_refs=verified, open_notes=open_notes,
                          areas_db=areas_db, assignments=assignments)


@router.get("/area-summaries")
def summaries(version: str | None = None, c: Ctx = Depends(require(Perm.VIEW_RETURN))):
    v = _version(c, version)
    return {"version": v, "areas": _summaries(c, v)}


@router.get("/area-summaries/{key}")
def area_detail(key: str, version: str | None = None, c: Ctx = Depends(require(Perm.VIEW_RETURN))):
    if key not in AREAS_BY_KEY:
        raise HTTPException(404, f"Unknown area '{key}'.")
    v = _version(c, version)
    summary = next(a for a in _summaries(c, v) if a["key"] == key)
    lines = [ln for ln in c.idx.return_lines_by_version[v].values() if area_for_line(ln) == key]
    # Individual sales live in the brokerage schedule; box totals stay in the area's line list.
    is_lot = lambda ln: ln["form"] == "F8949" and not ln["key"].endswith(".total")  # noqa: E731
    notes = []
    if c.can(Perm.VIEW_INTERNAL_NOTES):
        names = {u.id: u.name for u in c.db.scalars(select(User)).all()}
        notes = [{"id": n.id, "target_ref": n.target_ref, "kind": n.kind, "body": n.body, "blocking": n.blocking,
                  "author_name": names.get(n.author_id), "created_at": n.created_at,
                  "via": "area" if n.target_ref == f"area:{key}" else "line" if n.target_ref.startswith("line:") else "evidence"}
                 for n in _open_notes(c) if key in _note_areas(c, n, v)]
    return {**summary, "version": v, "open_notes": notes,
            "lines_preview": [{"key": ln["key"], "label": ln["label"], "value": ln["value"]}
                              for ln in lines if not is_lot(ln)][:120],
            "lots_hidden": sum(1 for ln in lines if is_lot(ln))}


@router.get("/schedules")
def schedule_index(c: Ctx = Depends(require(Perm.VIEW_RETURN))):
    return [{"name": n} for n in S.SCHEDULES]


@router.get("/schedules/brokerage/lots")
def lots(version: str | None = None, box: str | None = None, document_id: str | None = None, q: str | None = None,
         attention: bool = False, sort: str = Query("gain", pattern="^(gain|sold|key)$"),
         offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=200),
         c: Ctx = Depends(require(Perm.VIEW_RETURN))):
    return S.brokerage_lots(c.idx, _version(c, version), box=box, document_id=document_id, q=q,
                            attention=attention, sort=sort, offset=offset, limit=limit)


@router.get("/schedules/residency")
def residency(c: Ctx = Depends(require(Perm.VIEW_RETURN))):
    return S.residency(c.idx)


@router.get("/schedules/{name}")
def schedule(name: str, version: str | None = None, c: Ctx = Depends(require(Perm.VIEW_RETURN))):
    fn = S.SCHEDULES.get(name)
    if fn is None:
        raise HTTPException(404, f"Unknown schedule '{name}'.")
    return fn(c.idx, _version(c, version))
