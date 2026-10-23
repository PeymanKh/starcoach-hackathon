# Starcoach Hackathon Challenge – Backend

The backend for Torob's AI shopping assistant that helps you buy in person in Tehran. You tell it what you want, and it finds the product, the stores nearby that sell it, where exactly they are inside the mall, whether they're open, and how much to trust the listed price.

- Live UI: https://chat.peymankh.dev
- API docs: https://api.peymankh.dev/api/docs/
- UI code: https://github.com/PeymanKh/starcoach-hackathon-ui

## How it works

An agent answer can take 20 to 60 seconds and several tool calls, so the agent never runs inside the HTTP request.

1. The UI sends a message. Django creates a run, puts it on a Celery queue and answers right away.
2. A Celery worker runs the agent (LangChain) and publishes every step as an event: thinking, tool start, tool end, text tokens.
3. Events go to a Redis Stream, one per run, and reach the browser over SSE. If the connection drops, the browser reconnects with `Last-Event-ID` and continues where it left off.
4. The conversation is saved in Postgres, so any chat can be reopened with all its cards.

The stack is Django, DRF, Celery, Redis, PostgreSQL (with `pg_trgm`) and LangChain, with models served through OpenRouter.

## Data

The dataset is too big for GitHub. See [data/README.md](data/README.md) for the download links.

- `data/raw/`: the 3 original CSV files (shops, products, offers).
- `data/data-preprocessing.ipynb`: the notebook that cleans them. Each step is explained inside.
- `data/clean/`: what the notebook produces, 8 Parquet files.

The main rule while cleaning was to not delete anything. Suspicious values are flagged, and unknown values stay unknown. For example, prices above 100 billion Toman are marked as too high. Two stores listed every product at 1 Toman, so those prices are treated as missing and you're told to ask the seller.

To run the notebook, install the data dependencies with `uv sync --group data`.

## Catalog

`apps/catalog` holds the database models for the cleaned data: products (with specs as JSON), shops, offers, the price of each product at each shop, working hours, payment options and shop categories.

To load the Parquet files into Postgres:

```bash
uv run python manage.py import_dataset data/clean
```

It replaces the catalog tables in one transaction, so if anything fails the old data stays. It loads with Postgres `COPY`, which is fast even for millions of rows. While importing, it also builds a normalized search text for every product, with Arabic and Persian letters and digits unified, which is what the trigram search uses.

## Agent tools

The tools are in `apps/agents/tools`. Each one queries Postgres directly and returns JSON with a `type`. The model gets the data, and the UI builds its cards from the same data, so prices and addresses never come from the model's own text.

| Tool | What it does |
|---|---|
| `explore_category` | Price bands, top brands and common specs of a category, for when the user isn't sure what they want |
| `search_products` | Persian or English search that tolerates typos, with category, brand and price filters |
| `get_product_details` | All specs of one product and its price range across stores |
| `compare_products` | 2 to 4 products side by side |
| `find_alternatives` | Similar or cheaper products, when the original is too expensive or has no seller |
| `find_stores` | Physical stores that sell a product, nearest first. Includes price and how old it is, opening status, installments, and floor and unit in the mall |
| `find_stores_by_category` | Stores for a whole category, when `find_stores` finds too few |
| `get_store_details` | Weekly hours, contact info and what a store sells |
| `compare_stores` | 2 to 5 stores for one product, marking which is cheapest, nearest, open now, or in the same mall |

## Agent features

- **Prompt in parts.** The system prompt is built from small markdown files in `apps/agents/prompts` (role, voice, workflow, tools, format, rules). On every run, the user's location and today's Jalali date are added to it.
- **Honest prices.** Every store price comes with its age (fresh, recent, old or very old), and the agent suggests calling when a price is old.
- **Long chats stay cheap.** Past about 30k tokens, older tool results are hidden from the model and only the last 4 stay in full. The saved chat is not changed.
- **Limits.** At most 8 tool calls per message, and rate limits on the API (10 runs and 60 transcriptions per minute per IP).
- **Fallback.** If the chosen model fails, a backup model finishes the answer. If a tool crashes, the error goes back to the model instead of killing the run.
- **Model choice.** The UI can choose between a few models and three reasoning levels. The list is in `apps/agents/llm.py`.
- **Voice input.** `/api/agent/transcribe/` turns Persian speech into text with Whisper (through OpenRouter).

## API

The full API docs, with every request and response, are at **https://api.peymankh.dev/api/docs/** (ReDoc). When you run the project locally, they're at http://localhost:8000/api/docs/. The raw OpenAPI schema is at `/api/schema/`.

| Endpoint | |
|---|---|
| `GET /api/agent/models/` | Available models and reasoning levels |
| `POST /api/agent/runs/` | Send a message, which starts a run |
| `GET /api/agent/runs/<id>/stream/` | The run's events (SSE) |
| `GET /api/agent/threads/` | Chat list |
| `GET /api/agent/threads/<id>/` | One chat with its messages and cards |
| `POST /api/agent/transcribe/` | Speech to text |
| `GET /health/` | Health check |

## Run locally

You need Python 3.12+, [uv](https://docs.astral.sh/uv/) and Docker.

```bash
uv sync
cp .env.example .env          # then put your OPENROUTER_API_KEY in .env
make up                       # Postgres and Redis in Docker
make migrate
uv run python manage.py import_dataset data/clean
make run                      # API on http://localhost:8000
make worker                   # in a second terminal: the agent worker
```

The API docs are now at http://localhost:8000/api/docs/.

Then run the UI repo, which talks to `localhost:8000` by default.

## Tests and checks

```bash
make test     # about 95 tests
make check    # lint, type check and tests, the same as CI
```

## Deploy

Every push to `main` runs CI. If it passes, GitHub Actions builds a Docker image and deploys it to a VPS with Docker Compose: Postgres, Redis, the Django API (gunicorn), the Celery worker and nginx. Migrations run automatically, and the deploy finishes with a health check. The production files are in `deploy/`, and the environment variables are listed in `.env.prod.example`.
