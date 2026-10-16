import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
BACKEND = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND / ".env", env_prefix="TAXPROOF_", extra="ignore")

    packet_path: Path = ROOT / "okafor_lindqvist_2025_packet.json"
    # PostgreSQL is the primary target (docker compose). SQLite is accepted for tests / zero-dependency runs.
    database_url: str = f"sqlite:///{BACKEND / 'taxproof.db'}"
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]
    run_migrations_on_startup: bool = True
    # Optional AI model (Iteration 9). Without a key TaxProof uses its deterministic grounded writer.
    ai_api_key: str | None = None
    ai_model: str = "claude-opus-5-5"
    ai_base_url: str = "https://api.anthropic.com"


def _driver_url(url: str) -> str:
    """Hosted Postgres (Vercel / Neon, Render, Heroku …) hands out postgres:// URLs; SQLAlchemy needs the driver."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


settings = Settings()
if not os.environ.get("TAXPROOF_DATABASE_URL"):
    # On a host that provisions the database itself, use the URL it injects (pooled first).
    for var in ("POSTGRES_URL", "DATABASE_URL"):
        if os.environ.get(var):
            settings.database_url = os.environ[var]
            break
settings.database_url = _driver_url(settings.database_url)
SERVERLESS = bool(os.environ.get("VERCEL"))
if SERVERLESS and not settings.database_url.startswith("postgresql"):
    # The serverless filesystem is read-only and per-instance: SQLite would fail or silently lose every write.
    # Name only the scheme — never echo the value, which may hold a password.
    scheme = settings.database_url.split(":", 1)[0] if ":" in settings.database_url else "empty"
    raise RuntimeError("No PostgreSQL database configured: set DATABASE_URL (or POSTGRES_URL) to a postgresql:// "
                       f"connection string for this deployment (current value starts with '{scheme}').")
