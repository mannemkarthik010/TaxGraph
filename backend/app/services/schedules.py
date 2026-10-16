"""The records a CPA expects, built deterministically from the packet with provenance on every row.

Each schedule returns rows that carry the refs they came from (`line` keys, `ev-` ids, `py:/…`,
`asset:…`), so the UI can open the source page or Prove It from any number. Where TaxProof can
independently recompute something (a bridge total, a basis roll-forward, a ratio, a schedule total),
it does so and reports agreement with the supplied engine; it never replaces the engine's number.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date
from typing import Any

from ..packet.index import PacketIndex
from ..packet.refs import json_pointer
from .areas import area_for_line
from .evidence import get_analysis
from .variance import compute_variance

TOLERANCE = 1.0  # whole-dollar engine output vs cents in source documents

# 2024 was a full-year resident return (Form 540); 2025 is part-year (Form 540NR). Lines are matched by
# meaning, not by number: e.g. 540 line 32 is exemption credits while 540NR line 32 is California AGI.
PRIOR_FORM_MAP = {
    "F540NR.13": "CA540.13",  # federal AGI
    "F540NR.17": "CA540.17",  # AGI under California law (a full-year resident's CA AGI is the whole AGI)
    "F540NR.18": "CA540.18",  # deduction
    "F540NR.19": "CA540.19",  # taxable income
    "F540NR.31": "CA540.31",  # tax on taxable income
    "F540NR.64": "CA540.64",  # total tax
    "F540NR.71": "CA540.71",  # withholding
    "F540NR.72": "CA540.72",  # estimated payments
}


def prior_value(idx: PacketIndex, key: str) -> Any | None:
    """The 2024 counterpart of a 2025 line: same key, or an explicitly mapped line on the 2024 form."""
    return idx.prior_year_values.get(key) or idx.prior_year_values.get(PRIOR_FORM_MAP.get(key, ""))


def _lines(idx: PacketIndex, version: str) -> dict[str, Any]:
    return idx.return_lines_by_version[version]


def _val(idx: PacketIndex, version: str, key: str) -> Any:
    line = idx.line(version, key)
    return line["value"] if line else None


def _num(v: Any) -> float:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0


def _check(name: str, ours: float, engine: float, refs: list[str], detail: str, *,
           precision: int = 2, tolerance: float = TOLERANCE) -> dict[str, Any]:
    diff = round(ours - engine, precision)
    return {"check": name, "taxproof": round(ours, precision), "engine": engine, "difference": diff,
            "agrees": abs(diff) <= tolerance, "refs": refs, "detail": detail}


def _line_order(line: str) -> tuple:
    m = re.match(r"(\d+)(.*)", line)
    return (int(m.group(1)), m.group(2)) if m else (9999, line)


def as_of(idx: PacketIndex, version: str) -> str:
    """The evidence cutoff for a version: when the engine computed it."""
    return idx.versions_by_id[version]["computed_at"]


def available_docs(idx: PacketIndex, version: str | None) -> list[Any]:
    """Documents in the file at a version's cutoff. Schedules for an earlier version never use evidence
    that arrived later (with no version, everything received so far)."""
    docs = idx.data["documents"]
    return docs if version is None else [d for d in docs if d["received_at"] <= as_of(idx, version)]


def _std(idx: PacketIndex) -> tuple[float, float]:
    from . import standards
    return standards.variance(idx)


# ---- return summary / tax computation ----------------------------------------------------------------

def tax_computation(idx: PacketIndex, version: str) -> dict[str, Any]:
    """Form 1040 and Form 540NR in line order: the return as a CPA reads it top to bottom."""
    out = {}
    pct, amt = _std(idx)
    for form, juris in (("F1040", "federal"), ("F540NR", "california")):
        rows = []
        for line in sorted((ln for ln in _lines(idx, version).values() if ln["form"] == form),
                           key=lambda ln: _line_order(ln["line"])):
            py = prior_value(idx, line["key"])
            var = compute_variance(line["value"], py["value"] if py else None, pct, amt)
            rows.append({"key": line["key"], "line": line["line"], "label": line["label"], "value": line["value"],
                         "prior_year": py["value"] if py else None, "prior_year_key": py["key"] if py else None,
                         "change": var.change, "variance_flag": var.flagged,
                         "rule": line.get("rule"), "note": line.get("note")})
        out[juris] = rows
    return {"version": version, **out, "summary": idx.versions_by_id[version]["summary"]}


# ---- prior-year comparison -----------------------------------------------------------------------------

def prior_year_comparison(idx: PacketIndex, version: str) -> dict[str, Any]:
    pct, amt = _std(idx)
    lines = _lines(idx, version)
    rows, missing_now = [], []
    reverse_map = {v: k for k, v in PRIOR_FORM_MAP.items()}
    for key, py in idx.prior_year_values.items():
        if not isinstance(py["value"], (int, float)) and py["value"] is not None and key not in lines:
            continue
        cur = lines.get(key) or lines.get(reverse_map.get(key, ""))
        if cur is None:
            missing_now.append({"key": key, "label": py["label"], "prior_year": py["value"], "source": py["source"]})
            continue
        var = compute_variance(cur["value"], py["value"], pct, amt)
        rows.append({"key": cur["key"], "prior_year_key": key, "label": cur["label"], "area": area_for_line(cur), "value": cur["value"],
                     "prior_year": py["value"], "prior_source": py["source"], "change": var.change,
                     "change_pct": var.change_pct, "variance_flag": var.flagged})
    rows.sort(key=lambda r: (not r["variance_flag"], -abs(r["change"] or 0)))
    new_keys = [k for k, ln in lines.items() if prior_value(idx, k) is None and ln["form"] != "F8949"]
    by_area: dict[str, int] = defaultdict(int)
    for k in new_keys:
        by_area[area_for_line(lines[k])] += 1
    return {"version": version, "standard": {"percent": pct, "amount": amt}, "rows": rows,
            "flagged": sum(1 for r in rows if r["variance_flag"]),
            "only_prior_year": missing_now,
            "new_this_year": {"count": len(new_keys), "by_area": dict(by_area)}}


# ---- books to tax ------------------------------------------------------------------------------------

BOOKS_TOTAL_FIELDS = {"total_income", "total_expenses", "net_income"}


def books_to_tax(idx: PacketIndex, version: str) -> dict[str, Any]:
    """Walk the client's books (profit and loss) to Schedule C net profit.

    Every Schedule C line that cites a books value is compared with those books amounts; Schedule C
    lines with no books source are additions; books lines no Schedule C line cites are removals.
    The walk must land exactly on Schedule C net profit, or the bridge says by how much it does not.
    """
    lines = _lines(idx, version)
    books_docs = [d["id"] for d in available_docs(idx, version) if d["document_type"] == "books_profit_loss"]
    books = [ev for doc in books_docs for ev in idx.values_by_document.get(doc, []) if ev["page"] == 1]
    by_field = {ev["field"]: ev for ev in books}
    items = [ev for ev in books if ev["field"] not in BOOKS_TOTAL_FIELDS]
    income_items = [ev for ev in items if ev["field"].lower().startswith(("sales", "income", "revenue"))]
    expense_items = [ev for ev in items if ev not in income_items]
    books_ids = {ev["id"] for ev in books}

    net = by_field.get("net_income")
    checks = []
    if "total_income" in by_field:
        checks.append(_check("Books income items add up", sum(_num(e["value"]) for e in income_items),
                             _num(by_field["total_income"]["value"]), [e["id"] for e in income_items],
                             "Sum of income lines vs printed total income."))
    if "total_expenses" in by_field:
        checks.append(_check("Books expense items add up", sum(_num(e["value"]) for e in expense_items),
                             _num(by_field["total_expenses"]["value"]), [e["id"] for e in expense_items],
                             "Sum of expense lines vs printed total expenses."))

    # Schedule C lines that make up profit: gross receipts and every input of total expenses, plus home office.
    receipts = [k for k in ("SchC.1",) if k in lines]
    expenses = list(lines["SchC.28"]["inputs"]) if "SchC.28" in lines else []
    extra = [k for k in ("SchC.30",) if k in lines]
    rows: list[dict[str, Any]] = []
    cited: set[str] = set()

    def books_amount(line: Any) -> tuple[float, list[str]]:
        srcs = [s for s in line.get("sources", ()) if s in books_ids]
        cited.update(srcs)
        if any(idx.values_by_id[s]["field"] == "total_income" for s in srcs):
            cited.update(e["id"] for e in income_items)
        return sum(_num(idx.values_by_id[s]["value"]) for s in srcs), srcs

    for key in receipts:
        ln = lines[key]
        b, srcs = books_amount(ln)
        rows.append({"kind": "income", "key": key, "label": ln["label"], "books": b, "tax": _num(ln["value"]),
                     "effect": _num(ln["value"]) - b, "books_refs": srcs, "note": ln.get("note")})
    for key in expenses + extra:
        ln = lines[key]
        b, srcs = books_amount(ln)
        rows.append({"kind": "expense", "key": key, "label": ln["label"], "books": b, "tax": _num(ln["value"]),
                     "effect": -(_num(ln["value"]) - b), "books_refs": srcs, "note": ln.get("note")})
    removed = []
    for ev in expense_items:
        if ev["id"] in cited:
            continue
        elsewhere = [{"version": v, "key": k} for v, k in idx.lines_by_source.get(ev["id"], ()) if v == version]
        removed.append({"kind": "removed", "key": None, "label": f"{ev['field']} (books)", "books": _num(ev["value"]),
                        "tax": 0.0, "effect": _num(ev["value"]), "books_refs": [ev["id"]], "note": None,
                        "used_elsewhere": elsewhere})
    rows += removed

    start = _num(net["value"]) if net else 0.0
    end_calc = start + sum(r["effect"] for r in rows)
    engine_profit = _num(lines["SchC.31"]["value"]) if "SchC.31" in lines else 0.0
    checks.append(_check("Bridge lands on Schedule C net profit", end_calc, engine_profit,
                         ([net["id"]] if net else []) + ["SchC.31"],
                         "Books net income plus every reconciling item vs the engine's Schedule C line 31."))
    return {
        "version": version, "books_documents": books_docs,
        "start": {"label": "Books net income", "value": start, "ref": net["id"] if net else None},
        "rows": [r for r in rows if abs(r["effect"]) > 0.005] + [r | {"unchanged": True} for r in rows if abs(r["effect"]) <= 0.005],
        "end": {"label": "Schedule C net profit (line 31)", "value": engine_profit, "key": "SchC.31"},
        "checks": checks,
    }


# ---- depreciation ------------------------------------------------------------------------------------

def depreciation(idx: PacketIndex, version: str) -> dict[str, Any]:
    v = idx.versions_by_id[version]
    prior = {a["asset_id"]: a for a in idx.data["prior_years"].get("asset_records", ())}
    rows, checks = [], []
    by_activity: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for a in v["assets"]:
        p = prior.get(a["asset_id"])
        continuity = None
        if p:
            prior_sum = round(sum(_num(x) for x in p.get("federal", {}).values()), 2)
            continuity = _check(f"{a['asset_id']} prior accumulated depreciation", _num(a["federal"]["prior_accumulated"]),
                                prior_sum, [f"asset:{a['asset_id']}", "py:/asset_records"],
                                "Engine's prior accumulated depreciation vs the sum of the prior preparer's yearly amounts.")
            checks.append(continuity)
        fed, ca, amt = _num(a["federal"]["depreciation_2025"]), _num(a["california"]["depreciation_2025"]), _num(a["amt"]["depreciation_2025"])
        by_activity[a["activity"]]["federal"] += fed
        by_activity[a["activity"]]["california"] += ca
        by_activity[a["activity"]]["amt"] += amt
        rows.append({
            "asset_id": a["asset_id"], "description": a["description"], "activity": a["activity"],
            "cost": a.get("cost"), "land": a.get("land_value_not_depreciated"), "placed_in_service": a["placed_in_service"],
            "method": a["method"], "life_years": a.get("life_years"),
            "federal": dict(a["federal"]), "california": dict(a["california"]), "amt": dict(a["amt"]),
            "federal_vs_california": round(fed - ca, 2), "disposed": a.get("disposed"),
            "disposition": dict(a["disposition"]) if a.get("disposition") else None,
            "new_in_year": a["placed_in_service"].startswith(str(idx.data["household"]["tax_year"])),
            "continuity_agrees": continuity["agrees"] if continuity else None,
            "refs": list(a.get("sources", ())),
        })
    # Activity totals vs the engine's depreciation lines.
    lines = _lines(idx, version)
    for key, ln in lines.items():
        if ln["form"] in ("F4562-E", "F4562-C") and (key.endswith(".22") or ".total" in key):
            assets = [s.split(":", 1)[1] for s in ln.get("sources", ()) if s.startswith("asset:")]
            if key.startswith("F4562-C"):
                assets = [r["asset_id"] for r in rows if r["activity"].startswith("Business")]
            ours = sum(_num(r["federal"]["depreciation_2025"]) for r in rows if r["asset_id"] in assets)
            checks.append(_check(f"{ln['label']} ({key})", ours, _num(ln["value"]), [key] + [f"asset:{x}" for x in assets],
                                 "Sum of this activity's 2025 federal depreciation by asset vs the engine's total."))
    return {"version": version, "assets": rows,
            "by_activity": {k: {kk: round(vv, 2) for kk, vv in t.items()} for k, t in by_activity.items()},
            "checks": checks,
            "california_basis_differences": dict(v["carryovers_out"].get("california", {}).get("depreciation_basis_differences", {}))}


# ---- brokerage ---------------------------------------------------------------------------------------

_LOT_ATTRS = (("proceeds", "proceeds"), ("basis", "basis"), ("wash", "wash_sale"), ("adj", "adjustment"),
              ("acq", "acquired"), ("sold", "sold"), ("desc", "description"), ("asset", "description"))
BOX_TERM = {"A": "short", "B": "short", "C": "short", "G": "short", "H": "short", "I": "short",
            "D": "long", "E": "long", "F": "long", "J": "long", "K": "long", "L": "long"}


def _lots(idx: PacketIndex, version: str) -> list[dict[str, Any]]:
    a = get_analysis(idx)
    out = []
    for key, ln in _lines(idx, version).items():
        if ln["form"] != "F8949" or key.endswith(".total"):
            continue
        box, lot = ln["line"].split(".", 1)
        attrs: dict[str, Any] = {}
        docs: dict[str, int] = defaultdict(int)
        flags = []
        for s in ln.get("sources", ()):
            ev = idx.values_by_id.get(s)
            if not ev:
                continue
            docs[ev["document_id"]] += 1
            flags += [f.as_dict() | {"ref": s} for f in a.value_flags.get(s, ())]
            attr = ev["field"][len(lot) + 1:] if ev["field"].startswith(f"{lot}_") else ev["field"]
            for needle, name in _LOT_ATTRS:
                if needle in attr.lower() and name not in attrs:
                    attrs[name] = ev["value"]
                    break
        doc = max(docs, key=docs.get) if docs else None
        proceeds = attrs.get("proceeds")
        basis = attrs.get("basis")
        gain = _num(ln["value"])
        computed = (_num(proceeds) - _num(basis)) if proceeds is not None and basis is not None else None
        out.append({
            "key": key, "box": box, "lot": lot, "term": BOX_TERM.get(box, "?"),
            "description": attrs.get("description") or ln["label"].split(" (")[0],
            "acquired": attrs.get("acquired"), "sold": attrs.get("sold"),
            "proceeds": proceeds, "basis": basis, "wash_sale": attrs.get("wash_sale"),
            "gain": gain, "adjustment": round(gain - computed, 2) if computed is not None else None,
            # A line the engine computes (no extracted sources, e.g. S-corp excess distributions) is not a sale
            # with a missing basis.
            "computed_line": not ln.get("sources"),
            "basis_missing": basis is None and bool(ln.get("sources")), "document_id": doc,
            "broker": idx.documents_by_id[doc]["issuer"] if doc else "Computed by the engine",
            "flags": flags, "sources": list(ln.get("sources", ())),
        })
    return out


def brokerage(idx: PacketIndex, version: str) -> dict[str, Any]:
    """Hundreds of sales summarised by source and Form 8949 box; detail only on request."""
    lots = _lots(idx, version)
    lines = _lines(idx, version)
    groups: dict[tuple, dict[str, Any]] = {}
    for lot in lots:
        k = (lot["document_id"], lot["box"])
        g = groups.setdefault(k, {"document_id": lot["document_id"], "broker": lot["broker"], "box": lot["box"],
                                  "term": lot["term"], "lots": 0, "proceeds": 0.0, "basis": 0.0, "gain": 0.0,
                                  "basis_missing": 0, "flagged": 0, "largest_gain": None})
        g["lots"] += 1
        g["proceeds"] += _num(lot["proceeds"])
        g["basis"] += _num(lot["basis"])
        g["gain"] += lot["gain"]
        g["basis_missing"] += int(lot["basis_missing"])
        g["flagged"] += int(bool(lot["flags"]))
        if g["largest_gain"] is None or abs(lot["gain"]) > abs(g["largest_gain"]["gain"]):
            g["largest_gain"] = {"key": lot["key"], "description": lot["description"], "gain": lot["gain"]}
    for g in groups.values():
        for f in ("proceeds", "basis", "gain"):
            g[f] = round(g[f], 2)
        g["document_title"] = idx.documents_by_id[g["document_id"]]["title"] if g["document_id"] else None
    checks = []
    for box in sorted({lot["box"] for lot in lots}):
        total = lines.get(f"F8949.{box}.total")
        if total:
            ours = sum(lot["gain"] for lot in lots if lot["box"] == box)
            checks.append(_check(f"Box {box} lots add up to the box total", ours, _num(total["value"]),
                                 [f"F8949.{box}.total"], "Sum of the engine's lot gains vs its box total (whole dollars)."))
    term = {t: round(sum(lot["gain"] for lot in lots if lot["term"] == t), 2) for t in ("short", "long")}
    return {"version": version, "lot_count": len(lots), "groups": sorted(groups.values(), key=lambda g: (g["box"], g["document_id"] or "")),
            "by_term": term, "checks": checks,
            "attention": {"lots": sum(1 for x in lots if x["basis_missing"] or x["flags"]),
                          "basis_missing": sum(1 for x in lots if x["basis_missing"]),
                          "flagged": sum(1 for x in lots if x["flags"])}}


def brokerage_lots(idx: PacketIndex, version: str, *, box: str | None = None, document_id: str | None = None,
                   q: str | None = None, attention: bool = False, sort: str = "gain", offset: int = 0,
                   limit: int = 25) -> dict[str, Any]:
    lots = _lots(idx, version)
    ql = (q or "").lower()
    hits = [x for x in lots
            if (not box or x["box"] == box) and (not document_id or x["document_id"] == document_id)
            and (not ql or ql in (x["description"] or "").lower() or ql in x["key"].lower())
            and (not attention or x["basis_missing"] or x["flags"])]
    if sort == "gain":
        hits.sort(key=lambda x: -abs(x["gain"]))
    elif sort == "sold":
        hits.sort(key=lambda x: str(x["sold"] or ""))
    return {"total": len(hits), "offset": offset, "limit": limit, "items": hits[offset: offset + limit]}


# ---- rentals -----------------------------------------------------------------------------------------

def rentals(idx: PacketIndex, version: str) -> dict[str, Any]:
    lines = _lines(idx, version)
    letters = sorted({m.group(1) for k in lines if (m := re.fullmatch(r"SchE\.1([A-Z])", k))})
    dep = depreciation(idx, version)
    props = []
    for p in letters:
        def get(n: str) -> Any:
            return lines.get(f"SchE.{n}{p}")
        address = get("1")["value"] if get("1") else p
        expenses = [
            {"key": k, "label": ln["label"].replace(f" - property {p}", ""), "value": ln["value"],
             "prior_year": idx.prior_year_values.get(k, {}).get("value")}
            for k, ln in lines.items()
            if (m := re.fullmatch(rf"SchE\.(\d+){p}", k)) and 5 <= int(m.group(1)) <= 19
        ]
        assets = [a for a in dep["assets"] if a["activity"].lower().startswith("rental") and
                  str(address).split(",")[0].lower() in a["activity"].lower()]
        props.append({
            "letter": p, "address": address, "days": get("2")["value"] if get("2") else None,
            "rents": get("3")["value"] if get("3") else None, "rents_key": f"SchE.3{p}",
            "expenses": sorted(expenses, key=lambda e: _line_order(e["key"].split(".")[1])),
            "total_expenses": get("20")["value"] if get("20") else None,
            "net": get("21")["value"] if get("21") else None,
            "allowed": get("22")["value"] if get("22") else None,
            "assets": [{"asset_id": a["asset_id"], "description": a["description"],
                        "federal": a["federal"]["depreciation_2025"], "disposed": a["disposed"]} for a in assets],
            "disposed": next((a["disposed"] for a in assets if a["disposed"]), None),
            "prior_year_net": idx.prior_year_values.get(f"SchE.21{p}", {}).get("value"),
        })
    passive = [{"key": k, "label": ln["label"], "value": ln["value"], "sources": list(ln.get("sources", ()))}
               for k, ln in lines.items() if ln["form"] == "F8582"]
    sale = [{"key": k, "label": ln["label"], "value": ln["value"]}
            for k, ln in sorted(lines.items(), key=lambda kv: _line_order(kv[1]["line"])) if ln["form"] == "F4797"]
    carry_in = {k: v for k, v in idx.data["prior_years"]["carryovers_into_2025"].items() if k.startswith("passive")}
    carry_out = {k: v for k, v in idx.versions_by_id[version]["carryovers_out"]["federal"].items() if k.startswith("passive")}
    checks = []
    for prop in props:
        if prop["rents"] is not None and prop["total_expenses"] is not None and prop["net"] is not None:
            checks.append(_check(f"Property {prop['letter']}: rents less expenses", _num(prop["rents"]) - _num(prop["total_expenses"]),
                                 _num(prop["net"]), [f"SchE.3{prop['letter']}", f"SchE.20{prop['letter']}", f"SchE.21{prop['letter']}"],
                                 "Recomputed net income or loss vs the engine's line 21."))
    return {"version": version, "properties": props, "passive_activity": passive, "sale": sale,
            "suspended_losses": {"into_year": carry_in, "out_of_year": carry_out}, "checks": checks,
            "total": lines.get("SchE.26", {}).get("value")}


# ---- K-1s and basis ----------------------------------------------------------------------------------

def k1_basis(idx: PacketIndex, version: str) -> dict[str, Any]:
    d = idx.data
    cutoff = as_of(idx, version)
    all_k1 = [doc for doc in d["documents"] if doc["document_type"].startswith("K-1")]
    k1_docs = [doc for doc in all_k1 if doc["received_at"] <= cutoff]  # evidence the roll-forward may use
    k1s = []
    for doc in all_k1:
        vals = idx.values_by_document.get(doc["id"], [])
        k1s.append({
            "document_id": doc["id"], "title": doc["title"], "type": doc["document_type"], "tax_year": doc["tax_year"],
            "received_at": doc["received_at"], "received_after_version": doc["received_at"] > cutoff,
            "used_in_versions": [v for v in idx.version_ids if doc["id"] in idx.versions_by_id[v]["documents_used"]],
            "items": [{"ref": ev["id"], "field": ev["field"], "label": ev["label"], "value": ev["value"],
                       "value_type": ev["value_type"],
                       "lines": sorted({k for v, k in idx.lines_by_source.get(ev["id"], ()) if v == version})}
                      for ev in vals],
        })

    # Independent S corporation stock basis roll-forward from the last known basis.
    records = d["prior_years"]["basis_records"].get("scorp_lindqvist_family_woodworks", [])
    known = [r for r in records if r.get("ending_stock_basis") is not None]
    roll = []
    if known:
        start = max(known, key=lambda r: r["year"])
        basis = float(start["ending_stock_basis"])
        roll.append({"year": start["year"], "beginning": None, "income": None, "distributions": None,
                     "ending": basis, "excess_distribution": 0.0, "refs": ["py:/basis_records/scorp_lindqvist_family_woodworks/0"],
                     "source": start["source"], "gap": False})
        tax_year = d["household"]["tax_year"]
        for year in range(start["year"] + 1, tax_year + 1):
            income, dist, refs, src = None, None, [], None
            doc = next((k for k in k1_docs if k["document_type"] == "K-1-1120S" and k["tax_year"] == year), None)
            if doc:
                vals = {ev["field"]: ev for ev in idx.values_by_document.get(doc["id"], [])}
                income = sum(_num(vals[f]["value"]) for f in ("box1", "box4") if f in vals)
                dist = _num(vals["box16d"]["value"]) if "box16d" in vals else 0.0
                refs = [vals[f]["id"] for f in ("box1", "box4", "box16d") if f in vals]
                src = f"{doc['id']} ({doc['title']})"
            elif year == tax_year - 1 and d["prior_years"]["return_2024"].get("K1_1120S"):
                k = d["prior_years"]["return_2024"]["K1_1120S"]
                income, dist = _num(k.get("box1")), _num(k.get("box16D"))
                refs, src = ["py:/return_2024/K1_1120S"], "2024 return K-1"
            gap = income is None
            begin = basis
            if not gap:
                after = begin + income
                excess = max(0.0, dist - after)
                basis = max(0.0, after - dist)
            else:
                excess = 0.0
            later = next((k for k in all_k1 if k["document_type"] == "K-1-1120S" and k["tax_year"] == year and k not in k1_docs), None)
            roll.append({"year": year, "beginning": begin, "income": income, "distributions": dist, "ending": None if gap else basis,
                         "excess_distribution": excess, "refs": refs,
                         "source": src or (f"no K-1 in file at {version} ({later['id']} arrived {later['received_at'][:10]})" if later else "no K-1 in file"),
                         "gap": gap})
            if gap:
                break
    lines = _lines(idx, version)
    checks = []
    if roll and len(roll) >= 2 and not roll[-1]["gap"]:
        this = roll[-1]
        checks.append(_check("Beginning stock basis (Form 7203 line 1)", this["beginning"], _num(_val(idx, version, "F7203.1")),
                             ["F7203.1"] + roll[-2]["refs"], "TaxProof roll-forward from the last known basis vs the engine."))
        checks.append(_check("Distributions in excess of basis", this["excess_distribution"], _num(_val(idx, version, "F7203.excess")),
                             ["F7203.excess"] + this["refs"], "Excess distribution taxed as capital gain."))
    # When a year has no K-1, basis cannot be proven: report the gap and what the engine assumed instead
    # of computing a number from evidence that was not in the file.
    gap = None
    if roll and roll[-1]["gap"]:
        g = roll[-1]
        gap = {"year": g["year"], "last_known": {"year": roll[-2]["year"], "ending": roll[-2]["ending"]} if len(roll) > 1 else None,
               "engine_beginning": _val(idx, version, "F7203.1"), "engine_refs": list((idx.line(version, "F7203.1") or {}).get("sources", ())),
               "detail": f"No {g['year']} S corporation K-1 was in the file when {version} was computed, so stock basis cannot be rolled "
                         f"forward to {d['household']['tax_year']}. The engine's beginning basis rests on its own assumption for the missing year."}
    partnership = {
        "records": list(d["prior_years"]["basis_records"].get("partnership_ridgeline", [])),
        "capital_account_end": idx.versions_by_id[version]["carryovers_out"]["federal"].get("ridgeline_capital_account_end"),
        "outside_basis_known": any(r.get("outside_basis") is not None for r in d["prior_years"]["basis_records"].get("partnership_ridgeline", [])),
    }
    return {"version": version, "k1s": k1s, "scorp_basis": roll, "checks": checks, "gap": gap, "partnership": partnership,
            "form7203": [{"key": k, "label": ln["label"], "value": ln["value"]} for k, ln in lines.items() if ln["form"] == "F7203"]}


# ---- state allocation + residency --------------------------------------------------------------------

def state_allocation(idx: PacketIndex, version: str) -> dict[str, Any]:
    lines = _lines(idx, version)
    rows: dict[str, dict[str, Any]] = {}
    for k, ln in lines.items():
        if ln["form"] != "SchCA540NR":
            continue
        parts = ln["line"].split(".")
        if len(parts) != 2 or parts[1] not in "ABCDE":
            continue
        num, col = parts
        r = rows.setdefault(num, {"line": num, "label": re.sub(r" - (federal|CA additions|CA subtractions|total using CA law|California amount)$", "", ln["label"]),
                                  "columns": {}, "keys": {}, "notes": []})
        r["columns"][col] = ln["value"]
        r["keys"][col] = k
        if ln.get("note"):
            r["notes"].append(ln["note"])
    ordered = sorted(rows.values(), key=lambda r: _line_order(r["line"]))
    for r in ordered:
        dcol, ecol = r["columns"].get("D"), r["columns"].get("E")
        r["california_share"] = round(_num(ecol) / _num(dcol), 4) if dcol not in (None, 0) and ecol is not None else None
    f540 = [{"key": k, "line": ln["line"], "label": ln["label"], "value": ln["value"]}
            for k, ln in sorted(((k, ln) for k, ln in lines.items() if ln["form"] == "F540NR"), key=lambda kv: _line_order(kv[1]["line"]))]
    checks = []
    if "F540NR.32" in lines and "F540NR.17" in lines and "F540NR.34" in lines:
        checks.append(_check("Deduction percentage = CA AGI / total AGI", round(_num(lines["F540NR.32"]["value"]) / _num(lines["F540NR.17"]["value"]), 4),
                             _num(lines["F540NR.34"]["value"]), ["F540NR.32", "F540NR.17", "F540NR.34"], "Recomputed ratio (4 decimals).",
                             precision=4, tolerance=0.0001))
    for r in ordered:
        a, b, c, dval = (r["columns"].get(x) for x in "ABCD")
        if a is not None and dval is not None:
            checks.append(_check(f"Line {r['line']}: A − B + C = D", _num(a) - _num(b) + _num(c), _num(dval),
                                 [v for v in r["keys"].values()], "Federal amount adjusted to California law."))
    return {"version": version, "rows": ordered, "form540nr": f540, "checks": checks, "residency": residency(idx, version)}


def residency(idx: PacketIndex, version: str | None = None) -> dict[str, Any]:
    hh = idx.data["household"]
    year = hh["tax_year"]
    y0, y1 = date(year, 1, 1), date(year, 12, 31)

    def clamp(s: str | None, default: date) -> date:
        return max(y0, min(y1, date.fromisoformat(s))) if s else default

    periods = []
    for r in hh["residency"]:
        a, b = clamp(r["from"], y0), clamp(r["to"], y1)
        periods.append({"state": r["state"], "from": a.isoformat(), "to": b.isoformat(), "status": r["status"],
                        "days": (b - a).days + 1})
    events: list[dict[str, Any]] = []
    for a in hh["addresses"]:
        if a["from"] and a["from"][:4] == str(year):
            events.append({"date": a["from"], "kind": "address", "label": f"Moved in: {a['address']} ({a['type']})", "ref": "household:addresses"})
        if a["to"] and a["to"][:4] == str(year):
            events.append({"date": a["to"], "kind": "address", "label": f"Moved out: {a['address']}", "ref": "household:addresses"})
    # Dated documents that matter for a part-year return: closing statements, the 1099-S, state payments.
    for doc in available_docs(idx, version):
        if doc["document_type"] not in ("closing_statement_buyer", "closing_statement_seller", "1099-S", "payment_confirmation"):
            continue
        for ev in idx.values_by_document.get(doc["id"], []):
            if ev["value_type"] == "date" and isinstance(ev["value"], str) and ev["value"][:4] == str(year):
                events.append({"date": ev["value"], "kind": doc["document_type"], "label": f"{ev['label']} — {doc['title']}",
                               "ref": ev["id"], "document_id": doc["id"]})
    for qa in idx.data["client"]["questionnaire"]:
        if "move" in qa["question"].lower():
            events.append({"date": None, "kind": "client_answer", "label": f"{qa['question']} → {qa['answer']}", "ref": qa["id"]})
    events.sort(key=lambda e: e["date"] or "9999")
    for e in events:
        if e["date"]:
            e["state"] = next((p["state"] for p in periods if p["from"] <= e["date"] <= p["to"]), None)
    param_days = idx.data["engine_reference"]["parameters"].get("ca_resident_days")
    ca_days = sum(p["days"] for p in periods if p["state"] == "CA")
    checks = [_check("California resident days", ca_days, _num(param_days), ["household:residency", "ref:param.ca_resident_days"],
                     "Days from the organizer's residency dates vs the engine parameter.")] if param_days is not None else []
    return {"year": year, "periods": periods, "events": events, "checks": checks,
            "days_in_year": (y1 - y0).days + 1}


# ---- carryovers --------------------------------------------------------------------------------------

def carryovers(idx: PacketIndex, version: str) -> dict[str, Any]:
    d = idx.data
    cin = d["prior_years"]["carryovers_into_2025"]
    cout = idx.versions_by_id[version]["carryovers_out"]
    users: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for src, consumers in idx.lines_by_source.items():
        if src.startswith("py:/carryovers_into_2025/"):
            item = src.rsplit("/", 1)[1]
            for v, key in consumers:
                if v == version:
                    users[item].append({"key": key, "label": idx.line(v, key)["label"], "value": idx.line(v, key)["value"]})
    items = sorted({k for k in cin if k not in ("california", "sources")} | set(cout.get("federal", {})))
    ca_in = cin.get("california", {})
    rows = []
    for item in items:
        into = cin.get(item)
        rows.append({
            "item": item, "into_year": into, "into_ref": f"py:/carryovers_into_2025/{item}" if item in cin else None,
            "used_by": users.get(item, []), "out_of_year": cout.get("federal", {}).get(item),
            "california_into": ca_in.get(item) if isinstance(ca_in.get(item), (int, float)) else None,
            "status": ("used" if users.get(item) else "not used" if into else "new") if into or cout.get("federal", {}).get(item) else "none",
        })
    try:
        source_note = json_pointer(d["prior_years"], "/carryovers_into_2025/sources")
    except KeyError:
        source_note = None
    return {"version": version, "rows": rows, "california_out": dict(cout.get("california", {})),
            "california_note": ca_in.get("note"), "source": source_note}


SCHEDULES = {
    "tax-computation": tax_computation, "prior-year": prior_year_comparison, "books-to-tax": books_to_tax,
    "depreciation": depreciation, "brokerage": brokerage, "rentals": rentals, "k1-basis": k1_basis,
    "state-allocation": state_allocation, "carryovers": carryovers,
}

AREA_SCHEDULES = {
    "business": ["books-to-tax", "depreciation"], "investments": ["brokerage"], "rentals": ["rentals", "depreciation"],
    "k1_basis": ["k1-basis"], "california": ["state-allocation"], "carryovers": ["carryovers"],
}
