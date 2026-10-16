"""Examiner Mode and agency-notice responses: the filed return, reconstructed and defended years later.

Everything here is read from the **filed snapshot** (what was filed, the adjustments, verifications,
judgments and client answers recorded with it) plus the immutable packet's evidence graph. Internal
collaboration — review notes, the inbox, escalations, assignments, client-question threads, sign-off
reopen history — is deliberately left out; the view says what it excludes.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..deps import Ctx, require
from ..models import FiledSnapshot, NoticeResponse
from ..packet.index import PacketIndex
from ..packet.refs import resolve
from ..security.masking import mask_payload, mask_text
from ..security.roles import Perm
from ..services import audit
from ..services import filing as F
from ..services.assurance import challenge
from ..services.graph import GraphView, get_graph, subgraph
from .collaboration import _names

router = APIRouter(prefix="/api")

EVIDENCE_KINDS = ("Document", "Page", "ExtractedValue", "PriorYearValue", "AgencyRecord", "Asset", "ClientAnswer")
EXCLUDED = ["review notes", "the Uncertainty Inbox (assignments, escalations, internal resolutions)",
            "client-question threads (only answers accepted as evidence are shown)", "sign-off reopen history"]


def _snapshot(c: Ctx) -> FiledSnapshot:
    snap = F.latest_snapshot(c.db, c.engagement.id)
    if snap is None:
        raise HTTPException(409, "Examiner Mode reconstructs a filed return; nothing has been filed yet.")
    return snap


def _received_notices(c: Ctx) -> dict[str, str]:
    """Notices the firm has (replayed `notice_received` events): id → received at."""
    out = {}
    for e in F.events(c.db, c.engagement.id):
        for n in e.detail.get("notices", []):
            out[n["id"]] = e.at
    return out


def notice_lines(idx: PacketIndex, text: str) -> list[str]:
    """Return lines an examination item names, deterministically: "Schedule A line 12" → SchA.12; "(Form 8283)"
    → the Form 8283 lines; "Schedule C gross receipts" → the Schedule C line with that label."""
    lines = idx.return_lines_by_version[idx.current_version]
    keys: list[str] = []
    for sched, num in re.findall(r"Schedule ([A-Z0-9]+) line (\w+)", text):
        k = f"Sch{sched}.{num}"
        if k in lines:
            keys.append(k)
    for form in re.findall(r"Form (\d{4})", text):
        keys += [k for k, ln in lines.items() if ln["form"] == f"F{form}" and k not in keys]
    if not keys:
        for sched, phrase in re.findall(r"Schedule ([A-Z0-9]+) ([a-z][a-z ]+?)(?:[:,.(]|$)", text):
            keys += [k for k, ln in lines.items() if ln["form"] == f"Sch{sched}" and phrase.strip() in ln["label"].lower()]
    return keys


def examine(c: Ctx, snap: FiledSnapshot, key: str) -> dict[str, Any]:
    content = snap.content
    filed = {ln["key"]: ln for ln in content["lines"]}
    if key not in filed:
        raise HTTPException(404, f"{key} is not on the filed return.")
    ver = snap.version
    line = c.idx.line(ver, key)
    original = F.original_snapshot(c.db, c.engagement.id)
    orig_value = next((ln["filed_value"] for ln in original.content["lines"] if ln["key"] == key), None) if original else None
    ref = f"line:{ver}:{key}"

    # Evidence: everything upstream of the line in the immutable packet graph.
    view = GraphView(get_graph(c.idx), [], [])
    sg = subgraph(view, ref, "up", depth=10, max_children=200, max_per_level=500, include_rules=True)
    evidence = [{"ref": n["id"], "kind": n["kind"], "label": n["label"], "value": n["value"]}
                for n in sg["nodes"] if n["kind"] in EVIDENCE_KINDS]
    rule = line.get("rule")
    rules = c.idx.data["engine_reference"]["rules"]
    inputs = [{"key": i, "label": filed[i]["label"] if i in filed else i, "filed_value": filed.get(i, {}).get("filed_value"),
               "basis": filed.get(i, {}).get("basis")}
              for i in line.get("inputs", ())]

    adjustments = [a for a in content["adjustments"] if a["line"] == key]
    cited = {r for a in adjustments for r in a["evidence_refs"]}
    upstream = {e["ref"] for e in evidence}
    verifications = [v for v in content["verifications"] if v["target_ref"] in ({ref} | upstream)]
    judgments = [j for j in content["judgments"] if ref in j["target_refs"]]
    cited |= {r for v in verifications for r in v["evidence_refs"]} | {r for j in judgments for r in j["evidence_refs"]}
    answers = [q for q in content["client_answers"] if q["about"] in ({ref} | upstream) or q["ref"] in cited]
    for r in sorted(cited - upstream):
        if r.startswith("client_answer:"):
            continue
        res = resolve(c.idx, r)
        if res.exists:
            evidence.append({"ref": r, "kind": res.kind, "label": res.label, "value": None, "cited_by_workpaper": True})
    checks = [{"id": f.id, "title": f.title, "status": f.status, "summary": f.summary, "breakdown": f.breakdown,
               "engine": f.engine, "independent": f.independent}
              for f in challenge(c.idx, ver) if key in f.lines]
    amendments = []
    for s in c.db.scalars(select(FiledSnapshot).where(FiledSnapshot.engagement_id == c.engagement.id,
                                                      FiledSnapshot.kind == "amendment").order_by(FiledSnapshot.id)).all():
        for ch in s.content.get("amendment", {}).get("changes", []):
            if ch["line"] == key:
                amendments.append({"snapshot_id": s.id, "number": s.number, "filed_at": s.filed_at, **ch})
    accepted = {j: s["date"] for j, s in F.jurisdictions(c.db, c.engagement.id).items() if s["status"] == "accepted"}
    return mask_payload({
        "line": {"key": key, "label": line["label"], "form": line["form"], "jurisdiction": line.get("jurisdiction")},
        "reported": {"filed_value": filed[key]["filed_value"], "original_filed_value": orig_value,
                     "basis": filed[key].get("basis", "engine"), "basis_note": F.BASIS_NOTE.get(filed[key].get("basis", "engine")),
                     "affected_by": filed[key].get("affected_by", []),
                     "engine_value": filed[key]["engine_value"], "snapshot_id": snap.id, "snapshot_sha256": snap.content_sha256},
        "calculation": {"rule": rule, "description": rules.get(rule) if rule else None, "engine_note": line.get("note"), "inputs": inputs},
        "evidence": evidence,
        "client_answers": answers,
        "adjustment_history": adjustments,
        "verifications": verifications,
        "judgments": judgments,
        "independent_checks": checks,
        "filed_result": {"filed_at": snap.filed_at, "accepted": accepted, "amendments": amendments,
                         "integrity": F.verify(snap)["valid"]},
        "excluded": EXCLUDED,
    })


@router.get("/examiner")
def examiner_overview(c: Ctx = Depends(require(Perm.VIEW_INTERNAL_NOTES))):
    snap = _snapshot(c)
    received = _received_notices(c)
    notices = []
    for n in c.idx.data["tax_agency_records"]["notices"]:
        if n.get("tax_year") != c.engagement.tax_year:
            continue
        items = [{"text": t, "lines": notice_lines(c.idx, t)} for t in n.get("items_under_examination", [])]
        resp = c.db.scalar(select(NoticeResponse).where(NoticeResponse.engagement_id == c.engagement.id, NoticeResponse.notice_id == n["id"])
                           .order_by(NoticeResponse.id.desc()).limit(1))
        notices.append({"id": n["id"], "agency": n["agency"], "type": n["type"], "dated": n["dated"],
                        "response_due": n.get("response_due"), "document": n.get("document"), "received_at": received.get(n["id"]),
                        "items": items, "response_id": resp.id if resp else None, "response_status": resp.status if resp else None})
    return mask_payload({"snapshot": {"id": snap.id, "kind": snap.kind, "number": snap.number, "filed_at": snap.filed_at,
                                      "content_sha256": snap.content_sha256, "integrity": F.verify(snap)["valid"]},
                         "clock": F.clock(c.db, c.idx, c.engagement.id), "notices": notices, "excluded": EXCLUDED,
                         "summary": snap.content["workpaper_summary"], "engine_summary": snap.content["engine_summary"],
                         "filed_summary": snap.content.get("filed_summary")})


@router.get("/examiner/item")
def examiner_item(line: str, c: Ctx = Depends(require(Perm.VIEW_INTERNAL_NOTES))):
    return examine(c, _snapshot(c), line)


# ---- notice response package ------------------------------------------------------------------------------

def _response_dict(r: NoticeResponse, names: dict[str, str]) -> dict:
    return mask_payload({"id": r.id, "notice_id": r.notice_id, "snapshot_id": r.snapshot_id, "items": r.items,
                         "cover_letter": r.cover_letter, "status": r.status, "prepared_by": names.get(r.prepared_by_id),
                         "prepared_by_id": r.prepared_by_id, "created_at": r.created_at, "approved_by": names.get(r.approved_by_id or ""),
                         "approved_at": r.approved_at, "content_sha256": r.content_sha256,
                         "history": [h | {"by_name": names.get(h.get("by"))} for h in r.history]})


def _notice(c: Ctx, notice_id: str) -> dict:
    n = next((x for x in c.idx.data["tax_agency_records"]["notices"] if x["id"] == notice_id), None)
    if n is None:
        raise HTTPException(404, f"No notice '{notice_id}'.")
    if notice_id not in _received_notices(c):
        raise HTTPException(409, f"{notice_id} has not been received yet (replay clock {F.clock(c.db, c.idx, c.engagement.id)}).")
    return n


def _entry(c: Ctx, action: str, note: str | None = None) -> dict:
    return {"action": action, "by": c.user.id, "role": c.user.role, "at": datetime.now(timezone.utc).isoformat(), "note": note}


@router.post("/notices/{notice_id}/response", status_code=201)
def build_response(notice_id: str, c: Ctx = Depends(require(Perm.CREATE_NOTE))):
    """Assemble the response from the evidence connected to each examined line of the filed return."""
    n = _notice(c, notice_id)
    snap = _snapshot(c)
    if c.db.scalar(select(NoticeResponse).where(NoticeResponse.engagement_id == c.engagement.id, NoticeResponse.notice_id == notice_id,
                                                NoticeResponse.status == "draft")):
        raise HTTPException(409, "A draft response already exists; edit it.")
    items = []
    for text in n.get("items_under_examination", []):
        lines = notice_lines(c.idx, text)
        exhibits: dict[str, dict] = {}
        detail = []
        for key in lines:
            ex = examine(c, snap, key)
            detail.append({"line": key, "label": ex["line"]["label"], "filed_value": ex["reported"]["filed_value"],
                           "engine_value": ex["reported"]["engine_value"], "adjustments": ex["adjustment_history"],
                           "judgments": ex["judgments"], "independent_checks": ex["independent_checks"]})
            for e in ex["evidence"]:
                if e["kind"] in ("Document", "Page", "ExtractedValue", "AgencyRecord", "PriorYearValue"):
                    exhibits.setdefault(e["ref"], {"ref": e["ref"], "kind": e["kind"], "label": e["label"], "value": e["value"], "lines": []})
                    exhibits[e["ref"]]["lines"].append(key)
            for q in ex["client_answers"]:
                exhibits.setdefault(q["ref"], {"ref": q["ref"], "kind": "ClientAnswer", "label": q["answer"], "value": None, "lines": [key]})
            for v in ex["verifications"]:
                exhibits.setdefault(f"verification:{v['id']}", {"ref": f"verification:{v['id']}", "kind": "Verification",
                                                                "label": f"{v['method'].replace('_', ' ')} by {v['by']}: {v['note'] or ''}",
                                                                "value": None, "lines": [key]})
        filed_list = "; ".join(f"{d['label']} ({d['line']}) {d['filed_value']:,.0f}" for d in detail if isinstance(d["filed_value"], (int, float)))
        recon = [f"{c_['title']}: " + ", ".join(f"{b['label']} {b['value']:,.0f}" for b in c_["breakdown"] if isinstance(b.get("value"), (int, float)))
                 for d in detail for c_ in d["independent_checks"] if c_["breakdown"]]
        explanation = (f"As filed: {filed_list}. " if filed_list else "") + \
            (f"Reconciliation: {' | '.join(recon)}. " if recon else "") + \
            f"{len(exhibits)} exhibits from the filed workpaper are attached."
        items.append({"text": text, "lines": lines, "detail": detail, "exhibits": sorted(exhibits.values(), key=lambda e: e["ref"]),
                      "explanation": explanation})
    cover = (f"Re: {n['type']} dated {n['dated']} — tax year {n['tax_year']}.\n\n"
             f"On behalf of our clients we respond to each item under examination below. Each answer cites the evidence "
             f"supporting the return as filed on {snap.filed_at[:10]} (filed snapshot {snap.content_sha256[:12]}…)."
             f"\n\nResponse due {n.get('response_due')}.")
    r = NoticeResponse(engagement_id=c.engagement.id, notice_id=notice_id, snapshot_id=snap.id, items=F.storable(mask_payload(items)),
                       cover_letter=mask_text(cover), status="draft", prepared_by_id=c.user.id, history=[_entry(c, "assemble")])
    c.db.add(r)
    c.db.flush()
    audit.record(c.db, c.engagement.id, "notice_response.assembled", actor_id=c.user.id, actor_role=c.user.role,
                 payload={"response_id": r.id, "notice_id": notice_id, "snapshot_id": snap.id,
                          "exhibits": sum(len(i["exhibits"]) for i in items)})
    c.db.commit()
    return _response_dict(r, _names(c))


@router.get("/notices/{notice_id}/response")
def get_response(notice_id: str, c: Ctx = Depends(require(Perm.VIEW_INTERNAL_NOTES))):
    r = c.db.scalar(select(NoticeResponse).where(NoticeResponse.engagement_id == c.engagement.id, NoticeResponse.notice_id == notice_id)
                    .order_by(NoticeResponse.id.desc()).limit(1))
    if r is None:
        raise HTTPException(404, "No response package yet.")
    return _response_dict(r, _names(c))


class ResponseEdit(BaseModel):
    cover_letter: str | None = Field(default=None, max_length=20000)
    explanations: dict[int, str] = Field(default_factory=dict)


def _load(c: Ctx, rid: int) -> NoticeResponse:
    r = c.db.get(NoticeResponse, rid)
    if r is None or r.engagement_id != c.engagement.id:
        raise HTTPException(404, "Response not found.")
    return r


@router.post("/notice-responses/{rid}/edit")
def edit_response(rid: int, body: ResponseEdit, c: Ctx = Depends(require(Perm.CREATE_NOTE))):
    r = _load(c, rid)
    if r.status != "draft":
        raise HTTPException(409, "The response is approved; it can no longer change.")
    items = [dict(i) for i in r.items]
    for i, text in body.explanations.items():
        if not 0 <= i < len(items):
            raise HTTPException(422, f"No item {i}.")
        items[i]["explanation"] = text.strip()
    r.items = F.storable(items)
    if body.cover_letter is not None:
        r.cover_letter = body.cover_letter.strip()
    r.history = list(r.history) + [_entry(c, "edit")]
    audit.record(c.db, c.engagement.id, "notice_response.edited", actor_id=c.user.id, actor_role=c.user.role, payload={"response_id": r.id})
    c.db.commit()
    return _response_dict(r, _names(c))


@router.post("/notice-responses/{rid}/approve")
def approve_response(rid: int, c: Ctx = Depends(require(Perm.CREATE_NOTE))):
    r = _load(c, rid)
    if c.user.role != "partner":
        raise HTTPException(403, "The response to an agency is approved by the partner.")
    contributors = {r.prepared_by_id} | {h.get("by") for h in r.history if h.get("action") in ("assemble", "edit")}
    if c.user.id in contributors:
        raise HTTPException(403, "You contributed to this response (assembled or edited it); someone independent must "
                                 "approve it. A person may not review or sign off on work they prepared.")
    if r.status != "draft":
        raise HTTPException(409, "Already approved.")
    r.status, r.approved_by_id, r.approved_at = "approved", c.user.id, datetime.now(timezone.utc)
    r.content_sha256 = F.canonical_hash({"items": r.items, "cover_letter": r.cover_letter, "snapshot_id": r.snapshot_id})
    r.history = list(r.history) + [_entry(c, "approve")]
    audit.record(c.db, c.engagement.id, "notice_response.approved", actor_id=c.user.id, actor_role=c.user.role,
                 payload={"response_id": r.id, "content_sha256": r.content_sha256})
    c.db.commit()
    return _response_dict(r, _names(c))
