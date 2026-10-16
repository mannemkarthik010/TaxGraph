"""Role model and server-side permission matrix.

The role switcher selects an acting *user*; the user's role determines permissions. Identity matters
because several firm rules are about who did the work, not just what role they hold.
"""

from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    PREPARER = "preparer"
    REVIEWER = "reviewer"
    PARTNER = "partner"
    FIRM_ADMIN = "firm_administrator"
    CLIENT = "client"
    QUALITY_REVIEWER = "quality_reviewer"


class Perm(str, Enum):
    VIEW_RETURN = "view_return"
    VIEW_EVIDENCE = "view_evidence"
    VIEW_INTERNAL_NOTES = "view_internal_notes"
    CREATE_NOTE = "create_note"
    CREATE_REVIEW_NOTE = "create_review_note"
    RESOLVE_REVIEW_NOTE = "resolve_review_note"
    VIEW_AUDIT_LOG = "view_audit_log"
    VIEW_ACCESS_LOG = "view_access_log"
    VIEW_FIRM = "view_firm"
    VERIFY = "verify"
    ADJUST = "adjust"
    ASK_CLIENT = "ask_client"
    ANSWER_CLIENT_QUESTION = "answer_client_question"
    RECORD_JUDGMENT = "record_judgment"
    REVIEW_JUDGMENT = "review_judgment"
    SIGN_PREPARED = "sign_prepared"
    SIGN_REVIEWED = "sign_reviewed"
    SIGN_PARTNER = "sign_partner"
    MANAGE_FIRM = "manage_firm"


_STAFF_READ = {Perm.VIEW_RETURN, Perm.VIEW_EVIDENCE, Perm.VIEW_INTERNAL_NOTES, Perm.VIEW_FIRM}

MATRIX: dict[Role, frozenset[Perm]] = {
    Role.PREPARER: frozenset(_STAFF_READ | {Perm.CREATE_NOTE, Perm.VERIFY, Perm.ADJUST, Perm.ASK_CLIENT,
                                            Perm.RECORD_JUDGMENT, Perm.SIGN_PREPARED}),
    Role.REVIEWER: frozenset(
        _STAFF_READ | {Perm.CREATE_NOTE, Perm.CREATE_REVIEW_NOTE, Perm.RESOLVE_REVIEW_NOTE, Perm.VERIFY, Perm.ADJUST,
                       Perm.ASK_CLIENT, Perm.RECORD_JUDGMENT, Perm.REVIEW_JUDGMENT, Perm.SIGN_PREPARED, Perm.SIGN_REVIEWED}
    ),
    Role.PARTNER: frozenset(
        _STAFF_READ | {Perm.CREATE_NOTE, Perm.CREATE_REVIEW_NOTE, Perm.RESOLVE_REVIEW_NOTE, Perm.VIEW_AUDIT_LOG,
                       Perm.VERIFY, Perm.ADJUST, Perm.ASK_CLIENT, Perm.RECORD_JUDGMENT, Perm.REVIEW_JUDGMENT,
                       Perm.SIGN_PREPARED, Perm.SIGN_REVIEWED, Perm.SIGN_PARTNER}
    ),
    Role.QUALITY_REVIEWER: frozenset(
        _STAFF_READ | {Perm.CREATE_NOTE, Perm.CREATE_REVIEW_NOTE, Perm.RESOLVE_REVIEW_NOTE, Perm.VERIFY,
                       Perm.VIEW_AUDIT_LOG, Perm.VIEW_ACCESS_LOG}
    ),
    Role.FIRM_ADMIN: frozenset({Perm.VIEW_RETURN, Perm.VIEW_FIRM, Perm.MANAGE_FIRM, Perm.VIEW_AUDIT_LOG, Perm.VIEW_ACCESS_LOG}),
    # Clients see their own return and documents, never internal collaboration or firm settings.
    Role.CLIENT: frozenset({Perm.VIEW_RETURN, Perm.VIEW_EVIDENCE, Perm.ANSWER_CLIENT_QUESTION}),
}

ROLE_LABELS = {
    Role.PREPARER: "Preparer",
    Role.REVIEWER: "Reviewer",
    Role.PARTNER: "Partner",
    Role.FIRM_ADMIN: "Firm Administrator",
    Role.CLIENT: "Client",
    Role.QUALITY_REVIEWER: "Quality Reviewer",
}


class PermissionDenied(Exception):
    def __init__(self, message: str, perm: str | None = None):
        super().__init__(message)
        self.perm = perm


def permissions_for(role: str) -> frozenset[Perm]:
    try:
        return MATRIX[Role(role)]
    except ValueError:
        return frozenset()


def has_perm(role: str, perm: Perm) -> bool:
    return perm in permissions_for(role)


def can_reveal_sensitive(role: str, kind: str, cleared: bool) -> bool:
    """Firm rule: staff without sensitive-data clearance see SSNs, bank/account numbers and IP PINs masked.

    Cleared staff may reveal (each reveal is logged). Clients may reveal their own household's data.
    The firm administrator manages settings, not client data, and does not reveal.
    """
    if role == Role.CLIENT.value:
        return kind == "client"
    if role == Role.FIRM_ADMIN.value:
        return False
    return kind == "staff" and cleared


def assert_independent(actor_id: str, prepared_by_id: str | None, action: str = "review") -> None:
    """Firm rule: a person may not review or sign off on work they prepared."""
    if prepared_by_id is not None and actor_id == prepared_by_id:
        raise PermissionDenied(f"A person may not {action} work they prepared.", perm="independence")
