/** Explicit microphone capture. Only the authenticated backend transcribes audio. */
import { backendClient } from '../BackendClient';

const MAX_RECORDING_MS = 30000;
const TRANSCRIPTION_TIMEOUT_MS = 65000;
const own = (object, key) => Object.prototype.hasOwnProperty.call(object, key);

export class VoiceListener {
  constructor(options = {}) {
    this.client = options.client || backendClient;
    this.mediaDevices = options.mediaDevices || globalThis.navigator?.mediaDevices;
    this.Recorder = options.MediaRecorderClass || globalThis.MediaRecorder;
    this.AudioContext = own(options, 'AudioContextClass') ? options.AudioContextClass : (globalThis.AudioContext || globalThis.webkitAudioContext);
    this.state = 'idle';
    this.continuousMode = !!options.continuousMode;
    this.audioLevel = 0;
    this.mediaStream = null;
    this.audioContext = null;
    this.analyser = null;
    this._mediaRecorder = null;
    this._session = null;
    this._generation = 0;
    this._shouldBeListening = false;
    this._restartTimer = null;
  }

  onTranscript(callback) { this._onTranscript = callback; return this; }
  onCommand(callback) { this._onCommand = callback; return this; }
  onEmotion(callback) { this._onEmotion = callback; return this; }
  onStateChange(callback) { this._onStateChange = callback; return this; }
  onAudioLevel(callback) { this._onAudioLevel = callback; return this; }
  onError(callback) { this._onError = callback; return this; }
  setContinuousMode(enabled) { this.continuousMode = !!enabled; }
  getContinuousMode() { return this.continuousMode; }
  getState() { return this.state; }
  isListening() { return this.state === 'listening' || this.state === 'speech_detected'; }
  isSupported() { return !!(this.mediaDevices?.getUserMedia && this.Recorder); }
  _current(session) { return this._session === session && this._generation === session.id; }
  _setState(state) { if (this.state !== state) { this.state = state; this._onStateChange?.(state); } }

  async startListening(language = 'en-US') {
    if (this._session) return this.isListening();
    clearTimeout(this._restartTimer);
    this._shouldBeListening = true;
    const session = { id: ++this._generation, language, chunks: [], stream: null, recorder: null, transcribe: true, processed: false, stopping: false };
    this._session = session;
    this._setState('requesting');
    try {
      if (!this.isSupported()) throw new Error('Microphone recording is unavailable. Open Lyra in its desktop app or a browser with microphone access on localhost.');
      const stream = await this.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
      if (!this._current(session)) { stream.getTracks().forEach(track => track.stop()); return false; }
      this.mediaStream = session.stream = stream;
      const mimeType = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus'].find(type => this.Recorder.isTypeSupported?.(type));
      const recorder = new this.Recorder(stream, mimeType ? { mimeType } : undefined);
      session.recorder = this._mediaRecorder = recorder;
      session.mimeType = recorder.mimeType || mimeType || 'audio/webm';
      recorder.ondataavailable = event => { if (this._current(session) && session.transcribe && event.data?.size > 0) session.chunks.push(event.data); };
      recorder.onstop = () => { this._releaseCapture(session); this._transcribeRecordedAudio(session); };
      recorder.onerror = event => this._fail(session, new Error(event.error?.message || 'Microphone recording failed. Check that the microphone is still connected.'));
      recorder.start(100);
      this._setState('listening');
      this._onTranscript?.({ final: '', interim: 'Recording — click stop to transcribe.' });
      this._startMeter(session);
      session.safetyTimer = setTimeout(() => this._stopRecording(session, true), MAX_RECORDING_MS);
      return true;
    } catch (error) {
      if (!this._current(session)) return false;
      const message = error.name === 'NotAllowedError' || error.name === 'SecurityError'
        ? 'Microphone access was denied. Allow microphone access for Lyra in system privacy settings and this browser, then try again.'
        : error.name === 'NotFoundError' ? 'No microphone was found. Connect a microphone and try again.'
          : error.name === 'NotReadableError' ? 'The microphone is busy or unavailable. Close other recording apps and try again.'
            : error.message || 'Could not start the microphone.';
      this._fail(session, new Error(message));
      return false;
    }
  }

  _startMeter(session) {
    // Recording still works if Web Audio analysis is unavailable.
    if (!this.AudioContext) return;
    try {
      const context = new this.AudioContext();
      session.audioContext = this.audioContext = context;
      context.resume?.().catch?.(() => {});
      const source = context.createMediaStreamSource(session.stream);
      const analyser = context.createAnalyser();
      analyser.fftSize = 512;
      source.connect(analyser);
      session.source = source;
      this.analyser = analyser;
      const samples = new Uint8Array(analyser.fftSize);
      let speechAt = 0, lastSpeechAt = 0;
      session.levelTimer = setInterval(() => {
        if (!this._current(session) || session.stopping) return;
        analyser.getByteTimeDomainData(samples);
        const rms = Math.sqrt(samples.reduce((sum, value) => sum + ((value - 128) / 128) ** 2, 0) / samples.length);
        this.audioLevel = Math.min(1, rms * 5);
        this._onAudioLevel?.(this.audioLevel);
        const now = Date.now();
        if (rms > 0.02) { speechAt ||= now; lastSpeechAt = now; }
        // Silence can finish a spoken turn; manual stop always submits regardless of level.
        if (speechAt && now - speechAt > 1000 && now - lastSpeechAt > 1600) this._stopRecording(session, true);
      }, 80);
    } catch { /* The level meter is optional; MediaRecorder remains the capture source. */ }
  }

  _releaseCapture(session) {
    clearInterval(session.levelTimer);
    clearTimeout(session.safetyTimer);
    if (session.stream) { session.stream.getTracks().forEach(track => track.stop()); session.stream = null; }
    session.source?.disconnect?.();
    session.source = null;
    if (session.audioContext) { session.audioContext.close?.().catch?.(() => {}); session.audioContext = null; }
    if (this._current(session)) {
      this.mediaStream = null; this.audioContext = null; this.analyser = null;
      this.audioLevel = 0; this._onAudioLevel?.(0);
    }
  }

  _stopRecording(session, transcribe) {
    if (!this._current(session) || session.stopping) return;
    session.stopping = true;
    session.transcribe = transcribe;
    if (transcribe) this._setState('transcribing');
    if (session.recorder && session.recorder.state !== 'inactive') {
      try { session.recorder.stop(); }
      catch (error) { this._fail(session, error); }
    }
    this._releaseCapture(session);
  }

  _stopCapturing() { if (this._session) this._stopRecording(this._session, true); }

  stop(transcribe = true) {
    this._shouldBeListening = false;
    clearTimeout(this._restartTimer);
    const session = this._session;
    if (session && transcribe && this.isListening()) { this._stopRecording(session, true); return; }
    if (session) {
      session.transcribe = false;
      session.abort?.abort();
      clearTimeout(session.requestTimer);
      this._stopRecording(session, false);
      this._releaseCapture(session);
    }
    ++this._generation;
    this._session = null; this._mediaRecorder = null;
    this._setState('idle');
    this._onTranscript?.({ final: '', interim: '' });
  }

  async _transcribeRecordedAudio(session) {
    if (!this._current(session) || !session.transcribe || session.processed) return;
    session.processed = true;
    this._setState('transcribing');
    this._onTranscript?.({ final: '', interim: 'Transcribing recording…' });
    try {
      const blob = new Blob(session.chunks, { type: session.mimeType });
      session.chunks = [];
      if (!blob.size) throw new Error('No audio was recorded. Check your microphone input and try again.');
      const audio = await this._blobToBase64(blob);
      if (!this._current(session)) return;
      session.abort = new AbortController();
      session.requestTimer = setTimeout(() => { session.timedOut = true; session.abort.abort(); }, TRANSCRIPTION_TIMEOUT_MS);
      const result = await this.client.request('/api/stt', { method: 'POST', body: { audio, format: session.mimeType, language: session.language.split(/[-_]/)[0].toLowerCase() }, signal: session.abort.signal });
      if (!this._current(session)) return;
      if (result.error) throw new Error(typeof result.error === 'string' ? result.error : result.error.message || 'Speech transcription failed.');
      const text = result.text?.trim();
      if (!text) throw new Error('No speech was detected. Check your input volume, speak clearly, and try again.');
      clearTimeout(session.requestTimer);
      this._session = null; this._mediaRecorder = null;
      this._setState('idle');
      this._onTranscript?.({ final: text, interim: '' });
      this._onCommand?.(text, null);
      if (this.continuousMode && this._shouldBeListening) this._restartTimer = setTimeout(() => this.startListening(session.language), 300);
    } catch (error) {
      if (this._current(session)) this._fail(session, session.timedOut ? new Error('Speech transcription timed out. Check the backend connection and try a shorter recording.') : error);
    } finally { clearTimeout(session.requestTimer); }
  }

  _fail(session, error) {
    if (!this._current(session)) return;
    session.transcribe = false;
    session.abort?.abort();
    clearTimeout(session.requestTimer);
    this._stopRecording(session, false);
    this._releaseCapture(session);
    this._session = null; this._mediaRecorder = null;
    this._shouldBeListening = false;
    this._setState('error');
    this._onTranscript?.({ final: '', interim: '' });
    this._onError?.(error.message || 'Voice transcription failed. Please try again.');
  }

  async _blobToBase64(blob) {
    const bytes = new Uint8Array(await blob.arrayBuffer());
    let binary = '';
    for (let offset = 0; offset < bytes.length; offset += 8192) binary += String.fromCharCode(...bytes.subarray(offset, offset + 8192));
    return globalThis.btoa(binary);
  }
}

export const voiceListener = new VoiceListener();
export default voiceListener;
