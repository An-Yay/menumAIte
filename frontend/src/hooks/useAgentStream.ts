/**
 * Consumes the agent's event stream and exposes state for the UI.
 *
 * Currently backed by `mocks/mockStream.runAgent`. Once the real SSE endpoint
 * exists, only the import + the body of `start()` need to change (read from
 * an EventSource/fetch stream instead of the async generator) -- the shape
 * consumed by components stays the same.
 */

import { useCallback, useRef, useState } from "react";
import { runAgent } from "../mocks/mockStream";
import type { Observation, SearchBrief, Suggestion } from "../types/models";

export type AgentRunStatus = "idle" | "running" | "done" | "error";

export interface AgentStreamState {
  status: AgentRunStatus;
  /** Observations keyed by span_id; updates in place as spans start/finish. */
  observations: Map<string, Observation>;
  /** Insertion order of span_ids, stable even as their status updates. */
  order: string[];
  suggestions: Suggestion[] | null;
  errorMessage: string | null;
}

const initialState: AgentStreamState = {
  status: "idle",
  observations: new Map(),
  order: [],
  suggestions: null,
  errorMessage: null,
};

export function useAgentStream() {
  const [state, setState] = useState<AgentStreamState>(initialState);
  const abortRef = useRef<AbortController | null>(null);

  const start = useCallback(async (brief: SearchBrief) => {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    setState({ ...initialState, status: "running" });

    try {
      for await (const event of runAgent(brief, controller.signal)) {
        if (controller.signal.aborted) return;

        if (event.type === "observation") {
          setState((prev) => {
            const observations = new Map(prev.observations);
            const isNew = !observations.has(event.observation.span_id);
            observations.set(event.observation.span_id, event.observation);
            return {
              ...prev,
              observations,
              order: isNew ? [...prev.order, event.observation.span_id] : prev.order,
            };
          });
        } else if (event.type === "result") {
          setState((prev) => ({ ...prev, status: "done", suggestions: event.suggestions }));
        } else if (event.type === "error") {
          setState((prev) => ({ ...prev, status: "error", errorMessage: event.message }));
        }
      }
    } catch (err) {
      if (controller.signal.aborted) return;
      setState((prev) => ({
        ...prev,
        status: "error",
        errorMessage: err instanceof Error ? err.message : "Unknown error running the agent.",
      }));
    }
  }, []);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    setState(initialState);
  }, []);

  return { ...state, start, reset };
}
