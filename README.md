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

Or run all three together — mock API, API and the Streamlit UI — with the built-in dev launcher.
Output is prefixed per service, and the first process to exit stops the other two:

```bash
uv run deskfleet-dev
```

| Service | URL |
|---|---|
| API | http://localhost:8080 |
| Mock vendor API | http://localhost:8081 |
| Streamlit UI | http://localhost:8501 |

**Leaving `API_KEY` unset makes the service unguarded** — every request is accepted and billed to
the server's `OPENAI_API_KEY`. That is the intended local default, and the API logs
`api_key_unset_service_is_unguarded` at startup to say so. Set `API_KEY` to require the
`X-API-Key` header, which is what the UI's "Service key" field fills in.

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

## Deployment

The GitHub Actions workflow lives in [`.github/workflows/deploy.yml`](.github/workflows/deploy.yml).
It runs:

1. `uv sync --frozen --dev`
2. `ruff check` and `ruff format --check`
3. `pytest tests/unit tests/safety tests/prompts`
4. `docker build` and `docker push` for both service images
5. a new Secret Manager version for every configured secret
6. `gcloud run deploy` for the mock API first, then the main API
7. `GET /health` and an unauthenticated `POST /resolve` against the deployed URL, asserting 200
   and 401

Steps 4–7 only run on `main` or `workflow_dispatch`, and only after step 3 passes — a failing
safety test stops the pipeline before any image is built.

Before using it, create:

1. A GCP project with billing enabled.
2. An Artifact Registry Docker repository.
3. A service account for the workflow with `roles/run.admin`, `roles/artifactregistry.writer`,
   `roles/iam.serviceAccountUser`, `roles/secretmanager.secretVersionAdder` (to publish new secret
   versions) and `roles/secretmanager.secretAccessor` (which Cloud Run needs at runtime, since the
   same account is the service identity). No `roles/editor`, no `roles/owner`, and deliberately not
   `roles/secretmanager.admin` — the workflow adds versions but never creates or deletes secrets.
4. A GitHub Workload Identity Federation provider that can impersonate that service account.
5. One Secret Manager secret per runtime value, created once. The workflow fails with the exact
   command if one is missing:

   ```bash
   for name in DATABASE_URL OPENAI_API_KEY API_KEY LANGCHAIN_API_KEY GROQ_API_KEY \
               GRAFANA_CLOUD_PROM_URL GRAFANA_CLOUD_PROM_USER GRAFANA_CLOUD_PROM_KEY; do
     gcloud secrets create "$name" --project "$GCP_PROJECT_ID" --replication-policy automatic
   done
   ```

Required GitHub secrets:

1. `GCP_PROJECT_ID`
2. `GCP_REGION`
3. `GCP_ARTIFACT_REGISTRY_REPOSITORY`
4. `GCP_WORKLOAD_IDENTITY_PROVIDER`
5. `GCP_SERVICE_ACCOUNT_EMAIL`
6. `DATABASE_URL`
7. `OPENAI_API_KEY`
8. `LANGCHAIN_API_KEY`
9. `API_KEY`
10. `GROQ_API_KEY`
11. `GRAFANA_CLOUD_PROM_URL`
12. `GRAFANA_CLOUD_PROM_USER`
13. `GRAFANA_CLOUD_PROM_KEY`

Secrets 6–13 are never passed to Cloud Run with `--set-env-vars`, which would write them in clear
into the revision spec for anyone holding `run.viewer`. The workflow pipes each value into
`gcloud secrets versions add --data-file=-` — so no secret reaches a command line or a log — and the
service reads them through `--set-secrets NAME=NAME:latest`. Non-secret configuration still goes
through `--set-env-vars`, using gcloud's `^@^` delimiter so a comma inside a value cannot be read as
the start of the next variable.

The workflow deploys the mock API first, captures its URL, and then deploys the main service with
`ORDER_API_BASE_URL` and `PRODUCT_API_BASE_URL` pointed at that mock URL. The Cloud Run flags are:

- `--min-instances 0`
- `--memory 512Mi` for the mock API
- `--memory 1Gi` for the main API
- `--timeout 300`
- `--allow-unauthenticated`
- `--port 8081` for the mock API
- `--port 8080` for the main API

## Tests

```bash
uv run pytest
```

Unit, safety and prompt tests run everywhere and need no keys. Tests marked `integration` hit real
providers and are deselected by default.
