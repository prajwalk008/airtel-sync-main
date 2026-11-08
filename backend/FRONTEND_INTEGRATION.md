# Advisor integrated into the original frontend

The separate journey page, styling and banner were removed. `web/src/App.css` and the original homepage/login/service layouts are preserved. The existing AI business partner screen now renders `web/src/AdvisorChat.tsx`; the original Android Advisor screen renders `mobile/AdvisorChat.tsx`. Safe area handling and the two-column Android service layout are retained.

Both clients import `shared/advisor-client.ts`. They create a matching demo authenticated backend session, explicitly record consent, send the opening problem/budget/registration context to `/sessions`, and send subsequent text/option replies to `/sessions/{id}/turn`. Session state, confirmation, eligibility, tax and product prices are server-owned. The old frontend `suggest()` functions were removed. A repeated network retry uses the same event ID for the same pending answer.

The chat shows backend questions, selectable answer options, pending/error states, confirmation requests and recommendation cards in the existing visual treatment. The opening budget is retained and not asked again. Going to other screens does not unmount the chat. Starting another conversation reuses the current demo authentication instead of requesting another OTP unnecessarily.

## AI setup

Put the following in the ignored `backend/.env` file and restart `npm run dev:stack`:

```dotenv
OPENAI_API_KEY=YOUR_PRIVATE_PROVIDER_KEY
OPENAI_MODEL=YOUR_AVAILABLE_RESPONSES_MODEL
```

The customer must allow optional AI processing in the chat before model calls occur. The pipeline uses structured model interpretation of free-form business answers and structured per-product explanations, validated against allowed product IDs. Numeric/currency claims, unknown products and guarantee/discount claims in generated explanations are discarded. The model does not set prices. Provider failures use backend parsing or ask for clarification. Without credentials the backend uses deterministic fallback; live LLM behaviour has not been claimed tested.

All backend modules from the earlier phase remain usable. No replacement quote/KYC website is introduced. Integrating those APIs into additional original app screens is separate from the completed advisor integration.

## Running

1. At the root: `npm run dev:stack`.
2. Website: `cd web`, `npm run dev`, open `/` and select **Speak with AI business partner**.
3. Android: `cd mobile`, `npm start`, open Expo Go on the same network. The backend host is derived from Expo's development host; override with `EXPO_PUBLIC_API_URL` in `mobile/.env` for another server. The stack listens on `0.0.0.0:8000` for LAN testing; set `BACKEND_HOST=127.0.0.1` for computer-only use.

The web proxy is `/api` → `127.0.0.1:8000`; no internal or model secret is exposed to frontend code. Prototype phone authentication is explicitly mocked, as before.

## Verification

- Backend suite: 17 passed, including original-frontend context, Android session compatibility and model-output price/product safeguards. One existing Starlette/AnyIO deprecation warning.
- Website build/lint passed.
- Android typecheck/lint passed; Metro/Hermes Android bundle export passed with the shared client.
- `node backend/scripts/verify_frontend_client.mjs`: actual shared client used by the web and Android screens completed conversations against the running Vite proxy/shared API and returned catalogue-priced recommendations. This verifies HTTP integration, not physical-device UI interaction.
- Original `App.css` has no changes; the separate journey component and CSS are deleted. Current browser-control tooling failed to connect, so a new visual walkthrough is not asserted.
