"""Collects LLM generation records for the current request.

The interface can show a trace of every model call made while answering a message:
the model used, the tokens in and out, and an estimated cost. Those calls happen
deep inside tools, far from the streaming endpoint that needs to report them, so a
context-local collector carries the records back out without threading a parameter
through every layer.

`contextvars` is used rather than a module global so that concurrent requests keep
separate collectors: each request runs in its own context, and the collector is
reset at the start of a turn.
"""

from __future__ import annotations

from contextvars import ContextVar

from pydantic import BaseModel, Field

# Published OpenAI prices per 1M tokens, in USD. Hard-coded because the API does
# not return pricing, and clearly an estimate: rates change, and only the models
# this project uses are listed. Update when the model or its price changes.
_PRICES_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    # model: (input per 1M, output per 1M)
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
}


class GenerationRecord(BaseModel):
    """One model call: what it was for, its token use, and its estimated cost."""

    label: str = Field(description="What the call was doing, e.g. 'extract_menu'.")
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float | None = Field(
        default=None, description="Estimated cost in USD, or None if the model is unpriced."
    )


# The collector for the request currently being handled. Default is None so that
# code running outside a request (tests, scripts) simply records nothing.
_collector: ContextVar[list[GenerationRecord] | None] = ContextVar(
    "generation_collector", default=None
)


def _rates_for(model: str) -> tuple[float, float] | None:
    """Look up prices for a model id.

    OpenAI returns a dated model id (e.g. `gpt-4o-mini-2024-07-18`), so an exact
    match fails; the longest configured key that the id starts with is used
    instead, which maps every dated variant to its base model's price.
    """

    if model in _PRICES_USD_PER_MTOK:
        return _PRICES_USD_PER_MTOK[model]
    matches = [key for key in _PRICES_USD_PER_MTOK if model.startswith(key)]
    if not matches:
        return None
    return _PRICES_USD_PER_MTOK[max(matches, key=len)]


def start_collecting() -> None:
    """Begin a fresh collection for the current request/turn."""

    _collector.set([])


def record_generation(
    *, label: str, model: str, input_tokens: int, output_tokens: int
) -> None:
    """Record one model call, if collection is active.

    Cost is estimated from the model's published rate; an unknown model records
    tokens with a null cost rather than a wrong number.
    """

    collector = _collector.get()
    if collector is None:
        return

    rates = _rates_for(model)
    cost = None
    if rates:
        input_rate, output_rate = rates
        cost = (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000

    collector.append(
        GenerationRecord(
            label=label,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            cost_usd=round(cost, 6) if cost is not None else None,
        )
    )


def collected_generations() -> list[GenerationRecord]:
    """Return the generations recorded for the current request."""

    return list(_collector.get() or [])
