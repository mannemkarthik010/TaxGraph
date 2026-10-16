"""Prior-year variance flagging (deterministic).

Firm starter standard: compare to prior year; flag if the change exceeds `flag_if_change_over_percent`
AND exceeds `and_over_amount`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Variance:
    current: float | None
    prior: float | None
    change: float | None
    change_pct: float | None
    flagged: bool


def compute_variance(current: object, prior: object, pct_threshold: float, amount_threshold: float) -> Variance:
    if not isinstance(current, (int, float)) or not isinstance(prior, (int, float)) \
            or isinstance(current, bool) or isinstance(prior, bool):
        return Variance(current if isinstance(current, (int, float)) else None,
                        prior if isinstance(prior, (int, float)) else None, None, None, False)
    change = float(current) - float(prior)
    pct = (change / abs(prior) * 100.0) if prior else None
    over_pct = pct is None or abs(pct) > pct_threshold  # new item where prior year was zero counts as a swing
    flagged = over_pct and abs(change) > amount_threshold
    return Variance(float(current), float(prior), change, round(pct, 1) if pct is not None else None, flagged)
