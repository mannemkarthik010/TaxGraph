"""Iteration 8: filing lifecycle, replay, filed snapshot, certificate, amendments, Examiner Mode, notice response.

Filing and freezing lock the workpaper, so this module runs against its own database (see filing_support).
"""

import re

import pytest

from app.models import FiledSnapshot
from tests.filing_support import (CARD, CLIENT, MILEAGE, PARTNER, PREPARER, QR, REVIEWER, act, decide_everything, get,  # noqa: F401
                                  isolated_client, post, replay, sign_everything, state)


@pytest.fixture(scope="module")
def fc():
    yield from isolated_client("filing_test")


def test_the_return_cannot_reach_the_partner_until_the_workpaper_is_ready(fc):
    s = state(fc)
    assert s["state"] == "preparing" and s["clock"] == "2026-06-23T06:05:00Z" and s["next_event"]["id"] == "tl-18"
    assert act(fc, PREPARER, "hand_off").status_code == 409                       # nothing prepared
    assert act(fc, PREPARER, "partner_approve").status_code == 403
    assert post(fc, PREPARER, "/api/amendments", {"reason": "nothing is filed yet"}).status_code == 409
    # the client approval cannot be replayed before the partner has approved
    replay(fc), replay(fc)                                                          # tl-18, tl-19: client messages
    r = replay(fc)
    assert r.status_code == 409 and "partner's approval" in r.json()["detail"]

    a1 = post(fc, PREPARER, "/api/adjustments/from-finding", {"finding_id": MILEAGE, "apply": True}).json()
    a2 = post(fc, PREPARER, "/api/adjustments/from-finding", {"finding_id": CARD, "apply": True}).json()
    assert a1["status"] == a2["status"] == "applied"
    decide_everything(fc)
    sign_everything(fc)
    assert act(fc, CLIENT, "hand_off").status_code == 403
    assert act(fc, PREPARER, "hand_off").status_code == 200
    # an open blocking review note stops the partner approval, and says why
    note = post(fc, REVIEWER, "/api/workpaper/notes", {"target_ref": "engagement", "kind": "review_note", "body": "Check the 8879 copy"}).json()
    r = act(fc, PARTNER, "partner_approve")
    assert r.status_code == 409 and [ch["key"] for ch in r.json()["detail"]["checks"]] == ["blocking_notes"]
    post(fc, REVIEWER, f"/api/workpaper/notes/{note['id']}/resolve", {"resolution": "Checked."})
    assert act(fc, REVIEWER, "partner_approve").status_code == 403
    s = act(fc, PARTNER, "partner_approve").json()
    assert s["state"] == "partner_approved" and s["approval"]["partner"] == s["approval"]["current"]


def test_the_client_approves_exactly_what_the_partner_approved(fc):
    extra = post(fc, PREPARER, "/api/adjustments", {"target_line": "SchC.8", "adjusted_value": 2000, "reason": "invoices", "apply": True}).json()
    r = replay(fc)
    assert r.status_code == 409 and "changed after the partner approved" in r.json()["detail"] and "SchC.8" in r.json()["detail"]
    post(fc, PREPARER, f"/api/adjustments/{extra['id']}/undo")
    s = replay(fc).json()                                                           # tl-20
    assert s["state"] == "client_approved" and s["approval"]["client_matches"]
    ev = s["history"][-1]
    assert ev["timeline_id"] == "tl-20" and "41207" not in ev["note"] and "88310" not in ev["note"]   # PINs masked
    # the SchC.8 apply/undo reopened sign-offs: ready-to-file waits for them
    r = act(fc, REVIEWER, "ready_to_file")
    assert r.status_code == 409 and "signoffs" in [ch["key"] for ch in r.json()["detail"]["checks"]]
    sign_everything(fc)
    assert act(fc, REVIEWER, "ready_to_file").json()["state"] == "ready_to_file"
    assert act(fc, PREPARER, "submit").status_code == 403
    s = act(fc, REVIEWER, "submit").json()
    assert s["state"] == "submitted"
    # while it is with the agencies, the return cannot change; collaboration can
    r = post(fc, PREPARER, "/api/adjustments", {"target_line": "SchC.17", "adjusted_value": 1600, "reason": "late invoice"})
    assert r.status_code == 409 and "Submitted" in r.json()["detail"]
    assert post(fc, PREPARER, "/api/signoffs", {"area_key": "business", "level": "prepared"}).status_code == 409
    assert post(fc, PREPARER, "/api/workpaper/notes", {"target_ref": "engagement", "body": "Submitted 7/13"}).status_code == 201


def test_rejection_correction_and_acceptance(fc):
    s = replay(fc).json()                                                           # tl-21
    assert s["state"] == "rejected"
    rej = s["history"][-1]["detail"]
    fed = next(x for x in rej["submissions"] if x["jurisdiction"] == "federal")
    assert fed["status"] == "rejected" and fed["errors"][0]["code"] == "R0000-504-02"
    assert any(f["id"].startswith("identity:theo") for f in rej["linked_findings"])    # TaxProof had flagged it before filing
    # the corrected evidence does not exist yet at the replay clock
    r = act(fc, REVIEWER, "resubmit", note="Theo's SSN corrected to the Social Security card.", evidence_refs=["D71"])
    assert r.status_code == 422 and "not been received" in r.json()["detail"]
    assert act(fc, REVIEWER, "resubmit", evidence_refs=["D71"]).status_code == 422          # no note
    replay(fc)                                                                       # tl-22: D71 + msg-10 arrive
    s = act(fc, REVIEWER, "resubmit", note="Theo's SSN corrected to the Social Security card (D71).", evidence_refs=["D71", "msg-10"]).json()
    assert s["state"] == "submitted"
    assert replay(fc).json()["state"] == "submitted"                                 # tl-23: federal accepted, California pending
    s = replay(fc).json()                                                            # tl-24
    assert s["state"] == "accepted" and {j: x["status"] for j, x in s["jurisdictions"].items()} == {"federal": "accepted", "california": "accepted"}
    r = replay(fc)                                                                   # tl-25 needs a filed return
    assert r.status_code == 409 and "filed return" in r.json()["detail"]


def test_filing_creates_an_immutable_snapshot_and_certificate(fc):
    s = act(fc, REVIEWER, "record_filed").json()
    assert s["state"] == "filed" and len(s["snapshots"]) == 1 and s["snapshots"][0]["integrity"]
    snap = get(fc, REVIEWER, f"/api/filing/snapshots/{s['snapshots'][0]['id']}").json()
    lines = {ln["key"]: ln for ln in snap["content"]["lines"]}
    assert lines["SchC.44a"]["filed_value"] == 8100 and lines["SchC.44a"]["engine_value"] == 11800
    assert lines["SchC.1"]["filed_value"] == 151300
    assert snap["filed_at"] == "2026-07-15T02:10:00Z"

    cert = get(fc, REVIEWER, "/api/filing/certificate").json()
    assert cert["return_version"] == "v3" and cert["integrity"]["valid"]
    assert {a["line"] for a in cert["effective_adjustments"]} == {"SchC.44a", "SchC.1"}
    assert {x["submission_id"] for x in cert["efile_submissions"]} == {"71530420261940012345", "71530420261940012346",
                                                                        "71530420261950019871", "71530420261950019872"}
    assert cert["accepted"] == {"federal": "2026-07-14T16:22:00Z", "california": "2026-07-15T02:10:00Z"}
    assert cert["client_approval"]["at"] == "2026-07-10T20:05:00Z" and "41207" not in str(cert)
    assert all(cert["signoffs"][lv]["complete"] for lv in ("prepared", "reviewed", "partner"))
    assert "D71" not in cert["documents_used"] and cert["documents_superseded"]
    assert isinstance(cert["unresolved_items"], list) and cert["accepted_with_explanation"]

    # post-filing: payment and refund come from the return as filed
    s = replay(fc).json()
    pay = s["history"][-1]["detail"]["amount"]["federal_balance_due_as_filed"]
    assert pay == cert["workpaper_summary"]["estimated"]["federal_balance_due"]
    s = replay(fc).json()
    assert s["history"][-1]["detail"]["amount"]["california_refund_as_filed"] > 0
    replay(fc), replay(fc)                                                           # tl-27 quality review, tl-28 next year

    # the filed return can no longer change; tampering with the stored snapshot is detected
    assert post(fc, PREPARER, "/api/judgments", {"topic": "Late judgment", "target_refs": ["line:v3:SchC.8"], "decision": "keep it", "decision_option": "keep_engine",
                                                  "alternatives": [{"option": "other"}], "rationale": "after filing?", "authority": "n/a"}).status_code == 409
    with fc.Session() as db:
        row = db.get(FiledSnapshot, cert["snapshot_id"])
        content = dict(row.content)
        content["return_version"] = "v2"
        row.content = content
        db.commit()
        assert get(fc, REVIEWER, f"/api/filing/snapshots/{row.id}").json()["integrity"]["valid"] is False
        row.content = dict(content, return_version="v3")      # a new object, so the change is written
        db.commit()
    assert get(fc, REVIEWER, f"/api/filing/snapshots/{cert['snapshot_id']}").json()["integrity"]["valid"] is True


def test_examiner_mode_and_the_2028_notice_response(fc):
    ov = get(fc, REVIEWER, "/api/examiner").json()
    l566 = next(n for n in ov["notices"] if n["id"] == "N-2025-L566")
    assert l566["received_at"] is None
    assert post(fc, PREPARER, "/api/notices/N-2025-L566/response").status_code == 409     # not received yet
    s = replay(fc).json()                                                                  # tl-29
    assert s["history"][-1]["detail"]["notices"][0]["id"] == "N-2025-L566"
    ov = get(fc, REVIEWER, "/api/examiner").json()
    l566 = next(n for n in ov["notices"] if n["id"] == "N-2025-L566")
    assert l566["received_at"] == "2028-01-26T15:00:00Z"
    charity, receipts = l566["items"]
    assert "SchA.12" in charity["lines"] and any(k.startswith("F8283") for k in charity["lines"])
    assert receipts["lines"] == ["SchC.1"]

    item = get(fc, REVIEWER, "/api/examiner/item?line=SchC.1").json()
    assert item["reported"]["filed_value"] == 151300 and item["reported"]["engine_value"] == 163700
    assert item["calculation"]["rule"] == "R-SCHC-GROSS" and item["calculation"]["description"]
    assert item["adjustment_history"][0]["original_value"] == 163700
    assert any(ch["id"] == CARD for ch in item["independent_checks"])
    assert any(e["ref"].startswith("ev-") for e in item["evidence"])
    assert "review notes" in " ".join(item["excluded"])
    assert "Dispositioned before partner approval" not in str(item) and "Check the 8879 copy" not in str(item)

    r = post(fc, PREPARER, "/api/notices/N-2025-L566/response")
    assert r.status_code == 201
    resp = r.json()
    assert len(resp["items"]) == 2 and all(i["exhibits"] for i in resp["items"])
    assert "151,300" in resp["items"][1]["explanation"] and "Reconciliation" in resp["items"][1]["explanation"]
    assert post(fc, PREPARER, "/api/notices/N-2025-L566/response").status_code == 409     # one draft at a time
    assert post(fc, PREPARER, f"/api/notice-responses/{resp['id']}/edit", {"explanations": {"0": "Acknowledgments attached."}}).status_code == 200
    assert post(fc, PREPARER, f"/api/notice-responses/{resp['id']}/approve").status_code == 403
    done = post(fc, PARTNER, f"/api/notice-responses/{resp['id']}/approve").json()
    assert done["status"] == "approved" and done["content_sha256"]
    assert post(fc, PREPARER, f"/api/notice-responses/{resp['id']}/edit", {"cover_letter": "changed"}).status_code == 409


def test_amendments_never_touch_the_filed_snapshot_and_freezing_locks_the_workpaper(fc):
    original = get(fc, REVIEWER, "/api/filing/snapshots").json()[0]
    a = post(fc, PREPARER, "/api/amendments", {"reason": "Vehicle sold at auction: deduction limited to gross proceeds."}).json()
    r = post(fc, PREPARER, f"/api/amendments/{a['id']}/changes", {"line": "F8283.A1.vehicle", "amended_value": 2100,
                                                                    "reason": "Form 1098-C gross proceeds", "evidence_refs": ["call-01"]})
    assert r.status_code == 200 and r.json()["changes"][0]["difference"] == -3900
    assert post(fc, PREPARER, f"/api/amendments/{a['id']}/changes", {"line": "SchA.14", "amended_value": 1, "reason": "x"}).status_code == 422
    assert post(fc, PREPARER, f"/api/amendments/{a['id']}/file").status_code == 403
    assert post(fc, REVIEWER, f"/api/amendments/{a['id']}/file").status_code == 409         # not approved
    assert post(fc, PREPARER, f"/api/amendments/{a['id']}/approve").status_code == 403
    assert post(fc, PARTNER, f"/api/amendments/{a['id']}/approve").json()["status"] == "approved"
    filed = post(fc, REVIEWER, f"/api/amendments/{a['id']}/file").json()
    assert filed["status"] == "filed" and filed["filed_snapshot_id"] != original["id"]
    snaps = get(fc, REVIEWER, "/api/filing/snapshots").json()
    assert snaps[0]["content_sha256"] == original["content_sha256"] and snaps[0]["integrity"]["valid"]
    assert snaps[1]["kind"] == "amendment" and snaps[1]["integrity"]["valid"]
    item = get(fc, REVIEWER, "/api/examiner/item?line=F8283.A1.vehicle").json()
    assert item["reported"]["filed_value"] == 2100 and item["reported"]["original_filed_value"] == 6000
    assert item["filed_result"]["amendments"][0]["number"] == 1

    assert act(fc, REVIEWER, "freeze").status_code == 403
    assert act(fc, PARTNER, "freeze").json()["state"] == "frozen"
    for path, body in (("/api/workpaper/notes", {"target_ref": "engagement", "body": "late note"}),
                       ("/api/verifications", {"target_ref": "line:v3:SchC.8", "method": "recalculated", "note": "late"}),
                       ("/api/client-questions", {"target_ref": "line:v3:SchC.8", "question": "One more question?"})):
        r = post(fc, PREPARER, path, body)
        assert r.status_code == 409 and "frozen" in r.json()["detail"], path
    assert post(fc, PREPARER, "/api/amendments", {"reason": "Second amendment is still possible."}).status_code == 201
    assert replay(fc).status_code == 409                                                  # the script is complete
    assert get(fc, PARTNER, "/api/audit/verify").json()["valid"] is True


def test_clients_see_the_lifecycle_but_no_internal_detail(fc):
    s = get(fc, CLIENT, "/api/filing/state").json()
    assert s["state"] == "frozen" and "actions" not in s and all("note" not in e for e in s["history"])
    assert get(fc, CLIENT, "/api/filing/certificate").status_code == 403
    assert get(fc, CLIENT, "/api/examiner").status_code == 403
    assert not re.search(r"\b\d{3}-\d{2}-\d{4}\b", get(fc, REVIEWER, "/api/filing/certificate").text)
