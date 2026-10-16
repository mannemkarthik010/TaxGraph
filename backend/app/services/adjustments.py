"""Adjustments: how a CPA acts on a finding without losing the original.

An adjustment targets one return line of the current version. The engine's value stays untouched; the
workpaper's *effective* value is the engine value plus the applied adjustment. Every adjustment carries
who, why, the evidence, the estimated federal and California effect (from the version's
`tax_effect_rates` — an estimate, never an engine rerun) and whether a reviewer or a partner must
approve it (firm rule: a tax effect over 1,000 needs partner sign-off).

States:   proposed ──apply──▶ applied ──undo──▶ undone ──restore──▶ applied
                └──────────────undo (discard)──────────▲
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..packet.index import PacketIndex
from . import standards
from .assurance import Ctx, _dollar_ratio, _effect, ca_category_for, line_category

ACTIVE = ("proposed", "applied")

TRANSITIONS: dict[str, tuple[set[str], str]] = {
    # action: (allowed from, resulting status)
    "apply": ({"proposed"}, "applied"),
    "undo": ({"proposed", "applied"}, "undone"),
    "restore": ({"undone"}, "applied"),
}


class AdjustmentError(ValueError):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


def unit_of(idx: PacketIndex, version: str, key: str) -> str:
    line = idx.line(version, key)
    return "miles" if line and "mile" in line["label"].lower() else "USD"


def fmt_unit(v: float, unit: str) -> str:
    return f"{v:,.0f}{' miles' if unit == 'miles' else ''}"


def estimate_effect(idx: PacketIndex, version: str, key: str, change: float) -> dict[str, Any]:
    """Estimated effect of changing `key` by `change`. Non-dollar lines (miles) go through the line that
    turns them into dollars (miles × standard rate). Lines with no rate category get no estimate."""
    c = Ctx(idx, version)
    if unit_of(idx, version, key) != "USD":
        conv = _dollar_ratio(c, key)
        if conv:
            consumer, factor = conv
            eff = _effect(c, consumer, change * factor,
                          note=f"{change:,.0f} {unit_of(idx, version, key)} × {factor:g} = {change * factor:,.0f} on {consumer}.")
            if eff:
                return eff
    # The same rate context the Challenge engine uses (e.g. California-source income for a lot sold while
    # a California resident), so an adjustment never re-estimates its finding's effect differently.
    ca_cat = ca_category_for(c, key)
    eff = _effect(c, key, change, ca_category=ca_cat,
                  note="Sold while a California resident: California effect uses ca_source_income." if ca_cat else None)
    if eff:
        return eff
    return {"kind": "none", "federal": 0.0, "california": 0.0, "estimate": True, "category": None,
            "basis": f"No tax_effect_rates category maps to {key}; the effect cannot be estimated without rerunning the engine."}


def review_required(effect: dict[str, Any]) -> str:
    big = max(abs(effect.get("federal") or 0), abs(effect.get("california") or 0)) > standards.partner_threshold()
    return "partner" if big else "reviewer"


def validate_target(idx: PacketIndex, version: str, key: str) -> Any:
    if version != idx.current_version:
        raise AdjustmentError(f"Adjustments are made on the current return ({idx.current_version}); {version} is superseded.", 422)
    line = idx.line(version, key)
    if line is None:
        raise AdjustmentError(f"Line '{key}' is not in {version}.", 404)
    if not isinstance(line["value"], (int, float)) or isinstance(line["value"], bool):
        raise AdjustmentError(f"Line '{key}' is not numeric and cannot be adjusted.", 422)
    if line_category(Ctx(idx, version), key) is None and unit_of(idx, version, key) == "USD" \
            and key not in ("F1040.26", "F1040.25a", "Sch3.10", "F540NR.71", "F540NR.72", "F540NR.73"):
        # Allowed, but the effect will be "not estimable"; totals lines would double count their inputs.
        if line.get("inputs"):
            raise AdjustmentError(f"'{key}' is computed from other lines; adjust one of its inputs instead "
                                  f"({', '.join(line['inputs'][:4])}{'…' if len(line['inputs']) > 4 else ''}).", 422)
    return line


def flows_into(idx: PacketIndex, version: str, key: str) -> set[str]:
    """Every line `key` flows into, transitively."""
    out: set[str] = set()
    stack = [key]
    while stack:
        for d in idx.lines_by_input.get((version, stack.pop()), ()):
            if d not in out and d != key:
                out.add(d)
                stack.append(d)
    return out


def flow_related(idx: PacketIndex, version: str, key: str) -> set[str]:
    """Every line `key` flows into, and every line that flows into it (transitively).

    Two adjustments on lines in one flow path express the same correction twice (business miles and the
    car expense computed from them), so their estimated effects would be counted twice. Lines that only
    meet in a later total (gross receipts and an expense) are independent and are not related.
    """
    lines = idx.return_lines_by_version[version]
    upstream: set[str] = set()
    stack = [key]
    while stack:
        for i in lines.get(stack.pop(), {}).get("inputs", ()):
            if i not in upstream and i != key:
                upstream.add(i)
                stack.append(i)
    return upstream | flows_into(idx, version, key)


def history_entry(action: str, user_id: str, role: str, note: str | None = None) -> dict[str, Any]:
    return {"action": action, "by": user_id, "role": role, "at": datetime.now(timezone.utc).isoformat(), "note": note}


def can_approve(role: str, required: str) -> bool:
    return role == "partner" if required == "partner" else role in ("reviewer", "partner")


def workpaper_summary(idx: PacketIndex, version: str, applied: list[Any]) -> dict[str, Any]:
    """Engine totals beside the workpaper's estimate after applied adjustments — always labelled."""
    s = idx.versions_by_id[version]["summary"]
    fed_tax = sum((a.effect or {}).get("federal", 0) for a in applied if (a.effect or {}).get("kind") == "tax")
    ca_tax = sum((a.effect or {}).get("california", 0) for a in applied if (a.effect or {}).get("kind") == "tax")
    fed_bal = sum((a.effect or {}).get("federal", 0) for a in applied if (a.effect or {}).get("kind") == "balance")
    ca_bal = sum((a.effect or {}).get("california", 0) for a in applied if (a.effect or {}).get("kind") == "balance")
    return {
        "version": version,
        "engine": {"federal_total_tax": s["federal"]["total_tax"], "federal_balance_due": s["federal"]["balance_due"],
                   "california_total_tax": s["california"]["total_tax"], "california_balance_due": s["california"]["balance_due"]},
        "applied_adjustments": len(applied),
        "estimated": {
            "federal_total_tax": round(s["federal"]["total_tax"] + fed_tax),
            "federal_balance_due": round(s["federal"]["balance_due"] + fed_tax + fed_bal),
            "california_total_tax": round(s["california"]["total_tax"] + ca_tax),
            "california_balance_due": round(s["california"]["balance_due"] + ca_tax + ca_bal),
        },
        "note": "Engine figures plus the estimated effect of each applied adjustment at this version's tax_effect_rates. "
                "Not an engine recomputation: effects interact and can cross thresholds.",
    }
