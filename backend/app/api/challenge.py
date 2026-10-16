"""Challenge Return API: TaxProof's independent findings, kept apart from the engine's diagnostics."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from ..deps import Ctx, require
from ..models import ChallengeRun, User
from ..packet.refs import resolve
from ..security.masking import mask_payload, mask_resolved, mask_text
from ..security.roles import Perm
from ..services import audit
from ..services.assurance import FAMILIES, challenge, summarize
from ..services.graph import GraphView, get_graph, impact

router = APIRouter(prefix="/api/challenge")


def _masked(value):
    """Mask every string in a finding payload (titles, summaries, breakdowns)."""
    return mask_payload(value)


def _version(c: Ctx, version: str | None) -> str:
    v = version or c.idx.current_version
    if v not in c.idx.versions_by_id:
        raise HTTPException(404, f"Unknown return version '{v}'.")
    return v


def _results(findings) -> list[dict]:
    return [{"id": f.id, "status": f.status, "severity": f.severity, "difference": f.difference,
             "federal": (f.effect or {}).get("federal"), "california": (f.effect or {}).get("california")} for f in findings]


def _run_dict(r: ChallengeRun, names: dict[str, str]) -> dict:
    return {"id": r.id, "version": r.version, "run_at": r.run_at, "run_by": names.get(r.run_by_id), "run_by_role": r.run_by_role,
            "summary": r.summary, "packet_sha256": r.packet_sha256}


COMPARED = ("status", "severity", "difference", "federal", "california")


def _diff(old: dict, new: dict) -> dict:
    """Field-by-field comparison of two recorded results. Amounts count as changed when they move by
    more than half a dollar (rounding noise); status and severity on any change."""
    out = {}
    for k in COMPARED:
        a, b = old.get(k), new.get(k)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            if abs(a - b) > 0.5:
                out[k] = [a, b]
        elif a != b:
            out[k] = [a, b]
    return out


def _changes(previous: ChallengeRun | None, findings) -> dict:
    """What changed since the last recorded run of this version: new, resolved, and changed findings —
    changed meaning its status, severity, difference or estimated effect moved."""
    if previous is None:
        return {"since_run": None, "new": [], "gone": [], "changed": [], "changed_detail": {}}
    before = {r["id"]: r for r in previous.results}
    now = {r["id"]: r for r in _results(findings)}
    changed_detail = {i: d for i, r in now.items() if i in before and (d := _diff(before[i], r))}
    return {
        "since_run": previous.id,
        "new": [i for i, r in now.items() if i not in before and r["status"] != "pass"],
        "gone": [i for i, r in before.items() if i not in now or (r["status"] != "pass" and now[i]["status"] == "pass")],
        "changed": sorted(changed_detail),
        "changed_detail": changed_detail,
    }


@router.get("")
def overview(version: str | None = None, c: Ctx = Depends(require(Perm.VIEW_INTERNAL_NOTES))):
    v = _version(c, version)
    findings = challenge(c.idx, v)
    names = {u.id: u.name for u in c.db.scalars(select(User)).all()}
    last = c.db.scalar(select(ChallengeRun).where(ChallengeRun.engagement_id == c.engagement.id, ChallengeRun.version == v)
                       .order_by(ChallengeRun.id.desc()).limit(1))
    ver = c.idx.versions_by_id[v]
    return {
        "summary": summarize(c.idx, v, findings),
        "findings": [_masked(f.as_dict()) for f in findings],
        "families": FAMILIES,
        # The supplied engine's own diagnostics — shown, never merged with TaxProof's findings.
        "engine_diagnostics": [
            _masked({**dict(dg), "related_findings": [f.id for f in findings if dg["code"] in f.engine_diagnostics]})
            for dg in ver["diagnostics"]
        ],
        "last_run": _run_dict(last, names) if last else None,
        "changes_since_last_run": _changes(last, findings),
    }


@router.get("/finding")
def finding(id: str, version: str | None = None, c: Ctx = Depends(require(Perm.VIEW_INTERNAL_NOTES))):
    v = _version(c, version)
    f = next((x for x in challenge(c.idx, v) if x.id == id), None)
    if f is None:
        raise HTTPException(404, f"No finding '{id}' in {v}.")
    evidence = [mask_resolved(c.idx, resolve(c.idx, r, v).as_dict()) for r in f.evidence]
    lines = [{"key": k, "label": (c.idx.line(v, k) or {}).get("label"), "value": (c.idx.line(v, k) or {}).get("value")}
             for k in f.lines if c.idx.line(v, k)]
    reach = impact(c.idx, GraphView(get_graph(c.idx)), f"line:{v}:{f.lines[0]}", v) if lines else None
    return {**_masked(f.as_dict()), "version": v, "evidence_resolved": evidence, "lines_resolved": lines,
            "impact": {"affected_lines": reach["affected_lines"], "headlines": reach["headlines"]} if reach else None}


@router.post("/runs", status_code=201)
def record_run(version: str | None = None, c: Ctx = Depends(require(Perm.CREATE_NOTE))):
    v = _version(c, version)
    findings = challenge(c.idx, v)
    summary = summarize(c.idx, v, findings)
    previous = c.db.scalar(select(ChallengeRun).where(ChallengeRun.engagement_id == c.engagement.id, ChallengeRun.version == v)
                           .order_by(ChallengeRun.id.desc()).limit(1))
    changes = _changes(previous, findings)
    run = ChallengeRun(engagement_id=c.engagement.id, version=v, packet_sha256=c.idx.packet.sha256, run_by_id=c.user.id,
                       run_by_role=c.user.role, summary={k: summary[k] for k in ("checks", "by_status", "estimated_effect")},
                       results=_results(findings))
    c.db.add(run)
    c.db.flush()
    audit.record(c.db, c.engagement.id, "challenge.run", actor_id=c.user.id, actor_role=c.user.role, target_ref=v,
                 payload={"run_id": run.id, "by_status": summary["by_status"], "changes": changes})
    c.db.commit()
    return {**_run_dict(run, {c.user.id: c.user.name}), "changes": changes}


@router.get("/runs")
def list_runs(version: str | None = None, c: Ctx = Depends(require(Perm.VIEW_INTERNAL_NOTES))):
    stmt = select(ChallengeRun).where(ChallengeRun.engagement_id == c.engagement.id)
    if version:
        stmt = stmt.where(ChallengeRun.version == version)
    names = {u.id: u.name for u in c.db.scalars(select(User)).all()}
    return [_run_dict(r, names) for r in c.db.scalars(stmt.order_by(ChallengeRun.id.desc())).all()]
