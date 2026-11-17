const assert = require('node:assert/strict');
const { before, test } = require('node:test');
const { build } = require('esbuild');
const Module = require('node:module');
const { resolve } = require('node:path');
let source;
before(async () => {
  const result = await build({ entryPoints: [resolve(__dirname, '../../src/components/VoiceAssistant/VoiceAssistant.jsx')], bundle: true, platform: 'node', format: 'cjs', write: false, plugins: [{ name: 'voice-ui-boundaries', setup(build) {
    build.onResolve({ filter: /.*/ }, args => args.importer ? { path: args.path, namespace: 'boundary' } : undefined);
    build.onLoad({ filter: /.*/, namespace: 'boundary' }, ({ path }) => ({ contents: path === 'react' ? 'export default globalThis.__voiceUI.hooks; export const {useState,useEffect,useRef,useCallback}=globalThis.__voiceUI.hooks;' : path.includes('VoiceEngine') ? 'export const voiceEngine=globalThis.__voiceUI.engine;' : path.includes('constants') ? 'export const VOICE_LANGUAGES=[{code:"en-US",label:"English",flag:"EN"},{code:"hi-IN",label:"Hindi",flag:"HI"}];' : '', loader: 'js' }));
  } }] });
  source = result.outputFiles[0].text;
});
function harness(context, props = {}) {
  let cursor, dirty, tree, effects = [], callbacks;
  const slots = [], transcripts = [], calls = { start: [], stop: [] };
  const equal = (a, b) => a && b && a.length === b.length && a.every((item, index) => Object.is(item, b[index]));
  const hooks = {
    createElement(type, props, ...children) { return { type, props: props || {}, children }; },
    useState(initial) { const index = cursor++; slots[index] ||= { value: initial }; return [slots[index].value, update => { const next = typeof update === 'function' ? update(slots[index].value) : update; if (!Object.is(next, slots[index].value)) { slots[index].value = next; dirty = true; } }]; },
    useRef(initial) { const index = cursor++; slots[index] ||= { value: { current: initial } }; return slots[index].value; },
    useCallback(callback, dependencies) { const index = cursor++; if (!slots[index] || !equal(slots[index].dependencies, dependencies)) slots[index] = { value: callback, dependencies }; return slots[index].value; },
    useEffect(callback, dependencies) { const index = cursor++; if (!slots[index] || !equal(slots[index].dependencies, dependencies)) { const previous = slots[index]; slots[index] = { dependencies, cleanup: previous?.cleanup }; effects.push(() => { previous?.cleanup?.(); slots[index].cleanup = callback(); }); } },
  };
  const engine = {
    isSTTSupported: () => true,
    async startListening(language, handlers) { calls.start.push(language); callbacks = handlers; handlers.onStateChange('listening'); return true; },
    stopListening(transcribe) { calls.stop.push(transcribe); callbacks?.onStateChange(transcribe ? 'transcribing' : 'idle'); },
  };
  const previous = globalThis.__voiceUI;
  globalThis.__voiceUI = { hooks, engine };
  const fixture = new Module(__filename); fixture._compile(source, __filename);
  let currentProps = { onTranscript: text => transcripts.push(text), language: 'en-US', ...props };
  const flush = () => { let count = 0; do { dirty = false; cursor = 0; tree = fixture.exports.default(currentProps); const pending = effects; effects = []; pending.forEach(effect => effect()); assert(++count < 20); } while (dirty); };
  const nodes = root => Array.isArray(root) ? root.flatMap(nodes) : root && typeof root === 'object' ? [root, ...root.children.flatMap(nodes)] : root == null || typeof root === 'boolean' ? [] : [root];
  const button = () => nodes(tree).find(node => node?.type === 'button' && node.props.className?.includes('va-mic-btn'));
  const text = () => nodes(tree).filter(node => typeof node === 'string').join(' ');
  const emit = (name, payload) => { callbacks[name](payload); flush(); };
  flush();
  context.after(() => { slots.forEach(slot => slot.cleanup?.()); globalThis.__voiceUI = previous; });
  return { engine, calls, transcripts, flush, button, text, emit, update(changes) { currentProps = { ...currentProps, ...changes }; flush(); }, destroy() { slots.forEach(slot => slot.cleanup?.()); } };
}

test('composer voice records explicitly, shows transcription state, and inserts the transcript', async context => {
  const h = harness(context);
  assert.equal(h.calls.start.length, 0, 'mount must not capture audio');
  await h.button().props.onClick(); h.flush();
  assert.match(h.button().props['aria-label'], /Stop recording/);
  assert.match(h.text(), /Recording/);
  await h.button().props.onClick(); h.flush();
  assert.equal(h.calls.stop.at(-1), true);
  assert.match(h.text(), /Transcribing/);
  assert.match(h.button().props['aria-label'], /Cancel transcription/);
  h.emit('onResult', { final: 'inspect localhost', isFinal: true });
  assert.deepEqual(h.transcripts, ['inspect localhost']);
});
test('composer voice displays the useful backend error and remains visible without browser recognition', async context => {
  const h = harness(context);
  await h.button().props.onClick(); h.flush();
  h.emit('onError', 'Speech credentials were rejected. Update the backend configuration.');
  assert.match(h.text(), /Speech credentials were rejected/);
  assert.match(h.button().props['aria-label'], /Start voice input/);
});
test('disabled composer cancels capture, blocks new requests and ignores callbacks after unmount', async context => {
  const h = harness(context);
  await h.button().props.onClick(); h.flush();
  h.update({ disabled: true });
  assert.equal(h.calls.stop.at(-1), false);
  assert.equal(h.button().props.disabled, true);
  await h.button().props.onClick();
  assert.equal(h.calls.start.length, 1);
  h.destroy(); h.emit('onResult', { final: 'late result', isFinal: true });
  assert.deepEqual(h.transcripts, []);
});
