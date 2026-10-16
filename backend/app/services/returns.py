"""Read models over the supplied return versions. Nothing here recomputes tax."""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from ..packet.index import PacketIndex
from ..packet.refs import resolve
from ..security.masking import is_sensitive_value, mask_extracted_value
from .areas import AREAS, COMPUTATION, area_for_line
from .evidence import get_analysis
from .schedules import prior_value
from .variance import compute_variance

# Headline figures and where they live (2025 v-lines and the 2024 filed return).
HEADLINES = (
    ("federal", "agi", "Adjusted gross income", "F1040.11", "F1040.11"),
    ("federal", "taxable_income", "Taxable income", "F1040.15", "F1040.15"),
    ("federal", "total_tax", "Total tax", "F1040.24", "F1040.24"),
    ("federal", "payments", "Total payments", "F1040.33", "F1040.33"),
    ("federal", "balance_due", "Balance due / (refund)", "F1040.37", None),
    ("federal", "penalty", "Estimated tax penalty", "F1040.38", None),
    ("california", "total_agi", "Total AGI (California law)", "F540NR.17", "CA540.17"),
    ("california", "ca_agi", "California AGI", "F540NR.32", None),
    ("california", "total_tax", "California total tax", "F540NR.64", "CA540.64"),
    ("california", "payments", "California payments", None, None),
    ("california", "balance_due", "California balance due / (refund)", None, None),
)


def _standards(idx: PacketIndex) -> tuple[float, float]:
    from . import standards
    return standards.variance(idx)


def prior_year_balance(idx: PacketIndex) -> float | None:
    lines = idx.data["prior_years"]["return_2024"]["lines"]
    if "F1040.37" in lines:
        return lines["F1040.37"]
    if "F1040.34" in lines:  # 2024 was an overpayment
        return -lines["F1040.34"]
    return None


def return_summary(idx: PacketIndex, version: str) -> dict[str, Any]:
    v = idx.versions_by_id[version]
    pct, amt = _standards(idx)
    prior = idx.prior_year_values
    rows = []
    for juris, field, label, line_key, py_key in HEADLINES:
        current = v["summary"][juris].get(field)
        py_value = prior[py_key]["value"] if py_key and py_key in prior else None
        if juris == "federal" and field == "balance_due":
            py_value = prior_year_balance(idx)
        var = compute_variance(current, py_value, pct, amt)
        rows.append({
            "jurisdiction": juris, "field": field, "label": label, "value": current,
            "line_key": line_key, "prior_year": py_value, "prior_year_key": py_key,
            "change": var.change, "change_pct": var.change_pct, "variance_flag": var.flagged,
        })
    return {
        "version": version,
        "computed_at": v["computed_at"],
        "trigger": v["trigger"],
        "summary": v["summary"],
        "headlines": rows,
        "documents_used": len(v["documents_used"]),
        "documents_superseded": list(v["documents_superseded"]),
        "diagnostics": {"total": len(v["diagnostics"]),
                        "by_severity": dict(Counter(dg["severity"] for dg in v["diagnostics"]))},
        "line_count": len(v["lines"]),
        "variance_standard": {"percent": pct, "amount": amt},
    }


def versions_overview(idx: PacketIndex) -> list[dict[str, Any]]:
    out = []
    for v in idx.data["return_versions"]:
        out.append({
            "version": v["version"], "computed_at": v["computed_at"], "trigger": v["trigger"],
            "federal_total_tax": v["summary"]["federal"]["total_tax"],
            "federal_balance_due": v["summary"]["federal"]["balance_due"],
            "california_total_tax": v["summary"]["california"]["total_tax"],
            "california_balance_due": v["summary"]["california"]["balance_due"],
            "documents_used": len(v["documents_used"]), "lines": len(v["lines"]),
            "changes_from_previous": len(v["changes_from_previous"]),
            "is_current": v["version"] == idx.current_version,
        })
    return out


def line_groups(idx: PacketIndex, version: str) -> list[dict[str, Any]]:
    """Lines grouped by tax area then form — summary first; detail fetched on demand."""
    groups: dict[str, dict[str, int]] = defaultdict(Counter)
    for line in idx.data["return_versions"][idx.version_ids.index(version)]["lines"]:
        groups[area_for_line(line)][line["form"]] += 1
    order = [a.key for a in AREAS] + [COMPUTATION]
    titles = {a.key: a.title for a in AREAS} | {COMPUTATION: "Return computation"}
    return [
        {"area": key, "title": titles[key], "line_count": sum(groups[key].values()),
         "forms": [{"form": f, "count": c} for f, c in sorted(groups[key].items())]}
        for key in order if key in groups
    ]


def _line_brief(line: Any, version: str) -> dict[str, Any]:
    return {
        "key": line["key"], "version": version, "form": line["form"], "line": line["line"],
        "label": line["label"], "value": line["value"], "jurisdiction": line["jurisdiction"],
        "rule": line.get("rule"), "source_count": len(line.get("sources", ())),
        "input_count": len(line.get("inputs", ())), "area": area_for_line(line),
    }


def list_lines(idx: PacketIndex, version: str, *, area: str | None = None, form: str | None = None,
               q: str | None = None, offset: int = 0, limit: int = 100) -> dict[str, Any]:
    lines = idx.data["return_versions"][idx.version_ids.index(version)]["lines"]
    ql = q.lower() if q else None
    hits = [
        ln for ln in lines
        if (not area or area_for_line(ln) == area)
        and (not form or ln["form"] == form)
        and (not ql or ql in ln["key"].lower() or ql in ln["label"].lower())
    ]
    return {"total": len(hits), "offset": offset, "limit": limit,
            "items": [_line_brief(ln, version) for ln in hits[offset: offset + limit]]}


def _source_view(idx: PacketIndex, ref: str, version: str) -> dict[str, Any]:
    r = resolve(idx, ref, version).as_dict()
    if r["kind"] == "extracted_value" and r["exists"]:
        ev = idx.values_by_id[ref]
        shown = mask_extracted_value(ev) if is_sensitive_value(ev) else ev
        r["value"] = shown["value"]
        r["detail"]["text_as_read"] = shown["text_as_read"]
        r["detail"]["document_title"] = idx.documents_by_id[ev["document_id"]]["title"]
        r["detail"]["flags"] = [f.as_dict() for f in get_analysis(idx).value_flags.get(ref, ())]
    return r


def line_detail(idx: PacketIndex, version: str, key: str) -> dict[str, Any] | None:
    line = idx.line(version, key)
    if line is None:
        return None
    rules = idx.data["engine_reference"]["rules"]
    other_versions = {
        vid: ln["value"] for vid, ln in idx.return_lines_by_key.get(key, {}).items()
    }
    py = prior_value(idx, key)  # same 2024 counterpart rule as the summary and area screens
    pct, amt = _standards(idx)
    var = compute_variance(line["value"], py["value"] if py else None, pct, amt)
    diagnostics = [
        dg for dg in idx.versions_by_id[version]["diagnostics"]
        if key in dg["refs"] or any(s in dg["refs"] for s in line.get("sources", ()))
    ]
    return {
        **_line_brief(line, version),
        "note": line.get("note"),
        "rule_description": rules.get(line.get("rule")),
        "inputs": [
            {"key": k, "label": (idx.line(version, k) or {}).get("label"), "value": (idx.line(version, k) or {}).get("value")}
            for k in line.get("inputs", ())
        ],
        "sources": [_source_view(idx, s, version) for s in line.get("sources", ())],
        "used_by": [
            {"key": k, "label": idx.line(version, k)["label"], "value": idx.line(version, k)["value"]}
            for k in idx.lines_by_input.get((version, key), ())
        ],
        "values_by_version": other_versions,
        "prior_year": {"key": py["key"], "value": py["value"], "label": py["label"], "source": py["source"]} if py else None,
        "variance": {"change": var.change, "change_pct": var.change_pct, "flagged": var.flagged},
        "engine_diagnostics": [dict(dg) for dg in diagnostics],
    }
