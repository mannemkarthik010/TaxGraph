"""Review Risk Score: an explainable ranking of what a reviewer should look at first.

Not a model's confidence. Each open item scores points on named components, and every component says why
and cites the evidence. The score is the sum, capped at 100:

  extraction_uncertainty     up to 15  a value behind the item was read with low confidence
  source_conflict            up to 20  the page and the extraction (or two sources) disagree
  duplicate_evidence         up to 20  the same evidence may be counted twice
  prior_year_variance        up to 10  a line moved beyond the firm's variance standard
  missing_expected_evidence  up to 15  something the return relies on is not in the file
  calculation_disagreement   up to 15  TaxProof's independent value differs from the engine's
  questionnaire_contradiction up to 10 the client's answer contradicts the documents
  material_tax_impact        up to 25  the estimated tax effect (over the partner threshold = 25)
  missing_verification       up to 10  nobody has verified the line or its evidence
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Adjustment, Judgment, Verification
from ..packet.index import PacketIndex
from . import standards
from .assurance import challenge
from .evidence import get_analysis
from .schedules import prior_value
from .variance import compute_variance

COMPONENTS = {
    "extraction_uncertainty": ("Extraction uncertainty", 15),
    "source_conflict": ("Source conflict", 20),
    "duplicate_evidence": ("Duplicate evidence", 20),
    "prior_year_variance": ("Prior-year variance", 10),
    "missing_expected_evidence": ("Missing expected evidence", 15),
    "calculation_disagreement": ("Calculation disagreement", 15),
    "questionnaire_contradiction": ("Questionnaire contradiction", 10),
    "material_tax_impact": ("Material tax impact", 25),
    "missing_verification": ("Missing verification", 10),
}
LOW_CONFIDENCE = 0.80
DUPLICATE_FAMILIES = {"duplicate_page", "duplicate_document", "duplicate_transaction"}
CONFLICT_FAMILIES = {"extraction", "cross_document", "payments", "state", "conversion", "source_totals", "books_to_tax"}
MISSING_FAMILIES = {"completeness", "broker_detail"}


def level(score: int) -> str:
    return "high" if score >= 50 else "medium" if score >= 25 else "low"


def _component(key: str, points: float, reason: str, refs: list[str]) -> dict[str, Any]:
    label, cap = COMPONENTS[key]
    return {"key": key, "label": label, "points": int(round(min(cap, points))), "max": cap, "reason": reason, "refs": refs[:8]}


def score_items(db: Session, idx: PacketIndex, engagement_id: str, items: list[Any]) -> list[dict[str, Any]]:
    """Score each open inbox item. `items` are services.inbox.Item objects."""
    v = idx.current_version
    lines = idx.return_lines_by_version[v]
    flags = get_analysis(idx).value_flags
    findings = {f.id: f for f in challenge(idx, v)}
    verified = {x.target_ref for x in db.scalars(select(Verification).where(
        Verification.engagement_id == engagement_id, Verification.status == "active")).all()}
    pct, amt = standards.variance(idx)
    adjustments = {a.id: a for a in db.scalars(select(Adjustment).where(Adjustment.engagement_id == engagement_id)).all()}
    judgments = {j.id: j for j in db.scalars(select(Judgment).where(Judgment.engagement_id == engagement_id)).all()}
    threshold = standards.partner_threshold()
    out = []
    for it in items:
        if it.status != "open":
            continue
        keys = [r.split(":", 2)[2] for r in it.refs if r.startswith("line:")] + [r for r in it.refs if r in lines]
        f = findings.get((it.links or {}).get("finding_id") or "")
        evidence = list(f.evidence) if f else [r for r in it.refs if not r.startswith("line:")]
        values = sorted({s for k in keys for s in lines.get(k, {}).get("sources", ()) if s in idx.values_by_id}
                        | {e for e in evidence if e in idx.values_by_id})
        comps = []
        low = [x for x in values if idx.values_by_id[x]["confidence"] < LOW_CONFIDENCE]
        if low:
            worst = min(idx.values_by_id[x]["confidence"] for x in low)
            comps.append(_component("extraction_uncertainty", 15 if worst < 0.6 else 8,
                                    f"{len(low)} value(s) read with confidence below {LOW_CONFIDENCE:.0%} (lowest {worst:.0%}).", low))
        conflicts = [x for x in values if any(fl.severity == "conflict" for fl in flags.get(x, ()))]
        if conflicts or (f and f.family in CONFLICT_FAMILIES and f.status == "fail"):
            comps.append(_component("source_conflict", 20 if conflicts else 12,
                                    f"{len(conflicts)} value(s) disagree with the printed page." if conflicts
                                    else f"TaxProof check failed: {f.title}.", conflicts or evidence))
        if f and f.family in DUPLICATE_FAMILIES:
            comps.append(_component("duplicate_evidence", 20, f"{f.title}.", evidence))
        varied = []
        for k in keys:
            py = prior_value(idx, k)
            if py and compute_variance(lines[k]["value"], py["value"], pct, amt).flagged:
                varied.append(f"line:{v}:{k}")
        if varied:
            comps.append(_component("prior_year_variance", 10, f"{len(varied)} line(s) moved more than {pct:g}% and {amt:,.0f} from 2024.", varied))
        if (f and (f.family in MISSING_FAMILIES or (f.family == "basis" and f.status == "attention"))) or it.nature == "missing":
            comps.append(_component("missing_expected_evidence", 15, f"Evidence the return relies on is not in the file: {it.title}.", evidence or it.refs))
        if f and f.status == "fail" and f.difference:
            rel = abs(f.difference) / max(1.0, abs(float((f.engine or {}).get("value") or 0)) or 1.0)
            comps.append(_component("calculation_disagreement", 15 if rel >= 0.05 else 8,
                                    f"Independent value differs from the engine's by {abs(f.difference):,.0f} {f.unit if f.unit != 'USD' else ''}".strip() + ".",
                                    ([f"line:{v}:{f.lines[0]}"] if f.lines else []) + evidence[:3]))
        if f and f.family == "questionnaire":
            comps.append(_component("questionnaire_contradiction", 10, f"{f.title}.", evidence))
        eff = (f.effect if f else None) or it.detail.get("effect") or {}
        m, why = 0.0, ""
        if eff and eff.get("kind") in ("tax", "balance", None):
            m = max(abs(eff.get("federal") or 0), abs(eff.get("california") or 0))
            why = f"Estimated effect up to {m:,.0f}"
        if it.source == "adjustment" and (a := adjustments.get(it.detail.get("adjustment_id"))):
            m = max(abs((a.effect or {}).get("federal") or 0), abs((a.effect or {}).get("california") or 0))
            why = f"Adjustment #{a.id} moves tax by up to {m:,.0f} (estimate)"
        if it.source == "judgment" and (j := judgments.get(it.detail.get("judgment_id"))):
            stake = (j.tax_effect or {}).get("tax_at_stake") or 0
            m = max(m, float(stake))
            why = f"Tax at stake between the decision and the alternatives considered: {stake:,.0f}"
        if m:
            comps.append(_component("material_tax_impact", 25 if m > threshold else 15 if m > threshold / 4 else 5,
                                    f"{why} (partner threshold {threshold:,.0f}).", it.refs))
        line_refs = [f"line:{v}:{k}" for k in keys]
        if line_refs and not any(r in verified for r in line_refs + values):
            comps.append(_component("missing_verification", 10, "No verification on the line or its evidence yet.", line_refs))
        score = min(100, sum(c["points"] for c in comps))
        out.append({"key": it.key, "title": it.title, "source": it.source, "group": it.group, "areas": it.areas,
                    "score": score, "level": level(score), "components": sorted(comps, key=lambda c: -c["points"]),
                    "refs": it.refs})
    return sorted(out, key=lambda r: (-r["score"], r["key"]))


def by_area(scored: list[dict[str, Any]]) -> list[dict[str, Any]]:
    areas: dict[str, list[dict[str, Any]]] = {}
    for s in scored:
        for a in s["areas"] or ["engagement"]:
            areas.setdefault(a, []).append(s)
    out = []
    for a, rows in areas.items():
        top = max(r["score"] for r in rows)
        out.append({"area": a, "score": top, "level": level(top), "open_items": len(rows), "high": sum(1 for r in rows if r["level"] == "high"),
                    "top_item": rows[0]["key"], "reason": f"Highest item: {rows[0]['title']} ({rows[0]['score']})."})
    return sorted(out, key=lambda r: (-r["score"], r["area"]))
