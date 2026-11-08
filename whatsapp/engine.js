import { randomUUID } from 'node:crypto';
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import { dirname } from 'node:path';
import { audioTypes, MAX_AUDIO_BYTES, messagesForTurn, normalizeMime, optionId } from './channel.js';

const textMessage = body => ({ type: 'text', text: { body } });
export async function createEngine({ file, advisor, meta }) {
  let state = { sessions: {}, jobs: {} };
  try { state = JSON.parse(await readFile(file, 'utf8')); } catch (e) { if (e.code !== 'ENOENT') throw e; }
  await mkdir(dirname(file), { recursive: true });
  async function save() { await writeFile(`${file}.tmp`, JSON.stringify(state)); await rename(`${file}.tmp`, file); }
  let tail = Promise.resolve();
  function exclusive(fn) { const task = tail.then(fn); tail = task.catch(() => {}); return task; }

  async function prepare(event) {
    const input = event.input;
    const previous = state.sessions[event.customerId];
    const reply = body => ({ session: previous, outgoing: [textMessage(body)] });
    if (input.type === 'unsupported') return reply('Please choose an answer, type a message, or send a voice note. Images, videos and other attachments are not supported yet.');
    if (input.type === 'text' && (typeof input.text !== 'string' || !input.text.trim() || input.text.length > 4000)) return reply('Please send a text answer of up to 4,000 characters.');
    const restart = input.type === 'text' && /^\/(start|restart)$/i.test(input.text.trim());
    if (!previous || restart) {
      // The first message opens the conversation; it is not silently treated as an answer.
      const sessionId = randomUUID();
      const turn = await advisor({ eventId: event.id, sessionId, customerId: event.customerId, channel: 'whatsapp', questionId: null, answer: null, history: [], initialMessage: input.type === 'text' ? input.text : null });
      const session = { sessionId, revision: 1, turn, history: [] };
      return { session, outgoing: messagesForTurn(session) };
    }
    if (previous.turn.completed) return reply('Your business details are already collected. Type /restart to begin again.');
    const question = previous.turn.question;
    let answer;
    if (input.type === 'option') {
      const option = question.options.find(o => optionId(previous, o) === input.optionId);
      if (!option) return { session: previous, outgoing: [textMessage('Please answer the latest question. That option is from an earlier step.'), ...messagesForTurn(previous)] };
      answer = { type: 'option', optionId: option.id, text: option.label };
    } else if (input.type === 'text') answer = { type: 'text', text: input.text.trim() };
    else if (input.type === 'audio') {
      let audio;
      try { audio = input.mediaId ? await meta.audio(input.mediaId) : input.audio; }
      catch { return reply('I could not open that voice note. Please try a shorter recording or type your answer.'); }
      const mimeType = normalizeMime(audio?.mimeType);
      const data = audio?.dataBase64;
      if (!audioTypes.has(mimeType) || typeof data !== 'string' || !data.length || data.length > Math.ceil(MAX_AUDIO_BYTES / 3) * 4 || !/^[A-Za-z0-9+/]+={0,2}$/.test(data)) return reply('Please send a supported voice note of up to 6 MB, or type your answer.');
      const bytes = Buffer.from(data, 'base64');
      if (!bytes.length || bytes.length > MAX_AUDIO_BYTES || bytes.toString('base64') !== data) return reply('That recording could not be read. Please record it again or type your answer.');
      answer = { type: 'audio', audio: { mimeType, dataBase64: data } };
    } else return reply('Please choose an option, type an answer, or send a voice note.');
    const turn = await advisor({ eventId: event.id, sessionId: previous.sessionId, customerId: event.customerId, channel: 'whatsapp', questionId: question.id, answer, history: previous.history });
    // Keep audio bytes out of the local session file. The pipeline receives them in the current turn.
    const stored = answer.type === 'audio' ? { type: 'audio', mimeType: answer.audio.mimeType, byteLength: Buffer.from(answer.audio.dataBase64, 'base64').length } : answer;
    const session = { ...previous, revision: previous.revision + 1, turn, history: [...previous.history, { questionId: question.id, question: question.text, answer: stored }] };
    return { session, outgoing: messagesForTurn(session) };
  }

  return {
    demo(event) { return exclusive(async () => {
      if (state.jobs[event.id]) return state.jobs[event.id].result;
      const prepared = await prepare(event);
      if (prepared.session) state.sessions[event.customerId] = prepared.session;
      const result = prepared;
      state.jobs[event.id] = { status: 'done', result };
      await save(); return result;
    }); },
    enqueue(events) { return exclusive(async () => {
      for (const event of events) if (!Object.hasOwn(state.jobs, event.id)) state.jobs[event.id] = { event, status: 'pending', attempts: 0, sent: 0 };
      await save();
    }); },
    pump() { return exclusive(async () => {
      // One process owns this file. Process oldest jobs first and preserve per-customer order on retries.
      const blocked = new Set();
      for (const job of Object.values(state.jobs)) {
        if (job.status !== 'pending' || blocked.has(job.event.customerId)) continue;
        if ((job.nextAttempt || 0) > Date.now()) { blocked.add(job.event.customerId); continue; }
        try {
          if (!job.outgoing) {
            const prepared = await prepare(job.event);
            if (prepared.session) state.sessions[job.event.customerId] = prepared.session;
            job.outgoing = prepared.outgoing;
            await save();
          }
          while (job.sent < job.outgoing.length) { await meta.send(job.event.customerId, job.outgoing[job.sent]); job.sent++; await save(); }
          job.status = 'done'; delete job.event.input; await save();
        } catch {
          job.attempts++; job.nextAttempt = Date.now() + 5000 * job.attempts;
          job.error = 'Processing or delivery failed; check provider configuration and availability.';
          if (job.attempts >= 5) { job.status = 'failed'; delete job.event.input; }
          else blocked.add(job.event.customerId);
          await save();
        }
      }
    }); }
  };
}
