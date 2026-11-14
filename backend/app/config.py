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
