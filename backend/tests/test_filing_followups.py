"""Review follow-ups after the Iteration 8 review (own isolated database)."""

import pytest

from app.packet import get_index
from app.services import filing as F
from tests.filing_support import (CARD, CLIENT, MILEAGE, PARTNER, PREPARER, REVIEWER, act, decide_everything, get,
                                  isolated_client, post, replay, sign_everything, state)

SUMMARY = {"F1040.24": ("federal_total_tax", 1), "F1040.37": ("federal_balance_due", 1),
           "F540NR.64": ("california_total_tax", 1), "F540NR.97": ("california_balance_due", -1)}


@pytest.fixture(scope="module")
def fc():
    yield from isolated_client("filing_followups")


def test_reopening_after_client_approval_has_a_way_forward(fc):
    """Client approval → reopen → partner approves again → the client approves again in TaxProof (the scripted
    approval is spent) → the season continues."""
    assert post(fc, PREPARER, "/api/adjustments/from-finding", {"finding_id": MILEAGE, "apply": True}).status_code == 201
    assert post(fc, PREPARER, "/api/adjustments/from-finding", {"finding_id": CARD, "apply": True}).status_code == 201
    decide_everything(fc)
    sign_everything(fc)
    act(fc, PREPARER, "hand_off")
    act(fc, PARTNER, "partner_approve")
    replay(fc), replay(fc)                                                         # tl-18, tl-19
    r = post(fc, CLIENT, "/api/filing/client-approval", {"confirm": True})
    assert r.status_code == 409 and "tl-20" in r.json()["detail"]                 # the scripted approval comes first
    assert replay(fc).json()["state"] == "client_approved"                          # tl-20
    assert act(fc, PARTNER, "reopen", note="The client asked to add a missed receipt.").json()["state"] == "preparing"
    assert act(fc, PREPARER, "hand_off").status_code == 200
    s = act(fc, PARTNER, "partner_approve").json()
    assert s["state"] == "partner_approved" and s["awaiting_client"] is True
    assert replay(fc).status_code == 409                                            # tl-21 needs a submission
    assert post(fc, PREPARER, "/api/filing/client-approval", {"confirm": True}).status_code == 403
    assert post(fc, CLIENT, "/api/filing/client-approval", {"confirm": False}).status_code == 422
    assert get(fc, CLIENT, "/api/filing/state").json()["client_can_approve"] is True
    s = post(fc, CLIENT, "/api/filing/client-approval", {"confirm": True}).json()
    assert s["state"] == "client_approved"
    ev = state(fc)["history"][-1]
    assert ev["kind"] == "client" and ev["actor"] == "Ngozi Okafor" and state(fc)["approval"]["client_matches"]
    act(fc, REVIEWER, "ready_to_file")
    act(fc, REVIEWER, "submit")
    assert replay(fc).json()["state"] == "rejected"                                 # tl-21: the season continues
    replay(fc)                                                                      # tl-22
    act(fc, REVIEWER, "resubmit", note="Theo's SSN corrected to the card (D71).", evidence_refs=["D71"])
    replay(fc), replay(fc)                                                          # tl-23, tl-24
    assert act(fc, REVIEWER, "record_filed").json()["state"] == "filed"


def _snapshot(fc, sid=None):
    sid = sid or get(fc, REVIEWER, "/api/filing/snapshots").json()[-1]["id"]
    return get(fc, REVIEWER, f"/api/filing/snapshots/{sid}").json()["content"]


def _assert_consistent(content):
    """No filed figure contradicts another: summary lines equal the filed summary, and every line that is an
    exact combination of its inputs equals that combination of their *filed* values."""
    lines = {ln["key"]: ln for ln in content["lines"]}
    est = content["workpaper_summary"]["estimated"]
    for key, (field, sign) in SUMMARY.items():
        assert lines[key]["filed_value"] == pytest.approx(sign * est[field], abs=1), key
    terms = F.linear_terms(get_index(), "v3")
    checked = 0
    for key, coefs in terms.items():
        ln = lines[key]
        if key in SUMMARY or ln["basis"] == "not_recomputed" or any(lines[i]["basis"] == "not_recomputed" for i, _ in coefs):
            continue
        total = sum((c or 0) * lines[i]["filed_value"] for i, c in coefs)
        assert ln["filed_value"] == pytest.approx(total, abs=1), (key, ln["filed_value"], total)
        checked += 1
    assert checked > 50
    return lines


def test_filed_lines_agree_with_the_filed_summary(fc):
    content = _snapshot(fc)
    lines = _assert_consistent(content)
    assert lines["SchC.44a"]["filed_value"] == 8100 and lines["SchC.44a"]["basis"] == "adjustment"
    assert lines["SchC.9"]["filed_value"] == 5670 and lines["SchC.9"]["basis"] == "derived"     # 8,100 × 0.70
    assert lines["SchC.1"]["filed_value"] == 151300
    assert lines["SchC.31"]["filed_value"] == lines["SchC.31"]["engine_value"] + 2590 - 12400
    assert lines["F1040.24"]["basis"] == "estimate_rates" and lines["F1040.24"]["filed_value"] != lines["F1040.24"]["engine_value"]
    # nothing affected by an adjustment is silently presented as the engine's figure
    affected = [ln for ln in lines.values() if ln.get("affected_by")]
    assert affected and all(ln["basis"] != "engine" for ln in affected)
    assert any(ln["basis"] == "not_recomputed" for ln in affected)
    item = get(fc, REVIEWER, "/api/examiner/item?line=SchC.9").json()
    assert item["reported"]["filed_value"] == 5670 and item["reported"]["basis"] == "derived"
    tax = get(fc, REVIEWER, "/api/examiner/item?line=F1040.24").json()["reported"]
    assert tax["filed_value"] == content["workpaper_summary"]["estimated"]["federal_total_tax"] and tax["basis"] == "estimate_rates"
    assert tax["basis_note"]


def test_nobody_approves_what_they_contributed_to(fc):
    a = post(fc, PREPARER, "/api/amendments", {"reason": "Advertising invoices found after filing."}).json()
    assert post(fc, PARTNER, f"/api/amendments/{a['id']}/changes", {"line": "SchC.8", "amended_value": 2000, "reason": "invoices"}).status_code == 200
    r = post(fc, PARTNER, f"/api/amendments/{a['id']}/approve")
    assert r.status_code == 403 and "contributed" in r.json()["detail"]
    post(fc, PREPARER, f"/api/amendments/{a['id']}/withdraw")

    for _ in range(5):                                                               # tl-25 … tl-29 (Letter 566)
        replay(fc)
    resp = post(fc, PREPARER, "/api/notices/N-2025-L566/response").json()
    assert post(fc, PARTNER, f"/api/notice-responses/{resp['id']}/edit", {"cover_letter": "Partner's wording."}).status_code == 200
    r = post(fc, PARTNER, f"/api/notice-responses/{resp['id']}/approve")
    assert r.status_code == 403 and "contributed" in r.json()["detail"]


def test_a_filed_amendment_moves_the_totals_too(fc):
    before = _snapshot(fc)
    a = post(fc, PREPARER, "/api/amendments", {"reason": "Advertising invoices found after filing."}).json()
    ch = post(fc, PREPARER, f"/api/amendments/{a['id']}/changes", {"line": "SchC.8", "amended_value": 2000, "reason": "invoices"}).json()
    eff = ch["changes"][0]["effect"]
    assert post(fc, PARTNER, f"/api/amendments/{a['id']}/approve").status_code == 200
    filed = post(fc, REVIEWER, f"/api/amendments/{a['id']}/file").json()
    after = _snapshot(fc, filed["filed_snapshot_id"])
    b, n = before["workpaper_summary"]["estimated"], after["workpaper_summary"]["estimated"]
    assert n["federal_total_tax"] == pytest.approx(b["federal_total_tax"] + eff["federal"], abs=1)
    assert n["california_total_tax"] == pytest.approx(b["california_total_tax"] + eff["california"], abs=1)
    assert n["federal_balance_due"] == pytest.approx(b["federal_balance_due"] + eff["federal"], abs=1)
    lines = _assert_consistent(after)
    assert lines["SchC.8"]["filed_value"] == 2000 and lines["SchC.8"]["basis"] == "amendment"
    assert lines["SchC.28"]["filed_value"] == {x["key"]: x for x in before["lines"]}["SchC.28"]["filed_value"] + (2000 - 2100)
    ov = get(fc, REVIEWER, "/api/examiner").json()
    assert ov["summary"]["estimated"]["federal_total_tax"] == n["federal_total_tax"]
    assert get(fc, REVIEWER, "/api/filing/snapshots").json()[0]["integrity"]["valid"]           # the original is untouched
