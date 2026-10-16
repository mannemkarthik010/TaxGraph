"""Tax areas: how TaxProof organizes the return for people (instead of form tabs).

A return line belongs to an area if its key is listed explicitly, otherwise by its form.
Lines in neither (AGI, taxable income, total tax …) belong to the return computation itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AreaDef:
    key: str
    title: str
    forms: tuple[str, ...]
    keys: tuple[str, ...] = ()
    budget_key: str | None = None


AREAS: tuple[AreaDef, ...] = (
    AreaDef("employment", "Employment", ("F8959",), ("F1040.1a", "F1040.1z", "F1040.25a", "F1040.25d", "Sch3.11"),
            "wages_and_stock_compensation"),
    AreaDef("investments", "Investments", ("SchB", "SchD", "F8949", "F8960"),
            ("F1040.2b", "F1040.3a", "F1040.3b", "F1040.7", "Sch2.12"), "investments_and_digital_assets"),
    AreaDef("business", "Business", ("SchC", "SchSE", "F4562-C", "F8995"),
            ("Sch1.3", "Sch1.15", "Sch1.16", "Sch1.17", "Sch2.4", "F1040.13"), "business"),
    AreaDef("rentals", "Rentals", ("F4562-E", "F4797", "F8582"),
            ("SchE.1A", "SchE.3A", "SchE.9A", "SchE.11A", "SchE.12A", "SchE.14A", "SchE.16A", "SchE.18A", "SchE.20A",
             "SchE.21A", "SchE.1B", "SchE.3B", "SchE.9B", "SchE.12B", "SchE.14B", "SchE.16B", "SchE.18B", "SchE.19B",
             "SchE.20B", "SchE.21B", "SchE.2A", "SchE.2B", "SchE.22A", "SchE.22B", "SchE.26"), "rentals_and_sale"),
    AreaDef("k1_basis", "K-1 / Basis", ("F7203",), ("SchE.28A", "SchE.28B", "SchE.32", "SchE.41", "Sch1.5"),
            "pass_throughs_and_basis"),
    AreaDef("retirement", "Retirement", ("F8606", "F8889"), ("F1040.4a", "F1040.4b", "Sch1.13")),
    AreaDef("foreign", "Foreign", ("F8938",), ("SchB.7a", "SchB.7b", "SchB.8", "Sch3.1")),
    AreaDef("deductions", "Deductions & Credits", ("SchA", "F8283", "F8812", "F8863", "F2441", "F8867"),
            ("F1040.12", "F1040.19"), "deductions_and_credits"),
    AreaDef("payments", "Payments", ("F2210",),
            ("F1040.26", "F1040.31", "F1040.33", "F1040.37", "F1040.38", "Sch3.10", "Sch3.15")),
    AreaDef("california", "California", ("F540NR", "SchCA540NR", "ScheduleS", "FTB3885A", "FTB5805"), (), "california"),
    AreaDef("carryovers", "Carryovers", ("F6251",), ("Sch2.1", "Sch2.3")),
)

AREAS_BY_KEY = {a.key: a for a in AREAS}
COMPUTATION = "computation"


def area_for_line(line: Any) -> str:
    key, form = line["key"], line["form"]
    for area in AREAS:
        if key in area.keys:
            return area.key
    for area in AREAS:
        if form in area.forms:
            return area.key
    return COMPUTATION
