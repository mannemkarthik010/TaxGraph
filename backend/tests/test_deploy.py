"""Deployment plumbing: hosted Postgres URLs and the optional access gate."""

from app.config import _driver_url
from tests.conftest import as_user


def test_hosted_postgres_urls_get_the_driver():
    assert _driver_url("postgres://u:p@h/db?sslmode=require") == "postgresql+psycopg://u:p@h/db?sslmode=require"
    assert _driver_url("postgresql://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert _driver_url("postgresql+psycopg://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert _driver_url("sqlite:///x.db") == "sqlite:///x.db"


def test_the_access_gate_is_off_by_default_and_closes_the_api_when_set(client, monkeypatch):
    assert client.get("/api/session/me", headers=as_user("st-01")).status_code == 200
    monkeypatch.setenv("TAXPROOF_ACCESS_CODE", "open-sesame-2025")
    assert client.get("/api/session/me", headers=as_user("st-01")).status_code == 401
    assert client.get("/api/health").status_code == 200                                     # health stays open
    assert client.get("/api/session/me", headers=as_user("st-01") | {"X-TaxProof-Access": "wrong"}).status_code == 401
    assert client.get("/api/session/me", headers=as_user("st-01") | {"X-TaxProof-Access": "open-sesame-2025"}).status_code == 200
    client.cookies.set("tp_access", "open-sesame-2025")
    try:
        assert client.get("/api/session/me", headers=as_user("st-01")).status_code == 200    # the web app's cookie
    finally:
        client.cookies.clear()
