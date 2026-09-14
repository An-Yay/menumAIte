"""Agent construction.

Assembles the model, the toolset and the system prompt into a Strands agent.

The agent is deliberately autonomous: the model decides which tool to call next,
guided by the process described in the system prompt. That makes the reasoning
visible and adaptable — a traveller who changes their mind mid-conversation is
handled naturally, rather than having to restart a fixed pipeline.
"""

from __future__ import annotations

from strands import Agent
from strands.models.openai import OpenAIModel

from app.agent.prompt import SYSTEM_PROMPT
from app.agent.tools import AGENT_TOOLS
from app.config import get_settings
from app.providers.llm import LLMError


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
