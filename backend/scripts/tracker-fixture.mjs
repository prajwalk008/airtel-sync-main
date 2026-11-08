import { createTrackerServer } from '../../src/server.js';
const [file, port] = process.argv.slice(2);
createTrackerServer({ ordersFile: file, apiKey: 'integration-key' }).listen(Number(port), '127.0.0.1');
