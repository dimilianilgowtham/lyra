const assert = require('node:assert/strict');
const { test, before } = require('node:test');
const { build } = require('esbuild');
const Module = require('node:module');
const path = require('node:path');
let BackendClient, TaskController;
before(async () => {
  const result = await build({ entryPoints: [path.resolve(__dirname, '../../src/modules/TaskController.js')], bundle: true, format: 'cjs', platform: 'node', write: false, define: { 'import.meta.env': '{}' } });
  const module = new Module(__filename);
  module._compile(result.outputFiles[0].text, __filename);
  ({ BackendClient, TaskController } = module.exports);
  globalThis.__taskExports = module.exports;
});
const response = (body, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => body });
test('browser session uses cookies and failed writes never report success', async () => {
  const calls = [];
  const client = new BackendClient({ fetch: async (url, options) => { calls.push({ url, options }); return url.endsWith('/api/session') ? response({ success: true }) : response({ detail: 'Denied' }, 403); }, getToken: async () => null });
  await assert.rejects(client.createTask({ prompt: 'Write a file' }), /Denied/);
  assert.equal(calls.length, 2);
  assert(calls.every(call => call.options.credentials === 'include'));
  assert(!calls.some(call => call.options.headers?.Authorization));
});
test('Electron credential goes only to the selected backend and requests are bounded', async () => {
  const calls = [];
  const client = new BackendClient({ fetch: async (url, options) => { calls.push({ url, options }); return response({ status: 'ok' }); }, getToken: async () => 'local-secret' });
  await client.health();
  assert.equal(calls.length, 1);
  assert.equal(calls[0].options.headers.Authorization, 'Bearer local-secret');
  assert.equal(calls[0].url, 'http://127.0.0.1:8100/api/health');
  assert(calls[0].options.signal);
  await assert.rejects(client.request('https://unrelated.example/steal'), /backend-relative/);
  assert.equal(calls.length, 1);
});
test('reload recovers pending approvals and stop does not falsely complete a task', async () => {
  const calls = [];
  const task = { id: 'saved', conversation_id: 'conversation', prompt: 'Change a file', status: 'awaiting_approval' };
  const api = { health: async () => ({ status: 'ok' }), listTasks: async () => ({ tasks: [task] }), getTask: async () => ({ task, events: [{ seq: 1, type: 'tool_approval_request', payload: { request_id: 'approval', tool: 'write_file', arguments: { path: '/tmp/file' } } }], approvals: [{ request_id: 'approval', tool: 'write_file', arguments: { path: '/tmp/file' } }] }), approveTask: async (...args) => { calls.push(args); throw new Error('Service unavailable'); }, cancelTask: async () => { throw new Error('Service unavailable'); } };
  const controller = new TaskController(api, { schedule: () => 1, unschedule() {} });
  await controller.recover();
  assert.equal(controller.snapshot().details.saved.approvals[0].request_id, 'approval');
  await assert.rejects(controller.approve('saved', 'approval', true), /Service unavailable/);
  assert.equal(controller.snapshot().details.saved.approvals.length, 1);
  await assert.rejects(controller.cancel('saved'), /Service unavailable/);
  assert.equal(controller.snapshot().tasks[0].status, 'awaiting_approval');
  controller.stop();
});
test('completed polling keeps the server tool receipt and stops scheduling', async () => {
  const queued = [];
  const task = { id: 'running', status: 'running' };
  const receipt = { tool: 'read_file', status: 'completed', result: { success: true, content: 'real file' } };
  const api = { createTask: async () => task, getTask: async () => ({ task: { ...task, status: 'completed', result: { response: 'Read the file' } }, events: [{ seq: 1, type: 'tool_status', payload: receipt }], approvals: [] }) };
  const controller = new TaskController(api, { schedule: callback => { queued.push(callback); return 1; }, unschedule() {} });
  await controller.start({ prompt: 'Read a file' });
  assert.equal(controller.snapshot().tasks[0].status, 'completed');
  assert.deepEqual(controller.snapshot().details.running.events[0].payload, receipt);
  assert.equal(queued.length, 0);
});
test('a stale poll cannot restore running status after cancellation', async () => {
  let resolvePoll; let polls = 0;
  const running = { id: 'race', status: 'running' }; const cancelled = { ...running, status: 'cancelled' };
  const api = { createTask: async () => running, cancelTask: async () => cancelled, getTask: async () => { if (++polls === 1) return new Promise(resolve => { resolvePoll = resolve; }); return { task: cancelled, events: [], approvals: [] }; } };
  const controller = new TaskController(api, { schedule: () => 1, unschedule() {} });
  const start = controller.start({ prompt: 'Start' });
  await new Promise(resolve => setImmediate(resolve));
  const cancel = controller.cancel('race');
  await new Promise(resolve => setImmediate(resolve));
  resolvePoll({ task: running, events: [], approvals: [] });
  await Promise.all([start, cancel]);
  assert.equal(controller.snapshot().tasks[0].status, 'cancelled');
  controller.stop();
});
test('approval rendering reflects a server approval resolution instead of calling it denied', () => {
  const { taskMessages } = globalThis.__taskExports;
  const messages = taskMessages({ task: { id: 'task', status: 'completed' }, events: [{ seq: 1, type: 'tool_approval_request', payload: { request_id: 'permission', tool: 'write_file', arguments: {} } }, { seq: 2, type: 'tool_approval_resolved', payload: { request_id: 'permission', approved: true } }], approvals: [] });
  assert.equal(messages[0].resolved, true);
  assert.equal(messages[0].approved, true);
});
test('default task timers preserve the browser global receiver', async () => {
  const original = globalThis.clearTimeout;
  globalThis.clearTimeout = function () { assert.equal(this, globalThis, 'Native browser timers require their global receiver'); };
  try {
    const controller = new TaskController({ getTask: async () => ({ task: { id: 'receiver', status: 'completed' }, events: [] }) });
    await controller.poll('receiver');
    assert.equal(controller.snapshot().details.receiver.task.status, 'completed');
  } finally { globalThis.clearTimeout = original; }
});
test('renderer credentials cannot be redirected to a remote backend', () => {
  assert.throws(() => new BackendClient({ baseUrl: 'https://unrelated.example' }), /local backend/);
});
