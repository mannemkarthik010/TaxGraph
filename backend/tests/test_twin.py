"""Iteration 10: Return Assurance Twin — dashboard, assurance score, trust report, what prevents filing, changes
since you looked. Runs on its own database so each state (preparing → decided → signed → filed) is exact."""

import re

import pytest

from app.services import twin as T
from tests.filing_support import (CARD, CLIENT, MILEAGE, PARTNER, PREPARER, REVIEWER, act, decide_everything, get,
                                  isolated_client, post, replay, sign_everything)

UNCLEARED = "st-04"
SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


@pytest.fixture(scope="module")
def tc():
    yield from isolated_client("twin_test")


def comps(d):
    return {c["key"]: c for c in d["assurance"]["components"]}


def test_weights_sum_to_100():
    assert sum(w for _, w in T.WEIGHTS.values()) == 100


def test_the_twin_starts_honest(tc):
    d = get(tc, PARTNER, "/api/twin").json()
    c = comps(d)
    assert d["assurance"]["score"] == round(sum(x["points"] for x in d["assurance"]["components"]))
    assert all(x["reason"] and x["link"] for x in c.values())
    assert d["documents"]["accounted"] == d["documents"]["total"] == 74                         # D71, D72: received after v3
    assert {r["id"] for r in d["documents"]["not_used"]} == {"D71", "D72"}
    assert d["traceability"]["traceable"] <= d["traceability"]["material"]
    assert c["review"]["ratio"] == 0 and c["partner"]["ratio"] == 0 and c["client"]["ratio"] == 0
    assert d["checks"]["passed"] + d["checks"]["failed"] + d["checks"]["attention"] <= d["checks"]["total"]
    prevent = {b["key"] for b in d["what_prevents_filing"]}
    assert {"open_items", "signoffs", "Partner approval", "E-file submission"} <= prevent
    assert d["engine"]["federal"]["total_tax"] == 81962 and d["filed"] is None
    assert d["since"]["first_visit"] is True
    assert get(tc, CLIENT, "/api/twin").status_code == 403 and get(tc, CLIENT, "/api/twin/trust").status_code == 403


def test_the_trust_report_answers_each_question_and_lists_exact_blockers(tc):
    t = get(tc, PARTNER, "/api/twin/trust").json()
    assert [s["key"] for s in t["sections"]] == ["documents", "traceability", "checks", "issues", "judgments", "review", "partner",
                                                 "client", "filing"]
    assert all(s["question"].endswith("?") and s["answer"] and s["status"] in ("good", "warn", "bad") for s in t["sections"])
    assert t["verdict"].startswith(f"{len(t['what_prevents_filing'])} thing(s) prevent filing")
    assert t["closing"].startswith("Traditional workpapers document what the preparer did.")
    again = get(tc, PARTNER, "/api/twin/trust").json()
    assert again["report_sha256"] == t["report_sha256"]                                        # same workpaper, same report
    events = get(tc, PARTNER, "/api/audit/events?limit=10").json()
    assert any(e["action"] == "twin.trust_report" and e["payload"]["report_sha256"] == t["report_sha256"] for e in events)
    s = post(tc, PARTNER, "/api/twin/trust/summary").json()
    assert s["rejected"] == 0 and s["supported"] >= 9 and all(c["refs"][0].startswith("twin:") for c in s["claims"])


def test_since_you_last_looked(tc):
    post(tc, PARTNER, "/api/twin/seen")
    assert get(tc, PARTNER, "/api/twin").json()["since"]["groups"] == []
    post(tc, REVIEWER, "/api/workpaper/notes", {"target_ref": "line:v3:SchC.8", "kind": "review_note", "body": "Support the advertising."})
    post(tc, PREPARER, "/api/adjustments/from-finding", {"finding_id": MILEAGE, "apply": True})
    post(tc, PARTNER, "/api/workpaper/notes", {"target_ref": "engagement", "body": "my own note"})          # own action: not news
    since = get(tc, PARTNER, "/api/twin").json()["since"]
    groups = {g["label"]: g["count"] for g in since["groups"]}
    assert groups.get("Review notes") == 1 and groups.get("Adjustments", 0) >= 2 and "Notes" not in groups
    assert all(e["by"] != "Helen Strand" for e in since["events"])
    post(tc, PARTNER, "/api/twin/seen")
    assert get(tc, PARTNER, "/api/twin").json()["since"]["groups"] == []


def test_the_score_rises_only_as_the_work_is_proven(tc):
    before = get(tc, PARTNER, "/api/twin").json()
    post(tc, PREPARER, "/api/adjustments/from-finding", {"finding_id": CARD, "apply": True})
    decide_everything(tc)
    mid = get(tc, PARTNER, "/api/twin").json()
    assert comps(mid)["checks"]["ratio"] == 1 and comps(mid)["blockers"]["ratio"] == 1 and comps(mid)["judgments"]["ratio"] == 1
    sign_everything(tc)
    signed = get(tc, PARTNER, "/api/twin").json()
    assert comps(signed)["review"]["ratio"] == comps(signed)["partner"]["ratio"] == 1
    assert signed["assurance"]["score"] > mid["assurance"]["score"] > before["assurance"]["score"]
    assert {b["kind"] for b in signed["what_prevents_filing"]} == {"lifecycle"}                 # only the steps ahead

    act(tc, PREPARER, "hand_off")
    act(tc, PARTNER, "partner_approve")
    for _ in range(3):
        replay(tc)                                                                            # … tl-20 client approval
    act(tc, REVIEWER, "ready_to_file")
    act(tc, REVIEWER, "submit")
    replay(tc)
    replay(tc)
    act(tc, REVIEWER, "resubmit", note="Theo's SSN corrected to his card (D71).", evidence_refs=["D71"])
    replay(tc)
    replay(tc)
    act(tc, REVIEWER, "record_filed")
    filed = get(tc, PARTNER, "/api/twin").json()
    assert filed["lifecycle"]["state"] == "filed" and filed["filed"]["integrity"] is True
    assert filed["what_prevents_filing"] == [] and comps(filed)["client"]["ratio"] == 1
    assert filed["assurance"]["score"] >= signed["assurance"]["score"]
    t = get(tc, PARTNER, "/api/twin/trust").json()
    assert t["verdict"].startswith("Filed and defended")
    assert next(s for s in t["sections"] if s["key"] == "filing")["status"] == "good"


def test_the_twin_never_shows_a_full_ssn(tc):
    post(tc, PREPARER, "/api/workpaper/notes", {"target_ref": "engagement", "body": "Organizer SSN 078-05-1120 was a typo"})
    for path in ("/api/twin", "/api/twin/trust"):
        assert not SSN.search(get(tc, UNCLEARED, path).text)
