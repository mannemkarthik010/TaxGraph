"""Area summaries: the reviewer's first screen for each tax area.

For each area: its key figures this year vs last, how much of it is traceable to evidence, how much
has been verified by a person, what is open (notes, evidence flags, engine diagnostics), and who
owns it. Everything is counted deterministically from the packet plus workpaper records.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from ..packet.index import PacketIndex
from .areas import AREAS, area_for_line
from .evidence import get_analysis
from .schedules import AREA_SCHEDULES, prior_value
from . import standards
from .variance import compute_variance

# The figures that characterise each area (first one is the headline).
AREA_KEY_LINES: dict[str, list[str]] = {
    "employment": ["F1040.1z", "F1040.25a"],
    "investments": ["F1040.7", "F1040.2b", "F1040.3b"],
    "business": ["SchC.31", "SchC.1", "SchSE.12"],
    "rentals": ["SchE.26", "F4797.25"],
    "k1_basis": ["SchE.32", "F7203.excess"],
    "retirement": ["F1040.4b", "Sch1.13"],
    "foreign": ["Sch3.1", "SchB.7a"],
    "deductions": ["F1040.12", "F1040.19"],
    "payments": ["F1040.33", "F1040.37"],
    "california": ["F540NR.64", "F540NR.32"],
    "carryovers": ["Sch2.1"],
}

EVIDENCE_KINDS = ("ev-", "py:", "agency:", "qa-", "msg-", "call-", "asset:", "household:", "D", "doc:")

_TRACE_CACHE: dict[tuple[str, str], dict[str, bool]] = {}


def traceable_lines(idx: PacketIndex, version: str) -> dict[str, bool]:
    """A line is traceable when some path through its inputs reaches cited evidence (not just rules)."""
    key = (idx.packet.sha256, version)
    if key in _TRACE_CACHE:
        return _TRACE_CACHE[key]
    lines = idx.return_lines_by_version[version]
    memo: dict[str, bool] = {}

    def visit(k: str, stack: set[str]) -> bool:
        if k in memo:
            return memo[k]
        if k in stack or k not in lines:
            return False
        ln = lines[k]
        ok = any(s.startswith(EVIDENCE_KINDS) for s in ln.get("sources", ()))
        if not ok:
            stack.add(k)
            ok = any(visit(i, stack) for i in ln.get("inputs", ()))
            stack.discard(k)
        memo[k] = ok
        return ok

    for k in lines:
        visit(k, set())
    _TRACE_CACHE[key] = memo
    return memo


def areas_for_ref(idx: PacketIndex, ref: str, version: str) -> set[str]:
    """Every area a workpaper record touches, derived from what it points at.

    A note on `area:business` belongs to Business; a note on a return line belongs to that line's area;
    a note on evidence (a value, a page, a document, a client answer) belongs to every area whose lines
    cite that evidence in this version. Records on the whole engagement belong to no single area.
    """
    if ref.startswith("area:"):
        return {ref[5:]}
    lines = idx.return_lines_by_version[version]
    if ref.startswith("line:"):
        _, _v, key = ref.split(":", 2)
        line = idx.line(_v, key) or lines.get(key)
        return {area_for_line(line)} if line else set()
    if ref in lines:  # bare line key
        return {area_for_line(lines[ref])}
    if ref.startswith("doc:"):
        doc_id, _, page = ref[4:].partition("#page")
        cited = [ev["id"] for ev in idx.values_by_document.get(doc_id, []) if str(ev["page"]) == page]
    elif ref in idx.documents_by_id:
        cited = [ev["id"] for ev in idx.values_by_document.get(ref, [])] + [ref]
    else:
        cited = [ref]
    return {area_for_line(lines[k]) for c in cited for v, k in idx.lines_by_source.get(c, ()) if v == version}


def area_summaries(idx: PacketIndex, version: str, *, verified_refs: set[str], open_notes: dict[str, dict[str, int]],
                   areas_db: dict[str, Any], assignments: dict[str, str]) -> list[dict[str, Any]]:
    lines = idx.return_lines_by_version[version]
    analysis = get_analysis(idx)
    trace = traceable_lines(idx, version)
    pct, amt = standards.variance(idx)
    budget = idx.data["firm"]["budget_hours"]
    diagnostics = idx.versions_by_id[version]["diagnostics"]

    by_area: dict[str, list[Any]] = defaultdict(list)
    for ln in lines.values():
        by_area[area_for_line(ln)].append(ln)

    out = []
    for area in AREAS:
        alines = by_area.get(area.key, [])
        keys = {ln["key"] for ln in alines}
        values = sorted({s for ln in alines for s in ln.get("sources", ()) if s in idx.values_by_id})
        docs = sorted({idx.values_by_id[v]["document_id"] for v in values})
        flags = [(v, f) for v in values for f in analysis.value_flags.get(v, ())]
        line_refs = {f"line:{version}:{k}" for k in keys}
        verified_values = [v for v in values if v in verified_refs]
        verified_lines = [r for r in line_refs if r in verified_refs]
        diag = [dg for dg in diagnostics if keys & set(dg["refs"]) or set(values) & set(dg["refs"])]
        variances = 0
        for ln in alines:
            py = prior_value(idx, ln["key"])
            if py and compute_variance(ln["value"], py["value"], pct, amt).flagged:
                variances += 1
        figures = []
        for k in AREA_KEY_LINES.get(area.key, []):
            if k not in lines:
                continue
            py = prior_value(idx, k)
            var = compute_variance(lines[k]["value"], py["value"] if py else None, pct, amt)
            figures.append({"key": k, "label": lines[k]["label"], "value": lines[k]["value"],
                            "prior_year": py["value"] if py else None, "change": var.change,
                            "change_pct": var.change_pct, "variance_flag": var.flagged})
        traceable = sum(1 for k in keys if trace.get(k))
        notes = open_notes.get(area.key, {})
        db = areas_db.get(area.key)
        out.append({
            "key": area.key, "title": area.title, "forms": list(area.forms),
            "figures": figures,
            "line_count": len(alines),
            "traceable_lines": traceable,
            "evidence": {
                "documents": docs, "values": len(values), "verified_values": len(verified_values),
                "verified_lines": len(verified_lines),
                "coverage": round(len(verified_values) / len(values), 3) if values else None,
                "traceability": round(traceable / len(alines), 3) if alines else None,
            },
            "issues": {
                "open_notes": notes.get("open", 0), "blocking_notes": notes.get("blocking", 0),
                "conflicts": sum(1 for _, f in flags if f.severity == "conflict"),
                "needs_review": sum(1 for _, f in flags if f.severity == "review"),
                "engine_diagnostics": len(diag), "variances": variances,
            },
            "diagnostics": [{"code": d["code"], "severity": d["severity"], "message": d["message"]} for d in diag],
            "status": {
                "preparer": db.preparer_status if db else "not_started",
                "reviewer": db.reviewer_status if db else "not_started",
                "partner": db.partner_status if db else "not_started",
                "preparer_name": assignments.get("preparer"), "reviewer_name": assignments.get("reviewer"),
            },
            "budget_hours": budget.get(area.budget_key) if area.budget_key else None,
            "schedules": AREA_SCHEDULES.get(area.key, []),
        })
    return out
