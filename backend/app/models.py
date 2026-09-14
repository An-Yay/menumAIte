"""Domain models shared across the agent's tools and pipeline steps.

These Pydantic types are the common vocabulary of the application. Every tool
either consumes or produces one of these, which keeps the agent's inputs and
outputs validated and self-documenting.

A guiding rule encoded here: **unavailable data is represented explicitly, never
faked.** Most notably, menu prices are frequently not published online, so
`MenuItem` models a missing price as a first-class state rather than a blank
string or a guessed number.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

# Common meal occasions, used to offer quick-pick suggestions during intake.
# `SearchBrief.meal` is deliberately a free-form string rather than an enum:
# travellers ask for brunch, snacks, late-night food, coffee or dessert, and we
# do not want the model to reject a perfectly valid request it has not seen.
COMMON_MEALS: tuple[str, ...] = (
    "breakfast",
    "brunch",
    "lunch",
    "snacks",
    "dinner",
    "late-night",
    "coffee",
    "dessert",
)


class PipelineStep(str, Enum):
    """The named stages of the agent's work.

    Each stage emits progress so the traveller can see *how* a recommendation
    was reached, which is a core requirement of the product.
    """

    INTAKE = "intake"
    DISCOVER = "discover"
    SHORTLIST = "shortlist"
    FETCH_MENU = "fetch_menu"
    TRANSLATE_MENU = "translate_menu"
    ANALYSE_REVIEWS = "analyse_reviews"
    CONTEXT_REVIEW_SEARCH = "context_review_search"
    SUGGEST = "suggest"


class SearchBrief(BaseModel):
    """The confirmed outcome of the intake conversation.

    Built once the traveller's requirements are unambiguous, and then used to
    drive the rest of the pipeline. Keeping it a single object means the agent
    never has to re-derive intent from raw chat history.
    """

    city: str = Field(description="City the traveller is eating in, e.g. 'Barcelona'.")
    meal: str = Field(
        description=(
            "Meal occasion in the traveller's own words, e.g. 'dinner', 'brunch', "
            f"'snacks'. Common values: {', '.join(COMMON_MEALS)}."
        )
    )
    dietary_requirements: list[str] = Field(
        default_factory=list,
        description=(
            "Resolved dietary constraints, e.g. ['vegetarian'], ['vegan', "
            "'gluten-free']. Ambiguities are clarified during intake so this "
            "list is unambiguous by the time the search runs."
        ),
    )
    area: str | None = Field(
        default=None,
        description="Optional neighbourhood or landmark to search near.",
    )
    cuisine_preferences: list[str] = Field(
        default_factory=list,
        description="Optional preferred cuisines, e.g. ['Catalan', 'Middle Eastern'].",
    )
    budget: str | None = Field(
        default=None,
        description="Optional free-form budget hint, e.g. 'cheap', 'mid-range'.",
    )
    group_size: int | None = Field(
        default=None, ge=1, description="Optional number of diners."
    )
    output_language: str = Field(
        default="en",
        description=(
            "Language the traveller wants results in. Menus written in another "
            "language are translated into this one."
        ),
    )


class Restaurant(BaseModel):
    """A candidate restaurant as returned by the places provider."""

    place_id: str = Field(description="Provider-specific stable identifier.")
    name: str
    rating: float | None = Field(
        default=None, description="Average rating, when the provider has one."
    )
    rating_count: int | None = Field(
        default=None, description="Number of ratings behind `rating`."
    )
    price_level: str | None = Field(
        default=None,
        description=(
            "Coarse provider price bucket (e.g. 'PRICE_LEVEL_MODERATE'). This is "
            "a band, not an actual menu price."
        ),
    )
    address: str | None = None
    website_url: str | None = Field(
        default=None,
        description="Restaurant's own site; the starting point for menu crawling.",
    )
    maps_url: str | None = Field(
        default=None, description="Provider map link, shown to the traveller."
    )
    primary_type: str | None = Field(
        default=None, description="Provider category, e.g. 'Vegan Restaurant'."
    )


class Review(BaseModel):
    """A single customer review, as published by the places provider."""

    text: str
    rating: float | None = None
    author: str | None = None
    language: str | None = Field(
        default=None, description="BCP-47 language code the review was written in."
    )
    published_at: str | None = None
    source_url: str | None = None


class MenuItem(BaseModel):
    """A dish read from a restaurant's menu.

    Price handling is deliberate: many restaurants do not publish prices online.
    `price_amount` stays `None` in that case and `price_available` is `False`, so
    the interface can state plainly that the price is not listed. We never invent
    a number.
    """

    name: str = Field(description="Dish name in the traveller's output language.")
    original_name: str | None = Field(
        default=None,
        description="Dish name as printed on the menu, before translation.",
    )
    description: str | None = None
    price_amount: float | None = Field(
        default=None,
        description="Numeric price when the menu publishes one, otherwise None.",
    )
    price_currency: str | None = Field(
        default=None, description="ISO currency code for `price_amount`, e.g. 'EUR'."
    )
    price_available: bool = Field(
        default=False,
        description=(
            "True only when a price was actually found on the menu. When False, "
            "the traveller is told the price is not listed."
        ),
    )
    dietary_tags: list[str] = Field(
        default_factory=list,
        description="Dietary properties inferred from the menu, e.g. ['vegan'].",
    )
    matches_requirements: bool | None = Field(
        default=None,
        description="Whether this dish satisfies the brief's dietary requirements.",
    )


class Menu(BaseModel):
    """The menu extracted for one restaurant, plus provenance for transparency."""

    restaurant_place_id: str
    menu_url: str | None = Field(
        default=None, description="Page the menu was actually read from."
    )
    source_language: str | None = Field(
        default=None, description="Language the menu was written in, if detected."
    )
    was_translated: bool = False
    items: list[MenuItem] = Field(default_factory=list)
    retrieval_note: str | None = Field(
        default=None,
        description=(
            "Human-readable explanation when a menu could not be read, e.g. the "
            "menu is a scanned image. Surfaced instead of guessing content."
        ),
    )


class ReviewInsight(BaseModel):
    """The outcome of reading a restaurant's reviews.

    This is *domain* data that feeds the final recommendation. The agent's
    internal reasoning and telemetry are modelled separately, by `Observation`
    further down, so that review findings stay independent of observability.

    Covers both required angles: a balanced positive/negative summary, and
    targeted findings for the traveller's specific situation.
    """

    restaurant_place_id: str
    positive_points: list[str] = Field(
        default_factory=list, description="Recurring praise found in reviews."
    )
    negative_points: list[str] = Field(
        default_factory=list, description="Recurring complaints found in reviews."
    )
    context_matches: list[str] = Field(
        default_factory=list,
        description=(
            "Review excerpts that speak directly to the traveller's context, "
            "e.g. mentions of vegetarian choice or gluten-free handling."
        ),
    )
    reviews_considered: int = 0


class Suggestion(BaseModel):
    """A final recommendation for one restaurant."""

    restaurant: Restaurant
    reasoning: str = Field(
        description="Why this restaurant fits the brief, in plain language."
    )
    recommended_items: list[MenuItem] = Field(
        default_factory=list,
        description="Specific dishes to order, drawn from the extracted menu.",
    )
    review_insight: ReviewInsight | None = None
    menu_url: str | None = None
    caveats: list[str] = Field(
        default_factory=list,
        description=(
            "Honest caveats, e.g. 'prices are not published online' or "
            "'reviews mention slow service at peak times'."
        ),
    )


# ---------------------------------------------------------------------------
# Observability / "show your work" models
#
# The interface renders an expandable reasoning panel: a nested tree of what the
# agent did, which tools it called, and which LLM generations happened, with
# timings and token metadata. Strands emits OpenTelemetry spans natively, so
# these models mirror OTel concepts (trace id, span id, parent span id) to allow
# real spans to be mapped straight into the interface instead of maintaining a
# separate, parallel log format.
# ---------------------------------------------------------------------------


class ObservationKind(str, Enum):
    """What sort of node an `Observation` represents.

    Mirrors the usual telemetry vocabulary so the interface can style each node
    appropriately (a tool call looks different from an LLM generation).
    """

    SPAN = "span"  # A unit of work, may contain children.
    GENERATION = "generation"  # An LLM call, carries model and token metadata.
    TOOL = "tool"  # A tool/function invocation by the agent.
    EVENT = "event"  # A point-in-time note with no duration.


class ObservationStatus(str, Enum):
    """Outcome of an observation, used for colouring and error surfacing."""

    RUNNING = "running"
    OK = "ok"
    ERROR = "error"


class GenerationMetadata(BaseModel):
    """Model and token details for an LLM call.

    Populated for `ObservationKind.GENERATION` nodes. Token counts and latency
    make the reasoning panel genuinely useful for debugging and for showing the
    cost of each step.
    """

    model_id: str | None = Field(
        default=None, description="Model that produced the output, e.g. a Gemini id."
    )
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    # The model's intermediate reasoning, when the provider exposes it. Shown in
    # the collapsible "thinking" section of the interface.
    reasoning: str | None = Field(
        default=None,
        description="Model-provided reasoning/thinking text, when available.",
    )
    finish_reason: str | None = None


class ToolMetadata(BaseModel):
    """Details of a tool invocation.

    Strands drives the pipeline by calling tools, so tool nodes form the backbone
    of the visible process: which tool ran, with what arguments, and what it
    returned.
    """

    tool_name: str
    arguments: dict[str, object] | None = Field(
        default=None, description="Arguments the agent passed to the tool."
    )
    result_summary: str | None = Field(
        default=None,
        description=(
            "Short summary of the tool result. Full payloads stay in the domain "
            "models rather than being duplicated into telemetry."
        ),
    )


class Observation(BaseModel):
    """One node in the agent's reasoning tree.

    Observations are streamed to the client as work happens. `parent_span_id`
    lets the interface rebuild the hierarchy and render an expandable tree, so a
    traveller can open up any step and inspect what the agent actually did.
    """

    # --- Identity and hierarchy (OpenTelemetry-compatible) ---
    span_id: str = Field(description="Unique id of this observation.")
    trace_id: str | None = Field(
        default=None, description="Id of the overall trace this belongs to."
    )
    parent_span_id: str | None = Field(
        default=None,
        description="Parent observation id; None for the root of the trace.",
    )

    # --- What happened ---
    kind: ObservationKind = ObservationKind.SPAN
    name: str = Field(description="Short label, e.g. 'discover_restaurants'.")
    step: PipelineStep | None = Field(
        default=None,
        description="Pipeline stage this belongs to, when it maps to one.",
    )
    message: str | None = Field(
        default=None, description="Human-readable description for the interface."
    )
    status: ObservationStatus = ObservationStatus.RUNNING
    error: str | None = Field(
        default=None, description="Failure detail when `status` is ERROR."
    )

    # --- Timing ---
    started_at: str | None = Field(
        default=None, description="ISO-8601 start timestamp."
    )
    ended_at: str | None = Field(default=None, description="ISO-8601 end timestamp.")
    duration_ms: float | None = None

    # --- Kind-specific detail ---
    generation: GenerationMetadata | None = Field(
        default=None, description="Set for GENERATION observations."
    )
    tool: ToolMetadata | None = Field(
        default=None, description="Set for TOOL observations."
    )

    # --- Free-form extras ---
    attributes: dict[str, object] | None = Field(
        default=None,
        description="Additional OTel-style attributes for display or debugging.",
    )

