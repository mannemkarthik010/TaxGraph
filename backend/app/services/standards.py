"""Firm standards: the packet's starter standards (version 0) overlaid by versions the firm administrator saves.

Everything that applies a standard reads it here, so a change takes effect everywhere at once:
  - variance review (prior-year comparison, area summaries, the prior-year schedule),
  - the partner-approval threshold (adjustments, judgments, Challenge findings),
  - the verification methods offered and accepted.
Records already created keep what applied when they were made (an adjustment's review requirement is stored
with it). The process holds the effective version in memory; it is loaded from the database at startup and
replaced whenever a version is saved.
"""

from __future__ import annotations

import copy
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import FirmStandards
from ..packet.index import PacketIndex

KNOWN_METHODS = ("agreed_to_source_document", "recalculated", "confirmed_with_client", "agreed_to_prior_year",
                 "agreed_to_agency_record", "agreed_to_third_party_record")
DEFAULT_PARTNER_THRESHOLD = 1000.0

_current: dict[str, Any] | None = None
_version: int = 0


class StandardsError(ValueError):
    pass


def starter(idx: PacketIndex) -> dict[str, Any]:
    s = copy.deepcopy(dict(idx.data["firm"]["starter_standards"]))
    s = {k: (list(v) if isinstance(v, (list, tuple)) else dict(v) if hasattr(v, "keys") else v) for k, v in s.items()}
    s.setdefault("partner_threshold", DEFAULT_PARTNER_THRESHOLD)  # the rule text says "over 1,000"
    if "agreed_to_agency_record" not in s["verification_types"]:
        s["verification_types"] = list(s["verification_types"])
        s["verification_types"].insert(4, "agreed_to_agency_record")
    return s


def load(db: Session, idx: PacketIndex) -> None:
    global _current, _version
    row = db.scalar(select(FirmStandards).order_by(FirmStandards.version.desc()).limit(1))
    if row is None:
        _current, _version = starter(idx), 0
    else:
        _current, _version = copy.deepcopy(row.content), row.version


def reset(idx: PacketIndex) -> None:
    """Back to the starter standards (used when a test database is discarded)."""
    global _current, _version
    _current, _version = starter(idx), 0


def effective(idx: PacketIndex | None = None) -> dict[str, Any]:
    if _current is None:
        if idx is None:
            from ..packet import get_index
            idx = get_index()
        reset(idx)
    return _current  # type: ignore[return-value]


def version() -> int:
    return _version


def variance(idx: PacketIndex) -> tuple[float, float]:
    vr = effective(idx)["variance_review"]
    return float(vr["flag_if_change_over_percent"]), float(vr["and_over_amount"])


def partner_threshold() -> float:
    return float(effective().get("partner_threshold", DEFAULT_PARTNER_THRESHOLD))


def verification_types(idx: PacketIndex) -> list[str]:
    return list(effective(idx)["verification_types"])


def validate(content: dict[str, Any]) -> dict[str, Any]:
    """Check a full standards document; raises StandardsError with the reason."""
    vr = content.get("variance_review") or {}
    try:
        pct, amt = float(vr["flag_if_change_over_percent"]), float(vr["and_over_amount"])
    except (KeyError, TypeError, ValueError):
        raise StandardsError("variance_review needs flag_if_change_over_percent and and_over_amount.")
    if not 0 < pct <= 100 or amt < 0:
        raise StandardsError("Variance percent must be in (0, 100] and the amount at least 0.")
    try:
        threshold = float(content.get("partner_threshold"))
    except (TypeError, ValueError):
        raise StandardsError("partner_threshold must be a number.")
    if threshold < 0:
        raise StandardsError("partner_threshold must be at least 0.")
    methods = content.get("verification_types") or []
    unknown = [m for m in methods if m not in KNOWN_METHODS]
    if not methods or unknown:
        raise StandardsError(f"verification_types must be a non-empty subset of {', '.join(KNOWN_METHODS)}"
                             + (f"; unknown: {', '.join(unknown)}" if unknown else "") + ".")
    for k in ("rules", "required_steps", "review_levels"):
        if not isinstance(content.get(k), list) or not all(isinstance(x, str) and x.strip() for x in content[k]):
            raise StandardsError(f"{k} must be a list of non-empty strings.")
    if content["review_levels"] != ["preparer", "reviewer", "partner"]:
        raise StandardsError("review_levels are fixed at preparer, reviewer, partner in this prototype.")
    return content


def save(db: Session, idx: PacketIndex, content: dict[str, Any], *, note: str, user_id: str) -> FirmStandards:
    global _current, _version
    load(db, idx)  # start from what the database says is current (another process may have saved since)
    merged = copy.deepcopy(effective(idx))
    merged.update(copy.deepcopy(content))
    validate(merged)
    latest = db.scalar(select(FirmStandards.version).order_by(FirmStandards.version.desc()).limit(1)) or 0
    row = FirmStandards(version=latest + 1, content=merged, note=note, changed_by_id=user_id)
    db.add(row)
    db.flush()
    _current, _version = merged, row.version
    return row
