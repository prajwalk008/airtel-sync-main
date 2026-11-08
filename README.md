# Airtel Order Tracker Service

The website and Android UI prototype are documented in [FRONTEND.md](FRONTEND.md).

A small prototype service that owns the order-status timeline after checkout. The Advisor, checkout, KYC, and provisioning systems publish lifecycle events to it; the main app reads the resulting order or customer-safe Tracker view.

## Run

Requires Node.js 22+.

```powershell
npm start
```

The service runs at `http://localhost:3001`.

```powershell
npm test
```

## API boundary

| Caller | Endpoint | Purpose |
| --- | --- | --- |
| Main service / KYC / operations | `POST /v1/orders` | Create an order once checkout succeeds. |
| Main service / KYC / operations | `POST /v1/orders/:orderId/events` | Append a trusted lifecycle event. |
| Main service | `GET /v1/orders/:orderId` | Retrieve the internal order record. |
| Customer-facing main app | `GET /v1/orders/:orderId/tracker` | Retrieve the customer-safe status view. |
| Operations | `GET /v1/orders` | List prototype orders. |
| Platform | `GET /health` | Liveness check. |

The customer-facing endpoint deliberately excludes the mobile number and contact name.

## Statuses

`order_confirmed` → `kyc_in_review` → `kyc_verified` → `provisioning` → `installation_scheduled` → `activated`

`kyc_action_required` and `cancelled` are exception states. The service lets operations publish status events, rather than letting the customer app mutate an order directly.

## Example

```powershell
Invoke-RestMethod http://localhost:3001/v1/orders/ORD-DEMO-003/tracker

Invoke-RestMethod http://localhost:3001/v1/orders/ORD-DEMO-002/events -Method Post -ContentType 'application/json' -Body '{
  "status": "installation_scheduled",
  "message": "Engineer visit confirmed for 18 June, 10 AM–12 PM.",
  "expectedActivationDate": "2026-06-18"
}'
```

Set `TRACKER_API_KEY` before deployment to require an `X-Tracker-Api-Key` header on the two write endpoints. In this first local prototype, data persists in `data/orders.json`; a production deployment should replace that file store with a transactional database and authenticated service-to-service identity.
