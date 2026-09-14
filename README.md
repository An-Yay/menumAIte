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
- **Reasoning, translation, review analysis:** OpenAI (via the `LLMProvider` abstraction)

## Running locally

Everything runs on your machine; there is no deployment step. The backend and the
interface run as two separate development servers.

### Backend

```bash
cd backend
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp ../.env.example .env      # then fill in your keys
.venv/bin/uvicorn app.main:app --reload --port 8000
```

- Health check: <http://localhost:8000/health>
- Interactive API docs: <http://localhost:8000/docs>

### Frontend

```bash
cd frontend
npm install
npm run dev                  # http://localhost:5173
```

The backend permits cross-origin requests from `http://localhost:5173` by default;
override with the `CORS_ORIGINS` environment variable if you use another port.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/chat` | Send a message; streams the agent's work as Server-Sent Events. |
| `GET` | `/api/meta` | Suggested meal and dietary options for quick-pick chips. |
| `DELETE` | `/api/session/{id}` | Discard a conversation. |
| `GET` | `/health` | Liveness, and whether keys are configured. |

`POST /api/chat` streams these event types:

- `session` — the conversation id to reuse for follow-up messages
- `observation` — a node in the reasoning tree (steps, tool calls, timings)
- `text` — an incremental chunk of the reply
- `final` — the complete reply
- `error` — a failure, reported without discarding partial results

## Status

Backend agent working end to end on the `agent` branch: discovery, menu crawling,
translation, review analysis, and a streaming chat API. Interface in progress on
the `frontend` branch.
