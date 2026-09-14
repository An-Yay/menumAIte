/**
 * The message input.
 *
 * Submits on Enter and grows with the text, so a longer message stays readable.
 * Disabled while the agent is working, which is a clearer signal than letting a
 * message be typed that cannot yet be sent.
 */

import { useEffect, useRef, useState } from "react";

interface ComposerProps {
  onSend: (message: string) => void;
  disabled?: boolean;
  placeholder?: string;
}

export function Composer({ onSend, disabled = false, placeholder }: ComposerProps) {
  const [value, setValue] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Grow the textarea to fit its content, up to a limit, so long messages are
  // visible without the box taking over the screen.
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [value]);

  // Return focus once the agent finishes, so a follow-up can be typed straight away.
  useEffect(() => {
    if (!disabled) textareaRef.current?.focus();
  }, [disabled]);

  function submit() {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue("");
  }

  return (
    <form
      className="composer"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <textarea
        ref={textareaRef}
        className="composer__input"
        rows={1}
        value={value}
        disabled={disabled}
        placeholder={placeholder ?? "Message menumAIte…"}
        aria-label="Message"
        onChange={(event) => setValue(event.target.value)}
        onKeyDown={(event) => {
          // Enter sends; Shift+Enter starts a new line.
          if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            submit();
          }
        }}
      />
      <button
        type="submit"
        className="composer__send"
        disabled={disabled || value.trim().length === 0}
        aria-label="Send message"
      >
        ↑
      </button>
    </form>
  );
}
