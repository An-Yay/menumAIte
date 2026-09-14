# menumAIte

An AI agent that recommends restaurants and vegetarian-friendly meal options for
travellers in any city worldwide. Given a traveller's city, meal (breakfast /
lunch / dinner) and dietary preferences, the agent:

1. **Discovers** candidate restaurants for the location, meal and diet.
2. **Shortlists** them with explicit, visible criteria.
3. **Reads** each shortlisted restaurant's menu from its website.
4. **Translates** the menu into the traveller's language.
5. **Analyses reviews** — both positive and negative — and searches for reviews
   relevant to the traveller's specific context (e.g. vegetarian, gluten-free).
6. **Shows** menu items and their prices (when the restaurant publishes them),
   and clearly states when a price is not available.
7. **Suggests** options, with web links to each restaurant and its menu page.

The agent is designed to *show its work* at every step, so the traveller can see
how each recommendation was reached.

## Branches

- `main` — project documentation and shared configuration
- `agent` — backend AI agent (Python)
- `frontend` — chat user interface (React)

## Data sources

- **Discovery & reviews:** Google Places API (New)
- **Menus:** live crawl of each restaurant's website + LLM extraction/translation
- **Reasoning, translation, review analysis:** LLM (provider to be finalised)

## Status

Early development. Backend agent in progress on the `agent` branch.
