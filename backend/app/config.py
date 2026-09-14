"""Application configuration.

Settings are loaded from environment variables (and, for local development, from
a `.env` file that is intentionally git-ignored). Secrets such as API keys must
never be hard-coded in source or committed to version control.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the backend.

    The LLM-related settings are optional at this stage so the application can
    boot and its non-LLM tools (restaurant discovery, menu crawling) can be
    exercised before a model provider is wired in.
    """

    # --- Google Cloud ---
    # Single Google key with "Places API (New)" enabled (restaurant discovery +
    # reviews) and, later, "Generative Language API" enabled (the LLM).
    google_api_key: str | None = None

    # --- Model selection (used once the Strands agent is assembled) ---
    # Kept optional for now; the agent step will require a real value.
    llm_model_id: str = "gemini/gemini-1.5-flash"

    # Pydantic-settings configuration: read from a local `.env` if present,
    # ignore unknown env vars, and treat variable names case-insensitively.
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance.

    Caching ensures the `.env` file and environment are read once per process,
    and lets other modules simply call `get_settings()` wherever they need it.
    """

    return Settings()
