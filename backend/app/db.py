from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


def make_engine(url: str):
    if not url.startswith("sqlite"):
        return create_engine(url, pool_pre_ping=True)
    eng = create_engine(url, connect_args={"check_same_thread": False})

    # pysqlite starts transactions lazily (only before DML), so a SAVEPOINT can open — and its RELEASE
    # commit — a transaction of its own, surviving a later rollback. Let SQLAlchemy own the transaction,
    # as the SQLAlchemy docs recommend, so rollback and savepoints behave as they do on PostgreSQL.
    @event.listens_for(eng, "connect")
    def _no_driver_transactions(dbapi_conn, _record):
        dbapi_conn.isolation_level = None

    @event.listens_for(eng, "begin")
    def _begin(conn):
        conn.exec_driver_sql("BEGIN")

    return eng


engine = make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
