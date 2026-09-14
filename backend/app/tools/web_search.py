"""Find menus that crawling a restaurant's own website could not reach.

Crawling the restaurant's site is the primary way to read a menu, but testing
against real sites showed it fails in predictable ways: the page is rendered by
JavaScript, the menu is a PDF or an image, the domain has changed hands, or the
site simply does not publish prices.

This module is the fallback for those cases. It uses OpenAI's hosted web search to
look for the menu elsewhere — including aggregator and listing sites, which
frequently do publish priced menus when the restaurant itself does not.

It is deliberately *not* part of the normal path:

* a hosted search call costs more and takes longer than reading a page;
* results may come from aggregators, whose prices can be out of date or reflect
  delivery pricing rather than dine-in.

Because of that second point the source is always reported back, so the traveller
can be told where a price came from rather than being left to assume it came from
the restaurant.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.config import get_settings
from app.providers.llm import LLMError

_RESPONSES_URL = "https://api.openai.com/v1/responses"

# Search is slower than a page fetch, so the budget is larger than the crawler's
# but still bounded to keep the traveller's wait reasonable.
_TIMEOUT_SECONDS = 60.0

_INSTRUCTIONS = """\
You are researching a restaurant's menu on the web.

Find the menu for the named restaurant in the named city and report the dishes you
can actually see, with prices ONLY where a price is genuinely shown. Never invent a
dish or a price.

Prefer the restaurant's own website. If the menu is only on a listing or delivery
site, that is acceptable, but say which site it came from, because such prices can
be outdated or specific to delivery.

Write dish names as they appear on the menu. Write the `note` field in ENGLISH,
regardless of the language of the restaurant or its website; the caller translates
it afterwards.

Reply with ONLY a JSON object. No prose before or after it, no markdown fences.
Even when you cannot find the menu, still reply with the JSON object and explain
the problem in `note`.

The JSON shape is:
{
  "menu_url": "the page the menu was read from, or null",
  "source_name": "the site it came from, e.g. 'the restaurant's website' or 'TheFork'",
  "currency": "ISO 4217 code if prices were found, else null",
  "items": [
    {"name": "dish name", "description": "string or null",
     "price_amount": number or null, "price_available": boolean}
  ],
  "note": "a short honest note if the menu could not be found, else null"
}"""


async def search_menu_online(
    *, restaurant_name: str, city: str, website_url: str | None = None
) -> dict[str, Any]:
    """Search the web for a restaurant's menu.

    Returns the raw structure described in `_INSTRUCTIONS`, plus a `searched`
    flag. Failures are returned as a note rather than raised, so a fallback that
    does not work cannot break the recommendation that prompted it.
    """

    settings = get_settings()
    if not settings.openai_api_key:
        raise LLMError("OPENAI_API_KEY is not configured.")

    query = f"{restaurant_name} restaurant menu {city}"
    if website_url:
        query += f" (official site: {website_url})"

    payload = {
        "model": settings.llm_model_id,
        "tools": [{"type": "web_search"}],
        "instructions": _INSTRUCTIONS,
        "input": query,
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(
                _RESPONSES_URL,
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
    except httpx.HTTPError as exc:
        return {"searched": False, "note": f"Web search failed: {exc}", "items": []}

    try:
        data = response.json()
    except ValueError:
        return {
            "searched": False,
            "note": f"Web search returned an unreadable response (HTTP {response.status_code}).",
            "items": [],
        }

    if response.status_code != httpx.codes.OK or data.get("error"):
        message = (data.get("error") or {}).get("message", response.text[:200])
        return {"searched": False, "note": f"Web search failed: {message}", "items": []}

    text = _output_text(data)
    if not text:
        return {
            "searched": True,
            "note": "Web search returned no readable result.",
            "items": [],
        }

    # Reuse the shared tolerant JSON extraction: the search-enabled model wraps
    # its JSON in prose more often than the plain completion endpoint does.
    from app.providers.llm import extract_json

    try:
        parsed = extract_json(text)
    except LLMError:
        # The model occasionally answers in prose despite the instructions, usually
        # when it did not find a menu. Its explanation is still useful, so it is
        # passed through as the note instead of being discarded as a parse error.
        return {
            "searched": True,
            "menu_url": None,
            "items": [],
            "note": text[:400],
        }

    parsed["searched"] = True
    parsed.setdefault("items", [])
    return parsed


def _output_text(data: dict[str, Any]) -> str:
    """Pull the assistant's text out of a Responses API payload.

    The response is a list of output items, of which only the message items carry
    text; web-search call items are also present and are skipped.
    """

    chunks: list[str] = []
    for item in data.get("output") or []:
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for block in item.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "output_text":
                chunks.append(block.get("text", ""))
    return "\n".join(chunk for chunk in chunks if chunk).strip()
