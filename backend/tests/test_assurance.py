import pytest

from app.services import assurance as A
from tests.conftest import as_user

V = "v3"


@pytest.fixture(scope="module")
def findings(idx):
    return {f.id: f for f in A.challenge(idx, V)}


def _by_rule(findings, rule, status=None):
    return [f for f in findings.values() if f.rule == rule and (status is None or f.status == status)]


# ---- required demo case 1: duplicated mileage page ---------------------------------------------------

def test_mileage_duplicate_page(findings, idx):
    f = findings["dup-page:D23#p3:SchC.44a"]
    assert f.status == "fail" and f.family == "duplicate_page"
    assert f.engine["value"] == 11800 and f.independent["value"] == 8100 and f.difference == -3700
    assert f.unit == "miles"
    assert [b["value"] for b in f.breakdown] == [2600, 3700, 3700, 1800]
    assert [b["duplicate"] for b in f.breakdown] == [False, False, True, False]
    assert {"doc:D23#page2", "doc:D23#page3"} <= set(f.evidence)
    assert f.lines == ["SchC.44a", "SchC.9"]           # miles → dollars via the standard-mileage line
    rates = idx.versions_by_id[V]["tax_effect_rates"]["schc_profit"]
    dollars = 3700 * 0.7
    assert f.effect["federal"] == round(dollars * rates["federal_per_dollar"])   # lower expense → more profit → more tax
    assert f.effect["california"] == round(dollars * rates["california_per_dollar"])
    assert f.effect["estimate"] is True


# ---- required demo case 2: Paywell 1099-K already inside books revenue -------------------------------

def test_card_receipts_counted_twice(findings):
    f = findings["card-in-books:D21:SchC.1"]
    assert f.status == "fail" and f.family == "duplicate_transaction"
    assert f.engine["value"] == 163700 and f.independent["value"] == 151300 and f.difference == -12400
    assert "Paywell" in f.summary and "already inside recorded sales" in f.summary
    assert "doc:D15#page3" in f.evidence and "ev-0127" in f.evidence
    corroboration = {b["label"]: b["value"] for b in f.breakdown}
    assert corroboration["Forms 1099-NEC received"] + corroboration["Deposits from clients who issued no 1099 (books detail)"] == 151300
    assert f.effect["federal"] < 0 and f.partner_review is True


# ---- other independent findings ----------------------------------------------------------------------

def test_rsu_basis_from_plan_statement(findings):
    fails = {f.subject for f in _by_rule(findings, "supplemental-basis", "fail")}
    assert fails == {"F8949.B.N1", "F8949.B.N3", "F8949.E.N4"}
    assert findings["supplemental-basis:F8949.A.N2"].status == "pass"     # ESPP already adjusted by the engine
    n1 = findings["supplemental-basis:F8949.B.N1"]
    assert n1.difference == -19100 and n1.effect["ca_category"] == "ca_source_income"  # sold while a CA resident
    n4 = findings["supplemental-basis:F8949.E.N4"]
    assert n4.effect["ca_category"] == "ltcg"                                         # sold after the move


def test_no_false_positive_on_same_acquisition_date(findings):
    """A Harborview Insurance lot shares the RSU's 2023-08-15 acquisition date; it must not match the plan."""
    assert not [f for f in findings.values() if f.rule == "supplemental-basis" and "Harborview" in f.title]


def test_california_wages_after_move(findings):
    f = findings["ca-wages:SchCA540NR.1.E"]
    assert f.status == "fail" and f.engine["value"] == 218400
    assert f.independent["value"] == 107100 + 22469        # Corvane (ended before move) + Halvorsen YTD at the move
    assert f.effect["federal"] == 0 and f.effect["california"] < -5000


def test_payments_against_agency_records(findings):
    fed = findings["payments-federal:F1040.26"]
    assert fed.engine["value"] == 13000 and fed.independent["value"] == 12000
    assert fed.effect == {**fed.effect, "kind": "balance", "federal": 1000.0}
    ca = findings["payments-california:F540NR.72"]
    assert ca.engine["value"] == 14000 and ca.independent["value"] == 10500 and ca.effect["california"] == 3500
    assert any(b["year"] == "2024" for b in ca.breakdown)


def test_same_account_interest_and_fx_and_unread_page(findings):
    i = findings["same-account-interest:SchB.1.1+SchB.1.2"]
    assert i.status == "fail" and i.difference == -1840
    fx = findings["fx-period:SchB.1.6"]
    assert fx.status == "fail" and "2024 average" in fx.title and fx.difference > 0
    b = findings["broker-summary:D31"]
    assert b.status == "fail" and b.difference == 250 and b.breakdown[0]["page"] == 32
    assert "BROKER_SUMMARY_DETAIL_MISMATCH" in b.engine_diagnostics


def test_identity_and_extraction(findings):
    theo = next(f for f in findings.values() if f.rule == "identity")
    assert theo.severity == "critical" and "household:theo" in theo.evidence
    assert findings["extraction-conflict:ev-1045"].status == "fail"


def test_judgment_items_are_attention_not_errors(findings):
    sehi = findings["questionnaire:qa-25"]
    assert sehi.status == "attention" and sehi.judgment and sehi.effect["potential"] is True
    repair = next(f for f in findings.values() if f.rule == "repair-vs-improvement")
    assert repair.status == "attention" and repair.effect is None
    assert findings["questionnaire:qa-14"].engine_diagnostics == ["QUESTIONNAIRE_SALES_CONFLICT"]


def test_passing_checks_are_reported_too(findings):
    passed = {f.id for f in findings.values() if f.status == "pass"}
    assert "books-bridge:SchC.31" in passed
    assert "dup-doc:D10" in passed                 # the engine counted the W-2 photo once
    assert {"py-capital-loss:capital_loss_short", "py-capital-loss:capital_loss_long"} <= passed
    assert "w2-sum:F1040.1a" in passed
    assert any(i.startswith("page-total:D23") for i in passed)


def test_every_required_family_runs(findings):
    families = {f.family for f in findings.values()}
    required = {"duplicate_document", "duplicate_page", "duplicate_transaction", "source_totals", "cross_document",
                "prior_year", "books_to_tax", "broker_detail", "completeness", "basis", "state", "questionnaire",
                "payments", "carryovers"}
    assert required <= families


def test_findings_depend_on_the_version(idx):
    v2 = {f.id: f for f in A.challenge(idx, "v2")}
    assert v2["scorp-basis-gap:gap:2023"].status == "attention"                           # 2023 K-1 not yet in file
    assert "scorp-basis:Beginning stock basis (Form 7203 line 1)" not in v2                 # no number from later evidence
    assert v2["expected-k1:K-1-1065"].status == "fail"                                    # Ridgeline K-1 not yet received
    assert v2["ca-wages:SchCA540NR.1.E"].status == "pass"                                 # move-date paystub arrived later


def test_rules_never_touch_the_packet(idx):
    before = idx.packet.sha256
    A._CACHE.clear()
    A.challenge(idx, V)
    assert idx.packet.sha256 == before and idx.line(V, "SchC.44a")["value"] == 11800


# ---- API ---------------------------------------------------------------------------------------------

def test_challenge_api_and_runs(client):
    h = as_user("st-02")
    data = client.get("/api/challenge", headers=h).json()
    assert data["summary"]["by_status"]["fail"] >= 10 and data["last_run"] is None
    assert all(d["code"] for d in data["engine_diagnostics"])
    diag = {d["code"]: d for d in data["engine_diagnostics"]}
    assert "broker-summary:D31" in diag["BROKER_SUMMARY_DETAIL_MISMATCH"]["related_findings"]
    detail = client.get("/api/challenge/finding", params={"id": "dup-page:D23#p3:SchC.44a"}, headers=h).json()
    assert detail["impact"]["affected_lines"] > 50 and detail["evidence_resolved"][0]["exists"]
    assert client.get("/api/challenge/finding", params={"id": "nope"}, headers=h).status_code == 404
    assert client.get("/api/challenge", headers=as_user("cu-01")).status_code == 403
    assert client.post("/api/challenge/runs", headers=as_user("st-05")).status_code == 403

    first = client.post("/api/challenge/runs", headers=h).json()
    assert first["changes"]["since_run"] is None
    second = client.post("/api/challenge/runs", headers=as_user("st-03")).json()
    assert second["changes"] == {"since_run": first["id"], "new": [], "gone": [], "changed": [], "changed_detail": {}}
    assert client.get("/api/challenge", headers=h).json()["last_run"]["id"] == second["id"]
    v2 = client.post("/api/challenge/runs?version=v2", headers=h).json()
    assert v2["version"] == "v2" and v2["changes"]["since_run"] is None   # runs are per version
    actions = [e["action"] for e in client.get("/api/audit/events?limit=500", headers=as_user("st-03")).json()]
    assert actions.count("challenge.run") >= 3


# ---- regressions from the Iteration 5 review ---------------------------------------------------------

def _secrets(idx):
    """Every raw sensitive value in the packet: full SSNs, IP PINs, bank numbers, sensitive extracted values."""
    from app.security.masking import is_sensitive_value
    hh = idx.data["household"]
    out = {p["ssn"] for p in hh["people"] if p.get("ssn")} | {p["ip_pin"] for p in hh["people"] if p.get("ip_pin")}
    out |= {hh["bank_account_for_refund_or_payment"]["account"], hh["bank_account_for_refund_or_payment"]["routing"]}
    out |= {str(ev["value"]) for ev in idx.data["extracted_values"] if is_sensitive_value(ev) and ev["value"]}
    return {s for s in out if s and len(s) >= 6}


@pytest.mark.parametrize("user", ["st-04", "st-02", "st-03"])
def test_no_challenge_response_leaks_sensitive_values(client, idx, user):
    """Regression (P1): finding evidence returned an unmasked SSN, even to staff without clearance.
    Unmasked values are only ever available through the logged reveal endpoint."""
    secrets = _secrets(idx)
    h = as_user(user)
    for v in ("v1", "v2", "v3"):
        body = client.get(f"/api/challenge?version={v}", headers=h).text
        assert not [s for s in secrets if s in body], (v, "overview")
        for f in A.challenge(idx, v):
            text = client.get("/api/challenge/finding", params={"id": f.id, "version": v}, headers=h).text
            leaked = [s for s in secrets if s in text]
            assert not leaked, (v, f.id, leaked)


def _cutoff_violations(idx, version):
    from app.packet.refs import json_pointer, resolve
    cutoff = idx.versions_by_id[version]["computed_at"]
    bad = []
    for f in A.challenge(idx, version):
        for ref in f.evidence:
            r = resolve(idx, ref, version)
            if r.document_id and idx.documents_by_id[r.document_id]["received_at"] > cutoff:
                bad.append((f.id, ref))
            if ref.startswith("agency:"):
                node = json_pointer(idx.data["tax_agency_records"], ref[len("agency:"):])
                if isinstance(node, dict) and str(node.get("as_of", "")) > cutoff[:10]:
                    bad.append((f.id, ref))
    return bad


@pytest.mark.parametrize("version", ["v1", "v2", "v3"])
def test_no_finding_uses_evidence_from_after_its_version(idx, version):
    """Regression (P2): v1/v2 passed the SEP check with D26, received after both were computed."""
    assert _cutoff_violations(idx, version) == []


def test_sep_check_waits_for_the_contribution_confirmation(idx):
    assert not [f for f in A.challenge(idx, "v1") if f.rule == "carry-sep"]
    assert not [f for f in A.challenge(idx, "v2") if f.rule == "carry-sep"]
    assert [f.status for f in A.challenge(idx, "v3") if f.rule == "carry-sep"] == ["pass"]
    # with no transcript pulled yet, v1's federal payments are "not yet confirmable", not a pass or a fail
    v1 = {f.id: f for f in A.challenge(idx, "v1")}
    assert v1["payments-federal:F1040.26"].status == "attention"


@pytest.mark.parametrize("version", ["v1", "v2", "v3"])
def test_every_evidence_reference_resolves(idx, version):
    """Regression (P2): residency and wage findings cited a bare `household` that did not resolve."""
    from app.packet.refs import resolve
    unresolved = [(f.id, r) for f in A.challenge(idx, version) for r in f.evidence if not resolve(idx, r, version).exists]
    assert unresolved == []


def test_effects_are_split_into_tax_and_balance(idx):
    """Review: the headline mixed tax estimates with payment corrections."""
    fs = A.challenge(idx, V)
    e = A.summarize(idx, V, fs)["estimated_effect"]
    tax = [f for f in fs if f.status == "fail" and f.effect and f.effect["kind"] == "tax" and not f.effect.get("potential")]
    bal = [f for f in fs if f.status == "fail" and f.effect and f.effect["kind"] == "balance"]
    assert e["tax"]["federal"] == sum(f.effect["federal"] for f in tax) == -19637
    assert e["tax"]["california"] == sum(f.effect["california"] for f in tax) == -8873
    assert (e["balance"]["federal"], e["balance"]["california"]) == (1000, 3500)
    assert {f.rule for f in bal} == {"payments-federal", "payments-california"}


def test_run_history_detects_amount_changes(client):
    """Regression (P2): runs compared only status, so a $500 move in an amount went unreported."""
    from app.models import ChallengeRun
    h = as_user("st-02")
    run = client.post("/api/challenge/runs?version=v3", headers=h).json()
    with client.Session() as db:
        r = db.get(ChallengeRun, run["id"])
        results = [dict(x) for x in r.results]
        target = next(x for x in results if x["id"] == "dup-page:D23#p3:SchC.44a")
        target["difference"] += 500
        target["federal"] += 500
        tiny = next(x for x in results if x["id"] == "card-in-books:D21:SchC.1")
        tiny["federal"] += 0.4                       # rounding noise must not count
        r.results = results
        db.commit()
    changes = client.get("/api/challenge?version=v3", headers=h).json()["changes_since_last_run"]
    assert changes["changed"] == ["dup-page:D23#p3:SchC.44a"]
    detail = changes["changed_detail"]["dup-page:D23#p3:SchC.44a"]
    assert detail["difference"] == [-3200.0, -3700.0] and detail["federal"] == [1419.0, 919.0]
    again = client.post("/api/challenge/runs?version=v3", headers=h).json()
    assert again["changes"]["changed"] == ["dup-page:D23#p3:SchC.44a"]
    assert client.post("/api/challenge/runs?version=v3", headers=h).json()["changes"]["changed"] == []
