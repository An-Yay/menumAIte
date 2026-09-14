/**
 * Builds a mock reasoning trace: a nested tree of `Observation`s that mirrors
 * what the real Strands agent is expected to emit once the SSE endpoint is
 * live (see backend/app/models.py PipelineStep + Observation).
 *
 * Each pipeline step is a SPAN with TOOL and/or GENERATION children carrying
 * plausible timings and token counts, so the reasoning panel can be built and
 * demoed without a live backend.
 */

import type {
  GenerationMetadata,
  Observation,
  PipelineStep,
  SearchBrief,
  ToolMetadata,
} from "../types/models";

let counter = 0;
function nextId(prefix: string): string {
  counter += 1;
  return `${prefix}-${counter}`;
}

interface PlannedNode {
  kind: Observation["kind"];
  name: string;
  step: PipelineStep;
  message: string;
  durationMs: number;
  tool?: ToolMetadata;
  generation?: GenerationMetadata;
  children?: PlannedNode[];
}

/** Builds the plan for one full trace, parameterised by the confirmed brief. */
export function planObservationTree(brief: SearchBrief): PlannedNode[] {
  const dietLabel = brief.dietary_requirements.join(", ") || "no specific diet";

  return [
    {
      kind: "span",
      name: "discover_restaurants",
      step: "discover",
      message: `Searching for ${brief.meal} options in ${brief.city}.`,
      durationMs: 900,
      children: [
        {
          kind: "tool",
          name: "places_search",
          step: "discover",
          message: "Querying Google Places API (New) for nearby candidates.",
          durationMs: 620,
          tool: {
            tool_name: "places_search",
            arguments: {
              city: brief.city,
              area: brief.area ?? null,
              meal: brief.meal,
              cuisine_preferences: brief.cuisine_preferences,
            },
            result_summary: "18 candidate restaurants returned.",
          },
        },
      ],
    },
    {
      kind: "span",
      name: "shortlist_restaurants",
      step: "shortlist",
      message: "Ranking candidates against the brief.",
      durationMs: 1400,
      children: [
        {
          kind: "generation",
          name: "shortlist_reasoning",
          step: "shortlist",
          message: "Scoring candidates on rating, relevance and dietary fit.",
          durationMs: 1150,
          generation: {
            model_id: "mock-llm-large",
            input_tokens: 812,
            output_tokens: 214,
            total_tokens: 1026,
            reasoning:
              `Filtering out chains and low-rated spots, prioritising places whose ` +
              `type or reviews mention "${dietLabel}". Kept 5 of 18 candidates.`,
            finish_reason: "stop",
          },
        },
      ],
    },
    {
      kind: "span",
      name: "fetch_and_translate_menus",
      step: "fetch_menu",
      message: "Reading each shortlisted restaurant's menu.",
      durationMs: 2600,
      children: [
        {
          kind: "tool",
          name: "crawl_menu",
          step: "fetch_menu",
          message: "Crawling restaurant websites for menu pages.",
          durationMs: 1800,
          tool: {
            tool_name: "crawl_menu",
            arguments: { restaurant_count: 5 },
            result_summary: "4 menus read successfully, 1 unreadable (scanned PDF).",
          },
        },
        {
          kind: "generation",
          name: "translate_menu_items",
          step: "translate_menu",
          message: `Translating menu items into ${brief.output_language}.`,
          durationMs: 700,
          generation: {
            model_id: "mock-llm-small",
            input_tokens: 1340,
            output_tokens: 980,
            total_tokens: 2320,
            reasoning: "Translated dish names and descriptions, preserved prices as-is.",
            finish_reason: "stop",
          },
        },
      ],
    },
    {
      kind: "span",
      name: "analyse_reviews",
      step: "analyse_reviews",
      message: "Reading reviews for recurring praise and complaints.",
      durationMs: 1300,
      children: [
        {
          kind: "tool",
          name: "fetch_reviews",
          step: "analyse_reviews",
          message: "Fetching recent reviews per restaurant.",
          durationMs: 500,
          tool: {
            tool_name: "fetch_reviews",
            arguments: { restaurant_count: 4, max_reviews: 20 },
            result_summary: "62 reviews collected across 4 restaurants.",
          },
        },
        {
          kind: "generation",
          name: "summarise_reviews",
          step: "analyse_reviews",
          message: "Summarising positive and negative themes.",
          durationMs: 700,
          generation: {
            model_id: "mock-llm-large",
            input_tokens: 2450,
            output_tokens: 340,
            total_tokens: 2790,
            reasoning: "Clustered review text into recurring themes per restaurant.",
            finish_reason: "stop",
          },
        },
      ],
    },
    {
      kind: "span",
      name: "context_review_search",
      step: "context_review_search",
      message: `Searching reviews for mentions relevant to: ${dietLabel}.`,
      durationMs: 800,
      children: [
        {
          kind: "generation",
          name: "find_context_matches",
          step: "context_review_search",
          message: "Matching review excerpts to the traveller's dietary context.",
          durationMs: 800,
          generation: {
            model_id: "mock-llm-large",
            input_tokens: 2450,
            output_tokens: 190,
            total_tokens: 2640,
            reasoning: `Looking specifically for excerpts mentioning ${dietLabel}.`,
            finish_reason: "stop",
          },
        },
      ],
    },
    {
      kind: "span",
      name: "build_suggestions",
      step: "suggest",
      message: "Composing final recommendations.",
      durationMs: 900,
      children: [
        {
          kind: "generation",
          name: "write_suggestions",
          step: "suggest",
          message: "Writing plain-language reasoning for each recommendation.",
          durationMs: 900,
          generation: {
            model_id: "mock-llm-large",
            input_tokens: 3100,
            output_tokens: 420,
            total_tokens: 3520,
            reasoning: "Drafted reasoning and caveats for each shortlisted restaurant.",
            finish_reason: "stop",
          },
        },
      ],
    },
  ];
}

/**
 * Flattens a planned tree into `Observation` start/end event pairs, in the
 * order a real tracer would emit them (start of parent, then children as
 * they run, then the parent's end once children finish).
 */
export function flattenToObservationEvents(
  plan: PlannedNode[],
  traceId: string,
  parentSpanId: string | null = null,
): { observation: Observation; delayMs: number }[] {
  const events: { observation: Observation; delayMs: number }[] = [];

  for (const node of plan) {
    const spanId = nextId(node.kind);
    const startedAt = new Date().toISOString();

    events.push({
      observation: {
        span_id: spanId,
        trace_id: traceId,
        parent_span_id: parentSpanId,
        kind: node.kind,
        name: node.name,
        step: node.step,
        message: node.message,
        status: "running",
        started_at: startedAt,
        generation: node.kind === "generation" ? { ...node.generation, reasoning: null } : null,
        tool: node.kind === "tool" ? { ...node.tool!, result_summary: null } : null,
      },
      delayMs: 0,
    });

    const childEvents = node.children
      ? flattenToObservationEvents(node.children, traceId, spanId)
      : [];
    events.push(...childEvents);

    events.push({
      observation: {
        span_id: spanId,
        trace_id: traceId,
        parent_span_id: parentSpanId,
        kind: node.kind,
        name: node.name,
        step: node.step,
        message: node.message,
        status: "ok",
        started_at: startedAt,
        ended_at: new Date().toISOString(),
        duration_ms: node.durationMs,
        generation: node.generation ?? null,
        tool: node.tool ?? null,
      },
      delayMs: node.durationMs,
    });
  }

  return events;
}
