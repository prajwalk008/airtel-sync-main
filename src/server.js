import { createServer } from 'node:http';
import { randomUUID } from 'node:crypto';
import { readFile, writeFile } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const rootDir = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const dataFile = resolve(rootDir, 'data', 'orders.json');

const statusDetails = {
  order_confirmed: {
    title: 'Order confirmed',
    description: 'Your selected services are reserved and we have started onboarding.',
    nextAction: 'We will review your business verification details.'
  },
  kyc_in_review: {
    title: 'Verification in progress',
    description: 'We are checking your submitted business documents.',
    nextAction: 'No action is needed right now.'
  },
  kyc_action_required: {
    title: 'We need one update from you',
    description: 'A document or business detail needs your attention.',
    nextAction: 'Complete the requested update so we can continue.'
  },
  kyc_verified: {
    title: 'Business verified',
    description: 'Your business verification is complete.',
    nextAction: 'We will now prepare your connection.'
  },
  provisioning: {
    title: 'Connection is being prepared',
    description: 'We are arranging the network and installation work.',
    nextAction: 'We will notify you when an installation visit is scheduled.'
  },
  installation_scheduled: {
    title: 'Installation scheduled',
    description: 'An engineer visit is booked for your location.',
    nextAction: 'Please keep a representative available at the installation address.'
  },
  activated: {
    title: 'Services active',
    description: 'Your selected business services are ready to use.',
    nextAction: 'You are all set.'
  },
  cancelled: {
    title: 'Order closed',
    description: 'This order is no longer being processed.',
    nextAction: 'Contact support if you would like to restart your order.'
  }
};

const allowedStatuses = new Set(Object.keys(statusDetails));

function sendJson(response, statusCode, body) {
  response.writeHead(statusCode, {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store'
  });
  response.end(JSON.stringify(body));
}

async function readBody(request) {
  let body = '';
  for await (const chunk of request) {
    body += chunk;
    if (body.length > 64_000) throw new Error('Request body is too large.');
  }
  if (!body) return {};
  try {
    return JSON.parse(body);
  } catch {
    throw new Error('Request body must be valid JSON.');
  }
}

async function loadOrders(ordersFile = dataFile) {
  return JSON.parse(await readFile(ordersFile, 'utf8'));
}

async function saveOrders(orders, ordersFile = dataFile) {
  await writeFile(ordersFile, `${JSON.stringify(orders, null, 2)}\n`, 'utf8');
}

function currentEvent(order) {
  return order.events.at(-1);
}

function customerView(order) {
  const latest = currentEvent(order);
  const details = statusDetails[latest.status];
  return {
    orderId: order.id,
    businessName: order.customer.businessName,
    preferredLanguage: order.customer.preferredLanguage,
    bundle: order.bundle,
    currentStatus: {
      code: latest.status,
      title: details.title,
      description: latest.message || details.description,
      nextAction: latest.actionRequired || details.nextAction,
      updatedAt: latest.occurredAt
    },
    expectedActivationDate: order.installation.expectedActivationDate,
    timeline: order.events.map((event) => ({
      code: event.status,
      title: statusDetails[event.status].title,
      message: event.message || statusDetails[event.status].description,
      occurredAt: event.occurredAt,
      actionRequired: event.actionRequired || null
    })),
    supportReference: order.id
  };
}

function validateOrderInput(order) {
  if (!order.customer?.businessName || !order.customer?.contactName || !order.customer?.mobile) {
    return 'customer.businessName, customer.contactName, and customer.mobile are required.';
  }
  if (!order.bundle?.name || !Number.isFinite(order.bundle?.monthlyPriceInr)) {
    return 'bundle.name and numeric bundle.monthlyPriceInr are required.';
  }
  return null;
}

function isInternalRequest(request) {
  const expectedKey = process.env.TRACKER_API_KEY;
  return !expectedKey || request.headers['x-tracker-api-key'] === expectedKey;
}

export function createTrackerServer({ ordersFile = dataFile } = {}) {
  return createServer(async (request, response) => {
    try {
      const url = new URL(request.url, `http://${request.headers.host || 'localhost'}`);
      const parts = url.pathname.split('/').filter(Boolean);

      if (request.method === 'GET' && url.pathname === '/health') {
        return sendJson(response, 200, { status: 'ok' });
      }

      if (request.method === 'GET' && url.pathname === '/v1/orders') {
        const orders = await loadOrders(ordersFile);
        return sendJson(response, 200, { orders });
      }

      if (parts[0] === 'v1' && parts[1] === 'orders' && parts[2]) {
        const orderId = decodeURIComponent(parts[2]);
        const orders = await loadOrders(ordersFile);
        const index = orders.findIndex((order) => order.id === orderId);
        if (index === -1) return sendJson(response, 404, { error: 'Order not found.' });

        if (request.method === 'GET' && parts.length === 3) {
          return sendJson(response, 200, { order: orders[index] });
        }

        if (request.method === 'GET' && parts[3] === 'tracker' && parts.length === 4) {
          return sendJson(response, 200, { tracker: customerView(orders[index]) });
        }

        if (request.method === 'POST' && parts[3] === 'events' && parts.length === 4) {
          if (!isInternalRequest(request)) return sendJson(response, 401, { error: 'Invalid tracker API key.' });
          const input = await readBody(request);
          if (!allowedStatuses.has(input.status)) {
            return sendJson(response, 400, { error: `status must be one of: ${[...allowedStatuses].join(', ')}` });
          }
          const event = {
            status: input.status,
            occurredAt: input.occurredAt || new Date().toISOString(),
            ...(input.message ? { message: input.message } : {}),
            ...(input.actionRequired ? { actionRequired: input.actionRequired } : {})
          };
          orders[index].events.push(event);
          orders[index].updatedAt = event.occurredAt;
          if (input.expectedActivationDate !== undefined) {
            orders[index].installation.expectedActivationDate = input.expectedActivationDate;
          }
          await saveOrders(orders, ordersFile);
          return sendJson(response, 201, { order: orders[index], tracker: customerView(orders[index]) });
        }
      }

      if (request.method === 'POST' && url.pathname === '/v1/orders') {
        if (!isInternalRequest(request)) return sendJson(response, 401, { error: 'Invalid tracker API key.' });
        const input = await readBody(request);
        const validationError = validateOrderInput(input);
        if (validationError) return sendJson(response, 400, { error: validationError });
        const now = new Date().toISOString();
        const order = {
          id: input.id || `ORD-${randomUUID().slice(0, 8).toUpperCase()}`,
          customer: input.customer,
          bundle: { ...input.bundle, items: input.bundle.items || [] },
          installation: {
            address: input.installation?.address || null,
            expectedActivationDate: input.installation?.expectedActivationDate || null
          },
          events: [{
            status: 'order_confirmed',
            occurredAt: now,
            message: 'Your order and chosen bundle are confirmed.'
          }],
          createdAt: now,
          updatedAt: now
        };
        const orders = await loadOrders(ordersFile);
        if (orders.some((existing) => existing.id === order.id)) {
          return sendJson(response, 409, { error: 'An order with this id already exists.' });
        }
        orders.push(order);
        await saveOrders(orders, ordersFile);
        return sendJson(response, 201, { order, tracker: customerView(order) });
      }

      return sendJson(response, 404, { error: 'Route not found.' });
    } catch (error) {
      return sendJson(response, 400, { error: error.message || 'Unexpected request error.' });
    }
  });
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const port = Number(process.env.PORT || 3001);
  createTrackerServer().listen(port, () => {
    console.log(`Tracker service running on http://localhost:${port}`);
  });
}
