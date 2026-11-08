# Shared backend

FastAPI + SQLite backend for Accel Business. [PLAN.md](PLAN.md) reconciles the supplied plan with the existing repo and records scope boundaries.

Current verification evidence and remaining live-integration limits are recorded in [VERIFICATION.md](VERIFICATION.md).

## Setup (Windows)

```powershell
cd X:\codes\projects2\airtel_sync
py -3.12 -m venv backend/.venv
backend/.venv/Scripts/python.exe -m pip install -r backend/requirements.txt
```

Source CSVs and KYC samples are already imported into `data/source/`. No external registry is queried. Install Tesseract locally for OCR, or set `TESSERACT_CMD` to its executable. Without it, extraction reports unavailable and KYC requires human review.

Optional settings: copy `.env.example` to `backend/.env`. Credentials belong in this ignored file. Keep `DEMO_MODE=true` for the prototype. Set the same `TRACKER_API_KEY` for both services; otherwise direct Tracker calls remain open for local development. `npm run dev:stack` propagates the backend environment to Tracker.

## Run the connected stack

Stop old processes occupying ports 3001, 3002 or 8000 first. Do not start a second instance against the same JSON files.

```powershell
npm run dev:stack
```

This starts:

- Shared API and Swagger UI: http://127.0.0.1:8000/docs
- Existing Node Tracker: http://127.0.0.1:3001
- WhatsApp simulator using the shared advisor API: http://127.0.0.1:3002

In another terminal:

```powershell
cd web
npm run dev
```

Open the normal website URL printed by Vite (usually http://127.0.0.1:5173/) and select **Speak with AI business partner**. The original website and Android Advisor screen now connect to the pipeline. The separate journey frontend was removed. See [FRONTEND_INTEGRATION.md](FRONTEND_INTEGRATION.md).

The frontend proxies `/api` to port 8000. For a separately hosted website configure `VITE_API_URL` and explicit `CORS_ORIGINS`. The quote, KYC and checkout APIs remain implemented; their further UI integration should use the original app design.

### Quick demo

1. Sign in using the existing prototype login and open **AI business partner**.
2. Describe the business problem, enter the monthly budget and allow business-answer processing.
3. Select **Find a solution**. Questions, options and recommendation cards now come from the shared backend.
4. Answer in text or choose an option; confirm interpreted answers. The initial problem/budget are retained.
5. To use the configured LLM, enable optional AI consent and set `OPENAI_API_KEY`/`OPENAI_MODEL` in `backend/.env`.

For the complete purchase API demonstration use the automated integration tests or Swagger at `/docs`. Those APIs use actual K03 specimen images and the real Node Tracker with mock signature/payment.

## Service contracts

Every customer resource requires `Authorization: Bearer <customer token>`. Use `/auth/request-otp` followed by `/auth/verify-otp` to obtain it. Tokens expire after 24 hours and are hashed in SQLite. OTPs expire after five minutes, are hashed, throttled per number and capped at five guesses. Demo mode intentionally returns the code. Public SMS authentication is not implemented; disabling demo mode rejects OTP requests.

| Endpoint | Purpose |
|---|---|
| `GET /health`, `/consent-notice`, `/catalogue` | Configuration status, consent copy, real synthetic catalogue |
| `POST /consents` | Record advice/KYC/optional AI consent or revocation |
| `GET /registry/{gstin\|udyam}/{identifier}` | Mock lookup; `?scenario=down` simulates failure in demo mode |
| `POST /profiles`, `PUT /profiles/{id}`, `GET /profiles/{id}` | Store and review confirmed facts |
| `POST /sessions`, `GET /sessions/{id}`, `POST /sessions/{id}/turn` | Shared stateful advisor for web/Android |
| `POST /advisor/turn` | WhatsApp adapter boundary; internal bearer key, not a customer token |
| `POST /bundles/recommend?profileId=...` | Validated bundle alternatives with uncovered needs and budget gaps |
| `POST /quotes`, `POST /bundles/reprice`, `POST /quotes/{id}/reprice` | Validate selected items and issue a new immutable quote |
| `GET /quotes/{id}`, `POST /quotes/{id}/sign` | View quote; explicitly mocked e-sign acceptance |
| `POST /kyc/documents` | Multipart `profileId`, `kind`, `file`; 6 MB PNG/JPEG limit |
| `POST /kyc/documents/{id}/confirm` | Confirm/correct the extracted field set |
| `POST /kyc/check?profileId=...` | Validate latest document of each type |
| `POST /quotes/{id}/checkout` | Mock payment with idempotency key; atomic order/outbox creation |
| `GET /orders`, `GET /orders/{id}/tracker`, `POST /orders/{id}/help` | Owned orders, live Tracker proxy and support ticket |
| `POST /internal/orders/{id}/events` | Trusted stage updates with transition validation |
| `POST /internal/tracker/sync`, `GET /internal/tracker/outbox` | Retry/inspect pending Tracker synchronisation |
| `GET /internal/review-queue`, `/internal/data-summary` | Review cases and source counts |

See Swagger for schemas. Recommendation accepts a profile ID in the query; price endpoints accept `{profileId, items:[{productId, quantity}]}`. Client-supplied prices are never accepted. Repricing creates a new quote that must be signed independently. Updating profiles/documents invalidates checkout until a matching quote and KYC check exist.

Internal routes require `Authorization: Bearer <INTERNAL_API_KEY>`. Default development key is `local-dev-only-change-me`; configure a private key before exposing this service.

### Advisor and WhatsApp

The API matches the existing [WhatsApp turn contract](../whatsapp/README.md). The question sequence now includes advice and optional AI consent, business name/type, employees/sites, location/tier, fibre availability, needs, GST-inclusive budget, optional GSTIN and current tools. Option answers are validated against the current question; free-text/voice interpretations require confirmation. Repeated event IDs return the cached turn; reuse with different input is rejected. All facts and provenance persist server-side; untrusted caller-provided history is not authoritative.

For a separately launched WhatsApp service, set:

```dotenv
ADVISOR_TURN_URL=http://127.0.0.1:8000/advisor/turn
ADVISOR_API_KEY=local-dev-only-change-me
```

Use your private internal key if changed. `dev:stack` sets these automatically and forces the local WhatsApp demo mode. For actual Meta delivery start the adapter separately with its live configuration.

### Optional real AI and speech

Set `OPENAI_API_KEY`, an available `OPENAI_MODEL` supporting Responses structured output, and optionally `OPENAI_TRANSCRIPTION_MODEL` supporting audio transcription. Model names are explicit configuration; no billable API request is made by the tests or default demo.

AI interprets an answer into an allowed field value. Local parsers validate that value, and the customer confirms it. Questions and recommendations/explanations remain approved deterministic text, so model output cannot invent product names or prices. English/Hindi/Hinglish question text is supported; full localisation of options/results is future work. Provider failures fall back to clarification; missing speech configuration asks for text instead of advancing on an unprocessed recording.

References: [Responses structured output](https://developers.openai.com/api/docs/guides/structured-outputs), [audio transcription](https://developers.openai.com/api/reference/resources/audio/subresources/transcriptions/methods/create). These optional provider paths are implemented but not live-tested without credentials.

## Verification and limits

```powershell
npm test
npm run test:backend
backend/.venv/Scripts/python.exe -m backend.scripts.audit_kyc --output backend/.runtime/kyc-audit.json
cd web
npm run build
npm run lint
```

The backend suite uses isolated temporary databases and a separate actual Node Tracker process; it never modifies the seed orders. It exercises real K03 image upload/OCR, purchase failure/retry, authentication/consent/ownership, replay handling and all 47 supplied images across 12 applicants. The audit report contains **observed raw-OCR outcomes**, not supplied ground-truth labels. Tesseract OCR can misread characters; correction/confirmation and manual review are intentional parts of the flow.

SQLite and the WhatsApp/Tracker JSON stores are local prototype persistence, without horizontal scaling or automatic document-retention cleanup. Pending Tracker outbox jobs retry every five seconds while the backend runs; paid orders survive outages. Shared API ownership checks protect its reads; configure Tracker's API key and restrict network access for non-local use. KYC is a synthetic demonstration, not government verification, identity authentication or forgery detection. Real SMS, e-sign, payment, LLM/STT calls and Meta delivery are not asserted tested.

Public rollout also needs real authentication, operational review access, retention/deletion controls, rate limits, deployment configuration and live integration testing. The optional back-office scoring/partner workflows and notification templates in the original plan have not been implemented.
