/**
 * The "agent is working" indicator, shown the instant a turn starts and until
 * either its first reasoning step or its first reply text arrives.
 *
 * Menu reads and review analysis can take real seconds, so a visible, animated
 * sign of life matters here — without it, the pause reads as broken rather than
 * as the agent doing real work.
 */

export function TypingIndicator() {
  return (
    <span className="typing-indicator" role="status" aria-label="Agent is working">
      <span className="typing-indicator__dot" />
      <span className="typing-indicator__dot" />
      <span className="typing-indicator__dot" />
    </span>
  );
}
