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


settings = Settings()
