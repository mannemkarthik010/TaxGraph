from app.services.evidence import (
    check_value, document_statuses, find_duplicate_pages, get_analysis, locate, where_used,
)
from tests.conftest import as_user

PREPARER, UNCLEARED, REVIEWER, PARTNER, CLIENT = "st-01", "st-04", "st-02", "st-03", "cu-01"


def _ev(**kw):
    base = {"id": "ev-x", "document_id": "D00", "page": 1, "field": "box1", "label": "Box 1 wages", "value": 100.0,
            "value_type": "money", "text_as_read": "100.00", "position": {}, "confidence": 0.99}
    return base | kw


# ---- value checks (unit) ---------------------------------------------------------------------------

def test_matching_value_has_no_flags():
    assert check_value(_ev(), "Box 1 100.00; Box 2 5.00", set()) == []


def test_high_confidence_misread_is_a_conflict():
    flags = check_value(_ev(value=1500.0, text_as_read="1,500.00"), "Received $?,500.00", set())
    assert [f.code for f in flags] == ["PRINTED_MISMATCH"] and flags[0].severity == "conflict"


def test_blank_field_recorded_as_zero_needs_review():
    flags = check_value(_ev(value=0.0, text_as_read=""), "basis (not reported) short-term", set())
    assert [f.code for f in flags] == ["VALUE_NOT_PRINTED"] and flags[0].severity == "review"


def test_text_transposition_is_a_conflict():
    ev = _ev(value="74-3829516", value_type="ein", text_as_read="74-3829516")
    assert [f.code for f in check_value(ev, "Tax ID 74-3829156.", set())] == ["PRINTED_MISMATCH"]


def test_dates_match_any_printed_format():
    ev = _ev(value="2026-01-12", value_type="date", text_as_read="")
    assert check_value(ev, "Signed 01/12/2026", set()) == []
    assert check_value(ev, "Signed January 12, 2026", set()) == []
    assert [f.code for f in check_value(ev, "Signed 01/13/2026", set())] == ["PRINTED_MISMATCH"]


def test_ssn_not_in_organizer_is_identity_conflict():
    ev = _ev(value="666-74-3390", value_type="ssn", text_as_read="666-74-3390")
    flags = check_value(ev, "Card 666-74-3390", {"666-74-3309"})
    assert [f.code for f in flags] == ["IDENTITY_MISMATCH"]


def test_low_confidence_flag():
    assert [f.code for f in check_value(_ev(confidence=0.5), "Box 1 100.00", set())] == ["LOW_CONFIDENCE"]


# ---- packet analysis -------------------------------------------------------------------------------

def test_packet_confident_mistakes_are_surfaced(idx):
    flags = {k: [f.code for f in v] for k, v in get_analysis(idx).value_flags.items()}
    assert flags["ev-1045"] == ["PRINTED_MISMATCH"]                       # D62 provider TIN transposed, conf 0.97
    assert "PRINTED_MISMATCH" in flags["ev-1049"]                          # D64 ambiguous '$?,500.00'
    assert flags["ev-0498"] == ["VALUE_NOT_PRINTED"]                       # D28 RSU basis 'not reported' -> 0
    assert flags["ev-1080"] == ["IDENTITY_MISMATCH"]                       # D71 Theo's card vs organizer
    assert idx.values_by_id["ev-1045"]["confidence"] > 0.9                 # confidence alone would not catch it
    assert "ev-0315" not in flags                                          # correct reading stays clean


def test_duplicate_page_detection_finds_only_the_mileage_rescan(idx):
    a = get_analysis(idx)
    assert set(a.duplicate_pages) == {"D23"}
    assert a.duplicate_pages["D23"][0]["pages"] == [2, 3]
    # template-alike brokerage pages with different numbers are not duplicates
    assert find_duplicate_pages(idx, "D28") == []


def test_duplicate_and_corrected_documents(idx):
    a = get_analysis(idx)
    assert a.duplicate_documents["D10"][0]["duplicate_of"] == "D09"
    assert a.corrected_pairs["D30"] == {"corrected_by": "D31"}
    assert a.corrected_pairs["D31"] == {"corrects": "D30"}


def test_locate_finds_the_value_in_printed_text(idx):
    a = get_analysis(idx)
    text = idx.documents_by_id["D23"]["pages"][1]["printed_content"]
    s, e = a.value_spans["ev-0315"]
    assert text[s:e] == "3,700" and "Page total" in text[s - 15:s]


def test_locate_disambiguates_repeated_amounts_by_label(idx):
    # W-2 boxes 3 and 5 both print 112,000.00; each value must land after its own box label.
    text = idx.documents_by_id["D08"]["pages"][0]["printed_content"]
    vals = {ev["field"]: ev for ev in idx.values_by_document["D08"]}
    s3, _ = locate(text, vals["box3"])
    s5, _ = locate(text, vals["box5"])
    assert s3 != s5
    assert text[s3 - 6:s3].strip() == "Box 3" and text[s5 - 6:s5].strip() == "Box 5"


def test_document_statuses(idx):
    codes = lambda d: [s["code"] for s in document_statuses(idx, d)]  # noqa: E731
    assert codes("D30") == ["superseded", "partial"]
    assert codes("D31") == ["used", "corrected", "partial"]
    assert codes("D23") == ["used", "duplicate"]
    assert codes("D10") == ["used", "duplicate"]
    assert codes("D71")[0] == "unused" and "conflict" in codes("D71")
    assert codes("D72") == ["unused", "not_extracted"]
    assert "after v3 was computed" in document_statuses(idx, "D72")[0]["detail"]
    assert codes("D16") == ["used"]


def test_where_used_spans_versions_and_prior_year(idx):
    w = where_used(idx, "ev-0315")
    assert {(l["version"], l["key"]) for l in w["lines"]} == {("v1", "SchC.44a"), ("v2", "SchC.44a"), ("v3", "SchC.44a")}
    py_src = next(pv for pv in idx.prior_year_values.values() if pv["source"])
    assert where_used(idx, py_src["source"])["prior_year_lines"][0]["key"] == py_src["key"]
    assert where_used(idx, "ev-1049")["diagnostics"][0]["code"] == "LOW_CONFIDENCE_READ"


# ---- API -------------------------------------------------------------------------------------------

def test_document_index_has_statuses(client):
    body = client.get("/api/documents", headers=as_user(REVIEWER)).json()
    assert body["counts"]["duplicate"] == 2 and body["counts"]["superseded"] == 1
    d62 = next(d for d in body["documents"] if d["id"] == "D62")
    assert d62["conflict_count"] == 1


def test_document_detail_masks_printed_content_and_locates_values(client):
    d = client.get("/api/documents/D08", headers=as_user(PARTNER)).json()
    page = d["pages"][0]
    assert "666-41-2287" not in page["printed_content"]
    ssn = next(v for v in page["values"] if v["value_type"] == "ssn")
    assert ssn["masked"] and page["printed_content"][ssn["span"][0]:ssn["span"][1]] == ssn["value"]
    box1 = next(v for v in page["values"] if v["field"] == "box1")
    assert page["printed_content"][box1["span"][0]:box1["span"][1]] == "104,600.00"
    assert d["renderer"] == "simulated_printed_content"


def test_document_detail_where_used_and_why_not_used(client):
    d23 = client.get("/api/documents/D23", headers=as_user(PREPARER)).json()
    assert "SchC.44a" in {l["key"] for l in d23["where_used"]["lines"]}
    assert d23["relations"]["duplicate_pages"][0]["pages"] == [2, 3]
    d72 = client.get("/api/documents/D72", headers=as_user(PREPARER)).json()
    assert d72["why_not_used"].startswith("Received 2028-01-26")
    assert client.get("/api/documents/D99", headers=as_user(PREPARER)).status_code == 404


def test_value_detail(client):
    v = client.get("/api/values/ev-0404", headers=as_user(PREPARER)).json()
    assert v["page"] == 3 and v["document_id"] == "D23" and v["value"] == 3700
    assert {l["key"] for l in v["where_used"]["lines"]} == {"SchC.44a"}
    assert client.get("/api/values/ev-9999", headers=as_user(PREPARER)).status_code == 404


def test_verification_workflow(client):
    post = lambda u, body: client.post("/api/verifications", headers=as_user(u), json=body)  # noqa: E731
    # one-click agreement for a clean value
    ok = post(PREPARER, {"target_ref": "ev-0226", "method": "agreed_to_source_document"})
    assert ok.status_code == 201 and ok.json()["verified_by_id"] == PREPARER
    vid = ok.json()["id"]
    # flagged value: agreement needs a note, and the flags are recorded as acknowledged
    assert post(PREPARER, {"target_ref": "ev-1045", "method": "agreed_to_source_document"}).status_code == 422
    ack = post(PREPARER, {"target_ref": "ev-1045", "method": "agreed_to_third_party_record",
                          "note": "Provider letterhead shows 74-3829156; extraction transposed digits."})
    assert ack.status_code == 201 and ack.json()["acknowledged_flags"] == ["PRINTED_MISMATCH"]
    # method rules
    assert post(PREPARER, {"target_ref": "ev-1049", "method": "confirmed_with_client", "note": "phone"}).status_code == 422
    assert post(PREPARER, {"target_ref": "ev-1049", "method": "confirmed_with_client",
                           "note": "Parish confirmed 1,500 by phone.", "evidence_refs": ["msg-08"]}).status_code == 201
    assert post(PREPARER, {"target_ref": "ev-0226", "method": "magic"}).status_code == 422
    assert post(PREPARER, {"target_ref": "qa-01", "method": "recalculated", "note": "x"}).status_code == 422
    assert post(PREPARER, {"target_ref": "ev-0226", "method": "agreed_to_prior_year", "note": "x",
                           "evidence_refs": ["py:/nope"]}).status_code == 422
    # lines can be verified too
    assert post(REVIEWER, {"target_ref": "line:v3:SchC.9", "method": "recalculated",
                           "note": "11,800 x 0.70 = 8,260"}).status_code == 201
    # roles
    assert post(CLIENT, {"target_ref": "ev-0226", "method": "agreed_to_source_document"}).status_code == 403
    assert client.get("/api/verifications", headers=as_user(CLIENT)).status_code == 403

    listed = client.get("/api/verifications?target_ref=ev-0226", headers=as_user(PARTNER)).json()
    assert [v["id"] for v in listed] == [vid]
    detail = client.get("/api/documents/D23", headers=as_user(PARTNER)).json()
    page1_total = next(v for v in detail["pages"][0]["values"] if v["id"] == "ev-0226")
    assert page1_total["verifications"][0]["method"] == "agreed_to_source_document"
    client_view = client.get("/api/documents/D23", headers=as_user(CLIENT)).json()
    assert "verifications" not in client_view["pages"][0]["values"][0]

    # withdrawal: not by another preparer, yes by a reviewer, only once; record is kept
    w = lambda u: client.post(f"/api/verifications/{vid}/withdraw", headers=as_user(u), json={"reason": "Page total re-added wrong"})  # noqa: E731
    assert w(UNCLEARED).status_code == 403
    assert w(REVIEWER).status_code == 200
    assert w(REVIEWER).status_code == 409
    assert client.get("/api/verifications?target_ref=ev-0226", headers=as_user(PARTNER)).json() == []
    kept = client.get("/api/verifications?target_ref=ev-0226&include_withdrawn=true", headers=as_user(PARTNER)).json()
    assert kept[0]["status"] == "withdrawn" and kept[0]["withdrawn_reason"] == "Page total re-added wrong"

    actions = {e["action"] for e in client.get("/api/audit/events?limit=500", headers=as_user(PARTNER)).json()}
    assert {"verification.created", "verification.withdrawn"} <= actions


def test_line_detail_carries_source_flags(client):
    d = client.get("/api/return/lines/F2441.1b", headers=as_user(PREPARER)).json()
    src = next(s for s in d["sources"] if s["ref"] == "ev-1045")
    assert src["detail"]["flags"][0]["code"] == "PRINTED_MISMATCH"


def test_verification_methods_must_cite_matching_evidence(client):
    post = lambda body: client.post("/api/verifications", headers=as_user(PREPARER), json=body)  # noqa: E731
    base = {"target_ref": "ev-0128", "note": "checked"}
    # "Confirmed with client" cannot rest on a document, page or extracted value…
    for ref in ("D23", "doc:D23#page2", "ev-0226", "agency:/efile"):
        r = post(base | {"method": "confirmed_with_client", "evidence_refs": [ref]})
        assert r.status_code == 422 and "cannot cite" in r.json()["detail"], ref
    # …nor on a mix that includes one
    assert post(base | {"method": "confirmed_with_client", "evidence_refs": ["qa-14", "D23"]}).status_code == 422
    # …only on what the client said
    for ref in ("qa-14", "msg-08", "call-01"):
        assert post(base | {"method": "confirmed_with_client", "evidence_refs": [ref]}).status_code == 201, ref
    # agency agreement must cite an agency record, prior-year agreement a prior-year source
    assert post(base | {"method": "agreed_to_agency_record", "evidence_refs": ["qa-14"]}).status_code == 422
    assert post(base | {"method": "agreed_to_agency_record", "evidence_refs": []}).status_code == 422
    assert post(base | {"method": "agreed_to_agency_record",
                        "evidence_refs": ["agency:/irs_account_transcript_2025/0"]}).status_code == 201
    assert post(base | {"method": "agreed_to_prior_year", "evidence_refs": ["msg-08"]}).status_code == 422
    assert post(base | {"method": "agreed_to_prior_year",
                        "evidence_refs": ["py:/return_2024/lines/F1040.24"]}).status_code == 201
