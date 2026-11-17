const assert = require('node:assert/strict');
const { before, test } = require('node:test');
const { build } = require('esbuild');
const Module = require('node:module');
const { resolve } = require('node:path');
let VoiceSpeaker;
before(async () => {
  const result = await build({ entryPoints: [resolve(__dirname, '../../src/modules/voice/VoiceSpeaker.js')], bundle: true, format: 'cjs', platform: 'node', write: false, define: { 'import.meta.env': '{}' } });
  const fixture = new Module(__filename); fixture._compile(result.outputFiles[0].text, __filename);
  ({ VoiceSpeaker } = fixture.exports);
});
test('no installed browser voices uses authenticated backend audio and real playback events', async () => {
  const requests = [], events = [];
  class Playback { constructor(src) { this.src = src; } play() { events.push('play'); queueMicrotask(() => this.onended?.()); return Promise.resolve(); } pause() {} }
  const speaker = new VoiceSpeaker({ synthesis: { getVoices: () => [], cancel() {} }, AudioClass: Playback, client: { async request(path, options) { requests.push({ path, options }); return { audio: 'c291bmQ=', format: 'wav' }; } } });
  speaker.onStart(() => events.push('start')).onEnd(() => events.push('end'));
  await speaker.speak('Read this message');
  assert.equal(requests.length, 1);
  assert.equal(requests[0].path, '/api/tts');
  assert.equal(requests[0].options.method, 'POST');
  assert.deepEqual(requests[0].options.body, { text: 'Read this message', language: 'en-US' });
  assert.deepEqual(events, ['play', 'start', 'end']);
  assert.equal(speaker.isSpeaking, false);
});
test('backend speech failure rejects and does not report a successful end', async () => {
  const events = [];
  const speaker = new VoiceSpeaker({ synthesis: null, client: { async request() { return { error: 'Speech generation failed' }; } } });
  speaker.onEnd(() => events.push('end')).onError(error => events.push(error.message));
  await assert.rejects(speaker.speak('Speak this'), /Speech generation failed/);
  assert.deepEqual(events, ['Speech generation failed']);
  assert.equal(speaker.isSpeaking, false);
});
test('cancelling pending speech aborts its request without playing late audio', async () => {
  let complete, signal; let played = 0;
  class Playback { play() { played++; return Promise.resolve(); } }
  const speaker = new VoiceSpeaker({ synthesis: null, AudioClass: Playback, client: { request(path, options) { signal = options.signal; return new Promise(resolve => { complete = resolve; }); } } });
  const speaking = speaker.speak('Cancel this');
  await new Promise(resolve => setImmediate(resolve));
  speaker.stop();
  complete({ audio: 'c291bmQ=', format: 'wav' });
  await speaking;
  assert.equal(signal.aborted, true);
  assert.equal(played, 0);
});
