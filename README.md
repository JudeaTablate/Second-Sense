# Second Sense

**Continuous behavioral authentication and account-takeover fraud detection API.**

Second Sense watches how a user types and moves their mouse, builds a rolling
statistical baseline of their normal behavior using an EWMA-based
anomaly scoring engine, and flags sessions that deviate — a lightweight
version of the "continuous authentication" systems used by banks and
fintechs to catch account takeover in real time, without needing extra
MFA prompts.

The core scoring math (EWMA baseline updates, Mahalanobis distance,
covariance shrinkage) is adapted from independent undergraduate thesis
research applying the same statistical techniques to clinical
psychomotor disturbance detection.

---

## Architecture

```
frontend (vanilla JS) --> backend (FastAPI)
                              |-- Postgres  (users, baselines, audit log, incidents)
                              |-- Redis     (hot baseline cache)
                              |-- Twilio / SendGrid (fraud alerts)
                              |-- IP enrichment API (geo/risk context)
```

The backend is one FastAPI app internally organized into clear modules
(ingestion, scoring, alerting) — structured so any of them could be
split into its own deployed service later without touching the core
scoring logic. See `backend/app/`.

---

## Project structure

```
second-sense/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI app entrypoint
│   │   ├── config.py          # env-based settings
│   │   ├── database.py        # SQLAlchemy engine/session
│   │   ├── models.py          # User, BehaviorBaseline, SessionScore, Incident
│   │   ├── schemas.py         # Pydantic request/response models
│   │   ├── auth_utils.py      # password hashing, JWT
│   │   ├── scoring/
│   │   │   ├── ewma.py        # core EWMA + Mahalanobis anomaly engine
│   │   │   └── features.py    # raw events -> feature vector
│   │   ├── services/
│   │   │   ├── redis_client.py
│   │   │   ├── alerting.py    # Twilio/SendGrid/webhook, retries via tenacity
│   │   │   └── enrichment.py  # IP/geo risk API integration
│   │   └── routers/
│   │       ├── auth.py
│   │       ├── scoring.py     # POST /sessions/ingest — the core pipeline
│   │       └── incidents.py
│   ├── scripts/init_db.py     # creates tables (run before app start)
│   ├── tests/                 # pytest unit + integration tests
│   ├── requirements.txt
│   ├── Dockerfile
│   └── fly.toml               # Fly.io deploy config
├── frontend/
│   ├── index.html
│   ├── style.css
│   └── app.js                 # captures keystroke/mouse events, live risk gauge
├── docker-compose.yml
└── .github/workflows/ci-cd.yml
```

---

## Run it locally (Docker — recommended, 3 commands)

You need Docker Desktop (or Docker Engine + Compose) installed.

```bash
git clone <your-repo-url> secondsense
cd secondsense
docker compose up --build
```

That single command builds the backend image, starts Postgres, Redis,
the API, and a static file server for the frontend. Give it ~30
seconds on first run.

- API: http://localhost:8000 (interactive docs at http://localhost:8000/docs)
- Frontend demo: http://localhost:5500
- Health check: http://localhost:8000/health

Open the frontend, sign up with any email, then start typing in the
text box. Every ~4 seconds it sends your keystroke/mouse events to the
API and updates the risk gauge. The first several batches will read
near-zero risk automatically (cold start — not enough baseline yet).
Once you've typed a few paragraphs normally, try typing very
differently (slower, pasting text, moving the mouse erratically) and
watch the score climb.

To stop: `docker compose down` (add `-v` to also wipe the database volume).

---

## Run it without Docker (local Python + your own Postgres/Redis)

```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

# point these at your own local Postgres/Redis, or run them via:
#   docker run -d -p 5432:5432 -e POSTGRES_USER=secondsense -e POSTGRES_PASSWORD=secondsense -e POSTGRES_DB=secondsense postgres:16-alpine
#   docker run -d -p 6379:6379 redis:7-alpine
export DATABASE_URL=postgresql://secondsense:secondsense@localhost:5432/secondsense
export REDIS_URL=redis://localhost:6379/0
export JWT_SECRET=dev-secret-change-me

python scripts/init_db.py
uvicorn app.main:app --reload
```

Then serve the frontend separately:
```bash
cd frontend
python -m http.server 5500
```

---

## Running the tests

```bash
cd backend
pip install -r requirements.txt
pytest tests/ -v --cov=app --cov-report=term-missing
```

Tests run against an in-memory SQLite database and a fake Redis
(`fakeredis`), so they need no external services and run in a couple
of seconds — this is exactly what CI runs.

Test coverage as of this scaffold: **20 tests, 85% coverage**, split
between:
- `tests/test_scoring.py` — pure unit tests on the EWMA anomaly engine
  and feature extraction (no framework, no DB — the fastest and most
  important tests in the suite)
- `tests/test_api.py` — integration tests hitting the actual FastAPI
  endpoints end to end (signup, login, ingest, scoring, incidents)

---

## Configuration (environment variables)

All optional except the DB/Redis URLs — everything else has a sane
default or runs in "mocked" mode if unset.

| Variable | Purpose | Default |
|---|---|---|
| `DATABASE_URL` | Postgres connection string | `postgresql://secondsense:secondsense@localhost:5432/secondsense` |
| `REDIS_URL` | Redis connection string | `redis://localhost:6379/0` |
| `JWT_SECRET` | Secret for signing auth tokens | `dev-secret-change-me` (**change in production**) |
| `EWMA_LAMBDA` | How fast the behavioral baseline adapts (0-1) | `0.2` |
| `RISK_ALERT_THRESHOLD` | Score (0-100) above which an incident fires | `70.0` |
| `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` / `TWILIO_FROM_NUMBER` / `ALERT_SMS_TO` | SMS alerting | unset = mocked (logs instead of sending) |
| `SENDGRID_API_KEY` / `ALERT_EMAIL_FROM` / `ALERT_EMAIL_TO` | Email alerting | unset = mocked |
| `IP_ENRICHMENT_API_URL` | IP/geo risk API base URL | `https://ipapi.co` (free tier, no key needed at low volume) |
| `CORS_ORIGINS` | Comma-separated allowed frontend origins | `http://localhost:5500` |

---

## CI/CD pipeline

`.github/workflows/ci-cd.yml` runs on every push/PR to `main`:

1. **Lint** — `ruff check`
2. **Test** — `pytest` with a coverage gate (fails the build if coverage drops below 70%)
3. **Build & push** — builds the Docker image and pushes to GitHub
   Container Registry (`ghcr.io`), tagged with both `latest` and the
   commit SHA
4. **Deploy** — deploys to either Fly.io or AWS ECS Fargate, gated
   behind a `DEPLOY_TARGET` repo variable so it's a no-op until you
   configure one

### To enable deployment

**Fly.io (fastest — free tier, ~10 min to a live URL):**
1. `flyctl auth login`, then `cd backend && flyctl launch` (don't deploy yet, just create the app — it'll detect `fly.toml`)
2. Attach Postgres/Redis: `flyctl postgres create` and `flyctl redis create`, then set the resulting URLs as Fly secrets: `flyctl secrets set DATABASE_URL=... REDIS_URL=... JWT_SECRET=...`
3. In your GitHub repo: Settings → Secrets → add `FLY_API_TOKEN` (from `flyctl auth token`)
4. Settings → Variables → add `DEPLOY_TARGET` = `flyio`
5. Push to `main` — the pipeline builds, tests, and deploys automatically

**AWS ECS Fargate (more resume-recognizable, more setup):**
1. Create an ECR-backed ECS cluster/service named `secondsense-cluster` / `secondsense-backend` (console, CLI, or Terraform)
2. Add repo secrets `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`
3. Add repo variables `DEPLOY_TARGET=aws`, `AWS_REGION=<your-region>`
4. Push to `main`

---

## What to say about this project in interviews

- **Why EWMA over a static threshold?** It weights recent behavior
  more heavily, so it adapts to gradual legitimate drift (fatigue, a
  new keyboard) without being blind to sudden anomalies.
- **Why split ingestion/scoring/alerting into separate modules?**
  They have different scaling profiles — alerting is I/O-bound and
  talks to flaky third-party APIs, scoring is CPU-bound numpy work.
  Structured so either could become its own deployed service under load.
- **What happens if Twilio is down?** `alerting.py` wraps every
  provider call in `tenacity` retry with exponential backoff, and
  each provider fails independently — one down provider never blocks
  the others or the request itself.
- **How would this scale to more users?** Redis absorbs the hot-path
  reads/writes so Postgres only sees periodic durability writes;
  horizontal scaling on the API layer is stateless since baseline
  state lives in Redis/Postgres, not in-process.

---

## Roadmap / good next additions

- Alembic migrations instead of `create_all`
- Rate limiting on `/sessions/ingest`
- A small admin dashboard for reviewing flagged incidents (the
  `/incidents` endpoint already exists — just needs a UI)
- Locust load test script + documented results in this README
- Terraform for the AWS path, so infra is versioned too
