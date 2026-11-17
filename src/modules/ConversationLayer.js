/**
 * LYRA — Conversation Layer
 * Makes Lyra's responses natural, context-aware, and human-like.
 * Handles personality adaptation, anti-robotic filtering, and context injection.
 */

export class ConversationLayer {
  constructor() {
    // Anti-robotic patterns to filter from responses
    this.roboticPatterns = [
      /^(Sure|Of course|Absolutely|Certainly|Great question)[,!.]\s*(I'd be happy to |I can |Let me )/gi,
      /As an AI (language model|assistant|),?\s*/gi,
      /I don't have (personal )?(feelings|emotions|opinions),?\s*(but\s*)?/gi,
      /I hope (this|that) helps[.!]?\s*/gi,
      /Feel free to (ask|let me know|reach out)[^.]*[.!]\s*$/gi,
      /Is there anything else (I can help|you('d like| need))[^?]*\?\s*$/gi,
    ];
  }

  /**
   * Build an enhanced system prompt with personality and context.
   * @param {Object} params
   * @param {string} params.basePrompt - The core system directive
   * @param {string} params.userName - User's first name
   * @param {string} params.mode - Current work mode
   * @param {Array} params.recentHistory - Summary of past conversations for context
   * @param {Object} params.preferences - User preferences from memory
   */
  buildEnhancedPrompt({ basePrompt, userName, mode, recentHistory = [], preferences = {} }) {
    const hour = new Date().getHours();
    const timeContext = hour < 6 ? "late night" : hour < 12 ? "morning" : hour < 17 ? "afternoon" : hour < 21 ? "evening" : "night";

    let enhanced = basePrompt;

    // Personality layer
    enhanced += `\n\n## Personality & Tone
- Be naturally conversational but professional. Never sound robotic.
- Address ${userName || "the user"} by name occasionally, but not in every message.
- It's ${timeContext} — adjust energy accordingly (e.g., gentler at night, energetic in morning).
- NEVER start with "Sure!", "Of course!", "Absolutely!", "Great question!" or similar filler.
- NEVER end with "Feel free to ask!" or "Is there anything else?" 
- NEVER say "As an AI..." or refer to yourself as an AI/language model.
- Instead, begin responses with substance — jump directly into the answer.
- Use natural transitions: "Here's what I'd suggest...", "Looking at this...", "The key thing here is..."
- Match the user's communication style — if they're casual, be a bit more relaxed. If formal, stay professional.`;

    // Mode-specific personality adjustments
    const modePersonality = {
      draft: "\n- When drafting, be a skilled ghostwriter. Anticipate what the user truly needs, not just what they asked for.",
      analyze: "\n- When analyzing, be a sharp consultant. Lead with insights, not just data.",
      summarize: "\n- When summarizing, highlight what actually matters. Don't just compress — curate.",
      review: "\n- When reviewing, be a thoughtful editor. Be honest but constructive.",
      chat: "\n- In conversation, be a brilliant colleague — insightful, warm, and genuinely helpful.",
    };
    if (modePersonality[mode]) {
      enhanced += modePersonality[mode];
    }

    // Inject recent context if available
    if (recentHistory.length > 0) {
      enhanced += `\n\n## Context from Previous Conversations
The user has recently discussed: ${recentHistory.slice(0, 3).join("; ")}. 
Use this context naturally if relevant, but don't force it.`;
    }

    return enhanced;
  }

  /**
   * Post-process a response to remove robotic patterns.
   * @param {string} response - The raw AI response
   * @returns {string} - Cleaned, natural-sounding response
   */
  postProcess(response) {
    let cleaned = response;

    // Remove robotic opener patterns
    for (const pattern of this.roboticPatterns) {
      cleaned = cleaned.replace(pattern, "");
    }

    // Clean up any resulting double spaces or leading whitespace
    cleaned = cleaned.replace(/^\s+/, "").replace(/  +/g, " ");

    // If the cleanup removed the first character, capitalize the next one
    if (cleaned && cleaned[0] === cleaned[0].toLowerCase() && /^[a-z]/.test(cleaned)) {
      cleaned = cleaned[0].toUpperCase() + cleaned.slice(1);
    }

    return cleaned;
  }

  /**
   * Generate conversation context summaries from message history.
   * Used to inject context into system prompts.
   * @param {Array} messages - Full message array
   * @returns {string[]} - Summary topics
   */
  extractTopics(messages) {
    if (!messages || messages.length === 0) return [];

    const userMessages = messages
      .filter(m => m.role === "user")
      .map(m => m.content.slice(0, 100));

    // Simple keyword extraction
    const topics = userMessages.slice(-5).map(msg => {
      // Get first meaningful phrase
      const firstLine = msg.split("\n")[0].replace(/[[\](){}]/g, "").trim();
      return firstLine.slice(0, 60);
    });

    return topics.filter(Boolean);
  }

  /**
   * Determine the user's communication style from their messages.
   */
  analyzeUserStyle(messages) {
    const userMsgs = messages.filter(m => m.role === "user").map(m => m.content);
    if (userMsgs.length === 0) return "balanced";

    const avgLength = userMsgs.reduce((s, m) => s + m.length, 0) / userMsgs.length;
    const hasEmojis = userMsgs.some(m => /[\u{1F600}-\u{1F64F}]/u.test(m));
    const isFormal = userMsgs.every(m => /^[A-Z]/.test(m.trim()) && !hasEmojis);

    if (avgLength < 30 && hasEmojis) return "casual";
    if (avgLength > 200 && isFormal) return "formal";
    return "balanced";
  }
}

export const conversationLayer = new ConversationLayer();
export default conversationLayer;
