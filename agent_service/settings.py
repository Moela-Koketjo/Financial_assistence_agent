import logging
import os
from urllib.parse import quote_plus

from pydantic import Field, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables or .env file.
    All agent files import from the global `settings` instance at the bottom.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # --- App ---
    APP_NAME: str = "My Finance Agent"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # --- Google Gemini ---
    # One model PER ROLE. The free tier's request quota is per model, so giving
    # each role its own model triples the usable daily budget. All three
    # defaults are vision-capable and verified working on a free-tier key.
    GOOGLE_API_KEY: str = Field(..., description="API key for Google Gemini")
    PARSE_MODEL: str = Field(
        "gemini-3.5-flash-lite",
        description="Vision model — statement image to transactions",
    )
    CATEGORIZE_MODEL: str = Field(
        "gemini-3.1-flash-lite",
        description="Classification model — transaction descriptions to categories",
    )
    CHAT_MODEL: str = Field(
        "gemini-3.6-flash",
        description="Chat model — tool calling and NL to SQL; upgrade to a pro model on paid quota",
    )

    # --- Chat memory ---
    CHAT_HISTORY_MAX_TURNS: int = Field(
        20,
        description="Chat turns kept per session before history is reset",
    )

    # --- Database (MySQL) ---
    DB_USER: str = Field(..., description="MySQL username")
    DB_PASSWORD: str = Field(..., description="MySQL password")
    DB_HOST: str = Field("localhost", description="MySQL host")
    DB_PORT: int = Field(3306, description="MySQL port")
    DB_NAME: str = Field(..., description="MySQL database name")

    # --- LLM reliability ---
    LLM_MAX_ATTEMPTS: int = Field(
        3,
        description="Attempts per Gemini call before giving up (transient errors only)",
    )
    LLM_RETRY_BASE_DELAY: float = Field(
        2.0,
        description="Base seconds for exponential backoff between retries",
    )
    LLM_MAX_RETRY_DELAY: float = Field(
        30.0,
        description="Cap on any single retry wait",
    )

    # --- Statement parsing ---
    STATEMENT_MAX_PAGES: int = Field(
        10,
        description="Maximum PDF pages sent to the vision model per statement",
    )

    # --- Categorization ---
    LLM_CONFIDENCE_THRESHOLD: float = Field(
        0.75,
        description="Confidence below this flags transaction for user review",
    )

    # --- Charts ---
    DEFAULT_MONTHS_TREND: int = Field(
        6,
        description="Number of months shown in the trend chart",
    )

    # --- NL to SQL ---
    MAX_SQL_ROWS: int = Field(
        100,
        description="Maximum rows returned by NL to SQL queries",
    )

    @field_validator(
        "GOOGLE_API_KEY", "PARSE_MODEL", "CATEGORIZE_MODEL", "CHAT_MODEL",
        "DB_USER", "DB_PASSWORD", "DB_HOST", "DB_NAME",
        mode="before",
    )
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        """Strip accidental whitespace from all string fields."""
        return v.strip() if isinstance(v, str) else v

    @computed_field
    @property
    def DATABASE_URL(self) -> str:
        """
        Constructs a safe MySQL connection string using PyMySQL.
        Uses quote_plus to handle special characters in passwords.
        """
        safe_password = quote_plus(self.DB_PASSWORD)
        return (
            f"mysql+pymysql://{self.DB_USER}:{safe_password}@"
            f"{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )


# Global settings instance — import this everywhere
settings = Settings()
