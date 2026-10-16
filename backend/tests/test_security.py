import pytest

from app.security.masking import mask_extracted_value, mask_household, mask_ssn, mask_tail, mask_text
from app.security.roles import (
    MATRIX, Perm, PermissionDenied, Role, assert_independent, can_reveal_sensitive, has_perm,
)


# ---- masking ---------------------------------------------------------------------------------------

def test_mask_ssn_keeps_last_four():
    assert mask_ssn("666-41-2287") == "•••-••-2287"


def test_mask_tail():
    assert mask_tail("4483019276") == "••••9276"


def test_household_masking_hides_every_sensitive_field(idx):
    m = mask_household(idx.data["household"])
    blob = repr(m)
    for p in idx.data["household"]["people"]:
        assert p["ssn"] not in blob
        if p.get("ip_pin"):
            assert p["ip_pin"] not in blob
    bank = idx.data["household"]["bank_account_for_refund_or_payment"]
    assert bank["account"] not in blob and bank["routing"] not in blob
    # the source packet itself is untouched
    assert idx.people_by_id["ngozi"]["ssn"] == "666-41-2287"


def test_printed_content_masking(idx):
    w2 = idx.documents_by_id["D08"]["pages"][0]["printed_content"]
    assert "666-41-2287" not in mask_text(w2)
    assert "•••-••-2287" in mask_text(w2)
    swedish = idx.documents_by_id["D36"]["pages"][0]["printed_content"]
    assert "SE45 8000 0000 0412 7783 9901" not in mask_text(swedish)
    ip_pin = idx.documents_by_id["D03"]["pages"][0]["printed_content"]
    assert "482915" not in mask_text(ip_pin)
    assert "2026" in mask_text(ip_pin)  # years are not PINs
    tax_bill = idx.documents_by_id["D58"]["pages"][0]["printed_content"]
    assert "0418-2290-07" not in mask_text(tax_bill)


def test_signature_pins_in_timeline_are_masked(idx):
    detail = idx.timeline_by_id["tl-20"]["detail"]
    masked = mask_text(detail)
    assert "41207" not in masked and "88310" not in masked


def test_dollar_amounts_and_eins_are_not_masked():
    text = "EIN 82-4471903. Box 1 104,600.00; Total levy 13,420.00"
    assert mask_text(text) == text


def test_sensitive_extracted_values_are_masked(idx):
    ev = mask_extracted_value(idx.values_by_id["ev-0012"])
    assert ev["masked"] and "3390" in ev["value"] and "666-74" not in ev["value"]
    iban = mask_extracted_value(idx.values_by_id["ev-0963"])
    assert iban["value"].endswith("9901") and "SE45" not in iban["value"]
    plain = mask_extracted_value(idx.values_by_id["ev-0315"])
    assert plain["value"] == 3700 and "masked" not in plain


# ---- roles -----------------------------------------------------------------------------------------

def test_every_role_has_a_permission_set():
    assert set(MATRIX) == set(Role)


def test_client_cannot_see_internal_collaboration_or_firm():
    for p in (Perm.VIEW_INTERNAL_NOTES, Perm.CREATE_NOTE, Perm.VIEW_FIRM, Perm.VIEW_AUDIT_LOG):
        assert not has_perm("client", p)


def test_only_reviewers_and_above_raise_review_notes():
    assert not has_perm("preparer", Perm.CREATE_REVIEW_NOTE)
    for r in ("reviewer", "partner", "quality_reviewer"):
        assert has_perm(r, Perm.CREATE_REVIEW_NOTE)
    assert not has_perm("firm_administrator", Perm.CREATE_NOTE)


def test_unknown_role_has_no_permissions():
    assert not has_perm("intern", Perm.VIEW_RETURN)


def test_sensitive_reveal_rules():
    assert can_reveal_sensitive("reviewer", "staff", True)
    assert not can_reveal_sensitive("preparer", "staff", False)  # Marcus Bell
    assert not can_reveal_sensitive("firm_administrator", "staff", True)
    assert can_reveal_sensitive("client", "client", False)


def test_preparer_cannot_review_own_work():
    with pytest.raises(PermissionDenied):
        assert_independent("st-01", "st-01")
    assert_independent("st-02", "st-01")  # does not raise
