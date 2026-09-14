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
    # Google key with "Places API (New)" enabled: restaurant discovery + reviews.
    google_api_key: str | None = None

    # --- Model provider ---
    # OpenAI key used by the LLM-backed tools (dietary reasoning, menu
    # extraction/translation, review analysis) and by the Strands agent itself.
    # Kept optional so the app, and the non-LLM tools, can boot without it.
    openai_api_key: str | None = None
    llm_model_id: str = "gpt-4o-mini"

    # --- Interface ---
    # Origins allowed to call this API. The frontend development server runs on a
    # different port, which the browser treats as a separate origin, so it must be
    # listed explicitly. Comma-separated to keep it easy to set as one env var.
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        """`cors_origins` split into a list, ignoring blanks and stray spaces."""

        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

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
