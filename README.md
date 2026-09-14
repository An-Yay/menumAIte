# menumAIte

An AI agent that helps a traveller find somewhere to eat in any city in the world.
Tell it the city, the meal, and what you avoid; it finds restaurants, reads and
translates their menus, weighs the reviews, and recommends dishes — showing its
working at every step.

It is built to be **transparent** (you see each step the agent takes) and
**honest** (it never invents a restaurant, a price, or a review; when something
cannot be found, it says so).

---

## What it does

Given a request like *"vegetarian dinner in Barcelona"* or *"I'm Jain, lunch in
Mumbai"*, the agent:

1. **Understands the diet.** For religious or complex diets (Jain, halal, kosher,
   allergies) it reasons out what to avoid and what to search for, and asks a
   clarifying question when the request is genuinely ambiguous.
2. **Discovers** candidate restaurants for the city, meal and diet.
3. **Shortlists** a few, and says why.
4. **Reads the menu** for each, translating it into your language, and attaching
   prices where the menu publishes them.
5. **Reads the reviews** — both the praise and the complaints — and pulls out
   anything relevant to your situation.
6. **Recommends** dishes, with links to each restaurant, its menu and its map
   listing.

Everything runs in **your language**: ask in German, get answered in German.

---

## Key features

- **Conversational.** A real multi-turn chat, not a form. Start vague, refine as
  you go ("somewhere cheaper", "read their menus", "what about halal?").
- **Language mirroring.** The agent replies in whatever language you write in, and
  translates foreign menus into it.
- **Menus from anywhere.** It reads menus from a restaurant's website (HTML and
  PDF), and when that fails, from a web search, and as a last resort by reading a
  menu photo from the map listing.
- **Prices only when real.** A price is shown only when it was actually published;
  otherwise the dish is clearly marked "price not listed". No guesses.
- **Balanced reviews.** Both positive and negative points are surfaced, plus
  review excerpts specific to your request (e.g. "good gluten-free options").
- **Visible reasoning.** An expandable panel shows each tool the agent called,
  live, so you can see how a recommendation was reached.
- **Dietary reasoning.** Jain, halal, kosher, allergies and combinations are
  handled by the model, not a fixed list, so unusual requests still work.

---

## How it works

```
Traveller ─▶ Chat UI (React) ─▶ Agent (Strands + OpenAI) ─▶ Tools
                    ▲                    │                     ├─ Google Places  (discovery, reviews, photos)
                    └──── SSE stream ────┘                     ├─ Menu crawler   (website HTML + PDF)
                        (reasoning + reply + cards)            ├─ Web search     (menu fallback)
                                                               └─ Vision OCR     (menu-photo fallback)
```

- **Backend:** Python, FastAPI, the Strands agent SDK, OpenAI (`gpt-4o-mini`).
- **Frontend:** React + TypeScript + Vite.
- The agent decides which tools to call; the backend streams its reasoning, reply
  and structured recommendation cards to the UI over Server-Sent Events.
- Recommendation cards are assembled **in code from the data the tools returned**,
  not re-transcribed by the model, so ratings, prices and links are always the
  real values.

### Data sources

| Need | Source |
| --- | --- |
| Restaurant discovery, ratings, reviews, photos | Google Places API (New) |
| Menus | The restaurant's own website (HTML/PDF), then web search, then a menu photo |
| Reasoning, translation, extraction, OCR | OpenAI |

---

## Running it locally

Two servers, both on your machine. No deployment, no database.

**Prerequisites:** Python 3.12, Node 18+, a Google Cloud API key with *Places API
(New)* enabled, and an OpenAI API key.

**Backend:**

```bash
cd backend
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp ../.env.example .env      # then fill in GOOGLE_API_KEY and OPENAI_API_KEY
.venv/bin/uvicorn app.main:app --reload --port 8000
```

**Frontend** (in a second terminal):

```bash
cd frontend
npm install
npm run dev                  # http://localhost:5173
```

Open <http://localhost:5173> and start a conversation.

---

## Known limitations

Stated plainly, because being honest about these is part of the design.

- **Reviews are a sample.** Google Places returns only ~5 reviews per restaurant,
  chosen by Google, out of what can be thousands. The summary reflects that
  sample, not the full listing, and the card says how many it is based on.
- **Menu coverage is not universal.** Many restaurants publish no menu online at
  all, or only as an image the OCR step cannot fully read. In those cases the
  agent says the menu was unavailable and links out, rather than guessing.
- **Prices are often missing.** A great many restaurants — especially outside
  delivery-heavy markets — simply do not publish prices. "Price not listed" is a
  common and honest outcome, not a bug.
- **Certification cannot be verified.** For halal, kosher or Jain, the agent
  reports what the menu and reviews say and advises confirming with the
  restaurant; it never asserts certification it cannot check.
- **The agent is autonomous.** It decides which steps to run, so occasionally it
  answers a narrow question narrowly (e.g. lists places without reading menus);
  a follow-up like "read their menus" gets the rest.
- **No persistence.** Conversations live in memory and are lost when the backend
  restarts. Fine for a local demo, not for production.
- **Menu photo OCR is best-effort.** It reads at most a few listing photos and
  stops at the first that is actually a menu; if none are, it reads nothing rather
  than inventing.
- **Expired-certificate sites.** To read menus from small restaurant sites with
  expired TLS certificates, the menu crawler retries those (and only those) with
  certificate verification relaxed. This is scoped to read-only public menu pages
  and sends no credentials.

---

## Repository layout

- `main` — this documentation
- `agent` — the backend agent (Python)
- `frontend` — the chat interface (React)
