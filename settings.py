import logging
from urllib.parse import quote_plus

from pydantic import Field, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logging.basicConfig(level=logging.INFO)
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
    GOOGLE_API_KEY: str = Field(..., description="API key for Google Gemini")
    FLASH_MODEL: str = Field(
        "gemini-1.5-flash",
        description="Fast model — parsing and categorization",
    )
    PRO_MODEL: str = Field(
        "gemini-1.5-pro",
        description="Smart model — chat tool calling and NL to SQL",
    )

    # --- Database (MySQL) ---
    DB_USER: str = Field(..., description="MySQL username")
    DB_PASSWORD: str = Field(..., description="MySQL password")
    DB_HOST: str = Field("localhost", description="MySQL host")
    DB_PORT: int = Field(3306, description="MySQL port")
    DB_NAME: str = Field(..., description="MySQL database name")

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
        "GOOGLE_API_KEY", "FLASH_MODEL", "PRO_MODEL",
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
