const ACTIVE = new Set(['queued', 'running', 'awaiting_approval']);
const FINISHED_STEPS = new Set(['completed', 'failed', 'denied', 'cancelled']);
export function terminalConversationId(parentId, storage = globalThis.window?.localStorage) {
  if (parentId) return parentId.startsWith('terminal_') ? parentId : `terminal_${parentId}`;
  try { const saved = storage?.getItem('lyra.terminal.conversation'); if (saved?.startsWith('terminal_')) return saved; } catch {}
  const id = `terminal_${globalThis.crypto.randomUUID()}`;
  try { storage?.setItem('lyra.terminal.conversation', id); } catch {}
  return id;
}
/** Collapse progress into a receipt while preserving repeated commands as separate steps. */
export function terminalToolSteps(detail) {
  const steps = [];
  for (const event of detail?.events || []) {
    if (event.type !== 'tool_status' || !event.payload?.tool) continue;
    const payload = event.payload;
    const args = payload.arguments || payload.args || payload.receipt?.arguments || {};
    const signature = `${payload.tool}:${JSON.stringify(args)}`;
    let step = payload.status === 'pending' ? null : [...steps].reverse().find(item => item.signature === signature && !FINISHED_STEPS.has(item.status));
    if (!step) { step = { id: `${detail.task?.id || 'task'}:${event.seq}`, signature, tool: payload.tool, arguments: args }; steps.push(step); }
    Object.assign(step, { status: payload.status || 'pending', result: payload.result, receipt: payload.receipt || {}, seq: event.seq });
  }
  return steps;
}
export function terminalResponse(detail, task = detail?.task) {
  if (task?.result?.response) return task.result.response;
  let text = '';
  for (const event of detail?.events || []) {
    const payload = event.payload || {};
    if (event.type === 'token') text = payload.text ?? (text + (payload.token || ''));
    if (event.type === 'agent_response' || event.type === 'ai_response') text = payload.text || payload.response || text;
  }
  return text;
}
export function terminalIsActive(task) { return ACTIVE.has(task.status); }
export function terminalStepLabel(step) {
  if (step.tool === 'execute_command') return step.arguments.command || 'Shell command';
  const path = step.arguments.filepath || step.arguments.path || step.arguments.directory;
  return `${step.tool.replaceAll('_', ' ')}${path ? ` · ${path}` : ''}`;
}
