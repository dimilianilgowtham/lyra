/**
 * LYRA — Voice Manager System (Unified Facade)
 *
 * Coordinates decoupled VoiceListener (listening & adaptive VAD)
 * and VoiceSpeaker (speech synthesis & utterance queue).
 */

import { voiceListener } from "./voice/VoiceListener";
import { voiceSpeaker } from "./voice/VoiceSpeaker";

export class VoiceManager {
  constructor() {
    this.listener = voiceListener;
    this.speaker = voiceSpeaker;
    this.mode = "idle"; // idle | requesting | active | transcribing | speaking | error
    this.transcript = "";
    this.interimTranscript = "";
    this.audioLevel = 0;
    this.emotion = null;

    // Callbacks
    this._onWakeWord = null;
    this._onTranscript = null;
    this._onCommand = null;
    this._onEmotion = null;
    this._onStateChange = null;
    this._onAudioLevel = null;
    this._onSpeakStart = null;
    this._onSpeakEnd = null;
    this._onError = null;

    // Wire VoiceListener events
    this.listener.onTranscript(({ final, interim }) => {
      this.interimTranscript = interim;
      if (final) this.transcript = final;
      if (this._onTranscript) this._onTranscript({ final, interim });
    });

    this.listener.onCommand((cmd, emotionData) => {
      this.transcript = cmd;
      this.emotion = emotionData;
      if (this._onEmotion) this._onEmotion(emotionData);
      if (this._onCommand) this._onCommand(cmd, emotionData);
    });

    this.listener.onAudioLevel((level) => {
      this.audioLevel = level;
      if (this._onAudioLevel) this._onAudioLevel(level);
    });

    this.listener.onStateChange((state) => {
      if (state === "listening" || state === "speech_detected") {
        this._setMode("active");
      } else if (state === "requesting" || state === "transcribing") {
        this._setMode(state);
      } else if (state === "error") {
        this._setMode("error");
      } else if (state === "idle" && !this.speaker.isSpeaking) {
        this._setMode("idle");
      }
    });

    this.listener.onError((err) => {
      if (this._onError) this._onError(err);
    });

    // Wire VoiceSpeaker events
    this.speaker.onStart((text) => {
      // Pause listener while speaking to prevent feedback
      this.listener.stop(false);
      this._setMode("speaking");
      if (this._onSpeakStart) this._onSpeakStart();
    });

    this.speaker.onEnd((text) => {
      this._setMode("idle");
      if (this._onSpeakEnd) this._onSpeakEnd();
    });

    this.speaker.onError((err) => {
      this._setMode("idle");
      if (this._onError) this._onError(err.message || String(err));
    });
  }

  _setMode(mode) {
    if (this.mode === mode) return;
    this.mode = mode;
    if (this._onStateChange) this._onStateChange(mode);
  }

  getMode() { return this.mode; }
  isListening() { return this.listener.isListening(); }
  isSpeaking() { return this.speaker.isSpeaking; }

  // ── Callbacks ───────────────────────────────────────────────────

  onWakeWord(cb) { this._onWakeWord = cb; return this; }
  onTranscript(cb) { this._onTranscript = cb; return this; }
  onCommand(cb) { this._onCommand = cb; return this; }
  onEmotion(cb) { this._onEmotion = cb; return this; }
  onStateChange(cb) { this._onStateChange = cb; return this; }
  onAudioLevel(cb) { this._onAudioLevel = cb; return this; }
  onSpeakStart(cb) { this._onSpeakStart = cb; return this; }
  onSpeakEnd(cb) { this._onSpeakEnd = cb; return this; }
  onError(cb) { this._onError = cb; return this; }

  // ── Controls ────────────────────────────────────────────────────

  setContinuousMode(enabled) {
    this.listener.setContinuousMode(enabled);
  }

  getContinuousMode() {
    return this.listener.getContinuousMode();
  }

  setVoice(voiceName) {
    this.speaker.setVoice(voiceName);
  }

  getVoiceName() {
    return this.speaker.getVoiceName();
  }

  startListening() {
    this.speaker.stop();
    return this.listener.startListening();
  }

  startActiveListening() {
    return this.startListening();
  }

  startPassiveListening() {
    return this.startListening();
  }

  stop(transcribe = true) {
    this.listener.stop(transcribe);
    this.speaker.stop();
    if (!transcribe) this._setMode("idle");
  }

  speak(text, options = {}) {
    this.listener.stop(false);
    return this.speaker.speak(text, options);
  }

  stopSpeaking() {
    this.speaker.stop();
    if (this.mode === "speaking") this._setMode("idle");
  }

  getEmotion() {
    return this.emotion;
  }
}

export const voiceManager = new VoiceManager();
export default voiceManager;
