import pytest

from app.services import schedules as S
from app.services.area_summary import AREA_KEY_LINES, traceable_lines
from app.services.areas import AREAS
from tests.conftest import as_user

V = "v3"


def _checks(sched):
    return {c["check"]: c for c in sched["checks"]}


# ---- books to tax --------------------------------------------------------------------------------------

def test_books_to_tax_reconciles_to_the_dollar(idx):
    b = S.books_to_tax(idx, V)
    assert b["start"] == {"label": "Books net income", "value": 89834.0, "ref": "ev-0105"}
    assert b["end"]["value"] == 81854
    assert b["start"]["value"] + sum(r["effect"] for r in b["rows"]) == pytest.approx(81854)
    assert all(c["agrees"] for c in b["checks"])


def test_books_to_tax_items_are_derived_from_citations(idx):
    rows = {r["key"] or r["label"]: r for r in S.books_to_tax(idx, V)["rows"]}
    assert rows["SchC.1"]["effect"] == 12400 and rows["SchC.1"]["books_refs"] == ["ev-0103"]
    assert rows["SchC.13"]["effect"] == -38000 and "7,600" in rows["SchC.13"]["note"]
    assert rows["SchC.24b"]["effect"] == 1980                       # meals at 50%
    assert rows["Insurance - health (Erik) (books)"]["effect"] == 14400   # not deducted on Schedule C
    assert rows["SchC.8"].get("unchanged") is True                  # advertising carried as booked


# ---- depreciation -------------------------------------------------------------------------------------

def test_depreciation_ties_to_prior_schedule_and_engine_totals(idx):
    d = S.depreciation(idx, V)
    assert len(d["assets"]) == 9
    checks = _checks(d)
    assert all(c["agrees"] for c in d["checks"]), [c for c in d["checks"] if not c["agrees"]]
    assert "SAC-BLDG prior accumulated depreciation" in checks
    assert any("F4562-C.22" in c["check"] for c in d["checks"])
    aus = next(a for a in d["assets"] if a["asset_id"] == "AUS-BLDG")
    assert aus["disposed"] == "2025-10-15" and aus["disposition"]["unrecaptured_1250_depreciation"] > 0
    studio = [a for a in d["assets"] if a["asset_id"].startswith("STU-") and a["new_in_year"]]
    assert studio and all(a["federal_vs_california"] > 0 for a in studio)  # CA disallows bonus depreciation


# ---- brokerage ----------------------------------------------------------------------------------------

def test_brokerage_summarises_hundreds_of_lots(idx):
    b = S.brokerage(idx, V)
    lot_lines = [k for k in idx.return_lines_by_version[V] if k.startswith("F8949.") and not k.endswith(".total")]
    assert b["lot_count"] == len(lot_lines) == 295
    assert sum(g["lots"] for g in b["groups"]) == 295
    assert len(b["groups"]) < 15
    assert all(c["agrees"] for c in b["checks"])
    brightpath = [g for g in b["groups"] if g["document_id"] == "D74"]
    assert sum(g["lots"] for g in brightpath) == 260


def test_brokerage_lots_on_demand_with_attention_filter(idx):
    page = S.brokerage_lots(idx, V, box="A", document_id="D74", limit=10)
    assert page["total"] == 110 and len(page["items"]) == 10
    gains = [abs(x["gain"]) for x in page["items"]]
    assert gains == sorted(gains, reverse=True)
    attention = S.brokerage_lots(idx, V, attention=True, limit=50)["items"]
    keys = {x["key"] for x in attention}
    assert "F8949.H.C6" in keys            # crypto lot with no basis
    assert "F8949.B.N1" in keys            # RSU basis "(not reported)" read as 0
    assert "F8949.F.SCORP" not in keys     # an engine-computed line is not a sale missing basis
    assert S.brokerage(idx, V)["attention"]["lots"] == len(attention)  # unique lots, not flag count


# ---- rentals, K-1/basis, state, carryovers ------------------------------------------------------------

def test_rentals(idx):
    r = S.rentals(idx, V)
    props = {p["letter"]: p for p in r["properties"]}
    assert props["A"]["net"] == -15957 and props["B"]["disposed"] == "2025-10-15"
    assert {a["asset_id"] for a in props["A"]["assets"]} == {"SAC-BLDG", "SAC-APPL", "SAC-ROOF"}
    assert all(c["agrees"] for c in r["checks"])
    assert r["suspended_losses"]["into_year"] == {"passive_1450_fremont": 6300, "passive_1200_barton_hills": 9850}


def test_scorp_basis_rolled_forward_independently(idx):
    k = S.k1_basis(idx, V)
    years = {r["year"]: r for r in k["scorp_basis"]}
    assert years[2022]["ending"] == 21300
    assert years[2023]["ending"] == 15400       # needs the late 2023 K-1 (D40)
    assert years[2024]["ending"] == 2300
    assert years[2025]["ending"] == 0 and years[2025]["excess_distribution"] == 21215
    assert all(c["agrees"] for c in k["checks"])
    assert {x["document_id"] for x in k["k1s"]} == {"D37", "D38", "D39", "D40"}
    assert k["partnership"]["outside_basis_known"] is False


def test_basis_roll_forward_reports_a_gap_without_the_2023_k1(idx):
    """v1/v2 were computed before the 2023 K-1 (D40) arrived: basis cannot be proven, so TaxProof reports
    the gap and the engine's assumption instead of a number built from later evidence."""
    for v in ("v1", "v2"):
        k = S.k1_basis(idx, v)
        assert k["checks"] == []
        assert k["gap"]["year"] == 2023 and k["gap"]["engine_beginning"] == 8200
        assert k["scorp_basis"][-1]["gap"] and "D40 arrived 2026-06-05" in k["scorp_basis"][-1]["source"]
        d40 = next(x for x in k["k1s"] if x["document_id"] == "D40")
        assert d40["received_after_version"] is True
    assert S.k1_basis(idx, "v3")["gap"] is None


def test_state_allocation_and_residency(idx):
    st = S.state_allocation(idx, V)
    assert all(c["agrees"] for c in st["checks"])
    ratio = _checks(st)["Deduction percentage = CA AGI / total AGI"]
    assert ratio["taxproof"] == 0.6347
    rows = {r["line"]: r for r in st["rows"]}
    assert rows["12"]["columns"]["C"] == 30400 and rows["12"]["notes"]
    res = st["residency"]
    assert [(p["state"], p["days"]) for p in res["periods"]] == [("CA", 195), ("TX", 170)]
    assert res["checks"][0]["agrees"]
    sale = next(e for e in res["events"] if e["kind"] == "closing_statement_seller")
    assert sale["date"] == "2025-10-15" and sale["state"] == "TX"


def test_ratio_check_fails_when_off_by_more_than_a_basis_point():
    c = S._check("r", 0.6349, 0.6347, [], "", precision=4, tolerance=0.0001)
    assert c["agrees"] is False


def test_carryovers(idx):
    rows = {r["item"]: r for r in S.carryovers(idx, V)["rows"]}
    assert rows["capital_loss_long"]["into_year"] == 11000 and rows["capital_loss_long"]["used_by"][0]["key"] == "SchD.14"
    assert rows["passive_1450_fremont"]["status"] == "used"
    assert rows["minimum_tax_credit_from_2025_amt"]["status"] == "new" and rows["minimum_tax_credit_from_2025_amt"]["out_of_year"] == 3871


def test_tax_computation_and_prior_year_mapping(idx):
    t = S.tax_computation(idx, V)
    fed = [r["key"] for r in t["federal"]]
    assert fed.index("F1040.11") < fed.index("F1040.15") < fed.index("F1040.24") < fed.index("F1040.37")
    ca = {r["key"]: r for r in t["california"]}
    assert ca["F540NR.64"]["prior_year"] == 12520          # mapped by meaning to 2024 Form 540 line 64
    assert ca["F540NR.32"]["prior_year"] is None           # 540 line 32 means something else: not compared
    py = S.prior_year_comparison(idx, V)
    assert py["flagged"] == sum(1 for r in py["rows"] if r["variance_flag"]) > 0
    assert any(r["key"] == "F540NR.64" and r["prior_year_key"] == "CA540.64" for r in py["rows"])


# ---- area summaries -----------------------------------------------------------------------------------

def test_area_key_lines_exist(idx):
    lines = idx.return_lines_by_version[V]
    for area, keys in AREA_KEY_LINES.items():
        assert keys[0] in lines, area


def test_traceability(idx):
    t = traceable_lines(idx, V)
    assert t["SchC.9"] and t["F1040.24"]          # through inputs down to cited evidence
    assert len(t) == len(idx.return_lines_by_version[V])


def test_area_summary_api(client):
    h = as_user("st-02")
    client.post("/api/verifications", headers=as_user("st-01"), json={"target_ref": "ev-0226", "method": "agreed_to_source_document"})
    client.post("/api/workpaper/notes", headers=h, json={"target_ref": "area:business", "kind": "review_note", "body": "Explain the 12,400"})
    areas = {a["key"]: a for a in client.get("/api/workpaper/area-summaries", headers=h).json()["areas"]}
    assert set(areas) == {a.key for a in AREAS}
    biz = areas["business"]
    assert biz["figures"][0]["key"] == "SchC.31" and biz["figures"][0]["prior_year"] == 71900
    assert biz["evidence"]["verified_values"] >= 1 and biz["issues"]["blocking_notes"] >= 1
    assert biz["schedules"] == ["books-to-tax", "depreciation"]
    assert areas["deductions"]["issues"]["conflicts"] >= 1          # the D64 handwritten gift / D62 provider ID
    detail = client.get("/api/workpaper/area-summaries/investments", headers=h).json()
    preview = {l["key"] for l in detail["lines_preview"]}
    assert detail["lots_hidden"] == 295 and "F8949.A.total" in preview
    assert not any(k.startswith("F8949") and not k.endswith(".total") for k in preview)
    assert client.get("/api/workpaper/area-summaries/nowhere", headers=h).status_code == 404
    # clients see figures but not internal workpaper counts
    cl = {a["key"]: a for a in client.get("/api/workpaper/area-summaries", headers=as_user("cu-01")).json()["areas"]}
    assert cl["business"]["issues"]["open_notes"] == 0 and cl["business"]["evidence"]["verified_values"] == 0


def test_schedule_api(client):
    h = as_user("st-01")
    for name in S.SCHEDULES:
        assert client.get(f"/api/workpaper/schedules/{name}", headers=h).status_code == 200, name
    assert client.get("/api/workpaper/schedules/books-to-tax?version=v1", headers=h).json()["version"] == "v1"
    assert client.get("/api/workpaper/schedules/nope", headers=h).status_code == 404
    assert client.get("/api/workpaper/schedules/brokerage?version=v9", headers=h).status_code == 404
    lots = client.get("/api/workpaper/schedules/brokerage/lots?box=H&limit=5", headers=h).json()
    assert lots["total"] == 7 and len(lots["items"]) == 5
    assert client.get("/api/workpaper/schedules/residency", headers=h).json()["periods"][0]["state"] == "CA"


# ---- regression: notes attached to evidence count in the areas that use that evidence -------------------

def test_areas_for_ref(idx):
    from app.services.area_summary import areas_for_ref
    assert areas_for_ref(idx, "area:rentals", V) == {"rentals"}
    assert areas_for_ref(idx, "line:v3:SchC.44a", V) == {"business"}
    assert areas_for_ref(idx, "SchC.9", V) == {"business"}
    assert areas_for_ref(idx, "ev-0315", V) == {"business"}            # mileage page total
    assert areas_for_ref(idx, "doc:D23#page2", V) == {"business"}      # its page
    assert areas_for_ref(idx, "D23", V) == {"business"}                # its document
    assert areas_for_ref(idx, "D39", V) >= {"k1_basis"}                # a K-1 feeds several areas
    assert areas_for_ref(idx, "engagement", V) == set()
    assert areas_for_ref(idx, "D72", V) == set()                       # unused document: no area


def test_evidence_notes_count_in_area_summaries(client):
    """Regression: a blocking review note on ev-0315 left Business at 0 blocking notes."""
    h = as_user("st-03")

    def biz():
        return next(a for a in client.get("/api/workpaper/area-summaries", headers=h).json()["areas"] if a["key"] == "business")

    before = biz()["issues"]
    created = []
    for ref in ("ev-0315", "doc:D23#page3", "D23"):
        r = client.post("/api/workpaper/notes", headers=h, json={"target_ref": ref, "kind": "review_note", "body": f"check {ref}"})
        assert r.status_code == 201
        created.append(r.json()["id"])
    after = biz()["issues"]
    assert after["open_notes"] == before["open_notes"] + 3
    assert after["blocking_notes"] == before["blocking_notes"] + 3
    detail = client.get("/api/workpaper/area-summaries/business", headers=h).json()
    via = {n["target_ref"]: n["via"] for n in detail["open_notes"]}
    assert via["ev-0315"] == "evidence" and via["D23"] == "evidence"
    # the overview's area tiles use the same rule
    tiles = {a["key"]: a for a in client.get("/api/workpaper/areas", headers=h).json()}
    assert tiles["business"]["open_notes"] >= 3
    # resolving a note removes it from the count
    client.post(f"/api/workpaper/notes/{created[0]}/resolve", headers=h, json={"resolution": "Checked"})
    assert biz()["issues"]["blocking_notes"] == after["blocking_notes"] - 1


# ---- regressions from the Iteration 1–5 review: shared schedules respect the evidence cutoff ----------

def _doc_ids(obj, idx):
    """Every document a schedule's output points at, directly or through an extracted value / page ref."""
    from app.packet.refs import resolve
    found = set()
    def walk(x):
        if isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, str) and (x.startswith(("ev-", "doc:")) or (len(x) == 3 and x[0] == "D" and x[1:].isdigit())):
            r = resolve(idx, x)
            if r.exists and r.document_id:
                found.add(r.document_id)
    walk(obj)
    return found


@pytest.mark.parametrize("version", ["v1", "v2", "v3"])
def test_schedules_never_use_evidence_received_after_their_version(idx, version):
    cutoff = idx.versions_by_id[version]["computed_at"]
    late = {}
    for name in ("books-to-tax", "state-allocation"):
        late[name] = [d for d in _doc_ids(S.SCHEDULES[name](idx, version), idx) if idx.documents_by_id[d]["received_at"] > cutoff]
    k = S.k1_basis(idx, version)
    late["k1-basis roll-forward"] = [d for d in _doc_ids(k["scorp_basis"] + k["checks"], idx) if idx.documents_by_id[d]["received_at"] > cutoff]
    assert all(v == [] for v in late.values()), late
