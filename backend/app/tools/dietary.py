"""Reason about a traveller's dietary needs.

Rather than maintaining a hard-coded table of what each diet forbids, the model
does the reasoning from the traveller's own words. This handles unusual or
combined requirements ("Jain but I eat honey", "halal, no nuts") that a fixed
table would get wrong, and lets the same tool serve religious diets, ethical
diets and allergies alike.

The output is validated into `DietaryProfile`, so downstream steps get a
structured, displayable result regardless of how the model phrased things.
"""

from __future__ import annotations

from app.models import DietaryProfile
from app.providers.llm import LLMError, LLMProvider

# Behavioural rules for the model. The emphasis on honesty mirrors the rest of
# the product: never assert a guarantee (certification, allergen safety) that
# cannot be verified from a menu.
_SYSTEM = """\
You are a dietary reasoning assistant for a restaurant recommender.
Given a traveller's description of how they eat, work out what it means in
practice. Reason carefully and safely:

- List concrete ingredients to avoid, not vague categories.
- For religious diets (halal, kosher, Jain, etc.) note that certification or
  preparation cannot be verified from a menu and must be confirmed with the
  restaurant.
- Treat allergies as safety-critical: never imply a dish is safe, only that a
  menu does or does not list an allergen.
- When a diet has no dedicated map category (e.g. Jain), suggest alternative
  search terms that find suitable restaurants (e.g. "pure vegetarian",
  "satvik", regional cuisines known for such food).
- Ask a clarifying question only for genuine ambiguities (e.g. eggs for a
  vegetarian), not for the sake of it.

Reply with a single JSON object and nothing else."""

_SCHEMA_HINT = """\
{
  "labels": ["string"],
  "forbidden_ingredients": ["string"],
  "allowed_notes": ["string"],
  "clarifying_questions": ["string"],
  "search_terms": ["string"],
  "verification_note": "string or null"
}"""


async def resolve_dietary_profile(
    description: str, llm: LLMProvider
) -> DietaryProfile:
    """Turn a free-text dietary description into a structured profile.

    Falls back to a minimal profile that simply echoes the description as a label
    if the model output cannot be parsed, so discovery can still proceed rather
    than the whole request failing on a diet it did not understand.
    """

    prompt = (
        f'The traveller describes their diet as: "{description.strip()}".\n'
        "Produce the dietary profile as JSON."
    )

    try:
        data = await llm.complete_json(
            system=_SYSTEM, prompt=prompt, schema_hint=_SCHEMA_HINT, label="dietary_profile"
        )
    except LLMError:
        data = {}

    if not data:
        # Safe degradation: keep the traveller's own wording as a search label.
        cleaned = description.strip()
        return DietaryProfile(
            labels=[cleaned] if cleaned else [],
            verification_note=(
                "Dietary requirements could not be interpreted automatically; "
                "using them as-is for the search."
            ),
        )

    return DietaryProfile.model_validate(data)
