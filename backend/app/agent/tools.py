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

import asyncio
import re
from typing import Any

from strands import tool

from app.crawler.menu_crawler import MenuCrawler, MenuCrawlResult
from app.language import current_language, ensure_language
from app.models import (
    Menu,
    MenuItem,
    Restaurant,
    Review,
    ReviewInsight,
    SearchBrief,
    Suggestion,
    SuggestionList,
    SuggestionPick,
)
from app.providers.llm import OpenAIProvider
from app.providers.places import GooglePlacesProvider, PlacesError
from app.tools.dietary import resolve_dietary_profile as _resolve_dietary_profile
from app.tools.menu_extract import extract_and_translate_menu as _extract_menu
from app.tools.menu_ocr import read_menu_from_photo as _read_menu_from_photo
from app.tools.reviews import analyze_reviews as _analyze_reviews
from app.tools.web_search import search_menu_online as _search_menu_online

# Everything a tool call has already read is cached here, keyed by place id. Scoped
# to the process, which is sufficient for a locally run session.
#
# These exist so the final recommendation can be assembled from the actual data the
# tools returned, rather than by asking the model to restate it. Restating turned
# out to be unreliable: a restaurant whose menu had just been read correctly, with
# real prices, was later reported by the model as "menu could not be read" when it
# tried to reproduce that data from its own conversation history. Prices and dish
# names are looked up here instead; the model is only asked for judgement calls
# (which restaurant, which dishes to feature, why) that a lookup cannot make.
# How many listing photos to check when looking for a menu. Kept small: each one
# is a billed photo request plus a vision model call, and the search stops at the
# first photo that actually shows a menu, so the usual cost is one.
_MAX_MENU_PHOTOS = 3

_restaurant_cache: dict[str, Restaurant] = {}
_menu_cache: dict[str, Menu] = {}
_review_cache: dict[str, list[Review]] = {}

# Review summaries are keyed by place id AND the request they were written for,
# because the summary text is written in the traveller's language. Keying on the
# place alone meant a summary produced for an earlier German request was reused
# verbatim for a later Hinglish one, so a card showed German review points under
# Hinglish prose. The raw reviews above are language-neutral and stay keyed by
# place id alone.
_review_insight_cache: dict[tuple[str, str], ReviewInsight] = {}


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
        output_language=current_language(),
    )

    provider = GooglePlacesProvider()
    restaurants = await provider.discover(brief, limit=limit)

    for restaurant in restaurants:
        _restaurant_cache[restaurant.place_id] = restaurant

    return {
        "count": len(restaurants),
        "restaurants": [r.model_dump() for r in restaurants],
    }


@tool
async def get_menu(
    restaurant_name: str,
    city: str,
    restaurant_place_id: str,
    currency: str,
    website_url: str | None = None,
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
        restaurant_place_id: Its place id, from `discover_restaurants`.
        website_url: Its website, from `discover_restaurants`. Pass None when the
            restaurant has none; the other sources are still tried.
        currency: ISO 4217 code for the local currency, e.g. "EUR" in Barcelona,
            "AUD" in Sydney, "INR" in Mumbai. Menus often print prices with no
            currency, so this is attached to them.
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

    menu, source, note = await _read_menu(
        restaurant_name=restaurant_name,
        city=city,
        restaurant_place_id=restaurant_place_id,
        currency=currency,
        website_url=website_url,
        forbidden_ingredients=forbidden_ingredients or [],
    )

    if not menu.items:
        return {
            "menu_available": False,
            "menu_url": menu.menu_url,
            "items": [],
            "note": menu.retrieval_note,
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
    if note:
        payload["note"] = note
    return payload


async def _read_menu(
    *,
    restaurant_name: str,
    city: str,
    restaurant_place_id: str,
    currency: str | None,
    website_url: str | None,
    forbidden_ingredients: list[str],
) -> tuple[Menu, str, str | None]:
    """Read a restaurant's menu, trying every source in turn, and cache the result.

    Returns the menu, a short description of where it came from, and an optional
    note. The menu's `items` are empty when nothing could be read. Shared by the
    `get_menu` tool and the assembly-time backfill so both get the identical
    crawl -> PDF -> web search -> photo pipeline.
    """

    # A restaurant with no website skips straight to the later sources rather than
    # being written off; its menu may still exist in a search result or a photo.
    crawl = (
        await MenuCrawler().crawl(website_url)
        if website_url
        else MenuCrawlResult(website_url="", note="no website is listed")
    )

    if crawl.has_menu_text:
        menu = await _extract_menu(
            raw_text=crawl.text,
            restaurant_place_id=restaurant_place_id,
            menu_url=crawl.menu_url,
            forbidden_ingredients=forbidden_ingredients,
            llm=OpenAIProvider(),
            fallback_currency=currency,
        )
        if menu.items:
            _menu_cache[restaurant_place_id] = menu
            return menu, "the restaurant's website", crawl.note

    # Web search fallback, only when reading the site produced nothing.
    search = await _search_menu_online(
        restaurant_name=restaurant_name, city=city, website_url=website_url
    )
    found = search.get("items") or []
    if found:
        web_menu = Menu(
            restaurant_place_id=restaurant_place_id,
            menu_url=search.get("menu_url") or crawl.menu_url,
            items=[
                MenuItem(
                    name=item.get("name") or "",
                    description=item.get("description"),
                    price_amount=item.get("price_amount"),
                    price_currency=currency if item.get("price_available") else None,
                    price_available=bool(item.get("price_available")),
                )
                for item in found
                if item.get("name")
            ],
        )
        _menu_cache[restaurant_place_id] = web_menu
        return web_menu, (search.get("source_name") or "a web search"), search.get("note")

    # Last resort: a menu photo from the map listing.
    photo_menu = await _menu_from_photo(
        restaurant_place_id=restaurant_place_id, currency=currency
    )
    if photo_menu is not None and photo_menu.items:
        _menu_cache[restaurant_place_id] = photo_menu
        return (
            photo_menu,
            "a photo of the menu from the restaurant's listing",
            "Transcribed from a customer photo of the menu, so it may be incomplete "
            "or out of date.",
        )

    no_menu = Menu(
        restaurant_place_id=restaurant_place_id,
        menu_url=crawl.menu_url or website_url,
        retrieval_note=crawl.note or search.get("note") or "No menu could be read.",
    )
    _menu_cache[restaurant_place_id] = no_menu
    return no_menu, "", no_menu.retrieval_note


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
async def analyse_restaurant_reviews(place_id: str, context: str) -> dict[str, Any]:
    """Summarise a restaurant's reviews, good and bad, for this traveller.

    Uses the reviews fetched by `get_restaurant_reviews`, so call that first.

    Args:
        place_id: The restaurant's place id.
        context: The traveller's own words about what they are looking for, e.g.
            "vegetarian dinner, gluten-free". Used both to find reviews that speak
            to their situation and to decide which language to write the findings
            in, so pass their phrasing rather than a translation of it.

    Returns:
        Recurring praise, recurring complaints, and review excerpts relevant to the
        traveller's context. Report the complaints as well as the praise.
    """

    reviews = _review_cache.get(place_id, [])
    insight = await _analyze_reviews(
        reviews=reviews,
        restaurant_place_id=place_id,
        context=context,
        llm=OpenAIProvider(),
    )
    _review_insight_cache[(place_id, context)] = insight
    return insight.model_dump()


async def _menu_from_photo(*, restaurant_place_id: str, currency: str) -> Menu | None:
    """Try to read a menu from one photo on the restaurant's map listing.

    Returns None when no photo is available or none of it could be read, so the
    caller falls through to reporting that no menu was found.
    """

    try:
        photo_urls = await GooglePlacesProvider().get_photo_urls(
            restaurant_place_id, limit=_MAX_MENU_PHOTOS
        )
    except PlacesError:
        return None

    # Photos come back in the provider's own order, which is rarely menu-first, so
    # the first one is often the dining room or a plate of food. Each is tried in
    # turn and the loop stops at the first that is actually a menu, which keeps the
    # usual cost at a single call while giving a realistic chance of finding one.
    found: list[dict[str, Any]] = []
    for photo_url in photo_urls:
        result = await _read_menu_from_photo(photo_url=photo_url)
        found = result.get("items") or []
        if found:
            break

    if not found:
        return None

    return Menu(
        restaurant_place_id=restaurant_place_id,
        items=[
            MenuItem(
                name=item.get("name") or "",
                description=item.get("description"),
                price_amount=item.get("price_amount"),
                price_currency=currency if item.get("price_available") else None,
                price_available=bool(item.get("price_available")),
            )
            for item in found
            if item.get("name")
        ],
        retrieval_note=(
            "Read from a customer photo of the menu; it may be incomplete."
        ),
    )


def _clean_caveat(text: str) -> str | None:
    """Reduce a model-written caveat to a short, safe remark, or drop it.

    The model has repeatedly pasted raw tool output (a JSON object, a markdown
    citation link, or both concatenated) into a caveat instead of summarising it.
    Rather than trying to recognise every shape that bad output can take, this
    truncates at the first character that signals pasted data (an opening brace or
    bracket, or a markdown link) and keeps only the prose before it. A caveat with
    nothing usable before that point is dropped; a short prefix that happens to
    precede junk is still worth keeping.
    """

    stripped = text.strip()
    if not stripped:
        return None

    cut = len(stripped)
    for marker in ("{", "[", "](", "## ["):
        index = stripped.find(marker)
        if index != -1:
            cut = min(cut, index)

    cleaned = stripped[:cut].strip().rstrip("#*_-— ")
    if not cleaned or len(cleaned) < 8 or len(cleaned) > 300:
        return None
    return cleaned


async def assemble_suggestion(
    pick: SuggestionPick, *, review_context: str = ""
) -> Suggestion | None:
    """Build one `Suggestion` from a model's pick and the data already gathered.

    Returns None when the restaurant itself was never looked up (an invalid
    place_id from the model), which the caller drops rather than showing an empty
    card. Reviews are fetched here as a fallback if the agent did not analyse them.
    """

    restaurant = _restaurant_cache.get(pick.place_id)
    if restaurant is None:
        return None

    # Read the menu here if the agent did not during its run. Like reviews, a menu
    # should be on every recommended card, but being autonomous the agent sometimes
    # recommends restaurants without having called get_menu (it may stop after
    # discovery). Backfilling in code guarantees the card is not left menu-less.
    menu = _menu_cache.get(pick.place_id)
    if menu is None:
        # Currency is unknown here (the agent, which supplies it, was not involved),
        # so prices are read without one; the common paths still run through the
        # agent's own get_menu call where currency is known.
        menu, _, _ = await _read_menu(
            restaurant_name=restaurant.name,
            city=restaurant.address or "",
            restaurant_place_id=restaurant.place_id,
            currency=None,
            website_url=restaurant.website_url,
            forbidden_ingredients=[],
        )

    all_items = menu.items if menu else []

    # Match the model's chosen dish names against the actual menu, case-insensitively
    # and allowing a partial match, so small rewordings ("Dosa" vs "Plain Dosa")
    # still resolve to the right item.
    recommended: list[MenuItem] = []
    for wanted in pick.recommended_dish_names:
        wanted_lower = wanted.lower()
        match = next(
            (
                item
                for item in all_items
                if item.name.lower() == wanted_lower or wanted_lower in item.name.lower()
            ),
            None,
        )
        if match:
            recommended.append(match)

    # If nothing named by the model matched, but real dishes exist, still show a
    # few: an empty card for a restaurant with a perfectly good menu is worse than
    # showing dishes the model did not explicitly name.
    if not recommended and all_items:
        recommended = all_items[:4]

    # The model's caveats are meant to be a short prose remark, but it has been
    # observed pasting a raw tool result (a JSON blob, or a citation link plus one)
    # in here instead of summarising it. Such text is filtered out rather than
    # shown to the traveller; the real caveat (the menu's own retrieval note) is
    # already added from data, not from the model's retelling of it.
    caveats = [c for raw in pick.caveats if (c := _clean_caveat(raw)) is not None]
    if menu and menu.retrieval_note and menu.retrieval_note not in caveats:
        caveats.append(menu.retrieval_note)

    # Every recommended restaurant should carry a review summary, since positive
    # and negative reviews are a core part of the answer. The agent is supposed to
    # call the review tools during its run, but being autonomous it sometimes skips
    # them; when a card has no cached insight, fetch and analyse the reviews here so
    # the card is never missing them.
    insight = _review_insight_cache.get(pick.place_id)
    if insight is None:
        insight = await _ensure_review_insight(
            place_id=pick.place_id, context=review_context
        )

    return Suggestion(
        restaurant=restaurant,
        reasoning=pick.reasoning,
        recommended_items=recommended,
        review_insight=insight,
        menu_url=menu.menu_url if menu else None,
        caveats=caveats,
    )


async def _ensure_review_insight(
    *, place_id: str, context: str
) -> ReviewInsight | None:
    """Fetch and analyse a restaurant's reviews if not already done this session.

    Returns None on any failure, so a card can still be shown without a review
    summary rather than the whole recommendation failing.
    """

    try:
        reviews = _review_cache.get(place_id)
        if reviews is None:
            reviews = await GooglePlacesProvider().get_reviews(place_id, limit=5)
            _review_cache[place_id] = reviews
        if not reviews:
            return None
        insight = await _analyze_reviews(
            reviews=reviews,
            restaurant_place_id=place_id,
            context=context,
            llm=OpenAIProvider(),
        )
        _review_insight_cache[(place_id, context)] = insight
        return insight
    except Exception:  # noqa: BLE001 - reviews are best-effort, never fatal
        return None


async def assemble_suggestions(
    picks: list[SuggestionPick], *, review_context: str = ""
) -> SuggestionList:
    """Build the full `SuggestionList` from the model's picks.

    `review_context` is used only when a card is missing its review summary and the
    reviews have to be fetched here as a fallback.

    The finished cards are then checked for language, because a card is assembled
    from several separate model calls and any one of them can slip into the wrong
    language — most often the review summary echoing the language of the reviews it
    read.
    """

    suggestions: list[Suggestion] = []
    for pick in picks:
        built = await assemble_suggestion(pick, review_context=review_context)
        if built is not None:
            suggestions.append(built)

    return SuggestionList(
        suggestions=[await _verify_language(s) for s in suggestions]
    )


async def _verify_segments(segments: list[str]) -> list[str] | None:
    """Verify a card's prose segments as one block; return corrected list or None.

    The segments are numbered and checked together in a single call. Returns None
    when there is nothing to check, when the text was already correct, or when the
    corrected block does not split back into the same number of segments (so a
    mangled correction can never silently reshape the card).
    """

    if not any(s.strip() for s in segments):
        return None

    numbered = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(segments))
    corrected = await ensure_language(numbered, OpenAIProvider())
    if corrected == numbered:
        return None

    # Parse the numbered lines back out, tolerating wrapped lines by attaching them
    # to the current item.
    parsed: list[str] = []
    for line in corrected.splitlines():
        match = re.match(r"^\s*(\d+)\.\s?(.*)$", line)
        if match:
            parsed.append(match.group(2).strip())
        elif parsed:
            parsed[-1] = f"{parsed[-1]} {line.strip()}".strip()

    return parsed if len(parsed) == len(segments) else None


async def _verify_language(suggestion: Suggestion) -> Suggestion:
    """Correct any part of a card that is not in the expected language.

    All of the card's generated prose is verified in a single call — the reasoning,
    the caveats and the review points together — rather than one call per field, so
    a card costs one check rather than a dozen. `ensure_language` returns the text
    unchanged when it is already correct, so the common case adds only that one
    cheap call. Dish names are deliberately excluded: they are what is printed on
    the menu, and a diner needs to be able to point at them.
    """

    insight = suggestion.review_insight

    # Collect every prose field into one numbered block, remembering where each
    # piece came from so the corrected block can be split back out.
    segments: list[str] = [suggestion.reasoning, *suggestion.caveats]
    counts = {"reasoning": 1, "caveats": len(suggestion.caveats)}
    if insight is not None:
        segments += insight.positive_points + insight.negative_points + insight.context_matches
        counts["positive"] = len(insight.positive_points)
        counts["negative"] = len(insight.negative_points)
        counts["context"] = len(insight.context_matches)

    fixed = await _verify_segments(segments)
    if fixed is None:  # Unchanged or unrecoverable; keep the card as built.
        return suggestion

    # Split the corrected segments back into their fields, in the same order.
    cursor = 0

    def take(n: int) -> list[str]:
        nonlocal cursor
        chunk = fixed[cursor : cursor + n]
        cursor += n
        return chunk

    reasoning = take(1)[0]
    caveats = take(counts["caveats"])

    if insight is not None:
        insight = insight.model_copy(
            update={
                "positive_points": take(counts["positive"]),
                "negative_points": take(counts["negative"]),
                "context_matches": take(counts["context"]),
            }
        )

    return suggestion.model_copy(
        update={
            "reasoning": reasoning,
            "caveats": caveats,
            "review_insight": insight,
        }
    )


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
