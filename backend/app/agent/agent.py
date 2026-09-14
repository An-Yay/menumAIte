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
from app.agent.tools import AGENT_TOOLS, assemble_suggestions
from app.config import get_settings
from app.models import SuggestionList, SuggestionPickList
from app.providers.llm import LLMError

logger = logging.getLogger(__name__)

# Asks the agent only for its judgement calls, not for the data it already
# gathered. An earlier version asked the agent to restate the full recommendation
# (restaurant details, dishes, prices) from its conversation history, and that
# restating was unreliable: a restaurant whose menu had just been read correctly,
# with real prices, was sometimes reported back here as "menu could not be read".
# Reproducing structured data from context turned out to be a weaker guarantee
# than looking it up, so this prompt asks only for what a lookup cannot supply.
_FINALIZE_PROMPT = (
    "Which of the restaurants you looked up should be recommended? For each one, "
    "give its place_id exactly as returned by discover_restaurants, your reasoning "
    "for recommending it, the names of a few dishes to feature (matching the menu "
    "you already read), and any caveat worth mentioning as a short sentence of "
    "your own words. Do not include prices, ratings or review counts here, and "
    "never paste a tool's raw output (JSON, citations, links) into a caveat; write "
    "your own short remark instead. If you did not gather enough to recommend "
    "anything, return an empty list.\n\n"
    "IMPORTANT: write the reasoning, dish names and caveats in {language}, the same "
    "language you have used with the traveller. This is card text shown to them, so "
    "it must be in their language, not English (unless their language is English)."
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


async def extract_suggestions(
    agent: Agent, *, review_context: str = "", output_language: str = "en"
) -> SuggestionList:
    """Pull structured recommendations out of a completed conversation.

    Run after the agent has answered, so the interface can render restaurant cards
    (ratings, priced dishes, review balance, links) alongside the chat reply. It
    draws on the agent's existing context rather than fetching anything again, so
    it is one cheap model call.

    Any failure returns an empty list: the chat reply has already been shown, so a
    missing card view should degrade quietly rather than surface an error.
    """

    # The finalize call runs on the same agent, with the whole conversation in its
    # history, so it can be told to reuse "the same language you have used" rather
    # than being handed a language code (which the app does not reliably track).
    prompt = _FINALIZE_PROMPT.format(language="the same language you have used with the traveller")

    try:
        picks = await agent.structured_output_async(SuggestionPickList, prompt)
    except Exception as exc:  # noqa: BLE001 - cards are secondary to the text reply
        # Logged rather than silently swallowed: an empty card list looks identical
        # to "no recommendations were made", which made a real failure here
        # invisible during development.
        logger.warning("Could not extract suggestion picks: %s", exc)
        return SuggestionList(suggestions=[])

    return await assemble_suggestions(
        picks.picks, review_context=review_context, output_language=output_language
    )
