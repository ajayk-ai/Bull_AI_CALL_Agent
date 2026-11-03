# Bull AI Voice Calling Platform: Implementation Plan

Status: Approved to proceed, 3 November 2026. Decisions D1 to D5 confirmed, see Section 2.1.
Progress: Phases 1 and 2 complete. Phase 3 (voice POC) next. MinIO replaced by encrypted local storage (images no longer published).

---

## 1. Inspection findings

### 1.1 This repository

| Item | Finding |
|---|---|
| Git | Branch `master`, no commits. `main` (named as the PR base) does not exist yet. |
| Contents | `uv` scaffold only: `pyproject.toml`, `.python-version` (3.14), empty `src/bull_ai_call_agent/__init__.py`, empty README. |
| Conclusion | Greenfield. Nothing to migrate or preserve. |

### 1.2 Server

| Item | Brief assumes | Actual |
|---|---|---|
| OS | Ubuntu 24.04 LTS | **Ubuntu 26.04.1 LTS** |
| CPU / RAM / disk | 8 vCPU / 16 GB / 200 GB | 8 vCPU / 30 GB (27 GB free) / 193 GB (180 GB free) |
| Python | not stated | 3.14.4, uv 0.13.5 |
| Node | not stated | 22.22.1 (npm 9.2.0) |
| Docker | required | Docker 29.1.3, Compose 2.40.3 |
| PostgreSQL | container | Host PostgreSQL 18.6 already running on `127.0.0.1:5432` |
| Redis | container | Not installed on host (container is fine) |
| TLS | HTTPS required | **No certificates on the host.** No listener on 443. |
| Port 80 | our Nginx | **Taken** by `costing-nginx-1` (another application's container) |

The server is shared. Running services:

| Service | Port | Notes |
|---|---|---|
| Costing app + Nginx (Docker) | 80 public, 8000 local | Owns port 80 |
| HR Absentee Call Agent (`~/apps/absentee-v2`) | 8080 public → 8020 | Voice agent, live |
| SOP Translator | 8081 public | |
| PO Agent (`~/voice_call`, Docker `po-agent`, `po-sync`) | 8082 public | Voice agent, live |

Our Compose stack therefore cannot bind 80/443 directly without coordinating with the costing application owner. **Decided 3 November 2026: no Nginx for now; this platform uses port 8083** (confirmed free). See Section 8.

### 1.3 Existing voice agents on this server (most important finding)

Two working AI calling applications already exist and have made **real, provider-connected calls**:

| | PO Agent (`~/voice_call`) | HR Absentee Call Agent (`~/apps/absentee-v2`) |
|---|---|---|
| Purpose | Overdue PO follow-up with vendors: WhatsApp, then voice call, then meeting | Calls absent employees in Tamil for reason and return date |
| Telephony | FreJun (Teler) | FreJun (Teler) |
| Voice AI | Gemini Live (native audio, speech-to-speech) | Gemini Live |
| Post-call | Separate analysis model extracts delay reason and committed dates | Reason and return-day extraction |
| Evidence | Tests in `tests/voice_agent` | `evidence.txt`, 29 Oct 2026: completed Tamil calls with extracted reasons and return days; per-call audio quality report |

Consequences for this project:

1. **The highest technical risk named in the brief (a natural AI conversation over Indian telephone networks, in Tamil) has already been retired once on this server**, with FreJun + Gemini Live. The brief's Phase 3 plan (Exotel + separate ASR, LLM and TTS) would re-open that risk with a different, unproven stack.
2. **The initial use case (SCM supplier delivery confirmation) overlaps the PO Agent.** Running both against the same suppliers would produce duplicate calls to the same vendor. One must own supplier calling, or they must share a do-not-call/suppression list.
3. Proven, reusable pieces exist: telephony WebSocket bridge, 24 kHz → 8/16 kHz resampling with a phone-band filter, turn recording, signed call-context tokens, phone number masking, emergency stop, and tuned VAD/buffer settings.

These points drive Decisions D1 to D3 below.

---

## 2. Decisions required before Phase 1

| # | Decision | Options | Recommendation |
|---|---|---|---|
| D1 | Voice pipeline architecture | (a) Speech-to-speech: Gemini Live native audio. (b) Cascaded: streaming ASR → LLM → streaming TTS. | **Support both behind one `VoiceEngine` interface; build (a) first.** (a) is proven here and has lower latency and built-in barge-in. (b) gives per-stage control, better transcripts and provider choice, and is needed if (a) fails on Hindi or code-mixed speech. The FSM and tool-gating apply to both. |
| D2 | First telephony provider | (a) FreJun Teler (already contracted and working). (b) Exotel AgentStream (brief's choice, not yet integrated). | **(a) first, (b) as the second adapter in Phase 3b.** Building against a working account removes a commercial dependency from the critical path. The adapter interface is designed from day one so Exotel is a drop-in. |
| D3 | Relationship to PO Agent | (a) New platform replaces PO Agent's voice step over time. (b) Both run; platform takes SCM delivery confirmation, PO Agent keeps its escalation flow. (c) Platform starts with a non-SCM use case. | **(a), with a shared suppression check during overlap.** Needs the SCM owner's agreement. |
| D4 | PostgreSQL | (a) Container, as the brief says. (b) Existing host PostgreSQL 18. | **(a)**. Isolates data, backups and upgrades from other applications. Not published to the host. |
| D5 | Public HTTPS endpoint | (a) Domain + certificate from IT. (b) Cloudflare tunnel to port 8083 (as PO Agent does). | **(b) for now**, since Nginx is deferred; (a) when Nginx is introduced. Telephony providers must reach the webhook and media WebSocket over HTTPS/WSS. |

### 2.1 Decisions confirmed (3 November 2026)

| # | Decision |
|---|---|
| D1 | Speech-to-speech with Gemini Live native audio. The cascaded engine is not planned; the `VoiceEngine` interface is kept so it can be added later if Phase 3 shows a need. |
| D2 | FreJun Teler is the first and only telephony provider for now. Exotel is not planned; the `TelephonyProvider` interface is kept. |
| D3 | The platform is independent of PO Agent and has its own separate database. No data is shared between them. |
| D4 | PostgreSQL in this platform's own container (`bullcall-postgres-1`), separate from the host PostgreSQL and from PO Agent. |
| D5 | Cloudflare tunnel to port 8083, as PO Agent does. No Nginx for now. |

Consequence of D3: neither system knows what the other has called. While both are active, the same supplier can
receive a call from each. This is managed operationally (for example, SCM does not load the same suppliers into
both) rather than in code.

Phase 3b (Exotel adapter, cascaded engine, provider evaluation) is dropped from the roadmap following D1 and D2.

---

## 3. Target architecture

```
            Users / telephony provider (HTTPS / WSS via Cloudflare tunnel)
                                 │
                          host port 8083
                                 │
                 app container (one FastAPI process, uvicorn)
          ┌──────────────────────┼─────────────────────────┐
          │                      │                         │
     /  (static)            /api/v1, /ws              /telephony/*
     built React            api routers               voice-gateway routers
     frontend               REST, auth, RBAC,         provider webhooks, media WebSocket,
                            live-event WS             call FSM, VoiceEngine
                                 │                         │
             ┌───────────────────┼─────────────┬───────────┘
             │                   │             │
        PostgreSQL            Redis         MinIO
        (state, audit)   (queue, locks,   (recordings,
                          pub/sub events)  import files)
             │                   │
     campaign-worker         ai-worker            celery-beat
     (Celery: dispatch,      (Celery: extraction,  (schedules: campaign
      retries, concurrency)   summaries, followups) windows, retention)
```

Principles:

- **One public port, one web process for now.** Without Nginx, a single port cannot route to separate `api` and `voice-gateway` containers, so both router sets run in one FastAPI process on 8083, which also serves the built frontend. At 5 concurrent calls this is well within one process's capacity; PO Agent runs the same way. The voice code stays in its own package (`app/voice`, `main_voice.py`) with no imports from the API routers, so it can move to its own container when Nginx is introduced. Celery workers and beat are separate containers from the start. No other microservices.
- **The LLM never acts directly.** It can only call declared tools (`record_answer`, `request_transfer`, `end_call`). The FSM validates every tool call against the script and current state. Placing calls, writing business records and retries are done by deterministic code.
- **Provider independence.** `TelephonyProvider`, `VoiceEngine`, `ASRProvider`, `TTSProvider` and `LLMProvider` are interfaces. Provider names appear only in `app/providers/<name>/` and in configuration.
- **Mock mode is explicit.** `TELEPHONY_MODE=mock|live`. Mock calls are stored with `is_simulated = true`, shown with a "SIMULATED" badge, and excluded from dashboards by default. Live mode refuses to start with mock credentials.

### 3.1 Call lifecycle FSM

```
QUEUED → DIALING → RINGING → CONNECTED → GREETING → CONVERSING ⇄ (BARGE_IN)
                      │           │                       │
                      ▼           ▼                       ▼
              NO_ANSWER/BUSY   FAILED            CONFIRMING → CLOSING → COMPLETED
                                                          │
                                         TRANSFER_REQUESTED / ESCALATED / DROPPED
```

Guards enforced by the FSM, not the model: calling window, DNC check at dial time, maximum call duration, silence timeout (configurable, for example 2 prompts then close), maximum turns, emergency stop, and the rule that `CLOSING` requires every mandatory question to be answered or explicitly refused.

---

## 4. Repository structure

```
Bull_AI_CALL_Agent/
├── backend/
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── alembic/versions/
│   ├── app/
│   │   ├── core/            settings, logging, security (JWT, password hashing, encryption), errors
│   │   ├── db/              SQLAlchemy engine/session, base model
│   │   ├── models/          ORM models (one module per aggregate)
│   │   ├── schemas/         Pydantic request/response models
│   │   ├── api/v1/          routers: auth, users, departments, contacts, imports, campaigns,
│   │   │                    scripts, calls, transcripts, results, followups, dashboard, webhooks
│   │   ├── services/        business logic (no HTTP)
│   │   ├── rbac/            roles, permissions, department scoping
│   │   ├── voice/
│   │   │   ├── fsm.py       call state machine
│   │   │   ├── session.py   per-call orchestration
│   │   │   ├── audio/       resampling, VAD, codecs, jitter buffer
│   │   │   └── tools.py     LLM tool definitions and FSM validation
│   │   ├── providers/
│   │   │   ├── telephony/   base.py, mock.py, frejun.py, exotel.py
│   │   │   ├── engines/     gemini_live.py, cascaded.py
│   │   │   ├── asr/ tts/ llm/
│   │   ├── extraction/      schema validation, evidence linking, confidence routing
│   │   ├── workers/         celery app, campaign tasks, ai tasks, beat schedule
│   │   ├── main.py          FastAPI app on port 8083: mounts api + voice routers + frontend
│   │   ├── main_api.py      api routers (standalone app later)
│   │   └── main_voice.py    voice-gateway routers (standalone app later)
│   └── tests/ unit/ integration/ fixtures/audio/
├── frontend/                Vite + React + TypeScript + Tailwind
├── deploy/
│   ├── docker-compose.yml, docker-compose.dev.yml
│   ├── backup/              pg_dump + MinIO mirror scripts
│   └── DEPLOYMENT.md        Ubuntu deployment guide
├── docs/                    this plan, API notes, provider evaluation, runbooks
├── .env.example
└── README.md
```

The current `src/bull_ai_call_agent` scaffold will be replaced by `backend/app`.

---

## 5. Data model notes

All 22 tables in the brief are kept. Additions and conventions:

- UUID v7 primary keys (time-ordered, index friendly); `created_at`, `updated_at` on all tables; soft delete only where audit requires it.
- `departments` scope everything: `contacts`, `campaigns`, `scripts`, `calls` carry `department_id`, and every query passes through a department filter in the service layer.
- `script_versions` is immutable once `status = published`. `campaigns` reference a `script_version_id`, not a script.
- `calls` stores `script_version_id`, `ai_config` (JSONB snapshot: engine, models, voice, language, VAD settings), `provider`, `provider_call_id` (unique per provider), `is_simulated`.
- `call_events` has a unique key on `(provider, provider_event_id)` for idempotent webhook handling.
- `campaign_contacts` has a unique key on `(campaign_id, contact_id)`; `call_queue` uses a Redis lock per phone number to prevent concurrent duplicate dials across campaigns.
- `extracted_results` keeps `raw` (model output), `validated` (after schema check) and `corrected` (human) separately, with `extraction_field_evidence` linking each field to transcript turn IDs.
- Phone numbers stored in E.164, encrypted at rest (application-level, Fernet/AES-GCM) with a separate hashed column for lookups and duplicate detection. Masked in all API responses unless the user holds `contacts:view_full_number`.

---

## 6. Provider dependencies

All candidates below must be validated with **real Bull supplier-style speech samples** (Tamil, Hindi, English, Tamil-English mix; mobile and landline; noisy shop-floor backgrounds). No provider is final until the evaluation in Phase 3 passes.

| Function | First choice | Alternatives to evaluate | Account / input needed |
|---|---|---|---|
| Telephony | FreJun Teler (existing account) | Exotel AgentStream | Confirm FreJun account can be shared or a new sub-account issued; Exotel KYC, DID/virtual number, AgentStream enablement |
| Speech-to-speech | Gemini Live native audio (as used by PO Agent) | | Gemini API key or Vertex project; confirm data residency acceptable to IT |
| Streaming ASR (cascaded) | Sarvam AI (Indian languages, code-mixed) | Google Cloud Speech (Chirp), Deepgram | API keys for evaluation |
| Streaming TTS (cascaded) | Sarvam AI | Google Cloud TTS, ElevenLabs | API keys for evaluation |
| LLM (cascaded, extraction) | Gemini | GPT, Claude | API key; model chosen on extraction accuracy in evaluation |
| Object storage | MinIO (self-hosted) | AWS S3 | None for MinIO |

Evaluation criteria (Phase 3): word error rate on PO numbers and dates, response latency (target: first audio within 1.2 s of caller end-of-speech, to be confirmed), barge-in reaction time, language switch handling, voice naturalness rated by SCM users, and cost per call minute. **Cost figures are not included here; they require current quotes from each provider.**

---

## 7. Phased milestones

Each milestone ends with tests passing and a short demo. A feature is reported complete only after it has been tested.

| Phase | Deliverable | Acceptance |
|---|---|---|
| **1. Foundation** | Repo structure, Compose dev stack (postgres, redis, minio), settings, logging, Alembic baseline, all core tables, JWT auth, users, departments, RBAC, audit log, contacts CRUD, DNC, consent, health checks | Unit + integration tests green; OpenAPI at `/api/v1/docs`; department isolation test proves HOD of dept A cannot read dept B |
| **2. Campaigns and scripts** | Excel/CSV import with row-level error report, duplicate detection, import history, campaigns CRUD and state machine, script builder API, versioning, approval workflow, SCM delivery confirmation script and extraction schema as seed data; minimal React UI for these | Import of a 500-row file with deliberate errors yields the exact error report; a published script version cannot be edited |
| **3a. Voice POC (single call)** | `TelephonyProvider` + mock + FreJun adapter, voice gateway, FSM, Gemini Live engine, tool gating, transcript and recording to MinIO, individual call API | **10 real calls** to internal test numbers (Tamil, English, Hindi, mixed) with transcripts, recordings and latency report. Mock-mode tests in CI |
| ~~3b. Provider evaluation~~ | Dropped (D1, D2). Language quality for Hindi and Tamil-English mix is still measured in Phase 3a calls | |
| **4. Bulk calling** | Celery dispatch, concurrency limit (5), calling window, retries, pause/resume/cancel, idempotent webhooks, live campaign progress WebSocket | 100-call campaign against mock completes with correct retry counts; 20-call live campaign to internal numbers |
| **5. AI intelligence** | Post-call extraction, schema validation, evidence linking, confidence routing to human review queue, summaries, follow-up tasks | Extraction accuracy measured against hand-labelled transcripts from Phase 3/4 calls |
| **6. Enterprise deployment** | Dashboard and filters, transcript/recording/result viewers, retention jobs, backups, production Compose, deployment guide, UAT. Nginx + TLS + split voice-gateway container only if decided by then | UAT sign-off by SCM; compliance sign-off (Section 9) |

Phase 3a starts as soon as the Phase 1 data model and auth exist; the full Phase 2 UI is not needed before the first real call.

---

## 8. Deployment on the shared server

- The stack runs as a separate Compose project (`bullcall`) on its own Docker network. PostgreSQL, Redis, MinIO and internal ports are **not** published to the host.
- **No Nginx for now.** Only the `app` container is published, on **port 8083**. The bind address is set by `APP_BIND_ADDRESS` in `.env`. The default is `127.0.0.1`, so the only way in is through the Cloudflare tunnel, which provides HTTPS/WSS to users and the telephony provider. `0.0.0.0` would serve plain HTTP on 8083 to the network, and should only be used if the cloud firewall limits 8083 to the office network.
- A quick Cloudflare tunnel's address changes on every restart, so the provider webhook URL must be updated each time. A named tunnel or an IT-issued domain removes this; needed before Phase 4.
- When Nginx is introduced later, it takes the public port and `app` moves behind it unchanged.
- Resource budget at the initial load (5 concurrent calls, 100 attempts/day) is small; the server has ample headroom. Container memory limits will be set so this stack cannot starve the other applications.
- Observation outside this project's scope, for IT: ports 8080, 8081 and 8082 are bound on all interfaces (`0.0.0.0`). Whether these are reachable from the internet depends on the cloud firewall/security group, which was not checked.

---

## 9. Compliance items (owner: compliance team, before any production calling)

These are flagged, not resolved. The platform will implement the controls; whether they are sufficient is the compliance team's decision.

1. TRAI rules for automated/commercial voice calls to suppliers (B2B service calls), including whether a specific number series or registration is required.
2. DPDPA: lawful basis and notice for recording and transcribing calls; disclosure that the caller is an AI; retention periods for recordings, transcripts and extracted data.
3. Cross-border processing: audio and transcripts sent to cloud AI providers.
4. Calling-window defaults (proposed 09:30 to 18:30 IST, Monday to Saturday, excluding company holidays; to be confirmed).

---

## 10. Technical risks

| Risk | Mitigation |
|---|---|
| Python 3.14 compatibility of Celery, asyncpg and audio libraries | Verify in Phase 1. Fall back to 3.13 in containers if any core dependency fails. |
| Speech-to-speech gives less control over exact wording of PO numbers and dates | Read-back confirmation step in FSM; extraction validated against contact data (PO number must match the campaign record) |
| Hindi and code-mixed speech quality unproven with current stack | Phase 3b evaluation; cascaded engine as fallback |
| Duplicate supplier calls from PO Agent and this platform | Separate databases (D3), so managed operationally: SCM decides which system calls which suppliers |
| Provider webhook or media stream outages | Idempotent events, FSM timeouts, call marked `FAILED_PROVIDER` and retried per campaign rules |

---

## 11. Data and inputs requested

1. Decisions D1 to D5.
2. A sample (anonymised) SCM supplier list in the real format: column names, number formats, PO number pattern.
3. 10 to 20 internal test phone numbers with consent, covering Tamil, Hindi and English speakers.
4. Provider accounts: FreJun access for this project; Exotel account status; Gemini/Vertex project to use.
5. Company domain and the IT contact for DNS and TLS.
6. Existing SSO/identity provider, if user login should use it instead of local passwords.
