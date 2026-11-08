# Reconciled implementation plan

This document adapts the supplied phased plan to the repository that already exists. It describes a local working prototype, not a public production deployment.

| Stage | Adaptation | Implementation / verification |
|---|---|---|
| Foundation | Keep `web/`, `mobile/`, Node Tracker and WhatsApp; add FastAPI under `backend/` | SQLite stores customers, expiring bearer sessions, OTP attempts, profiles, consent decisions, advisor sessions, documents, quotes, orders, tickets, audit events and a Tracker outbox. Synthetic source pack is under `data/source/`. |
| Core engines | Build missing builder/validator modules; configuration in JSON rather than adding YAML dependency | All 25 catalogue rows drive price, quantities, setup, contracts, installation days, eligibility and dependencies. Mock registry lookup supports active, inactive, missing and simulated-down responses. |
| Advisor | Share a persisted question state machine across authenticated web/Android API calls and trusted WhatsApp adapter calls | Text/option interpretation has deterministic fallback. Unstructured or voice answers require confirmation. Optional OpenAI structured interpretation/transcription is gated by consent and environment configuration. Model outputs never set catalogue prices. |
| Purchase | Immutable quote snapshots, explicit reprice, KYC field review, mock signing/payment | APIs remain available. The separate `/journey` frontend was removed at the user's direction. The original web/Android design is retained and the existing AI business partner screens call the pipeline. Checkout/KYC UI integration remains in the original design's future scope. |
| Tracker | Integrate existing Node service through durable SQLite outbox | Orders commit before delivery. Failed sync remains pending and retries. Stable event IDs prevent repeated lifecycle events. Tracker reads are proxied after ownership checks; private reads can be API-key protected. |
| KYC | Real local Tesseract OCR for PNG/JPEG; validate against synthetic registries | Customer confirms/corrects extracted fields. Results are pass, customer_to_fix or manual_review. Date checks use pack reference 2026-07-15. Small/blur heuristics are advisory; comprehensive tilt/liveness/forgery detection is not implemented. |
| WhatsApp | Keep text/options/voice scope requested by user | `npm run dev:stack` connects the existing simulator to `/advisor/turn`. Images/videos remain unsupported in chat. KYC images go through authenticated HTTP upload. Actual Meta delivery still requires credentials. |

## Deliberate changes from the pasted plan

- The referenced `bundle_builder.py` and `kyc_validator.py` were not present. New modules implement the documented concepts rather than claiming those files were reused.
- Do not force a Rs 4,844 CA-firm bundle. Prices are computed from the actual selected products and quantities. Example: fibre 100 + five email seats + five endpoint licences = Rs 2,119 before GST / Rs 2,500.42 including GST.
- Catalogue price ranges are not a complete tariff schedule. This demo explicitly chooses the minimum rate, adds 18% GST to recurring/setup prices and charges first month plus setup in mock pay-today. These are demo policies, not asserted real carrier terms.
- City tier/fibre availability are declared demo facts. There is no live address-serviceability source in the pack. Unknown tier produces no eligible connectivity recommendation rather than inventing availability.
- No original expected-outcome labels for all 12 KYC applicants were supplied. The OCR audit records observed results; it is not an independent accuracy benchmark. K03 and K12 are clean regression specimens with this extraction flow.
- Human/manual KYC review is queued, not silently approved. A production reviewer role, decision workflow and reviewer UI remain future work.
- Complete localisation, AI-authored phrasing, voice UI in the web/Android app, secure cross-channel checkout links, approved WhatsApp notifications, independent per-product provisioning, automatic simulated progress, propensity training, partner commissions and submission slides/video remain later phases.
- Shared mobile numbers are normalised (ten-digit Indian input gets +91 in storage); WhatsApp transport identity is accepted only on the internal authenticated endpoint. Customers still authenticate separately to retrieve private profiles/orders.

## Verification gates

1. Data counts and registry failures; exact tax/dependency checks and broad catalogue eligibility combinations.
2. Consent, authentication, ownership isolation, advisor confirmation, duplicate/replayed turn handling and voice failure fallback.
3. All 47 real specimen images across 12 applicants; mismatched names, stale address proof, missing authorisation and missing OCR cannot silently pass.
4. Actual uploaded K03 documents → KYC pass → signed quote → failed/mock-success payment → real Node Tracker → installation → activation.
5. Node Tracker/WhatsApp regression suite and connected web build/lint; manual browser purchase walkthrough.

No finite test run establishes an error-free system. Results and remaining external requirements are recorded in `backend/README.md` and the generated local audit report.
