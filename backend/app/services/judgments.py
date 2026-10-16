"""Judgment Ledger: professional judgments, documented the way the firm standards require.

Every judgment records the topic, the decision, the alternatives considered, the rationale, the
authority relied on (firm rule: "Every judgment call records the authority relied on"), the evidence,
the tax effect, who prepared it, who reviewed it and when.

Tax effects are never invented. A decision is one of:
  keep_engine     – the return as the engine computed it (effect 0 against the return);
  what_if:<id>    – an engine alternative run supplied in the packet (exact engine figures, not an estimate);
  other           – anything else: no effect is computed (record an adjustment if a line changes).
The *tax at stake* is the largest difference between the decision and any alternative considered; a
judgment with more than 1,000 at stake (federal or California) needs partner approval, mirroring the
firm's rule for adjustments.

Lifecycle: recorded → (reviewer) approved, or recorded → reviewed → (partner) approved. Revisions
supersede; nothing is edited in place.
"""

from __future__ import annotations

from typing import Any

from ..packet.index import PacketIndex
from . import standards


class JudgmentError(ValueError):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def _alternatives(idx: PacketIndex) -> dict[str, Any]:
    return {a["id"]: a for a in idx.data.get("what_if", {}).get("alternatives", ())}


def option_effect(idx: PacketIndex, option: str) -> dict[str, Any]:
    if option == "keep_engine":
        return {"federal": 0.0, "california": 0.0, "source": "engine",
                "basis": f"The return as the engine computed it ({idx.current_version})."}
    if option.startswith("what_if:"):
        alt = _alternatives(idx).get(option[8:])
        if alt is None:
            raise JudgmentError(f"Unknown engine alternative '{option[8:]}'.")
        if alt["base_version"] != idx.current_version:
            raise JudgmentError(f"Engine alternative '{alt['id']}' is based on {alt['base_version']}, not the current return.")
        return {"federal": float(alt["federal"]["total_tax_change"]), "california": float(alt["california"]["total_tax_change"]),
                "source": "engine_alternative",
                "basis": f"Engine alternative run '{alt['id']}' supplied in the packet: {alt['description']} "
                         "Change in total tax against the current return (engine figures, not an estimate)."}
    if option == "other":
        return {"federal": None, "california": None, "source": "not_computed",
                "basis": "Not computed: TaxProof does not invent engine results. If a line changes, record an adjustment."}
    raise JudgmentError(f"Unknown option '{option}'. Use keep_engine, what_if:<id> or other.")


def options(idx: PacketIndex, lines: list[str] | None = None) -> list[dict[str, Any]]:
    """Every option a judgment can choose or consider, with its effect; alternatives that change one of
    `lines` are marked `related`."""
    keys = set(lines or ())
    out = [{"option": "keep_engine", "label": "Keep the return as computed", **option_effect(idx, "keep_engine"), "related": True}]
    for alt in _alternatives(idx).values():
        if alt["base_version"] != idx.current_version:
            continue
        changed = {c["key"] for c in alt.get("changed_lines", ())}
        out.append({"option": f"what_if:{alt['id']}", "label": alt["description"], **option_effect(idx, f"what_if:{alt['id']}"),
                    "related": bool(keys & changed), "choices": dict(alt["choices"])})
    out.append({"option": "other", "label": "Another treatment (describe it)", **option_effect(idx, "other"), "related": False})
    return out


def tax_at_stake(decision: dict[str, Any], alternatives: list[dict[str, Any]]) -> float | None:
    diffs = []
    for alt in alternatives:
        for j in ("federal", "california"):
            a, d = alt.get(j), decision.get(j)
            if isinstance(a, (int, float)) and isinstance(d, (int, float)):
                diffs.append(abs(a - d))
    return max(diffs) if diffs else None


def prepare(idx: PacketIndex, *, decision_option: str, alternatives: list[dict[str, Any]]) -> tuple[dict, list[dict], str]:
    """Validate the options and compute the effects. Returns (tax_effect, alternatives, review_required)."""
    if not alternatives:
        raise JudgmentError("Record at least one alternative that was considered.")
    effect = option_effect(idx, decision_option)
    alts = []
    seen = {decision_option}
    for a in alternatives:
        opt = a.get("option") or "other"
        if opt != "other" and opt in seen:
            raise JudgmentError(f"'{opt}' is listed twice (or is also the decision).")
        seen.add(opt)
        eff = option_effect(idx, opt)
        alts.append({"option": opt, "description": (a.get("description") or "").strip()[:2000] or eff["basis"],
                     "federal": eff["federal"], "california": eff["california"], "source": eff["source"],
                     "why_not": (a.get("why_not") or "").strip()[:2000]})
    stake = tax_at_stake(effect, alts)
    effect = {**effect, "tax_at_stake": stake}
    required = "partner" if stake is not None and stake > standards.partner_threshold() else "reviewer"
    return effect, alts, required


def next_status(status: str, review_required: str) -> str:
    if status == "recorded":
        return "approved" if review_required == "reviewer" else "reviewed"
    if status == "reviewed" and review_required == "partner":
        return "approved"
    raise JudgmentError(f"A {status} judgment has nothing left to review.", 409)
