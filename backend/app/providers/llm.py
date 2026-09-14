"""Model provider abstraction.

The agent's model-backed tools depend on this small interface rather than on any
particular vendor SDK, so the model can be swapped (or stubbed in tests) without
touching tool logic. Each tool asks the provider for a JSON object matching a
schema, which keeps model output structured and directly validatable into our
Pydantic models.

Only the interface and a deterministic stub live here. The concrete Strands- or
Gemini-backed implementation is wired in during agent assembly, once a model is
configured.
"""

from __future__ import annotations

import json
from typing import Any, Protocol


class LLMError(RuntimeError):
    """Raised when the model cannot return a usable response."""


class LLMProvider(Protocol):
    """The minimal contract the model-backed tools rely on."""

    async def complete_json(
        self,
        *,
        system: str,
        prompt: str,
        schema_hint: str,
    ) -> dict[str, Any]:
        """Return a JSON object produced by the model.

        `system` sets behaviour and rules, `prompt` carries the task and data, and
        `schema_hint` describes the JSON shape expected back. Implementations must
        return already-parsed JSON so callers can validate it into domain models.
        """
        ...


def extract_json(raw: str) -> dict[str, Any]:
    """Pull a JSON object out of a model's text response.

    Models often wrap JSON in prose or markdown fences even when asked not to, so
    the first balanced ``{...}`` block is located and parsed. Centralising this
    keeps every tool tolerant of that behaviour.
    """

    text = raw.strip()

    # Strip a leading ```json / ``` fence if present.
    if text.startswith("```"):
        text = text.split("```", 2)[1] if text.count("```") >= 2 else text
        text = text.removeprefix("json").strip()

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise LLMError(f"No JSON object found in model output: {raw[:200]!r}")

    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise LLMError(f"Model output was not valid JSON: {exc}") from exc


class StubLLMProvider:
    """A deterministic provider used before a real model is configured.

    It performs no reasoning; it simply returns an empty JSON object. This lets
    the model-backed tools be imported, wired and unit-tested for their
    non-model logic (prompt assembly, validation, fallbacks) without a key or
    network access.
    """

    async def complete_json(
        self, *, system: str, prompt: str, schema_hint: str
    ) -> dict[str, Any]:
        return {}
