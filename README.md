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
| 3. Real-time voice POC | FreJun (Teler) + Gemini Live call pipeline, call state machine and guards, signed webhooks, individual calls (API + UI), mock mode | Built and tested in simulation |
| 3b. Scenario calls | LangGraph scenario controller during the call, LangChain + Gemini structured result after it, campaign dialer (one channel, one call at a time, retries) | Built and tested in simulation (135 backend + 10 frontend tests). **No real call made yet**: waiting for FreJun and Gemini keys |

Calling is **off** by default (`TELEPHONY_MODE=disabled`). No real call has been placed yet; see
"Running a scenario call" below.

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

**Public address: https://ai.bullmachine.in/aicall/**. The server's shared host nginx (the same one that serves
`/costing/` and `/voicecall/`) passes `/aicall/` to 127.0.0.1:8083. The whole app, including the API
(`/aicall/api/v1/...`) and the FreJun webhooks (`/aicall/telephony/...`), lives under `BASE_PATH=/aicall` from
`.env`. The frontend is built for that prefix, so changing `BASE_PATH` needs `up -d --build`. Directly on the
server the app is at http://127.0.0.1:8083/aicall/.

The nginx site file is kept at `~/nginx/ai.bullmachine.in` and installed with:

```bash
sudo cp ~/nginx/ai.bullmachine.in /etc/nginx/sites-available/ai.bullmachine.in
sudo nginx -t && sudo systemctl reload nginx
```

For local development, `BASE_PATH` can be left empty (the app is then served at `/`).

## Accounts and access

One platform serves every department. **Only admins create accounts and grant access** (Admin > Users and access):

- There are two kinds of account: **Admin** and **User**. The admin makes an account for each person who needs
  one. Each account has a **user ID** for signing in (e-mail is optional and also accepted at sign-in) and,
  except for admins, a department, which decides the records the person sees (table below).
- The admin types a password or has one generated. It is shown once, to pass on to the user, and the user must
  choose their own at first sign-in before they can do anything else.
- The admin can edit name, e-mail, access and department, reset a password (the user is signed out and gets a new
  temporary one), unlock an account after five failed sign-ins, and deactivate or reactivate it. The last active
  admin cannot be removed, and nobody can change their own access or deactivate themselves.
- Every user can change their own password (header > Change password). Every account action is in the audit log;
  passwords never are.

The first admin is created on the server with the CLI command above; after that, everything is done in the app.

## How the main workflows run

- **Contact upload** (`/imports`): upload a .csv or .xlsx, confirm the suggested column mapping, run with
  `dry_run` to see row-level problems, then run for real. By default one bad row stops the whole import;
  `skip_invalid_rows` saves the valid rows instead. The error report downloads as CSV. Into a campaign, rows with
  the same phone number become one contact with several items (one per PO), and the script's required fields
  (PO number, material, original delivery date) are checked row by row.
- **Scripts**: each change is a new version. Draft, then submit, then approval by someone other than the
  author (a colleague in the department, or an admin). Publishing retires the previous version; campaigns keep the exact version they were approved with.
- **Campaigns**: draft, then submit (checks script, contacts and their data), then approval by someone other than
  the submitter. Start, pause and resume arrive with the calling engine in Phase 4.

File storage is a local directory (Docker volume `storage`). Uploaded files are encrypted with
`DATA_ENCRYPTION_KEY`. MinIO was planned but its Docker images are no longer published; storage sits behind an
interface so an S3-compatible service can be added later.

## Calling

```
FreJun  --POST /telephony/frejun/flow-->   app: "stream to wss://.../media"
FreJun  <==WS /telephony/frejun/media==>  app <==> Gemini Live (speech to speech)
                                                    |  record_answer / end_call (tools)
                                                    v
                                            LangGraph scenario graph: checks each answer, decides what to ask next
FreJun  --POST /telephony/frejun/status--> app: ringing / no-answer / completed / recording
after the call:  transcript + recorded answers --> LangChain + Gemini text --> structured result (script's schema)
```

**AI stack (hybrid).** Gemini Live listens and speaks, so replies stay fast (no separate speech-to-text or
text-to-speech). The order of the call is run by a **LangGraph** graph built from the script's questions
([app/voice/scenario.py](backend/app/voice/scenario.py)): whenever the caller answers, the agent calls
`record_answer`; the graph checks the answer (yes/no, real date, "revised date not before the original", ranges,
choices), stores it per PO line, and tells the agent the next question, the next line, or to read back and close.
After the call a **LangChain** chain over a Gemini text model (`GEMINI_TEXT_MODEL`) turns the transcript and the
recorded answers into the script's result schema ([app/services/extraction.py](backend/app/services/extraction.py)).
The result is checked against the schema; it is marked **needs review** when it fails the schema, confidence is
below 0.7, or the call ended before every question was asked.

**One channel, one call at a time.** `CALL_CHANNELS=1` (default): any call waits until the current one ends.
The campaign dialer ([app/services/dialer.py](backend/app/services/dialer.py)) runs inside the app when calling
is on. For each running campaign, inside its calling hours, it calls the contacts one after another. No answer,
busy or an early hang-up is retried after the campaign's retry interval, up to its maximum attempts. Do-not-call
contacts are skipped. Campaign page: **Start calling**, **Pause** (the call in progress finishes), **Resume**.

- Every URL given to FreJun carries a signed token for that call and purpose; the media stream is single-use.
- The call controller (not the AI) checks do-not-call, calling hours, the channel limit and that the number is
  not already being called; it hangs up on silence, turn and time limits. The AI can only end the call
  (`end_call` with an outcome). If the outcome is `opted_out`, the number goes on the do-not-call list by rule.
- Each call stores the exact script version, prompt, model, voice and settings used (`ai_config`), the
  transcript, provider events (phone numbers masked), metrics (reply time, interruptions) and the end reason.
- `TELEPHONY_MODE=mock` simulates the phone network for development; such calls are stored and shown as
  **simulated** and are refused when `APP_ENV=production`.

### Running a scenario call

1. Put the FreJun and Gemini values in `.env`: `TELER_API_KEY`, `FREJUN_PHONE_NUMBER`, `GEMINI_API_KEY`.
2. Start the Cloudflare tunnel: `deploy/tunnel.sh`. It opens a quick tunnel to the app's host port, writes
   `PUBLIC_URL=https://<random>.trycloudflare.com/aicall` into `.env`, restarts the app and checks the address
   answers. FreJun's webhooks and audio stream use this address; people keep using ai.bullmachine.in/aicall/.
   A quick tunnel's address changes whenever it restarts (e.g. after a server reboot): run `deploy/tunnel.sh`
   again. `deploy/tunnel.sh stop` closes it. A named Cloudflare tunnel would keep a fixed address.
3. Set `TELEPHONY_MODE=live` and restart: `docker compose -f deploy/docker-compose.yml --env-file .env up -d`.
   The app refuses to start if anything required for live calls is missing.
4. Load the scenario (the SCM delivery confirmation script) and approve it in the app (a second person, or an
   admin, approves): `docker compose -f deploy/docker-compose.yml --env-file .env exec app python -m app.cli
   seed-scm-script --department SCM`.
5. **One call:** Calls > New call: the test number, the script, and one PO line (PO number, material, original
   delivery date). The call page shows the transcript live, then the answers recorded during the call and the
   extracted result.
6. **One by one:** a campaign with a few internal test contacts (upload or add them, each with its PO lines),
   submit, approve, then **Start calling**. The dialer calls them one after another.

## Connected apps

Every department can link its own systems under **Connected apps** (`/integrations`), without code changes:

- **Bring people in** (`fetch_contacts`): the app GETs a JSON list from the department's CRM, ERP or HR system.
  The records (nested fields flattened to columns such as `customer.name`) go through the same column matching,
  duplicate and do-not-call checks as an uploaded file: Upload contacts > Connected app.
- **Send results out** (`send_results`): after each call is analysed, the app POSTs the result as JSON (sample:
  `GET /api/v1/integrations/sample-result`). With a signing secret, verify
  `X-BullCall-Signature = "sha256=" + hex(HMAC_SHA256(secret, X-BullCall-Timestamp + "." + body))`.
  Server errors and timeouts are retried; phone numbers are always masked.

Sign-in can be a bearer token, an API key header or user name and password; secrets are stored encrypted and never
returned. Connections refuse loopback and link-local addresses, and private networks unless
`INTEGRATIONS_ALLOW_PRIVATE_NETWORKS=true`.

### API keys and MCP (other systems calling us)

Under Connected apps, anyone can create an **API key** (`bmk_...`, shown once; only its SHA-256 is stored). A key
acts as its creator, in their department, limited to its access level:

- **read**: campaigns, scripts, calls and results, contacts.
- **write**: also create campaigns, add contacts, submit for approval, start / pause / resume.

Keys can never approve, place one-off calls, or reach accounts, keys, connected apps, departments or the audit
log. They stop working when revoked, expired, or when the owner is deactivated or changes department. Send
`Authorization: Bearer bmk_...` (or `X-API-Key: bmk_...`) to the REST API (`/api/v1/docs`).

The **MCP server** is at `/api/v1/mcp` (Streamable HTTP, stateless JSON; same keys). Tools: `list_scripts`,
`list_campaigns`, `get_campaign`, `list_calls`, `get_call_result`, and with a write key `create_campaign`,
`add_contacts` (same checks as an upload; `dry_run` first), `submit_campaign`, `control_campaign`. Claude Code:

    claude mcp add --transport http bull-ai-calling https://<host>/aicall/api/v1/mcp \
      --header "Authorization: Bearer bmk_..."

## Security notes

- Phone numbers are stored encrypted (Fernet, `DATA_ENCRYPTION_KEY`) with a keyed HMAC (`PHONE_HASH_KEY`) for
  look-ups and duplicate detection. API responses show masked numbers only. The full number is available to the
  department's users and to admins through `GET /contacts/{id}/phone`, and every such request is audited.
- **Back up `DATA_ENCRYPTION_KEY` and `PHONE_HASH_KEY` separately from the database.** Without the first, stored
  numbers cannot be read; changing the second breaks duplicate detection and do-not-call matching.
- Five failed sign-ins lock an account for 15 minutes. Password changes, resets, deactivation and access changes
  sign the user out of all sessions.
- Users are confined to their own department; other departments' records return 404.

## Account types

| What they can do | User | Admin |
|---|:-:|:-:|
| Contacts, uploads, scripts, campaigns, calls, consent and do-not-call entries | ✓ (own department) | ✓ (all) |
| Approve a script or campaign written or submitted by someone else | ✓ (own department) | ✓ |
| Create accounts and give access, manage departments, global do-not-call entries, read the audit log | | ✓ |
