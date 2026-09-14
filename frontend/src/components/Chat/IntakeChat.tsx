/**
 * The intake conversation: greeting, then a short 2-3 turn gather of
 * city + meal + dietary needs, ending in a confirmable SearchBrief.
 *
 * Language mirroring: the backend agent is responsible for detecting the
 * traveller's language and returning results in it (see `SearchBrief.output_language`
 * and README notes on language mirroring). This component only needs to avoid
 * baking English-only assumptions into *control flow* -- it never parses the
 * free-text fields for meaning, it just carries them through to the brief. Chip
 * labels here are the intake UI's own copy and stay in English until the
 * backend contract for localised chip labels exists.
 */

import { useMemo, useState } from "react";
import { Chip } from "./Chip";
import { ChatMessage } from "./ChatMessage";
import { COMMON_DIETS, COMMON_MEALS, type SearchBrief } from "../../types/models";

type IntakeStep = "city" | "meal" | "diet" | "confirm";

interface IntakeChatProps {
  onConfirm: (brief: SearchBrief) => void;
}

export function IntakeChat({ onConfirm }: IntakeChatProps) {
  const [step, setStep] = useState<IntakeStep>("city");

  const [city, setCity] = useState("");
  const [cityInput, setCityInput] = useState("");

  const [meal, setMeal] = useState("");
  const [mealInput, setMealInput] = useState("");

  const [diets, setDiets] = useState<string[]>([]);
  const [dietInput, setDietInput] = useState("");

  const canSubmitCity = cityInput.trim().length > 0;
  const canSubmitMeal = meal.trim().length > 0 || mealInput.trim().length > 0;

  const summary = useMemo<SearchBrief>(
    () => ({
      city: city.trim(),
      meal: (meal || mealInput).trim(),
      dietary_requirements: diets,
      area: null,
      cuisine_preferences: [],
      budget: null,
      group_size: null,
      output_language: "en",
    }),
    [city, meal, mealInput, diets],
  );

  function submitCity() {
    if (!canSubmitCity) return;
    setCity(cityInput.trim());
    setStep("meal");
  }

  function submitMeal(chosen?: string) {
    const value = chosen ?? mealInput.trim();
    if (!value) return;
    setMeal(value);
    setStep("diet");
  }

  function toggleDiet(label: string) {
    setDiets((prev) =>
      prev.includes(label) ? prev.filter((d) => d !== label) : [...prev, label],
    );
  }

  function addFreeformDiet() {
    const value = dietInput.trim();
    if (!value) return;
    setDiets((prev) => (prev.includes(value) ? prev : [...prev, value]));
    setDietInput("");
  }

  function proceedToConfirm() {
    setStep("confirm");
  }

  return (
    <div className="intake-chat">
      <ChatMessage from="agent">
        Hi! I can help you find somewhere to eat, wherever you are. Which city are you in?
      </ChatMessage>

      {(step !== "city" || city) && (
        <ChatMessage from="user">{city || cityInput}</ChatMessage>
      )}

      {step === "city" && (
        <form
          className="intake-input-row"
          onSubmit={(e) => {
            e.preventDefault();
            submitCity();
          }}
        >
          <input
            autoFocus
            className="intake-input"
            placeholder="e.g. Barcelona"
            value={cityInput}
            onChange={(e) => setCityInput(e.target.value)}
          />
          <button className="intake-submit" type="submit" disabled={!canSubmitCity}>
            Send
          </button>
        </form>
      )}

      {step !== "city" && (
        <>
          <ChatMessage from="agent">
            Got it, {city}. What meal are you after?
          </ChatMessage>

          {(step !== "meal" || meal) && <ChatMessage from="user">{meal || mealInput}</ChatMessage>}

          {step === "meal" && (
            <>
              <div className="chip-row">
                {COMMON_MEALS.map((label) => (
                  <Chip key={label} label={label} onClick={() => submitMeal(label)} />
                ))}
              </div>
              <form
                className="intake-input-row"
                onSubmit={(e) => {
                  e.preventDefault();
                  submitMeal();
                }}
              >
                <input
                  className="intake-input"
                  placeholder="or type your own, e.g. elevenses"
                  value={mealInput}
                  onChange={(e) => setMealInput(e.target.value)}
                />
                <button className="intake-submit" type="submit" disabled={!canSubmitMeal}>
                  Send
                </button>
              </form>
            </>
          )}
        </>
      )}

      {(step === "diet" || step === "confirm") && (
        <>
          <ChatMessage from="agent">
            Any dietary needs I should search for? Pick any that apply, or type your own. You
            can also skip this if there aren't any.
          </ChatMessage>

          {step === "confirm" && (
            <ChatMessage from="user">
              {diets.length > 0 ? diets.join(", ") : "No specific dietary needs"}
            </ChatMessage>
          )}

          {step === "diet" && (
            <>
              <div className="chip-row">
                {COMMON_DIETS.map((label) => (
                  <Chip
                    key={label}
                    label={label}
                    selected={diets.includes(label)}
                    onClick={() => toggleDiet(label)}
                  />
                ))}
              </div>
              <form
                className="intake-input-row"
                onSubmit={(e) => {
                  e.preventDefault();
                  addFreeformDiet();
                }}
              >
                <input
                  className="intake-input"
                  placeholder="or type your own, e.g. no shellfish"
                  value={dietInput}
                  onChange={(e) => setDietInput(e.target.value)}
                />
                <button className="intake-submit" type="submit" disabled={!dietInput.trim()}>
                  Add
                </button>
              </form>
              <button className="intake-continue" type="button" onClick={proceedToConfirm}>
                Continue
              </button>
            </>
          )}
        </>
      )}

      {step === "confirm" && (
        <ChatMessage from="agent">
          <div className="brief-confirm">
            <p>Here's what I've got. Shall I go ahead?</p>
            <dl className="brief-confirm__list">
              <dt>City</dt>
              <dd>{summary.city}</dd>
              <dt>Meal</dt>
              <dd>{summary.meal}</dd>
              <dt>Dietary needs</dt>
              <dd>{summary.dietary_requirements.length > 0 ? summary.dietary_requirements.join(", ") : "None specified"}</dd>
            </dl>
            <div className="brief-confirm__actions">
              <button
                type="button"
                className="intake-continue"
                onClick={() => setStep("diet")}
              >
                Edit
              </button>
              <button
                type="button"
                className="intake-submit"
                onClick={() => onConfirm(summary)}
              >
                Find me somewhere to eat
              </button>
            </div>
          </div>
        </ChatMessage>
      )}
    </div>
  );
}
