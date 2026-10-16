"""Vercel entry point for the TaxProof API (FastAPI as a Python serverless function).

The application lives in backend/app; this file only puts backend/ on the import path and exposes the ASGI app.
The database is prepared on the first request (see app.main.ensure_ready)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.main import app  # noqa: E402,F401
