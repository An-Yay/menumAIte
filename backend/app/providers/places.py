"""Restaurant discovery and reviews.

This module isolates *where* restaurant data comes from. The rest of the
application depends only on the `PlacesProvider` protocol and on our own domain
models, never on a vendor's JSON shape, so the backing service can be replaced
without touching the agent or its tools.

The current implementation uses the Google Places API (New).

Cost note
---------
Places API (New) bills per request and charges more when review content is
requested. Discovery therefore asks only for inexpensive fields, and reviews are
fetched in a second call for shortlisted restaurants alone.
"""

from __future__ import annotations

from typing import Any, Protocol

import httpx

from app.config import get_settings
from app.models import Restaurant, Review, SearchBrief

# Base URL for Places API (New). The older `maps.googleapis.com/maps/api/place`
# endpoints are the legacy API and are not used here.
_PLACES_BASE_URL = "https://places.googleapis.com/v1"

# Fields requested during discovery. Kept intentionally lean: enough to rank and
# shortlist candidates, plus the website link the menu crawler needs.
_DISCOVERY_FIELD_MASK = ",".join(
    (
        "places.id",
        "places.displayName",
        "places.rating",
        "places.userRatingCount",
        "places.priceLevel",
        "places.websiteUri",
        "places.googleMapsUri",
        "places.formattedAddress",
        "places.primaryTypeDisplayName",
    )
)

# Reviews are requested separately, per place, because review content falls into
# a more expensive billing tier than the basic fields above.
_REVIEWS_FIELD_MASK = "reviews"


class PlacesError(RuntimeError):
    """Raised when the places service cannot fulfil a request.

    Surfacing failures explicitly lets the agent tell the traveller that a step
    did not work, instead of silently presenting an empty result as if no
    restaurants existed.
    """


class PlacesProvider(Protocol):
    """The contract the agent's tools rely on for restaurant data."""

    async def discover(self, brief: SearchBrief, limit: int = 10) -> list[Restaurant]:
        """Return candidate restaurants matching the traveller's brief."""
        ...

    async def get_reviews(self, place_id: str, limit: int = 5) -> list[Review]:
        """Return published reviews for a single restaurant."""
        ...

    async def get_photo_urls(self, place_id: str, limit: int = 1) -> list[str]:
        """Return URLs of photos published for a restaurant."""
        ...


def build_discovery_query(brief: SearchBrief) -> str:
    """Turn a structured brief into a natural-language search query.

    Places text search handles conversational phrasing well, so we compose the
    traveller's constraints into a sentence rather than trying to map them onto
    rigid category filters. Returning the query as a value (instead of building
    it inline) keeps it easy to show in the reasoning panel and easy to test.

    Example: "vegetarian gluten-free dinner restaurant in Barcelona near Gracia"
    """

    parts: list[str] = []

    # Dietary requirements first: they are the hardest constraint, and putting
    # them early biases the provider's ranking towards suitable places.
    parts.extend(brief.dietary_requirements)

    # Cuisine preferences are softer hints and follow the dietary terms.
    parts.extend(brief.cuisine_preferences)

    # The meal occasion, in the traveller's own words ("brunch", "late-night").
    if brief.meal:
        parts.append(brief.meal)

    parts.append("restaurant in")
    parts.append(brief.city)

    if brief.area:
        parts.append(f"near {brief.area}")

    return " ".join(part for part in parts if part).strip()


class GooglePlacesProvider:
    """`PlacesProvider` backed by the Google Places API (New)."""

    def __init__(self, api_key: str | None = None, timeout: float = 20.0) -> None:
        """Create a provider.

        The API key is read from application settings by default so that secrets
        stay in the environment and never appear in source or in call sites.
        """

        self._api_key = api_key or get_settings().google_api_key
        if not self._api_key:
            raise PlacesError(
                "GOOGLE_API_KEY is not configured. Set it in the environment or "
                "in a local .env file."
            )
        self._timeout = timeout

    def _headers(self, field_mask: str) -> dict[str, str]:
        """Build request headers.

        Places API (New) authenticates with `X-Goog-Api-Key` and requires an
        explicit field mask so callers only pay for the data they ask for.
        """

        return {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self._api_key or "",
            "X-Goog-FieldMask": field_mask,
        }

    async def discover(self, brief: SearchBrief, limit: int = 10) -> list[Restaurant]:
        """Search for restaurants matching the brief.

        Uses the `places:searchText` endpoint with a natural-language query built
        from the brief, and maps the response onto our `Restaurant` model.
        """

        query = build_discovery_query(brief)
        payload: dict[str, Any] = {
            "textQuery": query,
            # Places API (New) caps this at 20; we stay well below that because
            # each shortlisted place triggers further (billable) work.
            "maxResultCount": min(limit, 20),
        }

        # Ask the provider to return content in the traveller's language where it
        # can, which reduces how much we need to translate later.
        if brief.output_language:
            payload["languageCode"] = brief.output_language

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{_PLACES_BASE_URL}/places:searchText",
                    headers=self._headers(_DISCOVERY_FIELD_MASK),
                    json=payload,
                )
        except httpx.HTTPError as exc:  # Network-level failure.
            raise PlacesError(f"Places request failed: {exc}") from exc

        data = self._parse_response(response)
        return [self._to_restaurant(place) for place in data.get("places", [])]

    async def get_reviews(self, place_id: str, limit: int = 5) -> list[Review]:
        """Fetch reviews for one restaurant.

        Called only for shortlisted restaurants: review content is billed at a
        higher rate than the basic fields used during discovery.
        """

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    f"{_PLACES_BASE_URL}/places/{place_id}",
                    headers=self._headers(_REVIEWS_FIELD_MASK),
                )
        except httpx.HTTPError as exc:
            raise PlacesError(f"Places review request failed: {exc}") from exc

        data = self._parse_response(response)
        reviews = data.get("reviews", []) or []
        return [self._to_review(review) for review in reviews[:limit]]

    async def get_photo_urls(self, place_id: str, limit: int = 1) -> list[str]:
        """Return URLs for a restaurant's published photos.

        Diners very often photograph the menu board or a menu page, so these
        pictures are sometimes the only place a menu exists for a restaurant with
        no website. `limit` defaults to one because each photo is a billed request
        and each one read costs a vision model call on top.
        """

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(
                    f"{_PLACES_BASE_URL}/places/{place_id}",
                    headers=self._headers("photos"),
                )
        except httpx.HTTPError as exc:
            raise PlacesError(f"Places photo request failed: {exc}") from exc

        data = self._parse_response(response)
        photos = data.get("photos", []) or []

        # A photo is referenced by resource name; the bytes come from its `media`
        # endpoint. Width is capped to keep the download and the vision call small.
        return [
            f"{_PLACES_BASE_URL}/{photo['name']}/media"
            f"?maxWidthPx=1200&key={self._api_key}"
            for photo in photos[:limit]
            if photo.get("name")
        ]

    @staticmethod
    def _parse_response(response: httpx.Response) -> dict[str, Any]:
        """Validate an API response and return its decoded body.

        Google reports problems in an `error` object, so a 200 status alone is
        not proof of success. Both cases are converted into `PlacesError` with
        the provider's own message preserved for debugging.
        """

        try:
            data = response.json()
        except ValueError as exc:
            raise PlacesError(
                f"Places returned a non-JSON response (HTTP {response.status_code})."
            ) from exc

        if response.status_code != httpx.codes.OK:
            message = data.get("error", {}).get("message", response.text)
            raise PlacesError(f"Places error (HTTP {response.status_code}): {message}")

        if "error" in data:
            raise PlacesError(f"Places error: {data['error'].get('message')}")

        return data

    @staticmethod
    def _clean_maps_url(place: dict[str, Any]) -> str | None:
        """Return a stable map link for a place.

        The `googleMapsUri` Google returns carries a `g_mp` parameter identifying
        the request that produced it, which is not meaningful to a traveller and
        made shared links behave unpredictably. It is stripped, leaving the `cid`
        that identifies the place itself. When no usable link comes back, one is
        built from the place id instead, which Maps resolves directly.
        """

        raw = place.get("googleMapsUri")
        if raw:
            base, _, query = raw.partition("?")
            kept = [
                part
                for part in query.split("&")
                if part and not part.startswith("g_mp=")
            ]
            return f"{base}?{'&'.join(kept)}" if kept else base

        place_id = place.get("id")
        if place_id:
            return f"https://www.google.com/maps/place/?q=place_id:{place_id}"
        return None

    @staticmethod
    def _to_restaurant(place: dict[str, Any]) -> Restaurant:
        """Map a Places result onto our `Restaurant` model.

        Keeping this translation in one place means the vendor's field names stay
        contained in this module.
        """

        return Restaurant(
            place_id=place.get("id", ""),
            name=(place.get("displayName") or {}).get("text", "Unknown"),
            rating=place.get("rating"),
            rating_count=place.get("userRatingCount"),
            # A coarse band such as "PRICE_LEVEL_MODERATE" — deliberately not
            # treated as a menu price.
            price_level=place.get("priceLevel"),
            address=place.get("formattedAddress"),
            website_url=place.get("websiteUri"),
            maps_url=GooglePlacesProvider._clean_maps_url(place),
            primary_type=(place.get("primaryTypeDisplayName") or {}).get("text"),
        )

    @staticmethod
    def _to_review(review: dict[str, Any]) -> Review:
        """Map a Places review onto our `Review` model.

        Google nests review text under `text.text` and the reviewer under
        `authorAttribution`, and exposes the language the review was written in,
        which later tells us whether translation is needed.
        """

        text_block = review.get("text") or review.get("originalText") or {}
        author = review.get("authorAttribution") or {}

        return Review(
            text=text_block.get("text", ""),
            rating=review.get("rating"),
            author=author.get("displayName"),
            language=text_block.get("languageCode"),
            published_at=review.get("publishTime"),
            source_url=review.get("googleMapsUri"),
        )
