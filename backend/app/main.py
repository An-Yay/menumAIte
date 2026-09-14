"""FastAPI application entry point.

At this scaffold stage the app exposes a single health-check endpoint so we can
verify the server boots and dependencies resolve. Agent and streaming endpoints
are added in later steps.
"""

from fastapi import FastAPI

from app.config import get_settings

app = FastAPI(
    title="menumAIte backend",
    summary="AI agent that recommends restaurants and meal options for travellers.",
    version="0.1.0",
)


@app.get("/health")
def health() -> dict[str, object]:
    """Liveness probe.

    Returns a small status payload and reports whether an LLM key is configured,
    without ever exposing the key itself. Useful for confirming local setup.
    """

    settings = get_settings()
    return {
        "status": "ok",
        # Booleans only — never echo secret values back to clients.
        "google_api_key_configured": settings.google_api_key is not None,
    }
