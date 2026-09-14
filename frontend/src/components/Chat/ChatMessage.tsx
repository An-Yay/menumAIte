import type { ReactNode } from "react";

interface ChatMessageProps {
  from: "agent" | "user";
  children: ReactNode;
}

/** A single chat bubble. Content is passed as children so callers can mix
 * plain text with chips or a confirmation card without this component
 * needing to know about them. */
export function ChatMessage({ from, children }: ChatMessageProps) {
  return (
    <div className={`chat-message chat-message--${from}`}>
      <div className="chat-message__bubble">{children}</div>
    </div>
  );
}
