"""Return versions, summary and lines (read-only views of the supplied engine output)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ..deps import Ctx, require
from ..security.roles import Perm
from ..services import returns as svc
from ..services import time_machine as tm
from ..services.assurance import challenge

router = APIRouter(prefix="/api")


def _version(c: Ctx, version: str | None) -> str:
    v = version or c.idx.current_version
    if v not in c.idx.versions_by_id:
        raise HTTPException(404, f"Unknown return version '{v}'.")
    return v


@router.get("/return/versions")
def versions(c: Ctx = Depends(require(Perm.VIEW_RETURN))):
    return {"current": c.idx.current_version, "versions": svc.versions_overview(c.idx)}


@router.get("/return/summary")
def summary(version: str | None = None, c: Ctx = Depends(require(Perm.VIEW_RETURN))):
    return svc.return_summary(c.idx, _version(c, version))


@router.get("/return/groups")
def groups(version: str | None = None, c: Ctx = Depends(require(Perm.VIEW_RETURN))):
    return svc.line_groups(c.idx, _version(c, version))


@router.get("/return/lines")
def lines(version: str | None = None, area: str | None = None, form: str | None = None, q: str | None = None,
          offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500),
          c: Ctx = Depends(require(Perm.VIEW_RETURN))):
    return svc.list_lines(c.idx, _version(c, version), area=area, form=form, q=q, offset=offset, limit=limit)


@router.get("/return/lines/{key}")
def line(key: str, version: str | None = None, c: Ctx = Depends(require(Perm.VIEW_RETURN))):
    detail = svc.line_detail(c.idx, _version(c, version), key)
    if detail is None:
        raise HTTPException(404, f"Line '{key}' not in version.")
    return detail


@router.get("/return/diagnostics")
def diagnostics(version: str | None = None, c: Ctx = Depends(require(Perm.VIEW_EVIDENCE))):
    v = c.idx.versions_by_id[_version(c, version)]
    return {"version": v["version"], "source": "engine", "diagnostics": list(v["diagnostics"])}


@router.get("/return/time-machine")
def time_machine(from_version: str = Query(..., alias="from"), to_version: str = Query(..., alias="to"),
                 c: Ctx = Depends(require(Perm.VIEW_RETURN))):
    a, b = _version(c, from_version), _version(c, to_version)
    if a == b:
        raise HTTPException(422, "Pick two different versions to compare.")
    return tm.compare(c.idx, a, b)


@router.get("/return/what-if")
def what_if(c: Ctx = Depends(require(Perm.VIEW_RETURN))):
    findings = challenge(c.idx, c.idx.current_version) if c.can(Perm.VIEW_INTERNAL_NOTES) else []
    return tm.what_if(c.idx, findings)
