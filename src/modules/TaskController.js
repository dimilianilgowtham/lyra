import { BackendClient, backendClient } from './BackendClient';
export { BackendClient };
export const ACTIVE_TASK_STATUSES = new Set(['queued', 'running', 'awaiting_approval']);
/** Shared durable task state. Polls never overlap; failure preserves the last real state. */
export class TaskController {
  constructor(client = backendClient, options = {}) {
    this.client = client;
    this.schedule = options.schedule || ((...args) => globalThis.setTimeout(...args));
    this.unschedule = options.unschedule || ((...args) => globalThis.clearTimeout(...args));
    this.revisions = new Map(); this.listeners = new Set(); this.timers = new Map(); this.inFlight = new Map(); this.failures = new Map();
    this.state = { tasks: [], details: {}, connected: false, health: null, error: '', recovering: false };
    this.recovery = null;
  }
  snapshot() { return this.state; }
  subscribe(callback) { this.listeners.add(callback); return () => this.listeners.delete(callback); }
  update(changes) { this.state = { ...this.state, ...changes }; this.listeners.forEach(callback => callback(this.state)); }
  putTask(task) {
    if (!task?.id) throw new Error('The backend returned an invalid task.');
    this.update({ tasks: [task, ...this.state.tasks.filter(item => item.id !== task.id)].sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || ''))) });
  }
  async recover() {
    if (this.recovery) return this.recovery;
    this.update({ recovering: true });
    this.recovery = (async () => {
      try {
        const [health, data] = await Promise.all([this.client.health(), this.client.listTasks()]);
        this.update({ health, connected: true, error: '', tasks: data.tasks || [] });
        await Promise.allSettled(this.state.tasks.map(task => this.poll(task.id)));
      } catch (error) { this.update({ connected: false, error: error.message }); throw error; }
      finally { this.recovery = null; this.update({ recovering: false }); }
    })();
    return this.recovery;
  }
  async start(body) {
    const response = body.tool ? await this.client.runTool(body.tool, body.arguments, body) : await this.client.createTask(body);
    const task = response.task || response;
    this.putTask(task); this.update({ connected: true, error: '' });
    await this.poll(task.id);
    return task;
  }
  async poll(id) {
    if (this.inFlight.has(id)) return this.inFlight.get(id);
    this.unschedule(this.timers.get(id)); this.timers.delete(id);
    const revision = this.revisions.get(id) || 0;
    const pending = (async () => {
      try {
        const detail = await this.client.getTask(id);
        if (revision !== (this.revisions.get(id) || 0)) return null;
        this.putTask(detail.task); this.failures.delete(id);
        this.update({ details: { ...this.state.details, [id]: detail }, connected: true, error: '' });
        if (ACTIVE_TASK_STATUSES.has(detail.task.status)) this.timers.set(id, this.schedule(() => this.poll(id), 1200));
        return detail;
      } catch (error) {
        const attempts = (this.failures.get(id) || 0) + 1; this.failures.set(id, attempts);
        this.update({ connected: false, error: `Task updates unavailable: ${error.message}` });
        if (attempts < 4) this.timers.set(id, this.schedule(() => this.poll(id), attempts * 3000));
        return null;
      } finally { this.inFlight.delete(id); }
    })();
    this.inFlight.set(id, pending);
    return pending;
  }
  async approve(id, requestId, approved) {
    const result = await this.client.approveTask(id, requestId, approved);
    if (result.success === false) throw new Error(result.error || 'The approval was not accepted.');
    await this.poll(id);
  }
  async cancel(id) { const result = await this.client.cancelTask(id); this.revisions.set(id, (this.revisions.get(id) || 0) + 1); this.unschedule(this.timers.get(id)); this.timers.delete(id); this.putTask(result.task || result); if (this.inFlight.has(id)) await this.inFlight.get(id); await this.poll(id); }
  async resume(id) { const result = await this.client.resumeTask(id); this.putTask(result.task || result); await this.poll(id); }
  stop() { this.timers.forEach(timer => this.unschedule(timer)); this.timers.clear(); }
}
export function taskMessages(detail) {
  if (!detail?.task) return [];
  const { task, events = [], approvals = [] } = detail;
  const messages = [];
  const decisions = new Map(events.filter(event => event.type === 'tool_approval_resolved').map(event => [event.payload?.request_id, event.payload?.approved]));
  if (task.prompt) messages.push({ id: `${task.id}:user`, task_id: task.id, role: 'user', content: task.prompt });
  const pending = new Map(approvals.filter(item => item.approved === undefined || item.approved === null).map(item => [item.request_id, item]));
  let text = '';
  for (const event of events) {
    const payload = event.payload || {};
    if (event.type === 'tool_approval_request') {
      const confirmation = payload.confirmation || payload;
      const recorded = approvals.find(item => item.request_id === confirmation.request_id);
      messages.push({ id: `${task.id}:approval:${confirmation.request_id}`, task_id: task.id, role: 'tool_call', confirmation, resolved: !pending.has(confirmation.request_id), approved: recorded?.approved === true || decisions.get(confirmation.request_id) === true });
    }
    if (event.type === 'tool_status' && payload.result !== undefined) messages.push({ id: `${task.id}:receipt:${event.seq}`, task_id: task.id, role: 'tool', tool: payload.tool, status: payload.status, content: payload.result, approved: payload.receipt?.approved === true, verified: payload.receipt?.verified === true });
    if (event.type === 'token') text = payload.text ?? (text + (payload.token || ''));
    if (['agent_response', 'ai_response'].includes(event.type)) text = payload.text || payload.response || text;
  }
  for (const confirmation of pending.values()) if (!messages.some(message => message.confirmation?.request_id === confirmation.request_id)) messages.push({ id: `${task.id}:approval:${confirmation.request_id}`, task_id: task.id, role: 'tool_call', confirmation });
  text = task.result?.response || text;
  if (text) messages.push({ id: `${task.id}:assistant`, task_id: task.id, role: 'assistant', content: text, status: task.status, streaming: ACTIVE_TASK_STATUSES.has(task.status), provider: task.result?.provider || task.provider, model: task.result?.model || task.model });
  if (task.status === 'failed') messages.push({ id: `${task.id}:error`, task_id: task.id, role: 'error', content: task.error || task.result?.error || 'This task failed. See its tool receipts for details.' });
  return messages;
}
export const taskController = new TaskController();
