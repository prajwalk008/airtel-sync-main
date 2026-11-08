import test from 'node:test';
import assert from 'node:assert/strict';
import { copyFile, mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createTrackerServer } from '../src/server.js';

let server;
let baseUrl;
let tempDirectory;

test.before(async () => {
  tempDirectory = await mkdtemp(join(tmpdir(), 'airtel-tracker-test-'));
  const ordersFile = join(tempDirectory, 'orders.json');
  const seedFile = fileURLToPath(new URL('../data/orders.json', import.meta.url));
  await copyFile(seedFile, ordersFile);
  server = createTrackerServer({ ordersFile });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  baseUrl = `http://127.0.0.1:${server.address().port}`;
});

test.after(async () => {
  await new Promise((resolve) => server.close(resolve));
  await rm(tempDirectory, { recursive: true, force: true });
});

test('returns a customer-safe tracker view', async () => {
  const response = await fetch(`${baseUrl}/v1/orders/ORD-DEMO-003/tracker`);
  assert.equal(response.status, 200);
  const { tracker } = await response.json();
  assert.equal(tracker.currentStatus.code, 'kyc_action_required');
  assert.equal(tracker.customer, undefined);
  assert.match(tracker.currentStatus.nextAction, /Upload/);
});

test('creates an order and accepts a lifecycle event', async () => {
  const createResponse = await fetch(`${baseUrl}/v1/orders`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      id: 'ORD-TEST-001',
      customer: { businessName: 'Test CA Firm', contactName: 'Test Owner', mobile: '9000000000', preferredLanguage: 'English' },
      bundle: { name: 'Test Bundle', monthlyPriceInr: 1999 },
      installation: { address: 'Test Address', expectedActivationDate: '2026-07-20' }
    })
  });
  assert.equal(createResponse.status, 201);

  const eventResponse = await fetch(`${baseUrl}/v1/orders/ORD-TEST-001/events`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status: 'kyc_in_review' })
  });
  assert.equal(eventResponse.status, 201);
  const { tracker } = await eventResponse.json();
  assert.equal(tracker.currentStatus.code, 'kyc_in_review');
});
