from sqlalchemy import update

from app.config import settings
from app.models import AuditEvent
from app.packet.loader import sha256_of
from tests.conftest import as_user

PREPARER, UNCLEARED, REVIEWER, PARTNER, ADMIN, QR, CLIENT = "st-01", "st-04", "st-02", "st-03", "st-05", "st-06", "cu-01"


def test_health_and_seeded_users(client, idx):
    assert client.get("/api/health").json()["packet_sha256"] == idx.packet.sha256
    users = client.get("/api/session/users").json()
    assert {u["id"] for u in users} == {"st-01", "st-02", "st-03", "st-04", "st-05", "st-06", "cu-01", "cu-02"}
    marcus = next(u for u in users if u["id"] == UNCLEARED)
    assert marcus["engagement_roles"] == ["preparer"]  # joined via timeline tl-09
    assert not marcus["sensitive_data_clearance"]


def test_unknown_user_is_rejected(client):
    assert client.get("/api/session/me", headers=as_user("nobody")).status_code == 401


def test_me_reflects_role(client):
    me = client.get("/api/session/me", headers=as_user(CLIENT)).json()
    assert me["role"] == "client" and "view_internal_notes" not in me["permissions"]


def test_household_is_masked_for_everyone(client):
    for u in (PARTNER, UNCLEARED, CLIENT):
        body = client.get("/api/household", headers=as_user(u)).text
        assert "666-41-2287" not in body and "4483019276" not in body and "482915" not in body


def test_reveal_is_permissioned_and_logged(client):
    denied = client.post("/api/sensitive/reveal", json={"field_ref": "household:ngozi.ssn"}, headers=as_user(UNCLEARED))
    assert denied.status_code == 403
    ok = client.post("/api/sensitive/reveal", json={"field_ref": "household:ngozi.ssn"}, headers=as_user(REVIEWER))
    assert ok.status_code == 200 and ok.json()["value"] == "666-41-2287"
    assert client.post("/api/sensitive/reveal", json={"field_ref": "household:ngozi.dob"},
                       headers=as_user(REVIEWER)).status_code == 404
    logs = client.get("/api/audit/access-logs", headers=as_user(QR)).json()
    entries = {(l["user_id"], l["field_ref"], l["granted"]) for l in logs}
    assert (UNCLEARED, "household:ngozi.ssn", False) in entries
    assert (REVIEWER, "household:ngozi.ssn", True) in entries


def test_access_log_requires_permission(client):
    assert client.get("/api/audit/access-logs", headers=as_user(PREPARER)).status_code == 403


def test_client_cannot_view_firm_or_audit(client):
    assert client.get("/api/firm", headers=as_user(CLIENT)).status_code == 403
    assert client.get("/api/audit/events", headers=as_user(CLIENT)).status_code == 403
    assert client.get("/api/return/summary", headers=as_user(CLIENT)).status_code == 200


def test_notes_persist_and_respect_roles(client):
    # preparer may add a note but not a review note
    r = client.post("/api/workpaper/notes", headers=as_user(PREPARER),
                    json={"target_ref": "line:v3:SchC.44a", "body": "Agreed page totals to D23."})
    assert r.status_code == 201 and r.json()["area_key"] == "business" and r.json()["blocking"] is False
    assert client.post("/api/workpaper/notes", headers=as_user(PREPARER),
                       json={"target_ref": "D23", "kind": "review_note", "body": "x"}).status_code == 403

    rn = client.post("/api/workpaper/notes", headers=as_user(REVIEWER),
                     json={"target_ref": "doc:D23#page3", "kind": "review_note", "body": "Page 3 repeats page 2?"})
    assert rn.status_code == 201 and rn.json()["blocking"] is True  # open review notes block filing
    note_id = rn.json()["id"]

    # client cannot read internal notes and cannot write
    assert client.get("/api/workpaper/notes", headers=as_user(CLIENT)).json() == []
    assert client.post("/api/workpaper/notes", headers=as_user(CLIENT),
                       json={"target_ref": "D23", "body": "hi"}).status_code == 403

    # preparer cannot clear a review note; reviewer can, once
    assert client.post(f"/api/workpaper/notes/{note_id}/resolve", headers=as_user(PREPARER),
                       json={"resolution": "done"}).status_code == 403
    ok = client.post(f"/api/workpaper/notes/{note_id}/resolve", headers=as_user(REVIEWER),
                     json={"resolution": "Confirmed duplicate; tracked for Iteration 5 finding."})
    assert ok.status_code == 200 and ok.json()["status"] == "resolved"
    assert client.post(f"/api/workpaper/notes/{note_id}/resolve", headers=as_user(REVIEWER),
                       json={"resolution": "again"}).status_code == 409

    listed = client.get("/api/workpaper/notes?target_ref=doc:D23%23page3", headers=as_user(PARTNER)).json()
    assert [n["id"] for n in listed] == [note_id]


def test_notes_must_point_at_real_references(client):
    for bad in ("ev-9999", "line:v3:NOPE", "area:nowhere", "D99"):
        r = client.post("/api/workpaper/notes", headers=as_user(PREPARER), json={"target_ref": bad, "body": "x"})
        assert r.status_code == 422, bad


def test_return_endpoints(client):
    v = client.get("/api/return/versions").json()
    assert v["current"] == "v3" and [x["version"] for x in v["versions"]] == ["v1", "v2", "v3"]
    line = client.get("/api/return/lines/SchC.44a?version=v1").json()
    assert line["value"] == 11800 and line["version"] == "v1"
    assert client.get("/api/return/lines/SchC.44a?version=v9").status_code == 404
    docs = client.get("/api/documents").json()
    d30 = next(d for d in docs["documents"] if d["id"] == "D30")
    assert d30["superseded_in_current"] and d30["extraction_status"] == "partial"


def test_audit_chain_verifies_and_detects_tampering(client):
    v = client.get("/api/audit/verify", headers=as_user(PARTNER)).json()
    assert v["valid"] and v["events"] > 3
    with client.Session() as db:
        first = db.query(AuditEvent).order_by(AuditEvent.seq).first()
        original = dict(first.payload)
        db.execute(update(AuditEvent).where(AuditEvent.seq == first.seq).values(payload={"tampered": True}))
        db.commit()
        try:
            broken = client.get("/api/audit/verify", headers=as_user(PARTNER)).json()
            assert broken["valid"] is False and broken["broken_at_seq"] == first.seq
        finally:
            db.execute(update(AuditEvent).where(AuditEvent.seq == first.seq).values(payload=original))
            db.commit()
    assert client.get("/api/audit/verify", headers=as_user(PARTNER)).json()["valid"]


def test_permission_denials_are_audited(client):
    client.get("/api/firm", headers=as_user(CLIENT))
    events = client.get("/api/audit/events?limit=500", headers=as_user(PARTNER)).json()
    assert any(e["action"] == "permission.denied" and e["actor_id"] == CLIENT for e in events)


def test_source_packet_never_mutated_by_workflows(client, idx):
    """Run last-ish: after all API activity above, the file on disk and in memory are unchanged."""
    assert sha256_of(settings.packet_path) == idx.packet.sha256
    assert idx.values_by_id["ev-0315"]["value"] == 3700
    assert idx.people_by_id["theo"]["ssn"] == "666-74-3309"
