"""Review follow-ups after the Iteration 9 review."""

import json
import re

from app.services import ai as AI
from app.services import search
from tests.conftest import as_user

PREPARER, UNCLEARED, REVIEWER, PARTNER, ADMIN, CLIENT = "st-01", "st-04", "st-02", "st-03", "st-05", "cu-01"
SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
FAKE_SSN = "078-05-1120"


def post(client, user, path, body=None):
    return client.post(path, headers=as_user(user), json=body or {})


def get(client, user, path, **params):
    return client.get(path, headers=as_user(user), params=params)


FACTS = [AI.fact("T1", "Estimated effect on California tax: -1,222 (the lot was sold while a California resident).", ["F8949.B.N1"]),
         AI.fact("M1", "D23 page 3 duplicates page 2: 3,700 miles counted twice in SchC.44a.", ["doc:D23#page3"])]


def test_a_cited_fact_must_actually_support_the_claim():
    out = AI.validate([
        {"text": "California tax falls by 1,222 for the lot sold while a California resident.", "refs": ["F8949.B.N1"]},   # ok
        {"text": "California tax changes by -1,222 for the lot.", "refs": ["F8949.B.N1"]},                                   # ok
        {"text": "California tax increases by 1,222 for this lot.", "refs": ["F8949.B.N1"]},                                 # wrong direction
        {"text": "The California effect is +1,222.", "refs": ["F8949.B.N1"]},                                                # wrong sign
        {"text": "All evidence is verified and the return is ready to file.", "refs": ["doc:D23#page3"]},                   # status not in evidence
        {"text": "Page 3 duplicates page 2, so 3,700 miles are counted twice.", "refs": ["doc:D23#page3"]},                 # ok
        {"text": "The taxpayer's crypto wallet was hacked in Lisbon.", "refs": ["doc:D23#page3"]},                           # says nothing the evidence says
    ], FACTS)
    assert [c["status"] for c in out] == ["supported", "supported", "rejected", "rejected", "rejected", "supported", "rejected"]
    assert "direction" in " ".join(out[2]["problems"]) and "sign" in " ".join(out[3]["problems"])
    assert "not stated" in " ".join(out[4]["problems"]) and "not stated" in " ".join(out[6]["problems"])


class Malformed(AI.Provider):
    name, model = "anthropic", "test-model"

    def __init__(self, claims):
        self.claims = claims

    def complete(self, task, facts):
        return json.dumps({"claims": self.claims}), self.claims


def test_malformed_model_output_is_rejected_safely_or_falls_back():
    out = AI.validate([None, "text only", {"refs": ["M1"]}, {"text": 42, "refs": "M1"}], FACTS)
    assert [c["status"] for c in out] == ["rejected"] * 4 and all("malformed" in " ".join(c["problems"]) for c in out)
    r = AI.run("explain_finding", FACTS, Malformed([None]))
    assert r["provider"] == "grounded_template" and "no usable claims" in r["error"] and r["supported"] == len(FACTS)
    r = AI.run("explain_finding", FACTS, Malformed({"not": "a list"}))
    assert r["provider"] == "grounded_template" and r["supported"] == len(FACTS)


def test_firm_standards_are_masked_for_everyone(client):
    original = get(client, ADMIN, "/api/firm/standards").json()["standards"]
    try:
        r = post(client, ADMIN, "/api/firm/standards", {"changes": {"rules": original["rules"] + [f"Escalate if SSN {FAKE_SSN} appears."]},
                                                         "note": f"Added after a client sent SSN {FAKE_SSN} by email"})
        assert r.status_code == 200 and FAKE_SSN not in r.text
        for user in (UNCLEARED, PREPARER, PARTNER, ADMIN):
            for path in ("/api/firm/standards", "/api/firm", "/api/audit/events"):
                resp = get(client, user, path)
                if resp.status_code == 200:
                    assert FAKE_SSN not in resp.text, (user, path)
        post(client, PREPARER, "/api/time", {"budget_key": "business", "hours": 0.25, "worked_on": "2026-03-11", "note": f"call re {FAKE_SSN}"})
        assert FAKE_SSN not in get(client, UNCLEARED, "/api/time/budget").text
    finally:
        post(client, ADMIN, "/api/firm/standards", {"changes": {"rules": original["rules"]}, "note": "Restore the rules"})


def test_explanations_follow_the_selected_return_version(client):
    v1 = post(client, REVIEWER, "/api/ai/explain", {"finding_id": "ca-wages:SchCA540NR.1.E", "version": "v1"})
    v3 = post(client, REVIEWER, "/api/ai/explain", {"finding_id": "ca-wages:SchCA540NR.1.E", "version": "v3"})
    assert v1.status_code == v3.status_code == 200
    t1, t3 = " ".join(c["text"] for c in v1.json()["claims"]), " ".join(c["text"] for c in v3.json()["claims"])
    assert "v1" in t1 and "pass" in t1.lower() and "v3" in t3 and "fail" in t3.lower() and t1 != t3
    assert v1.json()["subject"].endswith("@v1")
    assert post(client, REVIEWER, "/api/ai/explain", {"finding_id": "ca-wages:SchCA540NR.1.E", "version": "v9"}).status_code == 404


def test_judgments_and_approvals_carry_their_tax_exposure_into_risk(client):
    j = post(client, PREPARER, "/api/judgments", {
        "topic": "Second HVAC unit at Fremont Way", "target_refs": ["line:v3:SchE.14A"], "decision": "Treat as a repair.",
        "decision_option": "keep_engine", "alternatives": [{"option": "what_if:hvac_improvement"}],
        "rationale": "Replacement of a failed compressor only.", "authority": "Treas. Reg. 1.263(a)-3(k)"}).json()
    assert j["tax_effect"]["tax_at_stake"] == 3633
    items = {i["key"]: i for i in get(client, REVIEWER, "/api/review/risk").json()["items"]}
    item = items[f"judgment:{j['id']}"]
    comp = next(c for c in item["components"] if c["key"] == "material_tax_impact")
    assert comp["points"] == 25 and "3,633" in comp["reason"] and item["score"] >= 25


def test_accepted_client_answers_are_searchable(client):
    phrase = "zebraquartz lighthouse invoice"
    q = post(client, PREPARER, "/api/client-questions", {"target_ref": "line:v3:SchC.18", "question": "What were the office supplies for?"}).json()
    post(client, CLIENT, f"/api/client-questions/{q['id']}/answer", {"answer": f"The {phrase} covered printer ink."})
    post(client, PREPARER, f"/api/client-questions/{q['id']}/accept", {})
    r = get(client, REVIEWER, "/api/search", q=phrase).json()
    assert r["results"] and r["results"][0]["ref"] == f"client_answer:{q['id']}"


def test_search_learns_associations_from_the_file(idx):
    assoc = search.associations(idx, "sacramento")
    assert assoc and all(w != "sacramento" for w, _ in assoc)
    r = search.rank(idx, "Austin relocation")
    assert any(x["ref"] in ("qa-02", "household:residency") for x in r[:10])


def test_semantic_layer_finds_answers_that_share_no_words(idx, monkeypatch):
    # The client's answer about the move ("Sacramento to Austin") never says "relocation" or "Texas".
    q = "relocation to Texas"
    qa02 = next(d for d in search._index(idx)[0] if d.ref == "qa-02")
    assert not set(search.tokens(q)) & set(search.tokens(qa02.title + " " + qa02.text))
    assert "qa-02" in [x["ref"] for x in search.rank(idx, q)[:5]]
    # Nothing lexical at all (no query word, lexicon concept or learned association): only the latent space ties
    # "university" to the scholarship letter, which talks about tuition and a second-year student.
    hit = next(x for x in search.rank(idx, "university")[:5] if x["ref"] == "doc:D60#page1")
    assert hit["matched"] == [] and hit["semantic"] > search.SEM_FLOOR and hit["related"]
    monkeypatch.setattr(search, "SEM_WEIGHT", 0.0)
    assert "doc:D60#page1" not in [x["ref"] for x in search.rank(idx, "university")[:5]]


def test_search_falls_back_to_bm25_without_the_semantic_layer(idx, monkeypatch):
    monkeypatch.setattr(search, "semantic", None)            # numpy not installed
    r = search.rank(idx, "Show me everything supporting the California move.")
    assert {"household:residency", "qa-02"} <= {x["ref"] for x in r[:10]}
    assert all(x["semantic"] == 0 and x["related"] == [] for x in r) and "unavailable" in search.method()

    class Broken:
        DIMS = 0

        @staticmethod
        def index(*_a, **_k):
            raise RuntimeError("latent space unavailable")
    monkeypatch.setattr(search, "semantic", Broken)
    assert "qa-02" in [x["ref"] for x in search.rank(idx, "Austin relocation")[:10]]


def test_search_api_reports_the_semantic_method_and_stays_masked(client):
    r = get(client, REVIEWER, "/api/search", q="relocation to Texas")
    body = r.json()
    assert "LSA" in body["method"] and "nothing leaves the server" in body["method"]
    assert "qa-02" in [x["ref"] for x in body["results"][:5]] and all("semantic" in x and "related" in x for x in body["results"])
    assert not SSN.search(get(client, UNCLEARED, "/api/search", q="Social Security number dependent").text)
