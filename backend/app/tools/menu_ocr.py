"""Read a menu from a photograph.

The last resort for a menu. Some restaurants have no website at all, and others
publish their menu only as an image, but diners routinely photograph the menu board
or a menu page and those photos end up on the restaurant's map listing.

Strictly bounded, because each attempt costs a billed photo request plus a vision
model call:

* one photo per restaurant, never a sweep of the whole gallery;
* only reached after the website crawl and the web search have both failed;
* a photo that turns out not to show a menu is reported as such rather than
  guessed at.
"""

from __future__ import annotations

import base64
from typing import Any

import httpx

from app.config import get_settings
from app.language import current_language
from app.providers.llm import LLMError, extract_json

_CHAT_URL = "https://api.openai.com/v1/chat/completions"

# Reading an image is slower than reading text, so this gets a wider budget than
# the text calls.
_TIMEOUT_SECONDS = 60.0

_SYSTEM = """\
You are reading a photograph taken at a restaurant.

If the photo shows a menu (a board, a printed menu, a page), transcribe the dishes
you can actually read, with prices only where a price is clearly legible.

If it shows something else — a plate of food, the dining room, the shopfront — say
so and return no items. Do not guess at a menu from a picture of food.

Never invent a dish or a price. If part of the menu is blurred or cut off, simply
omit what you cannot read.

Reply with only a JSON object, no prose and no markdown fences:
{
  "is_menu": boolean,
  "items": [
    {"name": "dish name as printed", "description": "string or null",
     "price_amount": number or null, "price_available": boolean}
  ],
  "note": "short note if the photo is not a menu or is barely legible, else null"
}"""


async def read_menu_from_photo(*, photo_url: str) -> dict[str, Any]:
    """Transcribe a menu from a single photo.

    Returns the parsed structure described in `_SYSTEM`, plus an `attempted` flag.
    Failures come back as a note rather than an exception, so a last-resort attempt
    that does not work cannot break the recommendation that prompted it.
    """

    settings = get_settings()
    if not settings.openai_api_key:
        raise LLMError("OPENAI_API_KEY is not configured.")

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS, follow_redirects=True) as client:
            image_response = await client.get(photo_url)
    except httpx.HTTPError as exc:
        return {"attempted": False, "is_menu": False, "items": [], "note": f"Could not download the photo: {exc}"}

    if image_response.status_code != httpx.codes.OK:
        return {
            "attempted": False,
            "is_menu": False,
            "items": [],
            "note": f"Could not download the photo (HTTP {image_response.status_code}).",
        }

    # Sent inline as a data URL. The Places media URL carries the API key as a
    # query parameter, so handing that URL to a third party would leak the key;
    # downloading here and forwarding only the bytes avoids that.
    media_type = image_response.headers.get("content-type", "image/jpeg").split(";")[0]
    encoded = base64.b64encode(image_response.content).decode("ascii")
    data_url = f"data:{media_type};base64,{encoded}"

    payload = {
        "model": settings.llm_model_id,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            f"Transcribe any menu in this photo. Write dish names as "
                            f"printed, and translate descriptions into {current_language()}."
                        ),
                    },
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
        "response_format": {"type": "json_object"},
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            response = await client.post(
                _CHAT_URL,
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
    except httpx.HTTPError as exc:
        return {
            "attempted": True,
            "is_menu": False,
            "items": [],
            "note": f"Could not read the photo: {type(exc).__name__}",
        }

    try:
        data = response.json()
    except ValueError:
        return {"attempted": True, "is_menu": False, "items": [], "note": "Unreadable response."}

    if response.status_code != httpx.codes.OK or "error" in data:
        message = data.get("error", {}).get("message", response.text[:150])
        return {"attempted": True, "is_menu": False, "items": [], "note": f"Photo read failed: {message}"}

    try:
        parsed = extract_json(data["choices"][0]["message"]["content"])
    except (LLMError, KeyError, IndexError):
        return {"attempted": True, "is_menu": False, "items": [], "note": "Could not parse the transcription."}

    parsed["attempted"] = True
    parsed.setdefault("items", [])
    parsed.setdefault("is_menu", False)

    # A photo of food rather than a menu must not contribute dishes, whatever else
    # the model returned alongside that judgement.
    if not parsed.get("is_menu"):
        parsed["items"] = []

    return parsed
