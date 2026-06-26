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

## Running the whole stack

One command brings up the API, the mock vendor API, Prometheus and Grafana:

```bash
docker compose -f deploy/docker-compose.yml up --build
```

| Service | URL | Notes |
|---|---|---|
| API | http://localhost:8080 | `/health`, `/resolve`, `/resolve/stream`, `/metrics` |
| Mock vendor API | http://localhost:8081 | orders and products |
| Prometheus | http://localhost:9090 | scrapes `api:8080/metrics` every 15s |
| Grafana | http://localhost:3000 | `admin`/`admin`, DeskFleet dashboard already provisioned |

`deploy/smoke.sh` brings the stack up and asserts all of that automatically.

**`DATABASE_URL` is the one thing the stack cannot provide itself** — Neon is external. Put it in a
`.env` file next to `deploy/docker-compose.yml`, or export it before `up`. Without it the service
still runs; audit writes are logged and dropped.

Provider keys (`OPENAI_API_KEY`, `GROQ_API_KEY`) are passed through from the environment when set.
The UI can also supply a key per node at request time, so the stack starts fine with none.

### Metrics in production

Prometheus pulls, but Cloud Run with `--min-instances 0` sleeps when idle and its counters reset on
every cold start. The deployed service therefore pushes: set `GRAFANA_CLOUD_PROM_URL`,
`GRAFANA_CLOUD_PROM_USER` and `GRAFANA_CLOUD_PROM_KEY` and `deploy/prometheus-entrypoint.sh` appends
a `remote_write` block. With any of the three unset, the stack runs scrape-only.

The dashboard and its alert rules are committed under `deploy/grafana/` and `deploy/alerts.yml`;
`tests/unit/deploy/` cross-checks every panel query against the metrics the code actually emits.

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
