"""Runtime configuration, read from environment variables and ``backend/.env``."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR.parent / "data"
VAR_DIR = BACKEND_DIR / "var"  # runtime state: database, keys, registry (git-ignored)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", extra="ignore")

    # Upstream Valio Aimo mock APIs (credentials stay server-side; trust-protocol §3)
    valio_api_base_url: str = ""
    valio_api_key: str = ""
    upstream_cache_ttl_seconds: int = 300  # fulfilment §7.1

    # Paths
    data_dir: Path = DATA_DIR
    var_dir: Path = VAR_DIR

    # Gateway identity
    public_base_url: str = "http://127.0.0.1:8000"
    access_token_ttl_seconds: int = 900  # trust-protocol §4.3: minutes, not days

    # Fulfilment behaviour (fulfilment-and-substitution §7.2, §13)
    cutoff_policy: str = "strict"  # "strict" | "lenient"

    # Offers (trust-protocol §6.1)
    offer_fallback_ttl_minutes: int = 30  # when the cut-off has passed or is unknown
    offer_max_ttl_hours: int = 24

    # Audit (audit-log §4.3, §6.2)
    checkpoint_every_events: int = 100
    checkpoint_every_minutes: int = 10
    abandoned_after_hours: int = 24

    # Frontend and demo (frontend.md §4.3, §4.6)
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    demo_mode: bool = False  # enables /dev/* endpoints and the tamper preview
    human_session_ttl_seconds: int = 12 * 3600
    upstream_mode: str = "live"  # "live" | "fixture" (B6)
    fixture_file: Path = BACKEND_DIR / "tests" / "fixtures" / "milk_2026-11-16.json"
    # With a fixture, start the clock at the recording time and let it run in real time.
    clock_start: str | None = None

    # Notifications (frontend.md §4.4)
    notify_async: bool = True
    vapid_subject: str = "mailto:notifications@veripantry.example"
    reminder_before_minutes: int = 60

    @property
    def db_path(self) -> Path:
        return self.var_dir / "veripantry.sqlite"

    @property
    def keys_dir(self) -> Path:
        return self.var_dir / "keys"

    @property
    def registry_path(self) -> Path:
        return self.var_dir / "registry.json"

    @property
    def policies_dir(self) -> Path:
        return self.var_dir / "policies"


settings = Settings()
