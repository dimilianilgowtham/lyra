/** The renderer talks only to Lyra's authenticated backend. Provider keys stay there. */
export class BackendClient {
  constructor(options = {}) {
    this.baseUrl = (options.baseUrl || import.meta.env?.VITE_BACKEND_URL || 'http://127.0.0.1:8100').replace(/\/$/, '');
    const destination = new URL(this.baseUrl);
    if (!['127.0.0.1', 'localhost', '[::1]'].includes(destination.hostname) || !['http:', 'https:'].includes(destination.protocol) || destination.username || destination.password) throw new Error('Lyra requires a local backend URL.');
    this.fetch = options.fetch || ((...args) => globalThis.fetch(...args));
    this.getToken = options.getToken || (() => globalThis.window?.lyra?.getBackendToken?.());
    this.session = null;
    this.token = null;
  }
  async authenticate() {
    if (!this.session) this.session = (async () => {
      this.token = await this.getToken();
      if (!this.token) {
        const response = await this.fetch(`${this.baseUrl}/api/session`, { credentials: 'include', signal: AbortSignal.timeout(10000) });
        if (!response.ok) throw new Error(`Backend session failed (HTTP ${response.status}).`);
      }
    })().catch(error => { this.session = null; throw error; });
    return this.session;
  }
  async request(path, options = {}) {
    if (!path.startsWith('/') || path.startsWith('//')) throw new Error('Use a backend-relative request path.');
    await this.authenticate();
    const headers = { ...options.headers };
    if (options.body !== undefined) headers['Content-Type'] = 'application/json';
    if (this.token) headers.Authorization = `Bearer ${this.token}`;
    const response = await this.fetch(`${this.baseUrl}${path}`, { ...options, headers, credentials: 'include', signal: options.signal || AbortSignal.timeout(20000), body: options.body === undefined ? undefined : JSON.stringify(options.body) });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      if (response.status === 401) { this.session = null; this.token = null; }
      throw new Error(typeof data.detail === 'string' ? data.detail : (typeof data.error === 'string' ? data.error : data.error?.message) || data.message || `Backend returned HTTP ${response.status}.`);
    }
    return data;
  }
  async websocketUrl() {
    await this.authenticate();
    const url = new URL('/ws', this.baseUrl);
    url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
    if (this.token) url.searchParams.set('token', this.token);
    return url.toString();
  }
  health() { return this.request('/api/health'); }
  createTask(body) { return this.request('/api/tasks', { method: 'POST', body: { ...body, user_id: 'default_user' } }); }
  runTool(tool, args, options = {}) { return this.createTask({ ...options, mode: 'agent', tool, arguments: args, prompt: options.prompt || `Run ${tool}` }); }
  listTasks() { return this.request('/api/tasks'); }
  getTask(id) { return this.request(`/api/tasks/${encodeURIComponent(id)}`); }
  cancelTask(id) { return this.request(`/api/tasks/${encodeURIComponent(id)}/cancel`, { method: 'POST' }); }
  resumeTask(id) { return this.request(`/api/tasks/${encodeURIComponent(id)}/resume`, { method: 'POST' }); }
  approveTask(id, requestId, approved) { return this.request(`/api/tasks/${encodeURIComponent(id)}/approvals/${encodeURIComponent(requestId)}`, { method: 'POST', body: { approved } }); }
  listConversations() { return this.request('/api/conversations?user_id=default_user'); }
  getConversationMessages(id) { return this.request(`/api/conversations/${encodeURIComponent(id)}/messages`); }
  importConversation(record) { return this.request('/api/conversations/import', { method: 'POST', body: { record, user_id: 'default_user' } }); }
  saveConversation(record) { return this.request('/api/conversations', { method: 'POST', body: { record, user_id: 'default_user' } }); }
  deleteConversation(id) { return this.request(`/api/conversations/${encodeURIComponent(id)}`, { method: 'DELETE' }); }
  listReminders() { return this.request('/api/reminders'); }
  createReminder(text, dueAt) { return this.request('/api/reminders', { method: 'POST', body: { text, due_at: dueAt } }); }
  deleteReminder(id) { return this.request(`/api/reminders/${encodeURIComponent(id)}`, { method: 'DELETE' }); }
}
export const backendClient = new BackendClient();
export default backendClient;
