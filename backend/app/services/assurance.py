"""Challenge Return: an independent assurance engine that does not trust the supplied tax engine.

Every rule is deterministic Python over the immutable packet. Rules are generic — they look for
patterns (two pages that are the same sheet, an amount added on top of books that the books' own
detail already contains, a summary that disagrees with its detail, a state wage figure that ignores
the move date) — and happen to find this packet's problems. Nothing here hard-codes a document id.

Output is a list of findings, each one clearly a TAXPROOF INDEPENDENT FINDING (never mixed with the
engine's own diagnostics), with the engine's number, TaxProof's number, the evidence, the lines it
touches, and — where a dollar change is implied — an *estimated* tax effect from the packet's
`tax_effect_rates`. The engine is never rerun and no tax number is changed here.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Callable

from ..packet.index import PacketIndex
from . import schedules as S
from . import standards as _standards
from .evidence import get_analysis, printed_numbers

PARTNER_THRESHOLD = 1000.0  # starter firm rule (over 1,000 needs partner sign-off); the effective value is in services.standards
SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
STATUS_ORDER = {"fail": 0, "attention": 1, "explained": 2, "pass": 3}

FAMILIES = {
    "duplicate_document": "Duplicate document detection",
    "duplicate_page": "Duplicate page detection",
    "duplicate_transaction": "Duplicate economic transaction detection",
    "source_totals": "Source total recalculation",
    "cross_document": "Cross-document reconciliation",
    "prior_year": "Prior-year continuity",
    "books_to_tax": "Books-to-tax reconciliation",
    "broker_detail": "Brokerage summary-to-detail reconciliation",
    "completeness": "Expected-document completeness",
    "basis": "Basis continuity",
    "state": "State allocation consistency",
    "questionnaire": "Questionnaire contradictions",
    "payments": "Payment reconciliation",
    "carryovers": "Carryover reconciliation",
    "extraction": "Extraction integrity",
    "conversion": "Currency conversion",
    "judgment": "Items needing professional judgment",
}


@dataclass
class Finding:
    rule: str
    family: str
    subject: str
    title: str
    status: str                       # fail | attention | explained | pass
    severity: str                     # critical | high | medium | low | info
    summary: str
    engine: dict[str, Any] | None = None        # {"label", "value", "ref"}
    independent: dict[str, Any] | None = None   # {"label", "value", "method"}
    difference: float | None = None
    unit: str = "USD"
    lines: list[str] = field(default_factory=list)       # affected return line keys (primary first)
    evidence: list[str] = field(default_factory=list)    # ev-/D/doc:/py:/agency:/qa-/msg- refs
    breakdown: list[dict[str, Any]] = field(default_factory=list)
    effect: dict[str, Any] | None = None        # estimated tax effect (see _effect)
    judgment: bool = False
    engine_diagnostics: list[str] = field(default_factory=list)
    # The single-line change that would act on this finding: {"line", "value"}. Set by a rule when the
    # fix is not "replace the engine value with TaxProof's" (e.g. zero a duplicated payer line).
    adjust: dict[str, Any] | None = None

    @property
    def id(self) -> str:
        return f"{self.rule}:{self.subject}"

    @property
    def proposed_adjustment(self) -> dict[str, Any] | None:
        """What an adjustment would change, or None when no single line can express the fix."""
        if self.status != "fail":
            return None
        if self.adjust:
            return dict(self.adjust)
        if self.engine and self.independent and self.lines and self.engine.get("ref") == self.lines[0]:
            return {"line": self.lines[0], "value": self.independent["value"]}
        return None


    @property
    def partner_review(self) -> bool:
        """Firm rule: a change with a tax effect over 1,000 (federal or state) needs partner sign-off."""
        return bool(self.effect and max(abs(self.effect.get("federal") or 0),
                                        abs(self.effect.get("california") or 0)) > _standards.partner_threshold())

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["id"] = self.id
        d["family_label"] = FAMILIES[self.family]
        d["partner_review"] = self.partner_review
        d["proposed_adjustment"] = self.proposed_adjustment
        return d


@dataclass
class Ctx:
    idx: PacketIndex
    version: str

    @property
    def lines(self) -> dict[str, Any]:
        return self.idx.return_lines_by_version[self.version]

    @property
    def v(self) -> Any:
        return self.idx.versions_by_id[self.version]

    @property
    def as_of(self) -> str:
        """Evidence that arrived after this version was computed is not held against it."""
        return self.v["computed_at"]

    def val(self, key: str) -> Any:
        ln = self.lines.get(key)
        return ln["value"] if ln else None

    def consumers(self, ref: str) -> list[str]:
        return [k for v, k in self.idx.lines_by_source.get(ref, ()) if v == self.version]

    def available(self, doc_id: str) -> bool:
        """Was this document in the file when the version was computed? (The evidence cutoff.)"""
        doc = self.idx.documents_by_id.get(doc_id)
        return bool(doc) and doc["received_at"] <= self.as_of

    def docs_of_type(self, *types: str) -> list[Any]:
        """Documents of these types that existed at this version's cutoff — rules never see later evidence."""
        return [d for d in self.idx.data["documents"] if d["document_type"] in types and d["received_at"] <= self.as_of]

    def agency_as_of(self, record: Any) -> bool:
        """Agency snapshots carry their own date; one pulled after the version was computed is later evidence."""
        return bool(record) and str(record.get("as_of", "")) <= self.as_of[:10]

    def fields(self, doc_id: str) -> dict[str, Any]:
        return {ev["field"]: ev for ev in self.idx.values_by_document.get(doc_id, [])}

    def used(self, doc_id: str) -> bool:
        return doc_id in self.v["documents_used"]


def _n(v: Any) -> float:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0.0


def _fmt(v: float) -> str:
    return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.2f}"


# ---- tax effect estimates ----------------------------------------------------------------------------

def line_category(c: Ctx, key: str) -> tuple[str, int] | None:
    """How a change in this line moves tax, as a tax_effect_rates category and a sign.

    Deterministic mapping by the line's role in the return structure (documented, not inferred by AI).
    """
    lines = c.lines
    if key in ("SchC.1", "SchC.5", "SchC.7"):
        return ("schc_profit", +1)
    if key == "SchC.30" or key in lines.get("SchC.28", {}).get("inputs", ()):
        return ("schc_profit", -1)
    if key.startswith("F8949.") and not key.endswith(".total"):
        box = key.split(".")[1]
        return ("stcg" if S.BOX_TERM.get(box) == "short" else "ltcg", +1)
    if re.fullmatch(r"SchB\.(1|5)\.\d+", key):
        return ("interest", +1)
    if key in ("F1040.1a", "F1040.1z"):
        return ("wages", +1)
    if key in ("Sch1.15", "Sch1.16", "Sch1.17", "Sch1.13"):
        return ("adjustment", +1)
    if key.startswith("SchE.") and re.fullmatch(r"SchE\.(9|1[0-9])[A-Z]", key):
        return ("ordinary_income", -1)
    if key.startswith("SchCA540NR.") and key.endswith(".E"):
        return ("ca_source_income", +1)
    return None


def ca_category_for(c: Ctx, key: str) -> str | None:
    """A line whose California rate differs from its federal category: a Form 8949 lot sold while a
    California resident is California-source income for a part-year return. None = same category."""
    if not key.startswith("F8949.") or key.endswith(".total"):
        return None
    residency = S.residency(c.idx, c.version)
    ca_end = max((p["to"] for p in residency["periods"] if p["state"] == "CA"), default=None)
    lot = next((x for x in S._lots(c.idx, c.version) if x["key"] == key), None)
    return "ca_source_income" if ca_end and lot and lot["sold"] and lot["sold"] <= ca_end else None


def _effect(c: Ctx, key: str, change: float, *, ca_category: str | None = None, note: str | None = None) -> dict[str, Any] | None:
    """Estimated tax change if `key` moved by `change` (independent − engine). Never an engine rerun."""
    if key in ("F1040.26", "F1040.25a", "Sch3.10"):
        return {"kind": "balance", "federal": -change, "california": 0.0, "category": "payment",
                "basis": "Payments change the balance due one-for-one.", "estimate": False}
    if key in ("F540NR.71", "F540NR.72", "F540NR.73"):
        return {"kind": "balance", "federal": 0.0, "california": -change, "category": "payment",
                "basis": "Payments change the balance due one-for-one.", "estimate": False}
    cat = line_category(c, key)
    if cat is None:
        return None
    rates = c.v["tax_effect_rates"]
    category, sign = cat
    fed_rate = rates[category]["federal_per_dollar"]
    ca_cat = ca_category or category
    ca_rate = rates[ca_cat]["california_per_dollar"]
    base = sign * change
    return {
        "kind": "tax", "category": category, "ca_category": ca_cat, "line_change": change,
        "federal": round(base * fed_rate, 0) + 0.0, "california": round(base * ca_rate, 0) + 0.0,  # + 0.0: no -0.0
        "federal_rate": fed_rate, "california_rate": ca_rate, "estimate": True,
        "basis": (f"{_fmt(abs(change))} change on {key} × {category} rate (federal {fed_rate}, California {ca_rate}"
                  f"{'' if ca_cat == category else f' using {ca_cat}'}). Estimate at {c.version}'s rates; "
                  "the engine is not rerun." + (f" {note}" if note else "")),
    }


def _sum_effects(effects: list[dict[str, Any] | None]) -> dict[str, Any] | None:
    effects = [e for e in effects if e]
    if not effects:
        return None
    out = dict(effects[0])
    out["federal"] = round(sum(e["federal"] for e in effects), 0)
    out["california"] = round(sum(e["california"] for e in effects), 0)
    if len(effects) > 1:
        out["basis"] = " + ".join(e["basis"].split(" Estimate")[0] for e in effects) + ". Estimate; the engine is not rerun."
    return out


# ---- rules ---------------------------------------------------------------------------------------------

def rule_duplicate_documents(c: Ctx) -> list[Finding]:
    a = get_analysis(c.idx)
    out = []
    for doc_id, rels in a.duplicate_documents.items():
        for rel in rels:
            if "duplicate_of" not in rel:
                continue
            orig = rel["duplicate_of"]
            if not (c.available(doc_id) and c.available(orig)):
                continue
            dup_lines = {k for ev in c.idx.values_by_document.get(doc_id, []) for k in c.consumers(ev["id"])}
            orig_lines = {k for ev in c.idx.values_by_document.get(orig, []) for k in c.consumers(ev["id"])}
            both = sorted(dup_lines & orig_lines)
            title = f"{doc_id} is a second copy of {orig}"
            if both:
                out.append(Finding("dup-doc", "duplicate_document", doc_id, title, "fail", "high",
                                   f"Values from both copies feed {', '.join(both)}: the same document may be counted twice.",
                                   lines=both, evidence=[doc_id, orig]))
            else:
                out.append(Finding("dup-doc", "duplicate_document", doc_id, title, "pass", "info",
                                   f"Only one copy feeds the return ({', '.join(sorted(orig_lines)) or 'no lines'}); "
                                   f"{doc_id} is not consumed.", lines=sorted(orig_lines), evidence=[doc_id, orig]))
    return out


def _dollar_ratio(c: Ctx, key: str) -> tuple[str, float] | None:
    """A non-dollar line (miles, square feet) usually becomes dollars in a single-input consumer line
    that multiplies it by an engine parameter. Return that consumer and the factor."""
    base = _n(c.val(key))
    if not base:
        return None
    for consumer in c.idx.lines_by_input.get((c.version, key), ()):
        ln = c.lines[consumer]
        if list(ln.get("inputs", ())) == [key] and any(s.startswith("ref:param.") for s in ln.get("sources", ())) \
                and isinstance(ln["value"], (int, float)):
            return consumer, _n(ln["value"]) / base
    return None


def rule_duplicate_pages(c: Ctx) -> list[Finding]:
    a = get_analysis(c.idx)
    out = []
    for doc_id, dups in a.duplicate_pages.items():
        if not c.available(doc_id):
            continue
        for dp in dups:
            p_keep, p_dup = dp["pages"]
            vals = c.idx.values_by_document.get(doc_id, [])
            keep_vals = {ev["id"] for ev in vals if ev["page"] == p_keep}
            dup_vals = [ev for ev in vals if ev["page"] == p_dup]
            hit_lines: dict[str, list[Any]] = defaultdict(list)
            for ev in dup_vals:
                for k in c.consumers(ev["id"]):
                    if any(s in keep_vals for s in c.lines[k].get("sources", ())):
                        hit_lines[k].append(ev)
            if not hit_lines:
                out.append(Finding("dup-page", "duplicate_page", f"{doc_id}#p{p_dup}", f"{doc_id} pages {p_keep} and {p_dup} are the same sheet",
                                   "pass", "info", "The repeated page does not feed any line together with its original.",
                                   evidence=[f"doc:{doc_id}#page{p_keep}", f"doc:{doc_id}#page{p_dup}"]))
                continue
            for key, evs in hit_lines.items():
                ln = c.lines[key]
                dup_amount = sum(_n(ev["value"]) for ev in evs)
                engine_val = _n(ln["value"])
                indep = engine_val - dup_amount
                parts = sorted(({"ref": s, "label": c.idx.values_by_id[s]["label"], "page": c.idx.values_by_id[s]["page"],
                                 "value": c.idx.values_by_id[s]["value"], "duplicate": s in {e["id"] for e in evs}}
                                for s in ln.get("sources", ()) if s in c.idx.values_by_id), key=lambda p: p["page"])
                unit = "miles" if "mile" in ln["label"].lower() else "USD"
                effect, lines = None, [key]
                conv = _dollar_ratio(c, key) if unit != "USD" else None
                if conv:
                    consumer, factor = conv
                    lines.append(consumer)
                    effect = _effect(c, consumer, -dup_amount * factor,
                                     note=f"{_fmt(dup_amount)} {unit} × {factor:g} per {unit[:-1]} = {_fmt(dup_amount * factor)} on {consumer}.")
                elif unit == "USD":
                    effect = _effect(c, key, -dup_amount)
                summary = (f"{ln['label']} ({key}) adds up every page of {doc_id}: "
                           f"{' + '.join(_fmt(_n(p['value'])) for p in parts)} = {_fmt(engine_val)}. "
                           f"Page {p_dup} is a second scan of page {p_keep} ({dp['text_similarity']:.0%} identical text, "
                           f"same readings), so {_fmt(dup_amount)} {unit} may be counted twice.")
                out.append(Finding("dup-page", "duplicate_page", f"{doc_id}#p{p_dup}:{key}",
                                   f"{doc_id} page {p_dup} duplicates page {p_keep} and both feed {key}",
                                   "fail", "high", summary,
                                   engine={"label": f"Supplied engine ({ln.get('rule')})", "value": engine_val, "ref": key},
                                   independent={"label": "Unique pages only", "value": indep,
                                                "method": f"Sum of page totals excluding duplicate page {p_dup}"},
                                   difference=indep - engine_val, unit=unit, lines=lines,
                                   evidence=[f"doc:{doc_id}#page{p_keep}", f"doc:{doc_id}#page{p_dup}"] + [p["ref"] for p in parts],
                                   breakdown=parts, effect=effect))
    return out


def rule_card_receipts_in_books(c: Ctx) -> list[Finding]:
    """Payment-card (1099-K) amounts added on top of books revenue when the books' own detail shows the
    same money already deposited and recorded as sales."""
    out = []
    detail_docs = c.docs_of_type("books_transaction_detail")
    for kdoc in c.docs_of_type("1099-K"):
        f = c.fields(kdoc["id"])
        if "box1a" not in f:
            continue
        amount = _n(f["box1a"]["value"])
        ref = f["box1a"]["id"]
        for key in c.consumers(ref):
            ln = c.lines[key]
            books_refs = [s for s in ln.get("sources", ()) if s in c.idx.values_by_id
                          and c.idx.values_by_id[s]["document_id"] in {d["id"] for d in c.docs_of_type("books_profit_loss")}]
            books_total = sum(_n(c.idx.values_by_id[s]["value"]) for s in books_refs)
            added = _n(ln["value"]) - books_total
            if not books_refs or abs(added - amount) > 1:
                continue
            filer = kdoc["issuer"].split()[0]
            hits = []
            for dd in detail_docs:
                for p in dd["pages"]:
                    text = p["printed_content"]
                    if filer.lower() in text.lower() and amount in printed_numbers(text):
                        sentence = next((s.strip() for s in re.split(r"(?<=\.)\s", text) if filer.lower() in s.lower()), text[:200])
                        hits.append({"ref": f"doc:{dd['id']}#page{p['page']}", "text": sentence})
            if not hits:
                out.append(Finding("card-in-books", "duplicate_transaction", f"{kdoc['id']}:{key}",
                                   f"{kdoc['issuer']} 1099-K added to books revenue", "attention", "medium",
                                   f"{_fmt(amount)} from {kdoc['id']} is added on top of books revenue; nothing in the books detail shows it was already recorded. Confirm.",
                                   lines=[key], evidence=[ref] + books_refs))
                continue
            # Corroborate from the 1099-NEC side: 1099-NEC receipts + receipts with no 1099 should equal books revenue.
            nec = sum(_n(c.fields(d["id"]).get("box1", {}).get("value")) for d in c.docs_of_type("1099-NEC"))
            no1099 = sum(_n(ev["value"]) for dd in detail_docs for ev in c.idx.values_by_document.get(dd["id"], [])
                         if "unreported" in ev["field"] or "no_1099" in ev["field"])
            breakdown = [
                {"label": "Books revenue (P&L)", "value": books_total, "ref": books_refs[0]},
                {"label": "Forms 1099-NEC received", "value": nec, "ref": None},
                {"label": "Deposits from clients who issued no 1099 (books detail)", "value": no1099, "ref": None},
                {"label": f"1099-K added by the engine ({kdoc['issuer']})", "value": amount, "ref": ref},
            ]
            corroborated = nec and abs(nec + no1099 - books_total) <= 1
            summary = (f"The engine adds {_fmt(amount)} from {kdoc['id']} ({kdoc['issuer']}) to books revenue of {_fmt(books_total)} "
                       f"because it could not match a deposit. The books' own detail says: “{hits[0]['text']}” — the card receipts are "
                       f"already inside recorded sales." + (f" Independently, 1099-NEC receipts {_fmt(nec)} + non-1099 deposits {_fmt(no1099)} "
                                                             f"= {_fmt(nec + no1099)} = books revenue, leaving no room for another {_fmt(amount)}." if corroborated else ""))
            out.append(Finding("card-in-books", "duplicate_transaction", f"{kdoc['id']}:{key}",
                               f"{kdoc['issuer']} card receipts may be counted twice in {key}", "fail", "high", summary,
                               engine={"label": "Supplied engine: books + unmatched 1099-K", "value": _n(ln["value"]), "ref": key},
                               independent={"label": "Books revenue (card receipts already inside)", "value": books_total,
                                            "method": "Books detail names the card processor and the amount"},
                               difference=books_total - _n(ln["value"]), lines=[key, "SchC.31"],
                               evidence=[ref] + books_refs + [h["ref"] for h in hits],
                               breakdown=breakdown, effect=_effect(c, key, books_total - _n(ln["value"]))))
    return out


def rule_same_account_interest(c: Ctx) -> list[Finding]:
    """Two interest lines with the same amount whose documents name the same account."""
    out = []
    payer_lines = [k for k in c.lines if re.fullmatch(r"SchB\.1\.\d+", k)]
    by_amount: dict[float, list[str]] = defaultdict(list)
    for k in payer_lines:
        by_amount[_n(c.val(k))].append(k)
    for amount, keys in by_amount.items():
        if amount <= 0 or len(keys) < 2:
            continue
        accounts = {}
        for k in keys:
            docs = {c.idx.values_by_id[s]["document_id"] for s in c.lines[k].get("sources", ()) if s in c.idx.values_by_id}
            texts = " ".join(p["printed_content"] for d in docs for p in c.idx.documents_by_id[d]["pages"])
            accounts[k] = (set(re.findall(r"account ending (\d{4})", texts)), docs)
        for i, k1 in enumerate(keys):
            for k2 in keys[i + 1:]:
                shared = accounts[k1][0] & accounts[k2][0]
                if not shared:
                    continue
                docs = sorted(accounts[k1][1] | accounts[k2][1])
                out.append(Finding("same-account-interest", "duplicate_transaction", f"{k1}+{k2}",
                                   f"Interest of {_fmt(amount)} reported on two lines for the same account", "fail", "medium",
                                   f"{k1} ({c.lines[k1]['label']}) and {k2} ({c.lines[k2]['label']}) both report {_fmt(amount)}, and their documents "
                                   f"({', '.join(docs)}) both refer to the account ending {', '.join(sorted(shared))} — the bank's 1099-INT for the sweep and "
                                   f"the brokerage composite may report the same interest.",
                                   engine={"label": "Supplied engine: two payer lines", "value": amount * 2, "ref": "SchB.2"},
                                   independent={"label": "Counted once", "value": amount, "method": "Same account named on both documents"},
                                   difference=-amount, lines=[k2, "SchB.2"], evidence=docs + list(c.lines[k1]["sources"]) + list(c.lines[k2]["sources"]),
                                   effect=_effect(c, k2, -amount), adjust={"line": k2, "value": 0.0}))
    return out


def rule_source_totals(c: Ctx) -> list[Finding]:
    """Recompute totals printed on source documents from their own line items."""
    out = []
    for doc in c.idx.data["documents"]:
        if not c.available(doc["id"]):
            continue
        vals = c.idx.values_by_document.get(doc["id"], [])
        by_page: dict[int, list[Any]] = defaultdict(list)
        for ev in vals:
            by_page[ev["page"]].append(ev)
        for page, evs in by_page.items():
            total = next((e for e in evs if e["field"] == "page_total"), None)
            items = [e for e in evs if re.fullmatch(r"trip\d+_miles|item\d+_amount|line\d+_amount", e["field"])]
            if total and items:
                s = sum(_n(e["value"]) for e in items)
                ok = abs(s - _n(total["value"])) <= 0.5
                out.append(Finding("page-total", "source_totals", f"{doc['id']}#p{page}", f"{doc['id']} page {page}: items add up to the printed total",
                                   "pass" if ok else "fail", "info" if ok else "medium",
                                   f"{len(items)} items sum to {_fmt(s)}; the page prints {_fmt(_n(total['value']))}.",
                                   engine={"label": "Printed page total", "value": _n(total["value"]), "ref": total["id"]},
                                   independent={"label": "Sum of items", "value": s, "method": "Re-added"},
                                   difference=s - _n(total["value"]), unit="miles" if "miles" in items[0]["field"] else "USD",
                                   evidence=[total["id"]]))
        monthly = [e for e in vals if re.fullmatch(r"box5_\d{2}", e["field"])]
        f = {e["field"]: e for e in vals}
        if monthly and "box1a" in f:
            s = sum(_n(e["value"]) for e in monthly)
            ok = abs(s - _n(f["box1a"]["value"])) <= 0.5
            out.append(Finding("monthly-total", "source_totals", doc["id"], f"{doc['id']}: monthly amounts add up to box 1a",
                               "pass" if ok else "fail", "info" if ok else "medium",
                               f"Twelve monthly amounts sum to {_fmt(s)} vs box 1a {_fmt(_n(f['box1a']['value']))}.",
                               engine={"label": "Box 1a", "value": _n(f["box1a"]["value"]), "ref": f["box1a"]["id"]},
                               independent={"label": "Sum of months", "value": s, "method": "Re-added"},
                               difference=s - _n(f["box1a"]["value"]), evidence=[f["box1a"]["id"]]))
    b = S.books_to_tax(c.idx, c.version)
    for chk in b["checks"][:2]:
        out.append(Finding("books-totals", "source_totals", chk["check"], chk["check"], "pass" if chk["agrees"] else "fail",
                           "info" if chk["agrees"] else "medium", chk["detail"],
                           engine={"label": "Printed total", "value": chk["engine"], "ref": None},
                           independent={"label": "Re-added", "value": chk["taxproof"], "method": "Sum of items"},
                           difference=chk["difference"], evidence=chk["refs"]))
    return out


def rule_broker_summary_detail(c: Ctx) -> list[Finding]:
    """A broker's printed 1099-B summary vs the lots extracted from the same document."""
    out = []
    lots = S._lots(c.idx, c.version)
    by_doc: dict[str, float] = defaultdict(float)
    for lot in lots:
        if lot["document_id"]:
            by_doc[lot["document_id"]] += _n(lot["proceeds"])
    for doc_id, detail in by_doc.items():
        f = c.fields(doc_id)
        if "b_summary_proceeds" in f:
            summary_ref, summary = [f["b_summary_proceeds"]["id"]], _n(f["b_summary_proceeds"]["value"])
        elif "st_proceeds" in f or "lt_proceeds" in f:
            summary_ref = [f[k]["id"] for k in ("st_proceeds", "lt_proceeds") if k in f]
            summary = sum(_n(f[k]["value"]) for k in ("st_proceeds", "lt_proceeds") if k in f)
        elif "total" in f and c.idx.documents_by_id[doc_id]["document_type"] == "1099-DA":
            summary_ref, summary = [f["total"]["id"]], _n(f["total"]["value"])
        else:
            continue
        diff = round(summary - detail, 2)
        doc = c.idx.documents_by_id[doc_id]
        if abs(diff) <= 1:
            out.append(Finding("broker-summary", "broker_detail", doc_id, f"{doc['issuer']}: 1099-B summary agrees with its lots",
                               "pass", "info", f"Summary proceeds {_fmt(summary)} = sum of {sum(1 for x in lots if x['document_id'] == doc_id)} lots.",
                               engine={"label": "Printed summary", "value": summary, "ref": summary_ref[0]},
                               independent={"label": "Sum of lots", "value": round(detail, 2), "method": "Re-added"},
                               difference=diff, evidence=summary_ref + [doc_id]))
            continue
        # Look for the gap on pages the pipeline did not read.
        read_pages = {ev["page"] for ev in c.idx.values_by_document.get(doc_id, [])}
        explained = []
        for p in doc["pages"]:
            if p["page"] in read_pages:
                continue
            m = re.search(r"proceeds ([\d,]+\.\d{2}) basis ([\d,]+\.\d{2})", p["printed_content"])
            if m and abs(float(m.group(1).replace(",", "")) - diff) <= 0.5:
                proceeds, basis = float(m.group(1).replace(",", "")), float(m.group(2).replace(",", ""))
                term = "short" if "short-term" in p["printed_content"] else "long"
                explained.append({"page": p["page"], "proceeds": proceeds, "basis": basis, "term": term,
                                  "text": p["printed_content"][:240]})
        if explained:
            e = explained[0]
            gain = e["proceeds"] - e["basis"]
            key = next((x["key"] for x in lots if x["document_id"] == doc_id), None)
            out.append(Finding("broker-summary", "broker_detail", doc_id,
                               f"{doc['issuer']}: a sale on unread page {e['page']} is missing from the return", "fail", "low",
                               f"Summary proceeds {_fmt(summary)} vs extracted lots {_fmt(detail)}: {_fmt(diff)} short. Page {e['page']} was not read by the "
                               f"pipeline and prints a sale with proceeds {_fmt(e['proceeds'])} and basis {_fmt(e['basis'])} ({e['term']}-term) — exactly the gap. "
                               f"The missing lot's gain or loss is {_fmt(gain)}.",
                               # A sum over many lots: no single line holds this engine value.
                               engine={"label": "Sum of extracted lots", "value": round(detail, 2), "ref": None},
                               independent={"label": "Printed 1099-B summary", "value": summary, "method": f"Gap traced to page {e['page']}"},
                               difference=diff, lines=[key] if key else [],
                               evidence=summary_ref + [f"doc:{doc_id}#page{e['page']}"],
                               breakdown=explained,
                               effect={"kind": "tax", "category": "stcg" if e["term"] == "short" else "ltcg",
                                       "federal": round(gain * c.v["tax_effect_rates"]["stcg" if e["term"] == "short" else "ltcg"]["federal_per_dollar"], 0),
                                       "california": round(gain * c.v["tax_effect_rates"]["stcg" if e["term"] == "short" else "ltcg"]["california_per_dollar"], 0),
                                       "estimate": True, "basis": f"Missing lot gain/loss {_fmt(gain)} × capital gain rate. Estimate."}))
        else:
            out.append(Finding("broker-summary", "broker_detail", doc_id, f"{doc['issuer']}: 1099-B summary disagrees with its lots",
                               "fail", "medium", f"Summary proceeds {_fmt(summary)} vs extracted lots {_fmt(detail)} ({_fmt(diff)}).",
                               engine={"label": "Sum of extracted lots", "value": round(detail, 2), "ref": None},
                               independent={"label": "Printed summary", "value": summary, "method": "Printed on the form"},
                               difference=diff, evidence=summary_ref + [doc_id]))
    return out


def _distinct_docs(c: Ctx, doc_type: str) -> list[Any]:
    dups = {d for d, rels in get_analysis(c.idx).duplicate_documents.items() if any("duplicate_of" in r for r in rels)}
    return [d for d in c.docs_of_type(doc_type) if d["id"] not in dups and d["tax_year"] == c.idx.data["household"]["tax_year"]]


def rule_cross_document(c: Ctx) -> list[Finding]:
    out = []
    w2s = _distinct_docs(c, "W-2")
    for box, key, label in (("box1", "F1040.1a", "Wages"), ("box2", "F1040.25a", "Federal withholding"),
                            ("box17", "F540NR.71", "California withholding")):
        refs = [c.fields(d["id"])[box]["id"] for d in w2s if box in c.fields(d["id"])]
        if not refs or key not in c.lines:
            continue
        s = sum(_n(c.idx.values_by_id[r]["value"]) for r in refs)
        ok = abs(s - _n(c.val(key))) <= 1
        out.append(Finding("w2-sum", "cross_document", key, f"{label}: distinct W-2s agree with {key}", "pass" if ok else "fail",
                           "info" if ok else "high", f"Sum of {box} on {len(w2s)} distinct W-2s = {_fmt(s)}; {key} = {_fmt(_n(c.val(key)))}.",
                           engine={"label": key, "value": _n(c.val(key)), "ref": key},
                           independent={"label": f"Σ W-2 {box}", "value": s, "method": "Distinct W-2s (copies excluded)"},
                           difference=s - _n(c.val(key)), lines=[key], evidence=refs,
                           effect=None if ok else _effect(c, key, s - _n(c.val(key)))))
    return out


def rule_prior_year(c: Ctx) -> list[Finding]:
    out = []
    py = c.idx.prior_year_values
    cin = c.idx.data["prior_years"]["carryovers_into_2025"]
    if all(k in py for k in ("SchD.7", "SchD.15", "SchD.21")):
        st, lt, allowed = -_n(py["SchD.7"]["value"]), -_n(py["SchD.15"]["value"]), -_n(py["SchD.21"]["value"])
        st_carry = max(0.0, st - allowed)
        lt_carry = lt - max(0.0, allowed - st)
        for item, ours in (("capital_loss_short", st_carry), ("capital_loss_long", lt_carry)):
            theirs = _n(cin.get(item))
            ok = abs(ours - theirs) <= 1
            out.append(Finding("py-capital-loss", "prior_year", item, f"{item.replace('_', ' ').capitalize()} carryover agrees with the 2024 Schedule D",
                               "pass" if ok else "fail", "info" if ok else "high",
                               f"2024 net short-term {_fmt(-st)}, long-term {_fmt(-lt)}, loss allowed {_fmt(allowed)} (short-term used first) → {_fmt(ours)}; "
                               f"carryover used in 2025 = {_fmt(theirs)}.",
                               engine={"label": "Carryover into 2025", "value": theirs, "ref": f"py:/carryovers_into_2025/{item}"},
                               independent={"label": "Recomputed from 2024 Schedule D", "value": ours, "method": "2024 lines 7, 15, 21"},
                               difference=ours - theirs, evidence=["py:/return_2024/lines/SchD.7", "py:/return_2024/lines/SchD.15",
                                                                   "py:/return_2024/lines/SchD.21"]))
    for letter, item in (("A", "passive_1450_fremont"), ("B", "passive_1200_barton_hills")):
        k = f"F8582.unallowed.{letter}"
        if k in py and item in cin:
            ours, theirs = -_n(py[k]["value"]), _n(cin[item])
            ok = abs(ours - theirs) <= 1
            out.append(Finding("py-passive", "prior_year", item, f"Suspended passive loss ({py[k]['label'].split(' - ')[-1]}) agrees with 2024",
                               "pass" if ok else "fail", "info" if ok else "high",
                               f"2024 Form 8582 unallowed {_fmt(ours)} vs carryover used {_fmt(theirs)}.",
                               engine={"label": "Carryover into 2025", "value": theirs, "ref": f"py:/carryovers_into_2025/{item}"},
                               independent={"label": "2024 Form 8582", "value": ours, "method": "Prior-year return"},
                               difference=ours - theirs, evidence=[f"py:/return_2024/lines/{k}"]))
    dep = S.depreciation(c.idx, c.version)
    cont = [chk for chk in dep["checks"] if "prior accumulated" in chk["check"]]
    if cont:
        bad = [chk for chk in cont if not chk["agrees"]]
        out.append(Finding("py-depreciation", "prior_year", "accumulated", "Prior accumulated depreciation agrees with the prior preparer's schedule",
                           "fail" if bad else "pass", "high" if bad else "info",
                           f"{len(cont) - len(bad)} of {len(cont)} assets agree." + (f" Breaks: {', '.join(b['check'] for b in bad)}." if bad else ""),
                           evidence=["py:/asset_records"]))
    if "F8606.2" in c.lines and "F8606.14" in py:
        ours, theirs = _n(py["F8606.14"]["value"]), _n(c.val("F8606.2"))
        ok = abs(ours - theirs) <= 1
        out.append(Finding("py-ira-basis", "prior_year", "F8606.2", "IRA basis carried from the 2024 Form 8606",
                           "pass" if ok else "fail", "info" if ok else "high", f"2024 line 14 {_fmt(ours)} vs 2025 line 2 {_fmt(theirs)}.",
                           engine={"label": "F8606.2", "value": theirs, "ref": "F8606.2"},
                           independent={"label": "2024 Form 8606 line 14", "value": ours, "method": "Prior-year return"},
                           difference=ours - theirs, lines=["F8606.2"], evidence=["py:/return_2024/lines/F8606.14"]))
    return out


def rule_books_to_tax(c: Ctx) -> list[Finding]:
    b = S.books_to_tax(c.idx, c.version)
    chk = b["checks"][-1]
    rows = [r for r in b["rows"] if not r.get("unchanged")]
    return [Finding("books-bridge", "books_to_tax", "SchC.31", "Books walk to Schedule C net profit",
                    "pass" if chk["agrees"] else "fail", "info" if chk["agrees"] else "high",
                    f"Books net income {_fmt(b['start']['value'])} + {len(rows)} reconciling items = {_fmt(chk['taxproof'])}; "
                    f"Schedule C line 31 = {_fmt(chk['engine'])}. The bridge reconciles; whether each reconciling item is right is tested by the other rules.",
                    engine={"label": "SchC.31", "value": chk["engine"], "ref": "SchC.31"},
                    independent={"label": "Bridge from books", "value": chk["taxproof"], "method": "Books + reconciling items"},
                    difference=chk["difference"], lines=["SchC.31"], evidence=[b["start"]["ref"]] if b["start"]["ref"] else [],
                    breakdown=[{"label": r["label"], "key": r["key"], "effect": r["effect"]} for r in rows])]


# Expected-document rules: (description, predicate over the packet). Each is a plain, reviewable rule.
def rule_completeness(c: Ctx) -> list[Finding]:
    out = []
    docs = c.idx.data["documents"]
    year = c.idx.data["household"]["tax_year"]
    current = [d for d in docs if d["tax_year"] == year and d["received_at"] <= c.as_of]
    issuers = " | ".join(d["issuer"].lower() for d in current)
    # 1) every 2024 interest/dividend payer has a 2025 document
    for key, pv in c.idx.prior_year_values.items():
        if not re.fullmatch(r"SchB\.(1|5)\.\d+", key) or not pv["label"]:
            continue
        payer = pv["label"].split(" - ", 1)[-1].split(" (")[0]
        found = payer.split()[0].lower() in issuers
        out.append(Finding("expected-payer", "completeness", key, f"2024 payer {payer} has a 2025 document",
                           "pass" if found else "attention", "info" if found else "medium",
                           f"{pv['label']} was on the 2024 return; " + ("a 2025 document from this payer is in file." if found else "no 2025 document from this payer is in file."),
                           evidence=[f"py:/return_2024/lines/{key}"]))
    # 2) every entity that issued a K-1 last year has issued one this year
    py = c.idx.data["prior_years"]["return_2024"]
    for kind, label, entity in (("K-1-1120S", "K1_1120S", "S corporation"), ("K-1-1065", "K1_1065", "partnership")):
        if py.get(label):
            have = [d for d in current if d["document_type"] == kind]
            out.append(Finding("expected-k1", "completeness", kind, f"2025 K-1 from the {entity} that issued one in 2024",
                               "pass" if have else "fail", "info" if have else "high",
                               f"{len(have)} 2025 {kind} document(s) in file as of {c.as_of[:10]}" + (f": {', '.join(d['id'] for d in have)}." if have else " — the return would be missing this entity."),
                               evidence=[f"py:/return_2024/{label}"] + [d["id"] for d in have]))
    # 3) prior preparer's open items: each needs evidence it was closed
    closers = {
        "k-1": lambda: [d["id"] for d in docs if d["document_type"].startswith("K-1") and d["tax_year"] < year - 1 and d["received_at"] <= c.as_of],
        "5498": lambda: [d["id"] for d in docs if d["document_type"] == "5498" and d["tax_year"] == year - 1 and d["received_at"] <= c.as_of],
        "square footage": lambda: [d["id"] for d in current if d["document_type"] == "client_note"],
        "3520": lambda: [d["id"] for d in docs if "3520" in d["title"]],
    }
    for i, item in enumerate(c.idx.data["prior_years"]["prior_preparer_workpaper"].get("open_items_left_by_prior_preparer", [])):
        evidence = next((fn() for k, fn in closers.items() if k in item.lower()), [])
        out.append(Finding("prior-open-item", "completeness", f"item{i}", f"Prior preparer open item: {item[:70]}",
                           "pass" if evidence else "attention", "info" if evidence else "medium",
                           (f"Closed by {', '.join(evidence)}." if evidence else "No document or answer in the file closes this item. Raise it with the client or record why it is out of scope."),
                           evidence=["D07"] + evidence, judgment=not evidence))
    return out


def rule_supplemental_basis(c: Ctx) -> list[Finding]:
    """Broker lots with blank/zero basis where a stock plan supplement gives the adjusted basis for the
    same lot (matched on acquisition date and quantity)."""
    out = []
    sup = defaultdict(dict)
    sup_doc = {}
    sup_scope: dict[str, tuple[str, str]] = {}  # supplement doc → (plan company, broker named in its text)
    for d in c.docs_of_type("stock_plan_supplement"):
        text = " ".join(p["printed_content"] for p in d["pages"])
        broker = re.search(r"through ([A-Z][\w&.]*(?: [A-Z][\w&.]*)*)", text)
        sup_scope[d["id"]] = (d["issuer"].split()[0].lower(), broker.group(1).lower() if broker else "")
        for ev in c.idx.values_by_document.get(d["id"], []):
            m = re.fullmatch(r"(.+)_(adjusted_basis|acquired|ordinary)", ev["field"])
            if m:
                sup[m.group(1)][m.group(2)] = ev
                sup_doc[m.group(1)] = d["id"]
    if not sup:
        return out
    for lot in S._lots(c.idx, c.version):
        if lot["computed_line"]:
            continue
        def same_plan_lot(name: str) -> bool:
            # same acquisition date AND the same company's shares AND sold through the broker the plan names
            f = sup[name]
            company, broker = sup_scope[sup_doc[name]]
            return ("acquired" in f and "adjusted_basis" in f and f["acquired"]["value"] == lot["acquired"]
                    and company in (lot["description"] or "").lower()
                    and (not broker or broker.split()[0] in (lot["broker"] or "").lower()))
        match = next((name for name in sup if same_plan_lot(name)), None)
        if not match:
            continue
        basis = _n(sup[match]["adjusted_basis"]["value"])
        used_basis = _n(lot["proceeds"]) - lot["gain"]  # basis net of any adjustment the engine applied
        if abs(used_basis - basis) <= 1:
            out.append(Finding("supplemental-basis", "basis", lot["key"], f"{lot['description']} uses the plan's adjusted basis",
                               "pass", "info", f"Engine's effective basis {_fmt(used_basis)} = supplement {match} adjusted basis {_fmt(basis)}.",
                               lines=[lot["key"]], evidence=[sup[match]["adjusted_basis"]["id"]] + lot["sources"]))
            continue
        delta = -(basis - used_basis)  # gain falls by the missing basis
        ca_cat = ca_category_for(c, lot["key"])
        out.append(Finding("supplemental-basis", "basis", lot["key"],
                           f"{lot['description']} taxed at {_fmt(used_basis)} basis; the plan statement shows {_fmt(basis)}", "fail", "high",
                           f"The broker reported basis {'blank' if lot['basis'] in (None, 0) else _fmt(_n(lot['basis']))} for this noncovered lot "
                           f"(acquired {lot['acquired']}, sold {lot['sold']}); the engine used it as reported. {sup_doc[match]} gives adjusted basis "
                           f"{_fmt(basis)} for {match} (same acquisition date) — income already taxed in wages at vest. "
                           f"Gain may be overstated by {_fmt(basis - used_basis)}.",
                           engine={"label": "Supplied engine gain", "value": lot["gain"], "ref": lot["key"]},
                           independent={"label": "Gain with plan's adjusted basis", "value": round(_n(lot["proceeds"]) - basis, 2),
                                        "method": f"Proceeds − {match} adjusted basis"},
                           difference=delta, lines=[lot["key"]],
                           evidence=[sup[match]["adjusted_basis"]["id"], sup[match]["acquired"]["id"]] + lot["sources"],
                           effect=_effect(c, lot["key"], delta, ca_category=ca_cat,
                                          note="Sold while a California resident: California effect uses ca_source_income." if ca_cat else None)))
    return out


def rule_basis_rollforward(c: Ctx) -> list[Finding]:
    k = S.k1_basis(c.idx, c.version)
    out = []
    if k["gap"]:
        g = k["gap"]
        out.append(Finding("scorp-basis-gap", "basis", f"gap:{g['year']}", f"S corporation basis cannot be proven: no {g['year']} K-1 in the file",
                           "attention", "high",
                           g["detail"] + (f" Last known basis {_fmt(_n(g['last_known']['ending']))} at the end of {g['last_known']['year']}; "
                                          if g["last_known"] else " ") + f"the engine starts {c.idx.data['household']['tax_year']} at "
                           f"{_fmt(_n(g['engine_beginning']))}. Obtain the {g['year']} K-1 (or a reconstructed basis worksheet) before relying on it.",
                           engine={"label": "Form 7203 line 1", "value": _n(g["engine_beginning"]), "ref": "F7203.1"},
                           lines=["F7203.1"], evidence=["py:/basis_records/scorp_lindqvist_family_woodworks"] + g["engine_refs"],
                           judgment=True))
    for chk in k["checks"]:
        out.append(Finding("scorp-basis", "basis", chk["check"], f"S corporation: {chk['check']}", "pass" if chk["agrees"] else "fail",
                           "info" if chk["agrees"] else "high",
                           f"TaxProof roll-forward {_fmt(chk['taxproof'])} vs engine {_fmt(chk['engine'])}.",
                           engine={"label": "Form 7203", "value": chk["engine"], "ref": chk["refs"][0]},
                           independent={"label": "Roll-forward from last known basis", "value": chk["taxproof"], "method": "K-1s by year"},
                           difference=chk["difference"], lines=[chk["refs"][0]], evidence=chk["refs"][1:]))
    for lot in S._lots(c.idx, c.version):
        if lot["basis_missing"]:
            out.append(Finding("missing-basis", "basis", lot["key"], f"{lot['description']}: no cost basis in the evidence", "attention", "medium",
                               f"The engine used zero basis for {lot['key']} (proceeds {_fmt(_n(lot['proceeds']))}). The client must substantiate the purchase.",
                               lines=[lot["key"]], evidence=lot["sources"], judgment=True))
    return out


def rule_state_wages(c: Ctx) -> list[Finding]:
    """California-source wages vs the move date: wages earned after residency ended belong to the new
    state unless the work was performed in California. A paystub at the move date pins the CA share."""
    out = []
    residency = S.residency(c.idx, c.version)
    ca_end = max((p["to"] for p in residency["periods"] if p["state"] == "CA"), default=None)
    if not ca_end or "SchCA540NR.1.E" not in c.lines:
        return out
    stubs = {d["issuer"]: d for d in c.docs_of_type("paystub")}
    rows, ours_total, refs = [], 0.0, []
    for w2 in _distinct_docs(c, "W-2"):
        f = c.fields(w2["id"])
        ca_wages = _n(f.get("box16", {}).get("value"))
        if not ca_wages:
            continue
        text = " ".join(p["printed_content"] for p in w2["pages"])
        ended = re.search(r"Employment ended (\d{2})/(\d{2})/(\d{4})", text)
        stub = stubs.get(w2["issuer"])
        if ended and f"{ended.group(3)}-{ended.group(1)}-{ended.group(2)}" <= ca_end:
            rows.append({"employer": w2["issuer"], "w2_ca_wages": ca_wages, "ca_source": ca_wages,
                         "method": f"Employment ended {ended.group(1)}/{ended.group(2)}/{ended.group(3)}, before the move", "ref": f["box16"]["id"]})
            ours_total += ca_wages
        elif stub and "ytd_ca_wages" in c.fields(stub["id"]) and stub["received_at"] <= c.as_of:
            sf = c.fields(stub["id"])
            ytd = _n(sf["ytd_ca_wages"]["value"])
            rows.append({"employer": w2["issuer"], "w2_ca_wages": ca_wages, "ca_source": ytd,
                         "method": f"Paystub {stub['id']}: California taxable wages year-to-date at the move", "ref": sf["ytd_ca_wages"]["id"]})
            ours_total += ytd
            refs += [sf["ytd_ca_wages"]["id"], f"doc:{stub['id']}#page1"]
        else:
            rows.append({"employer": w2["issuer"], "w2_ca_wages": ca_wages, "ca_source": ca_wages, "method": "No evidence to split; W-2 used", "ref": f["box16"]["id"]})
            ours_total += ca_wages
        refs.append(f["box16"]["id"])
    engine_val = _n(c.val("SchCA540NR.1.E"))
    diff = ours_total - engine_val
    if abs(diff) <= 1:
        out.append(Finding("ca-wages", "state", "SchCA540NR.1.E", "California-source wages respect the move date", "pass", "info",
                           f"California wages {_fmt(engine_val)} agree with the evidence-based split.", lines=["SchCA540NR.1.E"], evidence=refs))
        return out
    out.append(Finding("ca-wages", "state", "SchCA540NR.1.E", "California-source wages include pay earned after the move to Texas", "fail", "high",
                       f"Schedule CA column E takes California wages from W-2 box 16 ({_fmt(engine_val)}). The household left California on {ca_end}. "
                       f"Evidence-based split: " + "; ".join(f"{r['employer']} {_fmt(r['ca_source'])} ({r['method']})" for r in rows) +
                       f" = {_fmt(ours_total)}. The employer's W-2 assigns post-move wages to California (box 16 reflects its payroll setting, not where the work was done).",
                       engine={"label": "Supplied engine: W-2 box 16", "value": engine_val, "ref": "SchCA540NR.1.E"},
                       independent={"label": "Wages earned while a California resident", "value": ours_total, "method": "Employment dates and the move-date paystub"},
                       difference=diff, lines=["SchCA540NR.1.E"], evidence=refs + ["household:residency", "household:addresses"], breakdown=rows,
                       effect=_effect(c, "SchCA540NR.1.E", diff), judgment=True))
    return out


def rule_state_checks(c: Ctx) -> list[Finding]:
    st = S.state_allocation(c.idx, c.version)
    res = st["residency"]
    out = []
    for chk in res["checks"] + st["checks"][:1]:
        out.append(Finding("state-recalc", "state", chk["check"], chk["check"], "pass" if chk["agrees"] else "fail",
                           "info" if chk["agrees"] else "high", chk["detail"],
                           engine={"label": "Engine", "value": chk["engine"], "ref": chk["refs"][-1]},
                           independent={"label": "Recomputed", "value": chk["taxproof"], "method": chk["detail"]},
                           difference=chk["difference"], unit="days" if "days" in chk["check"] else ("ratio" if "percentage" in chk["check"] else "USD"),
                           evidence=chk["refs"]))
    return out


QUESTIONNAIRE_RULES: list[tuple[str, str, Callable[[Ctx], tuple[bool, str, list[str], list[str]]], str]] = []


def _q(pattern: str, answer: str, title: str):
    def deco(fn):
        QUESTIONNAIRE_RULES.append((pattern, answer, fn, title))
        return fn
    return deco


@_q(r"sell any stocks|sell any .*investments", r"^\s*no\b", "Client said no investments were sold")
def _q_sales(c: Ctx):
    lots = [x for x in S._lots(c.idx, c.version) if not x["computed_line"] and x["box"] not in "HK"]
    return bool(lots), f"Brokerage documents report {len(lots)} sales on Form 8949.", [lots[0]["key"]] if lots else [], sorted({x["document_id"] for x in lots if x["document_id"]})


@_q(r"cryptocurrency|digital assets", r"didn't really sell|did not sell|^\s*no\b", "Client said crypto wasn't really sold")
def _q_crypto(c: Ctx):
    lots = [x for x in S._lots(c.idx, c.version) if x["box"] in "HK"]
    return bool(lots), f"{len(lots)} digital asset dispositions are reported (Form 1099-DA).", [lots[0]["key"]] if lots else [], sorted({x["document_id"] for x in lots if x["document_id"]})


@_q(r"IRA details|prior basis", r"prior basis: none|no prior basis", "Client said there is no prior IRA basis")
def _q_ira(c: Ctx):
    pv = c.idx.prior_year_values.get("F8606.14")
    return bool(pv and _n(pv["value"])), f"The 2024 Form 8606 line 14 shows basis of {_fmt(_n(pv['value'])) if pv else 0}; the engine carried it.", ["F8606.2"], ["py:/return_2024/lines/F8606.14"]


@_q(r"eligible for health coverage through", r"^\s*yes\b", "Client said the self-employed spouse was eligible for employer coverage")
def _q_sehi(c: Ctx):
    v = _n(c.val("Sch1.17"))
    note = c.idx.data["prior_years"]["return_2024"].get("notes", {}).get("Sch1.17", "")
    return v > 0, f"The return deducts self-employed health insurance of {_fmt(v)} (Sch1.17). 2024 note: “{note}”", ["Sch1.17"], ["py:/return_2024/lines/Sch1.17"] if note else []


def rule_questionnaire(c: Ctx) -> list[Finding]:
    out = []
    for qa in c.idx.data["client"]["questionnaire"]:
        for pattern, answer, fn, title in QUESTIONNAIRE_RULES:
            if not re.search(pattern, qa["question"], re.I) or not re.search(answer, qa["answer"], re.I):
                continue
            contradicts, detail, lines, ev = fn(c)
            if not contradicts:
                continue
            effect = None
            if fn is _q_sehi:
                effect = _effect(c, "Sch1.17", -_n(c.val("Sch1.17")))
                effect = effect and {**effect, "potential": True,
                                     "basis": effect["basis"] + " Shown only if the deduction were disallowed — a judgment, not a finding of error."}
            out.append(Finding("questionnaire", "questionnaire", qa["id"], f"{title}: the file says otherwise", "attention",
                               "medium" if effect else "low",
                               f"{qa['id']}: “{qa['question']}” → “{qa['answer']}”. {detail} Confirm with the client and record how the return treats it.",
                               lines=lines, evidence=[qa["id"]] + ev, effect=effect, judgment=True))
    return out


def rule_payments(c: Ctx) -> list[Finding]:
    out = []
    year = c.idx.data["household"]["tax_year"]
    # Federal estimates vs the IRS account transcript (latest snapshot available at this version)
    snaps = [s for s in c.idx.agency_records.get("irs_account_transcript_2025", []) if c.agency_as_of(s)]
    if not snaps and "F1040.26" in c.lines:
        out.append(Finding("payments-federal", "payments", "F1040.26", "Federal estimated payments not yet confirmable",
                           "attention", "low", f"No IRS account transcript had been pulled when {c.version} was computed ({c.as_of[:10]}); "
                           "estimated payments rest on the client's confirmations only.", lines=["F1040.26"],
                           evidence=list(c.lines["F1040.26"]["sources"])))
    if snaps and "F1040.26" in c.lines:
        snap = max(snaps, key=lambda s: s["as_of"])
        i = c.idx.agency_records["irs_account_transcript_2025"].index(snap)
        est = [t for t in snap["transactions"] if t["code"] == "670" and "extension" not in t["description"].lower()
               and f"{year}-01-01" <= t["date"] <= f"{year + 1}-01-31"]
        agency = sum(_n(t["amount"]) for t in est)
        claimed = _n(c.val("F1040.26"))
        note = c.lines["F1040.26"].get("note") or ""
        ok = abs(agency - claimed) <= 1
        out.append(Finding("payments-federal", "payments", "F1040.26", "Federal estimated payments agree with the IRS transcript",
                           "pass" if ok else "fail", "info" if ok else "high",
                           (f"Return claims {_fmt(claimed)} ({note}). IRS transcript as of {snap['as_of']} shows "
                            + ", ".join(f"{t['date']} {_fmt(_n(t['amount']))}" for t in est) + f" = {_fmt(agency)}."
                            + ("" if ok else " The client's recollection (questionnaire) differs from what the IRS received.")),
                           engine={"label": "F1040.26", "value": claimed, "ref": "F1040.26"},
                           independent={"label": "IRS account transcript", "value": agency, "method": "Code 670 estimated payments for the tax year"},
                           difference=agency - claimed, lines=["F1040.26"], evidence=[f"agency:/irs_account_transcript_2025/{i}"] + list(c.lines["F1040.26"]["sources"]),
                           breakdown=[{"date": t["date"], "amount": t["amount"]} for t in est],
                           effect=None if ok else _effect(c, "F1040.26", agency - claimed)))
        ext = [t for t in snap["transactions"] if "extension" in t["description"].lower() and _n(t["amount"])]
        if "Sch3.10" in c.lines and _n(c.val("Sch3.10")):
            amt = sum(_n(t["amount"]) for t in ext)
            ok2 = abs(amt - _n(c.val("Sch3.10"))) <= 1 if ext else False
            out.append(Finding("payments-extension", "payments", "Sch3.10", "Extension payment agrees with the IRS transcript",
                               "pass" if ok2 else "attention", "info" if ok2 else "low",
                               f"Return {_fmt(_n(c.val('Sch3.10')))}; transcript {('shows ' + _fmt(amt)) if ext else 'snapshot predates the payment'}.",
                               lines=["Sch3.10"], evidence=[f"agency:/irs_account_transcript_2025/{i}"]))
    # California estimates vs FTB account and the payment confirmations' tax-year designation
    ftb = c.idx.agency_records.get("ftb_account")
    if ftb and not c.agency_as_of(ftb) and "F540NR.72" in c.lines:
        out.append(Finding("payments-california", "payments", "F540NR.72", "California estimated payments not yet confirmable",
                           "attention", "low", f"The FTB account record is dated {ftb['as_of']}, after {c.version} was computed; "
                           "California estimates rest on the payment confirmations only.", lines=["F540NR.72"],
                           evidence=list(c.lines["F540NR.72"]["sources"])))
    if ftb and c.agency_as_of(ftb) and "F540NR.72" in c.lines:
        agency = sum(_n(p["amount"]) for p in ftb.get(f"tax_year_{year}_payments", []))
        claimed = _n(c.val("F540NR.72"))
        designated_prior = []
        for d in c.docs_of_type("payment_confirmation"):
            f = c.fields(d["id"])
            for name, ev in f.items():
                m = re.fullmatch(r"(pay\d+)_year", name)
                if m and str(ev["value"]) != str(year) and f.get(f"{m.group(1)}_date", {}).get("value", "") >= f"{year}-01-01":
                    amt = f.get(f"{m.group(1)}_amount")
                    if amt and amt["id"] in c.lines["F540NR.72"].get("sources", ()) or (amt and f"{m.group(1)}_date" in f and f[f"{m.group(1)}_date"]["id"] in c.lines["F540NR.72"].get("sources", ())):
                        designated_prior.append({"date": f[f"{m.group(1)}_date"]["value"], "amount": _n(amt["value"]), "year": ev["value"], "ref": ev["id"]})
        ok = abs(agency - claimed) <= 1
        out.append(Finding("payments-california", "payments", "F540NR.72", "California estimated payments agree with the FTB account",
                           "pass" if ok else "fail", "info" if ok else "high",
                           f"Return claims {_fmt(claimed)}. FTB account (as of {ftb['as_of']}) credits {_fmt(agency)} to {year}."
                           + (" " + "; ".join(f"The {p['date']} payment of {_fmt(p['amount'])} was designated tax year {p['year']} on the confirmation" for p in designated_prior) + "." if designated_prior else "")
                           + (" FTB holds it as a credit for the prior year." if any("2024 credit" in (x.get("note") or "") for x in ftb.get(f"tax_year_{year - 1}_payments_after_filing", [])) else ""),
                           engine={"label": "F540NR.72", "value": claimed, "ref": "F540NR.72"},
                           independent={"label": "FTB account", "value": agency, "method": "Payments credited to the tax year"},
                           difference=agency - claimed, lines=["F540NR.72"],
                           evidence=["agency:/ftb_account"] + [p["ref"] for p in designated_prior],
                           breakdown=designated_prior, effect=None if ok else _effect(c, "F540NR.72", agency - claimed)))
    return out


def rule_carryovers(c: Ctx) -> list[Finding]:
    out = []
    cout = c.v["carryovers_out"]["federal"]
    sep_docs = c.docs_of_type("retirement_contribution")
    if "sep_contribution_not_deductible_for_2025" in cout and sep_docs and "Sch1.16" in c.lines:
        contributed = _n(c.fields(sep_docs[0]["id"]).get("amount", {}).get("value"))
        ours = contributed - _n(c.val("Sch1.16"))
        ok = abs(ours - _n(cout["sep_contribution_not_deductible_for_2025"])) <= 1
        out.append(Finding("carry-sep", "carryovers", "sep", "Nondeductible SEP contribution carried forward",
                           "pass" if ok else "fail", "info" if ok else "medium",
                           f"Contributed {_fmt(contributed)} − deducted {_fmt(_n(c.val('Sch1.16')))} = {_fmt(ours)}; carryover {_fmt(_n(cout['sep_contribution_not_deductible_for_2025']))}.",
                           difference=ours - _n(cout["sep_contribution_not_deductible_for_2025"]), evidence=[sep_docs[0]["id"]], lines=["Sch1.16"]))
    if "minimum_tax_credit_from_2025_amt" in cout and "F6251.11" in c.lines:
        ok = abs(_n(cout["minimum_tax_credit_from_2025_amt"]) - _n(c.val("F6251.11"))) <= 1
        out.append(Finding("carry-mtc", "carryovers", "mtc", "Minimum tax credit carryforward equals 2025 AMT",
                           "pass" if ok else "fail", "info" if ok else "medium",
                           f"AMT {_fmt(_n(c.val('F6251.11')))} vs credit carried {_fmt(_n(cout['minimum_tax_credit_from_2025_amt']))}.",
                           lines=["F6251.11"], evidence=[]))
    if "SchD.16" in c.lines and _n(c.val("SchD.16")) > 0:
        zero = all(_n(cout.get(k)) == 0 for k in ("capital_loss_short", "capital_loss_long"))
        out.append(Finding("carry-capital", "carryovers", "capital_loss", "No capital loss carried out when 2025 has a net gain",
                           "pass" if zero else "fail", "info" if zero else "medium",
                           f"Net capital gain {_fmt(_n(c.val('SchD.16')))} absorbs the 2024 carryovers; carryover out is {'zero' if zero else 'not zero'}.",
                           lines=["SchD.16"]))
    return out


def rule_extraction(c: Ctx) -> list[Finding]:
    """Readings that disagree with the printed page or the organizer, when they reach the return."""
    a = get_analysis(c.idx)
    out = []
    for ev_id, flags in a.value_flags.items():
        ev = c.idx.values_by_id[ev_id]
        if not c.available(ev["document_id"]):
            continue
        lines = c.consumers(ev_id)
        doc = c.idx.documents_by_id[ev["document_id"]]
        for f in flags:
            if f.code == "IDENTITY_MISMATCH":
                person = next((p for p in c.idx.data["household"]["people"] if p.get("ssn", "")[:6] == str(ev["value"])[:6]), None)
                if not person:
                    continue
                out.append(Finding("identity", "extraction", f"{person['id']}:{ev_id}",
                                   f"{person['name']}'s SSN in the organizer differs from {doc['id']} ({doc['title']})", "fail", "critical",
                                   f"The return uses the organizer SSN ending {person['ssn'][-4:]}; {doc['id']} shows one ending {str(ev['value'])[-4:]} "
                                   f"(same first five digits). A dependent TIN/name mismatch rejects the e-file. Confirm against the Social Security card.",
                                   lines=[k for k in c.lines if k.startswith(("F8812", "F2441")) and "dependent" in c.lines[k]["label"].lower()][:2],
                                   evidence=[ev_id, f"household:{person['id']}"]))
            elif f.severity == "conflict" and lines:
                out.append(Finding("extraction-conflict", "extraction", ev_id, f"{doc['id']}: {ev['label']} read differently from the page",
                                   "fail", "medium", f"{f.message} It feeds {', '.join(lines)}.",
                                   lines=lines, evidence=[ev_id, f"doc:{ev['document_id']}#page{ev['page']}"]))
        # One review finding per value, only when no stronger finding already covers it: values with a
        # conflict are reported above, and sale lots are covered by the basis rules.
        reviews = [f for f in flags if f.severity == "review" and f.code != "VALUE_NOT_PRINTED"]
        if reviews and lines and not any(f.severity == "conflict" for f in flags) \
                and not any(k.startswith("F8949.") for k in lines):
            out.append(Finding("extraction-review", "extraction", ev_id, f"{doc['id']}: {ev['label']} needs a human look",
                               "attention", "low", " ".join(f.message for f in reviews) + f" It feeds {', '.join(lines)}.", lines=lines,
                               evidence=[ev_id, f"doc:{ev['document_id']}#page{ev['page']}"], judgment=True))
    return out


def rule_fx(c: Ctx) -> list[Finding]:
    """Foreign amounts converted with an exchange rate from a different period than the income."""
    out = []
    year = str(c.idx.data["household"]["tax_year"])
    fx = c.idx.data["engine_reference"]["parameters"].get("fx", {})
    for key, ln in c.lines.items():
        rates = [s for s in ln.get("sources", ()) if s.startswith("ref:fx.")]
        if not rates:
            continue
        _, cur, period = rates[0].split(".", 2)
        if period.startswith(year) or not period.endswith("average"):
            continue
        right = f"{year}_average"
        if right not in fx.get(cur, {}):
            continue
        amounts = [c.idx.values_by_id[s] for s in ln.get("sources", ()) if s in c.idx.values_by_id]
        if not amounts:
            continue
        foreign = _n(amounts[0]["value"])
        used, correct = fx[cur][period], fx[cur][right]
        ours = round(foreign / correct)
        diff = ours - _n(ln["value"])
        out.append(Finding("fx-period", "conversion", key, f"{key} converted at the {period.replace('_', ' ')} rate", "fail", "low",
                           f"{ln['label']}: {cur} {_fmt(foreign)} ÷ {used} ({period}) = {_fmt(_n(ln['value']))}. Income earned in {year} would use the "
                           f"{year} average ({correct}): {_fmt(ours)}.",
                           engine={"label": f"At {period}", "value": _n(ln["value"]), "ref": key},
                           independent={"label": f"At {right}", "value": ours, "method": f"{cur} amount ÷ {correct}"},
                           difference=diff, lines=[key], evidence=[amounts[0]["id"], rates[0], f"ref:fx.{cur}.{right}"],
                           effect=_effect(c, key, diff)))
    return out


def rule_capital_repairs(c: Ctx) -> list[Finding]:
    """Large invoices for replacing a whole system, deducted as rental repairs: repair vs improvement
    is a professional judgment — surfaced, never decided here."""
    out = []
    words = re.compile(r"\b(installed new|replaced? (the )?(whole|entire)|new .{0,20}system|roof replacement)\b", re.I)
    for inv in c.docs_of_type("invoice"):
        text = " ".join(p["printed_content"] for p in inv["pages"])
        total = c.fields(inv["id"]).get("total")
        if not total or not words.search(text):
            continue
        for key, ln in c.lines.items():
            if not re.fullmatch(r"SchE\.14[A-Z]", key):
                continue
            prop = c.lines.get(f"SchE.1{key[-1]}", {}).get("value", "")
            if str(prop).split(",")[0].lower() not in inv["title"].lower():
                continue
            amt = _n(total["value"])
            if amt <= _n(ln["value"]) and (f"{amt:,.2f}" in (ln.get("note") or "") or amt > 0.5 * _n(ln["value"])):
                out.append(Finding("repair-vs-improvement", "judgment", f"{inv['id']}:{key}",
                                   f"{_fmt(amt)} {inv['issuer']} invoice deducted as a repair", "attention", "medium",
                                   f"{key} ({ln['label']}, {_fmt(_n(ln['value']))}) includes {inv['id']}: “{words.search(text).group(0)}…”. "
                                   f"Replacing a whole system is often an improvement to capitalize and depreciate rather than a repair. Record a judgment.",
                                   lines=[key], evidence=[total["id"], inv["id"]], judgment=True))
    return out


RULES: list[Callable[[Ctx], list[Finding]]] = [
    rule_duplicate_pages, rule_card_receipts_in_books, rule_same_account_interest, rule_supplemental_basis,
    rule_state_wages, rule_payments, rule_extraction, rule_broker_summary_detail, rule_fx, rule_questionnaire,
    rule_capital_repairs, rule_basis_rollforward, rule_completeness, rule_duplicate_documents, rule_source_totals,
    rule_cross_document, rule_prior_year, rule_books_to_tax, rule_state_checks, rule_carryovers,
]


def _attach_engine_diagnostics(c: Ctx, findings: list[Finding]) -> None:
    for f in findings:
        refs = set(f.lines) | set(f.evidence)
        f.engine_diagnostics = [dg["code"] for dg in c.v["diagnostics"] if refs & set(dg["refs"])]


_CACHE: dict[tuple[str, str], list[Finding]] = {}


def challenge(idx: PacketIndex, version: str) -> list[Finding]:
    """Run every rule against one return version. Pure and deterministic; cached by packet hash."""
    key = (idx.packet.sha256, version)
    if key not in _CACHE:
        c = Ctx(idx, version)
        findings: list[Finding] = []
        for rule in RULES:
            findings.extend(rule(c))
        _attach_engine_diagnostics(c, findings)
        findings.sort(key=lambda f: (STATUS_ORDER[f.status], SEVERITY_ORDER[f.severity],
                                     -max(abs((f.effect or {}).get("federal") or 0), abs((f.effect or {}).get("california") or 0))))
        _CACHE[key] = findings
    return _CACHE[key]


def summarize(idx: PacketIndex, version: str, findings: list[Finding]) -> dict[str, Any]:
    by_status: dict[str, int] = defaultdict(int)
    for f in findings:
        by_status[f.status] += 1
    fails = [f for f in findings if f.status == "fail" and f.effect and not f.effect.get("potential")]
    taxes = [f for f in fails if f.effect["kind"] == "tax"]
    balances = [f for f in fails if f.effect["kind"] == "balance"]
    families = defaultdict(lambda: defaultdict(int))
    for f in findings:
        families[f.family][f.status] += 1
    v = idx.versions_by_id[version]
    return {
        "version": version, "checks": len(findings), "by_status": dict(by_status),
        "families": {k: {"label": FAMILIES[k], **dict(vv)} for k, vv in families.items()},
        # Two different kinds of change, never added together: a tax estimate from rates, and a payment
        # correction that moves the balance due dollar for dollar without changing tax.
        "estimated_effect": {
            "tax": {
                "federal": round(sum(f.effect["federal"] for f in taxes), 0),
                "california": round(sum(f.effect["california"] for f in taxes), 0),
                "findings": len(taxes),
                "note": "Change in tax: sum of independent estimates at this version's tax_effect_rates. Effects interact "
                        "and cross thresholds — not an engine result.",
            },
            "balance": {
                "federal": round(sum(f.effect["federal"] for f in balances), 0),
                "california": round(sum(f.effect["california"] for f in balances), 0),
                "findings": len(balances),
                "note": "Change in balance due from payment corrections (agency records vs the return). Tax is unchanged.",
            },
        },
        "engine": {"diagnostics": len(v["diagnostics"]), "summary": v["summary"]},
    }
