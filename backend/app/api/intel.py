"""Firm intelligence: firm-wide search, firm standards (versioned, administrator-edited) and budget vs actual time."""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..deps import Ctx, require
from ..models import FirmStandards, TimeEntry, User
from ..security.masking import mask_payload
from ..security.roles import Perm
from ..services import audit, search, standards
from ..services import time_machine as TM
from .collaboration import _items, _names

router = APIRouter(prefix="/api")


# ---- search ---------------------------------------------------------------------------------------------

def _answer(c: Ctx, name: str, m) -> dict[str, Any] | None:
    v = c.idx.current_version
    if name == "version_change":
        a, b = m.group(3).lower(), m.group(4).lower()
        if a not in c.idx.versions_by_id or b not in c.idx.versions_by_id or a == b:
            return None
        cmp = TM.compare(c.idx, a, b)
        tc = cmp["tax_change"]
        return {"intent": "version_change", "title": f"Why tax changed from {a} to {b}",
                "text": f"Federal total tax changed by {tc['federal']:+,.0f} and California by {tc['california']:+,.0f}. "
                        f"{len(cmp['drivers'])} lines are where the change entered; the trigger was: {cmp['why']['triggers'][-1]['trigger']}",
                "items": [{"ref": f"line:{b}:{d['key']}", "title": f"{d['key']} {d['label']}: {d['old']} → {d['new']}",
                           "detail": ("new evidence: " + ", ".join(d["new_source_documents"])) if d["new_source_documents"] else "no new source document",
                           "link": f"/return?tab=time"} for d in cmp["drivers"]],
                "source": "Tax Time Machine (computed from the supplied engine runs)"}
    if name == "open_basis":
        rows = [i for i in _items(c) if i.status == "open" and ("basis" in i.title.lower() or (i.detail or {}).get("family") == "basis"
                                                                 or any(r.split(":")[-1].startswith(("F7203", "F8949")) for r in i.refs))]
        return {"intent": "open_basis", "title": "Unresolved basis issues", "text": f"{len(rows)} open item(s) concern basis.",
                "items": [{"ref": i.key, "title": i.title, "detail": f"{i.group_label if hasattr(i, 'group_label') else i.group} · {', '.join(i.areas)}",
                           "link": "/review?tab=inbox"} for i in rows], "source": "Uncertainty Inbox (open items)"}
    if name == "low_confidence":
        rows = []
        for ev in c.idx.data["extracted_values"]:
            if ev["confidence"] < 0.8:
                used = [k for ver, k in c.idx.lines_by_source.get(ev["id"], ()) if ver == v]
                rows.append({"ref": ev["id"], "title": f"{ev['id']} {ev['label']} — read '{ev['text_as_read']}' at {ev['confidence']:.0%}",
                             "detail": f"{ev['document_id']} page {ev['page']}; " + (f"feeds {', '.join(used)}" if used else "not used by the return"),
                             "link": f"/evidence?doc={ev['document_id']}"})
        return {"intent": "low_confidence", "title": "Values from low-confidence extractions (below 80%)",
                "text": f"{len(rows)} value(s) were read with confidence below 80%; {sum(1 for r in rows if 'feeds' in r['detail'])} reach the return.",
                "items": rows, "source": "Extracted values (confidence from the packet)"}
    return None


@router.get("/search")
def firm_search(q: str = Query(min_length=2, max_length=300), c: Ctx = Depends(require(Perm.VIEW_INTERNAL_NOTES))):
    hit = search.intent(q)
    answer = _answer(c, *hit) if hit else None
    extra = search.workpaper_docs(c.db, c.engagement.id)
    q_terms, expansion = search.expand(q)
    associated = search.learned(c.idx, q)
    results = search.rank(c.idx, q, extra)
    for r in results:
        if r["ref"].startswith("finding:"):
            r["link"] = f"/challenge?finding={r['ref'][8:]}"
    return mask_payload({"query": q, "answer": answer, "terms": q_terms, "expanded_with": expansion,
                         "associated": [{"term": w, "weight": wt} for w, wt in associated], "results": results,
                         "method": search.method()})


# ---- firm standards -------------------------------------------------------------------------------------------

@router.get("/firm/standards")
def get_standards(c: Ctx = Depends(require(Perm.VIEW_FIRM))):
    names = _names(c)
    rows = c.db.scalars(select(FirmStandards).order_by(FirmStandards.version.desc())).all()
    # Rules and change notes are free text an administrator typed: masked like every other such field.
    return mask_payload({"version": standards.version(), "standards": standards.effective(c.idx), "known_methods": list(standards.KNOWN_METHODS),
                         "history": [{"version": r.version, "note": r.note, "by": names.get(r.changed_by_id), "at": r.changed_at} for r in rows]
                         + [{"version": 0, "note": "Starter standards supplied in the packet.", "by": None, "at": None}]})


class StandardsIn(BaseModel):
    changes: dict[str, Any]
    note: str = Field(min_length=5, max_length=2000)


@router.post("/firm/standards")
def save_standards(body: StandardsIn, c: Ctx = Depends(require(Perm.MANAGE_FIRM))):
    allowed = {"variance_review", "partner_threshold", "verification_types", "rules", "required_steps"}
    bad = set(body.changes) - allowed
    if bad:
        raise HTTPException(422, f"Not editable: {', '.join(sorted(bad))}.")
    before = standards.effective(c.idx)
    try:
        row = standards.save(c.db, c.idx, body.changes, note=body.note.strip(), user_id=c.user.id)
    except standards.StandardsError as e:
        raise HTTPException(422, str(e))
    audit.record(c.db, c.engagement.id, "firm.standards_changed", actor_id=c.user.id, actor_role=c.user.role,
                 payload={"version": row.version, "changed": sorted(body.changes), "note": body.note,
                          "before": {k: before.get(k) for k in body.changes}, "after": {k: row.content.get(k) for k in body.changes}})
    c.db.commit()
    return get_standards(c)


# ---- budget vs actual time ------------------------------------------------------------------------------------

class TimeIn(BaseModel):
    budget_key: str = Field(min_length=1, max_length=60)
    hours: float = Field(gt=0, le=12)
    worked_on: date
    note: str | None = Field(default=None, max_length=1000)


@router.post("/time", status_code=201)
def log_time(body: TimeIn, c: Ctx = Depends(require(Perm.CREATE_NOTE))):
    budget = c.idx.data["firm"]["budget_hours"]
    if body.budget_key not in budget:
        raise HTTPException(422, f"Unknown budget line '{body.budget_key}'; use one of {', '.join(budget)}.")
    if round(body.hours * 4) != body.hours * 4:
        raise HTTPException(422, "Log time in quarter hours.")
    e = TimeEntry(engagement_id=c.engagement.id, user_id=c.user.id, budget_key=body.budget_key, hours=body.hours,
                  worked_on=body.worked_on.isoformat(), note=(body.note or "").strip() or None)
    c.db.add(e)
    c.db.flush()
    audit.record(c.db, c.engagement.id, "time.logged", actor_id=c.user.id, actor_role=c.user.role,
                 payload={"entry_id": e.id, "budget_key": e.budget_key, "hours": e.hours})
    c.db.commit()
    return budget_vs_actual(c)


@router.get("/time/budget")
def budget_vs_actual(c: Ctx = Depends(require(Perm.VIEW_FIRM))):
    budget = c.idx.data["firm"]["budget_hours"]
    names = {u.id: u.name for u in c.db.scalars(select(User)).all()}
    entries = c.db.scalars(select(TimeEntry).where(TimeEntry.engagement_id == c.engagement.id).order_by(TimeEntry.id.desc())).all()
    rows = []
    for key, hours in budget.items():
        mine = [e for e in entries if e.budget_key == key]
        actual = round(sum(e.hours for e in mine), 2)
        people: dict[str, float] = {}
        for e in mine:
            people[names.get(e.user_id, e.user_id)] = people.get(names.get(e.user_id, e.user_id), 0) + e.hours
        rows.append({"budget_key": key, "label": key.replace("_", " ").capitalize(), "budget": hours, "actual": actual,
                     "remaining": round(hours - actual, 2), "used_pct": round(actual / hours * 100) if hours else None,
                     "over": actual > hours, "by_person": people})
    total_b, total_a = sum(budget.values()), round(sum(e.hours for e in entries), 2)
    return mask_payload({"lines": rows, "total": {"budget": total_b, "actual": total_a, "remaining": round(total_b - total_a, 2),
                                                  "over": total_a > total_b},
                         "entries": [{"id": e.id, "who": names.get(e.user_id), "budget_key": e.budget_key, "hours": e.hours,
                                      "worked_on": e.worked_on, "note": e.note} for e in entries[:50]]})

