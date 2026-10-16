"""Tax Time Machine and What-If Lab: read models over the supplied engine runs. Nothing is recomputed.

Time Machine compares any two supplied versions: summary, every line, documents, diagnostics, and why —
the version triggers, the season's events and the documents that arrived between the two runs. It finds
the *drivers*: changed lines whose own inputs did not change, i.e. where new evidence entered.

What-If shows the engine's own alternative runs (`what_if`) and the April extension estimate exactly as
supplied, never inventing a result the packet does not contain.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from ..packet.index import PacketIndex
from .areas import area_for_line

SUMMARY_FIELDS = {
    "federal": ("agi", "taxable_income", "total_tax", "payments", "balance_due", "penalty"),
    "california": ("total_agi", "ca_agi", "total_tax", "payments", "balance_due", "penalty"),
}


def _num(v: Any) -> float | None:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def compare(idx: PacketIndex, a: str, b: str) -> dict[str, Any]:
    va, vb = idx.versions_by_id[a], idx.versions_by_id[b]
    la, lb = idx.return_lines_by_version[a], idx.return_lines_by_version[b]

    summary = {}
    for juris, fields in SUMMARY_FIELDS.items():
        summary[juris] = []
        for f in fields:
            x, y = va["summary"][juris].get(f), vb["summary"][juris].get(f)
            summary[juris].append({"field": f, "from": x, "to": y,
                                   "change": (y - x) if _num(x) is not None and _num(y) is not None else None})

    changes = []
    for key in sorted(set(la) | set(lb)):
        x, y = la.get(key), lb.get(key)
        if x and y and x["value"] == y["value"]:
            continue
        kind = "added" if x is None else "removed" if y is None else "changed"
        line = y or x
        old, new = (x or {}).get("value"), (y or {}).get("value")
        changes.append({"key": key, "change": kind, "label": line["label"], "form": line["form"], "area": area_for_line(line),
                        "old": old, "new": new,
                        "delta": (_num(new) - _num(old)) if _num(new) is not None and _num(old) is not None else None})
    changed_keys = {c["key"] for c in changes}

    # Drivers: changed lines none of whose inputs changed — the change entered here (new or different evidence).
    drivers = []
    for c in changes:
        line = lb.get(c["key"]) or la.get(c["key"])
        if any(i in changed_keys for i in line.get("inputs", ())):
            continue
        src_a = set((la.get(c["key"]) or {}).get("sources", ()))
        src_b = set((lb.get(c["key"]) or {}).get("sources", ()))
        new_sources = sorted(src_b - src_a)
        docs = sorted({idx.values_by_id[s]["document_id"] for s in new_sources if s in idx.values_by_id})
        drivers.append({**c, "new_sources": new_sources, "new_source_documents": docs, "lost_sources": sorted(src_a - src_b)})

    # Large detail summarised first: lots grouped by Form 8949 box, everything else by area.
    by_area: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for c in changes:
        by_area[c["area"]][c["change"]] += 1

    used_a, used_b = set(va["documents_used"]), set(vb["documents_used"])
    sup_a, sup_b = set(va["documents_superseded"]), set(vb["documents_superseded"])

    def doc(d: str) -> dict[str, Any]:
        x = idx.documents_by_id[d]
        return {"id": d, "title": x["title"], "received_at": x["received_at"]}

    diag_a = {d["code"]: d for d in va["diagnostics"]}
    diag_b = {d["code"]: d for d in vb["diagnostics"]}
    lo, hi = sorted([va["computed_at"], vb["computed_at"]])
    later = vb if vb["computed_at"] >= va["computed_at"] else va
    between = [v for v in idx.data["return_versions"] if lo < v["computed_at"] <= hi]

    # Cross-check with the engine's own change list when the two versions are consecutive.
    consistency = None
    order = idx.version_ids
    if order.index(b) == order.index(a) + 1:
        packet = {(c["key"], c["change"]) for c in vb["changes_from_previous"]}
        ours = {(c["key"], c["change"]) for c in changes}
        consistency = {"agrees": packet == ours, "packet_changes": len(packet), "computed_changes": len(ours),
                       "only_in_packet": sorted(k for k, _ in packet - ours)[:20], "only_computed": sorted(k for k, _ in ours - packet)[:20]}

    fed = next(r for r in summary["federal"] if r["field"] == "total_tax")
    ca = next(r for r in summary["california"] if r["field"] == "total_tax")
    return {
        "from": {"version": a, "computed_at": va["computed_at"], "trigger": va["trigger"]},
        "to": {"version": b, "computed_at": vb["computed_at"], "trigger": vb["trigger"]},
        "summary": summary,
        "tax_change": {"federal": fed["change"], "california": ca["change"]},
        "lines": {"total": len(changes), "by_area": {k: dict(v) for k, v in by_area.items()},
                  "changes": changes},
        "drivers": drivers,
        "documents": {
            "now_used": [doc(d) for d in sorted(used_b - used_a)], "no_longer_used": [doc(d) for d in sorted(used_a - used_b)],
            "newly_superseded": [doc(d) for d in sorted(sup_b - sup_a)], "no_longer_superseded": [doc(d) for d in sorted(sup_a - sup_b)],
        },
        "diagnostics": {
            "added": [dict(diag_b[c]) for c in sorted(set(diag_b) - set(diag_a))],
            "removed": [dict(diag_a[c]) for c in sorted(set(diag_a) - set(diag_b))],
            "changed": [{"code": c, "from": diag_a[c]["message"], "to": diag_b[c]["message"]}
                        for c in sorted(set(diag_a) & set(diag_b)) if diag_a[c]["message"] != diag_b[c]["message"]],
        },
        "why": {
            "triggers": [{"version": v["version"], "computed_at": v["computed_at"], "trigger": v["trigger"]} for v in between] or
                        [{"version": later["version"], "computed_at": later["computed_at"], "trigger": later["trigger"]}],
            "timeline": [dict(t) for t in idx.data["timeline"] if lo < t["at"] <= hi],
            "documents_received": [doc(d["id"]) for d in idx.data["documents"] if lo < d["received_at"] <= hi],
        },
        "consistency_with_engine": consistency,
    }


def what_if(idx: PacketIndex, findings: list[Any] | None = None) -> dict[str, Any]:
    w = idx.data.get("what_if", {})
    alts = []
    for alt in w.get("alternatives", ()):
        base = alt["base_version"]
        lines = idx.return_lines_by_version.get(base, {})
        changed = [{**dict(c), "label": (lines.get(c["key"]) or {}).get("label"),
                    "area": area_for_line(lines[c["key"]]) if c["key"] in lines else None} for c in alt.get("changed_lines", ())]
        keys = {c["key"] for c in changed}
        # Open findings about a line this alternative changes (on the finding's primary line, so summary
        # lines both happen to touch do not create false links).
        related = [{"id": f.id, "title": f.title, "status": f.status} for f in (findings or [])
                   if f.status != "pass" and f.lines and f.lines[0] in keys]
        alts.append({
            "id": alt["id"], "description": alt["description"], "base_version": base, "choices": dict(alt["choices"]),
            "federal": dict(alt["federal"]), "california": dict(alt["california"]),
            "changed_lines": changed, "related_findings": related, "source": "engine",
        })
    return {"alternatives": alts, "extension": dict(w["extension"]) if w.get("extension") else None,
            "note": "Each alternative is an engine run supplied in the packet. TaxProof displays it; it does not compute alternatives."}
