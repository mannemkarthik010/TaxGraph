"""Filing API: lifecycle state and firm actions, replay of the scripted timeline, filed snapshots, the
filing certificate and amendments. Every gate is checked here, server-side, and every step is audited."""

from __future__ import annotations

import copy
import re
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..deps import Ctx, require
from ..models import Amendment, FiledSnapshot, FilingEvent
from ..packet.refs import resolve
from ..security.masking import mask_payload, mask_text
from ..security.roles import Perm
from ..services import adjustments as A
from ..services import audit
from ..services import filing as F
from ..services import inbox as IB
from ..services.assurance import challenge
from .collaboration import _board, _items, _names, evidence_kind

router = APIRouter(prefix="/api")
STAFF_ACTORS = ("preparer", "reviewer", "partner")


def _err(e: F.FilingError):
    return HTTPException(e.status, e.detail if e.detail is not None else str(e))


def _readiness(c: Ctx) -> dict:
    items = _items(c)
    return IB.readiness(items, _board(c, items))


def _gate_readiness(c: Ctx, what: str) -> None:
    r = _readiness(c)
    if not r["can_file"]:
        raise HTTPException(409, {"message": f"{what} is blocked: the workpaper is not ready.",
                                  "checks": mask_payload([ch for ch in r["checks"] if not ch["ok"]])})


def _since_reopen(evs: list[FilingEvent]) -> list[FilingEvent]:
    """Events since the last reopen: approvals before a reopen no longer count."""
    last = max((i for i, e in enumerate(evs) if e.action == "reopen"), default=-1)
    return evs[last + 1:]


def _approval(evs: list[FilingEvent], action: str) -> dict | None:
    e = next((e for e in reversed(_since_reopen(evs)) if e.action == action), None)
    return e.detail.get("fingerprint") if e else None


def _gate_fingerprint(c: Ctx, evs: list[FilingEvent], against: str, who: str) -> dict:
    current = F.fingerprint(c.db, c.idx, c.engagement.id)
    approved = _approval(evs, against)
    if approved is None:
        raise HTTPException(409, f"No {who} approval on record.")
    if approved["sha256"] != current["sha256"]:
        raise HTTPException(409, f"The return changed after the {who} approved it ({F.describe_change(approved, current)}). "
                                 "The partner must reopen it and the approvals must be given again.")
    return current


def _received_by(c: Ctx, ref: str, at: str) -> None:
    """A correction may only cite evidence that existed at the replay clock."""
    kind = evidence_kind(c, ref)
    r = resolve(c.idx, ref)
    doc_id = r.document_id or (ref if ref in c.idx.documents_by_id else None)
    if doc_id:
        received = c.idx.documents_by_id[doc_id]["received_at"]
        if received > at:
            raise HTTPException(422, f"{doc_id} had not been received yet at {at} (received {received}).")
    if kind == "client_message":
        msg = next((m for m in c.idx.data["client"]["messages"] if m["id"] == ref), None)
        if msg and msg["sent_at"] > at:
            raise HTTPException(422, f"{ref} had not been sent yet at {at}.")


def _open_and_accepted(c: Ctx) -> tuple[list[dict], list[dict]]:
    items = _items(c)
    open_ = [{"key": i.key, "title": i.title, "group": i.group} for i in items if i.status == "open"]
    accepted = [{"key": i.key, "title": i.title, "explanation": (i.handled or {}).get("note")}
                for i in items if i.status == "handled" and (i.handled or {}).get("kind") == "accepted"]
    return open_, accepted


def _package(c: Ctx) -> dict:
    items = _items(c)
    open_, accepted = _open_and_accepted(c)
    return F.package(c.db, c.idx, c.engagement.id, _names(c), board=_board(c, items), open_items=open_, accepted_items=accepted)


def _event_dict(e: FilingEvent, names: dict[str, str], internal: bool) -> dict:
    d = {"id": e.id, "at": e.at, "kind": e.kind, "action": e.action, "timeline_id": e.timeline_id,
         "label": F.ACTIONS[e.action][3] if e.action in F.ACTIONS else F.REPLAY.get(e.action, (None, e.action))[1],
         "from_state": e.from_state, "to_state": e.to_state, "actor": names.get(e.actor_id or ""), "actor_role": e.actor_role}
    if internal:
        detail = {k: v for k, v in e.detail.items() if k != "package"}
        d |= {"note": e.note, "detail": detail, "recorded_at": e.recorded_at}
    return mask_payload(d)


# ---- state ---------------------------------------------------------------------------------------------

@router.get("/filing/state")
def filing_state(c: Ctx = Depends(require(Perm.VIEW_RETURN))):
    internal = c.can(Perm.VIEW_INTERNAL_NOTES)
    evs = F.events(c.db, c.engagement.id)
    names = _names(c)
    cur = F.state(c.db, c.engagement.id)
    now = F.clock(c.db, c.idx, c.engagement.id)
    nxt = F.next_scripted(c.db, c.idx, c.engagement.id)
    awaiting = cur == "partner_approved" and _scripted_approval_spent(c, evs)
    out = {"state": cur, "label": F.STATE_LABEL[cur], "states": [{"key": s, "label": F.STATE_LABEL[s]} for s in F.STATES],
           "clock": now, "history": [_event_dict(e, names, internal) for e in evs],
           "jurisdictions": mask_payload(F.jurisdictions(c.db, c.engagement.id)),
           "awaiting_client": awaiting, "client_can_approve": awaiting and c.user.kind == "client"}
    if not internal:
        return out
    actions = []
    for key, (allowed, _to, roles, label) in F.ACTIONS.items():
        why = []
        if cur not in allowed:
            why.append(f"needs {' or '.join(F.STATE_LABEL[s] for s in allowed)}")
        if c.user.role not in roles:
            why.append(f"done by a {' or '.join(roles)}")
        actions.append({"action": key, "label": label, "available": not why, "why_not": why,
                        "needs_note": key in ("resubmit", "reopen"), "needs_refs": key == "resubmit"})
    replay = None
    if nxt:
        allowed, label, needs = F.REPLAY.get(nxt["event"], (F.ANY, nxt["event"], ""))
        replay = {"id": nxt["id"], "at": nxt["at"], "event": nxt["event"], "label": label, "refs": list(nxt["refs"]),
                  "detail": mask_text(nxt["detail"]), "possible": cur in allowed,
                  "needs": None if cur in allowed else f"needs {needs} (the return is {F.STATE_LABEL[cur]})",
                  "can_replay": c.user.role in STAFF_ACTORS}
    current_fp = F.fingerprint(c.db, c.idx, c.engagement.id)["sha256"]
    partner_fp, client_fp = _approval(evs, "partner_approve"), _approval(evs, "client_approved_and_signed_8879")
    snaps = c.db.scalars(select(FiledSnapshot).where(FiledSnapshot.engagement_id == c.engagement.id).order_by(FiledSnapshot.id)).all()
    return out | {
        "actions": actions, "next_event": replay,
        "upcoming": [{"id": t["id"], "at": t["at"], "event": t["event"], "label": F.REPLAY.get(t["event"], (0, t["event"]))[1]}
                     for t in F.script(c.idx) if t["id"] not in {e.timeline_id for e in evs}],
        "approval": {"current": current_fp, "partner": partner_fp and partner_fp["sha256"], "client": client_fp and client_fp["sha256"],
                     "client_matches": bool(client_fp and client_fp["sha256"] == current_fp)},
        "snapshots": [{"id": s.id, "kind": s.kind, "number": s.number, "filed_at": s.filed_at, "content_sha256": s.content_sha256,
                       "integrity": F.verify(s)["valid"]} for s in snaps],
    }


def _scripted_approval_spent(c: Ctx, evs: list[FilingEvent]) -> bool:
    """The packet scripts one client approval (tl-20). Once it has been replayed, any later approval — after the
    partner reopened and re-approved the return — is given by the client in TaxProof."""
    scripted = {t["id"] for t in F.script(c.idx) if t["event"] == "client_approved_and_signed_8879"}
    return bool(scripted) and scripted <= {e.timeline_id for e in evs}


class ClientApprovalIn(BaseModel):
    confirm: bool


@router.post("/filing/client-approval")
def client_approval(body: ClientApprovalIn, c: Ctx = Depends(require(Perm.VIEW_RETURN))):
    """The client approves the return again (Forms 8879 / FTB 8879) after the partner reopened and re-approved it."""
    if c.user.kind != "client":
        raise HTTPException(403, "Only the client approves the return and signs Form 8879.")
    if not body.confirm:
        raise HTTPException(422, "Confirm that you reviewed the return and authorize its e-filing (Form 8879 / FTB 8879).")
    cur = F.state(c.db, c.engagement.id)
    if cur != "partner_approved":
        raise HTTPException(409, f"There is nothing to approve yet: the return is {F.STATE_LABEL[cur]}.")
    evs = F.events(c.db, c.engagement.id)
    if not _scripted_approval_spent(c, evs):
        nxt = next(t for t in F.script(c.idx) if t["event"] == "client_approved_and_signed_8879")
        raise HTTPException(409, f"The client's approval is part of the replayed season ({nxt['id']}, {nxt['at']}): replay it.")
    current = F.fingerprint(c.db, c.idx, c.engagement.id)
    partner = _approval(evs, "partner_approve")
    if not partner or partner["sha256"] != current["sha256"]:
        raise HTTPException(409, "The return changed after the partner approved it: the partner must approve again first.")
    at = F.clock(c.db, c.idx, c.engagement.id)
    F.record(c.db, c.engagement.id, at=at, kind="client", action="client_approved_and_signed_8879", from_state=cur,
             to_state="client_approved", actor_id=c.user.id, actor_role=c.user.role,
             note=f"Approved in TaxProof by {c.user.name}: Forms 8879 and FTB 8879 signed electronically for the return as re-approved by the partner.",
             detail={"fingerprint": current, "method": "in_app", "refs": []})
    audit.record(c.db, c.engagement.id, "filing.client_approval", actor_id=c.user.id, actor_role=c.user.role,
                 payload={"at": at, "fingerprint": current["sha256"]})
    c.db.commit()
    return filing_state(c)


# ---- firm actions ----------------------------------------------------------------------------------------

class ActionIn(BaseModel):
    note: str | None = Field(default=None, max_length=4000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)


@router.post("/filing/actions/{action}")
def filing_action(action: str, body: ActionIn, c: Ctx = Depends(require(Perm.VIEW_INTERNAL_NOTES))):
    cur = F.state(c.db, c.engagement.id)
    try:
        to, label = F.check_action(cur, action, c.user.role)
    except F.FilingError as e:
        raise _err(e)
    evs = F.events(c.db, c.engagement.id)
    at = F.clock(c.db, c.idx, c.engagement.id)
    note = (body.note or "").strip() or None
    detail: dict = {}
    if action == "hand_off":
        board = _board(c)
        missing = [a["title"] for a in board if a["levels"][0]["status"] != "signed"]
        if missing:
            raise HTTPException(409, f"Hand-off needs every area prepared; not yet: {', '.join(missing)}.")
    elif action == "partner_approve":
        _gate_readiness(c, "Partner approval")
        detail["fingerprint"] = F.fingerprint(c.db, c.idx, c.engagement.id)
    elif action == "ready_to_file":
        _gate_readiness(c, "Ready to file")
        detail["fingerprint"] = _gate_fingerprint(c, evs, "client_approved_and_signed_8879", "client")
    elif action in ("submit", "resubmit"):
        _gate_readiness(c, "Submission")
        detail["fingerprint"] = _gate_fingerprint(c, evs, "client_approved_and_signed_8879", "client")
        if action == "resubmit":
            if not note or len(note) < 10:
                raise HTTPException(422, "Say what was corrected after the rejection.")
            if not body.evidence_refs:
                raise HTTPException(422, "Cite the evidence for the correction.")
            for ref in body.evidence_refs:
                _received_by(c, ref, at)
            detail["correction"] = {"note": note, "evidence_refs": body.evidence_refs}
        pkg = _package(c)
        detail |= {"package": pkg, "package_sha256": F.canonical_hash(pkg)}
    elif action == "record_filed":
        sub = next((e for e in reversed(evs) if e.action in ("submit", "resubmit")), None)
        pkg = sub.detail["package"]
        if F.canonical_hash(pkg) != sub.detail["package_sha256"]:
            raise HTTPException(500, "The accepted submission package does not match its recorded hash.")
        accepted = F.jurisdictions(c.db, c.engagement.id)
        filed_at = max(s["date"] for s in accepted.values() if s["status"] == "accepted")
        snap = FiledSnapshot(engagement_id=c.engagement.id, kind="original", number=0, version=pkg["return_version"],
                             filed_at=filed_at, created_by_id=c.user.id, content=pkg, content_sha256=sub.detail["package_sha256"])
        c.db.add(snap)
        c.db.flush()
        detail |= {"snapshot_id": snap.id, "content_sha256": snap.content_sha256,
                   "submission_ids": [s["submission_id"] for s in accepted.values()]}
        audit.record(c.db, c.engagement.id, "filing.snapshot_created", actor_id=c.user.id, actor_role=c.user.role,
                     payload={"snapshot_id": snap.id, "kind": "original", "content_sha256": snap.content_sha256})
    elif action == "reopen":
        if not note or len(note) < 5:
            raise HTTPException(422, "Say why the return is reopened; approvals given so far will need to be given again.")
    F.record(c.db, c.engagement.id, at=at, kind="action", action=action, from_state=cur, to_state=to, actor_id=c.user.id,
             actor_role=c.user.role, note=note, detail=detail)
    audit.record(c.db, c.engagement.id, f"filing.{action}", actor_id=c.user.id, actor_role=c.user.role,
                 payload={"from": cur, "to": to, "at": at, "note": note,
                          "fingerprint": (detail.get("fingerprint") or {}).get("sha256"), "package_sha256": detail.get("package_sha256")})
    c.db.commit()
    return filing_state(c)


# ---- replay ----------------------------------------------------------------------------------------------

def _linked_findings(c: Ctx, errors: list[dict]) -> list[dict]:
    """Rejection errors that name a household member point at TaxProof findings about that person."""
    people = [p["name"] for p in c.idx.data["household"]["people"]]
    named = {p for e in errors for p in people if p in e.get("message", "")}
    return [{"id": f.id, "title": f.title, "status": f.status} for f in challenge(c.idx, c.idx.current_version)
            if f.status != "pass" and any(p in f.title for p in named)]


@router.post("/filing/replay")
def replay(c: Ctx = Depends(require(Perm.VIEW_INTERNAL_NOTES))):
    """Replay the next scripted event of the timeline — only when the lifecycle allows it."""
    if c.user.role not in STAFF_ACTORS:
        raise HTTPException(403, "Replay is driven by the engagement team.")
    t = F.next_scripted(c.db, c.idx, c.engagement.id)
    if t is None:
        raise HTTPException(409, "Nothing left to replay: the scripted timeline is complete.")
    cur = F.state(c.db, c.engagement.id)
    allowed, label, needs = F.REPLAY.get(t["event"], (F.ANY, t["event"], ""))
    if cur not in allowed:
        raise HTTPException(409, f"'{label}' ({t['id']}, {t['at']}) needs {needs}; the return is {F.STATE_LABEL[cur]}.")
    to, detail, note = cur, {"refs": list(t["refs"])}, t["detail"]
    evs = F.events(c.db, c.engagement.id)
    agency = c.idx.data["tax_agency_records"]
    if t["event"] == "client_approved_and_signed_8879":
        current = F.fingerprint(c.db, c.idx, c.engagement.id)
        partner = _approval(evs, "partner_approve")
        if not partner or partner["sha256"] != current["sha256"]:
            raise HTTPException(409, "The return changed after the partner approved it "
                                     f"({F.describe_change(partner or {}, current)}): the partner must approve again first.")
        to, detail["fingerprint"] = "client_approved", current
    elif t["event"].startswith("efile_"):
        subs = [dict(s) for s in agency["efile"] if s["date"] == t["at"]]
        detail["submissions"] = subs
        if t["event"] == "efile_rejected":
            to = "rejected"
            detail["linked_findings"] = _linked_findings(c, [e for s in subs for e in s.get("errors", [])])
        else:
            juris = F.jurisdictions(c.db, c.engagement.id) | {s["jurisdiction"]: s for s in subs}
            if all(juris.get(j, {}).get("status") == "accepted" for j in ("federal", "california")):
                to = "accepted"
    elif t["event"] in ("federal_balance_paid", "california_refund_issued"):
        snap = F.original_snapshot(c.db, c.engagement.id)
        est = snap.content["workpaper_summary"]["estimated"]
        if t["event"] == "federal_balance_paid":
            detail["amount"] = {"federal_balance_due_as_filed": est["federal_balance_due"]}
        else:
            detail["amount"] = {"california_refund_as_filed": -est["california_balance_due"]}
        detail["basis"] = "Amount on the return as filed (engine figures plus applied adjustments; adjustment effects are estimates)."
    elif t["event"] == "notice_received":
        notices = []
        for ref in t["refs"]:
            m = re.match(r"agency:/notices/(\d+)$", ref)
            if m:
                n = agency["notices"][int(m.group(1))]
                notices.append({"id": n["id"], "type": n["type"], "dated": n["dated"], "response_due": n.get("response_due")})
        detail["notices"] = notices
    F.record(c.db, c.engagement.id, at=t["at"], kind="replay", action=t["event"], timeline_id=t["id"], from_state=cur, to_state=to,
             actor_id=c.user.id, actor_role=c.user.role, note=mask_text(note), detail=detail)
    audit.record(c.db, c.engagement.id, f"filing.replay.{t['event']}", actor_id=c.user.id, actor_role=c.user.role,
                 payload={"timeline_id": t["id"], "at": t["at"], "from": cur, "to": to})
    c.db.commit()
    return filing_state(c)


# ---- snapshots and certificate ----------------------------------------------------------------------------

def _snapshot(c: Ctx, sid: int | None) -> FiledSnapshot:
    snap = c.db.get(FiledSnapshot, sid) if sid else F.original_snapshot(c.db, c.engagement.id)
    if snap is None or snap.engagement_id != c.engagement.id:
        raise HTTPException(404 if sid else 409, "Snapshot not found." if sid else "Nothing has been filed yet.")
    return snap


@router.get("/filing/snapshots")
def snapshots(c: Ctx = Depends(require(Perm.VIEW_INTERNAL_NOTES))):
    rows = c.db.scalars(select(FiledSnapshot).where(FiledSnapshot.engagement_id == c.engagement.id).order_by(FiledSnapshot.id)).all()
    return [{"id": s.id, "kind": s.kind, "number": s.number, "base_snapshot_id": s.base_snapshot_id, "filed_at": s.filed_at,
             "content_sha256": s.content_sha256, "integrity": F.verify(s)} for s in rows]


@router.get("/filing/snapshots/{sid}")
def snapshot(sid: int, c: Ctx = Depends(require(Perm.VIEW_INTERNAL_NOTES))):
    s = _snapshot(c, sid)
    return {"id": s.id, "kind": s.kind, "number": s.number, "filed_at": s.filed_at, "content_sha256": s.content_sha256,
            "integrity": F.verify(s), "content": mask_payload(s.content)}


@router.get("/filing/certificate")
def certificate(snapshot_id: int | None = None, c: Ctx = Depends(require(Perm.VIEW_INTERNAL_NOTES))):
    s = _snapshot(c, snapshot_id)
    return F.certificate(c.db, c.idx, c.engagement.id, s, _names(c))


# ---- amendments ------------------------------------------------------------------------------------------

def _amendment_dict(a: Amendment, names: dict[str, str]) -> dict:
    return mask_payload({"id": a.id, "base_snapshot_id": a.base_snapshot_id, "reason": a.reason, "changes": a.changes, "status": a.status,
                         "created_by": names.get(a.created_by_id), "created_by_id": a.created_by_id, "created_at": a.created_at,
                         "approved_by": names.get(a.approved_by_id or ""), "approved_at": a.approved_at,
                         "filed_snapshot_id": a.filed_snapshot_id, "history": [h | {"by_name": names.get(h.get("by"))} for h in a.history],
                         "total_effect": {j: round(sum((x["effect"] or {}).get(j) or 0 for x in a.changes if (x["effect"] or {}).get("kind") == "tax"))
                                          for j in ("federal", "california")}})


def _assert_intact(c: Ctx) -> None:
    """Amendments build on the filed record: refuse while any filed snapshot no longer matches its hash."""
    for s in c.db.scalars(select(FiledSnapshot).where(FiledSnapshot.engagement_id == c.engagement.id)).all():
        if not F.verify(s)["valid"]:
            raise HTTPException(409, f"Snapshot #{s.id} ({s.kind}) failed its integrity check: its content does not match the hash "
                                     "recorded when it was filed. Investigate before amending; nothing is built on altered content.")


def _entry(c: Ctx, action: str, note: str | None = None) -> dict:
    return {"action": action, "by": c.user.id, "role": c.user.role, "at": datetime.now(timezone.utc).isoformat(), "note": note}


def _load_amendment(c: Ctx, aid: int) -> Amendment:
    a = c.db.get(Amendment, aid)
    if a is None or a.engagement_id != c.engagement.id:
        raise HTTPException(404, "Amendment not found.")
    return a


@router.get("/amendments")
def list_amendments(c: Ctx = Depends(require(Perm.VIEW_INTERNAL_NOTES))):
    names = _names(c)
    return [_amendment_dict(a, names) for a in c.db.scalars(select(Amendment).where(Amendment.engagement_id == c.engagement.id)
                                                             .order_by(Amendment.id.desc())).all()]


class AmendmentIn(BaseModel):
    reason: str = Field(min_length=10, max_length=4000)


@router.post("/amendments", status_code=201)
def create_amendment(body: AmendmentIn, c: Ctx = Depends(require(Perm.ADJUST))):
    if F.state(c.db, c.engagement.id) not in F.POST_FILING:
        raise HTTPException(409, "Nothing is filed yet: change the return with adjustments, not an amendment.")
    _assert_intact(c)
    base = F.latest_snapshot(c.db, c.engagement.id)
    if c.db.scalar(select(Amendment).where(Amendment.engagement_id == c.engagement.id, Amendment.status.in_(("draft", "approved")))):
        raise HTTPException(409, "Finish or withdraw the open amendment first.")
    a = Amendment(engagement_id=c.engagement.id, base_snapshot_id=base.id, reason=body.reason.strip(), changes=[], status="draft",
                  created_by_id=c.user.id, created_by_role=c.user.role, history=[_entry(c, "create", body.reason)])
    c.db.add(a)
    c.db.flush()
    audit.record(c.db, c.engagement.id, "amendment.created", actor_id=c.user.id, actor_role=c.user.role,
                 payload={"amendment_id": a.id, "base_snapshot_id": base.id})
    c.db.commit()
    return _amendment_dict(a, _names(c))


class ChangeIn(BaseModel):
    line: str = Field(min_length=1, max_length=60)
    amended_value: float
    reason: str = Field(min_length=3, max_length=4000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)


@router.post("/amendments/{aid}/changes")
def add_change(aid: int, body: ChangeIn, c: Ctx = Depends(require(Perm.ADJUST))):
    a = _load_amendment(c, aid)
    if a.status != "draft":
        raise HTTPException(409, f"The amendment is {a.status}; only a draft can change.")
    base = c.db.get(FiledSnapshot, a.base_snapshot_id)
    filed = next((ln for ln in base.content["lines"] if ln["key"] == body.line), None)
    if filed is None:
        raise HTTPException(404, f"{body.line} is not on the filed return.")
    try:
        A.validate_target(c.idx, base.version, body.line)
    except A.AdjustmentError as e:
        raise HTTPException(e.status, str(e))
    for ref in body.evidence_refs:
        evidence_kind(c, ref)
    diff = round(body.amended_value - float(filed["filed_value"]), 2)
    if diff == 0:
        raise HTTPException(422, "The amended value equals the filed value.")
    # One correction, one line: a line and a line computed from it (either way) cannot both be amended here.
    related = A.flow_related(c.idx, base.version, body.line)
    clash = next((x["line"] for x in a.changes if x["line"] != body.line and x["line"] in related), None)
    if clash:
        how = (f"{clash} is computed from {body.line}" if clash in A.flows_into(c.idx, base.version, body.line)
               else f"{body.line} is computed from {clash}")
        raise HTTPException(409, f"{how}: amending both would count one correction twice. Change only one of them "
                                 f"(remove the {clash} change first, or amend {clash} alone).")
    change = {"line": body.line, "label": filed["label"], "filed_value": filed["filed_value"], "amended_value": body.amended_value,
              "difference": diff, "unit": A.unit_of(c.idx, base.version, body.line),
              "effect": A.estimate_effect(c.idx, base.version, body.line, diff), "reason": body.reason.strip(),
              "evidence_refs": body.evidence_refs}
    a.changes = [x for x in a.changes if x["line"] != body.line] + [F.storable(change)]
    a.history = list(a.history) + [_entry(c, "change", f"{body.line}: {filed['filed_value']} → {body.amended_value}")]
    audit.record(c.db, c.engagement.id, "amendment.changed", actor_id=c.user.id, actor_role=c.user.role,
                 target_ref=f"line:{base.version}:{body.line}", payload={"amendment_id": a.id, "difference": diff})
    c.db.commit()
    return _amendment_dict(a, _names(c))


@router.post("/amendments/{aid}/{action}")
def amendment_action(aid: int, action: Literal["approve", "file", "withdraw"], c: Ctx = Depends(require(Perm.ADJUST))):
    a = _load_amendment(c, aid)
    if action == "approve":
        if c.user.role != "partner":
            raise HTTPException(403, "An amendment to a filed return is approved by the partner.")
        contributors = {h.get("by") for h in a.history if h.get("action") in ("create", "change")}
        if c.user.id in contributors:
            raise HTTPException(403, "You contributed to this amendment (created or changed it); someone independent must "
                                     "approve it. A person may not review or sign off on work they prepared.")
        if a.status != "draft" or not a.changes:
            raise HTTPException(409, "Only a draft with at least one change can be approved.")
        a.status, a.approved_by_id, a.approved_at = "approved", c.user.id, datetime.now(timezone.utc)
    elif action == "file":
        if c.user.role not in ("reviewer", "partner"):
            raise HTTPException(403, "Filing an amendment is done by a reviewer or partner.")
        if a.status != "approved":
            raise HTTPException(409, "The partner must approve the amendment before it is filed.")
        _assert_intact(c)
        base = c.db.get(FiledSnapshot, a.base_snapshot_id)
        content = copy.deepcopy(base.content)
        # The totals move with the amendment (estimates at the filed version's rates), and every line computed
        # from an amended line is recomputed or marked "not recomputed" — the snapshot never contradicts itself.
        summary = content["workpaper_summary"]
        est = dict(summary["estimated"])
        for x in a.changes:
            eff = x.get("effect") or {}
            fed, ca = eff.get("federal") or 0, eff.get("california") or 0
            if eff.get("kind") == "tax":
                est["federal_total_tax"] += fed
                est["california_total_tax"] += ca
            if eff.get("kind") in ("tax", "balance"):
                est["federal_balance_due"] += fed
                est["california_balance_due"] += ca
        summary["estimated"] = {k: round(v) for k, v in est.items()}
        summary["amendments_applied"] = summary.get("amendments_applied", 0) + 1
        summary["note"] = (summary.get("note", "") + f" Amendment {a.id}: effects estimated at the filed version's rates.").strip()
        content["lines"] = F.derive_lines(c.idx, base.version, content["lines"],
                                          {x["line"]: (x["amended_value"], "amendment", a.id) for x in a.changes},
                                          summary["estimated"])
        content["filed_summary"] = F.filed_summary(content["lines"])
        number = 1 + max((s.number for s in c.db.scalars(select(FiledSnapshot).where(FiledSnapshot.engagement_id == c.engagement.id))), default=0)
        content["amendment"] = {"id": a.id, "number": number, "base_snapshot_id": base.id, "base_sha256": base.content_sha256,
                                "reason": a.reason, "changes": a.changes,
                                "basis": "Effects are estimates at the filed version's tax_effect_rates; the engine was not rerun."}
        content = F.storable(mask_payload(content))
        clk = F.clock(c.db, c.idx, c.engagement.id)
        snap = FiledSnapshot(engagement_id=c.engagement.id, kind="amendment", number=number, base_snapshot_id=base.id,
                             version=base.version, filed_at=clk, created_by_id=c.user.id, content=content,
                             content_sha256=F.canonical_hash(content))
        c.db.add(snap)
        c.db.flush()
        a.status, a.filed_snapshot_id = "filed", snap.id
        audit.record(c.db, c.engagement.id, "filing.snapshot_created", actor_id=c.user.id, actor_role=c.user.role,
                     payload={"snapshot_id": snap.id, "kind": "amendment", "amendment_id": a.id, "content_sha256": snap.content_sha256})
    else:
        if a.status not in ("draft", "approved"):
            raise HTTPException(409, f"The amendment is {a.status}.")
        a.status = "withdrawn"
    a.history = list(a.history) + [_entry(c, action)]
    audit.record(c.db, c.engagement.id, f"amendment.{action}", actor_id=c.user.id, actor_role=c.user.role, payload={"amendment_id": a.id})
    c.db.commit()
    return _amendment_dict(a, _names(c))

