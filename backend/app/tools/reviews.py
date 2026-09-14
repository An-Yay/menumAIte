"""Read reviews and surface what matters for the traveller.

Covers both angles the product requires: a balanced positive/negative summary,
and a targeted search for review content relevant to the traveller's specific
situation (for example, whether reviewers mention good vegetarian choice or
careful gluten-free handling).

Reviews often arrive in several languages; the model reads them as-is and reports
its findings in the traveller's output language.
"""

from __future__ import annotations

from app.models import Review, ReviewInsight
from app.providers.llm import LLMError, LLMProvider

_SYSTEM = """\
You analyse restaurant reviews for a traveller.
- Summarise recurring PRAISE as short positive points.
- Summarise recurring COMPLAINTS as short negative points. Do not hide the
  negatives; a balanced view is the goal.
- Given the traveller's context (meal and dietary needs), extract short excerpts
  or paraphrases from reviews that speak directly to that context. If none do,
  return an empty list rather than stretching.
- Base everything only on the reviews provided; do not invent experiences.
- Write your output in the SAME LANGUAGE as the traveller's context text below
  (for example, if their context is in German, write the points in German). The
  reviews themselves may be in other languages; translate your findings into the
  traveller's language.
Reply with a single JSON object and nothing else."""

_SCHEMA_HINT = """\
{
  "positive_points": ["string"],
  "negative_points": ["string"],
  "context_matches": ["string"]
}"""


async def analyze_reviews(
    *,
    reviews: list[Review],
    restaurant_place_id: str,
    context: str,
    output_language: str,
    llm: LLMProvider,
) -> ReviewInsight:
    """Produce a `ReviewInsight` from a restaurant's reviews.

    Always returns an insight. When there are no reviews, or analysis fails, the
    insight is empty rather than fabricated, and `reviews_considered` reflects
    how many reviews were actually available.
    """

    if not reviews:
        return ReviewInsight(
            restaurant_place_id=restaurant_place_id, reviews_considered=0
        )

    # Number the reviews so the model can attribute points to specific ones.
    joined = "\n".join(
        f"[{i + 1}] (rating={r.rating}, lang={r.language}) {r.text}"
        for i, r in enumerate(reviews)
    )
    # The traveller's context is their own message, so it carries the language to
    # answer in. The reviews are often in a different language and must not decide
    # the output language; the instruction below is emphatic because the reviews'
    # language otherwise tends to win.
    prompt = (
        f"Traveller's context: {context}\n\n"
        "Detect the language of the traveller's context above, and write ALL of "
        "your output (positive_points, negative_points, context_matches) in THAT "
        "language. The reviews below may be in a different language; translate your "
        "findings into the traveller's language. Do not answer in the reviews' "
        "language.\n\n"
        f"Reviews:\n{joined}\n\n"
        "Analyse these reviews as JSON."
    )

    try:
        data = await llm.complete_json(
            system=_SYSTEM, prompt=prompt, schema_hint=_SCHEMA_HINT, label="analyse_reviews"
        )
    except LLMError:
        # Analysis failure should not sink the recommendation; return an empty
        # insight that still records how many reviews existed.
        return ReviewInsight(
            restaurant_place_id=restaurant_place_id,
            reviews_considered=len(reviews),
        )

    return ReviewInsight(
        restaurant_place_id=restaurant_place_id,
        positive_points=data.get("positive_points", []) or [],
        negative_points=data.get("negative_points", []) or [],
        context_matches=data.get("context_matches", []) or [],
        reviews_considered=len(reviews),
    )
