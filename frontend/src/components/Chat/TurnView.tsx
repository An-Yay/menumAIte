/**
 * Renders one turn of the conversation.
 *
 * An assistant turn can carry three things, and they are shown in the order the
 * traveller needs them: what the agent did (collapsed by default, so it informs
 * without shouting), the reply itself, and the restaurant cards.
 *
 * Keeping these together per turn, rather than in separate panels, means the
 * working stays attached to the answer it produced — which is the point of showing
 * it at all.
 */

import { AgentReply } from "./AgentReply";
import { ChatMessage } from "./ChatMessage";
import { TypingIndicator } from "./TypingIndicator";
import { ReasoningPanel } from "../ReasoningPanel/ReasoningPanel";
import { ResultsList } from "../Results/ResultsList";
import type { Turn } from "../../hooks/useConversation";

interface TurnViewProps {
  turn: Turn;
}

export function TurnView({ turn }: TurnViewProps) {
  if (turn.role === "user") {
    return <ChatMessage from="user">{turn.text}</ChatMessage>;
  }

  const hasReasoning = turn.observationOrder.length > 0;
  const hasReply = turn.text.length > 0;
  // Nothing to show yet: the request has been sent but no event has arrived.
  const isWaiting = turn.isStreaming && !hasReasoning && !hasReply;

  return (
    <div className="turn">
      {isWaiting && (
        <ChatMessage from="agent">
          <TypingIndicator />
        </ChatMessage>
      )}

      {hasReasoning && (
        <ReasoningPanel
          observations={turn.observations}
          order={turn.observationOrder}
          isRunning={turn.isStreaming}
        />
      )}

      {/* Once reasoning is visible but the reply has not started, the typing
          indicator moves here so the traveller keeps seeing that work continues
          between tool calls. */}
      {turn.isStreaming && hasReasoning && !hasReply && (
        <ChatMessage from="agent">
          <TypingIndicator />
        </ChatMessage>
      )}

      {turn.text && (
        <ChatMessage from="agent">
          <AgentReply text={turn.text} />
        </ChatMessage>
      )}

      {turn.error && (
        <ChatMessage from="agent">
          <p className="turn__error">{turn.error}</p>
        </ChatMessage>
      )}

      {turn.suggestions && turn.suggestions.length > 0 && (
        <ResultsList suggestions={turn.suggestions} />
      )}
    </div>
  );
}
