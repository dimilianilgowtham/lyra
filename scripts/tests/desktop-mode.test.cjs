const assert = require('node:assert/strict');
const { before, test } = require('node:test');
const { resolve } = require('node:path');
const Module = require('node:module');
const esbuild = require('esbuild');

const workspace = resolve(__dirname, '../..');
let componentSource;

// Run the real component with controlled hooks and external service boundaries.
// This exercises event handlers and rendered behavior without requiring a browser
// or microphone. Full React/DOM integration remains a browser smoke check.
before(async () => {
  const result = await esbuild.build({
    entryPoints: [resolve(workspace, 'src/components/DesktopMode/DesktopMode.jsx')],
    bundle: true,
    platform: 'node',
    format: 'cjs',
    jsx: 'transform',
    write: false,
    plugins: [{
      name: 'desktop-test-boundaries',
      setup(build) {
        build.onResolve({ filter: /.*/ }, args => args.importer
          ? { path: args.path, namespace: 'boundary' }
          : undefined);
        build.onLoad({ filter: /.*/, namespace: 'boundary' }, ({ path }) => {
          let contents;
          if (path === 'react') {
            contents = 'export default globalThis.__desktopTest.hooks; export const {useState,useRef,useEffect,useCallback,useMemo}=globalThis.__desktopTest.hooks;';
           } else if (path.includes('useLyraAgent')) {
            contents = 'export const useLyraAgent=()=>globalThis.__desktopTest.agent;';
          } else if (path.includes('ModelRouter')) {
            contents = 'export const ModelRouter={getConfig:()=>({provider:"groq",model:"test-model"})};';
          } else if (path.includes('DesktopBridge')) {
            contents = 'export const DesktopBridge=globalThis.__desktopTest.bridge;';
          } else if (path.includes('VoiceManager')) {
            contents = 'export const voiceManager=globalThis.__desktopTest.voice;';
          } else if (path === 'lucide-react') {
            contents = 'export const ArrowLeft=()=>null, Brain=()=>null, Terminal=()=>null, MessageSquare=()=>null, Mic=()=>null, Send=()=>null, Square=()=>null, Volume2=()=>null;';
          } else {
            contents = 'export default function Boundary() {return null;}';
          }
          return { contents, loader: 'js' };
        });
      },
    }],
  });
  componentSource = result.outputFiles[0].text;
});

function createHarness() {
  const slots = [];
  const events = new Map();
  const windowEvents = new Map();
  const calls = { commands: [], interrupt: 0, voiceStarts: 0, stops: 0, speech: [] };
  const agent = { connected: true, agentMessages: [], tasks: [], details: {}, health: {}, error: '', isThinking: false, recovering: false,
    async sendMessage(text, options) { calls.commands.push({ text, options }); return { id: 'task', conversation_id: options.conversation_id }; },
    async stopResponse() { calls.interrupt++; }, confirmTool() {}, refresh() {}, cancelTask() {}, resumeTask() {},
  };
  let cursor = 0;
  let dirty = false;
  let effects = [];
  let tree;
  let connected = false;
  const equal = (a, b) => a && b && a.length === b.length && a.every((item, index) => Object.is(item, b[index]));
  const hooks = {
    createElement(type, props, ...children) { return { type, props: props || {}, children }; },
    useState(initial) {
      const index = cursor++;
      if (!slots[index]) slots[index] = { value: typeof initial === 'function' ? initial() : initial };
      return [slots[index].value, update => {
        const value = typeof update === 'function' ? update(slots[index].value) : update;
        if (!Object.is(value, slots[index].value)) { slots[index].value = value; dirty = true; }
      }];
    },
    useRef(initial) {
      const index = cursor++;
      if (!slots[index]) slots[index] = { value: { current: initial } };
      return slots[index].value;
    },
    useMemo(factory, dependencies) {
      const index = cursor++;
      if (!slots[index] || !equal(slots[index].dependencies, dependencies)) {
        slots[index] = { value: factory(), dependencies };
      }
      return slots[index].value;
    },
    useCallback(callback, dependencies) { return hooks.useMemo(() => callback, dependencies); },
    useEffect(callback, dependencies) {
      const index = cursor++;
      if (!slots[index] || !equal(slots[index].dependencies, dependencies)) {
        const previous = slots[index];
        slots[index] = { dependencies, cleanup: previous?.cleanup };
        effects.push(() => {
          previous?.cleanup?.();
          slots[index].cleanup = callback();
        });
      }
    },
  };
  const bridge = {
    connect() { connected = true; bridge.emit('connection_status', { status: 'connected' }); },
    isConnected() { return connected; },
    on(name, callback) {
      if (!events.has(name)) events.set(name, new Set());
      events.get(name).add(callback);
      return () => events.get(name).delete(callback);
    },
    emit(name, data) { for (const callback of events.get(name) || []) callback(data); },
    sendCommand(text) {
      if (!connected) return false;
      calls.commands.push({ kind: 'text', text });
      return true;
    },
    sendVoiceCommand(text) {
      if (!connected) return false;
      calls.commands.push({ kind: 'voice', text });
      return true;
    },
    interrupt() { calls.interrupt++; return connected; },
    stopSpeech() { return Promise.resolve(); },
  };
  const voice = {
    mode: 'idle', callbacks: {},
    listener: { onCommand(callback) { voice.callbacks.command = callback; } },
    setContinuousMode() {},
    startListening() {
      calls.voiceStarts++;
      voice.mode = 'active';
      voice.callbacks.stateChange?.('active');
      voice.callbacks.transcript?.({ final: '', interim: 'Listening…' });
      return Promise.resolve(true);
    },
    stop() { calls.stops++; voice.mode = 'idle'; voice.callbacks.stateChange?.('idle'); },
    stopSpeaking() { voice.mode = 'idle'; },
    speak(text) { calls.speech.push(text); voice.callbacks.stateChange?.('speaking'); return Promise.resolve(); },
  };
  for (const name of ['StateChange', 'Transcript', 'Error']) {
    voice[`on${name}`] = callback => { voice.callbacks[name[0].toLowerCase() + name.slice(1)] = callback; };
  }
  const previousWindow = global.window;
  const previousAudio = global.Audio;
  const previousTest = global.__desktopTest;
  global.__desktopTest = { hooks, bridge, voice, agent };
  global.window = {
    addEventListener(name, callback) {
      if (!windowEvents.has(name)) windowEvents.set(name, new Set());
      windowEvents.get(name).add(callback);
    },
    removeEventListener(name, callback) { windowEvents.get(name)?.delete(callback); },
  };
  global.Audio = class { play() { return Promise.resolve(); } pause() {} };
  const filename = resolve(__dirname, 'desktop-mode.fixture.cjs');
  const componentModule = new Module(filename);
  componentModule._compile(componentSource, filename);
  const Component = componentModule.exports.default;
  const flush = () => {
    let count = 0;
    do {
      dirty = false;
      cursor = 0;
      tree = Component({ onExit() {} });
      const pending = effects;
      effects = [];
      pending.forEach(effect => effect());
      assert(++count < 30, 'component should settle after state changes');
    } while (dirty);
    return tree;
  };
  const nodes = root => {
    if (Array.isArray(root)) return root.flatMap(nodes);
    if (root == null || typeof root === 'boolean') return [];
    if (typeof root !== 'object') return [root];
    return [root, ...root.children.flatMap(nodes)];
  };
  const find = (type, matches = () => true) => {
    const node = nodes(tree).find(item => item?.type === type && matches(item.props));
    assert(node, `expected ${type} control`);
    return node;
  };
  const text = () => nodes(tree).map(item => typeof item === 'object' ? item.props.content || '' : item).join(' ');
  const input = value => { find('textarea').props.onChange({ target: { value } }); flush(); };
  const send = value => {
    input(value);
    find('form').props.onSubmit({ preventDefault() {} });
    flush();
  };
  const emit = (name, data) => { bridge.emit(name, data); flush(); };
  const clickButton = label => {
    const button = find('button', props => props['aria-label'] === label);
    assert(!button.props.disabled, `${label} should be enabled`);
    const result = button.props.onClick();
    flush();
    return result;
  };
  const destroy = () => {
    slots.forEach(slot => slot?.cleanup?.());
    global.window = previousWindow;
    global.Audio = previousAudio;
    global.__desktopTest = previousTest;
  };
  flush();
  return {
    calls, voice, agent, flush, find, text, send, input, emit, clickButton, destroy,
    nodes: () => nodes(tree), events, windowEvents,
    disconnect() { connected = false; emit('connection_status', { status: 'disconnected' }); },
    reconnect() { bridge.connect(); flush(); },
  };
}

function useHarness(context) {
  const harness = createHarness();
  context.after(() => harness.destroy());
  return harness;
}

test('mount shows only server connection state and does not start the microphone', context => {
  const h = useHarness(context);
  assert(h.text().includes('Connected'));
  assert.equal(h.calls.voiceStarts, 0);
  assert.equal(h.nodes().filter(node => node?.type === 'article').length, 0);
  h.agent.connected = false; h.flush();
  assert(h.text().includes('Disconnected'));
});

test('text requests use a durable task with repeated conversation identity and selected provider', async context => {
  const h = useHarness(context);
  h.send('Inspect my workspace'); await new Promise(resolve => setImmediate(resolve)); h.flush();
  assert.equal(h.calls.commands[0].text, 'Inspect my workspace');
  assert.equal(h.calls.commands[0].options.mode, 'agent');
  assert.equal(h.calls.commands[0].options.provider, 'groq');
  assert.equal(h.calls.commands[0].options.model, 'test-model');
  const id = h.calls.commands[0].options.conversation_id;
  assert(id);
  h.send('Read another file'); await new Promise(resolve => setImmediate(resolve)); h.flush();
  assert.equal(h.calls.commands[1].options.conversation_id, id);
});

test('failed submission preserves the draft and exposes the real service error', async context => {
  const h = useHarness(context);
  h.agent.sendMessage = async () => { throw new Error('Provider unavailable'); };
  h.flush(); h.send('Keep this draft'); await new Promise(resolve => setImmediate(resolve)); h.flush();
  assert.equal(h.find('textarea').props.value, 'Keep this draft');
  assert(h.text().includes('Provider unavailable'));
});

test('stop sends task cancellation and leaves completed labels to server state', async context => {
  const h = useHarness(context);
  h.agent.isThinking = true;
  h.agent.agentMessages = [{ id: 'answer', role: 'assistant', content: 'Partial answer', status: 'running' }]; h.flush();
  await h.clickButton('Stop response'); h.flush();
  assert.equal(h.calls.interrupt, 1);
  assert(h.text().includes('Partial answer'));
  assert(!h.text().includes('completed'));
});

test('microphone starts explicitly and transcript uses the durable task route', async context => {
  const h = useHarness(context);
  await h.clickButton('Start microphone'); h.flush();
  assert.equal(h.calls.voiceStarts, 1);
  h.voice.callbacks.command('Voice request'); await new Promise(resolve => setImmediate(resolve)); h.flush();
  assert.equal(h.calls.commands[0].text, 'Voice request');
});

test('microphone errors keep text available', async context => {
  const h = useHarness(context);
  h.voice.startListening = () => { h.voice.callbacks.error('mic-denied'); return Promise.resolve(false); };
  await h.clickButton('Start microphone'); h.flush();
  assert(h.text().includes('Microphone access was denied'));
  h.send('Typed fallback'); await new Promise(resolve => setImmediate(resolve)); h.flush();
  assert.equal(h.calls.commands[0].text, 'Typed fallback');
});

test('unmount removes keyboard subscriptions and releases microphone callbacks', context => {
  const h = createHarness(); h.destroy();
  assert.equal([...h.windowEvents.values()].reduce((count, listeners) => count + listeners.size, 0), 0);
  assert.equal(h.voice.callbacks.command, null);
  assert.equal(h.voice.callbacks.transcript, null);
  assert.equal(h.voice.callbacks.error, null);
});
