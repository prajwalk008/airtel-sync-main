import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { loadEnvFile } from 'node:process';
if (existsSync('backend/.env')) loadEnvFile('backend/.env');
const python = process.platform === 'win32' ? 'backend/.venv/Scripts/python.exe' : 'backend/.venv/bin/python';
if (!existsSync(python)) { console.error('Create backend/.venv and install backend/requirements.txt first.'); process.exit(1); }
const children = [];
let stopping = false;
function stop() { if (stopping) return; stopping = true; for (const child of children) child.kill(); }
function start(command, args, env = {}) {
  const child = spawn(command, args, { stdio:'inherit', windowsHide:true, env:{...process.env,...env} });
  children.push(child);
  child.on('error', error => { console.error(error.message); stop(); process.exitCode = 1; });
  child.on('exit', code => { if (!stopping) { stop(); process.exitCode = code || 1; } });
}
const key = process.env.INTERNAL_API_KEY || 'local-dev-only-change-me';
start(process.execPath, ['src/server.js'], {PORT:'3001'});
start(resolve(python), ['-m','uvicorn','backend.main:app','--host',process.env.BACKEND_HOST||'0.0.0.0','--port','8000']);
start(process.execPath, ['--env-file-if-exists=whatsapp/.env','whatsapp/server.js'], { WHATSAPP_MODE:'demo', WHATSAPP_PORT:'3002', ADVISOR_TURN_URL:'http://127.0.0.1:8000/advisor/turn', ADVISOR_API_KEY:key });
process.on('SIGINT', stop); process.on('SIGTERM', stop);
console.log('Shared API: http://127.0.0.1:8000/docs | Tracker: :3001 | WhatsApp preview: http://127.0.0.1:3002');
console.log('Start web separately: cd web; npm run dev — use the existing AI business partner screen.');
