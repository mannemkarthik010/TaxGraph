"""Evidence Explorer: documents, simulated pages, extracted values, verifications, reverse tracing."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..deps import Ctx, ctx, require
from ..models import User, Verification
from ..packet.refs import resolve
from ..security.masking import is_sensitive_value, mask_extracted_value, mask_payload, mask_text
from ..security.roles import Perm
from ..services import audit, standards
from .collaboration import evidence_kind, reopen
from .locks import assert_not_frozen
from ..services.evidence import (
    document_statuses, get_analysis, locate, why_not_used, where_used,
)

router = APIRouter(prefix="/api")

METHOD_LABELS = {
    "agreed_to_source_document": "Agreed to source document",
    "recalculated": "Recalculated",
    "confirmed_with_client": "Confirmed with client",
    "agreed_to_prior_year": "Agreed to prior year",
    "agreed_to_agency_record": "Agreed to agency record",
    "agreed_to_third_party_record": "Agreed to third-party evidence",
}


# What each method may cite. "Confirmed with client" must rest on something the client said; "agreed to
# prior year" on the prior-year record, and so on. Methods without an entry accept any resolvable ref.
METHOD_EVIDENCE_KINDS: dict[str, set[str]] = {
    "confirmed_with_client": {"client_answer", "client_message", "call_note"},
    "agreed_to_prior_year": {"prior_year_value", "extracted_value", "document", "page"},
    "agreed_to_agency_record": {"agency_record"},
    "agreed_to_third_party_record": {"document", "page", "extracted_value"},
}
REQUIRES_EVIDENCE = {"confirmed_with_client", "agreed_to_prior_year", "agreed_to_agency_record"}


def verification_methods(c: Ctx) -> list[str]:
    """Firm standard verification types, plus agency-record agreement (IRS/FTB data is in the packet)."""
    return standards.verification_types(c.idx)  # firm standards (Iteration 9), incl. agency-record agreement


def _active_verifications(c: Ctx, refs: list[str] | None = None) -> dict[str, list[Verification]]:
    stmt = select(Verification).where(Verification.engagement_id == c.engagement.id, Verification.status == "active")
    if refs is not None:
        stmt = stmt.where(Verification.target_ref.in_(refs))
    out: dict[str, list[Verification]] = defaultdict(list)
    for v in c.db.scalars(stmt.order_by(Verification.verified_at)).all():
        out[v.target_ref].append(v)
    return out


def _names(c: Ctx) -> dict[str, str]:
    return {u.id: u.name for u in c.db.scalars(select(User)).all()}


def _verification_dict(v: Verification, names: dict[str, str]) -> dict:
    return mask_payload({
        "id": v.id, "target_ref": v.target_ref, "method": v.method, "method_label": METHOD_LABELS.get(v.method, v.method),
        "note": v.note, "evidence_refs": v.evidence_refs, "acknowledged_flags": v.acknowledged_flags,
        "verified_by_id": v.verified_by_id, "verified_by_name": names.get(v.verified_by_id),
        "verified_by_role": v.verified_by_role, "verified_at": v.verified_at, "status": v.status,
        "withdrawn_by_name": names.get(v.withdrawn_by_id or ""), "withdrawn_at": v.withdrawn_at,
        "withdrawn_reason": v.withdrawn_reason,
    })


def _value_view(c: Ctx, ev, masked_text: str | None, raw_text: str | None, verifs: dict, names: dict) -> dict:
    a = get_analysis(c.idx)
    shown = mask_extracted_value(ev) if is_sensitive_value(ev) else dict(ev)
    if masked_text is not None and masked_text == raw_text:
        span = a.value_spans.get(ev["id"])
    elif masked_text is not None:
        span = locate(masked_text, ev, shown["value"] if shown.get("masked") else None)
    else:
        span = None
    consumers = a.consumed_values.get(ev["id"], [])
    out = {
        **shown,
        "masked": bool(shown.get("masked")),
        "span": list(span) if span else None,
        "flags": [f.as_dict() for f in a.value_flags.get(ev["id"], ())],
        "used_in_versions": sorted({v for v, _ in consumers}),
        "line_count_current": sum(1 for v, _ in consumers if v == c.idx.current_version),
    }
    if c.can(Perm.VIEW_INTERNAL_NOTES):
        out["verifications"] = [_verification_dict(v, names) for v in verifs.get(ev["id"], [])]
    return out


@router.get("/documents")
def documents(c: Ctx = Depends(require(Perm.VIEW_EVIDENCE))):
    idx = c.idx
    a = get_analysis(idx)
    current = idx.versions_by_id[idx.current_version]
    verified = Counter()
    if c.can(Perm.VIEW_INTERNAL_NOTES):
        for ref in _active_verifications(c):
            ev = idx.values_by_id.get(ref)
            if ev:
                verified[ev["document_id"]] += 1
    out = []
    for doc in idx.data["documents"]:
        vals = idx.values_by_document.get(doc["id"], ())
        flags = [f for ev in vals for f in a.value_flags.get(ev["id"], ())]
        out.append({
            "id": doc["id"], "title": doc["title"], "document_type": doc["document_type"], "issuer": doc["issuer"],
            "belongs_to": doc["belongs_to"], "tax_year": doc["tax_year"], "received_at": doc["received_at"],
            "uploaded_by": doc["uploaded_by"], "page_count": doc["page_count"],
            "extraction_status": doc["extraction"]["status"], "extraction_reason": doc["extraction"].get("reason"),
            "marked_corrected": bool(doc.get("marked_corrected")), "value_count": len(vals),
            "used_in_current": doc["id"] in current["documents_used"],
            "superseded_in_current": doc["id"] in current["documents_superseded"],
            "used_in_versions": [v for v in idx.version_ids if doc["id"] in idx.versions_by_id[v]["documents_used"]],
            "statuses": document_statuses(idx, doc["id"]),
            "conflict_count": sum(1 for f in flags if f.severity == "conflict"),
            "review_count": sum(1 for f in flags if f.severity == "review"),
            "consumed_value_count": sum(1 for ev in vals if ev["id"] in a.consumed_values),
            "verified_value_count": verified.get(doc["id"], 0),
        })
    status_counts = Counter(s["code"] for d in out for s in d["statuses"])
    return {"version": idx.current_version, "counts": dict(status_counts), "documents": out}


@router.get("/documents/{doc_id}")
def document_detail(doc_id: str, c: Ctx = Depends(require(Perm.VIEW_EVIDENCE))):
    idx = c.idx
    doc = idx.documents_by_id.get(doc_id)
    if not doc:
        raise HTTPException(404, f"Unknown document '{doc_id}'.")
    a = get_analysis(idx)
    names = _names(c)
    vals = idx.values_by_document.get(doc_id, [])
    verifs = _active_verifications(c, [ev["id"] for ev in vals] + [doc_id]) if c.can(Perm.VIEW_INTERNAL_NOTES) else {}
    by_page: dict[int, list] = defaultdict(list)
    for ev in vals:
        by_page[ev["page"]].append(ev)
    pages = []
    for p in sorted(doc["pages"], key=lambda p: p["page"]):
        raw = p["printed_content"]
        masked = mask_text(raw)
        pages.append({
            "page": p["page"], "printed_content": masked, "extracted": bool(by_page.get(p["page"])),
            "values": [_value_view(c, ev, masked, raw, verifs, names) for ev in by_page.get(p["page"], [])],
        })

    # Document-level reverse trace: which current-version lines consume this document's values.
    lines_now: dict[str, dict] = {}
    for ev in vals:
        for vid, key in idx.lines_by_source.get(ev["id"], ()):
            if vid == idx.current_version:
                line = idx.line(vid, key)
                entry = lines_now.setdefault(key, {"key": key, "label": line["label"], "value": line["value"], "via": []})
                entry["via"].append(ev["id"])
    refs_elsewhere = [
        {"kind": "timeline", "id": t["id"], "label": t["event"], "at": t["at"]}
        for t in idx.data["timeline"] if doc_id in t["refs"]
    ]
    return {
        "id": doc_id, "title": doc["title"], "document_type": doc["document_type"], "issuer": doc["issuer"],
        "belongs_to": doc["belongs_to"], "tax_year": doc["tax_year"], "received_at": doc["received_at"],
        "uploaded_by": doc["uploaded_by"], "file_name": doc["file_name"], "page_count": doc["page_count"],
        "extraction": dict(doc["extraction"]), "marked_corrected": bool(doc.get("marked_corrected")),
        "renderer": "simulated_printed_content",  # a real page-image renderer would set "image" + per-page URLs
        "statuses": document_statuses(idx, doc_id),
        "relations": {
            "duplicates": a.duplicate_documents.get(doc_id, []),
            "corrections": a.corrected_pairs.get(doc_id, {}),
            "duplicate_pages": a.duplicate_pages.get(doc_id, []),
        },
        "used_in_versions": [v for v in idx.version_ids if doc_id in idx.versions_by_id[v]["documents_used"]],
        "why_not_used": None if doc_id in idx.versions_by_id[idx.current_version]["documents_used"]
        else why_not_used(idx, doc_id, idx.current_version),
        "where_used": {"version": idx.current_version, "lines": list(lines_now.values()), "references": refs_elsewhere},
        "pages": pages,
        "verifications": [_verification_dict(v, names) for v in verifs.get(doc_id, [])] if c.can(Perm.VIEW_INTERNAL_NOTES) else [],
    }


@router.get("/values/{ev_id}")
def value_detail(ev_id: str, c: Ctx = Depends(require(Perm.VIEW_EVIDENCE))):
    ev = c.idx.values_by_id.get(ev_id)
    if not ev:
        raise HTTPException(404, f"Unknown extracted value '{ev_id}'.")
    names = _names(c)
    verifs = _active_verifications(c, [ev_id]) if c.can(Perm.VIEW_INTERNAL_NOTES) else {}
    raw = next(p["printed_content"] for p in c.idx.documents_by_id[ev["document_id"]]["pages"] if p["page"] == ev["page"])
    view = _value_view(c, ev, mask_text(raw), raw, verifs, names)
    doc = c.idx.documents_by_id[ev["document_id"]]
    return {**view, "document_title": doc["title"], "where_used": where_used(c.idx, ev_id)}


# ---- verification workflow -------------------------------------------------------------------------

class VerificationCreate(BaseModel):
    target_ref: str = Field(min_length=1, max_length=120)
    method: str
    note: str | None = Field(default=None, max_length=5000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)


class Withdraw(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


@router.get("/verification-methods")
def methods(c: Ctx = Depends(ctx)):
    return [{"code": m, "label": METHOD_LABELS.get(m, m)} for m in verification_methods(c)]


@router.get("/verifications")
def list_verifications(target_ref: str | None = None, include_withdrawn: bool = False,
                       c: Ctx = Depends(require(Perm.VIEW_INTERNAL_NOTES))):
    stmt = select(Verification).where(Verification.engagement_id == c.engagement.id)
    if target_ref:
        stmt = stmt.where(Verification.target_ref == target_ref)
    if not include_withdrawn:
        stmt = stmt.where(Verification.status == "active")
    names = _names(c)
    return [_verification_dict(v, names) for v in c.db.scalars(stmt.order_by(Verification.verified_at.desc())).all()]


@router.post("/verifications", status_code=201)
def create_verification(body: VerificationCreate, c: Ctx = Depends(require(Perm.VERIFY))):
    assert_not_frozen(c, "recording verifications")
    if body.method not in verification_methods(c):
        raise HTTPException(422, f"Unknown verification method '{body.method}'.")
    target = resolve(c.idx, body.target_ref)
    if not target.exists or target.kind not in ("extracted_value", "return_line", "document", "page"):
        raise HTTPException(422, f"'{body.target_ref}' is not a verifiable value, line, document or page.")
    # Packet evidence, or workpaper evidence the firm accepted (an accepted client answer: client_answer:N).
    kinds = {ref: evidence_kind(c, ref) for ref in body.evidence_refs}
    # Each method must cite the kind of evidence its name claims (an empty list is checked below).
    allowed = METHOD_EVIDENCE_KINDS.get(body.method)
    wrong = [ref for ref, kind in kinds.items() if allowed and kind not in allowed]
    if wrong:
        raise HTTPException(422, f"'{METHOD_LABELS[body.method]}' cannot cite {', '.join(wrong)}: "
                                 f"expected {', '.join(sorted(allowed))}.")
    note = (body.note or "").strip() or None
    flags = [f.as_dict() for f in get_analysis(c.idx).value_flags.get(body.target_ref, ())]
    # A bare "agreed to source" tick is enough only for clean values. Everything else needs words, and
    # verifying over a deterministic flag means explicitly acknowledging it.
    if note is None and (body.method != "agreed_to_source_document" or flags):
        reason = "it carries open evidence flags" if flags else f"method '{body.method}' requires one"
        raise HTTPException(422, f"A note is required because {reason}.")
    if body.method in REQUIRES_EVIDENCE and not body.evidence_refs:
        raise HTTPException(422, f"'{METHOD_LABELS[body.method]}' must cite at least one reference "
                                 f"({', '.join(sorted(METHOD_EVIDENCE_KINDS[body.method]))}).")
    v = Verification(engagement_id=c.engagement.id, target_ref=body.target_ref, method=body.method, note=note,
                     evidence_refs=body.evidence_refs, acknowledged_flags=[f["code"] for f in flags],
                     verified_by_id=c.user.id, verified_by_role=c.user.role)
    c.db.add(v)
    c.db.flush()
    audit.record(c.db, c.engagement.id, "verification.created", actor_id=c.user.id, actor_role=c.user.role,
                 target_ref=body.target_ref, payload={"verification_id": v.id, "method": body.method,
                                                      "evidence_refs": body.evidence_refs,
                                                      "acknowledged_flags": v.acknowledged_flags})
    c.db.commit()
    return _verification_dict(v, _names(c))


@router.post("/verifications/{vid}/withdraw")
def withdraw_verification(vid: int, body: Withdraw, c: Ctx = Depends(require(Perm.VERIFY))):
    assert_not_frozen(c, "withdrawing verifications")
    v = c.db.get(Verification, vid)
    if v is None or v.engagement_id != c.engagement.id:
        raise HTTPException(404, "Verification not found.")
    if v.status != "active":
        raise HTTPException(409, "Verification already withdrawn.")
    if v.verified_by_id != c.user.id and not c.can(Perm.RESOLVE_REVIEW_NOTE):
        raise HTTPException(403, "Only the verifier or a reviewer can withdraw a verification.")
    v.status, v.withdrawn_by_id, v.withdrawn_at, v.withdrawn_reason = "withdrawn", c.user.id, datetime.now(timezone.utc), body.reason
    audit.record(c.db, c.engagement.id, "verification.withdrawn", actor_id=c.user.id, actor_role=c.user.role,
                 target_ref=v.target_ref, payload={"verification_id": v.id, "reason": body.reason})
    reopen(c, [v.target_ref], "verification.withdrawn",
           f"Verification #{v.id} ({v.method.replace('_', ' ')}) of {v.target_ref} withdrawn by {c.user.name}: {body.reason}",
           v.target_ref)
    c.db.commit()
    return _verification_dict(v, _names(c))
