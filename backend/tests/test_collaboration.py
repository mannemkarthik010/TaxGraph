"""Iteration 7: Uncertainty Inbox, client questions, Judgment Ledger, living sign-offs, filing gate."""

import pytest

from app.services import inbox as IB
from app.services import judgments as J
from tests.conftest import as_user

PREPARER, UNCLEARED, REVIEWER, PARTNER, ADMIN, QR, CLIENT, CLIENT2 = "st-01", "st-04", "st-02", "st-03", "st-05", "st-06", "cu-01", "cu-02"
MILEAGE = "finding:dup-page:D23#p3:SchC.44a"
HVAC = "finding:repair-vs-improvement:D47:SchE.14A"


def post(client, user, path, body=None):
    return client.post(path, headers=as_user(user), json=body or {})


def get(client, user, path):
    return client.get(path, headers=as_user(user))


def inbox(client, user=PREPARER, handled=True):
    data = get(client, user, f"/api/inbox?include_handled={'true' if handled else 'false'}").json()
    return {i["key"]: i for g in data["groups"] for i in g["items"]}


def area(client, key, user=PREPARER):
    return next(a for a in get(client, user, "/api/signoffs").json()["areas"] if a["key"] == key)


def level(a, name):
    return next(lv for lv in a["levels"] if lv["level"] == name)


def sign(client, user, area_key, lvl):
    return post(client, user, "/api/signoffs", {"area_key": area_key, "level": lvl})


@pytest.fixture()
def no_adjustments(client):
    for a in get(client, PARTNER, "/api/adjustments").json()["adjustments"]:
        if a["status"] != "undone":
            post(client, PARTNER, f"/api/adjustments/{a['id']}/undo")
    yield


# ---- inbox ---------------------------------------------------------------------------------------------

def test_every_open_item_is_in_exactly_one_group(client, idx):
    data = get(client, PREPARER, "/api/inbox").json()
    keys = [i["key"] for g in data["groups"] for i in g["items"]]
    assert len(keys) == len(set(keys)) and data["totals"]["open"] >= len(keys) - data["totals"]["handled"]
    by_key = {i["key"]: i for g in data["groups"] for i in g["items"]}
    assert [g["key"] for g in data["groups"]] == ["blockers", "conflicts", "missing", "judgment", "questions", "review"]
    # nature, never hard-coded by id: a failed duplicate check is a conflict, an unread page is missing evidence,
    # a repair-vs-improvement call is judgment, an engine "not computed" is missing evidence
    assert by_key[MILEAGE]["group"] == "conflicts" and by_key[MILEAGE]["areas"] == ["business"]
    assert by_key["finding:broker-summary:D31"]["group"] == "missing"
    assert by_key[HVAC]["group"] == "judgment" and by_key[HVAC]["areas"] == ["rentals"]
    assert by_key["diag:CA_AMT_NOT_COMPUTED"]["group"] == "missing"
    assert by_key["diag:FORM_1099_FILING"]["group"] == "judgment"
    # diagnostics a finding already covers are not repeated; informational diagnostics are not uncertainty
    assert not {"diag:LOW_CONFIDENCE_READ", "diag:BROKER_SUMMARY_DETAIL_MISMATCH", "diag:AOTC_PHASED_OUT"} & set(by_key)
    # actions follow the role
    assert "create_adjustment" in by_key[MILEAGE]["actions"] and "accept" not in by_key[MILEAGE]["actions"]
    assert "accept" in inbox(client, REVIEWER)[MILEAGE]["actions"]
    assert get(client, CLIENT, "/api/inbox").status_code == 403
    assert get(client, ADMIN, "/api/inbox").status_code == 403


def test_inbox_never_shows_a_full_ssn(client):
    import re
    body = get(client, UNCLEARED, "/api/inbox?include_handled=true").text
    assert not re.search(r"\b\d{3}-\d{2}-\d{4}\b", body)


def test_accept_resolve_escalate_and_assign(client):
    key = "finding:fx-period:SchB.1.6"
    assert post(client, PREPARER, "/api/inbox/accept", {"key": key, "note": "immaterial difference"}).status_code == 403
    assert post(client, REVIEWER, "/api/inbox/accept", {"key": key, "note": "short"}).status_code == 422
    r = post(client, REVIEWER, "/api/inbox/accept", {"key": key, "note": "Rate difference is immaterial (under 20)."})
    assert r.status_code == 200 and r.json()["status"] == "handled" and r.json()["handled"]["kind"] == "accepted"
    assert post(client, REVIEWER, "/api/inbox/accept", {"key": key, "note": "again, accepted as it stands"}).status_code == 409

    # escalation makes any item a filing blocker that only the partner can decide
    key = "diag:FORM_1099_FILING"
    assert post(client, PREPARER, "/api/inbox/escalate", {"key": key, "note": "Advice to client on late 1099s"}).status_code == 200
    item = inbox(client)[key]
    assert item["group"] == "blockers" and item["escalated"] and "partner" in item["blocking_reason"]
    ready = get(client, PREPARER, "/api/filing/readiness").json()
    assert not next(c for c in ready["checks"] if c["key"] == "escalations")["ok"] and not ready["can_file"]
    assert post(client, REVIEWER, "/api/inbox/resolve", {"key": key, "note": "told the client"}).status_code == 403
    assert post(client, PARTNER, "/api/inbox/resolve", {"key": key, "note": "Advised client in writing; outside the return."}).status_code == 200
    assert next(c for c in get(client, PREPARER, "/api/filing/readiness").json()["checks"] if c["key"] == "escalations")["ok"]

    key = "diag:DUE_DILIGENCE_REQUIRED"
    assert post(client, PREPARER, "/api/inbox/assign", {"key": key, "assignee_id": CLIENT}).status_code == 422
    assert post(client, PREPARER, "/api/inbox/assign", {"key": key, "assignee_id": UNCLEARED}).status_code == 200
    mine = get(client, UNCLEARED, "/api/inbox?mine=true").json()
    assert [i["key"] for g in mine["groups"] for i in g["items"]] == [key]
    history = inbox(client)[key]["history"]
    assert history[-1]["action"] == "assign" and history[-1]["by_name"] == "Priya Raman"
    actions = {e["action"] for e in get(client, PARTNER, "/api/audit/events?limit=1000").json()}
    assert {"inbox.accept", "inbox.escalate", "inbox.resolve", "inbox.assign"} <= actions


# ---- review notes block filing --------------------------------------------------------------------------

def test_blocking_review_note_disables_filing_and_the_review_signoff(client):
    note = post(client, REVIEWER, "/api/workpaper/notes", {"target_ref": "line:v3:F8606.2", "kind": "review_note",
                                                            "body": "Tie IRA basis to the 2024 Form 8606."}).json()
    key = f"note:{note['id']}"
    item = inbox(client)[key]
    assert item["group"] == "blockers" and item["areas"] == ["retirement"]
    ready = get(client, PREPARER, "/api/filing/readiness").json()
    check = next(c for c in ready["checks"] if c["key"] == "blocking_notes")
    assert not ready["can_file"] and not check["ok"] and key in [i["key"] for i in check["items"]]

    assert sign(client, PREPARER, "retirement", "prepared").status_code == 201
    r = sign(client, REVIEWER, "retirement", "reviewed")
    assert r.status_code == 409 and "blocking review note" in r.json()["detail"]
    assert "resolve" not in inbox(client)[key]["actions"]
    assert post(client, PREPARER, "/api/inbox/resolve", {"key": key, "note": "done"}).status_code == 403
    assert post(client, REVIEWER, "/api/inbox/resolve", {"key": key, "note": "Agreed to 2024 Form 8606 line 14."}).status_code == 200
    notes = get(client, REVIEWER, "/api/workpaper/notes?status=resolved").json()
    assert next(n for n in notes if n["id"] == note["id"])["resolution"] == "Agreed to 2024 Form 8606 line 14."
    assert next(c for c in get(client, PREPARER, "/api/filing/readiness").json()["checks"] if c["key"] == "blocking_notes")["ok"]
    assert sign(client, REVIEWER, "retirement", "reviewed").status_code == 201


# ---- sign-offs -------------------------------------------------------------------------------------------

def test_signoff_order_roles_and_independence(client):
    assert sign(client, REVIEWER, "foreign", "reviewed").status_code == 409            # needs prepared first
    assert sign(client, CLIENT, "foreign", "prepared").status_code == 403
    assert sign(client, QR, "foreign", "prepared").status_code == 403
    assert sign(client, REVIEWER, "foreign", "prepared").status_code == 201
    r = sign(client, REVIEWER, "foreign", "reviewed")                                    # reviewing own work
    assert r.status_code == 403 and "prepared" in r.json()["detail"]
    assert sign(client, PREPARER, "foreign", "reviewed").status_code == 403             # role
    assert sign(client, PARTNER, "foreign", "partner").status_code == 409               # reviewed first
    assert sign(client, PARTNER, "foreign", "reviewed").status_code == 201
    a = area(client, "foreign", PARTNER)
    assert level(a, "prepared")["status"] == level(a, "reviewed")["status"] == "signed"
    assert level(a, "partner")["status"] == "not_signed" and level(a, "partner")["can_sign"]
    assert not level(area(client, "foreign", REVIEWER), "partner")["can_sign"]
    assert sign(client, REVIEWER, "foreign", "prepared").status_code == 409             # already signed
    areas = {x["key"]: x for x in get(client, PREPARER, "/api/workpaper/areas").json()}
    assert (areas["foreign"]["preparer_status"], areas["foreign"]["reviewer_status"]) == ("prepared", "reviewed")


def test_adjustment_reopens_business_signoffs_with_the_reason(client, no_adjustments):
    """The demo: Business prepared/reviewed/partner ✓ → the mileage adjustment → reviewed and partner REOPENED."""
    for user, lvl in ((PREPARER, "prepared"), (REVIEWER, "reviewed"), (PARTNER, "partner")):
        if level(area(client, "business"), lvl)["status"] != "signed":
            assert sign(client, user, "business", lvl).status_code == 201, (lvl, sign(client, user, "business", lvl).json())
    a = post(client, PREPARER, "/api/adjustments/from-finding", {"finding_id": MILEAGE.split(":", 1)[1], "apply": True}).json()
    reopened = {(r["area"], r["level"]) for r in a["reopened_signoffs"]}
    assert reopened == {("business", "reviewed"), ("business", "partner")}
    b = area(client, "business")
    assert level(b, "prepared")["status"] == "signed"
    for lvl in ("reviewed", "partner"):
        lv = level(b, lvl)
        assert lv["status"] == "reopened"
        reason = lv["reopen_reasons"][-1]
        assert reason["action"] == "adjustment.apply" and reason["by_name"] == "Priya Raman"
        assert f"Adjustment #{a['id']} applied on SchC.44a (11,800 miles → 8,100 miles)" in reason["detail"]
    assert get(client, PREPARER, "/api/workpaper/areas").json()[2]["reviewer_status"] == "reopened"
    events = get(client, PARTNER, "/api/audit/events?limit=50").json()
    assert any(e["action"] == "signoff.reopened" and e["payload"]["action"] == "adjustment.apply" for e in events)
    # the finding is handled by the adjustment; the adjustment's approval is now the review item
    items = inbox(client)
    assert items[MILEAGE]["status"] == "handled" and items[MILEAGE]["handled"]["kind"] == "adjustment"
    assert items[f"adjustment:{a['id']}"]["group"] == "review"

    # re-sign, then an unrelated area's change leaves Business alone
    assert sign(client, REVIEWER, "business", "reviewed").status_code == 201
    pay = post(client, PREPARER, "/api/adjustments", {"target_line": "F1040.26", "adjusted_value": 18000, "reason": "per IRS transcript",
                                                      "apply": True}).json()
    assert {r["area"] for r in pay["reopened_signoffs"]} <= {"payments"}
    assert level(area(client, "business"), "reviewed")["status"] == "signed"
    # undoing the mileage adjustment is a change too
    undo = post(client, PREPARER, f"/api/adjustments/{a['id']}/undo").json()
    assert ("business", "reviewed") in {(r["area"], r["level"]) for r in undo["reopened_signoffs"]}
    # a reviewer who changes the area themselves cannot then review it
    mine = post(client, REVIEWER, "/api/adjustments", {"target_line": "SchC.8", "adjusted_value": 2000, "reason": "invoices",
                                                       "apply": True}).json()
    r = sign(client, REVIEWER, "business", "reviewed")
    assert r.status_code == 403 and f"adjustment #{mine['id']}" in r.json()["detail"]


def test_partner_signoff_waits_for_partner_approvals(client, no_adjustments):
    big = post(client, PREPARER, "/api/adjustments/from-finding", {"finding_id": "card-in-books:D21:SchC.1", "apply": True}).json()
    assert big["review_required"] == "partner"
    item = inbox(client)[f"adjustment:{big['id']}"]
    assert item["group"] == "blockers" and "partner sign-off" in item["blocking_reason"]
    b = area(client, "business", PARTNER)
    if level(b, "reviewed")["status"] != "signed":
        assert sign(client, REVIEWER, "business", "reviewed").status_code == 201
    r = sign(client, PARTNER, "business", "partner")
    assert r.status_code == 409 and f"adjustment #{big['id']}" in r.json()["detail"]
    assert post(client, PARTNER, f"/api/adjustments/{big['id']}/approve").status_code == 200
    assert f"adjustment:{big['id']}" not in inbox(client, handled=False)
    assert sign(client, PARTNER, "business", "partner").status_code == 201


# ---- client questions ------------------------------------------------------------------------------------

def test_client_answer_becomes_evidence_on_the_graph(client):
    key = "finding:questionnaire:qa-25"
    q = post(client, PREPARER, "/api/client-questions", {
        "item_key": key, "addressed_to_id": CLIENT, "blocking": True,
        "question": "Was Erik eligible for an employer health plan in 2025 (SSN 123-45-6789 on file)?"}).json()
    assert q["target_ref"] == "line:v3:Sch1.17" and "123-45-6789" not in q["question"] and "6789" in q["question"]
    items = inbox(client)
    assert items[f"question:{q['id']}"]["group"] == "blockers"
    assert items[key]["links"]["questions"] == [{"id": q["id"], "status": "asked"}]
    ready = get(client, PREPARER, "/api/filing/readiness").json()
    assert not next(c for c in ready["checks"] if c["key"] == "client_questions")["ok"]

    # the client sees only client-facing fields, and only questions addressed to them
    mine = get(client, CLIENT, "/api/client-questions").json()
    seen = next(x for x in mine if x["id"] == q["id"])
    assert "item_key" not in seen and "target_ref" not in seen and seen["about"]
    assert q["id"] not in [x["id"] for x in get(client, CLIENT2, "/api/client-questions").json()]
    assert post(client, CLIENT2, f"/api/client-questions/{q['id']}/answer", {"answer": "no"}).status_code == 403
    assert post(client, PREPARER, f"/api/client-questions/{q['id']}/answer", {"answer": "no"}).status_code == 403
    assert post(client, PREPARER, f"/api/client-questions/{q['id']}/accept", {}).status_code == 409   # not answered yet
    a = post(client, CLIENT, f"/api/client-questions/{q['id']}/answer",
             {"answer": "No. My employer's plan only covered me, and Erik was not eligible for it."})
    assert a.status_code == 200 and a.json()["status"] == "answered"
    assert post(client, CLIENT, f"/api/client-questions/{q['id']}/accept", {}).status_code == 403
    acc = post(client, PREPARER, f"/api/client-questions/{q['id']}/accept", {"note": "Answer supports the deduction.", "resolves_item": True})
    assert acc.status_code == 200 and acc.json()["evidence_node"] == f"client_answer:{q['id']}"

    items = inbox(client)
    assert items[key]["status"] == "handled" and items[key]["handled"]["kind"] == "client_answer"
    assert items[f"question:{q['id']}"]["status"] == "handled"
    node = get(client, REVIEWER, "/api/graph/node?ref=line:v3:Sch1.17").json()
    assert any(e["type"] == "CONFIRMED_BY" and e["other"] == f"client_answer:{q['id']}" and e["other_kind"] == "ClientAnswer"
               for e in node["outgoing"])
    assert not any(e.get("other", "").startswith("client_answer:") for e in
                   get(client, CLIENT, "/api/graph/node?ref=line:v3:Sch1.17").json()["outgoing"])      # internal overlay
    assert next(c for c in get(client, PREPARER, "/api/filing/readiness").json()["checks"] if c["key"] == "client_questions")["ok"]


# ---- judgment ledger ---------------------------------------------------------------------------------------

def test_judgment_options_come_from_the_packet(idx):
    opts = {o["option"]: o for o in J.options(idx, ["SchE.14A"])}
    hvac = opts["what_if:hvac_improvement"]
    assert hvac["related"] and (hvac["federal"], hvac["california"]) == (3633, 896) and hvac["source"] == "engine_alternative"
    assert opts["keep_engine"]["federal"] == 0 and opts["other"]["federal"] is None
    effect, alts, required = J.prepare(idx, decision_option="keep_engine", alternatives=[{"option": "what_if:hvac_improvement"}])
    assert effect["tax_at_stake"] == 3633 and required == "partner"
    effect, alts, required = J.prepare(idx, decision_option="other", alternatives=[{"option": "keep_engine"}])
    assert effect["federal"] is None and effect["tax_at_stake"] is None and required == "reviewer"
    for bad in ([], [{"option": "keep_engine"}, {"option": "keep_engine"}]):
        with pytest.raises(J.JudgmentError):
            J.prepare(idx, decision_option="what_if:nope" if not bad else "keep_engine", alternatives=bad or [{"option": "other"}])


def test_judgment_ledger_records_reviews_and_supersedes(client):
    opts = get(client, PREPARER, f"/api/judgments/options?item_key={HVAC.replace('#', '%23')}").json()
    assert opts["suggestion"]["target_refs"] == ["line:v3:SchE.14A"]
    body = {"item_key": HVAC, "topic": "HVAC replacement at 1450 Fremont Way: repair or improvement",
            "target_refs": ["line:v3:SchE.14A"], "decision": "Capitalize as an improvement.",
            "decision_option": "what_if:hvac_improvement",
            "alternatives": [{"option": "keep_engine", "why_not": "A whole-system replacement is a betterment."}],
            "rationale": "Call notes: the entire system was replaced with a heat pump, new air handler and line set.",
            "authority": "Treas. Reg. 1.263(a)-3(j) (betterment) and (k) (restoration)", "evidence_refs": ["call-01", "D47"]}
    assert post(client, PREPARER, "/api/judgments", body | {"authority": "  "}).status_code == 422
    assert post(client, PREPARER, "/api/judgments", body | {"alternatives": []}).status_code == 422
    assert post(client, PREPARER, "/api/judgments", body | {"evidence_refs": ["D99"]}).status_code == 422
    assert post(client, CLIENT, "/api/judgments", body).status_code == 403
    r = post(client, PREPARER, "/api/judgments", body)
    assert r.status_code == 201
    j = r.json()
    assert j["tax_effect"]["federal"] == 3633 and j["tax_effect"]["source"] == "engine_alternative"
    assert j["review_required"] == "partner" and j["status"] == "recorded" and j["areas"] == ["rentals"]
    assert j["alternatives"][0]["federal"] == 0 and j["prepared_by"] == "Priya Raman"
    items = inbox(client)
    assert items[HVAC]["status"] == "handled" and items[HVAC]["handled"]["kind"] == "judgment"
    assert items[f"judgment:{j['id']}"]["group"] == "judgment"
    assert post(client, PREPARER, "/api/judgments", body).status_code == 409                      # item already handled

    assert post(client, PREPARER, f"/api/judgments/{j['id']}/review", {}).status_code == 403       # no review permission
    assert post(client, REVIEWER, f"/api/judgments/{j['id']}/review", {"note": "agree"}).json()["status"] == "reviewed"
    assert post(client, REVIEWER, f"/api/judgments/{j['id']}/review", {}).status_code == 403       # partner step
    done = post(client, PARTNER, f"/api/judgments/{j['id']}/review", {"note": "approved"}).json()
    assert done["status"] == "approved" and done["reviewed_by"] == "Daniel Ortiz" and done["partner_by"] == "Helen Strand"
    assert f"judgment:{j['id']}" not in inbox(client, handled=False)
    node = get(client, REVIEWER, "/api/graph/node?ref=line:v3:SchE.14A").json()
    assert any(e["other"] == f"judgment:{j['id']}" and e["other_kind"] == "Judgment" for e in node["outgoing"])

    rev = post(client, PREPARER, "/api/judgments", body | {"supersedes_id": j["id"], "decision": "Capitalize; placed in service June.",
                                                           "item_key": None})
    assert rev.status_code == 201 and rev.json()["supersedes_id"] == j["id"] and rev.json()["item_key"] == HVAC
    all_j = {x["id"]: x for x in get(client, REVIEWER, "/api/judgments?include_superseded=true").json()}
    assert all_j[j["id"]]["status"] == "superseded"
    assert j["id"] not in [x["id"] for x in get(client, REVIEWER, "/api/judgments").json()]
    assert post(client, PREPARER, "/api/judgments", body | {"supersedes_id": j["id"], "item_key": None}).status_code == 409


# ---- review follow-ups (after the Iteration 7 review): escalation holds on every path -------------------

def test_escalation_cannot_be_bypassed_through_another_endpoint(client, no_adjustments):
    """An escalated item is the partner's: no adjustment, judgment, client answer, note endpoint or
    approval may handle it for anyone else."""
    finding = MILEAGE.split(":", 1)[1]
    proposed = post(client, PREPARER, "/api/adjustments", {"target_line": "SchC.44a", "adjusted_value": 8100, "reason": "dup page",
                                                           "finding_id": finding}).json()
    assert post(client, PREPARER, "/api/inbox/escalate", {"key": MILEAGE, "note": "Partner to decide the mileage"}).status_code == 200
    for r in (post(client, PREPARER, f"/api/adjustments/{proposed['id']}/apply"),
              post(client, REVIEWER, f"/api/adjustments/{proposed['id']}/apply"),
              post(client, PREPARER, "/api/adjustments/from-finding", {"finding_id": finding, "apply": True})):
        assert r.status_code == 403 and "escalated" in r.json()["detail"], r.json()
    bulk = post(client, REVIEWER, "/api/adjustments/bulk", {"action": "apply", "ids": [proposed["id"]]})
    assert bulk.status_code == 409 and "escalated" in bulk.json()["detail"]["errors"][0]["detail"]
    j = {"item_key": MILEAGE, "topic": "Mileage", "target_refs": ["line:v3:SchC.44a"], "decision": "Keep 11,800",
         "decision_option": "keep_engine", "alternatives": [{"option": "other"}], "rationale": "Both scans are distinct trips?",
         "authority": "IRC 274(d)"}
    assert post(client, PREPARER, "/api/judgments", j).status_code == 403
    q = post(client, PREPARER, "/api/client-questions", {"item_key": MILEAGE, "question": "Did you drive these May-Aug trips once or twice?"}).json()
    post(client, CLIENT, f"/api/client-questions/{q['id']}/answer", {"answer": "Once - page 3 is a rescan."})
    assert post(client, PREPARER, f"/api/client-questions/{q['id']}/accept", {"resolves_item": True}).status_code == 403
    item = inbox(client)[MILEAGE]
    assert item["status"] == "open" and item["group"] == "blockers"
    # the partner decides — by any of those routes
    assert post(client, PARTNER, f"/api/client-questions/{q['id']}/accept", {"resolves_item": False}).status_code == 200
    assert post(client, PARTNER, f"/api/adjustments/{proposed['id']}/apply").status_code == 200
    assert inbox(client)[MILEAGE]["status"] == "handled"

    # an escalated review note cannot be cleared through the notes endpoint by a reviewer
    note = post(client, REVIEWER, "/api/workpaper/notes", {"target_ref": "line:v3:SchC.8", "kind": "review_note",
                                                            "body": "Support the advertising spend."}).json()
    post(client, REVIEWER, "/api/inbox/escalate", {"key": f"note:{note['id']}", "note": "Partner call on materiality"})
    r = post(client, REVIEWER, f"/api/workpaper/notes/{note['id']}/resolve", {"resolution": "fine"})
    assert r.status_code == 403 and "escalated" in r.json()["detail"]
    assert post(client, PARTNER, f"/api/workpaper/notes/{note['id']}/resolve", {"resolution": "Immaterial; agreed."}).status_code == 200

    # an escalated approval: neither the approval nor an undo by someone else handles it
    adj = post(client, PREPARER, "/api/adjustments", {"target_line": "SchC.17", "adjusted_value": 1650, "reason": "invoice"}).json()
    post(client, PREPARER, "/api/inbox/escalate", {"key": f"adjustment:{adj['id']}", "note": "Unusual expense"})
    assert post(client, REVIEWER, f"/api/adjustments/{adj['id']}/approve").status_code == 403
    assert post(client, PREPARER, f"/api/adjustments/{adj['id']}/undo").status_code == 403
    assert post(client, PARTNER, f"/api/adjustments/{adj['id']}/approve").status_code == 200


# ---- the filing gate -----------------------------------------------------------------------------------------

def test_filing_opens_only_when_everything_is_decided_and_signed(client, no_adjustments):
    """Disposition everything, sign every area — then (and only then) the gate opens; one new blocking
    review note closes it again."""
    from app.api.collaboration import assert_can_file  # noqa: F401  (the gate Iteration 8 calls)

    for key, it in inbox(client, PARTNER, handled=False).items():
        if it["source"] == "question":
            post(client, PARTNER, f"/api/client-questions/{it['detail']['question_id']}/withdraw", {"note": "not needed"})
        elif it["source"] == "judgment":
            jid = it["detail"]["judgment_id"]
            for user in (REVIEWER, PARTNER):
                post(client, user, f"/api/judgments/{jid}/review", {})
        elif it["source"] == "adjustment":
            post(client, PARTNER, f"/api/adjustments/{it['detail']['adjustment_id']}/undo")
        elif it["source"] == "note":
            assert post(client, PARTNER, "/api/inbox/resolve", {"key": key, "note": "cleared for the test"}).status_code == 200
        else:
            assert post(client, PARTNER, "/api/inbox/accept", {"key": key, "note": "accepted for the gate test"}).status_code == 200
    assert inbox(client, handled=False) == {}
    ready = get(client, PREPARER, "/api/filing/readiness").json()
    assert not ready["can_file"] and [c["key"] for c in ready["checks"] if not c["ok"]] == ["signoffs"]

    for a in get(client, PREPARER, "/api/signoffs").json()["areas"]:
        for user, lvl in ((PREPARER, "prepared"), (REVIEWER, "reviewed"), (PARTNER, "partner")):
            if level(area(client, a["key"]), lvl)["status"] != "signed":
                r = sign(client, user, a["key"], lvl)
                if r.status_code == 403 and lvl == "reviewed":     # the reviewer prepared this area earlier in the suite
                    r = sign(client, PARTNER, a["key"], lvl)
                assert r.status_code == 201, (a["key"], lvl, r.json())
    ready = get(client, PREPARER, "/api/filing/readiness").json()
    assert ready["can_file"] is True, [c for c in ready["checks"] if not c["ok"]]

    note = post(client, QR, "/api/workpaper/notes", {"target_ref": "engagement", "kind": "review_note",
                                                       "body": "Confirm the engagement letter covers the FBAR."}).json()
    ready = get(client, PREPARER, "/api/filing/readiness").json()
    assert ready["can_file"] is False and [c["key"] for c in ready["checks"] if not c["ok"]] == ["blocking_notes"]
    post(client, QR, "/api/inbox/resolve", {"key": f"note:{note['id']}", "note": "Confirmed: FBAR is out of scope."})
    assert get(client, PREPARER, "/api/filing/readiness").json()["can_file"] is True


def test_readiness_is_a_pure_function_of_items_and_signoffs():
    note = IB.Item("note:1", "note", "review", "Review note", "x", "high", ["engagement"], [], blocks_filing=True)
    r = IB.readiness([note], [])
    assert not r["can_file"] and r["checks"][0]["count"] == 1
    assert IB.readiness([], [])["can_file"] is True
    unsigned = [{"key": "business", "title": "Business", "complete": False,
                 "levels": [{"label": "Reviewed", "status": "reopened"}, {"label": "Partner", "status": "not_signed"}]}]
    r = IB.readiness([], unsigned)
    assert not r["can_file"] and r["checks"][-1]["areas"][0]["missing"] == ["Reviewed reopened", "Partner not signed"]


# ---- review follow-ups (after the Iteration 7 review) ----------------------------------------------------

SSN = "078-05-1120"  # synthetic


def test_no_free_text_anywhere_leaks_an_ssn(client):
    """Every free-text field a person can type, in every record type, comes back masked — in each API and in
    the graph's metadata — for an uncleared preparer and everyone else."""
    t = f"see SSN {SSN}"
    j = post(client, PREPARER, "/api/judgments", {
        "topic": f"Topic {t}", "target_refs": ["line:v3:SchC.8"], "decision": f"Decision {t}", "decision_option": "keep_engine",
        "alternatives": [{"option": "other", "description": f"Alt {t}", "why_not": f"Why {t}"}],
        "rationale": f"Rationale {t}", "authority": f"Authority {t}", "evidence_refs": []}).json()
    post(client, REVIEWER, f"/api/judgments/{j['id']}/review", {"note": f"Review {t}"})
    note = post(client, REVIEWER, "/api/workpaper/notes", {"target_ref": "line:v3:SchC.8", "kind": "review_note", "body": f"Body {t}"}).json()
    post(client, PREPARER, "/api/inbox/escalate", {"key": f"note:{note['id']}", "note": f"Escalate {t}"})
    post(client, PARTNER, "/api/inbox/resolve", {"key": f"note:{note['id']}", "note": f"Resolution {t}"})
    q = post(client, PREPARER, "/api/client-questions", {"target_ref": "line:v3:SchC.8", "question": f"Question {t}"}).json()
    post(client, CLIENT, f"/api/client-questions/{q['id']}/answer", {"answer": f"Answer {t}"})
    post(client, PREPARER, f"/api/client-questions/{q['id']}/accept", {"note": f"Accepted {t}"})
    adj = post(client, PREPARER, "/api/adjustments", {"target_line": "SchC.18", "adjusted_value": 1050, "reason": f"Reason {t}"}).json()
    post(client, PREPARER, f"/api/adjustments/{adj['id']}/undo", {"note": f"Undo {t}"})
    post(client, PREPARER, "/api/verifications", {"target_ref": "line:v3:SchC.8", "method": "recalculated", "note": f"Verified {t}"})
    post(client, PREPARER, "/api/graph/links", {"src_ref": "line:v3:SchC.8", "dst_ref": "D23", "type": "RELATED_TO", "note": f"Link {t}"})
    sign(client, PREPARER, "deductions", "prepared")

    views = ["/api/judgments?include_superseded=true", "/api/inbox?include_handled=true", "/api/client-questions",
             "/api/signoffs", "/api/filing/readiness", "/api/adjustments", "/api/workpaper/notes",
             "/api/verifications?target_ref=line:v3:SchC.8", "/api/graph/links", "/api/graph/node?ref=line:v3:SchC.8",
             "/api/graph/prove?ref=line:v3:SchC.8", "/api/graph/trace?ref=line:v3:SchC.8", f"/api/graph/node?ref=judgment:{j['id']}",
             f"/api/graph/node?ref=client_answer:{q['id']}", "/api/adjustments/effective/SchC.18"]
    for user in (UNCLEARED, PREPARER, PARTNER):
        for v in views:
            r = get(client, user, v)
            assert r.status_code == 200, (user, v, r.status_code)
            assert SSN not in r.text, (user, v)
    assert SSN not in get(client, CLIENT, "/api/client-questions").text
    assert SSN not in get(client, PARTNER, "/api/audit/events?limit=1000").text


def test_downstream_areas_reopen_when_a_calculation_they_rest_on_changes(client, no_adjustments):
    """California rests on the Schedule C profit: a mileage correction reopens it too, and says how."""
    for user, lvl in ((PREPARER, "prepared"), (REVIEWER, "reviewed"), (PARTNER, "partner")):
        if level(area(client, "california"), lvl)["status"] != "signed":
            assert sign(client, user, "california", lvl).status_code == 201
    a = post(client, PREPARER, "/api/adjustments/from-finding", {"finding_id": MILEAGE.split(":", 1)[1], "apply": True}).json()
    assert a["effect"]["california"] != 0
    assert {("california", "reviewed"), ("california", "partner")} <= {(r["area"], r["level"]) for r in a["reopened_signoffs"]}
    reason = level(area(client, "california"), "reviewed")["reopen_reasons"][-1]
    assert reason["scope"] == "downstream" and reason["via"] and area_of_line(client, reason["via"]) == "california"
    assert f"Adjustment #{a['id']} applied on SchC.44a" in reason["detail"]
    # the area of the changed line itself is "direct"
    assert level(area(client, "business"), "reviewed")["reopen_reasons"][-1]["scope"] == "direct"
    # a payment correction flows only into payment totals: California stays signed
    for user, lvl in ((REVIEWER, "reviewed"), (PARTNER, "partner")):
        assert sign(client, user, "california", lvl).status_code == 201
    pay = post(client, PREPARER, "/api/adjustments", {"target_line": "F1040.26", "adjusted_value": 18000, "reason": "transcript",
                                                      "apply": True}).json()
    assert "california" not in {r["area"] for r in pay["reopened_signoffs"]}
    assert level(area(client, "california"), "reviewed")["status"] == "signed"


def area_of_line(client, key):
    from app.packet import get_index
    from app.services.areas import area_for_line
    return area_for_line(get_index().line("v3", key))


def test_revising_a_judgment_reopens_the_areas_it_used_to_support(client):
    body = {"topic": "Rental supplies", "target_refs": ["line:v3:SchE.16A"], "decision": "Deduct as supplies",
            "decision_option": "keep_engine", "alternatives": [{"option": "other", "description": "Capitalize"}],
            "rationale": "Consumed within the year; under the de minimis threshold.", "authority": "Treas. Reg. 1.162-3"}
    j = post(client, PREPARER, "/api/judgments", body).json()
    assert j["review_required"] == "reviewer"
    post(client, REVIEWER, f"/api/judgments/{j['id']}/review", {})
    for user, lvl in ((PREPARER, "prepared"), (REVIEWER, "reviewed"), (PARTNER, "partner")):
        if level(area(client, "rentals"), lvl)["status"] != "signed":
            assert sign(client, user, "rentals", lvl).status_code == 201, sign(client, user, "rentals", lvl).json()
    rev = post(client, PREPARER, "/api/judgments", body | {"supersedes_id": j["id"], "target_refs": ["line:v3:F1040.26"],
                                                           "topic": "Moved to payments"}).json()
    reopened = {(r["area"], r["level"]) for r in rev["reopened_signoffs"]}
    assert {("rentals", "reviewed"), ("rentals", "partner")} <= reopened
    reason = level(area(client, "rentals"), "reviewed")["reopen_reasons"][-1]
    assert f"revising #{j['id']}" in reason["detail"]


def test_an_accepted_client_answer_can_be_cited_as_evidence(client):
    q = post(client, PREPARER, "/api/client-questions", {"target_ref": "line:v3:SchC.15",
                                                         "question": "Is the 1,450 insurance policy for the studio only?"}).json()
    post(client, CLIENT, f"/api/client-questions/{q['id']}/answer", {"answer": "Yes, business only."})
    ref = f"client_answer:{q['id']}"
    body = {"target_ref": "line:v3:SchC.15", "method": "confirmed_with_client", "note": "Client confirmed business use.",
            "evidence_refs": [ref]}
    r = post(client, PREPARER, "/api/verifications", body)
    assert r.status_code == 422 and "not been accepted" in r.json()["detail"]            # answered, not yet accepted
    post(client, PREPARER, f"/api/client-questions/{q['id']}/accept", {})
    r = post(client, PREPARER, "/api/verifications", body)
    assert r.status_code == 201, r.json()
    assert post(client, PREPARER, "/api/verifications", body | {"evidence_refs": ["client_answer:99999"]}).status_code == 422
    assert post(client, PREPARER, "/api/verifications", body | {"method": "agreed_to_agency_record"}).status_code == 422  # wrong kind
    vid = f"verification:{r.json()['id']}"
    node = get(client, REVIEWER, f"/api/graph/node?ref={vid}").json()
    assert any(e["type"] == "CONFIRMED_BY" and e["other"] == ref for e in node["outgoing"])
    # the same answer can support an adjustment, a judgment and a link
    assert post(client, PREPARER, "/api/adjustments", {"target_line": "SchC.15", "adjusted_value": 1400, "reason": "per client",
                                                       "evidence_refs": [ref]}).status_code == 201
    assert post(client, PREPARER, "/api/graph/links", {"src_ref": "line:v3:SchC.15", "dst_ref": ref, "type": "CONFIRMED_BY",
                                                       "note": "client confirmation"}).status_code == 201
    j = post(client, PREPARER, "/api/judgments", {"topic": "Studio insurance", "target_refs": ["line:v3:SchC.15"], "decision": "Deduct",
                                                  "decision_option": "keep_engine", "alternatives": [{"option": "other"}],
                                                  "rationale": "Business-only policy per the client.", "authority": "IRC 162(a)",
                                                  "evidence_refs": [ref]})
    assert j.status_code == 201
    node = get(client, REVIEWER, f"/api/graph/node?ref={ref}").json()
    assert {e["other"].split(":")[0] for e in node["incoming"]} >= {"verification", "adjustment", "judgment", "line"}
