import { createServer } from 'node:http';
import { randomUUID } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
import { createAdvisor } from './advisor.js';
import { createMetaClient, extractMessages, validSignature } from './channel.js';
import { createEngine } from './engine.js';

export async function createWhatsAppServer({ env = process.env, file, advisor, meta } = {}) {
  const live = env.WHATSAPP_MODE === 'live';
  if (!['demo', 'live', undefined].includes(env.WHATSAPP_MODE)) throw new Error('WHATSAPP_MODE must be demo or live');
  if (live) {
    for (const name of ['WHATSAPP_GRAPH_VERSION', 'WHATSAPP_PHONE_NUMBER_ID', 'WHATSAPP_ACCESS_TOKEN', 'WHATSAPP_APP_SECRET', 'WHATSAPP_VERIFY_TOKEN']) if (!env[name]) throw new Error(`Missing ${name}`);
    if (!/^v\d+\.\d+$/.test(env.WHATSAPP_GRAPH_VERSION)) throw new Error('Invalid Graph API version');
  }
  const engine = await createEngine({
    file: file || fileURLToPath(new URL('./.runtime/state.json', import.meta.url)),
    advisor: advisor || createAdvisor({ url: env.ADVISOR_TURN_URL, apiKey: env.ADVISOR_API_KEY }),
    meta: meta || (live ? createMetaClient({ version: env.WHATSAPP_GRAPH_VERSION, token: env.WHATSAPP_ACCESS_TOKEN, phoneNumberId: env.WHATSAPP_PHONE_NUMBER_ID }) : undefined)
  });
  const json = (res, code, value) => { res.writeHead(code, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' }); res.end(JSON.stringify(value)); };
  const server = createServer(async (req, res) => {
    const url = new URL(req.url, 'http://localhost');
    try {
      if (req.method === 'GET' && url.pathname === '/health') return json(res, 200, { status: 'ok', mode: live ? 'live' : 'demo', advisor: env.ADVISOR_TURN_URL ? 'remote' : 'sample' });
      if (req.method === 'GET' && url.pathname === '/' && !live) {
        res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' });
        return res.end(await readFile(new URL('./preview.html', import.meta.url)));
      }
      if (live && req.method === 'GET' && url.pathname === '/webhooks/whatsapp') {
        if (url.searchParams.get('hub.mode') === 'subscribe' && url.searchParams.get('hub.verify_token') === env.WHATSAPP_VERIFY_TOKEN) { res.writeHead(200, { 'Content-Type': 'text/plain' }); return res.end(url.searchParams.get('hub.challenge') || ''); }
        return json(res, 403, { error: 'Verification failed' });
      }
      const webhook = live && req.method === 'POST' && url.pathname === '/webhooks/whatsapp';
      const demo = !live && req.method === 'POST' && url.pathname === '/demo/turn';
      if (!webhook && !demo) return json(res, 404, { error: 'Not found' });
      if (demo && req.headers.origin && req.headers.origin !== `http://${req.headers.host}`) return json(res, 403, { error: 'Origin not allowed' });
      const chunks = []; let size = 0;
      for await (const chunk of req) { size += chunk.length; if (size > (webhook ? 1_000_000 : 9_000_000)) { json(res, 413, { error: 'Request too large' }); return; } chunks.push(chunk); }
      const raw = Buffer.concat(chunks);
      if (webhook && !validSignature(raw, req.headers['x-hub-signature-256'], env.WHATSAPP_APP_SECRET)) return json(res, 401, { error: 'Invalid signature' });
      let payload;
      try { payload = JSON.parse(raw.toString()); } catch { return json(res, 400, { error: 'Invalid JSON' }); }
      if (webhook) {
        await engine.enqueue(extractMessages(payload, env.WHATSAPP_PHONE_NUMBER_ID));
        json(res, 200, { received: true });
        void engine.pump().catch(() => console.error('WhatsApp worker failed; pending work will retry.'));
        return;
      }
      if (!/^demo-[a-f0-9-]{36}$/.test(payload.customerId || '') || !payload.input || typeof payload.input !== 'object') return json(res, 400, { error: 'Invalid demo turn' });
      // Preview callers cannot ask the service to fetch arbitrary media IDs.
      delete payload.input.mediaId;
      return json(res, 200, await engine.demo({ id: randomUUID(), customerId: payload.customerId, input: payload.input }));
    } catch { if (!res.headersSent) json(res, 502, { error: 'Unable to process the answer. Please retry.' }); else res.end(); }
  });
  let timer;
  server.on('listening', () => { if (live) { timer = setInterval(() => void engine.pump().catch(() => console.error('WhatsApp worker failed.')), 1000); timer.unref(); } });
  server.on('close', () => clearInterval(timer));
  server.requestTimeout = 60_000;
  return server;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const server = await createWhatsAppServer();
  const port = Number(process.env.WHATSAPP_PORT || 3002);
  const host = process.env.WHATSAPP_HOST || '127.0.0.1';
  server.listen(port, host, () => console.log(`WhatsApp ${process.env.WHATSAPP_MODE || 'demo'} service: http://${host}:${port}`));
}
