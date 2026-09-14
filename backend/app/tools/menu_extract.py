"""Turn raw menu text into structured, translated dishes.

The crawler returns unstructured menu text in whatever language the restaurant
wrote it. This tool asks the model to parse that text into dishes, translate them
into the traveller's language, attach a price only when one is genuinely present,
and flag each dish against the traveller's dietary needs.

Two rules are enforced through the prompt and the output model:

* **Never invent a price.** A dish with no listed price is returned with
  ``price_available = false`` and no number.
* **Never invent dishes.** Only items actually present in the text are returned;
  if nothing menu-like is found, an empty list comes back and the caller reports
  the menu as unreadable.
"""

from __future__ import annotations

from app.models import Menu, MenuItem
from app.providers.llm import LLMError, LLMProvider

_SYSTEM = """\
You extract restaurant menu items from raw web-page text.
Rules:
- Return only dishes that genuinely appear in the text. Never invent items.
- Include a price ONLY if the text clearly states one for that dish. If no price
  is shown, set price_available to false and leave price_amount null. Never guess
  a price.
- Translate each dish name and description into the requested output language,
  and also keep the original name.
- Tag dishes with dietary properties you can infer (e.g. "vegan", "contains
  nuts") and, given the traveller's forbidden ingredients, set matches_requirements
  to true/false, or null when genuinely unclear.
- Detect the source language of the menu.
Reply with a single JSON object and nothing else."""

_SCHEMA_HINT = """\
{
  "source_language": "string (BCP-47) or null",
  "items": [
    {
      "name": "string (in output language)",
      "original_name": "string (as printed) or null",
      "description": "string or null",
      "price_amount": number or null,
      "price_currency": "string (ISO 4217) or null",
      "price_available": boolean,
      "dietary_tags": ["string"],
      "matches_requirements": true | false | null
    }
  ]
}"""


def _sanitize_item(item: dict, fallback_currency: str | None = None) -> dict:
    """Normalise one model-produced menu item before validation.

    Two corrections are applied, both from observed model behaviour:

    * An explicit ``null`` for a list field bypasses Pydantic's `default_factory`,
      which only applies when a key is missing, so such values are coerced.
    * A price is often printed on a menu without any currency, in which case the
      model returns an amount and no currency code. The currency inferred from the
      restaurant's country is filled in, because a bare number is of little use to
      a traveller. `price_available` is also reconciled with whether an amount is
      actually present, so the two can never disagree.
    """

    if item.get("dietary_tags") is None:
        item["dietary_tags"] = []

    has_amount = item.get("price_amount") is not None
    # Trust the amount over the flag: models occasionally set one without the other.
    item["price_available"] = has_amount

    if has_amount and not item.get("price_currency") and fallback_currency:
        item["price_currency"] = fallback_currency

    return item


async def extract_and_translate_menu(
    *,
    raw_text: str,
    restaurant_place_id: str,
    menu_url: str | None,
    output_language: str,
    forbidden_ingredients: list[str],
    llm: LLMProvider,
    max_items: int = 40,
    fallback_currency: str | None = None,
) -> Menu:
    """Parse and translate menu text into a structured `Menu`.

    A `Menu` is always returned. If extraction fails or finds nothing, the menu
    carries an explanatory `retrieval_note` instead of fabricated dishes.
    """

    if len(raw_text.strip()) < 100:
        return Menu(
            restaurant_place_id=restaurant_place_id,
            menu_url=menu_url,
            retrieval_note="Not enough menu text was available to read.",
        )

    forbidden = ", ".join(forbidden_ingredients) if forbidden_ingredients else "none"
    prompt = (
        f"Output language: {output_language}\n"
        f"Traveller's forbidden ingredients: {forbidden}\n\n"
        "Menu text follows between the markers.\n"
        "----- MENU TEXT START -----\n"
        f"{raw_text}\n"
        "----- MENU TEXT END -----\n\n"
        "Extract the menu as JSON."
    )

    try:
        data = await llm.complete_json(
            system=_SYSTEM, prompt=prompt, schema_hint=_SCHEMA_HINT
        )
    except LLMError as exc:
        return Menu(
            restaurant_place_id=restaurant_place_id,
            menu_url=menu_url,
            retrieval_note=f"Menu could not be interpreted: {exc}",
        )

    raw_items = data.get("items") or []
    if not raw_items:
        return Menu(
            restaurant_place_id=restaurant_place_id,
            menu_url=menu_url,
            source_language=data.get("source_language"),
            retrieval_note="No individual dishes could be read from the menu.",
        )

    items = [
        MenuItem.model_validate(_sanitize_item(item, fallback_currency))
        for item in raw_items[:max_items]
    ]

    source_language = data.get("source_language")
    was_translated = bool(
        source_language and source_language.split("-")[0] != output_language.split("-")[0]
    )

    return Menu(
        restaurant_place_id=restaurant_place_id,
        menu_url=menu_url,
        source_language=source_language,
        was_translated=was_translated,
        items=items,
    )
