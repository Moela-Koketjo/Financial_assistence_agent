"""Dashboard settings — the UI holds no secrets, only where to find the agent API."""

import logging

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """Dashboard configuration loaded from environment variables or .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    APP_NAME: str = Field("My Finance Agent", description="Page title")
    API_URL: str = Field(
        "http://127.0.0.1:8000",
        description="Base URL of the agent service API",
    )
    IMPORT_POLL_INTERVAL: float = Field(
        2.0,
        description="Seconds between import job status checks",
    )
    IMPORT_POLL_TIMEOUT: float = Field(
        300.0,
        description="Seconds to wait for an import job before giving up",
    )


# Global settings instance — import this everywhere
settings = Settings()
