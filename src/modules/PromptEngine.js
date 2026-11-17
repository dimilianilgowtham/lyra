import { backendClient } from "./BackendClient";
/**
 * LYRA — Prompt Engine
 * Enhances user prompts with three modes: Simple, Developer, Creative.
 * Uses the Groq API to intelligently improve prompts.
 */

const IMPROVEMENT_PROMPTS = {
  simple: `You are a prompt improvement expert. The user will give you a rough prompt. Your job:
1. Fix grammar and spelling
2. Add clarity and structure
3. Make the intent unambiguous
4. Keep it concise

Return ONLY the improved prompt. No explanations, no preamble. Just the better prompt.`,

  developer: `You are a senior software engineer and technical prompt expert. The user gives you a prompt. Your job:
1. Add technical precision and constraints
2. Specify expected output format (code, docs, etc.)
3. Add edge cases and error handling requirements
4. Include performance and best-practice considerations
5. Add context about language, framework, or tool if relevant
6. Make it structured with clear sections

Return ONLY the improved technical prompt. No explanations.`,

  creative: `You are a creative writing coach and prompt artist. The user gives you a prompt. Your job:
1. Expand scope with vivid, inspiring language
2. Add evocative details and sensory elements
3. Suggest creative angles the user might not have considered
4. Add emotional depth and storytelling elements
5. Make it inspiring and engaging while preserving the core intent

Return ONLY the improved creative prompt. No explanations.`,
};

export class PromptEngine {
  constructor() {}

  /**
   * Improve a prompt using the specified mode.
   * @param {string} originalPrompt - The user's raw prompt
   * @param {string} mode - 'simple' | 'developer' | 'creative'
   * @returns {Promise<{original: string, improved: string, mode: string}>}
   */
  async improve(originalPrompt, mode = "simple") {
    if (!originalPrompt.trim()) {
      throw new Error("Please enter a prompt to improve.");
    }

    const systemPrompt = IMPROVEMENT_PROMPTS[mode] || IMPROVEMENT_PROMPTS.simple;

    const response = await backendClient.createTask({ prompt: originalPrompt, mode: "chat", instructions: `${systemPrompt}\nReturn text only. Do not execute tools.`, conversation_id: `refine_${crypto.randomUUID()}` });
    const task = response.task || response;
    for (let attempt = 0; attempt < 90; attempt++) {
      const detail = await backendClient.getTask(task.id);
      if (detail.task.status === "completed") {
        const improved = detail.task.result?.response;
        if (!improved?.trim()) throw new Error("The provider returned no improved prompt.");
        return { original: originalPrompt, improved: improved.trim(), mode };
      }
      if (["failed", "cancelled", "interrupted", "awaiting_approval"].includes(detail.task.status)) throw new Error(detail.task.error || "Prompt improvement did not complete.");
      await new Promise(resolve => setTimeout(resolve, 1000));
    }
    throw new Error("Prompt improvement is still running. Check Tasks for its status.");
  }

  /**
   * Get a complexity score for a prompt (0-100).
   */
  analyzeComplexity(prompt) {
    if (!prompt) return 0;
    const words = prompt.trim().split(/\s+/).length;
    const sentences = prompt.split(/[.!?]+/).filter(Boolean).length;
    const hasConstraints = /must|should|ensure|require|include|avoid|format/i.test(prompt);
    const hasStructure = /\n|bullet|list|step|section/i.test(prompt);
    const hasExamples = /example|e\.g\.|like|such as/i.test(prompt);

    let score = Math.min(words / 2, 30);
    score += Math.min(sentences * 5, 20);
    if (hasConstraints) score += 15;
    if (hasStructure) score += 15;
    if (hasExamples) score += 10;
    score += Math.min(prompt.length / 50, 10);

    return Math.min(Math.round(score), 100);
  }
}

export default PromptEngine;
