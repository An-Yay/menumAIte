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
from app.tools.web_search import search_menu_online as _search_menu_online

# Reviews fetched during discovery are cached per place id so the reviews can be
# fetched once and then analysed without paying for a second Places call. Scoped
# to the process, which is sufficient for a locally run session.
_review_cache: dict[str, list[Review]] = {}

# Menu text is no longer cached between tool calls: `get_menu` crawls and extracts
# within a single call, so the large raw text never leaves the server or passes
# through the model's context.


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
async def get_menu(
    restaurant_name: str,
    city: str,
    website_url: str,
    restaurant_place_id: str,
    currency: str,
    output_language: str = "en",
    forbidden_ingredients: list[str] | None = None,
) -> dict[str, Any]:
    """Read a restaurant's menu and return its dishes, translated and priced.

    Does the whole job in one call: reads the restaurant's website (including PDF
    menus), extracts and translates the dishes, flags them against the traveller's
    dietary needs, and falls back to searching the web if the website cannot be
    read. Call it once per shortlisted restaurant.

    Args:
        restaurant_name: The restaurant's name, used if a web search is needed.
        city: The city it is in, so a search cannot match a namesake elsewhere.
        website_url: Its website, from `discover_restaurants`.
        restaurant_place_id: Its place id, from `discover_restaurants`.
        currency: ISO 4217 code for the local currency, e.g. "EUR" in Barcelona,
            "AUD" in Sydney, "INR" in Mumbai. Menus often print prices with no
            currency, so this is attached to them.
        output_language: Language to translate dishes into.
        forbidden_ingredients: Ingredients the traveller avoids, used to flag each
            dish as suitable or not.

    Returns:
        `items` holds the dishes. Each has a price only when the menu actually
        published one: where `price_available` is false, say the price is not listed
        rather than estimating. `source` says where the menu came from, and when it
        is a listing or delivery site rather than the restaurant, mention that
        because those prices can be stale.

        When `menu_available` is false, no menu could be read. Say so, give the link,
        and do not name any dishes for that restaurant.
    """

    crawl = await MenuCrawler().crawl(website_url)

    menu = None
    source = "the restaurant's website"

    if crawl.has_menu_text:
        menu = await _extract_menu(
            raw_text=crawl.text,
            restaurant_place_id=restaurant_place_id,
            menu_url=crawl.menu_url,
            output_language=output_language,
            forbidden_ingredients=forbidden_ingredients or [],
            llm=OpenAIProvider(),
            fallback_currency=currency,
        )

    # Fall back to searching the web only when reading the site produced nothing.
    # Doing this here, rather than leaving it to the agent, means the fallback is
    # never forgotten and never used unnecessarily.
    if menu is None or not menu.items:
        search = await _search_menu_online(
            restaurant_name=restaurant_name, city=city, website_url=website_url
        )
        found = search.get("items") or []
        if found:
            source = search.get("source_name") or "a web search"
            return {
                "menu_available": True,
                "menu_url": search.get("menu_url") or crawl.menu_url,
                "source": source,
                "source_language": None,
                "items": [
                    {
                        "name": item.get("name"),
                        "description": item.get("description"),
                        "price_amount": item.get("price_amount"),
                        "price_currency": currency if item.get("price_available") else None,
                        "price_available": bool(item.get("price_available")),
                        "dietary_tags": [],
                        "matches_requirements": None,
                    }
                    for item in found
                ],
                "note": search.get("note"),
            }

        return {
            "menu_available": False,
            "menu_url": crawl.menu_url or website_url,
            "items": [],
            "note": crawl.note or search.get("note") or "No menu could be read.",
            "instruction": (
                "No menu was read for this restaurant. Do NOT list any dishes for "
                "it, and do not turn dishes mentioned in reviews into menu items. "
                "Say the menu could not be read, give the link, and base any "
                "recommendation on reviews only, clearly attributed to reviewers."
            ),
        }

    payload = menu.model_dump()
    payload["menu_available"] = True
    payload["source"] = source
    payload["pages_visited"] = crawl.pages_visited
    if crawl.note:
        payload["note"] = crawl.note
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


# The toolset handed to the agent.
#
# Reading a menu used to be two tools (fetch the page, then extract from it) plus a
# separate web-search fallback. The model regularly called the first and skipped the
# rest, and then recommended dishes it had never actually read. Those steps are not
# decisions — a menu is always worth structuring once fetched — so they were merged
# into `get_menu`. The agent keeps the genuine judgements: which restaurants to
# shortlist, which dishes to suggest, and when to ask a clarifying question.
AGENT_TOOLS = [
    resolve_dietary_profile,
    discover_restaurants,
    get_menu,
    get_restaurant_reviews,
    analyse_restaurant_reviews,
]
