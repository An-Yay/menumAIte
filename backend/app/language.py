"""Work out which language to answer a message in.

Every part of a reply — the prose, the recommendation cards, the review summaries —
must be in the traveller's language. Leaving each component to infer that for
itself proved unreliable: the reviews' own language, or a cached summary written for
an earlier message, would win, producing a card with Hinglish prose and German
review points.

So the language is established once per message, explicitly, and then passed to
everything downstream. It is detected per message rather than once per conversation
because a traveller may switch language mid-conversation, and the answer should
follow.

Detection is a single cheap model call. The result is a human-readable description
("German", "Hinglish (Hindi written in Latin script)", etc) rather than a code, because
it is injected into prompts, where a description steers the model better than
"hi-Latn" does.
"""

from __future__ import annotations

from contextvars import ContextVar

from app.providers.llm import LLMError, LLMProvider

# Used when detection fails or the message is too short to judge. English is the
# safest default: a place name or "ok" should not switch the conversation.
DEFAULT_LANGUAGE = "English"

_SYSTEM = """\
You identify the language a message is written in.

Reply with a short human-readable description of the language, for example
"English", "German", "Spanish", "Hindi (Devanagari script)", or
"Hinglish (Hindi written in Latin script)".

Rules:
- Judge the language of the words the person wrote, not of any place name in it.
  "las vegas", "mumbai" or "paris" alone are NOT enough to identify a language.
- Romanised Indian languages are common: "mai dinner dhundna chahata hun" is
  Hinglish, not English. Identify it as Hinglish so the reply can match how they
  actually write.
- If the message is only a place name, a single word, or otherwise too short to
  tell, answer exactly "English".

Reply with a single JSON object and nothing else."""

_SCHEMA_HINT = '{"language": "string"}'


async def detect_language(message: str, llm: LLMProvider) -> str:
    """Return a description of the language `message` is written in.

    Falls back to `DEFAULT_LANGUAGE` when the message is empty, detection fails, or
    the model returns nothing usable, so a detection problem can never block an
    answer.
    """

    if not message.strip():
        return DEFAULT_LANGUAGE

    try:
        data = await llm.complete_json(
            system=_SYSTEM,
            prompt=f"Message:\n{message}",
            schema_hint=_SCHEMA_HINT,
            label="detect_language",
        )
    except LLMError:
        return DEFAULT_LANGUAGE

    language = (data.get("language") or "").strip()
    # Guard against a verbose answer being pasted in where a short name belongs.
    if not language or len(language) > 60:
        return DEFAULT_LANGUAGE
    return language


# The language for the message currently being answered. A context variable is used
# so that the tools the agent calls can read it without it being threaded through
# the agent's tool signatures, and so concurrent requests stay isolated.
_current_language: ContextVar[str] = ContextVar(
    "current_language", default=DEFAULT_LANGUAGE
)


def set_language(language: str) -> None:
    """Record the language for the message currently being answered."""

    _current_language.set(language)


def current_language() -> str:
    """Return the language the current reply should be written in."""

    return _current_language.get()


_TRANSLATE_SYSTEM = """\
You check whether text is written in an expected language, and correct it if not.

You are given the expected language and a piece of text. If the text is already in
that language, return it unchanged. If it is not, translate it into that language,
preserving meaning, names, numbers, prices and currency exactly as they appear.

Never add, remove or reinterpret content; this is a language check, not an edit.
Proper nouns (restaurant names, street names, dish names as printed on a menu) stay
as they are.

Reply with a single JSON object and nothing else."""

_TRANSLATE_SCHEMA = '{"was_correct": boolean, "text": "string"}'


async def ensure_language(text: str, llm: LLMProvider, language: str | None = None) -> str:
    """Return `text`, translated into the expected language if it is not already.

    A final safety net. Each component is told which language to write in, but a
    model can still slip — most often by echoing the language of its source
    material, such as writing review points in the reviews' own language. This
    verifies the finished text and repairs it rather than showing a reply that is
    partly in the wrong language.

    Returns the original text unchanged on any failure, since a mixed-language
    answer is better than no answer.
    """

    target = language or current_language()
    stripped = text.strip()
    if not stripped:
        return text

    try:
        data = await llm.complete_json(
            system=_TRANSLATE_SYSTEM,
            prompt=f"Expected language: {target}\n\nText:\n{stripped}",
            schema_hint=_TRANSLATE_SCHEMA,
            label="language_check",
        )
    except LLMError:
        return text

    if data.get("was_correct"):
        return text

    corrected = data.get("text")
    return corrected if isinstance(corrected, str) and corrected.strip() else text
