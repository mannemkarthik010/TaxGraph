"""Filing lifecycle, replay of the scripted post-v3 timeline, the filed snapshot and the amendment layer.

States:
  preparing → ready_for_review → partner_approved → client_approved → ready_to_file → submitted
            → rejected (→ resubmitted) / accepted → filed → frozen
Firm steps are explicit actions (`ACTIONS`); client and agency steps come from the packet's timeline,
replayed strictly in order (`REPLAY`), each at its own scripted time. The replay clock is the time of the
last filing event (initially when v3 was computed: "now" per the packet README).

The client approves a *fingerprint* of the return's content (version, applied adjustments, approved
judgments). If the content changes after that, nothing can be filed until the client approves again.

What is filed is frozen into a snapshot built from exactly the package the agencies accepted, hashed,
and never updated. Later changes are amendments: each filed amendment is a new snapshot; the original
stays byte-for-byte the same.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Adjustment, ClientQuestion, Engagement, FiledSnapshot, FilingEvent, Judgment, Verification
from ..packet.index import PacketIndex
from ..security.masking import mask_payload, mask_text
from .adjustments import workpaper_summary
from .audit import _storable

STATES = ("preparing", "ready_for_review", "partner_approved", "client_approved", "ready_to_file", "submitted",
          "rejected", "accepted", "filed", "frozen")
STATE_LABEL = {"preparing": "Preparing", "ready_for_review": "Ready for Review", "partner_approved": "Partner Approved",
               "client_approved": "Client Approved", "ready_to_file": "Ready to File", "submitted": "Submitted",
               "rejected": "Rejected", "accepted": "Accepted", "filed": "Filed", "frozen": "Frozen"}
# The return's content may not change while it is with the agencies or after it is filed.
RETURN_LOCKED = ("submitted", "accepted", "filed", "frozen")
POST_FILING = ("filed", "frozen")

# action: (allowed from, to, roles, label)
ACTIONS: dict[str, tuple[tuple[str, ...], str, tuple[str, ...], str]] = {
    "hand_off": (("preparing",), "ready_for_review", ("preparer", "reviewer", "partner"), "Hand off for review"),
    "partner_approve": (("ready_for_review",), "partner_approved", ("partner",), "Partner approval"),
    "ready_to_file": (("client_approved",), "ready_to_file", ("reviewer", "partner"), "Mark ready to file"),
    "submit": (("ready_to_file",), "submitted", ("reviewer", "partner"), "Submit e-file"),
    "resubmit": (("rejected",), "submitted", ("reviewer", "partner"), "Correct and resubmit"),
    "record_filed": (("accepted",), "filed", ("reviewer", "partner"), "Record as filed"),
    "freeze": (("filed",), "frozen", ("partner",), "Freeze the workpaper"),
    "reopen": (("ready_for_review", "partner_approved", "client_approved", "ready_to_file", "rejected"), "preparing",
               ("partner",), "Reopen for changes"),
}

ANY = tuple(STATES)
# timeline event: (allowed states, label, what it needs first)
REPLAY: dict[str, tuple[tuple[str, ...], str, str]] = {
    "client_message": (ANY, "Client message", ""),
    "document_received": (ANY, "Document received", ""),
    "client_approved_and_signed_8879": (("partner_approved",), "Client approves and signs Forms 8879 / FTB 8879",
                                         "the partner's approval of the return"),
    "efile_rejected": (("submitted",), "E-file rejected", "an e-file submission"),
    "efile_accepted_federal": (("submitted",), "Federal return accepted", "an e-file submission"),
    "efile_accepted_california": (("submitted",), "California return accepted", "an e-file submission"),
    "federal_balance_paid": (POST_FILING, "Federal balance paid", "a filed return"),
    "california_refund_issued": (POST_FILING, "California refund issued", "a filed return"),
    "quality_review_selected_return": (POST_FILING, "Quality review selects the return", "a filed return"),
    "next_year_engagement_started": (POST_FILING, "Next year's engagement starts", "a filed return"),
    "notice_received": (POST_FILING, "Agency notice received", "a filed return"),
}


class FilingError(ValueError):
    def __init__(self, message: str, status: int = 409, detail: Any = None):
        super().__init__(message)
        self.status = status
        self.detail = detail


def _now() -> datetime:
    return datetime.now(timezone.utc)


def canonical_hash(content: Any) -> str:
    """Hash of what the database will give back (JSON round trip, no negative zero)."""
    stored = _storable(json.loads(json.dumps(content, default=str)))
    return hashlib.sha256(json.dumps(stored, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def storable(content: Any) -> Any:
    return _storable(json.loads(json.dumps(content, default=str)))


# ---- state, clock, script ------------------------------------------------------------------------------

def events(db: Session, engagement_id: str) -> list[FilingEvent]:
    return list(db.scalars(select(FilingEvent).where(FilingEvent.engagement_id == engagement_id).order_by(FilingEvent.id)).all())


def state(db: Session, engagement_id: str) -> str:
    eng = db.get(Engagement, engagement_id)
    return eng.status if eng and eng.status in STATES else "preparing"


def start_of_replay(idx: PacketIndex) -> str:
    return idx.versions_by_id[idx.current_version]["computed_at"]


def clock(db: Session, idx: PacketIndex, engagement_id: str) -> str:
    evs = events(db, engagement_id)
    return max([start_of_replay(idx)] + [e.at for e in evs])


def script(idx: PacketIndex) -> list[Any]:
    """The timeline after "now" (v3), in order: what can be replayed."""
    start = start_of_replay(idx)
    return [t for t in idx.data["timeline"] if t["at"] > start]


def next_scripted(db: Session, idx: PacketIndex, engagement_id: str) -> Any | None:
    done = {e.timeline_id for e in events(db, engagement_id) if e.timeline_id}
    return next((t for t in script(idx) if t["id"] not in done), None)


def jurisdictions(db: Session, engagement_id: str) -> dict[str, dict[str, Any]]:
    """Latest e-file status per jurisdiction, from replayed agency events."""
    out: dict[str, dict[str, Any]] = {}
    for e in events(db, engagement_id):
        for s in e.detail.get("submissions", []):
            out[s["jurisdiction"]] = s
    return out


def record(db: Session, engagement_id: str, *, at: str, kind: str, action: str, from_state: str, to_state: str,
           actor_id: str | None, actor_role: str | None, note: str | None = None, timeline_id: str | None = None,
           detail: dict[str, Any] | None = None) -> FilingEvent:
    ev = FilingEvent(engagement_id=engagement_id, at=at, kind=kind, action=action, timeline_id=timeline_id,
                     from_state=from_state, to_state=to_state, actor_id=actor_id, actor_role=actor_role, note=note,
                     detail=storable(detail or {}))
    db.add(ev)
    db.get(Engagement, engagement_id).status = to_state
    db.flush()
    return ev


def check_action(current: str, action: str, role: str) -> tuple[str, str]:
    if action not in ACTIONS:
        raise FilingError(f"Unknown filing action '{action}'.", 404)
    allowed, to, roles, label = ACTIONS[action]
    if role not in roles:
        raise FilingError(f"{label} is done by a {' or '.join(roles)}.", 403)
    if current not in allowed:
        raise FilingError(f"{label} is not possible while the return is {STATE_LABEL[current]} "
                          f"(needs {' or '.join(STATE_LABEL[s] for s in allowed)}).")
    return to, label


# ---- what is being approved and filed ------------------------------------------------------------------

def fingerprint(db: Session, idx: PacketIndex, engagement_id: str) -> dict[str, Any]:
    """The return's content: the version and every workpaper change to it. What the client approves."""
    v = idx.current_version
    adjustments = sorted((a.target_line, a.adjusted_value, a.id) for a in db.scalars(select(Adjustment).where(
        Adjustment.engagement_id == engagement_id, Adjustment.version == v, Adjustment.status == "applied")).all())
    judgments = sorted((j.id, j.decision_option) for j in db.scalars(select(Judgment).where(
        Judgment.engagement_id == engagement_id, Judgment.status != "superseded")).all())
    content = {"version": v, "packet_sha256": idx.packet.sha256, "adjustments": adjustments, "judgments": judgments}
    return {"sha256": canonical_hash(content), "content": storable(content)}


def describe_change(before: dict[str, Any], after: dict[str, Any]) -> str:
    b, a = before.get("content", {}), after.get("content", {})
    parts = []
    if b.get("adjustments") != a.get("adjustments"):
        parts.append(f"applied adjustments {len(b.get('adjustments', []))} → {len(a.get('adjustments', []))}"
                     f" ({', '.join(sorted({x[0] for x in a.get('adjustments', [])} ^ {x[0] for x in b.get('adjustments', [])})) or 'values changed'})")
    if b.get("judgments") != a.get("judgments"):
        parts.append("judgments changed")
    if b.get("version") != a.get("version"):
        parts.append(f"return version {b.get('version')} → {a.get('version')}")
    return "; ".join(parts) or "content changed"


# ---- filed figures that agree with each other ----------------------------------------------------------

# The return lines that carry the summary figures (the packet's own form layout). They are set to the same
# rate-based estimate as the filed summary, so the two can never disagree. F540NR.97 is the overpayment,
# i.e. the negative of the California balance due.
SUMMARY_LINES: dict[str, tuple[str, int]] = {
    "F1040.24": ("federal_total_tax", 1), "F1040.37": ("federal_balance_due", 1),
    "F540NR.64": ("california_total_tax", 1), "F540NR.97": ("california_balance_due", -1),
}
BASIS_NOTE = {
    "engine": "The supplied engine's figure; nothing changed it.",
    "adjustment": "Changed by an approved workpaper adjustment.",
    "amendment": "Changed by a filed amendment.",
    "derived": "Recomputed exactly: this line is a fixed combination of its inputs (sum, difference, carry or "
               "parameter conversion, read from the engine's own figures), applied to their filed values.",
    "estimate_rates": "Estimated: the engine figure plus the effect of the adjustments at this version's "
                      "tax_effect_rates. The engine was not rerun.",
    "not_recomputed": "Affected by an adjustment but not a fixed combination of its inputs (a tax computation, "
                      "limitation or phase-out): the engine's figure is shown and was NOT recomputed.",
}
_LINEAR: dict[tuple[str, str], dict[str, list[tuple[str, float | None]]]] = {}


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def linear_terms(idx: PacketIndex, version: str) -> dict[str, list[tuple[str, float | None]]]:
    """Lines whose value is a fixed combination of their inputs, read from the engine's own figures:
    a carry (= the input), a parameter conversion (input × factor, e.g. miles × rate), or a signed sum where
    exactly one ± pattern reproduces the value. Zero-valued inputs whose sign cannot be read get None — a
    change to one of them makes the line "not recomputed"."""
    key = (idx.packet.sha256, version)
    if key in _LINEAR:
        return _LINEAR[key]
    lines = idx.return_lines_by_version[version]
    out: dict[str, list[tuple[str, float | None]]] = {}
    for k, ln in lines.items():
        ins = [i for i in ln.get("inputs", ()) if i in lines]
        val = ln["value"]
        if not ins or not _num(val) or any(not _num(lines[i]["value"]) for i in ins):
            continue
        vals = [float(lines[i]["value"]) for i in ins]
        if len(ins) == 1:
            if abs(vals[0] - val) < 0.5:
                out[k] = [(ins[0], 1.0)]
            elif vals[0] and any(src.startswith("ref:param.") for src in ln.get("sources", ())):
                out[k] = [(ins[0], val / vals[0])]
            continue
        nonzero = [j for j, x in enumerate(vals) if x != 0]
        if abs(sum(vals) - val) < 0.5:
            out[k] = [(i, 1.0) for i in ins]
            continue
        if len(nonzero) > 14:
            continue
        found = []
        for mask in range(1 << len(nonzero)):
            total = sum(-vals[j] if mask >> n & 1 else vals[j] for n, j in enumerate(nonzero))
            if abs(total - val) < 0.5:
                found.append(mask)
                if len(found) > 1:
                    break
        if len(found) == 1:
            sign = {j: (-1.0 if found[0] >> n & 1 else 1.0) for n, j in enumerate(nonzero)}
            signs = set(sign.values())
            zero_sign = signs.pop() if len(signs) == 1 else None
            out[k] = [(i, sign.get(j, zero_sign)) for j, i in enumerate(ins)]
    _LINEAR[key] = out
    return out


def derive_lines(idx: PacketIndex, version: str, base: list[dict[str, Any]], changes: dict[str, tuple[float, str, int]],
                 estimated: dict[str, float]) -> list[dict[str, Any]]:
    """Filed lines that agree with each other. `base` is the previous filed lines (or the engine's); `changes`
    maps a line to (new value, "adjustment" | "amendment", record id). Every line downstream of a change is
    recomputed exactly when it is a fixed combination of its inputs, set to the filed estimate when it is a
    summary line, and otherwise marked "not recomputed" — never silently left at the engine's figure."""
    lines = {ln["key"]: dict(ln) for ln in base}
    terms = linear_terms(idx, version)
    consumers = idx.lines_by_input
    delta: dict[str, float] = {}
    for key, (value, basis, rec) in changes.items():
        ln = lines[key]
        delta[key] = float(value) - float(ln["filed_value"])
        ln["filed_value"], ln["basis"] = value, basis
        ln["affected_by"] = sorted(set(ln.get("affected_by") or []) | {f"{basis}:{rec}"})
    # Everything downstream of a change, in dependency order.
    down: set[str] = set()
    stack = list(changes)
    while stack:
        for d in consumers.get((version, stack.pop()), ()):
            if d not in down and d in lines:
                down.add(d)
                stack.append(d)
    order: list[str] = []
    seen: set[str] = set()

    def visit(k: str) -> None:
        if k in seen:
            return
        seen.add(k)
        for i in idx.return_lines_by_version[version][k].get("inputs", ()):
            if i in down:
                visit(i)
        order.append(k)

    for k in sorted(down):
        visit(k)
    stale: set[str] = {k for k, ln in lines.items() if ln.get("basis") == "not_recomputed"}
    for k in order:
        ln = lines[k]
        src = idx.return_lines_by_version[version][k]
        moved = [i for i in src.get("inputs", ()) if i in delta or i in stale]
        ln["affected_by"] = sorted(set(ln.get("affected_by") or []) | {a for i in moved for a in lines[i].get("affected_by") or []})
        coefs = terms.get(k)
        bad = coefs is None or any(i in stale for i in moved) or any(c is None and delta.get(i) for i, c in (coefs or []))
        if k in SUMMARY_LINES:
            continue
        if bad:
            stale.add(k)
            ln["basis"] = "not_recomputed"
            continue
        d = sum((c or 0) * delta.get(i, 0.0) for i, c in coefs)
        if d:
            delta[k] = d
            v = round(float(ln["filed_value"]) + d, 2)
            ln["filed_value"] = int(v) if v.is_integer() else v
        if ln.get("basis", "engine") not in ("adjustment", "amendment"):
            ln["basis"] = "derived"
    for key, (field, sign) in SUMMARY_LINES.items():
        if key in lines and field in estimated:
            ln = lines[key]
            new = round(sign * estimated[field])
            if new != ln["engine_value"] or ln.get("affected_by"):
                ln["filed_value"], ln["basis"] = new, "estimate_rates"
    out = []
    for ln in base:
        x = lines[ln["key"]]
        x.setdefault("basis", "engine")
        x.setdefault("affected_by", [])
        out.append(x)
    return out


def filed_summary(lines: list[dict[str, Any]]) -> dict[str, Any]:
    by = {ln["key"]: ln for ln in lines}
    return {field: {"line": key, "value": sign * by[key]["filed_value"], "basis": by[key]["basis"]}
            for key, (field, sign) in SUMMARY_LINES.items() if key in by}


def package(db: Session, idx: PacketIndex, engagement_id: str, names: dict[str, str], *, board: list[dict[str, Any]],
            open_items: list[dict[str, Any]], accepted_items: list[dict[str, Any]]) -> dict[str, Any]:
    """The return as the workpaper finalizes it: engine output + applied adjustments, and the record behind it."""
    v = idx.current_version
    ver = idx.versions_by_id[v]
    applied = list(db.scalars(select(Adjustment).where(Adjustment.engagement_id == engagement_id, Adjustment.version == v,
                                                       Adjustment.status == "applied").order_by(Adjustment.id)).all())
    summary = workpaper_summary(idx, v, applied)
    engine_lines = [{"key": ln["key"], "label": ln["label"], "form": ln["form"], "engine_value": ln["value"],
                     "filed_value": ln["value"], "basis": "engine", "affected_by": []} for ln in ver["lines"]]
    lines = derive_lines(idx, v, engine_lines, {a.target_line: (a.adjusted_value, "adjustment", a.id) for a in applied},
                         summary["estimated"])
    judgments = db.scalars(select(Judgment).where(Judgment.engagement_id == engagement_id, Judgment.status != "superseded")
                           .order_by(Judgment.id)).all()
    verifs = db.scalars(select(Verification).where(Verification.engagement_id == engagement_id, Verification.status == "active")
                        .order_by(Verification.id)).all()
    answers = db.scalars(select(ClientQuestion).where(ClientQuestion.engagement_id == engagement_id,
                                                      ClientQuestion.status == "accepted").order_by(ClientQuestion.id)).all()
    signed = []
    for area in board:
        signed.append({"area": area["key"], "title": area["title"],
                       "levels": [{"level": lv["level"], "status": lv["status"], "by": lv["by"], "at": lv["at"]} for lv in area["levels"]]})
    content = {
        "return_version": v, "computed_at": ver["computed_at"], "packet_sha256": idx.packet.sha256,
        "engine_summary": {"federal": dict(ver["summary"]["federal"]), "california": dict(ver["summary"]["california"])},
        "workpaper_summary": summary,
        "filed_summary": filed_summary(lines),
        "basis_notes": BASIS_NOTE,
        "basis": "Filed figures are the supplied engine's output plus the applied adjustments; totals that include "
                 "adjustments are estimates at this version's tax_effect_rates (the engine was not rerun).",
        "adjustments": [{"id": a.id, "line": a.target_line, "original_value": a.original_value, "adjusted_value": a.adjusted_value,
                         "difference": a.difference, "unit": a.unit, "reason": a.reason, "effect": a.effect,
                         "evidence_refs": a.evidence_refs, "finding_id": a.finding_id, "created_by": names.get(a.created_by_id),
                         "approved_by": names.get(a.approved_by_id or ""), "approved_at": a.approved_at,
                         "review_required": a.review_required} for a in applied],
        "lines": lines,
        "documents": {"used": list(ver["documents_used"]), "superseded": list(ver["documents_superseded"])},
        "signoffs": signed,
        "judgments": [{"id": j.id, "topic": j.topic, "decision": j.decision, "decision_option": j.decision_option,
                       "authority": j.authority, "rationale": j.rationale, "target_refs": j.target_refs, "evidence_refs": j.evidence_refs,
                       "tax_effect": j.tax_effect, "status": j.status, "prepared_by": names.get(j.prepared_by_id),
                       "reviewed_by": names.get(j.reviewed_by_id or ""), "partner_by": names.get(j.partner_by_id or "")}
                      for j in judgments],
        "verifications": [{"id": x.id, "target_ref": x.target_ref, "method": x.method, "by": names.get(x.verified_by_id),
                           "at": x.verified_at, "note": x.note, "evidence_refs": x.evidence_refs} for x in verifs],
        "client_answers": [{"id": q.id, "ref": f"client_answer:{q.id}", "about": q.target_ref, "question": q.question,
                            "answer": q.answer, "answered_by": names.get(q.answered_by_id or ""), "accepted_by": names.get(q.accepted_by_id or "")}
                           for q in answers],
        "unresolved_items": open_items,
        "accepted_with_explanation": accepted_items,
    }
    return storable(mask_payload(content))


# ---- certificate ---------------------------------------------------------------------------------------

def certificate(db: Session, idx: PacketIndex, engagement_id: str, snap: FiledSnapshot, names: dict[str, str]) -> dict[str, Any]:
    c = snap.content
    evs = events(db, engagement_id)
    approval = next((e for e in reversed(evs) if e.action == "client_approved_and_signed_8879"), None)
    submissions = [s | {"recorded_at_event": e.timeline_id} for e in evs for s in e.detail.get("submissions", [])]
    accepted = {s["jurisdiction"]: s["date"] for s in submissions if s["status"] == "accepted"}
    level_rollup = {}
    for lv in ("prepared", "reviewed", "partner"):
        people = sorted({x["by"] for a in c["signoffs"] for x in a["levels"] if x["level"] == lv and x["status"] == "signed" and x["by"]})
        complete = all(x["status"] == "signed" for a in c["signoffs"] for x in a["levels"] if x["level"] == lv)
        level_rollup[lv] = {"by": people, "complete": complete}
    post = [{"at": e.at, "event": e.action, "label": REPLAY.get(e.action, ("", e.action, ""))[1], "detail": mask_text(e.note)}
            for e in evs if e.kind == "replay" and e.action in ("federal_balance_paid", "california_refund_issued")]
    return mask_payload({
        "snapshot_id": snap.id, "kind": snap.kind, "number": snap.number, "content_sha256": snap.content_sha256,
        "integrity": verify(snap), "filed_at": snap.filed_at, "return_version": c["return_version"],
        "engine_summary": c["engine_summary"], "workpaper_summary": c["workpaper_summary"], "basis": c["basis"],
        "filed_summary": c.get("filed_summary"),
        "effective_adjustments": c["adjustments"], "documents_used": c["documents"]["used"],
        "documents_superseded": c["documents"]["superseded"], "signoffs": level_rollup, "signoffs_by_area": c["signoffs"],
        "client_approval": {"at": approval.at, "detail": approval.note, "refs": approval.detail.get("refs", []),
                            "fingerprint": approval.detail.get("fingerprint", {}).get("sha256")} if approval else None,
        "efile_submissions": submissions, "accepted": accepted, "post_filing": post,
        "unresolved_items": c["unresolved_items"], "accepted_with_explanation": c["accepted_with_explanation"],
        "judgments": [{"id": j["id"], "topic": j["topic"], "decision": j["decision"], "authority": j["authority"]} for j in c["judgments"]],
    })


def verify(snap: FiledSnapshot) -> dict[str, Any]:
    actual = canonical_hash(snap.content)
    return {"valid": actual == snap.content_sha256, "stored": snap.content_sha256, "computed": actual}


def latest_snapshot(db: Session, engagement_id: str) -> FiledSnapshot | None:
    return db.scalar(select(FiledSnapshot).where(FiledSnapshot.engagement_id == engagement_id).order_by(FiledSnapshot.id.desc()).limit(1))


def original_snapshot(db: Session, engagement_id: str) -> FiledSnapshot | None:
    return db.scalar(select(FiledSnapshot).where(FiledSnapshot.engagement_id == engagement_id, FiledSnapshot.kind == "original"))
