import hmac
import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from .api import adjustments, ai, challenge, collaboration, core, evidence, examiner, filing, graph, intel, returns, schedules, twin, workpaper
from .bootstrap import run_migrations, seed
from .config import settings
from .db import SessionLocal, engine
from .packet import get_index
from .services.evidence import get_analysis
from .services.assurance import challenge as run_challenge
from .services.graph import get_graph
from .services import search, standards


_ready = threading.Lock()
_done = False


def ensure_ready() -> None:
    """Warm the packet caches and bring the database to head, once per process.

    Runs from the lifespan hook locally, and on the first request where a host (e.g. a serverless platform)
    does not run lifespan. On PostgreSQL an advisory lock makes concurrent cold starts migrate one at a time."""
    global _done
    if _done:
        return
    with _ready:
        if _done:
            return
        idx = get_index()  # load + freeze + hash the packet once
        get_analysis(idx)  # deterministic evidence checks, cached by packet hash
        get_graph(idx)  # evidence graph over the packet, cached by packet hash
        run_challenge(idx, idx.current_version)  # independent assurance checks for the current return
        search.warm(idx)  # search index + LSA latent space, cached by packet hash
        if settings.run_migrations_on_startup:
            if settings.database_url.startswith("postgresql"):
                with engine.connect() as conn:
                    conn.exec_driver_sql("SELECT pg_advisory_lock(727274)")
                    try:
                        run_migrations(settings.database_url)
                    finally:
                        conn.exec_driver_sql("SELECT pg_advisory_unlock(727274)")
            else:
                run_migrations(settings.database_url)
        with SessionLocal() as db:
            seed(db, idx)
            standards.load(db, idx)  # the firm's current standards (Iteration 9)
        _done = True


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_ready()
    yield


app = FastAPI(title="TaxProof API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])

@app.middleware("http")
async def _first_request(request, call_next):
    ensure_ready()  # no-op after the first call
    return await call_next(request)


@app.middleware("http")
async def _access_code(request, call_next):
    """Optional gate for a shared deployment: with TAXPROOF_ACCESS_CODE set, every API call (except health) must
    carry the code — the web app's cookie (forwarded through its /api proxy) or the X-TaxProof-Access header."""
    code = os.environ.get("TAXPROOF_ACCESS_CODE")
    if code and request.url.path != "/api/health":
        given = request.cookies.get("tp_access") or request.headers.get("x-taxproof-access") or ""
        if not hmac.compare_digest(given.encode(), code.encode()):
            return JSONResponse({"detail": "Access code required."}, status_code=401)
    return await call_next(request)


for r in (core.router, returns.router, evidence.router, graph.router, schedules.router, challenge.router, adjustments.router, collaboration.router, filing.router, examiner.router, ai.router, intel.router, twin.router, workpaper.router):
    app.include_router(r)


@app.get("/api/health")
def health():
    idx = get_index()
    return {"status": "ok", "packet_sha256": idx.packet.sha256, "current_version": idx.current_version,
            "database": settings.database_url.split(":", 1)[0]}
