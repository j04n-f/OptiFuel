from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """The only reader of environment variables: `OPTIFUEL_<FIELD>`."""

    model_config = SettingsConfigDict(env_prefix="OPTIFUEL_")

    environment: Literal["dev", "prod"] = "dev"
