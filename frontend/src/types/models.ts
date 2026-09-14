/**
 * Domain models shared with the backend agent.
 *
 * These TypeScript types mirror `backend/app/models.py` (Pydantic) field-for-field,
 * so the frontend can be developed against a mock stream now and switched to the
 * real SSE endpoint later without touching the shapes.
 *
 * Guiding rule carried over from the backend: unavailable data is represented
 * explicitly, never faked. Most notably, `MenuItem.price_available` is a
 * first-class flag rather than treating a missing price as a blank/zero.
 */

// Common meal occasions, used to offer quick-pick chips during intake.
// `SearchBrief.meal` is deliberately a free-form string, not a union of these,
// since travellers ask for things we haven't enumerated (e.g. "elevenses").
export const COMMON_MEALS = [
  "breakfast",
  "brunch",
  "lunch",
  "snacks",
  "dinner",
  "late-night",
  "coffee",
  "dessert",
] as const;

// Common dietary requirements offered as chips. `SearchBrief.dietary_requirements`
// is free-form strings for the same reason as `meal`.
export const COMMON_DIETS = [
  "vegetarian",
  "vegan",
  "gluten-free",
  "halal",
  "kosher",
  "jain",
  "dairy-free",
  "nut-free",
] as const;

export type PipelineStep =
  | "intake"
  | "discover"
  | "shortlist"
  | "fetch_menu"
  | "translate_menu"
  | "analyse_reviews"
  | "context_review_search"
  | "suggest";

export interface SearchBrief {
  city: string;
  meal: string;
  dietary_requirements: string[];
  area?: string | null;
  cuisine_preferences: string[];
  budget?: string | null;
  group_size?: number | null;
  output_language: string;
}

export interface Restaurant {
  place_id: string;
  name: string;
  rating?: number | null;
  rating_count?: number | null;
  /** Coarse provider price bucket (e.g. 'PRICE_LEVEL_MODERATE'). A band, not a menu price. */
  price_level?: string | null;
  address?: string | null;
  website_url?: string | null;
  maps_url?: string | null;
  primary_type?: string | null;
}

export interface Review {
  text: string;
  rating?: number | null;
  author?: string | null;
  language?: string | null;
  published_at?: string | null;
  source_url?: string | null;
}

export interface MenuItem {
  name: string;
  original_name?: string | null;
  description?: string | null;
  price_amount?: number | null;
  price_currency?: string | null;
  /** True only when a price was actually found on the menu. Never inferred. */
  price_available: boolean;
  dietary_tags: string[];
  matches_requirements?: boolean | null;
}

export interface Menu {
  restaurant_place_id: string;
  menu_url?: string | null;
  source_language?: string | null;
  was_translated: boolean;
  items: MenuItem[];
  /** Honest note when a menu could not be read, e.g. it's a scanned image. */
  retrieval_note?: string | null;
}

export interface DietaryProfile {
  labels: string[];
  forbidden_ingredients: string[];
  allowed_notes: string[];
  clarifying_questions: string[];
  search_terms: string[];
  verification_note?: string | null;
}

export interface ReviewInsight {
  restaurant_place_id: string;
  positive_points: string[];
  negative_points: string[];
  context_matches: string[];
  reviews_considered: number;
}

export interface Suggestion {
  restaurant: Restaurant;
  reasoning: string;
  recommended_items: MenuItem[];
  review_insight?: ReviewInsight | null;
  menu_url?: string | null;
  caveats: string[];
}

// ---------------------------------------------------------------------------
// Observability / "show your work" models
//
// The reasoning panel renders a nested tree of what the agent did, which
// tools it called, and which LLM generations happened, with timings and
// token metadata. These mirror OpenTelemetry concepts (trace id, span id,
// parent span id) so real spans can be mapped straight in later.
// ---------------------------------------------------------------------------

export type ObservationKind = "span" | "generation" | "tool" | "event";

export type ObservationStatus = "running" | "ok" | "error";

export interface GenerationMetadata {
  model_id?: string | null;
  input_tokens?: number | null;
  output_tokens?: number | null;
  total_tokens?: number | null;
  /** Model-provided reasoning/thinking text, shown in a collapsible section. */
  reasoning?: string | null;
  finish_reason?: string | null;
}

export interface ToolMetadata {
  tool_name: string;
  arguments?: Record<string, unknown> | null;
  result_summary?: string | null;
}

export interface Observation {
  // --- Identity and hierarchy (OpenTelemetry-compatible) ---
  span_id: string;
  trace_id?: string | null;
  parent_span_id?: string | null;

  // --- What happened ---
  kind: ObservationKind;
  name: string;
  step?: PipelineStep | null;
  message?: string | null;
  status: ObservationStatus;
  error?: string | null;

  // --- Timing ---
  started_at?: string | null;
  ended_at?: string | null;
  duration_ms?: number | null;

  // --- Kind-specific detail ---
  generation?: GenerationMetadata | null;
  tool?: ToolMetadata | null;

  // --- Free-form extras ---
  attributes?: Record<string, unknown> | null;
}

// ---------------------------------------------------------------------------
// Stream envelope
//
// Not part of models.py directly, but the minimal shape the planned SSE
// endpoint is expected to emit: a sequence of observation events, then a
// single final event carrying the results. Kept separate so the mock and
// real transport can share this contract.
// ---------------------------------------------------------------------------

// The event vocabulary emitted by the backend over SSE (see
// backend/app/api/chat.py). `session` and `text`/`final` support the live chat
// reply; `suggestions` carries the structured cards; `observation` feeds the
// reasoning panel.
/** One model call in a turn's telemetry trace. */
export interface GenerationRecord {
  label: string;
  model: string;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cost_usd?: number | null;
}

export type AgentStreamEvent =
  | { type: "session"; session_id: string }
  | { type: "observation"; observation: Observation }
  | { type: "text"; text: string }
  | { type: "final"; text: string; trace_id?: string }
  | { type: "suggestions"; suggestions: Suggestion[] }
  | {
      type: "generations";
      generations: GenerationRecord[];
      total_tokens: number;
      total_cost_usd: number;
    }
  | { type: "error"; message: string };
