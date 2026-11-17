const assert = require('node:assert/strict');
const { before, test } = require('node:test');
const { resolve } = require('node:path');
const Module = require('node:module');
const esbuild = require('esbuild');

const workspace = resolve(__dirname, '../..');
let source;

before(async () => {
  const build = await esbuild.build({
    entryPoints: [resolve(workspace, 'src/components/DesktopMode/AITerminal.jsx')],
    bundle: true, platform: 'node', format: 'cjs', jsx: 'transform', write: false,
    plugins: [{ name: 'terminal-test-boundaries', setup(builder) {
      builder.onResolve({ filter: /.*/ }, args => {
        if (!args.importer || args.path.includes('TerminalSession')) return undefined;
        return { path: args.path, namespace: 'boundary' };
      });
      builder.onLoad({ filter: /.*/, namespace: 'boundary' }, ({ path }) => {
        let contents;
        if (path === 'react') contents = 'export default globalThis.__terminalTest.hooks;export const {useState,useRef,useEffect,useCallback,useMemo}=globalThis.__terminalTest.hooks;';
        else if (path.includes('useLyraAgent')) contents = 'export const useLyraAgent=()=>globalThis.__terminalTest.agent;';
        else if (path.includes('ModelRouter')) contents = 'export const ModelRouter={getConfig:()=>({provider:"test-provider",model:"test-model"})};';
        else if (path.includes('BackendClient')) contents = 'export const backendClient=globalThis.__terminalTest.client;';
        else if (path.includes('VoiceListener')) contents = 'export const voiceListener={onCommand(){},onError(){},stop(){}};';
        else if (path.includes('TaskController')) contents = 'export const ACTIVE_TASK_STATUSES=new Set(["queued","running","awaiting_approval"]);';
        else if (path.includes('VoiceAssistant')) contents = 'export default function VoiceAssistant() {}';
        else if (path.includes('ToolConfirmationCard')) contents = 'export default function ApprovalCard() {}';
        else if (path.includes('MarkdownContent')) contents = 'export default function MarkdownContent() {}';
        else if (path === 'lucide-react') contents = 'export const Terminal=()=>null,Mic=()=>null,Trash2=()=>null,Square=()=>null,CornerDownLeft=()=>null,ArrowUp=()=>null,ArrowUpRight=()=>null,ChevronRight=()=>null,FolderOpen=()=>null,Crosshair=()=>null,RefreshCw=()=>null,Plus=()=>null,Check=()=>null,Command=()=>null,MessageSquare=()=>null,ShieldCheck=()=>null,Clock3=()=>null,ChevronDown=()=>null;';
        else contents = 'export default function Boundary() {}';
        return { contents, loader: 'js' };
      });
    } }],
  });
  source = build.outputFiles[0].text;
});

function harness(context) {
  const slots = []; let cursor = 0; let effects = []; let dirty = false; let tree;
  const calls = { tasks: [], raw: [], stops: [], resumes: [], refresh: 0 };
  const agent = {
    connected: true, recovering: false, isThinking: false, error: '', tasks: [], details: {},
    async sendMessage(text, options) { calls.tasks.push({ text, options }); return { id: 'task', conversation_id: options.conversation_id }; },
    async cancelTask(id) { calls.stops.push(id); }, async stopResponse() { calls.stops.push('all'); },
    async resumeTask(id) { calls.resumes.push(id); }, confirmTool() {}, refresh() { calls.refresh++; },
  };
  const client = { async request() { return { cwd: '/default-workspace' }; }, async runTool(tool, args, options) { calls.raw.push({ tool, args, options }); return { id: 'raw' }; } };
  const equal = (a, b) => a && b && a.length === b.length && a.every((value, index) => Object.is(value, b[index]));
  const hooks = {
    createElement(type, props, ...children) { return { type, props: props || {}, children }; },
    useState(initial) { const index = cursor++; if (!slots[index]) slots[index] = { value: typeof initial === 'function' ? initial() : initial }; return [slots[index].value, update => { const next = typeof update === 'function' ? update(slots[index].value) : update; if (!Object.is(next, slots[index].value)) { slots[index].value = next; dirty = true; } }]; },
    useRef(initial) { const index = cursor++; if (!slots[index]) slots[index] = { value: { current: initial } }; return slots[index].value; },
    useMemo(factory, dependencies) { const index = cursor++; if (!slots[index] || !equal(slots[index].dependencies, dependencies)) slots[index] = { value: factory(), dependencies }; return slots[index].value; },
    useCallback(callback, dependencies) { return hooks.useMemo(() => callback, dependencies); },
    useEffect(callback, dependencies) { const index = cursor++; if (!slots[index] || !equal(slots[index].dependencies, dependencies)) { const old = slots[index]; slots[index] = { dependencies, cleanup: old?.cleanup }; effects.push(() => { old?.cleanup?.(); slots[index].cleanup = callback(); }); } },
  };
  const previous = { test: global.__terminalTest, window: global.window };
  const storage = new Map();
  global.__terminalTest = { hooks, agent, client };
  global.window = { localStorage: { getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value) } };
  const filename = resolve(__dirname, 'terminal-chat.fixture.cjs');
  const module = new Module(filename); module._compile(source, filename); const Component = module.exports.default;
  const props = { conversationId: 'conv_work', selectedModel: 'selected' };
  const flush = () => { let count = 0; do { dirty = false; cursor = 0; tree = Component(props); const pending = effects; effects = []; pending.forEach(callback => callback()); assert(++count < 30, 'terminal should settle'); } while (dirty); };
  const nodes = root => Array.isArray(root) ? root.flatMap(nodes) : root == null || typeof root === 'boolean' ? [] : typeof root === 'object' ? [root, ...(typeof root.type === 'function' && root.type.name === 'StepOutput' ? nodes(root.type(root.props)) : root.children.flatMap(nodes))] : [root];
  const find = (type, match = () => true) => { const node = nodes(tree).find(node => node?.type === type && match(node.props)); assert(node, `expected ${type} control`); return node; };
  const change = (label, value) => { const node = nodes(tree).find(node => node?.props?.['aria-label'] === label); assert(node, `expected ${label}`); node.props.onChange({ target: { value } }); flush(); };
  const click = label => { const node = find('button', props => props['aria-label'] === label); assert(!node.props.disabled, `${label} should be enabled`); const result = node.props.onClick(); flush(); return result; };
  const submit = async text => { const input = nodes(tree).find(node => node?.type === 'textarea' || node?.props?.['aria-label'] === 'Shell command'); assert(input, 'terminal has a composer'); input.props.onChange({ target: { value: text } }); flush(); await find('form').props.onSubmit({ preventDefault() {} }); await new Promise(resolve => setImmediate(resolve)); flush(); };
  const text = () => nodes(tree).map(node => typeof node === 'object' ? node.props.content || '' : node).join(' ');
  flush();
  context.after(() => { slots.forEach(slot => slot?.cleanup?.()); global.__terminalTest = previous.test; global.window = previous.window; });
  return { calls, agent, client, props, change, click, submit, flush, find, text, nodes: () => nodes(tree) };
}

test('ordinary instructions create a terminal agent task with working directory and assessment context', async context => {
  const h = harness(context);
  h.change('Working directory', '/Users/analyst/lab');
  h.change('Assessment context', 'Local training application only');
  await h.submit('Inspect this project and explain its local attack surface');
  assert.equal(h.calls.tasks.length, 1);
  assert.equal(h.calls.tasks[0].text, 'Inspect this project and explain its local attack surface');
  assert.equal(h.calls.tasks[0].options.mode, 'terminal');
  assert.deepEqual(h.calls.tasks[0].options.metadata, { terminal: true, cwd: '/Users/analyst/lab', scope: 'Local training application only' });
  assert.notEqual(h.calls.tasks[0].options.conversation_id, 'conv_work');
  assert.equal(h.calls.tasks[0].options.provider, 'test-provider');
  assert.equal(h.calls.tasks[0].options.model, 'test-model');
  assert.equal(h.calls.raw.length, 0);
});

test('a terminal conversation identity survives repeated requests and uses explicit raw-command mode', async context => {
  const h = harness(context);
  await h.submit('Describe the directory');
  const firstId = h.calls.tasks[0].options.conversation_id;
  await h.submit('Now identify local configuration files');
  assert.equal(h.calls.tasks[1].options.conversation_id, firstId);
  await h.click('Shell command mode');
  h.change('Working directory', '/Users/analyst/lab');
  await h.submit('pwd');
  assert.equal(h.calls.raw.length, 1);
  assert.equal(h.calls.raw[0].tool, 'execute_command');
  assert.deepEqual(h.calls.raw[0].args, { command: 'pwd', cwd: '/Users/analyst/lab' });
  assert.equal(h.calls.raw[0].options.conversation_id, firstId);
});

test('agent tasks show the instruction, actual command, separate streams and exit code', async context => {
  const h = harness(context); await h.submit('Inspect local tools');
  const id = h.calls.tasks[0].options.conversation_id;
  h.agent.tasks = [{ id: 'task', conversation_id: id, prompt: 'Inspect local tools', status: 'failed', created_at: '2026-10-16', result: { response: 'One tool is absent.' } }];
  h.agent.details = { task: { task: h.agent.tasks[0], approvals: [], events: [
    { seq: 1, type: 'tool_status', payload: { tool: 'execute_command', arguments: { command: 'command -v nmap', cwd: '/lab' }, status: 'running', result: {} } },
    { seq: 2, type: 'tool_status', payload: { tool: 'execute_command', arguments: { command: 'command -v nmap', cwd: '/lab' }, status: 'failed', result: { success: false, stdout: 'actual stdout', stderr: 'actual stderr', exit_code: 1, cwd: '/lab' }, receipt: { duration_ms: 140 } } },
  ] } }; h.flush();
  assert(h.text().includes('Inspect local tools'));
  assert(h.text().includes('command -v nmap'));
  assert(h.text().includes('actual stdout'));
  assert(h.text().includes('actual stderr'));
  assert.match(h.text(), /exit\s+1/i);
  assert(h.text().includes('One tool is absent.'));
  assert.equal(h.nodes().filter(node => node?.type === 'pre' && node.children.includes('actual stdout')).length, 1);
});

test('voice dictation fills the draft for review without translating or executing', async context => {
  const h = harness(context);
  const voice = h.nodes().find(node => typeof node?.type === 'function' && node.type.name === 'VoiceAssistant');
  assert(voice, 'shared recording component should be present');
  voice.props.onTranscript('Review the local web logs'); h.flush();
  assert.equal(h.find('textarea').props.value, 'Review the local web logs');
  assert.equal(h.calls.tasks.length, 0);
  assert.equal(h.calls.raw.length, 0);
});

test('submission failure preserves the draft and disconnected state blocks execution', async context => {
  const h = harness(context); h.agent.sendMessage = async () => { throw new Error('Model unavailable'); }; h.flush();
  await h.submit('Keep this instruction');
  assert.equal(h.find('textarea').props.value, 'Keep this instruction');
  assert(h.text().includes('Model unavailable'));
  h.agent.connected = false; h.flush();
  assert(h.find('button', props => props['aria-label'] === 'Send terminal instruction').props.disabled);
});

test('active terminal work can be cancelled and interrupted work can resume', async context => {
  const h = harness(context); await h.submit('Inspect files'); const id = h.calls.tasks[0].options.conversation_id;
  h.agent.tasks = [{ id: 'running', conversation_id: id, prompt: 'Inspect files', status: 'running' }, { id: 'paused', conversation_id: id, prompt: 'Earlier work', status: 'interrupted' }]; h.flush();
  await h.click('Stop terminal task');
  assert.deepEqual(h.calls.stops, ['running']);
  await h.click('Resume terminal task');
  assert.deepEqual(h.calls.resumes, ['paused']);
});

test('clearing older turns leaves active approvals visible and actionable', async context => {
  const h = harness(context); await h.submit('Check the local tool version'); const id = h.calls.tasks[0].options.conversation_id;
  const approval = { request_id: 'approval-command', tool: 'execute_command', arguments: { command: 'nmap --version', cwd: '/lab' } };
  h.agent.tasks = [{ id: 'old', conversation_id: id, prompt: 'An earlier instruction', status: 'completed' }, { id: 'pending', conversation_id: id, prompt: 'Check the local tool version', status: 'awaiting_approval' }];
  h.agent.details = { pending: { task: h.agent.tasks[1], approvals: [approval], events: [] } }; h.flush();
  await h.click('Clear terminal view'); h.flush();
  assert(!h.text().includes('An earlier instruction'));
  assert(h.text().includes('Check the local tool version'));
  const card = h.nodes().find(node => typeof node?.type === 'function' && node.type.name === 'ApprovalCard');
  assert.equal(card?.props.confirmation.request_id, 'approval-command');
});

test('recovered tasks keep repeated commands separate and retain timeout output', async context => {
  const h = harness(context);
  h.agent.tasks = [{ id: 'restored', conversation_id: 'terminal_conv_work', prompt: 'Compare two local runs', status: 'failed' }];
  const args = { command: 'printf test', cwd: '/lab' };
  h.agent.details = { restored: { task: h.agent.tasks[0], approvals: [], events: [
    { seq: 1, type: 'tool_status', payload: { tool: 'execute_command', arguments: args, status: 'pending', result: {} } },
    { seq: 2, type: 'tool_status', payload: { tool: 'execute_command', arguments: args, status: 'completed', result: { stdout: 'first run', exit_code: 0 } } },
    { seq: 3, type: 'tool_status', payload: { tool: 'execute_command', arguments: args, status: 'pending', result: {} } },
    { seq: 4, type: 'tool_status', payload: { tool: 'execute_command', arguments: args, status: 'failed', result: { stdout: 'partial second run', stderr: 'timeout detail', error: 'Timed out', exit_code: -9 } } },
  ] } }; h.flush();
  assert.equal(h.nodes().filter(node => node?.type === 'section' && node.props['aria-label'] === 'Command execution').length, 2);
  assert(h.text().includes('first run'));
  assert(h.text().includes('partial second run'));
  assert(h.text().includes('timeout detail'));
  assert(h.text().includes('Timed out'));
  assert.equal(h.calls.tasks.length, 0, 'recovering saved tasks must never replay them');
});

test('recovery restores the last terminal context without replacing a newly edited directory', async context => {
  const h = harness(context);
  h.agent.tasks = [{ id: 'saved', conversation_id: 'terminal_conv_work', prompt: 'Earlier work', status: 'completed', metadata: { terminal: true, cwd: '/lab/evidence', scope: 'Training evidence only' } }]; h.flush();
  assert.equal(h.find('input', props => props['aria-label'] === 'Working directory').props.value, '/lab/evidence');
  assert.equal(h.find('input', props => props['aria-label'] === 'Assessment context').props.value, 'Training evidence only');
  h.change('Working directory', '/lab/new');
  h.agent.tasks = [...h.agent.tasks]; h.flush();
  assert.equal(h.find('input', props => props['aria-label'] === 'Working directory').props.value, '/lab/new');
});
