/**
 * LYRA — Acoustic + Lexical Emotion Engine v1.0
 *
 * Realistic, heuristic-based voice sentiment analyzer.
 * No ML models — pure signal processing + keyword matching.
 *
 * Acoustic analysis (from Web Audio AnalyserNode):
 *   - volumeRMS: Rolling average amplitude → high variance = agitation
 *   - speechRateWPM: Words / duration → >160 = rushed, <100 = calm/tired
 *   - pauseDuration: Silence between utterances → long = thoughtful
 *   - volumePeakRatio: Peak / average → high = emphasis/stress
 *
 * Lexical analysis (from transcript text):
 *   - Urgency, excitement, stress, fatigue, curiosity keyword matching
 *   - Exclamation and question density
 *
 * Output: { primaryEmotion, confidence, stressIndex, valence, arousal, speechRateWPM, adaptations }
 */

// ── Keyword Dictionaries ─────────────────────────────────────────────

const URGENCY_WORDS = [
  "hurry", "quick", "urgent", "asap", "immediately", "now", "fast",
  "emergency", "critical", "rush", "deadline", "right now", "straight away",
];

const EXCITEMENT_WORDS = [
  "awesome", "amazing", "incredible", "brilliant", "perfect", "fantastic",
  "excellent", "let's go", "yes!", "love it", "great", "wonderful",
  "cool", "sick", "phenomenal", "beautiful", "nailed it",
];

const STRESS_WORDS = [
  "damn", "broken", "not working", "failed", "error", "frustrated",
  "stuck", "why won't", "can't figure", "keeps crashing", "bug",
  "annoying", "messed up", "wrong", "impossible", "driving me crazy",
  "what the hell", "ugh", "argh", "come on",
];

const FATIGUE_WORDS = [
  "tired", "exhausted", "long day", "can't think", "burned out",
  "sleepy", "drained", "need a break", "winding down", "calling it",
  "brain is fried", "done for today",
];

const CURIOSITY_WORDS = [
  "how does", "what is", "why does", "explain", "tell me about",
  "curious", "wonder", "interesting", "how would", "what if",
  "is it possible", "can you show me", "teach me",
];

// ── Emotion Engine Class ─────────────────────────────────────────────

class EmotionEngine {
  constructor() {
    // Rolling acoustic history (last N measurements)
    this._volumeHistory = [];
    this._maxHistory = 40; // ~2 seconds at 50ms intervals

    // Per-utterance tracking
    this._utteranceStartTime = 0;
    this._wordCount = 0;

    // Current computed state
    this.currentEmotion = {
      primaryEmotion: "CALM",
      confidence: 0.5,
      stressIndex: 0,
      valence: 0.0,
      arousal: 0.3,
      speechRateWPM: 0,
      adaptations: {
        ttsRate: 185,
        ttsPitch: 1.0,
        toneDirective: "Respond naturally with your full personality.",
      },
    };

    // Smoothing factor — emotions should not flicker wildly
    this._smoothingAlpha = 0.3;
  }

  /**
   * Feed a raw audio level reading (0-1 from AnalyserNode RMS).
   * Call this on every audio monitoring tick (~50ms).
   */
  feedAudioLevel(level) {
    this._volumeHistory.push(level);
    if (this._volumeHistory.length > this._maxHistory) {
      this._volumeHistory.shift();
    }
  }

  /**
   * Mark the start of a new utterance for WPM calculation.
   */
  startUtterance() {
    this._utteranceStartTime = Date.now();
    this._wordCount = 0;
  }

  /**
   * Analyze a finalized transcript + accumulated acoustic data.
   * Returns the full emotion state object.
   *
   * @param {string} transcript - The finalized speech-to-text string
   * @returns {object} Emotion state with adaptations
   */
  analyze(transcript) {
    if (!transcript || !transcript.trim()) {
      return this.currentEmotion;
    }

    const text = transcript.toLowerCase().trim();
    const words = text.split(/\s+/).filter(Boolean);
    this._wordCount = words.length;

    // ── 1. Acoustic Metrics ──────────────────────────────────────────

    const volumeAvg = this._volumeHistory.length > 0
      ? this._volumeHistory.reduce((s, v) => s + v, 0) / this._volumeHistory.length
      : 0;

    const volumeVariance = this._volumeHistory.length > 2
      ? this._volumeHistory.reduce((s, v) => s + Math.pow(v - volumeAvg, 2), 0) / this._volumeHistory.length
      : 0;

    const volumePeak = this._volumeHistory.length > 0
      ? Math.max(...this._volumeHistory)
      : 0;

    const volumePeakRatio = volumeAvg > 0.01 ? volumePeak / volumeAvg : 1.0;

    // Speech rate (WPM)
    const durationSec = this._utteranceStartTime > 0
      ? Math.max(1, (Date.now() - this._utteranceStartTime) / 1000)
      : 3;
    const speechRateWPM = Math.round((this._wordCount / durationSec) * 60);

    // ── 2. Lexical Scoring ───────────────────────────────────────────

    const urgencyScore = this._matchKeywords(text, URGENCY_WORDS);
    const excitementScore = this._matchKeywords(text, EXCITEMENT_WORDS);
    const stressScore = this._matchKeywords(text, STRESS_WORDS);
    const fatigueScore = this._matchKeywords(text, FATIGUE_WORDS);
    const curiosityScore = this._matchKeywords(text, CURIOSITY_WORDS);

    // Punctuation density
    const exclamationCount = (text.match(/!/g) || []).length;
    const questionCount = (text.match(/\?/g) || []).length;
    const exclamationDensity = words.length > 0 ? exclamationCount / words.length : 0;
    const questionDensity = words.length > 0 ? questionCount / words.length : 0;

    // ── 3. Composite Emotion Classification ──────────────────────────

    // Score each emotion category
    const scores = {
      CALM:       1.0 - (volumeVariance * 10) - urgencyScore - stressScore,
      EXCITED:    excitementScore * 2 + exclamationDensity * 3 + (speechRateWPM > 160 ? 0.5 : 0),
      STRESSED:   stressScore * 2 + (volumeVariance * 8) + (volumePeakRatio > 3 ? 0.5 : 0),
      FRUSTRATED: stressScore * 2.5 + exclamationDensity * 2,
      URGENT:     urgencyScore * 3 + (speechRateWPM > 170 ? 0.6 : 0),
      CURIOUS:    curiosityScore * 2.5 + questionDensity * 4,
      TIRED:      fatigueScore * 3 + (speechRateWPM < 90 && speechRateWPM > 0 ? 0.8 : 0),
    };

    // Find the winning emotion
    let bestEmotion = "CALM";
    let bestScore = scores.CALM;
    for (const [emotion, score] of Object.entries(scores)) {
      if (score > bestScore) {
        bestScore = score;
        bestEmotion = emotion;
      }
    }

    // Confidence: how much the winner stands out from the rest
    const allScores = Object.values(scores);
    const avgScore = allScores.reduce((s, v) => s + v, 0) / allScores.length;
    const confidence = Math.min(1.0, Math.max(0.2, (bestScore - avgScore) / Math.max(bestScore, 0.01)));

    // ── 4. Derived Metrics ───────────────────────────────────────────

    // Stress index (0-100): weighted combination of stress keywords + volume variance + speech rate
    const rawStress =
      (stressScore + urgencyScore) * 20 +
      volumeVariance * 200 +
      (speechRateWPM > 160 ? (speechRateWPM - 160) * 0.5 : 0) +
      exclamationDensity * 30;
    const stressIndex = Math.min(100, Math.max(0, Math.round(rawStress)));

    // Valence (-1 to +1): positive = happy/excited, negative = frustrated/stressed
    const positiveSignal = excitementScore + (curiosityScore * 0.5);
    const negativeSignal = stressScore + (urgencyScore * 0.5) + (fatigueScore * 0.3);
    const rawValence = (positiveSignal - negativeSignal) / Math.max(1, positiveSignal + negativeSignal + 0.5);
    const valence = Math.max(-1, Math.min(1, rawValence));

    // Arousal (0-1): low = calm/tired, high = excited/urgent
    const rawArousal =
      (speechRateWPM / 250) +
      volumeVariance * 5 +
      exclamationDensity * 2 +
      urgencyScore +
      excitementScore * 0.8 -
      fatigueScore * 0.5;
    const arousal = Math.max(0, Math.min(1, rawArousal));

    // ── 5. TTS Adaptation ────────────────────────────────────────────

    const adaptations = this._computeAdaptations(bestEmotion, stressIndex, arousal);

    // ── 6. Apply Smoothing ───────────────────────────────────────────

    const alpha = this._smoothingAlpha;
    this.currentEmotion = {
      primaryEmotion: bestEmotion,
      confidence: this._lerp(this.currentEmotion.confidence, confidence, alpha),
      stressIndex: Math.round(this._lerp(this.currentEmotion.stressIndex, stressIndex, alpha)),
      valence: parseFloat(this._lerp(this.currentEmotion.valence, valence, alpha).toFixed(2)),
      arousal: parseFloat(this._lerp(this.currentEmotion.arousal, arousal, alpha).toFixed(2)),
      speechRateWPM,
      adaptations,
    };

    // Reset acoustic history for next utterance
    this._volumeHistory = [];

    return this.currentEmotion;
  }

  /**
   * Get current emotion state without re-analyzing.
   */
  getState() {
    return this.currentEmotion;
  }

  /**
   * Reset to neutral baseline.
   */
  reset() {
    this._volumeHistory = [];
    this._utteranceStartTime = 0;
    this._wordCount = 0;
    this.currentEmotion = {
      primaryEmotion: "CALM",
      confidence: 0.5,
      stressIndex: 0,
      valence: 0.0,
      arousal: 0.3,
      speechRateWPM: 0,
      adaptations: {
        ttsRate: 185,
        ttsPitch: 1.0,
        toneDirective: "Respond naturally with your full personality.",
      },
    };
  }

  // ── Private Helpers ────────────────────────────────────────────────

  _matchKeywords(text, keywords) {
    let count = 0;
    for (const kw of keywords) {
      if (text.includes(kw)) count++;
    }
    return Math.min(count, 4) / 4; // Normalized 0-1, capped at 4 matches
  }

  _computeAdaptations(emotion, stressIndex, arousal) {
    switch (emotion) {
      case "STRESSED":
      case "FRUSTRATED":
        return {
          ttsRate: 175,
          ttsPitch: 0.92,
          toneDirective: "Be concise, calm, and solution-oriented. Acknowledge their frustration briefly, then solve the problem.",
        };
      case "URGENT":
        return {
          ttsRate: 205,
          ttsPitch: 1.0,
          toneDirective: "Skip pleasantries. Execute immediately. Confirm with minimal words.",
        };
      case "EXCITED":
        return {
          ttsRate: 195,
          ttsPitch: 1.05,
          toneDirective: "Match their enthusiasm. Be proactive and suggest bold ideas. Celebrate momentum.",
        };
      case "TIRED":
        return {
          ttsRate: 170,
          ttsPitch: 0.9,
          toneDirective: "Be warm, brief, and efficient. If they've been working long, gently suggest a break.",
        };
      case "CURIOUS":
        return {
          ttsRate: 180,
          ttsPitch: 1.0,
          toneDirective: "Provide richer detail. Explore the topic with genuine intellectual engagement.",
        };
      case "CALM":
      default:
        return {
          ttsRate: 185,
          ttsPitch: 1.0,
          toneDirective: "Respond naturally with your full personality.",
        };
    }
  }

  _lerp(a, b, t) {
    return a + (b - a) * t;
  }
}

// Singleton export
export const emotionEngine = new EmotionEngine();
export default emotionEngine;
