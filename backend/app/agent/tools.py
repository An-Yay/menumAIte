"""The agent's toolset.

Each function here is exposed to the model as a callable tool. Strands builds the
tool specification from the signature, type hints and docstring, so the docstrings
are written for the model as much as for a developer: they state what the tool
does, when to use it, and what comes back.

The tools are thin adapters. Real work lives in the providers, the crawler and the
model-backed tools, which are independently testable; these wrappers only convert
between the agent's simple argument types and those components' richer models.
Returning plain dictionaries keeps tool results easy for the model to read.
"""

from __future__ import annotations

from typing import Any

from strands import tool

from app.crawler.menu_crawler import MenuCrawler
from app.models import Review, SearchBrief
from app.providers.llm import OpenAIProvider
from app.providers.places import GooglePlacesProvider
from app.tools.dietary import resolve_dietary_profile as _resolve_dietary_profile
from app.tools.menu_extract import extract_and_translate_menu as _extract_menu
from app.tools.reviews import analyze_reviews as _analyze_reviews

# Reviews fetched during discovery are cached per place id so the reviews can be
# fetched once and then analysed without paying for a second Places call. Scoped
# to the process, which is sufficient for a locally run session.
_review_cache: dict[str, list[Review]] = {}


@tool
async def resolve_dietary_profile(description: str) -> dict[str, Any]:
    """Work out what a traveller's dietary description means in practice.

    Use this before searching whenever dietary needs are mentioned, especially for
    religious diets (Jain, halal, kosher), allergies, or anything ambiguous.

    Args:
        description: The traveller's own words, e.g. "I'm Jain" or "vegetarian,
            no nuts".

    Returns:
        The dietary profile: normalised labels, ingredients to avoid, any
        clarifying questions worth asking, extra search terms that help find
        suitable restaurants, and a note on what cannot be verified.
    """

    profile = await _resolve_dietary_profile(description, OpenAIProvider())
    return profile.model_dump()


@tool
async def discover_restaurants(
    city: str,
    meal: str,
    dietary_requirements: list[str] | None = None,
    area: str | None = None,
    cuisine_preferences: list[str] | None = None,
    output_language: str = "en",
    limit: int = 8,
) -> dict[str, Any]:
    """Find candidate restaurants for a city, meal occasion and diet.

    This is the first step of the search. Pass any extra search terms from the
    dietary profile in `cuisine_preferences` when a diet has no map category.

    Args:
        city: City to search in, e.g. "Barcelona".
        meal: Meal occasion, e.g. "dinner", "brunch", "late-night snacks".
        dietary_requirements: Dietary labels, e.g. ["vegetarian"].
        area: Optional neighbourhood or landmark to search near.
        cuisine_preferences: Optional cuisines or extra search terms.
        output_language: Language code for returned content, e.g. "de".
        limit: How many candidates to return.

    Returns:
        The query that was used and the candidates found, each with its rating,
        number of ratings, price band, website and map link. A restaurant without
        a website cannot have its menu read.
    """

    brief = SearchBrief(
        city=city,
        meal=meal,
        dietary_requirements=dietary_requirements or [],
        area=area,
        cuisine_preferences=cuisine_preferences or [],
        output_language=output_language,
    )

    provider = GooglePlacesProvider()
    restaurants = await provider.discover(brief, limit=limit)

    return {
        "count": len(restaurants),
        "restaurants": [r.model_dump() for r in restaurants],
    }


@tool
async def read_menu(website_url: str) -> dict[str, Any]:
    """Read the menu text from a restaurant's website.

    Fetches the site, finds the menu page and extracts its text. Call this before
    `extract_menu_items`.

    Args:
        website_url: The restaurant's website, from `discover_restaurants`.

    Returns:
        The menu page URL and its raw text, whether prices appear to be published,
        and a note explaining any problem (for example a JavaScript-only site, a
        PDF menu, or a domain that no longer belongs to the restaurant). When
        `has_menu_text` is false, tell the traveller the menu could not be read
        and give them the link instead of guessing at its contents.
    """

    result = await MenuCrawler().crawl(website_url)
    return {
        "menu_url": result.menu_url,
        "raw_text": result.text,
        "has_menu_text": result.has_menu_text,
        "prices_present": result.prices_present,
        "note": result.note,
        "pages_visited": result.pages_visited,
    }


@tool
async def extract_menu_items(
    raw_text: str,
    restaurant_place_id: str,
    menu_url: str | None = None,
    output_language: str = "en",
    forbidden_ingredients: list[str] | None = None,
) -> dict[str, Any]:
    """Turn raw menu text into structured, translated dishes.

    Call this with the `raw_text` returned by `read_menu`.

    Args:
        raw_text: Menu text from `read_menu`.
        restaurant_place_id: The restaurant's place id.
        menu_url: Page the menu came from.
        output_language: Language to translate dishes into.
        forbidden_ingredients: Ingredients the traveller avoids, from the dietary
            profile, used to flag whether each dish is suitable.

    Returns:
        The menu's source language, whether it was translated, and the dishes. Each
        dish carries a price only when the menu published one: when
        `price_available` is false there is no price to show and you must say so
        rather than estimating.
    """

    menu = await _extract_menu(
        raw_text=raw_text,
        restaurant_place_id=restaurant_place_id,
        menu_url=menu_url,
        output_language=output_language,
        forbidden_ingredients=forbidden_ingredients or [],
        llm=OpenAIProvider(),
    )

    payload = menu.model_dump()

    # A system prompt alone has proven insufficient here: when extraction returns
    # nothing, the model tends to fill the gap with dishes mentioned in reviews and
    # present them as menu items. Returning an explicit instruction alongside the
    # empty result makes the constraint part of the tool's own output, which the
    # model treats as data rather than as advice it can weigh up.
    if not menu.items:
        payload["menu_available"] = False
        payload["instruction"] = (
            "No menu was read for this restaurant. You must NOT list any dishes "
            "for it, and must NOT use dishes mentioned in reviews as menu items or "
            "as 'menu highlights'. State that the menu could not be read, give the "
            "menu link if there is one, and base any recommendation on reviews "
            "only, clearly attributed to reviewers."
        )
    else:
        payload["menu_available"] = True

    return payload


@tool
async def get_restaurant_reviews(place_id: str, limit: int = 5) -> dict[str, Any]:
    """Fetch published reviews for one restaurant.

    Call this only for shortlisted restaurants; fetching reviews costs more than
    the basic search. Follow it with `analyse_restaurant_reviews`.

    Args:
        place_id: The restaurant's place id from `discover_restaurants`.
        limit: Maximum number of reviews to fetch.

    Returns:
        The reviews, each with its text, rating and language.
    """

    reviews = await GooglePlacesProvider().get_reviews(place_id, limit=limit)
    # Cached so the analysis step does not need a second billable call.
    _review_cache[place_id] = reviews
    return {
        "count": len(reviews),
        "reviews": [r.model_dump() for r in reviews],
    }


@tool
async def analyse_restaurant_reviews(
    place_id: str,
    context: str,
    output_language: str = "en",
) -> dict[str, Any]:
    """Summarise a restaurant's reviews, good and bad, for this traveller.

    Uses the reviews fetched by `get_restaurant_reviews`, so call that first.

    Args:
        place_id: The restaurant's place id.
        context: The traveller's situation, e.g. "vegetarian dinner, gluten-free",
            used to find reviews that speak to it directly.
        output_language: Language to write the findings in.

    Returns:
        Recurring praise, recurring complaints, and review excerpts relevant to the
        traveller's context. Report the complaints as well as the praise.
    """

    reviews = _review_cache.get(place_id, [])
    insight = await _analyze_reviews(
        reviews=reviews,
        restaurant_place_id=place_id,
        context=context,
        output_language=output_language,
        llm=OpenAIProvider(),
    )
    return insight.model_dump()


# The complete toolset handed to the agent.
AGENT_TOOLS = [
    resolve_dietary_profile,
    discover_restaurants,
    read_menu,
    extract_menu_items,
    get_restaurant_reviews,
    analyse_restaurant_reviews,
]
