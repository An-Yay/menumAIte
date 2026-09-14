"""Chat endpoint.

Exposes the agent over HTTP as a Server-Sent Events stream. SSE is a good fit
here: the traffic is one-way (server to browser), it runs over plain HTTP with no
extra protocol, and browsers reconnect automatically. A WebSocket would add
complexity for no benefit, since the client only ever sends a new message as a
fresh request.

Conversations are held in memory, keyed by session id, because the application is
run locally and a database would add setup for no gain. Each session keeps its own
agent so message history stays isolated between conversations.
"""

from __future__ import annotations

import json
import uuid
from typing import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from strands import Agent

from app.agent.agent import build_agent
from app.api.events import EventTranslator
from app.models import COMMON_MEALS

router = APIRouter(tags=["chat"])

# Session id -> agent. An agent carries its own message history, so keeping one
# per session is what makes the conversation continuous. Process-local, and
# therefore cleared on restart, which is acceptable for local use.
_sessions: dict[str, Agent] = {}


class ChatRequest(BaseModel):
    """A traveller's message."""

    message: str = Field(description="What the traveller typed, in any language.")
    session_id: str | None = Field(
        default=None,
        description=(
            "Identifies the conversation. Omit on the first message; the response "
            "stream reports the id to use for subsequent messages."
        ),
    )


def _get_agent(session_id: str) -> Agent:
    """Return the agent for a session, creating it on first use."""

    agent = _sessions.get(session_id)
    if agent is None:
        agent = build_agent()
        _sessions[session_id] = agent
    return agent


def _sse(payload: dict) -> str:
    """Format one event as an SSE frame.

    Each frame is a single ``data:`` line holding compact JSON, terminated by a
    blank line. Newlines inside the JSON would break the framing, so the payload
    is serialised without indentation.
    """

    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _stream(message: str, session_id: str) -> AsyncIterator[str]:
    """Run the agent and yield SSE frames describing its work."""

    translator = EventTranslator()

    # Sent first so the client can store the session id before anything else.
    yield _sse({"type": "session", "session_id": session_id})
    yield _sse(translator.start())

    try:
        agent = _get_agent(session_id)
        async for event in agent.stream_async(message):
            for translated in translator.translate(event):
                yield _sse(translated)
        yield _sse(translator.finish())
    except Exception as exc:  # noqa: BLE001
        # The stream has already begun, so a failure cannot be reported as an HTTP
        # error status. It is sent as an error event instead, which also lets the
        # interface keep whatever partial results it has already displayed.
        yield _sse(translator.error(f"{type(exc).__name__}: {exc}"))

    # Signals a clean end of stream, so the client can close its reader rather
    # than waiting for a timeout.
    yield "event: done\ndata: {}\n\n"


@router.post("/chat")
async def chat(request: ChatRequest) -> StreamingResponse:
    """Send a message to the agent and stream its work back.

    Returns an SSE stream of `observation` events (the reasoning tree), `text`
    chunks (the reply as it is written), and a final `final` event.
    """

    session_id = request.session_id or uuid.uuid4().hex

    return StreamingResponse(
        _stream(request.message, session_id),
        media_type="text/event-stream",
        headers={
            # Proxies and browsers must not buffer or cache a live stream.
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/meta")
def meta() -> dict[str, object]:
    """Options the interface can offer as quick-pick chips during intake.

    Meals are suggestions rather than a closed list: the agent accepts any meal
    occasion a traveller describes.
    """

    return {
        "common_meals": list(COMMON_MEALS),
        "common_diets": [
            "vegetarian",
            "vegan",
            "jain",
            "halal",
            "kosher",
            "gluten-free",
            "lactose-free",
            "nut allergy",
            "pescatarian",
        ],
    }


@router.delete("/session/{session_id}")
def end_session(session_id: str) -> dict[str, object]:
    """Discard a conversation and its history."""

    existed = _sessions.pop(session_id, None) is not None
    return {"ended": existed}
