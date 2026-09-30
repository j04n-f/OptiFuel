from pathlib import Path
from typing import Literal

from pydantic import BaseModel, HttpUrl, PositiveInt, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Tenant(BaseModel):
    aircraft_types: frozenset[str]
    model_version: str


class Settings(BaseSettings):
    """The only reader of environment variables: `OPTIFUEL_<FIELD>`."""

    model_config = SettingsConfigDict(env_prefix="OPTIFUEL_")

    environment: Literal["dev", "prod"] = "dev"
    database_url: SecretStr
    # JSON, keyed by airline code. Empty rejects every caller: no tenant, no default.
    tenants: dict[str, Tenant] = {}
    # Worker only; `worker.py` refuses to start without them.
    worker_airline: str | None = None
    model_dir: Path = Path("/models")
    weather_url: HttpUrl | None = None
    weather_token: SecretStr | None = None
    # Cleanup only: finished jobs, failed included, are purged this many days after they end.
    retention_days: PositiveInt = 30
