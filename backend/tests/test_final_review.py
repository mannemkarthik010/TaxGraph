"""Follow-ups from the full review after Iteration 10."""

from app.models import FiledSnapshot
from app.services import ai as AI
from tests.filing_support import (CARD, MILEAGE, PARTNER, PREPARER, REVIEWER, act, decide_everything, get, post, replay,
                                  sign_everything)

FACTS = [
    AI.fact("F2", "The supplied engine has 11,800; TaxProof's independent value is 8,100 (sum of page totals excluding duplicate page 3).",
            ["line:v3:SchC.44a"]),
    AI.fact("M1", "D23 page 3 duplicates page 2: 3,700 miles counted twice in SchC.44a.", ["doc:D23#page3"]),
    AI.fact("N1", "D71 was not used by the return: it was received after v3 was computed.", ["D71"]),
]


def test_negated_and_swapped_claims_are_rejected():
    out = AI.validate([
        {"text": "The engine has 11,800 and TaxProof's independent value is 8,100.", "refs": ["line:v3:SchC.44a"]},     # ok
        {"text": "The engine has 8,100 while TaxProof's independent value is 11,800.", "refs": ["line:v3:SchC.44a"]},   # swapped
        {"text": "D23 page 3 does not duplicate page 2.", "refs": ["doc:D23#page3"]},                                  # negated
        {"text": "Page 3 is not a duplicate, so no miles are counted twice in SchC.44a.", "refs": ["doc:D23#page3"]},  # negated
        {"text": "D71 was used by the return.", "refs": ["D71"]},                                                       # drops the negation
        {"text": "D71 was not used by the return because it was received after v3.", "refs": ["D71"]},                 # ok
        {"text": "Page 3 duplicates page 2, so 3,700 miles are counted twice.", "refs": ["doc:D23#page3"]},             # ok
    ], FACTS)
    assert [c["status"] for c in out] == ["supported", "rejected", "rejected", "rejected", "rejected", "supported", "supported"]
    assert "engine" in " ".join(out[1]["problems"]) and "negat" in " ".join(out[2]["problems"]) and "negat" in " ".join(out[4]["problems"])


def test_the_dashboard_counts_every_critical_issue(client):
    high = [i for i in get(client, PARTNER, "/api/review/risk").json()["items"] if i["level"] == "high"]
    t = get(client, PARTNER, "/api/twin").json()
    assert len(high) > 8
    assert t["critical_count"] == len(high) and len(t["critical"]) <= 8


def _file(c):
    post(c, PREPARER, "/api/adjustments/from-finding", {"finding_id": MILEAGE, "apply": True})
    post(c, PREPARER, "/api/adjustments/from-finding", {"finding_id": CARD, "apply": True})
    decide_everything(c)
    sign_everything(c)
    act(c, PREPARER, "hand_off")
    act(c, PARTNER, "partner_approve")
    for _ in range(3):
        replay(c)
    act(c, REVIEWER, "ready_to_file")
    act(c, REVIEWER, "submit")
    replay(c), replay(c)
    act(c, REVIEWER, "resubmit", note="Theo's SSN corrected to his card (D71).", evidence_refs=["D71"])
    replay(c), replay(c)
    assert act(c, REVIEWER, "record_filed").json()["state"] == "filed"


def test_a_tampered_snapshot_turns_the_trust_report_red_and_blocks_amendments(client):
    _file(client)
    assert get(client, PARTNER, "/api/twin/trust").json()["verdict"].startswith("Filed and defended")
    with client.Session() as db:
        snap = db.query(FiledSnapshot).order_by(FiledSnapshot.id).first()
        original = dict(snap.content)
        snap.content = dict(original, return_version="v2")
        db.commit()
    try:
        t = get(client, PARTNER, "/api/twin/trust").json()
        filing = next(s for s in t["sections"] if s["key"] == "filing")
        assert filing["status"] == "bad" and "does not match" in filing["detail"]
        assert not t["verdict"].startswith("Filed and defended") and "integrity" in t["verdict"].lower()
        assert any(b["key"] == "snapshot_integrity" for b in t["what_prevents_filing"])
        d = get(client, PARTNER, "/api/twin").json()
        assert d["can_file_now"] is False and next(c for c in d["assurance"]["components"] if c["key"] == "blockers")["ratio"] == 0
        r = post(client, PREPARER, "/api/amendments", {"reason": "Advertising invoices found after filing."})
        assert r.status_code == 409 and "integrity" in r.json()["detail"]
    finally:
        with client.Session() as db:
            snap = db.query(FiledSnapshot).order_by(FiledSnapshot.id).first()
            snap.content = dict(original)
            db.commit()
    assert get(client, PARTNER, "/api/twin/trust").json()["verdict"].startswith("Filed and defended")


def test_an_amended_snapshot_must_come_from_an_intact_base(client):
    a = post(client, PREPARER, "/api/amendments", {"reason": "Advertising invoices found after filing."}).json()
    post(client, PREPARER, f"/api/amendments/{a['id']}/changes", {"line": "SchC.8", "amended_value": 2000, "reason": "invoices"})
    post(client, PARTNER, f"/api/amendments/{a['id']}/approve")
    with client.Session() as db:
        snap = db.query(FiledSnapshot).order_by(FiledSnapshot.id).first()
        original = dict(snap.content)
        snap.content = dict(original, return_version="v2")
        db.commit()
    try:
        r = post(client, REVIEWER, f"/api/amendments/{a['id']}/file")
        assert r.status_code == 409 and "integrity" in r.json()["detail"]
    finally:
        with client.Session() as db:
            snap = db.query(FiledSnapshot).order_by(FiledSnapshot.id).first()
            snap.content = dict(original)
            db.commit()
    assert post(client, REVIEWER, f"/api/amendments/{a['id']}/file").json()["status"] == "filed"


def test_one_amendment_cannot_change_a_line_and_a_line_computed_from_it(client):
    a = post(client, PREPARER, "/api/amendments", {"reason": "Mileage log re-examined after filing."}).json()
    assert post(client, PREPARER, f"/api/amendments/{a['id']}/changes", {"line": "SchC.44a", "amended_value": 7000, "reason": "log"}).status_code == 200
    r = post(client, PREPARER, f"/api/amendments/{a['id']}/changes", {"line": "SchC.9", "amended_value": 4900, "reason": "7,000 × 0.70"})
    assert r.status_code == 409 and "SchC.44a" in r.json()["detail"]
    b = post(client, PREPARER, f"/api/amendments/{a['id']}/withdraw").json()
    assert b["status"] == "withdrawn"
    a = post(client, PREPARER, "/api/amendments", {"reason": "Car expense re-examined after filing."}).json()
    post(client, PREPARER, f"/api/amendments/{a['id']}/changes", {"line": "SchC.9", "amended_value": 4900, "reason": "x 0.70"})
    r = post(client, PREPARER, f"/api/amendments/{a['id']}/changes", {"line": "SchC.44a", "amended_value": 7000, "reason": "log"})
    assert r.status_code == 409 and "SchC.9" in r.json()["detail"]
    # replacing the same line is still allowed
    assert post(client, PREPARER, f"/api/amendments/{a['id']}/changes", {"line": "SchC.9", "amended_value": 5000, "reason": "re-read"}).status_code == 200
