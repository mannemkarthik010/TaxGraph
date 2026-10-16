"""Deterministic evidence analysis over the frozen packet.

This module does not trust extraction confidence. It compares each extracted value with what the page
actually prints, checks identity numbers against the organizer, finds duplicate documents and pages,
and derives a status for every document. Everything is computed once per packet and cached.
Later iterations (Challenge Return) build findings and tax impact on top of these primitives.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from difflib import SequenceMatcher
from typing import Any

from ..packet.index import PacketIndex

LOW_CONFIDENCE = 0.8
DUPLICATE_VALUE_OVERLAP = 0.9   # share of (field, value) pairs two documents/pages must have in common
DUPLICATE_TEXT_RATIO = 0.9      # printed-text similarity for page duplicates

_NUM = re.compile(r"-?\d[\d,]*(?:\.\d+)?")
_NUMERIC_TYPES = {"money", "integer", "quantity"}
_TEXT_TYPES = {"text", "code", "ssn", "ein", "account_number"}


@dataclass(frozen=True)
class Flag:
    code: str
    severity: str  # conflict | review
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "severity": self.severity, "message": self.message}


@dataclass
class EvidenceAnalysis:
    value_flags: dict[str, list[Flag]] = field(default_factory=dict)
    value_spans: dict[str, tuple[int, int] | None] = field(default_factory=dict)
    duplicate_documents: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    corrected_pairs: dict[str, dict[str, str]] = field(default_factory=dict)
    duplicate_pages: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    consumed_values: dict[str, list[tuple[str, str]]] = field(default_factory=dict)


# ---- helpers ---------------------------------------------------------------------------------------

def page_text(idx: PacketIndex, doc_id: str, page: int) -> str | None:
    doc = idx.documents_by_id.get(doc_id)
    if not doc:
        return None
    for p in doc["pages"]:
        if p["page"] == page:
            return p["printed_content"]
    return None


def printed_numbers(text: str) -> set[float]:
    out: set[float] = set()
    for m in _NUM.findall(text):
        try:
            out.add(round(float(m.replace(",", "")), 2))
        except ValueError:
            pass
    return out


def date_variants(iso: str) -> list[str]:
    y, m, d = iso.split("-")
    dt = date(int(y), int(m), int(d))
    day = str(dt.day)
    return [iso, f"{m}/{d}/{y}", f"{dt.month}/{dt.day}/{y}", f"{dt:%B} {day}, {y}", f"{dt:%b} {day}, {y}", f"{dt:%B} {day}"]


def number_variants(v: float) -> list[str]:
    a = abs(v)
    variants = [f"{a:,.2f}", f"{a:.2f}"]
    if float(a).is_integer():
        variants += [f"{int(a):,}", str(int(a))]
    return variants


def _fmt(v: float) -> str:
    return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.2f}"


# ---- value checks ----------------------------------------------------------------------------------

def check_value(ev: Any, text: str | None, household_ssns: set[str]) -> list[Flag]:
    flags: list[Flag] = []
    v, vt, read = ev["value"], ev["value_type"], ev.get("text_as_read") or ""
    if text is None:
        return [Flag("PAGE_MISSING", "conflict", f"Value cites page {ev['page']}, which the document does not have.")]

    if v is None:
        flags.append(Flag("NO_VALUE", "review", "The pipeline recorded no value for this field."))
    elif vt in _NUMERIC_TYPES and isinstance(v, (int, float)) and not isinstance(v, bool):
        nums = printed_numbers(text)
        if round(float(v), 2) not in nums and round(-float(v), 2) not in nums:
            if read == "":
                flags.append(Flag("VALUE_NOT_PRINTED", "review",
                                  f"Recorded {_fmt(v)} but nothing was read from the page for this field."))
            elif float(v) == 0:
                flags.append(Flag("ZERO_NOT_PRINTED", "review",
                                  f"Read as “{read}”, but the page prints no such amount."))
            else:
                flags.append(Flag("PRINTED_MISMATCH", "conflict",
                                  f"Read as “{read}”, but the page does not print {_fmt(v)}."))
    elif vt == "date" and isinstance(v, str):
        if not any(s in text for s in date_variants(v) + ([read] if read else [])):
            flags.append(Flag("PRINTED_MISMATCH", "conflict", f"Date {v} does not appear on the page."))
    elif vt in _TEXT_TYPES and isinstance(v, str):
        low = text.lower()
        if v.lower() not in low and (not read or read.lower() not in low):
            flags.append(Flag("PRINTED_MISMATCH", "conflict", f"“{v}” does not appear on the page as printed."))

    if vt == "ssn" and isinstance(v, str) and household_ssns and v not in household_ssns:
        flags.append(Flag("IDENTITY_MISMATCH", "conflict",
                          "SSN does not match any SSN the client entered in the organizer."))

    if ev["confidence"] < LOW_CONFIDENCE:
        flags.append(Flag("LOW_CONFIDENCE", "review", f"Extraction confidence {ev['confidence']:.2f}."))
    return flags


def locate(text: str, ev: Any, display_value: Any = None) -> tuple[int, int] | None:
    """Find where a value sits in the printed text. When the value occurs more than once, pick the
    occurrence whose preceding words best match the field label (e.g. 'Box 1', 'proceeds')."""
    v = ev["value"] if display_value is None else display_value
    read = ev.get("text_as_read") or ""
    candidates: list[str] = []
    if display_value is not None and isinstance(display_value, str):
        candidates.append(display_value)
    if read:
        candidates.append(read)
    if ev["value_type"] == "boolean" or isinstance(v, bool):
        # A checkbox reads as 'X'; find the printed label of the box instead.
        candidates = [ev["label"], re.sub(r"^Box \w+\s*", "", ev["label"])]
    elif ev["value_type"] == "percent" and isinstance(v, (int, float)):
        candidates += [f"{v * 100:g}%", f"{v * 100:.1f}%", f"{v:g}%"]
    elif isinstance(v, (int, float)):
        candidates += number_variants(float(v))
    elif isinstance(v, str):
        candidates.append(v)
        if ev["value_type"] == "date" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            candidates += date_variants(v)
    # Letters and digits split apart so 'box3' and 'Box 3' share the tokens {'box', '3'}.
    label_words = set(re.findall(r"[a-z]+|\d+", f"{ev['label']} {ev['field']}".lower()))

    best: tuple[float, int, int] | None = None
    seen: set[str] = set()
    for cand in candidates:
        if not cand or (len(cand) < 2 and not cand.isdigit()) or cand in seen:
            continue
        seen.add(cand)
        pattern = re.escape(cand)
        # never match inside a longer number or word (e.g. '500.00' inside '1,500.00')
        if cand[0].isalnum():
            pattern = r"(?<![\w,.])" + pattern
        if cand[-1].isalnum():
            pattern += r"(?!\w)"
        for m in re.finditer(pattern, text, flags=re.IGNORECASE):
            near = set(re.findall(r"[a-z]+|\d+", text[max(0, m.start() - 12): m.start()].lower()))
            wider = set(re.findall(r"[a-z]+|\d+", text[max(0, m.start() - 60): m.start()].lower()))
            score = 3 * len(label_words & near) + len(label_words & wider) + len(cand) / 100.0
            if best is None or score > best[0]:
                best = (score, m.start(), m.end())
    return (best[1], best[2]) if best else None


# ---- duplicates ------------------------------------------------------------------------------------

def _pairs(values: list[Any]) -> set[tuple[str, str]]:
    return {(e["field"], repr(e["value"])) for e in values if e["value"] not in (None, "", 0)}


def overlap(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def _normalize(text: str) -> str:
    text = re.sub(r"\([^)]*\)", " ", text)  # drop parentheticals such as scanner notes
    return re.sub(r"\s+", " ", text).strip().lower()


def find_duplicate_pages(idx: PacketIndex, doc_id: str) -> list[dict[str, Any]]:
    doc = idx.documents_by_id[doc_id]
    by_page: dict[int, list[Any]] = defaultdict(list)
    for ev in idx.values_by_document.get(doc_id, ()):
        by_page[ev["page"]].append(ev)
    pages = sorted(doc["pages"], key=lambda p: p["page"])
    out = []
    for i, a in enumerate(pages):
        for b in pages[i + 1:]:
            ov = overlap(_pairs(by_page[a["page"]]), _pairs(by_page[b["page"]]))
            # Template pages (e.g. brokerage lot listings) look alike as text, so a page duplicate must
            # also print the same numbers. Text similarity is only computed for those candidates.
            num_ov = overlap(printed_numbers(a["printed_content"]), printed_numbers(b["printed_content"]))
            if ov < DUPLICATE_VALUE_OVERLAP and num_ov < DUPLICATE_VALUE_OVERLAP:
                continue
            ta, tb = _normalize(a["printed_content"]), _normalize(b["printed_content"])
            ratio = SequenceMatcher(None, ta, tb, autojunk=False).ratio()
            if ratio >= DUPLICATE_TEXT_RATIO and max(ov, num_ov) >= DUPLICATE_VALUE_OVERLAP:
                out.append({"pages": [a["page"], b["page"]], "value_overlap": round(ov, 3),
                            "number_overlap": round(num_ov, 3), "text_similarity": round(ratio, 3)})
    return out


def _family(doc: Any) -> tuple:
    return (doc["document_type"], doc["belongs_to"], doc["tax_year"])


# ---- build -----------------------------------------------------------------------------------------

def analyze(idx: PacketIndex) -> EvidenceAnalysis:
    a = EvidenceAnalysis()
    ssns = {p["ssn"] for p in idx.data["household"]["people"] if p.get("ssn")}

    for ev in idx.data["extracted_values"]:
        text = page_text(idx, ev["document_id"], ev["page"])
        flags = check_value(ev, text, ssns)
        if flags:
            a.value_flags[ev["id"]] = flags
        a.value_spans[ev["id"]] = locate(text, ev) if text else None

    for src, consumers in idx.lines_by_source.items():
        if src in idx.values_by_id:
            a.consumed_values[src] = list(consumers)

    # Documents of the same kind whose readings substantially coincide: either the issuer's corrected
    # form (marked_corrected) or a second copy of the same document.
    families: dict[tuple, list[Any]] = defaultdict(list)
    for doc in idx.data["documents"]:
        families[_family(doc)].append(doc)
    for docs in families.values():
        for i, x in enumerate(docs):
            for y in docs[i + 1:]:
                ov = overlap(_pairs(idx.values_by_document.get(x["id"], [])), _pairs(idx.values_by_document.get(y["id"], [])))
                if ov < DUPLICATE_VALUE_OVERLAP:
                    continue
                if x.get("marked_corrected") or y.get("marked_corrected"):
                    corrected, original = (x, y) if x.get("marked_corrected") else (y, x)
                    a.corrected_pairs[original["id"]] = {"corrected_by": corrected["id"]}
                    a.corrected_pairs[corrected["id"]] = {"corrects": original["id"]}
                else:
                    first, second = sorted((x, y), key=lambda d: (d["received_at"], d["id"]))
                    rel = {"overlap": round(ov, 3)}
                    a.duplicate_documents.setdefault(second["id"], []).append({"duplicate_of": first["id"], **rel})
                    a.duplicate_documents.setdefault(first["id"], []).append({"duplicated_by": second["id"], **rel})

    for doc in idx.data["documents"]:
        if doc["page_count"] > 1:
            dups = find_duplicate_pages(idx, doc["id"])
            if dups:
                a.duplicate_pages[doc["id"]] = dups
    return a


_CACHE: dict[str, EvidenceAnalysis] = {}


def get_analysis(idx: PacketIndex) -> EvidenceAnalysis:
    """Analysis is a pure function of the (immutable) packet, so it is cached by packet hash."""
    if idx.packet.sha256 not in _CACHE:
        _CACHE[idx.packet.sha256] = analyze(idx)
    return _CACHE[idx.packet.sha256]


# ---- document status -------------------------------------------------------------------------------

STATUS_LABELS = {
    "used": "Used", "unused": "Unused", "superseded": "Superseded", "corrected": "Corrected",
    "partial": "Partial extraction", "not_extracted": "Not extracted", "conflict": "Conflict",
    "duplicate": "Duplicate", "needs_review": "Needs review",
}


def document_statuses(idx: PacketIndex, doc_id: str, version: str | None = None) -> list[dict[str, str]]:
    version = version or idx.current_version
    v = idx.versions_by_id[version]
    a = get_analysis(idx)
    doc = idx.documents_by_id[doc_id]
    out: list[dict[str, str]] = []

    def add(code: str, detail: str) -> None:
        out.append({"code": code, "label": STATUS_LABELS[code], "detail": detail})

    if doc_id in v["documents_superseded"]:
        by = a.corrected_pairs.get(doc_id, {}).get("corrected_by")
        add("superseded", f"Superseded in {version}" + (f" by {by}" if by else "") + ".")
    elif doc_id in v["documents_used"]:
        vals = idx.values_by_document.get(doc_id, ())
        consumed = sum(1 for ev in vals if ev["id"] in a.consumed_values)
        prior_sources = {pv["source"] for pv in idx.prior_year_values.values()}
        prior = sum(1 for ev in vals if ev["id"] in prior_sources)
        detail = f"Listed in {version}'s documents_used; {consumed} value(s) feed 2025 return lines"
        add("used", detail + (f", {prior} support 2024 lines." if prior else "."))
    else:
        add("unused", why_not_used(idx, doc_id, version))

    if doc.get("marked_corrected"):
        orig = a.corrected_pairs.get(doc_id, {}).get("corrects")
        add("corrected", "Issuer marked this form CORRECTED" + (f"; it replaces {orig}." if orig else "."))
    status = doc["extraction"]["status"]
    if status == "partial":
        add("partial", doc["extraction"].get("reason") or "Some pages were not read.")
    elif status == "not_extracted":
        add("not_extracted", doc["extraction"].get("reason") or "Not read by the pipeline.")

    for rel in a.duplicate_documents.get(doc_id, ()):
        if "duplicate_of" in rel:
            add("duplicate", f"Readings match {rel['duplicate_of']} ({rel['overlap']:.0%} of values): likely a second copy.")
    for dp in a.duplicate_pages.get(doc_id, ()):
        p1, p2 = dp["pages"]
        add("duplicate", f"Pages {p1} and {p2} appear to be the same sheet "
                         f"(values {dp['value_overlap']:.0%}, text {dp['text_similarity']:.0%} alike).")

    flags = [(ev["id"], f) for ev in idx.values_by_document.get(doc_id, ()) for f in a.value_flags.get(ev["id"], ())]
    conflicts = [x for x in flags if x[1].severity == "conflict"]
    reviews = [x for x in flags if x[1].severity == "review"]
    if conflicts:
        add("conflict", f"{len(conflicts)} extracted value(s) disagree with the printed page or the organizer.")
    if reviews:
        add("needs_review", f"{len(reviews)} extracted value(s) need a human look (blank, unprinted or low confidence).")
    return out


def why_not_used(idx: PacketIndex, doc_id: str, version: str) -> str:
    doc = idx.documents_by_id[doc_id]
    v = idx.versions_by_id[version]
    if doc["received_at"] > v["computed_at"]:
        return f"Received {doc['received_at'][:10]}, after {version} was computed ({v['computed_at'][:10]})."
    if doc["extraction"]["status"] == "not_extracted":
        return f"Not extracted: {doc['extraction'].get('reason') or 'no reason given'}"
    return f"Not in the engine's documents_used for {version}; no reason recorded by the engine."


def where_used(idx: PacketIndex, ref: str) -> dict[str, Any]:
    """Reverse trace for an extracted value: return lines (every version), engine diagnostics, prior-year lines."""
    lines = [
        {"version": vid, "key": key, "label": idx.line(vid, key)["label"], "value": idx.line(vid, key)["value"]}
        for vid, key in idx.lines_by_source.get(ref, ())
    ]
    diagnostics = [
        {"version": v["version"], "code": dg["code"], "severity": dg["severity"], "message": dg["message"]}
        for v in idx.data["return_versions"] for dg in v["diagnostics"] if ref in dg["refs"]
    ]
    prior = [
        {"key": k, "label": pv["label"], "value": pv["value"]}
        for k, pv in idx.prior_year_values.items() if pv["source"] == ref
    ]
    return {"lines": lines, "diagnostics": diagnostics, "prior_year_lines": prior}
