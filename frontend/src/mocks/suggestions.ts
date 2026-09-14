/**
 * Mock final results payload, matching `Suggestion` from backend/app/models.py.
 *
 * Deliberately includes a mix of: an item with a real price, an item with
 * `price_available: false` (never invented), and reviews with both positive
 * and negative points plus context-specific matches, so the results UI has
 * to handle the full contract rather than a happy-path subset.
 */

import type { SearchBrief, Suggestion } from "../types/models";

export function buildMockSuggestions(brief: SearchBrief): Suggestion[] {
  const diet = brief.dietary_requirements[0] ?? "your dietary needs";

  return [
    {
      restaurant: {
        place_id: "mock-place-1",
        name: "Café Verde",
        rating: 4.6,
        rating_count: 812,
        price_level: "PRICE_LEVEL_MODERATE",
        address: `12 Rambla Street, ${brief.city}`,
        website_url: "https://example.com/cafe-verde",
        maps_url: "https://maps.google.com/?cid=mock-place-1",
        primary_type: "Vegetarian Restaurant",
      },
      reasoning:
        `Highly rated, a short walk from the ${brief.area ?? "city centre"}, and its menu is ` +
        `explicitly built around ${diet} options rather than offering a single token dish.`,
      recommended_items: [
        {
          name: "Grilled vegetable & halloumi plate",
          original_name: "Plato de verduras a la parrilla con halloumi",
          description: "Seasonal vegetables, halloumi, romesco sauce.",
          price_amount: 12.5,
          price_currency: "EUR",
          price_available: true,
          dietary_tags: ["vegetarian", "gluten-free"],
          matches_requirements: true,
        },
        {
          name: "Chef's tasting menu",
          original_name: "Menú degustación",
          description: "A rotating multi-course menu; not priced on the website.",
          price_amount: null,
          price_currency: null,
          price_available: false,
          dietary_tags: ["vegetarian"],
          matches_requirements: true,
        },
      ],
      review_insight: {
        restaurant_place_id: "mock-place-1",
        positive_points: [
          "Consistently praised for fresh, seasonal produce.",
          "Staff described as attentive and quick to explain dishes.",
        ],
        negative_points: [
          "A few reviews mention long waits on weekend evenings.",
        ],
        context_matches: [
          `"Finally a place where the vegetarian menu isn't an afterthought" (5★)`,
          `"They clearly labelled every ${diet} dish, which made ordering easy" (4★)`,
        ],
        reviews_considered: 24,
      },
      menu_url: "https://example.com/cafe-verde/menu",
      caveats: [
        "The tasting menu price is not published online; confirm with the restaurant.",
      ],
    },
    {
      restaurant: {
        place_id: "mock-place-2",
        name: "Bar Costanera",
        rating: 4.3,
        rating_count: 1284,
        price_level: "PRICE_LEVEL_INEXPENSIVE",
        address: `48 Port Avenue, ${brief.city}`,
        website_url: "https://example.com/bar-costanera",
        maps_url: "https://maps.google.com/?cid=mock-place-2",
        primary_type: "Tapas Restaurant",
      },
      reasoning:
        `Not a dedicated ${diet} spot, but reviews confirm the kitchen accommodates it well, ` +
        `and it fits the ${brief.meal} timing and budget from the brief.`,
      recommended_items: [
        {
          name: "Marinated olives & bread",
          original_name: "Aceitunas marinadas con pan",
          description: null,
          price_amount: 4.0,
          price_currency: "EUR",
          price_available: true,
          dietary_tags: ["vegetarian", "vegan"],
          matches_requirements: true,
        },
      ],
      review_insight: {
        restaurant_place_id: "mock-place-2",
        positive_points: [
          "Praised for lively atmosphere and quick service at the bar.",
        ],
        negative_points: [
          "Some reviewers note the menu skews heavily toward meat and seafood.",
          "A couple of reviews mention it can get noisy during peak hours.",
        ],
        context_matches: [
          `"Asked about vegetarian options and the waiter pointed out several dishes without hesitation" (4★)`,
        ],
        reviews_considered: 31,
      },
      menu_url: "https://example.com/bar-costanera/menu",
      caveats: [
        "Menu is smaller for this diet than at Café Verde; better as a secondary option.",
      ],
    },
  ];
}
