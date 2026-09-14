# menumAIte

An AI agent that recommends restaurants and dishes for a traveller in any city.
Given a city, a meal and any dietary needs, it discovers restaurants, reads and
translates their menus, analyses reviews, and recommends dishes. It streams its
reasoning to the interface so each step is visible, and it does not fabricate
restaurants, prices or reviews.

## Table of contents

- [What it does](#what-it-does)
- [Features](#features)
- [Architecture](#architecture)
  - [High-level flow](#high-level-flow)
  - [Backend](#backend)
  - [Frontend](#frontend)
  - [The agent and its tools](#the-agent-and-its-tools)
  - [How a menu is read](#how-a-menu-is-read)
  - [How the answer is built](#how-the-answer-is-built)
- [Running locally](#running-locally)
- [Project layout](#project-layout)
- [Technical decisions](#technical-decisions)
- [Known limitations](#known-limitations)
- [Open items](#open-items)

## What it does

Given a request such as "vegetarian dinner in Barcelona" or "halal lunch in
Amsterdam", the agent:

1. Interprets the diet. For religious or complex diets (Jain, halal, kosher,
   allergies) it derives what to avoid and what to search for, and asks a
   clarifying question when the request is genuinely ambiguous.
2. Discovers candidate restaurants for the city, meal and diet.
3. Shortlists a few and states the reasons.
4. Reads each menu from the website (HTML or PDF), a web search, or a menu photo,
   and translates it into the traveller's language, attaching prices where the
   menu publishes them.
5. Reads reviews, both positive and negative, and extracts points relevant to the
   traveller's situation.
6. Recommends dishes, with links to each restaurant, its menu and its map listing.

The conversation runs in the language the traveller writes in.

## Features

- Multi-turn conversation rather than a fixed form; the traveller can refine the
  request across turns.
- Language mirroring: replies in the traveller's language and translates foreign
  menus into it.
- Menus read from several sources: website HTML, PDF menus, a web-search fallback,
  and a menu photo from the map listing.
- Prices shown only when actually published; otherwise marked "price not listed".
- Positive and negative review points, plus review excerpts specific to the
  request.
- A live, expandable panel showing each tool the agent calls.
- Dietary reasoning performed by the model rather than a fixed ingredient table.

## Architecture

### High-level flow

```
 Traveller
    |  message (any language)
    v
+---------------------+     POST /api/chat      +------------------------------+
|  Chat UI (React)    | ----------------------> |  FastAPI backend             |
|  - conversation     |                         |  - session per conversation  |
|  - reasoning panel  | <----- SSE stream ----- |  - streams the agent's work  |
|  - result cards     |   observations,         |                              |
+---------------------+   text, suggestions     +--------------+---------------+
                                                                |
                                                                v
                                                   +----------------------------+
                                                   |  Strands agent (OpenAI)     |
                                                   |  decides which tool to call |
                                                   +------------+----------------+
                                                                |
        +-----------------------+-------------------+-----------+----------+
        v                       v                   v                      v
 resolve_dietary_profile  discover_restaurants   get_menu          get_restaurant_reviews
   (LLM reasoning)          (Google Places)     (crawl -> PDF ->    analyse_restaurant_reviews
                                                 search -> OCR)        (Places + LLM)
```

### Backend

- Python, FastAPI, served by Uvicorn.
- Agent SDK: [Strands](https://strandsagents.com), which runs the tool-using event
  loop and emits OpenTelemetry-style events.
- Model: OpenAI `gpt-4o-mini`, behind an `LLMProvider` interface so it can be
  swapped.
- Transport: Server-Sent Events. The traffic is server-to-client only and runs
  over plain HTTP, so SSE is a simpler fit than a WebSocket.
- Sessions: in memory, one agent per conversation, so history is isolated between
  conversations. No database.

Layout under `backend/app/`:

| Module | Responsibility |
| --- | --- |
| `main.py` | FastAPI app, CORS, health check |
| `config.py` | Settings and secrets loaded from the environment / `.env` |
| `models.py` | Pydantic domain and observability models |
| `api/chat.py` | The `/api/chat` SSE endpoint and session store |
| `api/events.py` | Translates Strands events into interface events |
| `agent/agent.py` | Builds the agent; assembles the final recommendations |
| `agent/prompt.py` | The agent's system prompt |
| `agent/tools.py` | The tools the agent can call |
| `providers/places.py` | Google Places (discovery, reviews, photos) |
| `providers/llm.py` | OpenAI provider + JSON helpers |
| `crawler/menu_crawler.py` | Fetches and reads menus (HTML + PDF) |
| `tools/dietary.py` | Dietary reasoning |
| `tools/menu_extract.py` | Turns menu text into structured, translated dishes |
| `tools/web_search.py` | Web-search menu fallback |
| `tools/menu_ocr.py` | Reads a menu from a photo |
| `tools/reviews.py` | Positive/negative + context-specific review analysis |

### Frontend

- React + TypeScript + Vite.
- Reads the SSE stream from a `fetch` response body (an `EventSource` cannot POST),
  parsing frames directly.
- `useConversation` holds the turn list and the session id, collecting the reply
  text, reasoning observations and result cards for each turn.

Key pieces under `frontend/src/`:

| Piece | Responsibility |
| --- | --- |
| `api/agentClient.ts` | SSE client; maps backend events to app events |
| `hooks/useConversation.ts` | Multi-turn conversation state |
| `components/Chat/Conversation.tsx` | The thread, composer and starter prompts |
| `components/Chat/TurnView.tsx` | One turn: reasoning, reply, cards |
| `components/Chat/AgentReply.tsx` | Renders the reply's light markdown safely |
| `components/ReasoningPanel/` | The expandable live reasoning tree |
| `components/Results/` | Restaurant cards, star ratings, menu rows |
| `types/models.ts` | TypeScript mirror of the backend models |

### The agent and its tools

The agent is autonomous: the model decides which tool to call next, guided by the
process in its system prompt. Five tools, each a thin adapter over an
independently testable component:

- `resolve_dietary_profile` — derives a diet into exclusions, clarifying questions
  and extra search terms.
- `discover_restaurants` — Google Places text search.
- `get_menu` — reads and structures one restaurant's menu (see below).
- `get_restaurant_reviews` — fetches reviews, only for shortlisted places, since
  review content is billed at a higher rate.
- `analyse_restaurant_reviews` — summarises praise and complaints and finds review
  excerpts relevant to the request.

### How a menu is read

`get_menu` tries sources in order of cost and reliability, stopping at the first
that yields a menu:

1. The restaurant's website: fetch the homepage, find the menu page, read it.
   Handles HTML and PDF menus.
2. A web search: when the site yields nothing, search for the menu elsewhere,
   including listing and delivery sites.
3. A menu photo: read a menu photo from the map listing with a vision model.
   Capped at a few photos, stopping at the first that is actually a menu. A photo
   of a dining room is classified as not-a-menu and yields nothing.

These are merged into one tool rather than separate fetch/extract/fallback tools
because the sequence contains no decision the model needs to make, and exposing it
as multiple tools led the model to run the first and skip the rest.

### How the answer is built

Result cards are assembled in code from the data the tools returned, not
re-transcribed by the model. The model's final step supplies only judgements: which
restaurants to feature, why, and which dish names to highlight. The backend joins
those to the cached restaurant, menu and review data.

Consequently ratings, prices and links always come from tool data, and a
restaurant id the model did not actually look up produces no card.

## Running locally

Two servers, both local. No deployment, no database.

**Prerequisites**

- Python 3.12
- Node 18+
- A Google Cloud API key with Places API (New) enabled
- An OpenAI API key with credit

**Backend**

```bash
cd backend
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp ../.env.example .env      # then fill in GOOGLE_API_KEY and OPENAI_API_KEY
.venv/bin/uvicorn app.main:app --reload --port 8000
```

- Health check: <http://localhost:8000/health>
- Interactive API docs: <http://localhost:8000/docs>

**Frontend** (second terminal)

```bash
cd frontend
npm install
npm run dev                  # http://localhost:5173
```

Open <http://localhost:5173>. The backend allows the Vite origin by default;
override with `CORS_ORIGINS` for a different port.

**API**

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/chat` | Send a message; streams the agent's work as SSE |
| `GET` | `/api/meta` | Quick-pick meal and diet options |
| `DELETE` | `/api/session/{id}` | End a conversation |
| `GET` | `/health` | Liveness and whether keys are configured |

`POST /api/chat` streams these event types: `session` (conversation id),
`observation` (reasoning-tree node), `text` (incremental reply), `suggestions`
(result cards), `final` (complete reply), `error`.

## Project layout

```
menumAIte/
├── backend/          Python agent + FastAPI API
│   └── app/          (see the backend table above)
├── frontend/         React + TypeScript chat UI
│   └── src/          (see the frontend table above)
├── .env.example      Template for the two API keys
└── README.md
```

Branches: `main` holds the full project; `agent` and `frontend` are the
development branches for the two halves.

## Technical decisions

- **Menu data source.** No public API returns priced restaurant menus reliably
  worldwide. Menus are therefore read from live sources (website, web search,
  photo) with fallbacks, and prices are treated as best-effort.
- **Places provider: Google Places (New) over Foursquare.** Foursquare's Places
  API was evaluated first. Its current credit-based free tier is exhausted after a
  few calls, richer fields such as `menu` are gated behind premium/credits, and
  the `menu` field it exposes is a link rather than menu content. Google Places
  (New) returned websites and reviews reliably on the free trial and covers the
  same discovery need, so it was chosen. The provider sits behind a `PlacesProvider`
  interface, so another source can replace it.
- **LLM provider: OpenAI behind an interface.** Gemini was attempted first (the
  same Google project), but its access required either enabling a separate billing
  path or a service-account-bound key. OpenAI was simpler to wire and is accessed
  through an `LLMProvider` interface, so it can be swapped.
- **Reasoning in the model, facts in code.** Dietary rules and currency are
  reasoned by the model rather than encoded in tables. Ratings, prices and links
  shown to the user come from tool data, not the model's retelling.
- **Tool-level guarantees over prompt wording.** Where a prompt instruction proved
  unreliable (skipping steps, presenting review-mentioned dishes as a menu),
  the constraint was moved into the tools or the assembly code.
- **Single `get_menu` tool.** Fetching, extracting and the fallbacks are one tool,
  because the sequence has no branch the model needs to decide.
- **SSE, in-memory sessions.** Chosen for a local, single-user demo; both are
  called out under limitations for a production path.

## Known limitations

- **Reviews are a sample.** Google Places returns about five reviews per
  restaurant, selected by Google, out of a total that may run to thousands.
  Summaries reflect that sample, and the card states the count.
- **Foursquare was not usable as a menu source.** Even with credits, its `menu`
  field is a link rather than structured menu content, so it would not have solved
  the core menu problem.
- **Menu coverage is not universal.** Some restaurants publish no menu online, or
  only an image the OCR step cannot fully read. These are reported as unavailable
  with a link.
- **Certification cannot be verified.** For halal, kosher or Jain, the agent
  reports what the menu and reviews say and advises confirming with the
  restaurant; it does not assert certification.
- **The agent is autonomous.** It may answer a narrow question narrowly; a
  follow-up such as "read their menus" retrieves the rest.
- **No persistence.** Conversations are held in memory and lost on restart.
- **Menu-photo OCR is best-effort.** It reads a few listing photos, stopping at the
  first that is a menu; if none are, it returns nothing.
- **Expired-certificate sites.** To read menus from restaurant sites with expired
  TLS certificates, the crawler retries those (and only those) with certificate
  verification disabled. This is limited to read-only public menu pages and sends
  no credentials.
- **Latency.** A full run reads several menus and analyses several review sets, so
  a complete answer can take tens of seconds.

## Open items

Work that is scoped but not implemented:

- **"Pure vegetarian" venue signal.** Distinguish a fully vegetarian/vegan venue
  from a mixed restaurant with vegetarian options, using the Google Places
  category, and surface it as a badge and a shortlisting preference.
- **Deterministic step ordering (optional).** An explicit orchestration mode that
  guarantees discover → menu → reviews runs every time, as an alternative to the
  autonomous loop.
- **Menu and review caching across sessions.** Currently per-process; a shared
  cache with expiry would cut repeat cost and latency.
- **Persistence.** A datastore for conversations and cached results to survive
  restarts.
- **Broader OCR.** Rank listing photos so a menu photo is tried first, and support
  multi-page menu photos.
- **Structured-output reliability.** The final pick step occasionally omits a
  restaurant; a retry or a stricter schema would tighten it.
- **Automated tests.** Unit tests for the crawler, price detection, dietary
  reasoning and event translation; a small end-to-end test behind a mock provider.
- **Cost controls.** Configurable caps on shortlist size, photos read and menu
  length, exposed as settings.
