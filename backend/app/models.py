"""Mutable workpaper layer.

These tables never copy packet values. They reference packet content with the packet's own reference
grammar (`ev-0226`, `D23`, `doc:D23#page2`, `line:v3:SchC.44a`, `household:theo.ssn`) in `target_ref`.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base

JSONType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Engagement(Base):
    __tablename__ = "engagements"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    client_id: Mapped[str] = mapped_column(String(40), index=True)
    name: Mapped[str] = mapped_column(String(200))
    tax_year: Mapped[int] = mapped_column(Integer)
    packet_sha256: Mapped[str] = mapped_column(String(64))
    packet_version: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(40), default="preparing")
    current_return_version: Mapped[str] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(20))  # staff | client
    credential: Mapped[str | None] = mapped_column(String(20), nullable=True)
    sensitive_data_clearance: Mapped[bool] = mapped_column(Boolean, default=False)
    active_from: Mapped[str | None] = mapped_column(String(10), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="packet")


class EngagementAssignment(Base):
    __tablename__ = "engagement_assignments"
    __table_args__ = (UniqueConstraint("engagement_id", "user_id", "role"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    engagement_id: Mapped[str] = mapped_column(ForeignKey("engagements.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(String(40))
    assigned_at: Mapped[str] = mapped_column(String(32))
    source: Mapped[str] = mapped_column(String(80))


class WorkpaperArea(Base):
    __tablename__ = "workpaper_areas"
    __table_args__ = (UniqueConstraint("engagement_id", "key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    engagement_id: Mapped[str] = mapped_column(ForeignKey("engagements.id"), index=True)
    key: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(80))
    sort_order: Mapped[int] = mapped_column(Integer)
    forms: Mapped[list] = mapped_column(JSONType, default=list)
    budget_key: Mapped[str | None] = mapped_column(String(60), nullable=True)
    preparer_status: Mapped[str] = mapped_column(String(20), default="not_started")
    reviewer_status: Mapped[str] = mapped_column(String(20), default="not_started")
    partner_status: Mapped[str] = mapped_column(String(20), default="not_started")


class WorkpaperNote(Base):
    __tablename__ = "workpaper_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    engagement_id: Mapped[str] = mapped_column(ForeignKey("engagements.id"), index=True)
    target_ref: Mapped[str] = mapped_column(String(120), index=True)
    area_key: Mapped[str | None] = mapped_column(String(40), nullable=True)
    kind: Mapped[str] = mapped_column(String(20))  # note | review_note
    body: Mapped[str] = mapped_column(Text)
    visibility: Mapped[str] = mapped_column(String(20), default="internal")  # internal | client
    blocking: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | resolved
    author_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    author_role: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)


class AuditEvent(Base):
    """Append-only, hash-chained. Rows are never updated or deleted by the application."""

    __tablename__ = "audit_events"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    engagement_id: Mapped[str] = mapped_column(ForeignKey("engagements.id"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    actor_id: Mapped[str | None] = mapped_column(String(20), nullable=True)
    actor_role: Mapped[str | None] = mapped_column(String(40), nullable=True)
    action: Mapped[str] = mapped_column(String(60), index=True)
    target_ref: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    payload: Mapped[dict] = mapped_column(JSONType, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), unique=True)


class AccessLog(Base):
    __tablename__ = "access_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    engagement_id: Mapped[str] = mapped_column(ForeignKey("engagements.id"), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    user_id: Mapped[str] = mapped_column(String(20))
    user_role: Mapped[str] = mapped_column(String(40))
    field_ref: Mapped[str] = mapped_column(String(120))
    granted: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class Verification(Base):
    """A person's record of how a packet item was checked. Never deleted; withdrawn instead."""

    __tablename__ = "verifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    engagement_id: Mapped[str] = mapped_column(ForeignKey("engagements.id"), index=True)
    target_ref: Mapped[str] = mapped_column(String(120), index=True)
    method: Mapped[str] = mapped_column(String(60))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_refs: Mapped[list] = mapped_column(JSONType, default=list)
    acknowledged_flags: Mapped[list] = mapped_column(JSONType, default=list)
    verified_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    verified_by_role: Mapped[str] = mapped_column(String(40))
    verified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | withdrawn
    withdrawn_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    withdrawn_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class EvidenceLink(Base):
    """A relationship a person asserted between two graph nodes (e.g. a client answer that confirms a
    value, a K-1 related to the S corporation basis record). Retired, never deleted."""

    __tablename__ = "evidence_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    engagement_id: Mapped[str] = mapped_column(ForeignKey("engagements.id"), index=True)
    src_ref: Mapped[str] = mapped_column(String(160), index=True)
    dst_ref: Mapped[str] = mapped_column(String(160), index=True)
    type: Mapped[str] = mapped_column(String(30))
    note: Mapped[str] = mapped_column(Text)
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_by_role: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | retired
    retired_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class ChallengeRun(Base):
    """A recorded run of the independent assurance engine against one return version.

    Findings are recomputable from the packet; the run records *when* someone looked and what they saw,
    so the next run can say what changed.
    """

    __tablename__ = "challenge_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    engagement_id: Mapped[str] = mapped_column(ForeignKey("engagements.id"), index=True)
    version: Mapped[str] = mapped_column(String(10))
    packet_sha256: Mapped[str] = mapped_column(String(64))
    run_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    run_by_role: Mapped[str] = mapped_column(String(40))
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    summary: Mapped[dict] = mapped_column(JSONType, default=dict)
    results: Mapped[list] = mapped_column(JSONType, default=list)  # [{id, status, severity, difference, federal, california}]


class Adjustment(Base):
    """A workpaper change to one return line. The engine's value is never overwritten: the effective
    workpaper value is the engine value plus the applied adjustment, and every step is in `history`."""

    __tablename__ = "adjustments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    engagement_id: Mapped[str] = mapped_column(ForeignKey("engagements.id"), index=True)
    version: Mapped[str] = mapped_column(String(10))
    target_line: Mapped[str] = mapped_column(String(60), index=True)
    original_value: Mapped[float] = mapped_column(Float)
    adjusted_value: Mapped[float] = mapped_column(Float)
    difference: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(12), default="USD")
    reason: Mapped[str] = mapped_column(Text)
    evidence_refs: Mapped[list] = mapped_column(JSONType, default=list)
    finding_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="proposed")  # proposed | applied | undone
    review_required: Mapped[str] = mapped_column(String(20))          # reviewer | partner
    effect: Mapped[dict] = mapped_column(JSONType, default=dict)       # estimated federal/California effect
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_by_role: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    approved_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    history: Mapped[list] = mapped_column(JSONType, default=list)      # [{action, by, role, at, note}]


class Issue(Base):
    """What people decided about one Uncertainty Inbox item.

    Inbox items are derived (review notes, Challenge findings, engine diagnostics, approvals, client
    questions); this row holds only the human state — assignment, escalation and disposition — keyed by
    the item's stable key (`finding:dup-page:D23#p3:SchC.44a`, `note:12`, `diag:FORM_1099_FILING`, …).
    """

    __tablename__ = "issues"
    __table_args__ = (UniqueConstraint("engagement_id", "item_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    engagement_id: Mapped[str] = mapped_column(ForeignKey("engagements.id"), index=True)
    item_key: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | resolved | accepted
    escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    escalated_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    escalated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    escalation_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    assignee_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolution_kind: Mapped[str | None] = mapped_column(String(30), nullable=True)  # resolved | accepted | client_answer
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    history: Mapped[list] = mapped_column(JSONType, default=list)  # [{action, by, role, at, note}]


class ClientQuestion(Base):
    """A question the firm asks the client. An accepted answer becomes evidence on the graph node it is
    about (a ClientAnswer node, CONFIRMED_BY), and can resolve the inbox item it came from."""

    __tablename__ = "client_questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    engagement_id: Mapped[str] = mapped_column(ForeignKey("engagements.id"), index=True)
    item_key: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    target_ref: Mapped[str] = mapped_column(String(160))
    question: Mapped[str] = mapped_column(Text)
    blocking: Mapped[bool] = mapped_column(Boolean, default=True)
    addressed_to_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="asked")  # asked | answered | accepted | withdrawn
    asked_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    asked_by_role: Mapped[str] = mapped_column(String(40))
    asked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    answered_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    accepted_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acceptance_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolves_item: Mapped[bool] = mapped_column(Boolean, default=False)
    history: Mapped[list] = mapped_column(JSONType, default=list)


class Judgment(Base):
    """A documented professional judgment. Never edited in place: a revision supersedes it."""

    __tablename__ = "judgments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    engagement_id: Mapped[str] = mapped_column(ForeignKey("engagements.id"), index=True)
    item_key: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    topic: Mapped[str] = mapped_column(String(300))
    target_refs: Mapped[list] = mapped_column(JSONType, default=list)
    area_keys: Mapped[list] = mapped_column(JSONType, default=list)
    decision: Mapped[str] = mapped_column(Text)
    decision_option: Mapped[str] = mapped_column(String(80))  # keep_engine | what_if:<id> | other
    alternatives: Mapped[list] = mapped_column(JSONType, default=list)  # [{option, description, federal, california, source}]
    rationale: Mapped[str] = mapped_column(Text)
    authority: Mapped[str] = mapped_column(Text)
    evidence_refs: Mapped[list] = mapped_column(JSONType, default=list)
    tax_effect: Mapped[dict] = mapped_column(JSONType, default=dict)
    review_required: Mapped[str] = mapped_column(String(20))  # reviewer | partner
    status: Mapped[str] = mapped_column(String(20), default="recorded")  # recorded | reviewed | approved | superseded
    prepared_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    prepared_by_role: Mapped[str] = mapped_column(String(40))
    prepared_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    reviewed_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    partner_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    partner_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    supersedes_id: Mapped[int | None] = mapped_column(ForeignKey("judgments.id"), nullable=True)
    history: Mapped[list] = mapped_column(JSONType, default=list)


class Signoff(Base):
    """A person's sign-off on one tax area at one level. Reopened, never deleted: a new sign-off is a
    new row, and `reopen_reasons` says exactly what changed underneath it."""

    __tablename__ = "signoffs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    engagement_id: Mapped[str] = mapped_column(ForeignKey("engagements.id"), index=True)
    area_key: Mapped[str] = mapped_column(String(40), index=True)
    level: Mapped[str] = mapped_column(String(20))  # prepared | reviewed | partner
    version: Mapped[str] = mapped_column(String(10))
    signed_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    signed_by_role: Mapped[str] = mapped_column(String(40))
    signed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    open_items_at_signing: Mapped[list] = mapped_column(JSONType, default=list)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | reopened
    reopened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reopen_reasons: Mapped[list] = mapped_column(JSONType, default=list)  # [{at, by, action, ref, detail}]


class FilingEvent(Base):
    """Append-only filing lifecycle log: firm actions and replayed agency/client events, in order.

    `at` is when it happened in the engagement's world (a scripted timeline time for replayed events, the
    replay clock for firm actions); `recorded_at` is when the row was written. The engagement's state is
    the `to_state` of the last transition.
    """

    __tablename__ = "filing_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    engagement_id: Mapped[str] = mapped_column(ForeignKey("engagements.id"), index=True)
    at: Mapped[str] = mapped_column(String(32))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    kind: Mapped[str] = mapped_column(String(20))  # action | replay
    action: Mapped[str] = mapped_column(String(60))  # hand_off, partner_approve, … or the timeline event name
    timeline_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    from_state: Mapped[str] = mapped_column(String(30))
    to_state: Mapped[str] = mapped_column(String(30))
    actor_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    actor_role: Mapped[str | None] = mapped_column(String(40), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    detail: Mapped[dict] = mapped_column(JSONType, default=dict)


class FiledSnapshot(Base):
    """The return exactly as filed (or as amended). Written once, never updated: `content_sha256` is the
    hash of `content`, also recorded in the audit chain, so any later edit is detectable."""

    __tablename__ = "filed_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    engagement_id: Mapped[str] = mapped_column(ForeignKey("engagements.id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))  # original | amendment
    number: Mapped[int] = mapped_column(Integer)  # 0 = original, 1.. = amendments
    base_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("filed_snapshots.id"), nullable=True)
    version: Mapped[str] = mapped_column(String(10))
    filed_at: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    content: Mapped[dict] = mapped_column(JSONType)
    content_sha256: Mapped[str] = mapped_column(String(64))


class Amendment(Base):
    """A change to a filed return. It never touches the filed snapshot: filing it creates a new snapshot."""

    __tablename__ = "amendments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    engagement_id: Mapped[str] = mapped_column(ForeignKey("engagements.id"), index=True)
    base_snapshot_id: Mapped[int] = mapped_column(ForeignKey("filed_snapshots.id"))
    reason: Mapped[str] = mapped_column(Text)
    changes: Mapped[list] = mapped_column(JSONType, default=list)  # [{line, filed_value, amended_value, difference, unit, effect, reason, evidence_refs}]
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | approved | filed | withdrawn
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_by_role: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    approved_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    filed_snapshot_id: Mapped[int | None] = mapped_column(ForeignKey("filed_snapshots.id"), nullable=True)
    history: Mapped[list] = mapped_column(JSONType, default=list)


class NoticeResponse(Base):
    """A response package to an agency notice, assembled from the evidence connected to the filed return."""

    __tablename__ = "notice_responses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    engagement_id: Mapped[str] = mapped_column(ForeignKey("engagements.id"), index=True)
    notice_id: Mapped[str] = mapped_column(String(40))
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("filed_snapshots.id"))
    items: Mapped[list] = mapped_column(JSONType, default=list)  # [{text, lines, explanation, exhibits: [...]}]
    cover_letter: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | approved
    prepared_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    approved_by_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    history: Mapped[list] = mapped_column(JSONType, default=list)


class AIRun(Base):
    """Every AI call: what it was given (masked), what it returned, and how each claim was validated.
    AI output is advisory and read-only: nothing here changes the workpaper."""

    __tablename__ = "ai_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    engagement_id: Mapped[str] = mapped_column(ForeignKey("engagements.id"), index=True)
    task: Mapped[str] = mapped_column(String(40))  # reviewer_brief | explain_finding | draft_question
    subject: Mapped[str | None] = mapped_column(String(200), nullable=True)
    provider: Mapped[str] = mapped_column(String(40))  # anthropic | grounded_template
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    context_sha256: Mapped[str] = mapped_column(String(64))
    context: Mapped[dict] = mapped_column(JSONType, default=dict)
    raw_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    claims: Mapped[list] = mapped_column(JSONType, default=list)
    supported: Mapped[int] = mapped_column(Integer, default=0)
    rejected: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class FirmStandards(Base):
    """A version of the firm's standards (the packet's starter standards are version 0). Never edited:
    each change is a new version, so what applied when is always reconstructable."""

    __tablename__ = "firm_standards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[int] = mapped_column(Integer, unique=True)
    content: Mapped[dict] = mapped_column(JSONType)
    note: Mapped[str] = mapped_column(Text)
    changed_by_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TimeEntry(Base):
    """Time a person spent on the engagement, against one of the firm's budget lines."""

    __tablename__ = "time_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    engagement_id: Mapped[str] = mapped_column(ForeignKey("engagements.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    budget_key: Mapped[str] = mapped_column(String(60))
    hours: Mapped[float] = mapped_column(Float)
    worked_on: Mapped[str] = mapped_column(String(10))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ViewMark(Base):
    """When a person last looked at a view — so the dashboard can say what changed since."""

    __tablename__ = "view_marks"
    __table_args__ = (UniqueConstraint("engagement_id", "user_id", "scope"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    engagement_id: Mapped[str] = mapped_column(ForeignKey("engagements.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    scope: Mapped[str] = mapped_column(String(40))
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    seen_seq: Mapped[int] = mapped_column(Integer, default=0)  # last audit event seen
