import os
import re
import tempfile

# Point the app at an isolated database *before* app modules are imported.
# Default: a throwaway SQLite file. Set TAXPROOF_TEST_DATABASE_URL to run the same suite on PostgreSQL;
# that database's public schema is dropped and recreated (migrations run from scratch), so never point
# it at a database you care about.
_pg = os.environ.get("TAXPROOF_TEST_DATABASE_URL")
if _pg:
    if "test" not in _pg.rsplit("/", 1)[-1]:
        raise RuntimeError("TAXPROOF_TEST_DATABASE_URL must name a database containing 'test'.")
    import sqlalchemy as sa

    _engine = sa.create_engine(_pg, isolation_level="AUTOCOMMIT")
    with _engine.connect() as conn:
        conn.execute(sa.text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(sa.text("CREATE SCHEMA public"))
    _engine.dispose()
    os.environ["TAXPROOF_DATABASE_URL"] = _pg
else:
    _tmpdir = tempfile.mkdtemp(prefix="taxproof-test-")
    os.environ["TAXPROOF_DATABASE_URL"] = f"sqlite:///{_tmpdir}/test.db"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.packet import get_index  # noqa: E402


@pytest.fixture(scope="session")
def idx():
    return get_index()


def isolated_client(schema: str):
    """Yield a TestClient bound to a fresh database of its own — a new SQLite file, or its own PostgreSQL
    schema — migrated and seeded from the packet. Every test module gets one, so no module can see what
    another left behind and the suite passes in any file order."""
    import sqlalchemy as sa
    from sqlalchemy.orm import sessionmaker

    from app.bootstrap import run_migrations, seed
    from app.db import get_db, make_engine
    from app.services import standards

    base = os.environ["TAXPROOF_DATABASE_URL"]
    if base.startswith("sqlite"):
        url = f"sqlite:///{tempfile.mkdtemp(prefix=f'taxproof-{schema}-')}/test.db"
    else:
        admin = sa.create_engine(base, isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            conn.execute(sa.text(f"DROP SCHEMA IF EXISTS {schema} CASCADE"))
            conn.execute(sa.text(f"CREATE SCHEMA {schema}"))
        admin.dispose()
        url = base + ("&" if "?" in base else "?") + f"options=-csearch_path%3D{schema}"
    run_migrations(url)
    engine = make_engine(url)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override
    try:
        with TestClient(app) as c:  # lifespan (packet caches); this module's data lives in its own database
            with Session() as db:
                seed(db, get_index())
                standards.load(db, get_index())  # process-wide standards follow this module's database
            c.Session = Session
            yield c
    finally:
        app.dependency_overrides.pop(get_db, None)
        standards.reset(get_index())
        engine.dispose()


@pytest.fixture(scope="module")
def client(request):
    name = re.sub(r"[^a-z0-9_]", "_", request.module.__name__.rsplit(".", 1)[-1].lower())
    yield from isolated_client(f"t_{name}")


def as_user(user_id: str) -> dict:
    return {"X-TaxProof-User": user_id}
