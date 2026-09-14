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

import httpx

from app.config import get_settings
from app.telemetry import record_generation


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
        label: str = "generation",
    ) -> dict[str, Any]:
        """Return a JSON object produced by the model.

        `system` sets behaviour and rules, `prompt` carries the task and data, and
        `schema_hint` describes the JSON shape expected back. `label` names the
        call for the telemetry trace (for example "extract_menu"). Implementations
        must return already-parsed JSON so callers can validate it into models.
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


class OpenAIProvider:
    """`LLMProvider` backed by the OpenAI Chat Completions API.

    Uses `response_format={"type": "json_object"}`, which instructs the model to
    return a single JSON object and is the most reliable structured-output mode
    for this API, rather than relying on prompt wording alone.
    """

    _CHAT_URL = "https://api.openai.com/v1/chat/completions"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        # 45s rather than a shorter default: menu extraction is the heaviest call
        # this provider makes (large input, a translated multi-item response), and
        # it was seen timing out at 30s on genuinely large menus.
        timeout: float = 45.0,
    ) -> None:
        settings = get_settings()
        self._api_key = api_key or settings.openai_api_key
        if not self._api_key:
            raise LLMError(
                "OPENAI_API_KEY is not configured. Set it in the environment or "
                "in a local .env file."
            )
        self._model = model or settings.llm_model_id
        self._timeout = timeout

    async def complete_json(
        self, *, system: str, prompt: str, schema_hint: str, label: str = "generation"
    ) -> dict[str, Any]:
        # The schema hint is folded into the user prompt: JSON mode guarantees
        # valid JSON syntax but not a specific shape, so the expected shape still
        # has to be spelled out for the model.
        full_prompt = (
            f"{prompt}\n\nRespond with JSON matching this shape:\n{schema_hint}"
        )

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": full_prompt},
            ],
            "response_format": {"type": "json_object"},
        }

        # One retry on a transient network failure. Losing an entire restaurant's
        # menu to a single dropped connection or timeout was worse than the extra
        # latency of trying again once.
        last_exc: httpx.HTTPError | None = None
        response = None
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.post(
                        self._CHAT_URL,
                        headers={
                            "Authorization": f"Bearer {self._api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )
                break
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt == 0:
                    continue

        if response is None:
            # Some httpx exceptions (a bare ReadTimeout, for instance) stringify to
            # nothing, which made failures here unreadable. The exception's type
            # is included unconditionally so there is always something to act on.
            detail = str(last_exc) or "no further detail"
            raise LLMError(
                f"OpenAI request failed: {type(last_exc).__name__}: {detail}"
            ) from last_exc

        try:
            data = response.json()
        except ValueError as exc:
            raise LLMError(
                f"OpenAI returned a non-JSON response (HTTP {response.status_code})."
            ) from exc

        if response.status_code != httpx.codes.OK or "error" in data:
            message = data.get("error", {}).get("message", response.text)
            raise LLMError(f"OpenAI error (HTTP {response.status_code}): {message}")

        # Record token usage for the request's telemetry trace before returning.
        usage = data.get("usage") or {}
        record_generation(
            label=label,
            model=data.get("model", self._model),
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
        )

        content = data["choices"][0]["message"]["content"]
        return extract_json(content)


class StubLLMProvider:
    """A deterministic provider used before a real model is configured.

    It performs no reasoning; it simply returns an empty JSON object. This lets
    the model-backed tools be imported, wired and unit-tested for their
    non-model logic (prompt assembly, validation, fallbacks) without a key or
    network access.
    """

    async def complete_json(
        self, *, system: str, prompt: str, schema_hint: str, label: str = "generation"
    ) -> dict[str, Any]:
        return {}
