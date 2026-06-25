# DeskFleet

A multi-agent customer-support triage service. A LangGraph `StateGraph` of four nodes —
Classifier → Researcher → Responder → Reviewer — resolves a support ticket against an order/product
API and returns one of three decisions: `RESOLVED`, `ESCALATE` or `REFUSE`.

## Running locally

```bash
uv sync
cp .env.example .env      # then fill in the keys
uv run uvicorn deskfleet.api.app:app --reload --port 8080
uv run uvicorn mock_api.app:app --port 8081
```

## Database

Persistence is Neon serverless Postgres, accessed with raw SQL over `psycopg` — no ORM.

1. Create a free project at [neon.tech](https://neon.tech).
2. Copy the connection string into `DATABASE_URL` in `.env` (keep `?sslmode=require`).
3. The schema is applied on startup by `store.migrate()`, which is idempotent and never drops.

**Free-tier compute sleeps.** After a few minutes of inactivity Neon suspends the instance, so the
first query after idle pays a wake-up of a second or two. That is immaterial next to the LLM path,
but it is why connections are short-lived and opened per write rather than pooled in-process.

If `DATABASE_URL` is unset the service still runs — writes log an error and are dropped. A lost
audit row is better than a lost reply to a customer.

## Ephemerality caveats

Cloud Run's filesystem is in-memory and per-instance, and the service deploys with
`--min-instances 0`. Nothing written to disk survives a scale-down, which is why the durable record
lives in Postgres rather than SQLite, and why Prometheus metrics are pushed rather than scraped in
production.

## Tests

```bash
uv run pytest
```

Unit, safety and prompt tests run everywhere and need no keys. Tests marked `integration` hit real
providers and are deselected by default.
