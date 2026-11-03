# Bull AI Voice Calling Platform

Enterprise AI outbound calling platform for Bull Machines. Departments upload contacts, run calling campaigns with
configurable AI scripts, and receive structured results from each call. First use case: SCM supplier delivery
confirmation.

The design, decisions and roadmap are in [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md).

## Status

| Phase | Scope | State |
|---|---|---|
| 1. Foundation | Database (all 22 tables, Alembic), JWT auth, users, departments, RBAC with department isolation, contacts, consent, do-not-call, audit log, health checks, Docker | Done |
| 2. Campaigns and scripts | Excel/CSV upload with column mapping, script builder with versions and approval, campaigns with approval, SCM script, encrypted file storage, React UI | Done: 93 backend + 10 frontend tests, browser walkthrough |
| 3. Real-time voice POC | FreJun Teler + Gemini Live, single real call | Next |
| 3. Real-time voice POC | Telephony adapter, voice gateway, single real call | Not started |

No calling features exist yet. Nothing in this repository places phone calls.

## Layout

```
backend/
  app/
    core/        settings, logging, errors, security (JWT, Argon2, Fernet), phone numbers, Redis
    db/          SQLAlchemy base and async session
    models/      ORM models, one module per area
    schemas/     Pydantic request/response models
    services/    business logic (no HTTP), including the audit trail
    rbac/        role permissions and department scoping
    api/v1/      REST routers
    main.py      FastAPI app served on port 8083
    seeds/       ready-made scripts (SCM supplier delivery confirmation)
    cli.py       create the first admin and departments, load seed scripts
  alembic/       migrations
  tests/         unit and integration tests (real PostgreSQL and Redis)
frontend/        React + TypeScript + Tailwind (Vite); built into the app image and served at /
deploy/
  docker-compose.yml       postgres, redis, migrate, app (port 8083)
  docker-compose.dev.yml   publishes postgres and redis on localhost for development
docs/
.env.example
```

## Development setup

Needs Python 3.14, [uv](https://docs.astral.sh/uv/), Docker.

```bash
cp .env.example .env          # fill in the secrets; generation commands are in the file
docker compose -f deploy/docker-compose.yml -f deploy/docker-compose.dev.yml --env-file .env up -d postgres redis

cd backend
uv sync
uv run alembic upgrade head
uv run python -m app.cli create-department --code SCM --name "Supply Chain Management"
uv run python -m app.cli create-admin --email you@bullmachine.com --name "Your Name"   # prompts for password
uv run python -m app.cli seed-scm-script --department SCM   # draft; submit and approve it in the app
uv run uvicorn app.main:app --port 8083 --reload
```

API documentation: http://127.0.0.1:8083/api/v1/docs

Frontend (needs Node 22), in a second terminal:

```bash
cd frontend
npm ci
npm run dev        # http://127.0.0.1:5173, proxies /api to port 8083
npm test           # unit tests
npm run build      # production build into frontend/dist, which the backend serves at /
```

### Tests

```bash
cd backend
uv run pytest -q          # uses TEST_DATABASE_URL (created and migrated automatically) and Redis DB 15
uv run ruff check app tests && uv run ruff format --check app tests
```

The tests refuse to run if `TEST_DATABASE_URL` points to the same database as `DATABASE_URL`, because each
test truncates every table.

### Migrations

```bash
cd backend
uv run alembic revision --autogenerate -m "describe the change"   # review the generated file before committing
uv run alembic upgrade head
```

`test_migrations_match_models` fails if a model is changed without a migration.

## Running with Docker

```bash
docker compose -f deploy/docker-compose.yml --env-file .env up -d --build
docker compose -f deploy/docker-compose.yml --env-file .env exec app python -m app.cli create-admin --email ... --name ...
```

The `migrate` service applies migrations before `app` starts. Only the app is published, on
`${APP_BIND_ADDRESS}:8083` (default `127.0.0.1`). PostgreSQL and Redis are reachable only inside the Docker network.
There is no Nginx for now; HTTPS is provided by a Cloudflare tunnel to port 8083 (see the plan, Section 8).

## How the main workflows run

- **Contact upload** (`/imports`): upload a .csv or .xlsx, confirm the suggested column mapping, run with
  `dry_run` to see row-level problems, then run for real. By default one bad row stops the whole import;
  `skip_invalid_rows` saves the valid rows instead. The error report downloads as CSV. Into a campaign, rows with
  the same phone number become one contact with several items (one per PO), and the script's required fields
  (PO number, material, original delivery date) are checked row by row.
- **Scripts**: each change is a new version. Draft, then submit, then approval by a HOD or admin who is not the
  author. Publishing retires the previous version; campaigns keep the exact version they were approved with.
- **Campaigns**: draft, then submit (checks script, contacts and their data), then approval by someone other than
  the submitter. Start, pause and resume arrive with the calling engine in Phase 4.

File storage is a local directory (Docker volume `storage`). Uploaded files are encrypted with
`DATA_ENCRYPTION_KEY`. MinIO was planned but its Docker images are no longer published; storage sits behind an
interface so an S3-compatible service can be added later.

## Security notes

- Phone numbers are stored encrypted (Fernet, `DATA_ENCRYPTION_KEY`) with a keyed HMAC (`PHONE_HASH_KEY`) for
  look-ups and duplicate detection. API responses show masked numbers only. The full number is available to HOD
  and admin roles through `GET /contacts/{id}/phone`, and every such request is audited.
- **Back up `DATA_ENCRYPTION_KEY` and `PHONE_HASH_KEY` separately from the database.** Without the first, stored
  numbers cannot be read; changing the second breaks duplicate detection and do-not-call matching.
- Five failed logins for an e-mail lock it for 15 minutes. Password changes, resets, deactivation and role changes
  sign the user out of all sessions.
- Non-admin users are confined to their own department; other departments' records return 404.

## Roles

| Permission | Operator | Campaign Manager | HOD | Admin |
|---|:-:|:-:|:-:|:-:|
| Read contacts, scripts and campaigns; record consent; add DNC entries | ✓ | ✓ | ✓ | ✓ |
| Create, edit, delete contacts; upload files; write scripts and campaigns | | ✓ | ✓ | ✓ |
| Approve scripts and campaigns, view full phone numbers, remove DNC entries, manage users, read audit log | | | ✓ (own dept) | ✓ |
| Global DNC entries, manage departments | | | | ✓ |
