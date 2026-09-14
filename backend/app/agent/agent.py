"""Agent construction.

Assembles the model, the toolset and the system prompt into a Strands agent.

The agent is deliberately autonomous: the model decides which tool to call next,
guided by the process described in the system prompt. That makes the reasoning
visible and adaptable — a traveller who changes their mind mid-conversation is
handled naturally, rather than having to restart a fixed pipeline.
"""

from __future__ import annotations

import logging

from strands import Agent
from strands.models.openai import OpenAIModel

from app.agent.prompt import SYSTEM_PROMPT
from app.agent.tools import AGENT_TOOLS
from app.config import get_settings
from app.models import SuggestionList
from app.providers.llm import LLMError

logger = logging.getLogger(__name__)

# Asks the agent to convert what it already gathered into structured cards. It
# reuses the conversation context, so no restaurant, menu or review data is
# fetched again.
_FINALIZE_PROMPT = (
    "Using only the restaurants, menus and reviews you have already gathered in "
    "this conversation, produce the structured recommendations. Include every "
    "restaurant you recommended in your reply. For each one, fill in the review "
    "insight from the reviews you analysed (both positive and negative points, and "
    "any context-specific matches), and the dishes you suggested. Include a price "
    "on a dish only when the menu actually listed one; otherwise leave the price "
    "fields empty. Populate the website, menu and map links. Do not invent dishes, "
    "prices or reviews. If you did not gather enough to recommend anything, return "
    "an empty list."
)


def build_model() -> OpenAIModel:
    """Create the OpenAI model the agent reasons with.

    The key comes from settings so it stays in the environment, and the model id is
    configurable to make swapping models a config change rather than a code change.
    """

    settings = get_settings()
    if not settings.openai_api_key:
        raise LLMError(
            "OPENAI_API_KEY is not configured. Set it in the environment or in a "
            "local .env file."
        )

    return OpenAIModel(
        client_args={"api_key": settings.openai_api_key},
        model_id=settings.llm_model_id,
        params={
            # Low temperature: this agent reports facts gathered from tools, so
            # consistency matters more than variety.
            "temperature": 0.3,
        },
    )


def build_agent() -> Agent:
    """Create a menumAIte agent ready to hold a conversation.

    A fresh agent is built per conversation so that each traveller's message
    history stays isolated.
    """

    return Agent(
        model=build_model(),
        tools=AGENT_TOOLS,
        system_prompt=SYSTEM_PROMPT,
        name="menumAIte",
        description=(
            "Recommends restaurants and dishes for travellers, accounting for meal "
            "occasion and dietary needs, and shows its working."
        ),
    )


async def extract_suggestions(agent: Agent) -> SuggestionList:
    """Pull structured recommendations out of a completed conversation.

    Run after the agent has answered, so the interface can render restaurant cards
    (ratings, priced dishes, review balance, links) alongside the chat reply. It
    draws on the agent's existing context rather than fetching anything again, so
    it is one cheap model call.

    Any failure returns an empty list: the chat reply has already been shown, so a
    missing card view should degrade quietly rather than surface an error.
    """

    try:
        return await agent.structured_output_async(SuggestionList, _FINALIZE_PROMPT)
    except Exception as exc:  # noqa: BLE001 - cards are secondary to the text reply
        # Logged rather than silently swallowed: an empty card list looks identical
        # to "no recommendations were made", which made a real failure here
        # invisible during development.
        logger.warning("Could not extract structured suggestions: %s", exc)
        return SuggestionList(suggestions=[])
