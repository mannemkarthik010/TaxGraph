"""Universal reference resolver.

The packet cites things with a small grammar (see readme.reference_formats). TaxProof adopts the same
grammar as its node-reference format, adding `line:<version>:<key>` for return lines and
`rule:<R-ID>` for engine rules. Every workpaper record (note, verification, adjustment, sign-off …)
points at packet content through one of these strings, so the evidence graph can join across layers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .index import PacketIndex

_EV = re.compile(r"^ev-\d{4}$")
_DOC = re.compile(r"^D\d{2}$")
_DOC_PAGE = re.compile(r"^doc:(D\d{2})#page(\d+)$")
_VERSION = re.compile(r"^v\d+$")
_LINE = re.compile(r"^line:(v\d+):(.+)$")


@dataclass
class ResolvedRef:
    ref: str
    kind: str
    exists: bool
    label: str | None = None
    value: Any = None
    document_id: str | None = None
    page: int | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "kind": self.kind,
            "exists": self.exists,
            "label": self.label,
            "value": self.value,
            "document_id": self.document_id,
            "page": self.page,
            "detail": self.detail,
        }


def json_pointer(root: Any, pointer: str) -> Any:
    """RFC 6901 lookup. Raises KeyError when the path does not exist."""
    if pointer in ("", "/"):
        return root
    if not pointer.startswith("/"):
        raise KeyError(pointer)
    node = root
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(node, dict):
            node = node[token]
        elif isinstance(node, (list, tuple)):
            node = node[int(token)]
        else:
            raise KeyError(pointer)
    return node


def resolve(idx: PacketIndex, ref: str, version: str | None = None) -> ResolvedRef:
    """Resolve any packet reference. Bare line keys (e.g. `SchC.I`) resolve against `version`."""
    d = idx.data
    version = version or idx.current_version

    if _EV.match(ref):
        ev = idx.values_by_id.get(ref)
        if not ev:
            return ResolvedRef(ref, "extracted_value", False)
        return ResolvedRef(
            ref, "extracted_value", True, label=ev["label"], value=ev["value"],
            document_id=ev["document_id"], page=ev["page"],
            detail={"field": ev["field"], "confidence": ev["confidence"], "value_type": ev["value_type"]},
        )

    if _DOC.match(ref):
        doc = idx.documents_by_id.get(ref)
        return ResolvedRef(ref, "document", bool(doc), label=doc["title"] if doc else None, document_id=ref if doc else None)

    m = _DOC_PAGE.match(ref)
    if m:
        doc = idx.documents_by_id.get(m.group(1))
        page = int(m.group(2))
        ok = bool(doc) and 1 <= page <= doc["page_count"]
        return ResolvedRef(ref, "page", ok, label=f"{doc['title']} — page {page}" if ok else None,
                           document_id=m.group(1) if ok else None, page=page if ok else None)

    for prefix, table, kind in (
        ("qa-", idx.questions_by_id, "client_answer"),
        ("msg-", idx.messages_by_id, "client_message"),
        ("call-", idx.call_notes_by_id, "call_note"),
    ):
        if ref.startswith(prefix):
            rec = table.get(ref)
            if not rec:
                return ResolvedRef(ref, kind, False)
            label = rec.get("question") or rec.get("text") or "; ".join(rec.get("notes", ()))[:120]
            value = rec.get("answer") if kind == "client_answer" else None
            return ResolvedRef(ref, kind, True, label=label, value=value)

    if ref.startswith("timeline:") or ref.startswith("tl-"):
        tid = ref.split(":", 1)[1] if ref.startswith("timeline:") else ref
        ev = idx.timeline_by_id.get(tid)
        return ResolvedRef(ref, "timeline_event", bool(ev), label=ev["event"] if ev else None,
                           detail={"at": ev["at"]} if ev else {})

    if _VERSION.match(ref):
        v = idx.versions_by_id.get(ref)
        return ResolvedRef(ref, "return_version", bool(v), label=v["trigger"] if v else None)

    m = _LINE.match(ref)
    if m:
        return _line(idx, ref, m.group(1), m.group(2))

    for prefix, root_key, kind in (("py:", "prior_years", "prior_year_value"), ("agency:", "tax_agency_records", "agency_record")):
        if ref.startswith(prefix):
            try:
                node = json_pointer(d[root_key], ref[len(prefix):])
            except (KeyError, IndexError, ValueError):
                return ResolvedRef(ref, kind, False)
            scalar = node if not isinstance(node, (dict, tuple, list)) else None
            return ResolvedRef(ref, kind, True, label=ref[len(prefix):], value=scalar)

    if ref.startswith("asset:"):
        aid = ref.split(":", 1)[1]
        rec = idx.assets_by_id.get(aid, {})
        asset = rec.get(version) or rec.get("prior")
        return ResolvedRef(ref, "asset", bool(asset), label=asset["description"] if asset else None)

    if ref.startswith("household:"):
        path = ref.split(":", 1)[1]
        pid = path.split(".", 1)[0]
        person = idx.people_by_id.get(pid)
        if person:
            return ResolvedRef(ref, "household_member", True, label=person["name"], detail={"role": person["role"]})
        if pid == "bank":
            return ResolvedRef(ref, "household_bank", True, label="Refund / payment bank account")
        # Organizer sections other than people: household:residency, household:addresses, household:filing_status
        section = d["household"].get(pid) if pid not in ("people", "bank_account_for_refund_or_payment") else None
        if section is not None:
            label = {"residency": "Residency periods (organizer)", "addresses": "Addresses (organizer)"}.get(pid, pid.replace("_", " "))
            value = section if not isinstance(section, (tuple, dict)) else None
            return ResolvedRef(ref, "household_record", True, label=label, value=value)
        return ResolvedRef(ref, "household_member", False)

    if ref.startswith("ref:param."):
        name = ref[len("ref:param."):]
        params = d["engine_reference"]["parameters"]
        return ResolvedRef(ref, "engine_parameter", name in params, label=name, value=params.get(name) if not isinstance(params.get(name), (tuple, dict)) else None)

    if ref.startswith("ref:fx."):
        _, cur, rate = ref.split(".", 2)
        fx = d["engine_reference"]["parameters"].get("fx", {}).get(cur, {})
        return ResolvedRef(ref, "fx_rate", rate in fx, label=f"{cur} {rate}", value=fx.get(rate))

    if ref.startswith("rule:") or ref.startswith("R-"):
        rid = ref.split(":", 1)[1] if ref.startswith("rule:") else ref
        desc = d["engine_reference"]["rules"].get(rid)
        return ResolvedRef(ref, "engine_rule", desc is not None, label=desc)

    # Bare return-line key, as used in line.inputs and diagnostics refs.
    if ref in idx.return_lines_by_version.get(version, {}):
        return _line(idx, ref, version, ref)

    return ResolvedRef(ref, "unknown", False)


def _line(idx: PacketIndex, ref: str, version: str, key: str) -> ResolvedRef:
    line = idx.line(version, key)
    if not line:
        return ResolvedRef(ref, "return_line", False)
    return ResolvedRef(ref, "return_line", True, label=line["label"], value=line["value"],
                       detail={"version": version, "key": key, "form": line["form"], "jurisdiction": line["jurisdiction"]})


def line_ref(version: str, key: str) -> str:
    return f"line:{version}:{key}"
