"""Configuration of the stub buyer agent (frontend.md §4.1)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

AGENT_DIR = Path(__file__).resolve().parent.parent
DEMO_DIR = AGENT_DIR.parent / "backend" / "var" / "dev"  # written by backend/scripts/dev_setup.py


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENT_", env_file=AGENT_DIR / ".env", extra="ignore")

    gateway_url: str = "http://127.0.0.1:8000"
    # The audience the mandate was issued for (the gateway's public URL).
    gateway_audience: str = "http://127.0.0.1:8000"
    key_file: Path = DEMO_DIR / "agent-ed25519.pem"
    mandate_file: Path = DEMO_DIR / "mandate.jwt"
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    # "Today" for relative dates ("by Monday"); set it when the gateway runs on recorded data.
    today: date | None = None


settings = AgentSettings()
