'use strict';

const defaultHttp = require('node:http');
const { spawn: defaultSpawn } = require('node:child_process');
const { randomUUID } = require('node:crypto');

/**
 * Owns the Python service lifecycle. start()/waitForReady() resolve to authenticated
 * health JSON. stop() waits for owned children only; reused services stay running.
 * onStatus receives {state, owned, restartAttempts, error?}. HTTP, spawn, timers,
 * logging and durations are injectable so lifecycle races can be tested offline.
 */
class BackendManager {
  constructor(options) {
    if (!options?.python || !options.backendDir || !options.authToken) {
      throw new Error('Backend executable, directory, and authentication token are required.');
    }
    this.options = {
      host: '127.0.0.1', port: 8100, maxRestarts: 3,
      startupTimeoutMs: 35000, requestTimeoutMs: 1200, pollIntervalMs: 400,
      shutdownGraceMs: 3000, killWaitMs: 1000, restartDelayMs: 1000,
      ...options,
    };
    if (this.options.host !== '127.0.0.1') throw new Error('The desktop backend must use the loopback interface.');
    this.http = options.http || defaultHttp;
    this.spawn = options.spawn || defaultSpawn;
    this.timers = {
      setTimeout, clearTimeout, now: () => Date.now(), ...options.timers,
    };
    this.log = options.log || (() => {});
    this.onStatus = options.onStatus || (() => {});
    this.instanceId = options.instanceId || randomUUID();
    this.state = 'stopped'; this.child = null; this.health = null;
    this.restartAttempts = 0;
    this._stopping = false; this._startPromise = null; this._stopPromise = null;
    this._restartTimer = null; this._cancelWaits = new Set();
    this._childErrors = new WeakMap(); this._exited = new WeakSet();
    this._secrets = Object.entries({ ...process.env, ...options.env, BACKEND_AUTH_TOKEN: options.authToken })
      .filter(([key, value]) => /token|secret|password|api.?key|credential/i.test(key) && typeof value === 'string' && value.length >= 6)
      .map(([, value]) => value).sort((a, b) => b.length - a.length);
  }

  _status(state, error) {
    this.state = state;
    const detail = { state, owned: Boolean(this.child), restartAttempts: this.restartAttempts };
    if (error) detail.error = this._redact(error.message || String(error));
    try { this.onStatus(detail); } catch { /* UI listeners cannot break cleanup. */ }
  }

  _redact(value) {
    let line = String(value);
    for (const secret of this._secrets) line = line.split(secret).join('[redacted]');
    return line;
  }

  _writeLog(value) {
    try { this.log(this._redact(value)); } catch { /* A full log must not stop the service. */ }
  }

  start() {
    if (this._startPromise) return this._startPromise;
    if (this._stopPromise) return Promise.reject(new Error('Backend shutdown is still in progress.'));
    if (this.state === 'ready' && this.health) return Promise.resolve(this.health);
    if (this._restartTimer) {
      this.timers.clearTimeout(this._restartTimer); this._restartTimer = null;
    }
    this._stopping = false;
    this._status(this.restartAttempts ? 'restarting' : 'starting');
    const operation = this._start();
    this._startPromise = operation;
    operation.then(
      () => { if (this._startPromise === operation) this._startPromise = null; },
      error => {
        if (this._startPromise === operation) this._startPromise = null;
        if (!this._stopping && !this._restartTimer) this._status('failed', error);
      },
    );
    return operation;
  }

  waitForReady() { return this.start(); }

  async _start() {
    const existing = await this._probe();
    this._assertRunning();
    if (existing.kind === 'ready') {
      this.health = existing.data; this._status('ready'); return this.health;
    }
    if (existing.kind !== 'absent') throw existing.error;
    const child = this.spawn(this.options.python, this.options.args || ['main.py'], {
      cwd: this.options.backendDir,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: {
        ...process.env, ...this.options.env,
        PYTHONUNBUFFERED: '1', BACKEND_AUTH_TOKEN: this.options.authToken,
        BACKEND_HOST: this.options.host, BACKEND_PORT: String(this.options.port),
        BACKEND_INSTANCE_ID: this.instanceId,
      },
    });
    this.child = child;
    child.stdout?.on('data', data => this._writeLog(data));
    child.stderr?.on('data', data => this._writeLog(data));
    child.once('error', error => {
      this._childErrors.set(child, error);
      this._exited.add(child);
      if (this.child === child) this.child = null;
      this._wakeWaits();
    });
    child.once('exit', (code, signal) => this._onExit(child, code, signal));
    const deadline = this.timers.now() + this.options.startupTimeoutMs;
    try {
      while (this.timers.now() < deadline) {
        this._assertRunning();
        const spawnError = this._childErrors.get(child);
        if (spawnError) throw new Error(`Backend could not start: ${spawnError.message}`);
        if (this.child !== child) throw new Error('Backend exited before becoming ready.');
        const probe = await this._probe(true);
        this._assertRunning();
        const afterProbeError = this._childErrors.get(child);
        if (afterProbeError) throw new Error(`Backend could not start: ${afterProbeError.message}`);
        if (this.child !== child) throw new Error('Backend exited before becoming ready.');
        if (probe.kind === 'ready') {
          this.health = probe.data; this._status('ready'); return this.health;
        }
        if (probe.kind === 'occupied') throw probe.error;
        await this._delay(this.options.pollIntervalMs);
      }
      throw new Error(`Backend did not become ready within ${Math.round(this.options.startupTimeoutMs / 1000)} seconds. Check the backend log.`);
    } catch (error) {
      // Failed startup must not leave an unreachable service behind. Suppress
      // automatic recovery for this intentional termination.
      if (this.child === child && !this._stopping) {
        this.child = null;
        await this._terminate(child);
      }
      throw error;
    }
  }

  _assertRunning() {
    if (this._stopping) throw new Error('Backend startup was cancelled because the app stopped.');
  }

  _probe(owned = false) {
    return new Promise(resolve => {
      let req, finished = false, timeout;
      const finish = result => {
        if (finished) return;
        finished = true; this.timers.clearTimeout(timeout);
        this._cancelWaits.delete(cancel);
        resolve(result);
      };
      const occupied = message => ({ kind: 'occupied', error: new Error(message) });
      const cancel = () => { req?.destroy(); finish({ kind: 'absent' }); };
      this._cancelWaits.add(cancel);
      timeout = this.timers.setTimeout(() => {
        req?.destroy();
        finish(occupied(`The service on port ${this.options.port} timed out. Close it or restart Lyra.`));
      }, this.options.requestTimeoutMs);
      try {
        req = this.http.get(`http://${this.options.host}:${this.options.port}/api/health`, {
          headers: { Authorization: `Bearer ${this.options.authToken}` },
        }, res => {
          let body = '';
          res.on('data', chunk => {
            body += chunk;
            if (body.length > 65536) { req.destroy(); finish(occupied('The backend health response was too large.')); }
          });
          res.on('error', error => finish(occupied(`Backend health response failed: ${error.message}`)));
          res.on('end', () => {
            let data;
            try { data = JSON.parse(body); } catch { /* Invalid JSON is an occupied foreign service. */ }
            if (res.statusCode !== 200 || data?.system !== 'LYRA' || data?.status !== 'online') {
              finish(occupied(`Port ${this.options.port} is occupied by an unavailable or unauthenticated service. Close it before starting Lyra.`)); return;
            }
            const owner = data.instance_id || data.backend_instance_id;
            if (owned && owner && owner !== this.instanceId) {
              finish(occupied('A different backend instance owns this port. Restart Lyra after closing that service.')); return;
            }
            finish({ kind: 'ready', data });
          });
        });
        req.on('error', error => {
          if (error.code === 'ECONNREFUSED') finish({ kind: 'absent' });
          else finish(occupied(`Cannot verify the service on port ${this.options.port}: ${error.message}`));
        });
      } catch (error) { finish(occupied(`Backend health probe failed: ${error.message}`)); }
    });
  }

  _delay(ms) {
    return new Promise(resolve => {
      const done = () => {
        this.timers.clearTimeout(timer); this._cancelWaits.delete(done); resolve();
      };
      const timer = this.timers.setTimeout(done, ms);
      this._cancelWaits.add(done);
    });
  }

  _wakeWaits() { for (const cancel of [...this._cancelWaits]) cancel(); }

  _onExit(child, code, signal) {
    this._exited.add(child);
    if (this.child !== child) return;
    this.child = null; this.health = null; this._wakeWaits();
    if (this._stopping || this._restartTimer) return;
    const reason = new Error(`Backend exited unexpectedly (${signal || `code ${code}`}).`);
    this._writeLog(reason.message);
    if (this.restartAttempts >= this.options.maxRestarts) { this._status('failed', reason); return; }
    this.restartAttempts++;
    this._status('restarting', reason);
    this._restartTimer = this.timers.setTimeout(() => {
      this._restartTimer = null;
      if (this._stopping) return;
      // The previous startup can still be settling after its child exited.
      const previous = this._startPromise;
      Promise.resolve(previous).catch(() => {}).then(() => {
        if (!this._stopping) this.start().catch(error => this._writeLog(error.message));
      });
    }, this.options.restartDelayMs * this.restartAttempts);
  }

  stop() {
    if (this._stopPromise) return this._stopPromise;
    this._stopping = true; this.health = null;
    if (this._restartTimer) this.timers.clearTimeout(this._restartTimer);
    this._restartTimer = null; this._wakeWaits();
    const child = this.child; this.child = null;
    const starting = this._startPromise;
    const operation = (async () => {
      if (child) await this._terminate(child);
      await starting?.catch(() => {});
      this._status('stopped');
    })();
    this._stopPromise = operation;
    operation.finally(() => { if (this._stopPromise === operation) this._stopPromise = null; });
    return operation;
  }

  async _terminate(child) {
    if (this._exited.has(child)) return;
    const waitExit = timeoutMs => new Promise(resolve => {
      if (this._exited.has(child)) { resolve(true); return; }
      let timer;
      const done = exited => {
        this.timers.clearTimeout(timer); child.removeListener('exit', onExit); resolve(exited);
      };
      const onExit = () => done(true);
      child.once('exit', onExit);
      timer = this.timers.setTimeout(() => done(false), timeoutMs);
    });
    try { child.kill('SIGTERM'); } catch { return; }
    if (await waitExit(this.options.shutdownGraceMs)) return;
    try { child.kill('SIGKILL'); } catch { return; }
    if (!await waitExit(this.options.killWaitMs)) this._writeLog('The owned backend did not confirm exit after forced shutdown.');
  }
}

module.exports = { BackendManager };
