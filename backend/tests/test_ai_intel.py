"""Iteration 9: grounded AI reviewer, Review Risk Score, search, firm standards, budget vs actual."""

import json
import re

import pytest

from app.services import ai as AI
from app.services import standards
from tests.conftest import as_user

PREPARER, UNCLEARED, REVIEWER, PARTNER, ADMIN, QR, CLIENT = "st-01", "st-04", "st-02", "st-03", "st-05", "st-06", "cu-01"
SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


def post(client, user, path, body=None):
    return client.post(path, headers=as_user(user), json=body or {})


def get(client, user, path, **params):
    return client.get(path, headers=as_user(user), params=params)


# ---- the validator ---------------------------------------------------------------------------------------

FACTS = [AI.fact("F1", "D23 page 3 duplicates page 2: 3,700 miles counted twice; engine 11,800, independent 8,100.",
                 ["doc:D23#page2", "doc:D23#page3"]),
         AI.fact("F2", "Paywell 1099-K 12,400 already inside books revenue 151,300.", ["D21", "ev-0103"])]


def test_grounded_claims_pass_and_ungrounded_claims_are_rejected():
    out = AI.validate([
        {"text": "Mileage on D23 counts 3,700 miles twice (11,800 vs 8,100).", "refs": ["doc:D23#page3"]},
        {"text": "The 12,400 is already in books.", "refs": ["D21"]},
        {"text": "Mileage is overstated.", "refs": []},                                  # no evidence
        {"text": "See D99 for the missing 2,000.", "refs": ["D99"]},                     # evidence it was not given
        {"text": "Mileage is overstated by 4,100 miles.", "refs": ["doc:D23#page3"]},    # invented number
        {"text": "I have adjusted SchC.44a to 8,100.", "refs": ["doc:D23#page3"]},       # claims an action
        {"text": "Revenue 151,300 is right.", "refs": ["doc:D23#page2"]},                # number belongs to other evidence
    ], FACTS)
    status = [c["status"] for c in out]
    assert status == ["supported", "supported", "rejected", "rejected", "rejected", "rejected", "rejected"]
    reasons = [" ".join(c["problems"]) for c in out]
    assert "cites no evidence" in reasons[2] and "not given" in reasons[3] and "4,100" in reasons[4]
    assert "action" in reasons[5] and "151,300" in reasons[6]
    masked = AI.validate([{"text": "Theo's SSN is 666-74-3390.", "refs": ["D21"]}], FACTS)[0]
    assert not SSN.search(masked["text"])


class Hallucinating(AI.Provider):
    name, model = "anthropic", "test-model"

    def complete(self, task, facts):
        claims = [{"text": facts[0].text, "refs": facts[0].refs},
                  {"text": "Erik's crypto basis is 9,999 per D74.", "refs": ["D74"]},
                  {"text": "We resolved the mileage finding.", "refs": facts[0].refs}]
        return json.dumps({"claims": claims}), claims


class Broken(AI.Provider):
    name, model = "anthropic", "test-model"

    def complete(self, task, facts):
        raise RuntimeError("quota")


def test_the_brief_keeps_only_grounded_claims_and_changes_nothing(client, monkeypatch):
    before_adj = len(get(client, PARTNER, "/api/adjustments").json()["adjustments"])
    before_notes = len(get(client, PARTNER, "/api/workpaper/notes").json())
    monkeypatch.setattr(AI, "provider", lambda: Hallucinating())
    b = post(client, REVIEWER, "/api/ai/brief").json()
    assert b["is_ai"] and b["supported"] == 1 and b["rejected"] == 2
    rejected = [c for c in b["claims"] if c["status"] == "rejected"]
    assert any("not given" in " ".join(c["problems"]) for c in rejected)
    assert any("action" in " ".join(c["problems"]) for c in rejected)
    # read-only: nothing in the workpaper moved; the run itself is logged and audited
    assert len(get(client, PARTNER, "/api/adjustments").json()["adjustments"]) == before_adj
    assert len(get(client, PARTNER, "/api/workpaper/notes").json()) == before_notes
    runs = get(client, REVIEWER, "/api/ai/runs").json()
    assert runs[0]["id"] == b["id"] and runs[0]["context_sha256"] == b["context_sha256"]
    assert any(e["action"] == "ai.run" for e in get(client, PARTNER, "/api/audit/events", limit=20).json())

    monkeypatch.setattr(AI, "provider", lambda: Broken())
    b = post(client, REVIEWER, "/api/ai/brief").json()
    assert b["provider"] == "grounded_template" and not b["is_ai"] and "failed" in b["error"] and b["rejected"] == 0


def test_only_masked_context_is_sent_to_the_model(client, monkeypatch):
    sent = {}

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            facts = json.loads(sent["json"]["messages"][0]["content"].split("Facts:\n", 1)[1])
            return {"content": [{"type": "text", "text": json.dumps({"claims": [{"text": facts[0]["text"], "refs": facts[0]["refs"]}]})}]}

    def fake_post(url, **kw):
        sent.update(kw, url=url)
        return Resp()

    monkeypatch.setenv("TAXPROOF_AI_API_KEY", "test-key-not-real")
    monkeypatch.setattr(AI.httpx, "post", fake_post)
    r = post(client, REVIEWER, "/api/ai/explain", {"finding_id": "identity:theo:ev-0012"}).json()
    assert r["provider"] == "anthropic" and r["model"] == "claude-opus-5-5" and r["supported"] == 1
    payload = json.dumps(sent["json"])
    assert not SSN.search(payload)
    assert sent["url"].endswith("/v1/messages") and sent["headers"]["x-api-key"] == "test-key-not-real"


def test_explain_and_draft_without_a_model(client):
    e = post(client, REVIEWER, "/api/ai/explain", {"finding_id": "dup-page:D23#p3:SchC.44a"}).json()
    assert not e["is_ai"] and e["rejected"] == 0 and e["supported"] >= 3
    assert any("11,800" in c["text"] and "8,100" in c["text"] for c in e["claims"])
    assert all(c["refs"] for c in e["claims"])
    d = post(client, PREPARER, "/api/ai/draft-question", {"item_key": "finding:questionnaire:qa-25"}).json()
    assert d["question"] and d["question"].endswith("?")
    assert post(client, CLIENT, "/api/ai/draft-question", {"item_key": "finding:questionnaire:qa-25"}).status_code == 403
    assert post(client, CLIENT, "/api/ai/brief").status_code == 403
    assert get(client, REVIEWER, "/api/ai/status").json()["is_ai"] is False


# ---- risk score -------------------------------------------------------------------------------------------

def test_risk_scores_are_sums_of_explained_components(client):
    r = get(client, REVIEWER, "/api/review/risk").json()
    assert r["items"] and r["areas"]
    for it in r["items"]:
        assert 0 <= it["score"] <= 100 and it["score"] == min(100, sum(c["points"] for c in it["components"]))
        assert it["level"] == ("high" if it["score"] >= 50 else "medium" if it["score"] >= 25 else "low")
        for comp in it["components"]:
            assert comp["reason"] and 0 < comp["points"] <= comp["max"]
    card = next(i for i in r["items"] if i["key"] == "finding:card-in-books:D21:SchC.1")
    keys = {c["key"] for c in card["components"]}
    assert {"duplicate_evidence", "material_tax_impact", "calculation_disagreement"} <= keys
    low = next(i for i in r["items"] if i["key"] == "finding:extraction-conflict:ev-1049")
    assert {"extraction_uncertainty", "source_conflict"} <= {c["key"] for c in low["components"]}
    assert "ev-1049" in next(c for c in low["components"] if c["key"] == "extraction_uncertainty")["refs"]
    assert get(client, CLIENT, "/api/review/risk").status_code == 403


# ---- search ---------------------------------------------------------------------------------------------------

def test_the_example_questions(client):
    r = get(client, REVIEWER, "/api/search", q="Show me everything supporting the California move.").json()
    top = [x["ref"] for x in r["results"][:10]]
    assert "household:residency" in top and "qa-02" in top and "residency" in r["expanded_with"]

    r = get(client, REVIEWER, "/api/search", q="Why did tax increase from v2 to v3?").json()
    a = r["answer"]
    assert a["intent"] == "version_change" and "+4,492" in a["text"] and "+875" in a["text"]
    assert {"line:v3:F7203.1", "line:v3:Sch3.10", "line:v3:SchE.28B"} <= {i["ref"] for i in a["items"]}

    r = get(client, REVIEWER, "/api/search", q="Show unresolved basis issues").json()
    refs = {i["ref"] for i in r["answer"]["items"]}
    assert r["answer"]["intent"] == "open_basis" and "finding:supplemental-basis:F8949.B.N1" in refs

    r = get(client, REVIEWER, "/api/search", q="Which values came from low-confidence extractions?").json()
    assert r["answer"]["intent"] == "low_confidence" and "ev-1049" in {i["ref"] for i in r["answer"]["items"]}

    body = get(client, UNCLEARED, "/api/search", q="Theo Social Security card").text
    assert not SSN.search(body)
    assert get(client, CLIENT, "/api/search", q="California").status_code == 403


# ---- firm standards ------------------------------------------------------------------------------------------

def test_firm_standards_are_versioned_validated_and_take_effect(client):
    original = get(client, ADMIN, "/api/firm/standards").json()["standards"]
    assert post(client, PARTNER, "/api/firm/standards", {"changes": {"partner_threshold": 5000}, "note": "try"}).status_code == 403
    assert post(client, ADMIN, "/api/firm/standards", {"changes": {"variance_review": {"flag_if_change_over_percent": 0, "and_over_amount": 1}},
                                                         "note": "bad"}).status_code == 422
    assert post(client, ADMIN, "/api/firm/standards", {"changes": {"verification_types": ["eyeballed"]}, "note": "bad"}).status_code == 422
    assert post(client, ADMIN, "/api/firm/standards", {"changes": {"review_levels": []}, "note": "nope"}).status_code == 422
    try:
        r = post(client, ADMIN, "/api/firm/standards", {"changes": {"partner_threshold": 5000,
                                                                     "verification_types": [m for m in original["verification_types"] if m != "recalculated"]},
                                                         "note": "Raise the partner threshold for this season"})
        assert r.status_code == 200 and r.json()["version"] >= 1 and r.json()["history"][0]["note"].startswith("Raise")
        # takes effect: a 4,402 adjustment now needs only a reviewer; "recalculated" is no longer a method
        for a in get(client, PARTNER, "/api/adjustments").json()["adjustments"]:
            if a["status"] != "undone":
                post(client, PARTNER, f"/api/adjustments/{a['id']}/undo")
        adj = post(client, PREPARER, "/api/adjustments/from-finding", {"finding_id": "card-in-books:D21:SchC.1"}).json()
        assert adj["review_required"] == "reviewer"
        post(client, PREPARER, f"/api/adjustments/{adj['id']}/undo")
        assert "recalculated" not in get(client, PREPARER, "/api/verification-methods").json()
        assert post(client, PREPARER, "/api/verifications", {"target_ref": "line:v3:SchC.8", "method": "recalculated",
                                                              "note": "x"}).status_code == 422
        events = get(client, PARTNER, "/api/audit/events", limit=50).json()
        changed = next(e for e in events if e["action"] == "firm.standards_changed")
        assert changed["payload"]["before"]["partner_threshold"] == 1000 and changed["payload"]["after"]["partner_threshold"] == 5000
    finally:
        post(client, ADMIN, "/api/firm/standards", {"changes": {k: original[k] for k in ("partner_threshold", "verification_types")},
                                                     "note": "Back to the starter values"})
    assert standards.partner_threshold() == 1000


# ---- budget vs actual -----------------------------------------------------------------------------------------

def test_time_against_budget(client):
    r = post(client, PREPARER, "/api/time", {"budget_key": "business", "hours": 2.5, "worked_on": "2026-03-10", "note": "mileage log"})
    assert r.status_code == 201
    post(client, REVIEWER, "/api/time", {"budget_key": "business", "hours": 1.5, "worked_on": "2026-04-01"})
    line = next(x for x in get(client, ADMIN, "/api/time/budget").json()["lines"] if x["budget_key"] == "business")
    assert line["budget"] == 3.5 and line["actual"] >= 4.0 and line["over"] is True
    assert line["by_person"]["Priya Raman"] >= 2.5
    assert post(client, PREPARER, "/api/time", {"budget_key": "nope", "hours": 1, "worked_on": "2026-03-10"}).status_code == 422
    assert post(client, PREPARER, "/api/time", {"budget_key": "business", "hours": 0.3, "worked_on": "2026-03-10"}).status_code == 422
    assert post(client, PREPARER, "/api/time", {"budget_key": "business", "hours": 13, "worked_on": "2026-03-10"}).status_code == 422
    assert post(client, ADMIN, "/api/time", {"budget_key": "business", "hours": 1, "worked_on": "2026-03-10"}).status_code == 403
    assert get(client, CLIENT, "/api/time/budget").status_code == 403


