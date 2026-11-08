import { createHmac, timingSafeEqual } from 'node:crypto';

export const MAX_AUDIO_BYTES = 6 * 1024 * 1024;
export const audioTypes = new Set(['audio/ogg', 'audio/mp4', 'audio/mpeg', 'audio/amr', 'audio/aac', 'audio/webm']);
export function normalizeMime(mime = '') { return mime.split(';')[0].trim().toLowerCase(); }

export function validSignature(raw, signature, secret) {
  if (!secret || !/^sha256=[a-f0-9]{64}$/.test(signature || '')) return false;
  const expected = createHmac('sha256', secret).update(raw).digest();
  return timingSafeEqual(expected, Buffer.from(signature.slice(7), 'hex'));
}

export function optionId(session, option) { return `${session.sessionId}:${session.revision}:${session.turn.question.id}:${option.id}`; }

export function messagesForTurn(session) {
  const { turn } = session;
  const messages = [];
  if (turn.message) messages.push({ type: 'text', text: { body: turn.message } });
  if (!turn.question) return messages;
  const q = turn.question;
  const body = `${q.text}\n\nChoose an option, type your answer, or send a voice note.`;
  if (!q.options.length) messages.push({ type: 'text', text: { body } });
  else if (q.options.length <= 3) messages.push({ type: 'interactive', interactive: {
    type: 'button', body: { text: body }, action: { buttons: q.options.map(o => ({ type: 'reply', reply: { id: optionId(session, o), title: o.label } })) }
  } });
  else messages.push({ type: 'interactive', interactive: {
    type: 'list', body: { text: body }, action: { button: 'Choose an answer', sections: [{ title: 'Answers', rows: q.options.map(o => ({ id: optionId(session, o), title: o.label })) }] }
  } });
  return messages;
}

export function extractMessages(payload, phoneNumberId) {
  const result = [];
  if (payload.object !== 'whatsapp_business_account') return result;
  for (const entry of payload.entry || []) for (const change of entry.changes || []) {
    if (change.field !== 'messages' || change.value?.metadata?.phone_number_id !== phoneNumberId) continue;
    for (const m of change.value.messages || []) {
      if (typeof m.id !== 'string' || !/^\d{5,20}$/.test(m.from || '')) continue;
      let input;
      if (m.type === 'text') input = { type: 'text', text: m.text?.body };
      else if (m.type === 'interactive') input = { type: 'option', optionId: m.interactive?.button_reply?.id || m.interactive?.list_reply?.id };
      else if (m.type === 'audio') input = { type: 'audio', mediaId: m.audio?.id };
      else input = { type: 'unsupported' };
      result.push({ id: m.id, customerId: m.from, input });
    }
  }
  return result;
}

export function createMetaClient({ version, token, phoneNumberId, fetchImpl = fetch }) {
  const headers = { Authorization: `Bearer ${token}` };
  const graph = `https://graph.facebook.com/${version}`;
  return {
    async audio(mediaId) {
      if (typeof mediaId !== 'string' || !/^\d+$/.test(mediaId)) throw new Error('Invalid media ID');
      const response = await fetchImpl(`${graph}/${mediaId}`, { headers, signal: AbortSignal.timeout(15_000) });
      if (!response.ok) throw new Error('Media lookup failed');
      const media = await response.json();
      const mimeType = normalizeMime(media.mime_type);
      if (!audioTypes.has(mimeType) || media.file_size > MAX_AUDIO_BYTES) throw new Error('Unsupported or oversized audio');
      const url = new URL(media.url);
      if (url.protocol !== 'https:' || !(url.hostname === 'fbsbx.com' || url.hostname.endsWith('.fbsbx.com') || url.hostname.endsWith('.facebook.com'))) throw new Error('Invalid media host');
      const download = await fetchImpl(url, { headers, redirect: 'error', signal: AbortSignal.timeout(20_000) });
      if (!download.ok) throw new Error('Media download failed');
      const chunks = []; let size = 0;
      for await (const chunk of download.body) {
        size += chunk.length;
        if (size > MAX_AUDIO_BYTES) { await download.body.cancel().catch(() => {}); throw new Error('Audio too large'); }
        chunks.push(chunk);
      }
      if (!size) throw new Error('Empty audio');
      return { mimeType, dataBase64: Buffer.concat(chunks).toString('base64') };
    },
    async send(to, message) {
      const response = await fetchImpl(`${graph}/${phoneNumberId}/messages`, {
        method: 'POST', headers: { ...headers, 'Content-Type': 'application/json' }, signal: AbortSignal.timeout(20_000),
        body: JSON.stringify({ messaging_product: 'whatsapp', to, ...message })
      });
      if (!response.ok) throw new Error('WhatsApp delivery failed');
      return response.json();
    }
  };
}
