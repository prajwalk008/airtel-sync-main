import test from 'node:test';
import assert from 'node:assert/strict';
import { createHmac } from 'node:crypto';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createAdvisor, validateTurn } from '../whatsapp/advisor.js';
import { createEngine } from '../whatsapp/engine.js';
import { extractMessages, messagesForTurn, optionId, validSignature, createMetaClient } from '../whatsapp/channel.js';
import { createWhatsAppServer } from '../whatsapp/server.js';

async function fixture(t, extra = {}) {
  const dir = await mkdtemp(join(tmpdir(), 'accel-whatsapp-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  return { file: join(dir, 'state.json'), advisor: createAdvisor(), ...extra };
}

test('questionnaire accepts choices, custom text and audio; rejects stale options and unsupported media', async t => {
  const options = await fixture(t); const engine = await createEngine(options);
  let n = 0; const turn = input => engine.demo({ id: `event-${n++}`, customerId: '919999999999', input });
  let result = await turn({ type: 'text', text: 'Hello' });
  const firstId = optionId(result.session, result.session.turn.question.options[0]);
  result = await turn({ type: 'unsupported' }); assert.equal(result.session.turn.question.id, 'business');
  result = await turn({ type: 'option', optionId: firstId }); assert.equal(result.session.turn.question.id, 'team');
  result = await turn({ type: 'option', optionId: firstId }); assert.equal(result.session.history.length, 1);
  result = await turn({ type: 'text', text: 'We have seven staff' }); assert.equal(result.session.turn.question.id, 'location');
  result = await turn({ type: 'audio', audio: { mimeType: 'image/png', dataBase64: 'dGVzdA==' } }); assert.equal(result.session.turn.question.id, 'location');
  result = await turn({ type: 'audio', audio: { mimeType: 'audio/ogg; codecs=opus', dataBase64: 'dGVzdA==' } });
  assert.equal(result.session.turn.question.id, 'problem'); assert.equal(result.session.history[2].answer.type, 'audio');
  assert.equal(result.session.history[2].answer.dataBase64, undefined);
  const restarted = await createEngine(options);
  result = await restarted.demo({ id: 'after-restart', customerId: '919999999999', input: { type: 'text', text: 'Internet drops' } });
  assert.equal(result.session.turn.question.id, 'budget');
  result = await restarted.demo({ id: 'restart-command', customerId: '919999999999', input: { type: 'text', text: '/restart' } });
  assert.equal(result.session.turn.question.id, 'business'); assert.equal(result.session.history.length, 0);
  result = await restarted.demo({ id: 'stale-before-restart', customerId: '919999999999', input: { type: 'option', optionId: firstId } });
  assert.equal(result.session.turn.question.id, 'business'); assert.equal(result.session.history.length, 0);
  for (let i = 0; i < 6; i++) result = await restarted.demo({ id: `finish-${i}`, customerId: '919999999999', input: { type: 'text', text: 'Sample answer' } });
  assert.equal(result.session.turn.completed, true); assert.equal(result.session.history.length, 6);
});

test('engine forwards voice bytes and question context to a pluggable pipeline', async t => {
  const turns = [];
  const options = await fixture(t, { advisor: async turn => { turns.push(turn); return createAdvisor()(turn); } });
  const engine = await createEngine(options);
  const started = await engine.demo({ id: 'start', customerId: 'customer', input: { type: 'text', text: 'Hello, I own a shop' } });
  await engine.demo({ id: 'choice', customerId: 'customer', input: { type: 'option', optionId: optionId(started.session, started.session.turn.question.options[0]) } });
  await engine.demo({ id: 'voice', customerId: 'customer', input: { type: 'audio', audio: { mimeType: 'audio/ogg', dataBase64: 'dGVzdA==' } } });
  assert.equal(turns[0].initialMessage, 'Hello, I own a shop');
  assert.equal(turns[1].answer.optionId, 'retail');
  assert.equal(turns[2].questionId, 'team'); assert.equal(turns[2].answer.audio.dataBase64, 'dGVzdA==');
  assert.equal(turns[2].history[0].answer.text, 'Retail shop');
});

test('remote advisor receives current audio and selected options; validates response limits', async () => {
  let received;
  const advisor = createAdvisor({ url: 'https://advisor.example/turn', apiKey: 'secret', fetchImpl: async (url, init) => { received = JSON.parse(init.body); assert.equal(init.headers.Authorization, 'Bearer secret'); return Response.json({ completed: false, question: { id: 'next', text: 'Next?', options: [] } }); } });
  await advisor({ answer: { type: 'audio', audio: { mimeType: 'audio/ogg', dataBase64: 'dGVzdA==' } } });
  assert.equal(received.answer.audio.dataBase64, 'dGVzdA==');
  assert.throws(() => validateTurn({ completed: false, question: { id: 'q', text: 'Q?', options: [{ id: 'a', label: 'a'.repeat(21) }] } }));
  const session = { revision: 1, turn: { question: { id: 'q', text: 'Q?', options: Array.from({ length: 4 }, (_, i) => ({ id: `o${i}`, label: `Option ${i}` })) } } };
  assert.equal(messagesForTurn(session)[0].interactive.type, 'list');
});

test('durable queue deduplicates webhook retries and resumes prepared replies after restart', async t => {
  let calls = 0, deliveries = 0, fail = true;
  const options = await fixture(t, { advisor: async x => { calls++; return createAdvisor()(x); }, meta: { send: async () => { deliveries++; if (fail) throw new Error('offline'); } } });
  const engine = await createEngine(options);
  const event = { id: 'wamid.1', customerId: '919999999999', input: { type: 'text', text: 'hi' } };
  await engine.enqueue([event, event]); await engine.pump(); assert.equal(calls, 1);
  fail = false;
  // Move persisted backoff into the past without waiting in a test.
  const { readFile, writeFile } = await import('node:fs/promises');
  const state = JSON.parse(await readFile(options.file)); state.jobs[event.id].nextAttempt = 0;
  await writeFile(options.file, JSON.stringify(state));
  const recovered = await createEngine(options); await recovered.pump(); await recovered.enqueue([event]); await recovered.pump();
  assert.equal(calls, 1); assert.equal(deliveries, 2);
});

test('webhook verifies challenge/signatures and ignores status-only updates and other business numbers', async t => {
  const opts = await fixture(t);
  const env = { WHATSAPP_MODE: 'live', WHATSAPP_GRAPH_VERSION: 'v23.0', WHATSAPP_PHONE_NUMBER_ID: '123', WHATSAPP_ACCESS_TOKEN: 'token', WHATSAPP_APP_SECRET: 'secret', WHATSAPP_VERIFY_TOKEN: 'verify' };
  const server = await createWhatsAppServer({ ...opts, env, meta: { send: async () => {} } });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  t.after(() => new Promise(resolve => server.close(resolve)));
  const base = `http://127.0.0.1:${server.address().port}`;
  const challenge = await fetch(`${base}/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=verify&hub.challenge=abc`);
  assert.equal(await challenge.text(), 'abc');
  assert.equal((await fetch(`${base}/demo/turn`, { method: 'POST' })).status, 404);
  const payload = { object: 'whatsapp_business_account', entry: [{ changes: [{ field: 'messages', value: { metadata: { phone_number_id: '123' }, messages: [{ id: 'wamid.2', from: '919999999999', type: 'audio', audio: { id: '321' } }] } }] }] };
  assert.equal(extractMessages(payload, '123')[0].input.mediaId, '321'); assert.equal(extractMessages(payload, 'other').length, 0);
  assert.equal(extractMessages({ object: 'whatsapp_business_account', entry: [{ changes: [{ field: 'messages', value: { metadata: { phone_number_id: '123' }, statuses: [] } }] }] }, '123').length, 0);
  const raw = JSON.stringify({ object: 'whatsapp_business_account', entry: [] }); const signature = 'sha256=' + createHmac('sha256', 'secret').update(raw).digest('hex');
  assert.equal(validSignature(Buffer.from(raw), signature, 'secret'), true); assert.equal(validSignature(Buffer.from(raw+' '), signature, 'secret'), false);
  assert.equal((await fetch(`${base}/webhooks/whatsapp`, { method: 'POST', body: raw })).status, 401);
  assert.equal((await fetch(`${base}/webhooks/whatsapp`, { method: 'POST', headers: { 'x-hub-signature-256': signature }, body: raw })).status, 200);
});

test('Meta adapter downloads audio and sends interactive replies using authorized API calls', async () => {
  const requests = [];
  const client = createMetaClient({ version: 'v23.0', token: 'token', phoneNumberId: '123', fetchImpl: async (url, init) => { requests.push({ url: String(url), ...init }); if (String(url).endsWith('/messages')) return Response.json({ messages: [{ id: 'sent' }] }); if (String(url).includes('fbsbx')) return new Response(Buffer.from('audio')); return Response.json({ mime_type: 'audio/ogg', file_size: 5, url: 'https://lookaside.fbsbx.com/audio' }); } });
  assert.equal((await client.audio('456')).dataBase64, Buffer.from('audio').toString('base64'));
  await client.send('919999999999', { type: 'text', text: { body: 'Hi' } });
  assert.equal(requests[1].headers.Authorization, 'Bearer token'); assert.equal(JSON.parse(requests[2].body).messaging_product, 'whatsapp');
});
