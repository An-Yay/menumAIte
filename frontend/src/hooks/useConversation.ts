/**
 * Holds a conversation with the agent.
 *
 * The agent runs the dialogue itself: it greets, asks what it still needs, works
 * through its process and answers follow-up questions, all in whatever language
 * the traveller writes in. This hook therefore keeps no script of its own. It
 * sends messages, keeps the session id so the backend can continue the same
 * conversation, and collects what streams back.
 *
 * Each turn produces one assistant message, which fills in as `text` chunks
 * arrive, plus any reasoning observations and structured suggestions the backend
 * emits for that turn.
 */

import { useCallback, useRef, useState } from "react";
import { streamChat } from "../api/agentClient";
import type { GenerationRecord, Observation, Suggestion } from "../types/models";

export type Turn = {
  id: string;
  role: "user" | "assistant";
  /** Reply text, appended to as the stream arrives. */
  text: string;
  /** Reasoning nodes for this turn, keyed by span id. */
  observations: Map<string, Observation>;
  /** Insertion order of span ids, so the tree renders in the order work happened. */
  observationOrder: string[];
  /** Structured recommendation cards, when this turn produced any. */
  suggestions: Suggestion[] | null;
  /** Model calls made during this turn, with tokens and cost. */
  generations: GenerationRecord[];
  /** Estimated total cost of this turn in USD. */
  costUsd: number;
  /** True while this turn is still streaming. */
  isStreaming: boolean;
  error: string | null;
};

function newTurn(role: Turn["role"], text = ""): Turn {
  return {
    id: `${role}-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    role,
    text,
    observations: new Map(),
    observationOrder: [],
    suggestions: null,
    generations: [],
    costUsd: 0,
    isStreaming: role === "assistant",
    error: null,
  };
}

export function useConversation() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [isBusy, setIsBusy] = useState(false);
  const sessionIdRef = useRef<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  // Guards against sending the same message twice.
  //
  // `isBusy` cannot do this job: it is state, so it is captured by the callback's
  // closure and only updates on the next render. Two calls in quick succession —
  // a double click, or React's development double-invocation — therefore both saw
  // `isBusy === false` and both started a request, which produced two identical
  // replies and made the agent appear to answer before being asked. A ref updates
  // synchronously, so the second call sees the first immediately.
  const inFlightRef = useRef(false);

  /** Apply a change to the assistant turn currently streaming (the last one). */
  const updateCurrent = useCallback((change: (turn: Turn) => Turn) => {
    setTurns((prev) => {
      if (prev.length === 0) return prev;
      const next = [...prev];
      next[next.length - 1] = change(next[next.length - 1]);
      return next;
    });
  }, []);

  const send = useCallback(
    async (message: string) => {
      const trimmed = message.trim();
      if (!trimmed || inFlightRef.current) return;
      inFlightRef.current = true;

      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setIsBusy(true);
      setTurns((prev) => [...prev, newTurn("user", trimmed), newTurn("assistant")]);

      try {
        for await (const event of streamChat(trimmed, {
          sessionId: sessionIdRef.current ?? undefined,
          signal: controller.signal,
        })) {
          if (controller.signal.aborted) return;

          switch (event.type) {
            case "session":
              // Held outside state: it identifies the conversation rather than
              // describing it, and every later turn needs the same value.
              sessionIdRef.current = event.session_id;
              break;

            case "observation":
              updateCurrent((turn) => {
                const observations = new Map(turn.observations);
                const isNew = !observations.has(event.observation.span_id);
                observations.set(event.observation.span_id, event.observation);
                return {
                  ...turn,
                  observations,
                  observationOrder: isNew
                    ? [...turn.observationOrder, event.observation.span_id]
                    : turn.observationOrder,
                };
              });
              break;

            case "text":
              updateCurrent((turn) => ({ ...turn, text: turn.text + event.text }));
              break;

            case "final":
              // Prefer the complete reply: it can differ slightly from the sum of
              // the streamed chunks.
              updateCurrent((turn) => ({ ...turn, text: event.text }));
              break;

            case "suggestions":
              updateCurrent((turn) => ({ ...turn, suggestions: event.suggestions }));
              break;

            case "generations":
              updateCurrent((turn) => ({
                ...turn,
                generations: event.generations,
                costUsd: event.total_cost_usd,
              }));
              break;

            case "error":
              updateCurrent((turn) => ({ ...turn, error: event.message }));
              break;
          }
        }
      } catch (err) {
        if (!controller.signal.aborted) {
          updateCurrent((turn) => ({
            ...turn,
            error:
              err instanceof Error ? err.message : "Could not reach the agent.",
          }));
        }
      } finally {
        // Always released, even when aborted, or the guard would latch on and
        // block every later message.
        inFlightRef.current = false;
        if (!controller.signal.aborted) {
          updateCurrent((turn) => ({ ...turn, isStreaming: false }));
          setIsBusy(false);
        }
      }
    },
    [updateCurrent],
  );

  /** Abandon this conversation and start a new one. */
  const reset = useCallback(() => {
    abortRef.current?.abort();
    inFlightRef.current = false;
    sessionIdRef.current = null;
    setTurns([]);
    setIsBusy(false);
  }, []);

  // The session id is deliberately not returned: it lives in a ref because it is
  // not rendered, and reading a ref during render is unsafe. Nothing outside this
  // hook needs it, since `send` attaches it to each request itself.
  return { turns, isBusy, send, reset };
}
