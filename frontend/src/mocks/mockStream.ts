/**
 * Mock stand-in for the planned backend endpoint:
 *   POST /sessions            -> starts a run for a confirmed SearchBrief
 *   GET  /sessions/:id/stream -> SSE stream of `Observation` events, then a
 *                                 final result event.
 *
 * This module fakes that over an async generator so `useAgentStream` (the
 * consumer) doesn't need to know it's mocked. Swapping to the real endpoint
 * later means replacing this file's internals with an EventSource/fetch
 * stream reader behind the same `runAgent()` signature.
 */

import { flattenToObservationEvents, planObservationTree } from "./observations";
import { buildMockSuggestions } from "./suggestions";
import type { AgentStreamEvent, SearchBrief } from "../types/models";

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Runs the mock agent for a confirmed brief, yielding stream events as they
 * "happen". Accepts an AbortSignal so a caller can stop consuming early if
 * the user navigates away or starts a new search.
 */
export async function* runAgent(
  brief: SearchBrief,
  signal?: AbortSignal,
): AsyncGenerator<AgentStreamEvent> {
  const traceId = `trace-${Date.now()}`;
  const plan = planObservationTree(brief);
  const events = flattenToObservationEvents(plan, traceId);

  for (const { observation, delayMs } of events) {
    if (signal?.aborted) return;
    if (delayMs > 0) await sleep(Math.min(delayMs, 900));
    yield { type: "observation", observation };
  }

  if (signal?.aborted) return;
  await sleep(300);
  yield { type: "result", suggestions: buildMockSuggestions(brief) };
}
