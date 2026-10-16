"""Return Assurance Twin: the independent assurance record kept around the supplied engine's return.

The engine produces the return; the twin answers "is it proven?". Every figure here is computed from the
packet and the workpaper — nothing is estimated by a model — and every one says how it was computed:

  documents accounted for   used, superseded, or not used with a recorded reason (e.g. received after the version)
  material lines traceable  return lines of 1,000 or more whose inputs reach cited evidence (not just rules)
  evidence coverage         values feeding the return that a person verified
  independent checks        TaxProof checks that passed, or whose finding was dispositioned
  judgment completion       professional-judgment items decided (judgment recorded / accepted / resolved)
  review / partner          areas with an active reviewed / partner sign-off
  client authorization      the client approved exactly the content now on file
  filing readiness          the Iteration 7 gate plus the lifecycle steps still ahead

The **assurance score** is a weighted sum of those ratios (weights below), each component with its reason.
It is not a probability and not a model's confidence.
"""

from __future__ import annotations

from typing import Any

from ..packet.index import PacketIndex
from .area_summary import traceable_lines
from .evidence import document_statuses, get_analysis

MATERIAL = 1000.0
WEIGHTS = {
    "documents": ("Documents accounted for", 10),
    "traceability": ("Material lines traceable to evidence", 15),
    "coverage": ("Evidence verified by a person", 10),
    "checks": ("Independent checks passed or dispositioned", 20),
    "judgments": ("Judgment calls documented", 10),
    "review": ("Areas reviewed", 10),
    "partner": ("Areas partner-approved", 10),
    "client": ("Client authorization of the current return", 5),
    "blockers": ("No filing blockers", 10),
}
PROBLEM_CODES = {"conflict", "needs_review", "not_extracted", "partial", "duplicate"}


def documents(idx: PacketIndex, version: str) -> dict[str, Any]:
    rows, issues = [], []
    counts: dict[str, int] = {}
    for d in idx.data["documents"]:
        st = document_statuses(idx, d["id"], version)
        main = st[0]["code"]
        counts[main] = counts.get(main, 0) + 1
        accounted = main in ("used", "superseded") or (main == "unused" and bool(st[0]["detail"]))
        rows.append({"id": d["id"], "title": d["title"], "status": main, "accounted": accounted, "reason": st[0]["detail"]})
        for s in st[1:]:
            if s["code"] in PROBLEM_CODES:
                issues.append({"id": d["id"], "title": d["title"], "code": s["code"], "label": s["label"], "detail": s["detail"]})
    accounted = sum(1 for r in rows if r["accounted"])
    return {"total": len(rows), "accounted": accounted, "by_status": counts, "issues": issues,
            "unaccounted": [r for r in rows if not r["accounted"]],
            "not_used": [r for r in rows if r["status"] == "unused"]}


def traceability(idx: PacketIndex, version: str) -> dict[str, Any]:
    trace = traceable_lines(idx, version)
    material = [ln for ln in idx.versions_by_id[version]["lines"]
                if isinstance(ln["value"], (int, float)) and not isinstance(ln["value"], bool) and abs(ln["value"]) >= MATERIAL]
    ok = [ln for ln in material if trace.get(ln["key"])]
    return {"material": len(material), "traceable": len(ok), "threshold": MATERIAL,
            "untraceable": [{"key": ln["key"], "label": ln["label"], "value": ln["value"], "rule": ln.get("rule")}
                            for ln in material if not trace.get(ln["key"])][:25]}


def coverage(idx: PacketIndex, version: str, verified_refs: set[str]) -> dict[str, Any]:
    consumed = {s for ln in idx.versions_by_id[version]["lines"] for s in ln.get("sources", ()) if s in idx.values_by_id}
    verified = consumed & verified_refs
    lines = {f"line:{version}:{ln['key']}" for ln in idx.versions_by_id[version]["lines"]}
    flags = get_analysis(idx).value_flags
    flagged = {v for v in consumed if flags.get(v)}
    return {"values": len(consumed), "verified": len(verified), "verified_lines": len(lines & verified_refs),
            "flagged": len(flagged), "flagged_verified": len(flagged & verified_refs)}


def checks(findings: list[Any], items: list[Any]) -> dict[str, Any]:
    by_status: dict[str, int] = {}
    for f in findings:
        by_status[f.status] = by_status.get(f.status, 0) + 1
    handled = {i.links.get("finding_id") for i in items if i.source == "finding" and i.status == "handled"}
    non_pass = [f for f in findings if f.status != "pass"]
    disposed = [f for f in non_pass if f.id in handled]
    return {"total": len(findings), "by_status": by_status, "passed": by_status.get("pass", 0),
            "failed": by_status.get("fail", 0), "attention": by_status.get("attention", 0),
            "dispositioned": len(disposed), "open": [{"id": f.id, "title": f.title, "status": f.status, "severity": f.severity}
                                                     for f in non_pass if f.id not in handled]}


def judgments(items: list[Any], rows: list[Any]) -> dict[str, Any]:
    nature = [i for i in items if i.nature == "judgment" and i.source != "judgment"]
    decided = [i for i in nature if i.status == "handled"]
    live = [j for j in rows if j.status != "superseded"]
    return {"items": len(nature), "decided": len(decided), "recorded": len(live),
            "approved": sum(1 for j in live if j.status == "approved"),
            "awaiting_review": [{"id": j.id, "topic": j.topic, "status": j.status} for j in live if j.status != "approved"],
            "open": [{"key": i.key, "title": i.title} for i in nature if i.status == "open"]}


def signoffs(board: list[dict[str, Any]]) -> dict[str, Any]:
    def count(level: str) -> int:
        return sum(1 for a in board for lv in a["levels"] if lv["level"] == level and lv["status"] == "signed")
    reopened = [{"area": a["title"], "level": lv["label"], "reason": (lv["reopen_reasons"] or [{}])[-1].get("detail")}
                for a in board for lv in a["levels"] if lv["status"] == "reopened"]
    return {"areas": len(board), "prepared": count("prepared"), "reviewed": count("reviewed"), "partner": count("partner"),
            "complete": sum(1 for a in board if a["complete"]), "reopened": reopened}


def score(parts: dict[str, tuple[float, str, str]]) -> dict[str, Any]:
    """parts: key → (ratio 0..1, reason, link). Returns the score and its explained components."""
    comps = []
    for key, (label, weight) in WEIGHTS.items():
        ratio, reason, link = parts[key]
        ratio = max(0.0, min(1.0, ratio))
        comps.append({"key": key, "label": label, "weight": weight, "ratio": round(ratio, 3), "points": round(weight * ratio, 1),
                      "reason": reason, "link": link})
    total = round(sum(c["points"] for c in comps))
    return {"score": total, "level": "strong" if total >= 85 else "developing" if total >= 60 else "weak", "components": comps,
            "method": "Weighted sum of the components below (weights in brackets); each is a ratio computed from the packet "
                      "and the workpaper. Not a probability and not a model's confidence."}


def what_prevents_filing(readiness: dict[str, Any], state: str, state_label: str, client_matches: bool,
                         awaiting_client: bool) -> list[dict[str, Any]]:
    """Every blocker, exactly: failing gate checks, then the lifecycle steps still ahead."""
    out = []
    for ch in readiness["checks"]:
        if ch["ok"]:
            continue
        items = [i["title"] for i in ch.get("items", [])] or [f"{a['title']}: {', '.join(a['missing'])}" for a in ch.get("areas", [])]
        out.append({"kind": "gate", "key": ch["key"], "label": ch["label"], "count": ch["count"], "items": items[:12],
                    "link": "/review?tab=signoffs" if ch["key"] == "signoffs" else "/review?tab=inbox"})
    steps = {
        "preparing": ["Hand the return off for review", "Partner approval", "Client approval and Form 8879", "E-file submission"],
        "ready_for_review": ["Partner approval", "Client approval and Form 8879", "E-file submission"],
        "partner_approved": ["Client approval and Form 8879" + (" (the client approves again in TaxProof)" if awaiting_client else ""),
                             "E-file submission"],
        "client_approved": ["Mark ready to file", "E-file submission"],
        "ready_to_file": ["E-file submission"],
        "submitted": ["Agency acceptance (federal and California)"],
        "rejected": ["Correct the rejection and resubmit"],
        "accepted": ["Record the accepted return as filed"],
    }.get(state, [])
    for s in steps:
        out.append({"kind": "lifecycle", "key": s, "label": s, "count": 1, "items": [f"The return is {state_label}."], "link": "/filing"})
    if state in ("client_approved", "ready_to_file") and not client_matches:
        out.insert(0, {"kind": "lifecycle", "key": "client_reapproval", "label": "The return changed after the client approved it",
                       "count": 1, "items": ["The partner must reopen it and both approvals must be given again."], "link": "/filing"})
    return out
