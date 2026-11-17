const assert = require('node:assert/strict');
const { before, test } = require('node:test');
const { build } = require('esbuild');
const Module = require('node:module');
const { resolve } = require('node:path');

let VoiceListener;
before(async () => {
  const result = await build({ entryPoints: [resolve(__dirname, '../../src/modules/voice/VoiceListener.js')], bundle: true, format: 'cjs', platform: 'node', write: false, define: { 'import.meta.env': '{}' } });
  const fixture = new Module(__filename);
  fixture._compile(result.outputFiles[0].text, __filename);
  ({ VoiceListener } = fixture.exports);
});
const tick = () => new Promise(resolve => setImmediate(resolve));
function harness(context, options = {}) {
  const calls = [], states = [], transcripts = [], commands = [], errors = [];
  const track = { readyState: 'live', stops: 0, stop() { this.stops++; this.readyState = 'ended'; } };
  const stream = { getTracks: () => [track] };
  class Recorder {
    static isTypeSupported(type) { return type.includes('webm'); }
    constructor(stream, settings) { this.mimeType = settings?.mimeType || 'audio/webm'; this.state = 'inactive'; Recorder.latest = this; }
    start() { this.state = 'recording'; }
    stop() { this.state = 'inactive'; queueMicrotask(() => { this.ondataavailable?.({ data: new Blob(['synthetic recorded bytes'], { type: this.mimeType }) }); this.onstop?.(); }); }
  }
  const listener = new VoiceListener({ mediaDevices: { getUserMedia: options.getUserMedia || (async () => stream) }, MediaRecorderClass: Recorder, AudioContextClass: null, client: { async request(path, request) { calls.push({ path, request }); return options.request ? options.request(path, request) : { text: 'inspect the local project' }; } } });
  listener.onStateChange(state => states.push(state)).onTranscript(result => transcripts.push(result)).onCommand(text => commands.push(text)).onError(error => errors.push(error));
  context.after(() => listener.stop(false));
  return { listener, calls, states, transcripts, commands, errors, track, stream, Recorder };
}

test('recording works without browser recognition and a manual stop submits actual audio once', async context => {
  const h = harness(context);
  assert.equal(await h.listener.startListening('hi-IN'), true);
  assert.deepEqual(h.states, ['requesting', 'listening']);
  h.listener.stop(true);
  await tick();
  assert.equal(h.calls.length, 1);
  assert.equal(h.calls[0].path, '/api/stt');
  assert.equal(Buffer.from(h.calls[0].request.body.audio, 'base64').toString(), 'synthetic recorded bytes');
  assert.equal(h.calls[0].request.body.language, 'hi');
  assert(h.calls[0].request.signal);
  assert.deepEqual(h.commands, ['inspect the local project']);
  assert.equal(h.transcripts.filter(item => item.final).length, 1);
  assert.equal(h.track.stops, 1, 'microphone released before the network result');
  assert(h.states.includes('transcribing'));
  assert.equal(h.listener.getState(), 'idle');
  h.Recorder.latest.onstop?.();
  await tick();
  assert.equal(h.calls.length, 1, 'duplicate recorder completion cannot submit again');
});

test('cancel during a pending microphone permission request releases its eventual stream', async context => {
  let permit;
  const h = harness(context, { getUserMedia: () => new Promise(resolve => { permit = resolve; }) });
  const starting = h.listener.startListening();
  h.listener.stop(false);
  permit(h.stream);
  assert.equal(await starting, false);
  assert.equal(h.track.stops, 1);
  assert.equal(h.calls.length, 0);
  assert.equal(h.listener.getState(), 'idle');
});

test('cancel aborts transcription and ignores a late provider result', async context => {
  let complete;
  const h = harness(context, { request: () => new Promise(resolve => { complete = resolve; }) });
  await h.listener.startListening();
  h.listener.stop(true);
  await tick();
  h.listener.stop(false);
  assert.equal(h.calls[0].request.signal.aborted, true);
  complete({ text: 'do not send a cancelled request' });
  await tick();
  assert.deepEqual(h.commands, []);
  assert.equal(h.listener.getState(), 'idle');
  assert.equal(h.track.stops, 1);
});

test('transcription failures expose the backend message and do not restart recording', async context => {
  const h = harness(context, { request: async () => { throw new Error('Groq credentials were rejected. Update the backend key.'); } });
  await h.listener.startListening();
  h.listener.stop(true);
  await tick();
  assert.match(h.errors[0], /credentials were rejected/);
  assert.equal(h.listener.getState(), 'error');
  assert.equal(h.track.stops, 1);
  assert.deepEqual(h.commands, []);
});

test('empty transcription is a visible no-speech error', async context => {
  const h = harness(context, { request: async () => ({ text: '   ' }) });
  await h.listener.startListening(); h.listener.stop(true); await tick();
  assert.match(h.errors[0], /No speech/i);
  assert.equal(h.listener.getState(), 'error');
});

test('microphone permission denial remains actionable and no recording is created', async context => {
  const h = harness(context, { getUserMedia: async () => { const error = new Error('denied'); error.name = 'NotAllowedError'; throw error; } });
  assert.equal(await h.listener.startListening(), false);
  assert.match(h.errors[0], /permission|access/i);
  assert.equal(h.listener.getState(), 'error');
  assert.equal(h.calls.length, 0);
});
