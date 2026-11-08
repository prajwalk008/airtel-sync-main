# Local verification — 8 November 2026

**Historical record:** the separate `/journey` frontend described below was subsequently removed at the user's direction. Current frontend integration is in the original website and Android AI business partner screens. See `FRONTEND_INTEGRATION.md` for current behaviour and checks.

## Passed

- `backend/.venv/Scripts/python.exe -m pytest backend/tests -q`: **14 passed** in 37.29 seconds. One dependency deprecation warning in Starlette/AnyIO; no test failures.
- `npm test`: **8 passed**, covering the existing Tracker and WhatsApp adapter.
- `web`: `npm run build` and `npm run lint` both exited successfully after the connected journey changes.
- `git diff --check`: no whitespace errors (Git reports normal Windows LF/CRLF conversion notices).
- `backend/.venv/Scripts/python.exe -m backend.scripts.verify_stack`: actual HTTP WhatsApp simulator → shared FastAPI advisor → confirmations → catalogue-priced recommendation passed. No external Meta/AI request made.
- Browser walkthrough at `http://127.0.0.1:5174/journey`: mock OTP sign-in, advice/KYC consent, K03 profile, server recommendation, quote, actual K03 image extraction, customer confirmation of all three documents, KYC pass, simulated payment failure and successful retry, order creation and actual Node Tracker timeline.
- Browser-created synthetic order: `ORD-724ad25db5f6487eb04087995db417c7`. Timeline displayed confirmation, business verification and provisioning. This demo order was appended to the existing local Tracker data; existing sample orders were preserved.

## Data and OCR audit

Catalogue: 25 products. GSTIN registry: 3,534 entries. Udyam registry: 2,723 entries. Leads: 5,000 rows.

All 47 supplied images were processed across all 12 applicants. The generated local report is `backend/.runtime/kyc-audit.json`. Raw OCR observations with simulated field confirmation:

- Pass: K03, K12.
- Manual review: K05, K09 (signatory authorisation).
- Customer correction: K01, K02, K04, K06, K07, K08, K10, K11. This includes OCR character errors; some cases may move to manual review or pass after accurate customer corrections. K11 also contains stale address proof.

No supplied expected-outcome labels exist in the data pack. These observations and the regression pass-set are **not** an independent model-accuracy benchmark. The customer-facing flow never assumes the audit's simulated confirmation.

## Not live-tested / remaining scope

- Real OpenAI interpretation and speech transcription need configured credentials/models and explicit customer consent. Provider-shaped tests and missing-provider fallback pass; billable provider calls were not made.
- Actual WhatsApp delivery needs Meta production sender credentials and an HTTPS webhook.
- OTP, e-sign and payment are explicitly mocked. Public SMS authentication is not implemented.
- The Android visual prototype is preserved; its existing illustrative screens have not been migrated to the shared API. The connected web `/journey` and WhatsApp adapter use the shared backend.
- Remaining optional phases and production concerns are listed in `PLAN.md` and `README.md`.

The local stack is running on API 8000, Tracker 3001 and WhatsApp preview 3002. The additional Vite preview uses 5174 because an existing Vite process occupies 5173. For a fresh launch, run `npm run dev:stack`, then the web dev server separately.
