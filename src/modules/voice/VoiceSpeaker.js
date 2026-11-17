/** Speech playback reports real playback completion and falls back to backend audio. */
import { backendClient } from '../BackendClient';
const own = (object, key) => Object.prototype.hasOwnProperty.call(object, key);

export class VoiceSpeaker {
  constructor(options = {}) {
    this.client = options.client || backendClient;
    this.synth = own(options, 'synthesis') ? options.synthesis : globalThis.speechSynthesis;
    this.Utterance = options.UtteranceClass || globalThis.SpeechSynthesisUtterance;
    this.Audio = options.AudioClass || globalThis.Audio;
    this.isSpeaking = false;
    this.currentUtterance = null;
    this._preferredVoiceName = 'Samantha';
    this._bestVoice = null;
    this._operation = null;
    this._loadBestVoice();
    this.synth?.addEventListener?.('voiceschanged', () => this._loadBestVoice());
  }
  onStart(callback) { this._onStart = callback; return this; }
  onEnd(callback) { this._onEnd = callback; return this; }
  onError(callback) { this._onError = callback; return this; }
  getAvailableVoices() { return this.synth?.getVoices?.() || []; }
  _loadBestVoice(preferredName = this._preferredVoiceName, language = 'en-US') {
    const voices = this.getAvailableVoices();
    const matching = voices.filter(voice => voice.lang?.toLowerCase().startsWith(language.split('-')[0].toLowerCase()));
    this._bestVoice = matching.find(voice => voice.name?.toLowerCase().includes(preferredName.toLowerCase())) || matching.find(voice => voice.default) || matching[0] || null;
    return this._bestVoice;
  }
  setVoice(name) { this._preferredVoiceName = name; this._loadBestVoice(); }
  getVoiceName() { return this._bestVoice?.name || 'System voice'; }
  _current(operation) { return this._operation === operation; }
  _started(operation) {
    if (!this._current(operation) || operation.started) return;
    operation.started = true; this.isSpeaking = true;
    this._onStart?.(operation.text);
  }

  async speak(text, options = {}) {
    const cleanText = String(text || '').replace(/```[\s\S]*?```/g, ' Code block omitted. ').replace(/\[([^\]]+)\]\([^)]+\)/g, '$1').replace(/[*_#`~>]/g, '').trim().slice(0, 3000);
    if (!cleanText) return false;
    this.cancel();
    const operation = { text: cleanText, abort: new AbortController(), started: false };
    operation.cancelled = new Promise(resolve => { operation.resolveCancel = () => resolve(false); });
    this._operation = operation;
    try {
      const result = await Promise.race([this._perform(operation, options), operation.cancelled]);
      if (!this._current(operation)) return false;
      this._cleanup(operation);
      this._operation = null; this.isSpeaking = false; this.currentUtterance = null;
      if (result !== false) this._onEnd?.(cleanText);
      return result !== false;
    } catch (failure) {
      if (!this._current(operation)) return false;
      this._cleanup(operation);
      this._operation = null; this.isSpeaking = false; this.currentUtterance = null;
      const error = failure instanceof Error ? failure : new Error(String(failure));
      this._onError?.(error);
      throw error;
    }
  }

  async _perform(operation, options) {
    const language = options.language || 'en-US';
    if (this.synth && this.Utterance && this._loadBestVoice(this._preferredVoiceName, language)) {
      try { return await this._speakBrowser(operation, options); }
      catch (error) {
        if (!this._current(operation)) return false;
        // Browser speech is frequently unavailable in Electron even with installed voices.
        this.synth.cancel();
      }
    }
    return this._speakBackend(operation, options);
  }

  _speakBrowser(operation, options) {
    return new Promise((resolve, reject) => {
      const utterance = new this.Utterance(operation.text);
      this.currentUtterance = utterance;
      utterance.voice = this._bestVoice;
      utterance.lang = options.language || 'en-US';
      utterance.rate = options.rate ?? 1;
      utterance.pitch = options.pitch ?? 1;
      utterance.volume = options.volume ?? 1;
      const settle = (error = null) => {
        clearTimeout(operation.startTimer); clearTimeout(operation.playbackTimer);
        utterance.onstart = utterance.onend = utterance.onerror = null;
        if (error) reject(error); else resolve(true);
      };
      operation.startTimer = setTimeout(() => settle(new Error('Browser speech did not start.')), 3000);
      operation.playbackTimer = setTimeout(() => settle(new Error('Browser speech did not finish.')), 180000);
      utterance.onstart = () => { clearTimeout(operation.startTimer); this._started(operation); };
      utterance.onend = () => settle();
      utterance.onerror = event => settle(new Error(`Browser speech failed: ${event.error || 'audio error'}.`));
      try { this.synth.speak(utterance); }
      catch (error) { settle(error); }
    });
  }

  async _speakBackend(operation, options) {
    operation.requestTimer = setTimeout(() => operation.abort.abort(), 30000);
    let result;
    try { result = await this.client.request('/api/tts', { method: 'POST', body: { text: operation.text, language: options.language || 'en-US' }, signal: operation.abort.signal }); }
    catch (error) {
      if (operation.abort.signal.aborted && this._current(operation)) throw new Error('Speech generation timed out. Check the local backend and try again.');
      throw error;
    } finally { clearTimeout(operation.requestTimer); }
    if (!this._current(operation)) return false;
    if (result.error || !result.audio) throw new Error(typeof result.error === 'string' ? result.error : result.error?.message || 'The backend did not produce speech audio.');
    if (!this.Audio) throw new Error('Audio playback is unavailable in this browser.');
    const mime = { wav: 'audio/wav', mp3: 'audio/mpeg', m4a: 'audio/mp4', ogg: 'audio/ogg' }[result.format] || 'audio/wav';
    return new Promise((resolve, reject) => {
      const audio = new this.Audio(`data:${mime};base64,${result.audio}`);
      operation.audio = audio;
      audio.onplaying = () => this._started(operation);
      audio.onended = () => resolve(true);
      audio.onerror = () => reject(new Error('Generated speech could not be played. Check your audio output and try again.'));
      operation.playbackTimer = setTimeout(() => reject(new Error('Speech audio playback did not finish.')), 180000);
      try {
        const playing = audio.play();
        Promise.resolve(playing).then(() => this._started(operation), error => reject(new Error(error.name === 'NotAllowedError' ? 'Audio playback was blocked. Click read aloud again to allow playback.' : error.message || 'Could not play speech audio.')));
      } catch (error) { reject(error); }
    });
  }

  _cleanup(operation) {
    clearTimeout(operation.startTimer); clearTimeout(operation.requestTimer); clearTimeout(operation.playbackTimer);
    operation.abort.abort();
    if (operation.audio) { operation.audio.onplaying = operation.audio.onended = operation.audio.onerror = null; operation.audio.pause?.(); }
    if (this.currentUtterance) this.currentUtterance.onstart = this.currentUtterance.onend = this.currentUtterance.onerror = null;
  }
  cancel() {
    const operation = this._operation;
    this._operation = null;
    if (operation) { this._cleanup(operation); operation.resolveCancel(); }
    try { this.synth?.cancel?.(); } catch { /* Cancellation is best effort. */ }
    this.currentUtterance = null; this.isSpeaking = false;
  }
  stop() { this.cancel(); }
}

export const voiceSpeaker = new VoiceSpeaker();
export default voiceSpeaker;
