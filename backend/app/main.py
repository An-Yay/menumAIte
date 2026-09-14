"""FastAPI application entry point.

Exposes a health check plus the chat API that streams the agent's work. The
frontend runs as a separate development server, so cross-origin requests are
permitted from its origin.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.chat import router as chat_router
from app.config import get_settings

app = FastAPI(
    title="menumAIte backend",
    summary="AI agent that recommends restaurants and meal options for travellers.",
    version="0.1.0",
)

# The interface is served by its own dev server on a different port, which the
# browser treats as a separate origin. Allowed origins are configurable rather
# than hard-coded so the port can change without a code edit.
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router, prefix="/api")


@app.get("/health")
def health() -> dict[str, object]:
    """Liveness probe.

    Reports whether the required keys are configured, as booleans only, so setup
    can be verified without ever exposing a key.
    """

    settings = get_settings()
    return {
        "status": "ok",
        "google_api_key_configured": settings.google_api_key is not None,
        "openai_api_key_configured": settings.openai_api_key is not None,
        "llm_model_id": settings.llm_model_id,
    }
