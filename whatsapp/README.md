# WhatsApp business advisor interface

The shared advisor backend is now implemented. `npm run dev:stack` connects this simulator to it automatically. See [backend/README.md](../backend/README.md) for setup; the shared pipeline adds consent and answer-confirmation steps before issuing recommendations.

Separate Node service on port **3002** (Tracker stays on 3001). No additional npm dependencies. Node 22.16+ is recommended.

## Try the sample conversation

From `X:\codes\projects2\airtel_sync`:

```powershell
npm run whatsapp
```

Open http://127.0.0.1:3002. The browser preview supports options, typed answers and microphone recording. Allow microphone access when requested. Each page load starts a new demo customer; Restart resets that customer's questionnaire. This is a local simulator, not a WhatsApp Web integration.

Sample questions collect business type, team size, city/postcode, problem, budget and existing tools. All questions accept custom text or audio even when options are present. Sample mode accepts audio and moves to the next question; **it does not transcribe, interpret or validate the spoken answer**. No products, quotes or orders are generated.

## Connect your friend's advisor API

Copy `whatsapp/.env.example` to `whatsapp/.env`. Set `ADVISOR_TURN_URL` to the full POST endpoint and optionally set `ADVISOR_API_KEY`. Restart the service. Both preview and live WhatsApp then use the same adapter.

The interface makes one request to get the next question **and its answer options together**. It doesn't hardcode the remote pipeline's question sequence. The pipeline owns reasoning and speech interpretation.

Request example:

```json
{
  "eventId": "wamid.unique-incoming-message-id",
  "sessionId": "a-server-generated-uuid",
  "customerId": "919876543210",
  "channel": "whatsapp",
  "questionId": "business",
  "answer": { "type": "option", "optionId": "retail", "text": "Retail shop" },
  "history": []
}
```

On start, `questionId` and `answer` are null; `initialMessage` contains the opening text if present. The opening text is passed as context rather than assumed to answer the first question. `history` contains earlier `{questionId, question, answer}` entries.

Other answer shapes:

```json
{ "type": "text", "text": "I run a bakery with seven staff" }
```

```json
{
  "type": "audio",
  "audio": {
    "mimeType": "audio/ogg",
    "dataBase64": "BASE64_ENCODED_RECORDING"
  }
}
```

The pipeline must accept audio bytes (or route them to transcription internally). The adapter does not invent a transcript. Raw audio is sent only in the current request; earlier audio answers in `history` have `{type: "audio", mimeType, byteLength}` metadata. The pipeline should retain any needed transcript against `sessionId` and deduplicate calls by `eventId`. A retry can repeat an API call if a crash happens before the result is saved.

Response for the next question:

```json
{
  "completed": false,
  "message": "Thanks. Let's understand your team.",
  "question": {
    "id": "team",
    "text": "How many people work in your business?",
    "options": [
      { "id": "small", "label": "1–5 people" },
      { "id": "medium", "label": "6–20 people" },
      { "id": "large", "label": "21+ people" }
    ]
  }
}
```

Final response:

```json
{ "completed": true, "message": "Thank you. Here is your recommendation…" }
```

Contract constraints:

- `completed` is required. Active turns require `question`; completed turns require `message` and no question.
- Question and option IDs: 1–64 ASCII letters, digits, underscores or hyphens; option IDs must be unique within a question.
- Question text: up to 1,000 characters. Optional message: up to 4,000 characters.
- `options` must be an array: empty for an open question, 1–3 for reply buttons, 4–10 for a list. Labels: up to 20 characters. Lists and buttons both allow users to answer using ordinary text or voice.
- Questions must be answerable through text, an option or audio. This interface does not implement image/video/document upload, consent processing, checkout, order creation or human handoff.
- Audio: OGG, MP4, MPEG, AMR, AAC or WebM, up to 6 MB. WhatsApp delivers its supported formats; WebM is accepted for browser recordings. Audio codec validity is the receiving pipeline's responsibility.
- Remote requests time out after 45 seconds. Return a non-2xx response for failures; don't return a success response with an error disguised as a question.

## Connect an actual WhatsApp number

1. Create/configure a Meta developer app with WhatsApp and a test sender. Add permitted test recipients in Meta's dashboard.
2. In `.env`, set `WHATSAPP_MODE=live`, the Graph API version shown in your Meta dashboard, phone number ID, access token, **Meta app secret** and a randomly chosen webhook verify token. App secret and verify token have different purposes.
3. Run `npm run whatsapp`. Expose port 3002 through a public HTTPS deployment or a development tunnel. Keep one process running against the session file.
4. Set Meta's callback URL to `https://YOUR-HOST/webhooks/whatsapp` and the same verify token. Subscribe to WhatsApp `messages` events.
5. Send `/start` or a greeting from an allowed tester. Choose a reply button, type custom text, or use WhatsApp's native microphone to send a voice note.

`GET /webhooks/whatsapp` handles verification; `POST /webhooks/whatsapp` checks the raw-body `X-Hub-Signature-256` HMAC with the app secret. Only messages for the configured sender are processed. Delivery/status events are ignored. Image/video/other attachments produce a supported-input reminder without advancing the questionnaire. Old option replies do not advance the current question.

The local preview and `/demo/turn` are disabled in live mode. `/health` reports mode and whether the advisor is sample or remote. Never put the access token in the browser, mobile app or repository. `.env` and runtime files are ignored by Git.

## Persistence and retry limits

Sessions, incoming message IDs, pending jobs and prepared outgoing messages persist in `whatsapp/.runtime/state.json`. Webhooks are acknowledged after the incoming job is saved; the worker then calls the advisor and sends replies. Failed work retries up to five times with backoff; exhausted jobs have `status: "failed"` in the local file. Restarting the process resumes pending jobs. Duplicate incoming IDs are ignored.

This JSON store is for a **single local prototype process**. It contains customer answers and identifiers; run it in a controlled environment. No automatic retention cleanup or operations dashboard is included. Move to a database/queue with retention controls before public rollout. Do not run multiple instances sharing the file. A network interruption after Meta accepted a reply can result in a duplicate outgoing message; delivery is not exactly-once. In-flight jobs aren't gracefully drained on process shutdown.

The service replies to incoming customer messages; proactive notifications and approved template messages are outside this prototype. Real Meta delivery, credentials and audio codecs must be checked with your test sender before claiming an end-to-end WhatsApp demo.

## Verification

```powershell
npm test
```

Tests cover questionnaire progression, stale buttons, unsupported media, audio forwarding, restart recovery, webhook verification/signatures, duplicate incoming deliveries, retries and the Meta HTTP payloads. Meta requests are mocked; these tests don't prove live account connectivity.

References: [Meta's developer hub](https://whatsappbusiness.com/developers/developer-hub/), [Meta's WhatsApp API collection](https://www.postman.com/meta/whatsapp-business-platform/documentation/wlk6lh4/whatsapp-cloud-api).
