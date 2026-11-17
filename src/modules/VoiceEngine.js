/** Composer voice facade: shared capture/playback implementations, no cloud keys here. */
import { VoiceListener } from './voice/VoiceListener';
import { VoiceSpeaker } from './voice/VoiceSpeaker';

export class VoiceEngine {
  constructor(options = {}) {
    this.listener = options.listener || new VoiceListener(options);
    this.speaker = options.speaker || new VoiceSpeaker(options);
    this.synthesis = this.speaker.synth;
    this._currentLanguage = 'en-US';
    this._callbacks = {};
    this.listener.onStateChange(state => {
      this._callbacks.onStateChange?.(state);
      if (state === 'listening') this._callbacks.onStart?.();
      if (state === 'idle' || state === 'error') this._callbacks.onEnd?.();
    });
    this.listener.onTranscript(({ final, interim }) => this._callbacks.onResult?.({ final, interim, isFinal: !!final }));
    this.listener.onAudioLevel(level => this._callbacks.onAudioLevel?.(level));
    this.listener.onError(error => this._callbacks.onError?.(error));
  }
  get isListening() { return this.listener.isListening(); }
  get isSpeaking() { return this.speaker.isSpeaking; }
  get currentUtterance() { return this.speaker.currentUtterance; }
  isSTTSupported() { return this.listener.isSupported(); }
  isTTSSupported() { return !!(this.speaker.synth || this.speaker.Audio); }
  getCurrentLanguage() { return this._currentLanguage; }
  startListening(language = 'en-US', callbacks = {}) {
    this.listener.stop(false);
    this.speaker.stop();
    this._callbacks = callbacks;
    this._currentLanguage = language;
    return this.listener.startListening(language);
  }
  stopListening(transcribe = true) { this.listener.stop(transcribe); }
  speak(text, language = 'en-US', options = {}) {
    return this.speaker.speak(text, { ...options, language }).then(success => {
      if (success) options.onEnd?.();
      return success;
    }).catch(error => { options.onError?.(error); throw error; });
  }
  stopSpeaking() { this.speaker.stop(); }
  toggleSpeak(text, language = 'en-US', options = {}) {
    if (this.isSpeaking) { this.stopSpeaking(); return Promise.resolve(false); }
    return this.speak(text, language, options);
  }
  getVoicesForLanguage(language) {
    return this.speaker.getAvailableVoices().filter(voice => voice.lang?.toLowerCase().startsWith(language.split('-')[0].toLowerCase()));
  }
  getAvailableLanguages() { return [...new Set(this.speaker.getAvailableVoices().map(voice => voice.lang))].sort(); }
}
export const voiceEngine = new VoiceEngine();
export default voiceEngine;
