# Bull AI Voice Calling Platform

Enterprise AI outbound calling platform for Bull Machines. Departments upload contacts, run calling campaigns with
configurable AI scripts, and receive structured results from each call. First use case: SCM supplier delivery
confirmation.

The design, decisions and roadmap are in [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md).

## Status

| Phase | Scope | State |
|---|---|---|
| 1. Foundation | Database (all 22 tables, Alembic), JWT auth, users, departments, RBAC with department isolation, contacts, consent, do-not-call, audit log, health checks, Docker | Done |
| 2. Campaigns and scripts | Excel/CSV upload with column mapping, script builder with versions and approval, campaigns with approval, SCM script, encrypted file storage, React UI | Done |
| 3. Real-time voice POC | FreJun (Teler) + Gemini Live call pipeline, call state machine and guards, signed webhooks, individual calls (API + UI), mock mode | Built and tested in simulation (125 backend + 10 frontend tests, browser walkthroughs). **No real call made yet**: waiting for credentials |

Calling is **off** by default (`TELEPHONY_MODE=disabled`). No real call has been placed yet; see
"Making the first real call" below.

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
    providers/   telephony adapters (FreJun, mock) behind one interface
    voice/       call session, Gemini Live engine, prompt builder, state machine, signed URLs, webhooks
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
uv run python -m app.cli create-admin --user-id admin --name "Your Name"   # prompts for password
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
docker compose -f deploy/docker-compose.yml --env-file .env exec app python -m app.cli create-admin --user-id admin --name "..."
```

The `migrate` service applies migrations before `app` starts. Only the app is published, on
`${APP_BIND_ADDRESS}:8083` (default `127.0.0.1`). PostgreSQL and Redis are reachable only inside the Docker network.
There is no Nginx for now; HTTPS is provided by a Cloudflare tunnel to port 8083 (see the plan, Section 8).

## Accounts and access

One platform serves every department. **Only admins create accounts and grant access** (Admin > Users and access):

- Each account has a **user ID** for signing in (e-mail is optional and also accepted at sign-in), a role and,
  except for admins, a department. The role decides what the person can do (table below); the department
  decides which records they see.
- The admin types a password or has one generated. It is shown once, to pass on to the user, and the user must
  choose their own at first sign-in before they can do anything else.
- The admin can edit name, e-mail, role and department, reset a password (the user is signed out and gets a new
  temporary one), unlock an account after five failed sign-ins, and deactivate or reactivate it. The last active
  admin cannot be removed, and nobody can change their own role or deactivate themselves.
- Every user can change their own password (header > Change password). Every account action is in the audit log;
  passwords never are.

The first admin is created on the server with the CLI command above; after that, everything is done in the app.

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

## Calling (Phase 3)

```
FreJun  --POST /telephony/frejun/flow-->   app: "stream to wss://.../media"
FreJun  <==WS /telephony/frejun/media==>  app <==> Gemini Live (speech to speech)
FreJun  --POST /telephony/frejun/status--> app: ringing / no-answer / completed / recording
```

- Every URL given to FreJun carries a signed token for that call and purpose; the media stream is single-use.
- The call controller (not the AI) checks do-not-call, calling hours, the 5-call limit and that the number is
  not already being called; it hangs up on silence, turn and time limits. The AI can only end the call
  (`end_call` with an outcome). If the outcome is `opted_out`, the number goes on the do-not-call list by rule.
- Each call stores the exact script version, prompt, model, voice and settings used (`ai_config`), the
  transcript, provider events (phone numbers masked), metrics (reply time, interruptions) and the end reason.
- `TELEPHONY_MODE=mock` simulates the phone network for development; such calls are stored and shown as
  **simulated** and are refused when `APP_ENV=production`.

### Making the first real call

1. Put the FreJun and Gemini values in `.env`: `TELER_API_KEY`, `FREJUN_PHONE_NUMBER`, `GEMINI_API_KEY`.
2. Start a tunnel to port 8083 and put its https address in `PUBLIC_URL`:
   `cloudflared tunnel --url http://localhost:8083` (a quick tunnel's address changes on every restart;
   a named tunnel or company domain is needed before campaigns).
3. Set `TELEPHONY_MODE=live` and restart: `docker compose -f deploy/docker-compose.yml --env-file .env up -d`.
   The app refuses to start if anything required for live calls is missing.
4. In the app: approve the SCM script, add an internal test contact, then Calls > New call.

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
| Read contacts, scripts and campaigns; place individual calls; record consent; add DNC entries | ✓ | ✓ | ✓ | ✓ |
| Create, edit, delete contacts; upload files; write scripts and campaigns | | ✓ | ✓ | ✓ |
| Approve scripts and campaigns, view full phone numbers, remove DNC entries, see the department's users, read audit log | | | ✓ (own dept) | ✓ |
| Create accounts and grant access, manage departments, global DNC entries | | | | ✓ |
