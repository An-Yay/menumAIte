/**
 * The conversation view.
 *
 * A single scrolling thread with one input at the bottom, which is what the agent
 * is actually built for: it greets, asks what it still needs, and takes follow-up
 * questions, in the traveller's own language.
 *
 * Deliberately no scripted intake here. An earlier version walked through fixed
 * city/meal/diet steps with English prompts and then sent one request; that
 * duplicated what the agent does, forced English on the first turns, and threw the
 * conversation away after a single answer.
 *
 * The starter prompts on the empty screen are shortcuts, not a form. Anything typed
 * instead of clicking works just as well.
 */

import { useEffect, useRef } from "react";
import { Composer } from "./Composer";
import { TurnView } from "./TurnView";
import { useConversation } from "../../hooks/useConversation";

// Example openers, chosen to show the range: different cities, meals, diets, and
// languages, hinting that the agent replies in whatever language it is asked in.
const STARTERS = [
  "Vegetarian dinner in Barcelona",
  "Pure veg dinner places in Sydney",
  "I'm Jain, looking for lunch in Mumbai",
  "Gluten-free brunch in Lisbon",
];

export function Conversation() {
  const { turns, isBusy, send, reset } = useConversation();
  const bottomRef = useRef<HTMLDivElement>(null);

  // Follow the conversation as it grows, the way a chat is expected to behave.
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns]);

  const isEmpty = turns.length === 0;

  return (
    <div className="conversation">
      <div className="conversation__thread">
        {isEmpty ? (
          <div className="conversation__welcome">
            <h2>Where are you eating?</h2>
            <p>
              Tell me the city, the meal, and anything you avoid. I'll read the menus,
              check the reviews, and show you what I found. Any language works.
            </p>
            <div className="conversation__starters">
              {STARTERS.map((starter) => (
                <button
                  key={starter}
                  type="button"
                  className="starter"
                  onClick={() => void send(starter)}
                >
                  {starter}
                </button>
              ))}
            </div>
          </div>
        ) : (
          turns.map((turn) => <TurnView key={turn.id} turn={turn} />)
        )}
        <div ref={bottomRef} />
      </div>

      <div className="conversation__footer">
        <Composer
          onSend={(message) => void send(message)}
          disabled={isBusy}
          placeholder={
            isBusy ? "Working on it…" : isEmpty ? "e.g. vegetarian dinner in Barcelona" : "Ask a follow-up…"
          }
        />
        {!isEmpty && (
          <button
            type="button"
            className="conversation__reset"
            onClick={reset}
            disabled={isBusy}
          >
            Start over
          </button>
        )}
      </div>
    </div>
  );
}
