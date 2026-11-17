const test = require('node:test');
const assert = require('node:assert/strict');
const { EventEmitter } = require('node:events');

let BackendManager;
try { ({ BackendManager } = require('../../electron/backend-manager.cjs')); }
catch (error) { if (error.code !== 'MODULE_NOT_FOUND') throw error; }

const healthy = { status: 'online', system: 'LYRA' };
const pause = (ms = 0) => new Promise(resolve => setTimeout(resolve, ms));

function fakeChild() {
  const child = new EventEmitter();
  child.stdout = new EventEmitter(); child.stderr = new EventEmitter();
  child.kills = [];
  child.kill = signal => {
    child.kills.push(signal);
    if (signal === 'SIGKILL' || !child.ignoreTerm) queueMicrotask(() => child.emit('exit', null, signal));
    return true;
  };
  return child;
}

function harness(overrides = {}) {
  let up = false;
  const children = [], calls = [], statuses = [], requests = [], logs = [];
  const http = {
    get(url, options, callback) {
      const req = new EventEmitter();
      requests.push({ url, options, req });
      req.destroy = () => { req.destroyed = true; };
      req.setTimeout = () => req;
      queueMicrotask(() => {
        if (req.destroyed) return;
        const response = overrides.response ? overrides.response({ up, req }) : up ? { code: 200, body: healthy } : null;
        if (response === 'hang') return;
        if (!response) { req.emit('error', Object.assign(new Error('connection refused'), { code: 'ECONNREFUSED' })); return; }
        const res = new EventEmitter(); res.statusCode = response.code;
        callback(res);
        res.emit('data', typeof response.body === 'string' ? response.body : JSON.stringify(response.body));
        res.emit('end');
      });
      return req;
    },
  };
  const manager = new BackendManager({
    python: '/python', backendDir: '/backend', authToken: 'a-secret-token',
    env: { TEST_API_KEY: 'private-api-credential' },
    http, startupTimeoutMs: 100, pollIntervalMs: 2, requestTimeoutMs: 20,
    shutdownGraceMs: 5, killWaitMs: 10, restartDelayMs: 2,
    log: line => logs.push(line), onStatus: value => statuses.push(value),
    spawn(...args) {
      calls.push(args); const child = fakeChild(); children.push(child);
      if (overrides.spawnError) queueMicrotask(() => child.emit('error', overrides.spawnError));
      else if (!overrides.neverReady) up = true;
      child.on('exit', () => { up = false; });
      return child;
    },
    ...overrides.options,
  });
  return { manager, calls, children, statuses, requests, logs, setUp: value => { up = value; } };
}

test('exports a backend lifecycle manager', () => {
  assert.equal(typeof BackendManager, 'function');
});

test('reuses only authenticated healthy LYRA without taking process ownership', async () => {
  const h = harness(); h.setUp(true);
  assert.deepEqual(await h.manager.start(), healthy);
  assert.equal(h.calls.length, 0);
  assert.equal(h.requests[0].options.headers.Authorization, 'Bearer a-secret-token');
  await h.manager.stop();
  assert.equal(h.children.length, 0);
  assert.equal(h.statuses.at(-1).state, 'stopped');
});

test('rejects occupied or unauthenticated ports instead of spawning a duplicate', async () => {
  for (const response of [
    { code: 401, body: { detail: 'Unauthorized' } },
    { code: 200, body: { status: 'online', system: 'OTHER' } },
    { code: 200, body: '<html>some service</html>' },
  ]) {
    const h = harness({ response: () => response });
    await assert.rejects(h.manager.start(), /port|service|authentication/i);
    assert.equal(h.calls.length, 0);
    await h.manager.stop();
  }
});

test('starts one owned backend and waits for verified readiness for concurrent callers', async () => {
  const h = harness();
  const first = h.manager.start(), second = h.manager.start();
  assert.equal(first, second);
  assert.deepEqual(await first, healthy);
  assert.equal(h.calls.length, 1);
  const [python, args, options] = h.calls[0];
  assert.equal(python, '/python'); assert.deepEqual(args, ['main.py']);
  assert.equal(options.cwd, '/backend');
  assert.equal(options.env.BACKEND_HOST, '127.0.0.1');
  assert.equal(options.env.BACKEND_AUTH_TOKEN, 'a-secret-token');
  assert.equal(h.statuses.at(-1).state, 'ready');
  await h.manager.stop();
  assert.deepEqual(h.children[0].kills, ['SIGTERM']);
});

test('reports an executable spawn failure promptly', async () => {
  const h = harness({ spawnError: Object.assign(new Error('missing python executable'), { code: 'ENOENT' }) });
  await assert.rejects(h.manager.start(), /missing python|ENOENT/);
  assert.equal(h.statuses.at(-1).state, 'failed');
  await h.manager.stop();
});

test('bounds a stalled HTTP probe and refuses the occupied port', async () => {
  const h = harness({ response: () => 'hang' });
  await assert.rejects(h.manager.start(), /timeout|timed out|port/i);
  assert.equal(h.requests[0].req.destroyed, true);
  assert.equal(h.calls.length, 0);
  await h.manager.stop();
});

test('rejects a mismatched owner after spawning its own backend', async () => {
  const h = harness({ options: { instanceId: 'this-app' }, response: ({ up }) => up ? { code: 200, body: { ...healthy, instance_id: 'another-app' } } : null });
  await assert.rejects(h.manager.start(), /instance|owner/i);
  assert.equal(h.calls.length, 1);
  assert.deepEqual(h.children[0].kills, ['SIGTERM']);
  await h.manager.stop();
});

test('reuses a valid authenticated external Lyra instance without owner matching', async () => {
  const h = harness({ options: { instanceId: 'this-app' }, response: () => ({ code: 200, body: { ...healthy, instance_id: 'external-app' } }) });
  await h.manager.start();
  assert.equal(h.calls.length, 0);
  await h.manager.stop();
});

test('supports a frozen backend executable with no Python script argument', async () => {
  const h = harness({ options: { python: '/bundle/lyra-backend', args: [] } });
  await h.manager.start();
  assert.deepEqual(h.calls[0][1], []);
  await h.manager.stop();
});

test('restarts unexpected signal exits and stops after the bounded restart budget', async () => {
  const h = harness({ options: { maxRestarts: 2 } });
  await h.manager.start();
  for (let index = 0; index < 2; index++) {
    h.children[index].emit('exit', null, 'SIGSEGV');
    h.children[index].emit('exit', null, 'SIGSEGV');
    await pause(15);
    assert.equal(h.calls.length, index + 2);
  }
  h.children[2].emit('exit', 1, null);
  await pause(15);
  assert.equal(h.calls.length, 3);
  assert.equal(h.statuses.at(-1).state, 'failed');
  await h.manager.stop();
});

test('shutdown cancels startup polling and never schedules a recovery process', async () => {
  const h = harness({ neverReady: true });
  const starting = h.manager.start();
  const rejected = assert.rejects(starting, /stopped|cancel/i);
  await pause(5);
  await h.manager.stop(); await rejected;
  await pause(15);
  assert.equal(h.calls.length, 1);
  assert.equal(h.statuses.at(-1).state, 'stopped');
});

test('forces only its owned backend down if graceful shutdown is ignored', async () => {
  const h = harness(); await h.manager.start();
  h.children[0].ignoreTerm = true;
  await h.manager.stop();
  assert.deepEqual(h.children[0].kills, ['SIGTERM', 'SIGKILL']);
  await pause(10);
  assert.equal(h.calls.length, 1);
});

test('redacts configured credentials from child output before logging', async () => {
  const h = harness(); await h.manager.start();
  h.children[0].stdout.emit('data', Buffer.from('token a-secret-token key private-api-credential'));
  assert.ok(h.logs.length > 0);
  assert.equal(h.logs.some(line => line.includes('a-secret-token') || line.includes('private-api-credential')), false);
  await h.manager.stop();
});
