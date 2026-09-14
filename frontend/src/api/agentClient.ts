/**
 * Real transport to the backend agent, replacing the mock stream.
 *
 * The backend exposes the agent at `POST /api/chat` as a Server-Sent Events
 * stream. `EventSource` only supports GET, so the stream is read from a `fetch`
 * response body instead, and SSE frames are parsed by hand. Each frame is one
 * `data:` line of JSON, separated by a blank line.
 *
 * The backend's event vocabulary is mapped onto the `AgentStreamEvent` shape the
 * rest of the app already consumes, so components did not have to change when the
 * mock was swapped for this.
 *
 * Backend events (see backend/app/api/chat.py):
 *   session     -> the conversation id; surfaced so follow-up messages continue it
 *   observation -> a reasoning-tree node (passed through unchanged)
 *   text        -> an incremental chunk of the reply
 *   final       -> the completed reply text
 *   error       -> a failure; partial results remain valid
 */

import type { AgentStreamEvent, SearchBrief } from "../types/models";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

/**
 * Turn a confirmed search brief into the single message the agent starts from.
 *
 * The backend agent runs one conversation from natural language, so the
 * structured brief is rendered into a sentence. Optional fields are only included
 * when set, to keep the prompt clean.
 */
export function briefToMessage(brief: SearchBrief): string {
  const parts: string[] = [];
  const diet = brief.dietary_requirements.join(", ");
  if (diet) parts.push(diet);
  parts.push(brief.meal);
  parts.push(`in ${brief.city}`);
  if (brief.area) parts.push(`near ${brief.area}`);
  if (brief.cuisine_preferences.length) {
    parts.push(`(cuisines: ${brief.cuisine_preferences.join(", ")})`);
  }
  if (brief.budget) parts.push(`budget: ${brief.budget}`);
  if (brief.group_size) parts.push(`for ${brief.group_size} people`);

  return (
    `I'm looking for ${parts.join(" ")}. ` +
    `Please shortlist a few places, read their menus with prices, ` +
    `check the positive and negative reviews, and recommend dishes.`
  );
}

/**
 * Open the agent stream for a message and yield backend events as they arrive.
 *
 * Accepts an AbortSignal so a caller can stop the stream when the user starts a
 * new search or navigates away.
 */
export async function* streamChat(
  message: string,
  options: { sessionId?: string; signal?: AbortSignal } = {},
): AsyncGenerator<AgentStreamEvent> {
  const response = await fetch(`${API_BASE}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message, session_id: options.sessionId ?? null }),
    signal: options.signal,
  });

  if (!response.ok || !response.body) {
    throw new Error(`Agent request failed (HTTP ${response.status}).`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    // SSE frames are separated by a blank line. Process every complete frame in
    // the buffer, leaving any partial trailing frame for the next read.
    let sep = buffer.indexOf("\n\n");
    while (sep !== -1) {
      const frame = buffer.slice(0, sep);
      buffer = buffer.slice(sep + 2);
      const parsed = parseFrame(frame);
      if (parsed) yield parsed;
      sep = buffer.indexOf("\n\n");
    }
  }
}

/**
 * Parse one SSE frame into a backend event.
 *
 * Only `data:` lines carry a payload; the terminal `event: done` frame has no
 * JSON and is ignored. Malformed frames are skipped rather than throwing, so one
 * bad frame cannot abort an otherwise healthy stream.
 */
function parseFrame(frame: string): AgentStreamEvent | null {
  const dataLine = frame
    .split("\n")
    .find((line) => line.startsWith("data:"));
  if (!dataLine) return null;

  const json = dataLine.slice("data:".length).trim();
  if (!json || json === "{}") return null;

  try {
    return JSON.parse(json) as AgentStreamEvent;
  } catch {
    return null;
  }
}
