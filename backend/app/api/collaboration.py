"""Iteration 7 API: Uncertainty Inbox, client questions, Judgment Ledger, living sign-offs, filing readiness.

Every write is permission-checked here (server-side), audited in the hash chain, and — where it changes
what a sign-off attested to — reopens the affected reviewed/partner sign-offs with the reason.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..deps import Ctx, require
from ..models import ClientQuestion, Issue, Judgment, User, WorkpaperNote
from ..packet.refs import resolve
from ..security.masking import mask_payload, mask_text
from ..security.roles import Perm, permissions_for
from ..services import audit
from ..services import inbox as IB
from ..services import judgments as J
from ..services import signoffs as SO
from .locks import assert_not_frozen, assert_return_editable

router = APIRouter(prefix="/api")


def _names(c: Ctx) -> dict[str, str]:
    return {u.id: u.name for u in c.db.scalars(select(User)).all()}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _entry(c: Ctx, action: str, note: str | None = None, **extra) -> dict:
    return {"action": action, "by": c.user.id, "role": c.user.role, "at": _now().isoformat(), "note": note, **extra}


def reopen(c: Ctx, refs: list[str], action: str, detail: str, ref: str | None = None) -> list[dict]:
    """Reopen sign-offs affected by a change this request made (caller commits)."""
    return SO.reopen(c.db, c.idx, c.engagement.id, refs, actor_id=c.user.id, actor_name=c.user.name,
                     actor_role=c.user.role, action=action, detail=detail, ref=ref)


def _items(c: Ctx) -> list[IB.Item]:
    return IB.build(c.db, c.idx, c.engagement.id)


def _item(c: Ctx, key: str) -> IB.Item:
    item = next((i for i in _items(c) if i.key == key), None)
    if item is None:
        raise HTTPException(404, f"No inbox item '{key}'.")
    return item


def _issue(c: Ctx, key: str) -> Issue:
    issue = c.db.scalar(select(Issue).where(Issue.engagement_id == c.engagement.id, Issue.item_key == key))
    if issue is None:
        issue = Issue(engagement_id=c.engagement.id, item_key=key, status="open", history=[])
        c.db.add(issue)
        c.db.flush()
    return issue


def guard_escalation(c: Ctx, keys: list[str | None], doing: str) -> None:
    """An escalated, still-open item is the partner's to decide — whichever endpoint would handle it
    (an inbox action, an adjustment, a judgment, an accepted client answer, the notes endpoint, an approval)."""
    if c.user.role == "partner":
        return
    keys = [k for k in keys if k]
    if not keys:
        return
    hit = c.db.scalar(select(Issue).where(Issue.engagement_id == c.engagement.id, Issue.item_key.in_(keys),
                                          Issue.escalated.is_(True), Issue.status == "open"))
    if hit:
        raise HTTPException(403, f"'{hit.item_key}' was escalated to the partner ({hit.escalation_note}); "
                                 f"only the partner can {doing}.")


def evidence_kind(c: Ctx, ref: str) -> str:
    """Resolve an evidence reference: anything in the packet, or workpaper evidence the firm has accepted
    (`client_answer:N` — an accepted client answer). Returns its kind; 422 if it is not evidence (yet)."""
    if ref.startswith("client_answer:"):
        qid = ref.split(":", 1)[1]
        q = c.db.get(ClientQuestion, int(qid)) if qid.isdigit() else None
        if q is None or q.engagement_id != c.engagement.id:
            raise HTTPException(422, f"Evidence reference '{ref}' does not resolve.")
        if q.status != "accepted":
            raise HTTPException(422, f"Client answer #{q.id} has not been accepted as evidence yet (it is {q.status}).")
        return "client_answer"
    r = resolve(c.idx, ref)
    if not r.exists:
        raise HTTPException(422, f"Reference '{ref}' does not resolve to anything in the packet.")
    return r.kind


def _resolvable(c: Ctx, ref: str) -> str:
    evidence_kind(c, ref)
    return ref


# ---- Uncertainty Inbox ---------------------------------------------------------------------------------

@router.get("/inbox")
def get_inbox(include_handled: bool = False, mine: bool = False, c: Ctx = Depends(require(Perm.VIEW_INTERNAL_NOTES))):
    items = _items(c)
    names = _names(c)
    perms = permissions_for(c.user.role)
    shown = [i for i in items if (include_handled or i.status == "open") and (not mine or i.assignee_id == c.user.id)]
    groups = []
    for key, label in IB.GROUPS:
        rows = [IB.as_dict(i, names, IB.actions_for(i, perms, c.user.role)) for i in shown if i.group == key]
        groups.append({"key": key, "label": label, "open": sum(1 for r in rows if r["status"] == "open"), "items": rows})
    return {"version": c.idx.current_version, "groups": groups,
            "totals": {"open": sum(1 for i in items if i.status == "open"),
                       "blocking": sum(1 for i in items if i.status == "open" and i.blocks_filing),
                       "handled": sum(1 for i in items if i.status == "handled"),
                       "mine": sum(1 for i in items if i.status == "open" and i.assignee_id == c.user.id)}}


class InboxAction(BaseModel):
    key: str = Field(min_length=3, max_length=200)
    note: str | None = Field(default=None, max_length=5000)
    assignee_id: str | None = None


@router.post("/inbox/{action}")
def inbox_action(action: Literal["resolve", "accept", "assign", "escalate"], body: InboxAction,
                 c: Ctx = Depends(require(Perm.CREATE_NOTE))):
    assert_not_frozen(c, "the Uncertainty Inbox")
    item = _item(c, body.key)
    if item.status != "open":
        raise HTTPException(409, f"'{item.key}' is already handled ({(item.handled or {}).get('label')}).")
    if action not in IB.actions_for(item, permissions_for(c.user.role), c.user.role):
        if item.escalated and action in ("resolve", "accept"):
            raise HTTPException(403, "This item was escalated: the partner decides it.")
        if action == "accept":
            raise HTTPException(403, "Accepting an item as-is is a review decision (reviewer, partner or quality reviewer).")
        if action == "resolve" and item.source == "note":
            raise HTTPException(403, "Review notes are cleared by a reviewer, partner or quality reviewer.")
        raise HTTPException(403 if item.source in ("finding", "diagnostic", "note") else 409,
                            f"'{action}' is not available for this item ({item.source}).")
    note = (body.note or "").strip()
    issue = _issue(c, item.key)
    if action == "assign":
        who = c.db.get(User, body.assignee_id or "")
        if who is None or who.kind != "staff" or who.role not in ("preparer", "reviewer", "partner", "quality_reviewer"):
            raise HTTPException(422, "Assign to a preparer, reviewer, partner or quality reviewer.")
        issue.assignee_id = who.id
        issue.history = list(issue.history) + [_entry(c, "assign", note or None, assignee=who.id)]
    elif action == "escalate":
        if len(note) < 5:
            raise HTTPException(422, "Say why this needs the partner.")
        issue.escalated, issue.escalated_by_id, issue.escalated_at, issue.escalation_note = True, c.user.id, _now(), note
        issue.history = list(issue.history) + [_entry(c, "escalate", note)]
    else:
        minimum = 10 if action == "accept" else 3
        if len(note) < minimum:
            raise HTTPException(422, "Explain why the item is accepted as it stands (at least 10 characters)." if action == "accept"
                                else "Say how it was resolved.")
        if item.source == "note":
            n = c.db.get(WorkpaperNote, item.detail["note_id"])
            n.status, n.resolution, n.resolved_by_id, n.resolved_at = "resolved", note, c.user.id, _now()
            audit.record(c.db, c.engagement.id, "review_note.resolved", actor_id=c.user.id, actor_role=c.user.role,
                         target_ref=n.target_ref, payload={"note_id": n.id, "resolution": note, "via": "inbox"})
        issue.status = "accepted" if action == "accept" else "resolved"
        issue.resolution_kind, issue.resolution = issue.status, note
        issue.resolved_by_id, issue.resolved_at = c.user.id, _now()
        issue.history = list(issue.history) + [_entry(c, action, note)]
    audit.record(c.db, c.engagement.id, f"inbox.{action}", actor_id=c.user.id, actor_role=c.user.role, target_ref=item.refs[0] if item.refs else None,
                 payload={"item": item.key, "note": note or None, "assignee": issue.assignee_id})
    c.db.commit()
    names = _names(c)
    updated = _item(c, item.key)
    return IB.as_dict(updated, names, IB.actions_for(updated, permissions_for(c.user.role), c.user.role))


# ---- Client questions ----------------------------------------------------------------------------------

def _about(c: Ctx, ref: str) -> str:
    r = resolve(c.idx, ref)
    return mask_text(r.label or ref) if r.exists else ref


def _question_dict(c: Ctx, q: ClientQuestion, names: dict[str, str], internal: bool) -> dict:
    d = {"id": q.id, "question": mask_text(q.question), "status": q.status, "about": _about(c, q.target_ref),
         "asked_by": names.get(q.asked_by_id), "asked_at": q.asked_at, "addressed_to": names.get(q.addressed_to_id or ""),
         "addressed_to_id": q.addressed_to_id, "answer": mask_text(q.answer) if q.answer else None,
         "answered_by": names.get(q.answered_by_id or ""), "answered_at": q.answered_at}
    if internal:
        d |= {"target_ref": q.target_ref, "item_key": q.item_key, "blocking": q.blocking, "accepted_by": names.get(q.accepted_by_id or ""),
              "accepted_at": q.accepted_at, "acceptance_note": q.acceptance_note, "resolves_item": q.resolves_item,
              "history": [h | {"by_name": names.get(h.get("by"))} for h in q.history],
              "evidence_node": f"client_answer:{q.id}" if q.status == "accepted" else None}
    return mask_payload(d)


def _load_question(c: Ctx, qid: int) -> ClientQuestion:
    q = c.db.get(ClientQuestion, qid)
    if q is None or q.engagement_id != c.engagement.id:
        raise HTTPException(404, "Question not found.")
    return q


@router.get("/client-questions")
def list_questions(status: str | None = None, c: Ctx = Depends(require(Perm.VIEW_RETURN))):
    internal = c.can(Perm.VIEW_INTERNAL_NOTES)
    if not internal and not c.can(Perm.ANSWER_CLIENT_QUESTION):
        raise HTTPException(403, "Client questions are for the firm and the client.")
    stmt = select(ClientQuestion).where(ClientQuestion.engagement_id == c.engagement.id)
    if not internal:  # a client sees questions addressed to them (or to the household) that are still live or answered
        stmt = stmt.where((ClientQuestion.addressed_to_id.is_(None)) | (ClientQuestion.addressed_to_id == c.user.id),
                          ClientQuestion.status != "withdrawn")
    if status:
        stmt = stmt.where(ClientQuestion.status == status)
    names = _names(c)
    return [_question_dict(c, q, names, internal) for q in c.db.scalars(stmt.order_by(ClientQuestion.id.desc())).all()]


class QuestionCreate(BaseModel):
    question: str = Field(min_length=10, max_length=4000)
    target_ref: str | None = Field(default=None, max_length=160)
    item_key: str | None = Field(default=None, max_length=200)
    blocking: bool = True
    addressed_to_id: str | None = None


@router.post("/client-questions", status_code=201)
def ask(body: QuestionCreate, c: Ctx = Depends(require(Perm.ASK_CLIENT))):
    assert_not_frozen(c, "asking the client")
    target = body.target_ref
    if body.item_key:
        item = _item(c, body.item_key)
        if item.status != "open":
            raise HTTPException(409, f"'{item.key}' is already handled.")
        target = target or (item.refs[0] if item.refs else None)
    if not target:
        raise HTTPException(422, "Say what the question is about (a return line, document or value).")
    _resolvable(c, target)
    if body.addressed_to_id:
        who = c.db.get(User, body.addressed_to_id)
        if who is None or who.kind != "client":
            raise HTTPException(422, "Questions are addressed to a client user.")
    q = ClientQuestion(engagement_id=c.engagement.id, item_key=body.item_key, target_ref=target, question=body.question.strip(),
                       blocking=body.blocking, addressed_to_id=body.addressed_to_id, asked_by_id=c.user.id, asked_by_role=c.user.role,
                       history=[_entry(c, "ask")])
    c.db.add(q)
    c.db.flush()
    audit.record(c.db, c.engagement.id, "client_question.asked", actor_id=c.user.id, actor_role=c.user.role, target_ref=target,
                 payload={"question_id": q.id, "item": body.item_key, "blocking": body.blocking})
    c.db.commit()
    return _question_dict(c, q, _names(c), True)


class Answer(BaseModel):
    answer: str = Field(min_length=1, max_length=5000)


@router.post("/client-questions/{qid}/answer")
def answer(qid: int, body: Answer, c: Ctx = Depends(require(Perm.ANSWER_CLIENT_QUESTION))):
    assert_not_frozen(c, "answering a question")
    q = _load_question(c, qid)
    if c.user.kind != "client" or (q.addressed_to_id and q.addressed_to_id != c.user.id):
        raise HTTPException(403, "Only the client the question is addressed to can answer it.")
    if q.status not in ("asked", "answered"):
        raise HTTPException(409, f"This question is {q.status}.")
    q.answer, q.answered_by_id, q.answered_at, q.status = body.answer.strip(), c.user.id, _now(), "answered"
    q.history = list(q.history) + [_entry(c, "answer")]
    audit.record(c.db, c.engagement.id, "client_question.answered", actor_id=c.user.id, actor_role=c.user.role,
                 target_ref=q.target_ref, payload={"question_id": q.id})
    c.db.commit()
    return _question_dict(c, q, _names(c), False)


class Accept(BaseModel):
    note: str | None = Field(default=None, max_length=4000)
    resolves_item: bool = True


@router.post("/client-questions/{qid}/accept")
def accept_answer(qid: int, body: Accept, c: Ctx = Depends(require(Perm.ASK_CLIENT))):
    """The firm accepts the client's answer as evidence: it becomes a ClientAnswer node CONFIRMED_BY on the
    graph node it is about, can resolve the item it came from, and reopens sign-offs it affects."""
    assert_not_frozen(c, "accepting a client answer")
    q = _load_question(c, qid)
    guard_escalation(c, [f"question:{q.id}", q.item_key if body.resolves_item else None], "accept this answer")
    if q.status != "answered":
        raise HTTPException(409, "Only an answered question can be accepted." if q.status == "asked" else f"This question is {q.status}.")
    q.status, q.accepted_by_id, q.accepted_at = "accepted", c.user.id, _now()
    q.acceptance_note, q.resolves_item = (body.note or "").strip() or None, bool(body.resolves_item and q.item_key)
    q.history = list(q.history) + [_entry(c, "accept", q.acceptance_note)]
    if q.resolves_item:
        issue = _issue(c, q.item_key)
        if issue.status == "open":
            issue.status, issue.resolution_kind = "resolved", "client_answer"
            issue.resolution = f"Client answer (question #{q.id}): {q.answer}"[:4000]
            issue.resolved_by_id, issue.resolved_at = c.user.id, _now()
            issue.history = list(issue.history) + [_entry(c, "resolve", f"by client answer #{q.id}")]
    audit.record(c.db, c.engagement.id, "client_question.accepted", actor_id=c.user.id, actor_role=c.user.role,
                 target_ref=q.target_ref, payload={"question_id": q.id, "resolves_item": q.item_key if q.resolves_item else None,
                                                   "evidence_node": f"client_answer:{q.id}"})
    reopened = reopen(c, [q.target_ref], "client_answer.accepted",
                      f"Client answer #{q.id} accepted as evidence for {q.target_ref} by {c.user.name}.", q.target_ref)
    c.db.commit()
    return _question_dict(c, q, _names(c), True) | {"reopened_signoffs": mask_payload(reopened)}


class Withdraw(BaseModel):
    note: str = Field(min_length=3, max_length=2000)


@router.post("/client-questions/{qid}/withdraw")
def withdraw_question(qid: int, body: Withdraw, c: Ctx = Depends(require(Perm.ASK_CLIENT))):
    assert_not_frozen(c, "withdrawing a question")
    q = _load_question(c, qid)
    guard_escalation(c, [f"question:{q.id}"], "withdraw this question")
    if q.status not in ("asked", "answered"):
        raise HTTPException(409, f"This question is {q.status}.")
    q.status = "withdrawn"
    q.history = list(q.history) + [_entry(c, "withdraw", body.note)]
    audit.record(c.db, c.engagement.id, "client_question.withdrawn", actor_id=c.user.id, actor_role=c.user.role,
                 target_ref=q.target_ref, payload={"question_id": q.id, "note": body.note})
    c.db.commit()
    return _question_dict(c, q, _names(c), True)


# ---- Judgment Ledger -----------------------------------------------------------------------------------

def _judgment_dict(j: Judgment, names: dict[str, str]) -> dict:
    return mask_payload({"id": j.id, "item_key": j.item_key, "topic": mask_text(j.topic), "target_refs": j.target_refs, "areas": j.area_keys,
            "decision": mask_text(j.decision), "decision_option": j.decision_option, "alternatives": j.alternatives,
            "rationale": mask_text(j.rationale), "authority": j.authority, "evidence_refs": j.evidence_refs,
            "tax_effect": j.tax_effect, "review_required": j.review_required, "status": j.status,
            "prepared_by": names.get(j.prepared_by_id), "prepared_by_id": j.prepared_by_id, "prepared_by_role": j.prepared_by_role,
            "prepared_at": j.prepared_at, "reviewed_by": names.get(j.reviewed_by_id or ""), "reviewed_at": j.reviewed_at,
            "partner_by": names.get(j.partner_by_id or ""), "partner_at": j.partner_at, "supersedes_id": j.supersedes_id,
            "history": [h | {"by_name": names.get(h.get("by"))} for h in j.history]})


@router.get("/judgments")
def list_judgments(include_superseded: bool = False, c: Ctx = Depends(require(Perm.VIEW_INTERNAL_NOTES))):
    stmt = select(Judgment).where(Judgment.engagement_id == c.engagement.id)
    if not include_superseded:
        stmt = stmt.where(Judgment.status != "superseded")
    names = _names(c)
    return [_judgment_dict(j, names) for j in c.db.scalars(stmt.order_by(Judgment.id.desc())).all()]


@router.get("/judgments/options")
def judgment_options(item_key: str | None = None, c: Ctx = Depends(require(Perm.VIEW_INTERNAL_NOTES))):
    lines: list[str] = []
    suggestion = None
    if item_key:
        item = _item(c, item_key)
        lines = [r.split(":", 2)[2] for r in item.refs if r.startswith("line:")]
        suggestion = {"topic": mask_text(item.title), "target_refs": item.refs,
                      "evidence_refs": [r for r in item.detail.get("evidence", []) if resolve(c.idx, r).exists]}
    return {"options": J.options(c.idx, lines), "suggestion": suggestion}


class AlternativeIn(BaseModel):
    option: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=2000)
    why_not: str | None = Field(default=None, max_length=2000)


class JudgmentCreate(BaseModel):
    topic: str = Field(min_length=3, max_length=300)
    item_key: str | None = Field(default=None, max_length=200)
    target_refs: list[str] = Field(min_length=1, max_length=20)
    decision: str = Field(min_length=3, max_length=4000)
    decision_option: str = Field(min_length=1, max_length=80)
    alternatives: list[AlternativeIn] = Field(min_length=1, max_length=10)
    rationale: str = Field(min_length=10, max_length=8000)
    authority: str = Field(min_length=3, max_length=2000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=30)
    supersedes_id: int | None = None


@router.post("/judgments", status_code=201)
def record_judgment(body: JudgmentCreate, c: Ctx = Depends(require(Perm.RECORD_JUDGMENT))):
    if not body.authority.strip():
        raise HTTPException(422, "Every judgment call records the authority relied on (firm rule).")
    for ref in body.target_refs + body.evidence_refs:
        _resolvable(c, ref)
    assert_return_editable(c, "recording a judgment")
    guard_escalation(c, [body.item_key], "record a judgment that decides it")
    if body.item_key:
        item = _item(c, body.item_key)
        if item.status != "open" and not body.supersedes_id:
            raise HTTPException(409, f"'{item.key}' is already handled ({(item.handled or {}).get('label')}).")
    old = None
    if body.supersedes_id:
        old = c.db.get(Judgment, body.supersedes_id)
        if old is None or old.engagement_id != c.engagement.id:
            raise HTTPException(404, "The judgment to revise was not found.")
        if old.status == "superseded":
            raise HTTPException(409, f"Judgment #{old.id} was already revised.")
    try:
        effect, alts, required = J.prepare(c.idx, decision_option=body.decision_option,
                                           alternatives=[a.model_dump() for a in body.alternatives])
    except J.JudgmentError as e:
        raise HTTPException(e.status, str(e))
    areas = sorted(SO.areas_touched(c.idx, body.target_refs))
    j = Judgment(engagement_id=c.engagement.id, item_key=body.item_key or (old.item_key if old else None), topic=body.topic.strip(),
                 target_refs=body.target_refs, area_keys=areas, decision=body.decision.strip(), decision_option=body.decision_option,
                 alternatives=alts, rationale=body.rationale.strip(), authority=body.authority.strip(),
                 evidence_refs=body.evidence_refs, tax_effect=effect, review_required=required, status="recorded",
                 prepared_by_id=c.user.id, prepared_by_role=c.user.role, supersedes_id=old.id if old else None,
                 history=[_entry(c, "record")])
    c.db.add(j)
    c.db.flush()
    if old:
        old.status = "superseded"
        old.history = list(old.history) + [_entry(c, "superseded", f"revised by judgment #{j.id}")]
    audit.record(c.db, c.engagement.id, "judgment.recorded", actor_id=c.user.id, actor_role=c.user.role, target_ref=body.target_refs[0],
                 payload={"judgment_id": j.id, "item": j.item_key, "decision_option": j.decision_option, "effect": effect,
                          "review_required": required, "supersedes": old.id if old else None})
    # A revision changes what the old judgment supported too: reopen the areas of both (old ∪ new targets).
    touched = list(dict.fromkeys(body.target_refs + (list(old.target_refs) if old else [])))
    reopened = reopen(c, touched, "judgment.recorded" if not old else "judgment.revised",
                      f"Judgment #{j.id} {'revising #' + str(old.id) + ' ' if old else ''}recorded by {c.user.name}: {j.topic}",
                      body.target_refs[0])
    c.db.commit()
    return _judgment_dict(j, _names(c)) | {"reopened_signoffs": mask_payload(reopened)}


class ReviewIn(BaseModel):
    note: str | None = Field(default=None, max_length=4000)


@router.post("/judgments/{jid}/review")
def review_judgment(jid: int, body: ReviewIn, c: Ctx = Depends(require(Perm.REVIEW_JUDGMENT))):
    j = c.db.get(Judgment, jid)
    if j is None or j.engagement_id != c.engagement.id:
        raise HTTPException(404, "Judgment not found.")
    if j.prepared_by_id == c.user.id:
        raise HTTPException(403, "A person may not review or sign off on work they prepared.")
    assert_return_editable(c, "reviewing a judgment")
    guard_escalation(c, [f"judgment:{j.id}"], "review this judgment")
    try:
        nxt = J.next_status(j.status, j.review_required)
    except J.JudgmentError as e:
        raise HTTPException(e.status, str(e))
    if j.status == "reviewed":  # the partner step
        if c.user.role != "partner":
            raise HTTPException(403, f"Judgment #{j.id} has more tax at stake than the firm's partner threshold: partner approval required.")
        j.partner_by_id, j.partner_at = c.user.id, _now()
    else:
        j.reviewed_by_id, j.reviewed_at = c.user.id, _now()
    j.status = nxt
    j.history = list(j.history) + [_entry(c, "review" if nxt == "reviewed" else "approve", body.note)]
    audit.record(c.db, c.engagement.id, f"judgment.{'reviewed' if nxt == 'reviewed' else 'approved'}", actor_id=c.user.id,
                 actor_role=c.user.role, target_ref=j.target_refs[0] if j.target_refs else None,
                 payload={"judgment_id": j.id, "status": nxt, "note": body.note})
    c.db.commit()
    return _judgment_dict(j, _names(c))


# ---- Sign-offs and filing readiness ----------------------------------------------------------------------

def _board(c: Ctx, items: list[IB.Item] | None = None) -> list[dict]:
    items = items if items is not None else _items(c)
    return mask_payload(SO.board(c.db, c.idx, c.engagement.id, _names(c), c.user.id, c.user.role, IB.open_by_area(items)))


@router.get("/signoffs")
def signoff_board(c: Ctx = Depends(require(Perm.VIEW_INTERNAL_NOTES))):
    return {"version": c.idx.current_version, "areas": _board(c)}


class SignIn(BaseModel):
    area_key: str = Field(min_length=1, max_length=40)
    level: Literal["prepared", "reviewed", "partner"]
    note: str | None = Field(default=None, max_length=2000)


@router.post("/signoffs", status_code=201)
def sign(body: SignIn, c: Ctx = Depends(require(Perm.SIGN_PREPARED))):
    assert_return_editable(c, "signing off")
    items = _items(c)
    open_items = IB.open_by_area(items).get(body.area_key, [])
    try:
        SO.sign(c.db, c.idx, c.engagement.id, body.area_key, body.level, user_id=c.user.id, user_role=c.user.role,
                note=(body.note or "").strip() or None, open_items=open_items)
    except SO.SignoffError as e:
        raise HTTPException(e.status, str(e))
    c.db.commit()
    return next(a for a in _board(c, items) if a["key"] == body.area_key)


@router.get("/filing/readiness")
def filing_readiness(c: Ctx = Depends(require(Perm.VIEW_INTERNAL_NOTES))):
    items = _items(c)
    return mask_payload(IB.readiness(items, _board(c, items)))


def assert_can_file(c: Ctx) -> None:
    """The gate every filing transition calls (Iteration 8): refuses while anything blocks filing."""
    items = _items(c)
    r = IB.readiness(items, _board(c, items))
    if not r["can_file"]:
        raise HTTPException(409, {"message": "Filing is blocked.", "checks": [ch for ch in r["checks"] if not ch["ok"]]})

