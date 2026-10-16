from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import adjustments, ai, challenge, collaboration, core, evidence, examiner, filing, graph, intel, returns, schedules, twin, workpaper
from .bootstrap import run_migrations, seed
from .config import settings
from .db import SessionLocal
from .packet import get_index
from .services.evidence import get_analysis
from .services.assurance import challenge as run_challenge
from .services.graph import get_graph
from .services import search, standards


@asynccontextmanager
async def lifespan(app: FastAPI):
    idx = get_index()  # load + freeze + hash the packet once
    get_analysis(idx)  # deterministic evidence checks, cached by packet hash
    get_graph(idx)  # evidence graph over the packet, cached by packet hash
    run_challenge(idx, idx.current_version)  # independent assurance checks for the current return
    search.warm(idx)  # search index + LSA latent space, cached by packet hash
    if settings.run_migrations_on_startup:
        run_migrations(settings.database_url)
    with SessionLocal() as db:
        seed(db, idx)
        standards.load(db, idx)  # the firm's current standards (Iteration 9)
    yield


app = FastAPI(title="TaxProof API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])

for r in (core.router, returns.router, evidence.router, graph.router, schedules.router, challenge.router, adjustments.router, collaboration.router, filing.router, examiner.router, ai.router, intel.router, twin.router, workpaper.router):
    app.include_router(r)


@app.get("/api/health")
def health():
    idx = get_index()
    return {"status": "ok", "packet_sha256": idx.packet.sha256, "current_version": idx.current_version,
            "database": settings.database_url.split(":", 1)[0]}
