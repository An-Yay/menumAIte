import { RestaurantCard } from "./RestaurantCard";
import type { Suggestion } from "../../types/models";

interface ResultsListProps {
  suggestions: Suggestion[];
}

export function ResultsList({ suggestions }: ResultsListProps) {
  if (suggestions.length === 0) {
    return <p className="results-empty">No matching restaurants found for this brief.</p>;
  }

  return (
    <div className="results-list">
      {suggestions.map((suggestion) => (
        <RestaurantCard key={suggestion.restaurant.place_id} suggestion={suggestion} />
      ))}
    </div>
  );
}
