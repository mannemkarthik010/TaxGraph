import pytest

from app.config import settings
from app.packet.loader import sha256_of
from app.services import adjustments as A
from app.services import assurance
from app.services import time_machine as TM
from tests.conftest import as_user

PREPARER, UNCLEARED, REVIEWER, PARTNER, ADMIN, QR, CLIENT = "st-01", "st-04", "st-02", "st-03", "st-05", "st-06", "cu-01"


def post(client, user, path, body=None):
    return client.post(path, headers=as_user(user), json=body or {})


@pytest.fixture()
def clean(client):
    """Undo every active adjustment so each test starts with free lines (history is kept, never deleted)."""
    for a in client.get("/api/adjustments", headers=as_user(PARTNER)).json()["adjustments"]:
        if a["status"] != "undone":
            post(client, PARTNER, f"/api/adjustments/{a['id']}/undo")
    yield


# ---- effects ------------------------------------------------------------------------------------------

def test_mileage_effect_goes_through_the_dollar_line(idx):
    eff = A.estimate_effect(idx, "v3", "SchC.44a", -3700)
    rates = idx.versions_by_id["v3"]["tax_effect_rates"]["schc_profit"]
    assert eff["kind"] == "tax" and eff["federal"] == round(2590 * rates["federal_per_dollar"])
    assert "3,700 miles" in eff["basis"] or "-3,700 miles" in eff["basis"]
    assert A.review_required(eff) == "reviewer"
    assert A.review_required(A.estimate_effect(idx, "v3", "SchC.1", -12400)) == "partner"


def test_payment_adjustment_moves_balance_not_tax(idx):
    eff = A.estimate_effect(idx, "v3", "F1040.26", -1000)
    assert eff == {**eff, "kind": "balance", "federal": 1000, "california": 0.0}


def test_targets_are_validated(idx):
    with pytest.raises(A.AdjustmentError):
        A.validate_target(idx, "v2", "SchC.44a")           # superseded version
    with pytest.raises(A.AdjustmentError):
        A.validate_target(idx, "v3", "SchE.1A")            # text line
    with pytest.raises(A.AdjustmentError):
        A.validate_target(idx, "v3", "F1040.24")           # a total of other lines: adjust an input instead


# ---- the required example ------------------------------------------------------------------------------

def test_mileage_adjustment_end_to_end(client, idx, clean):
    a = post(client, PREPARER, "/api/adjustments/from-finding", {"finding_id": "dup-page:D23#p3:SchC.44a"}).json()
    assert (a["target_line"], a["original_value"], a["adjusted_value"], a["difference"], a["unit"]) == ("SchC.44a", 11800, 8100, -3700, "miles")
    assert a["status"] == "proposed" and a["finding_id"] == "dup-page:D23#p3:SchC.44a"
    assert a["effect"]["federal"] == 919 and a["effect"]["california"] == 80 and a["effect"]["estimate"] is True
    assert "doc:D23#page3" in a["evidence_refs"] and a["review_required"] == "reviewer"

    eff = client.get("/api/adjustments/effective/SchC.44a", headers=as_user(REVIEWER)).json()
    assert eff["engine_value"] == 11800 and eff["effective_value"] == 11800 and not eff["adjusted"]   # proposed only
    assert post(client, PREPARER, f"/api/adjustments/{a['id']}/apply").json()["status"] == "applied"
    eff = client.get("/api/adjustments/effective/SchC.44a", headers=as_user(REVIEWER)).json()
    assert eff["effective_value"] == 8100 and eff["adjusted"]

    # the original is never overwritten
    assert idx.line("v3", "SchC.44a")["value"] == 11800
    assert sha256_of(settings.packet_path) == idx.packet.sha256

    summary = client.get("/api/adjustments", headers=as_user(REVIEWER)).json()["summary"]
    assert summary["estimated"]["federal_total_tax"] == summary["engine"]["federal_total_tax"] + 919

    undone = post(client, PREPARER, f"/api/adjustments/{a['id']}/undo", {"note": "re-check"}).json()
    assert undone["status"] == "undone"
    assert client.get("/api/adjustments/effective/SchC.44a", headers=as_user(REVIEWER)).json()["effective_value"] == 11800
    restored = post(client, PREPARER, f"/api/adjustments/{a['id']}/restore").json()
    assert restored["status"] == "applied"
    assert [h["action"] for h in restored["history"]] == ["create", "apply", "undo", "restore"]
    node = client.get("/api/graph/node", params={"ref": "line:v3:SchC.44a"}, headers=as_user(REVIEWER)).json()
    assert any(e["type"] == "ADJUSTED_BY" and e["other"] == f"adjustment:{a['id']}" for e in node["outgoing"])


def test_every_proposable_finding_becomes_an_adjustment(client, idx, clean):
    findings = assurance.challenge(idx, "v3")
    proposable = [f for f in findings if f.proposed_adjustment]
    assert len(proposable) >= 8
    created = []
    for f in proposable:
        r = post(client, PREPARER, "/api/adjustments/from-finding", {"finding_id": f.id})
        assert r.status_code == 201, (f.id, r.json())
        a = r.json()
        assert a["target_line"] == f.proposed_adjustment["line"] and a["adjusted_value"] == f.proposed_adjustment["value"]
        created.append(a)
    targets = {a["target_line"] for a in created}
    assert targets >= {"SchC.44a", "SchC.1", "F8949.B.N1", "SchCA540NR.1.E", "F1040.26", "F540NR.72", "SchB.1.2", "SchB.1.6"}
    assert not [t for t in targets if idx.line("v3", t)["rule"] == "R-SUM"]     # never a line that only adds others
    interest = next(a for a in created if a["target_line"] == "SchB.1.2")
    assert interest["adjusted_value"] == 0 and interest["effect"]["federal"] < 0
    for a in created:
        post(client, PREPARER, f"/api/adjustments/{a['id']}/undo")
    # not expressible as one line: judgment items, and the missing Meridian sale
    judgment = next(f for f in findings if f.status == "attention")
    assert post(client, PREPARER, "/api/adjustments/from-finding", {"finding_id": judgment.id}).status_code == 422
    assert post(client, PREPARER, "/api/adjustments/from-finding", {"finding_id": "broker-summary:D31"}).status_code == 422


# ---- state machine, bulk, approvals, roles -------------------------------------------------------------

def test_one_active_adjustment_per_line_and_valid_transitions(client, clean):
    a = post(client, PREPARER, "/api/adjustments", {"target_line": "SchC.8", "adjusted_value": 2000, "reason": "Advertising per invoices"}).json()
    assert post(client, PREPARER, "/api/adjustments", {"target_line": "SchC.8", "adjusted_value": 1900, "reason": "again"}).status_code == 409
    assert post(client, PREPARER, f"/api/adjustments/{a['id']}/restore").status_code == 409     # not undone
    assert post(client, PREPARER, f"/api/adjustments/{a['id']}/undo").status_code == 200
    assert post(client, PREPARER, f"/api/adjustments/{a['id']}/undo").status_code == 409
    b = post(client, PREPARER, "/api/adjustments", {"target_line": "SchC.8", "adjusted_value": 1900, "reason": "replacement"}).json()
    assert post(client, PREPARER, f"/api/adjustments/{a['id']}/restore").status_code == 409     # line now taken by b
    assert post(client, PREPARER, "/api/adjustments", {"target_line": "SchC.8", "adjusted_value": 2100, "reason": "no change"}).status_code == 409
    post(client, PREPARER, f"/api/adjustments/{b['id']}/undo")
    assert post(client, PREPARER, "/api/adjustments", {"target_line": "SchC.8", "adjusted_value": 2100, "reason": "same as engine"}).status_code == 422
    assert post(client, PREPARER, "/api/adjustments", {"target_line": "SchC.8", "adjusted_value": 1, "reason": "x",
                                                       "evidence_refs": ["D99"]}).status_code == 422


def test_bulk_is_all_or_nothing(client, clean):
    ids = [post(client, PREPARER, "/api/adjustments", {"target_line": k, "adjusted_value": v, "reason": "bulk test"}).json()["id"]
           for k, v in (("SchC.15", 1400), ("SchC.17", 1700), ("SchC.18", 1100))]
    ok = post(client, PREPARER, "/api/adjustments/bulk", {"action": "apply", "ids": ids})
    assert ok.status_code == 200 and {a["status"] for a in ok.json()["changed"]} == {"applied"}
    post(client, PREPARER, f"/api/adjustments/{ids[0]}/undo")
    bad = post(client, PREPARER, "/api/adjustments/bulk", {"action": "undo", "ids": ids})     # ids[0] already undone
    assert bad.status_code == 409 and bad.json()["detail"]["errors"][0]["id"] == ids[0]
    states = {a["id"]: a["status"] for a in client.get("/api/adjustments", headers=as_user(PREPARER)).json()["adjustments"]}
    assert states[ids[1]] == states[ids[2]] == "applied"                  # nothing changed
    assert post(client, PREPARER, "/api/adjustments/bulk", {"action": "undo", "ids": [ids[1], ids[1]]}).status_code == 422
    assert post(client, PREPARER, "/api/adjustments/bulk", {"action": "undo", "ids": ids[1:]}).status_code == 200


def test_approval_rules(client, clean):
    small = post(client, PREPARER, "/api/adjustments", {"target_line": "SchC.22", "adjusted_value": 3000, "reason": "supplies receipts", "apply": True}).json()
    big = post(client, PREPARER, "/api/adjustments/from-finding", {"finding_id": "card-in-books:D21:SchC.1", "apply": True}).json()
    assert small["review_required"] == "reviewer" and big["review_required"] == "partner"
    assert post(client, PREPARER, f"/api/adjustments/{small['id']}/approve").status_code == 403    # own work
    assert post(client, REVIEWER, f"/api/adjustments/{big['id']}/approve").status_code == 403      # needs partner
    assert post(client, REVIEWER, f"/api/adjustments/{small['id']}/approve").json()["approved_by"] == "Daniel Ortiz"
    assert post(client, PARTNER, f"/api/adjustments/{big['id']}/approve").json()["approved_by"] == "Helen Strand"
    assert post(client, PARTNER, f"/api/adjustments/{big['id']}/approve").status_code == 409
    # restoring after an undo is a new decision: approval is cleared
    post(client, PREPARER, f"/api/adjustments/{small['id']}/undo")
    assert post(client, PREPARER, f"/api/adjustments/{small['id']}/restore").json()["approved_by"] in (None, "")


def test_roles(client, clean):
    body = {"target_line": "SchC.24a", "adjusted_value": 4000, "reason": "travel"}
    for user in (CLIENT, ADMIN, QR):
        assert post(client, user, "/api/adjustments", body).status_code == 403, user
    assert client.get("/api/adjustments", headers=as_user(CLIENT)).status_code == 403
    a = post(client, PREPARER, "/api/adjustments", body).json()
    assert post(client, UNCLEARED, f"/api/adjustments/{a['id']}/undo").status_code == 403         # another preparer's work
    assert post(client, REVIEWER, f"/api/adjustments/{a['id']}/undo").status_code == 200
    eff = client.get("/api/adjustments/effective/SchC.24a", headers=as_user(CLIENT)).json()
    assert eff["adjustments"] == []                                                               # internal history hidden
    actions = {e["action"] for e in client.get("/api/audit/events?limit=1000", headers=as_user(PARTNER)).json()}
    assert {"adjustment.created", "adjustment.apply", "adjustment.undo", "adjustment.restore", "adjustment.bulk", "adjustment.approve"} <= actions


# ---- Time Machine / What-If ------------------------------------------------------------------------------

@pytest.mark.parametrize("a,b", [("v1", "v2"), ("v2", "v3")])
def test_time_machine_matches_the_engines_change_list(idx, a, b):
    d = TM.compare(idx, a, b)
    assert d["consistency_with_engine"]["agrees"] is True
    assert d["lines"]["total"] == len(idx.versions_by_id[b]["changes_from_previous"])
    s = {v: idx.versions_by_id[v]["summary"]["federal"]["total_tax"] for v in (a, b)}
    assert d["tax_change"]["federal"] == s[b] - s[a]


def test_time_machine_explains_v2_to_v3(idx):
    d = TM.compare(idx, "v2", "v3")
    drivers = {x["key"]: x for x in d["drivers"]}
    assert drivers["F7203.1"]["new_source_documents"] == ["D40"]       # the late 2023 K-1
    assert "D37" in drivers["SchE.28B"]["new_source_documents"]        # the Ridgeline K-1
    assert drivers["Sch3.10"]["new"] == 36000                          # extension payment
    assert "F1040.24" not in drivers                                   # totals move because inputs moved
    assert {x["id"] for x in d["documents"]["now_used"]} >= {"D37", "D38", "D40"}
    assert {x["code"] for x in d["diagnostics"]["removed"]} == {"K1_EXPECTED_NOT_RECEIVED", "SCORP_BASIS_INCOMPLETE"}
    assert any(t["event"] == "extension_filed_with_payment" for t in d["why"]["timeline"])


def test_time_machine_any_pair_and_reverse(idx):
    fwd, back = TM.compare(idx, "v1", "v3"), TM.compare(idx, "v3", "v1")
    assert fwd["consistency_with_engine"] is None                      # not consecutive: no engine list to check
    assert fwd["tax_change"]["federal"] == -back["tax_change"]["federal"]
    assert fwd["lines"]["total"] == back["lines"]["total"]


def test_what_if_shows_only_supplied_engine_results(idx, client):
    w = TM.what_if(idx, assurance.challenge(idx, "v3"))
    supplied = {a["id"]: a for a in idx.data["what_if"]["alternatives"]}
    assert {a["id"] for a in w["alternatives"]} == set(supplied)
    for a in w["alternatives"]:
        assert a["federal"]["total_tax_change"] == supplied[a["id"]]["federal"]["total_tax_change"]
        assert a["california"]["total_tax_change"] == supplied[a["id"]]["california"]["total_tax_change"]
        assert len(a["changed_lines"]) == len(supplied[a["id"]]["changed_lines"]) and a["source"] == "engine"
    hvac = next(a for a in w["alternatives"] if a["id"] == "hvac_improvement")
    assert [f["id"] for f in hvac["related_findings"]] == ["repair-vs-improvement:D47:SchE.14A"]
    assert w["extension"]["federal"]["paid_with_form_4868"] == 36000
    r = client.get("/api/return/what-if", headers=as_user(CLIENT)).json()
    assert all(a["related_findings"] == [] for a in r["alternatives"])     # clients don't see internal findings
    assert client.get("/api/return/time-machine?from=v3&to=v3", headers=as_user(PREPARER)).status_code == 422



def test_audit_chain_survives_negative_zero(client, clean):
    """Regression: a California-only effect produced federal −0.0; JSONB stored 0 and broke the hash chain."""
    from app.services.audit import _storable
    assert str(_storable({"a": [-0.0, {"b": -0.0}]})) == "{'a': [0.0, {'b': 0.0}]}"
    a = post(client, PREPARER, "/api/adjustments/from-finding", {"finding_id": "ca-wages:SchCA540NR.1.E", "apply": True}).json()
    assert str(a["effect"]["federal"]) == "0.0"
    assert client.get("/api/audit/verify", headers=as_user(PARTNER)).json()["valid"] is True



def test_derived_proposals_only_replace_the_value_the_engine_has_on_that_line(idx):
    """Regression: the Meridian finding's 'engine value' was a sum of lots but cited one lot, so the adjustment
    would have replaced that lot's gain with the 1099-B summary."""
    for f in assurance.challenge(idx, "v3"):
        p = f.proposed_adjustment
        if p and not f.adjust:
            assert f.engine["value"] == idx.line("v3", p["line"])["value"], f.id


# ---- review follow-ups (after the Iteration 6 review) --------------------------------------------------

def _states(client):
    return {a["id"]: a["status"] for a in client.get("/api/adjustments", headers=as_user(PREPARER)).json()["adjustments"]}


def test_bulk_rolls_back_items_that_succeeded_before_a_failure(client, clean):
    """A valid item first, then one that fails: the valid one must not stay changed (it did on SQLite)."""
    ids = [post(client, PREPARER, "/api/adjustments", {"target_line": k, "adjusted_value": v, "reason": "bulk rollback"}).json()["id"]
           for k, v in (("SchC.15", 1300), ("SchC.17", 1600))]
    events_before = client.get("/api/audit/verify", headers=as_user(PARTNER)).json()["events"]
    for bad_ids in ([ids[0], 999_999], [ids[0], ids[1], 999_999], [999_999, ids[0]]):
        r = post(client, PREPARER, "/api/adjustments/bulk", {"action": "apply", "ids": bad_ids})
        assert r.status_code == 409 and r.json()["detail"]["message"].startswith("No adjustments changed")
        states = _states(client)
        assert states[ids[0]] == states[ids[1]] == "proposed", bad_ids
    chain = client.get("/api/audit/verify", headers=as_user(PARTNER)).json()
    assert chain["valid"] is True and chain["events"] == events_before    # no apply event survived either


def test_an_adjustment_keeps_its_findings_rate_context(client, idx, clean):
    """Every adjustment made from a finding estimates the same effect the finding showed — including
    California's ca_source_income category for a lot sold while a California resident."""
    for f in assurance.challenge(idx, "v3"):
        p = f.proposed_adjustment
        if not p or not f.effect:
            continue
        a = post(client, PREPARER, "/api/adjustments/from-finding", {"finding_id": f.id}).json()
        assert (a["effect"]["federal"], a["effect"]["california"]) == (f.effect["federal"], f.effect["california"]), f.id
        assert a["effect"].get("ca_category") == f.effect.get("ca_category"), f.id
        post(client, PREPARER, f"/api/adjustments/{a['id']}/undo")
    rsu = next(f for f in assurance.challenge(idx, "v3") if f.id.startswith("supplemental-basis") and f.status == "fail")
    assert rsu.lines[0] == "F8949.B.N1" and rsu.effect["california"] == -1222
    # the same change typed by hand on that lot gets the same California category
    manual = A.estimate_effect(idx, "v3", "F8949.B.N1", rsu.difference)
    assert manual["ca_category"] == "ca_source_income" and manual["california"] == -1222


def test_related_lines_cannot_both_carry_an_adjustment(client, clean):
    """Mileage (SchC.44a) flows into the car expense (SchC.9): adjusting both counts one correction twice."""
    miles = post(client, PREPARER, "/api/adjustments/from-finding", {"finding_id": "dup-page:D23#p3:SchC.44a", "apply": True}).json()
    r = post(client, PREPARER, "/api/adjustments", {"target_line": "SchC.9", "adjusted_value": 5670, "reason": "8,100 miles × 0.70"})
    assert r.status_code == 409 and "SchC.44a" in r.json()["detail"] and f"#{miles['id']}" in r.json()["detail"]
    s = client.get("/api/adjustments", headers=as_user(PREPARER)).json()["summary"]
    assert s["applied_adjustments"] == 1 and s["estimated"]["federal_total_tax"] - s["engine"]["federal_total_tax"] == 919

    # the other way round: with SchC.9 adjusted, the mileage adjustment can be neither created nor restored
    post(client, PREPARER, f"/api/adjustments/{miles['id']}/undo")
    car = post(client, PREPARER, "/api/adjustments", {"target_line": "SchC.9", "adjusted_value": 5670, "reason": "8,100 miles × 0.70",
                                                      "apply": True})
    assert car.status_code == 201
    r = post(client, PREPARER, f"/api/adjustments/{miles['id']}/restore")
    assert r.status_code == 409 and "SchC.9" in r.json()["detail"]
    assert post(client, PREPARER, "/api/adjustments/from-finding", {"finding_id": "dup-page:D23#p3:SchC.44a"}).status_code == 409
    # bulk restore is refused as a whole
    assert post(client, PREPARER, "/api/adjustments/bulk", {"action": "restore", "ids": [miles["id"]]}).status_code == 409
    # unrelated lines that merely meet in a total (gross receipts and an expense) are independent
    assert post(client, PREPARER, "/api/adjustments", {"target_line": "SchC.8", "adjusted_value": 2000, "reason": "advertising"}).status_code == 201
