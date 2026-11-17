/**
 * LYRA — Model Registry v2.0
 * 
 * Central catalog of all AI models Lyra can route to.
 * Integrates Anthropic Claude (3.7 Sonnet, 3.5 Sonnet), DeepSeek (R1, V3),
 * OpenAI (GPT-4o, o3-mini), Google Gemini (2.5 Pro, Flash), NVIDIA NIM,
 * Groq, and OpenRouter universal gateway.
 * 
 * Each model entry contains:
 *   - id:            API model identifier
 *   - label:         Human-friendly display name
 *   - provider:      Provider key (anthropic, openrouter, groq, nvidia, gemini, openai)
 *   - providerLabel: Provider display name
 *   - description:   Short model description
 *   - contextWindow: Context window size string
 *   - strengths:     Array of strength tags
 *   - icon:          Provider/model icon
 *   - tier:          reasoning | coding | fast | massive | vision | search
 *   - isVision:      Supports image inputs
 *   - isCompound:    Supports built-in tool use
 */

// ── Provider Metadata ──────────────────────────────────────────────────────────
export const PROVIDERS = {
  claude_code: { id: "claude_code", name: "Claude Code", icon: "✻", color: "#D97706", description: "Local Claude session" },
  ollama: { id: "ollama", name: "Ollama", icon: "◌", color: "#9dd4b0", description: "Local inference" },
  anthropic: {
    id: "anthropic",
    name: "Anthropic",
    icon: "✻",
    color: "#D97706",
    description: "Frontier reasoning & coding intelligence",
  },
  openrouter: {
    id: "openrouter",
    name: "OpenRouter",
    icon: "🌐",
    color: "#6B5CE7",
    description: "200+ frontier models, universal gateway",
  },
  openai: {
    id: "openai",
    name: "OpenAI",
    icon: "✦",
    color: "#10A37F",
    description: "GPT-4o & advanced STEM reasoning",
  },
  gemini: {
    id: "gemini",
    name: "Google Gemini",
    icon: "◆",
    color: "#4285F4",
    description: "Massive context window + multimodal vision",
  },
  groq: {
    id: "groq",
    name: "Groq",
    icon: "⚡",
    color: "#F55036",
    description: "Sub-second ultra-fast open inference",
  },
  nvidia: {
    id: "nvidia",
    name: "NVIDIA NIM",
    icon: "🔥",
    color: "#76B900",
    description: "Heavy-duty enterprise reasoning & vision",
  },
};

// ── Model Catalog ──────────────────────────────────────────────────────────────
export const MODEL_CATALOG = [
  { id: "claude-sonnet-4-6", label: "Claude Sonnet", provider: "claude_code", providerLabel: "Claude Code", description: "Uses the local Claude session", strengths: ["Tools", "Coding"], icon: "✻" },
  { id: "claude-3-7-sonnet-latest", label: "Claude Sonnet API", provider: "anthropic", providerLabel: "Anthropic", description: "Backend Anthropic provider", icon: "✻" },
  { id: "llama3.2", label: "Llama 3.2 local", provider: "ollama", providerLabel: "Ollama", description: "Backend local inference", icon: "◌" },
  // ── Anthropic Claude (Frontier Coding & Hybrid Thinking) ──────────────────────
  {
    id: "anthropic/claude-3.7-sonnet",
    label: "Claude 3.7 Sonnet (Thinking)",
    provider: "openrouter",
    providerLabel: "Anthropic / OpenRouter",
    description: "Hybrid reasoning & world-class autonomous software engineering",
    contextWindow: "200K",
    strengths: ["Architecture", "Coding", "Thinking", "Reasoning"],
    icon: "✻",
    tier: "coding",
    isVision: true,
    isCompound: false,
  },
  {
    id: "anthropic/claude-3.5-sonnet",
    label: "Claude 3.5 Sonnet",
    provider: "openrouter",
    providerLabel: "Anthropic / OpenRouter",
    description: "Elite code generation, refactoring, and instruction following",
    contextWindow: "200K",
    strengths: ["Code Review", "Tool Use", "Writing", "Logic"],
    icon: "✻",
    tier: "coding",
    isVision: true,
    isCompound: false,
  },

  // ── DeepSeek Reasoning & Chat ────────────────────────────────────────────────
  {
    id: "deepseek/deepseek-r1",
    label: "DeepSeek R1 (Reasoning)",
    provider: "openrouter",
    providerLabel: "DeepSeek / OpenRouter",
    description: "State-of-the-art open reasoning, mathematics, and logic puzzle solving",
    contextWindow: "128K",
    strengths: ["Math", "Complex Logic", "Deep Analysis", "Chain of Thought"],
    icon: "🧠",
    tier: "reasoning",
    isVision: false,
    isCompound: false,
  },
  {
    id: "deepseek/deepseek-chat",
    label: "DeepSeek V3",
    provider: "openrouter",
    providerLabel: "DeepSeek / OpenRouter",
    description: "High-speed 671B MoE model for versatile coding and conversational depth",
    contextWindow: "128K",
    strengths: ["General", "Code", "Speed", "Value"],
    icon: "🧠",
    tier: "coding",
    isVision: false,
    isCompound: false,
  },

  // ── OpenAI Frontier ──────────────────────────────────────────────────────────
  {
    id: "openai/gpt-4o",
    label: "GPT-4o Multimodal",
    provider: "openrouter",
    providerLabel: "OpenAI / OpenRouter",
    description: "Omni-modal flagship model for creative synthesis and visual tasks",
    contextWindow: "128K",
    strengths: ["Creative", "Multimodal", "General", "Synthesis"],
    icon: "✦",
    tier: "vision",
    isVision: true,
    isCompound: false,
  },
  {
    id: "openai/o3-mini",
    label: "o3-mini (STEM Reasoning)",
    provider: "openrouter",
    providerLabel: "OpenAI / OpenRouter",
    description: "Lightweight frontier reasoning model optimized for science and code",
    contextWindow: "200K",
    strengths: ["STEM", "Math", "Debugging", "Fast Reasoning"],
    icon: "✦",
    tier: "reasoning",
    isVision: false,
    isCompound: false,
  },

  // ── Google Gemini (Massive Context & Multimodal) ──────────────────────────────
  {
    id: "gemini-2.5-pro",
    label: "Gemini 2.5 Pro (2M Context)",
    provider: "gemini",
    providerLabel: "Google Gemini",
    description: "Deep reasoning across 2 million tokens of codebase, documents, or video",
    contextWindow: "2M",
    strengths: ["Massive Context", "Whole-Repo Analysis", "Multimodal", "Vision"],
    icon: "◆",
    tier: "massive",
    isVision: true,
    isCompound: false,
  },
  {
    id: "gemini-2.0-flash",
    label: "Gemini 2.0 Flash",
    provider: "gemini",
    providerLabel: "Google Gemini",
    description: "High-speed 1M context model with low latency and visual understanding",
    contextWindow: "1M",
    strengths: ["Fast Vision", "Tool Calling", "Low Latency"],
    icon: "◆",
    tier: "massive",
    isVision: true,
    isCompound: false,
  },

  // ── Qwen Coder (Heavy-Duty Engineering) ──────────────────────────────────────
  {
    id: "qwen/qwen-2.5-coder-32b-instruct",
    label: "Qwen 2.5 Coder 32B",
    provider: "openrouter",
    providerLabel: "Qwen / OpenRouter",
    description: "Premier specialized open coding engine for algorithms and system code",
    contextWindow: "128K",
    strengths: ["Algorithms", "Python", "Rust", "C++", "Tool Calling"],
    icon: "💻",
    tier: "coding",
    isVision: false,
    isCompound: false,
  },

  // ── Groq Ultra-Fast Models ────────────────────────────────────────────────────
  {
    id: "llama-3.3-70b-versatile",
    label: "Llama 3.3 70B",
    provider: "groq",
    providerLabel: "Groq",
    description: "Sub-second conversational response on Groq LPU inference hardware",
    contextWindow: "128K",
    strengths: ["Sub-second Speed", "Real-Time Voice", "Chat", "Drafting"],
    icon: "⚡",
    tier: "fast",
    isVision: false,
    isCompound: false,
  },
  {
    id: "compound-beta",
    label: "Compound Beta",
    provider: "groq",
    providerLabel: "Groq",
    description: "Agentic model with built-in real-time web search and code execution",
    contextWindow: "128K",
    strengths: ["Web Search", "Live Intel", "Code Sandbox"],
    icon: "⚡",
    tier: "search",
    isVision: false,
    isCompound: true,
  },

  // ── NVIDIA NIM Models ────────────────────────────────────────────────────────
  {
    id: "moonshotai/kimi-k3",
    label: "Kimi K3 (Moonshot)",
    provider: "nvidia",
    providerLabel: "NVIDIA NIM",
    description: "Ultra-high intelligence multimodal reasoning model via NVIDIA NIM",
    contextWindow: "128K",
    strengths: ["Deep Reasoning", "Multimodal Vision", "Analysis"],
    icon: "🔥",
    tier: "reasoning",
    isVision: true,
    isCompound: false,
  },
];

// ── Registry API ───────────────────────────────────────────────────────────────
export class ModelRegistry {
  static health = null;
  static setHealth(health) { this.health = health; }
  static providerAvailable(id) {
    const provider = this.health?.providers?.[id];
    return provider === true || (typeof provider === "object" && (provider.available === true || provider.configured === true));
  }
  static getAllModels() {
    return MODEL_CATALOG.map(model => ({ ...model, isAvailable: this.providerAvailable(model.provider), providerColor: PROVIDERS[model.provider]?.color || "#888", providerName: PROVIDERS[model.provider]?.name || model.provider }));
  }
  static getModelsGrouped() {
    const groups = {};
    for (const model of this.getAllModels()) {
      const provider = PROVIDERS[model.provider];
      if (!groups[model.provider]) groups[model.provider] = { provider: model.provider, providerLabel: provider?.name || model.providerLabel, icon: provider?.icon || "", color: provider?.color || "#888", hasKey: this.providerAvailable(model.provider), models: [] };
      groups[model.provider].models.push(model);
    }
    return Object.values(groups).sort((a, b) => Number(b.hasKey) - Number(a.hasKey));
  }
  static getModelById(id) { return this.getAllModels().find(model => model.id === id) || null; }
  static getProviders() { return Object.values(PROVIDERS).map(provider => ({ ...provider, hasKey: this.providerAvailable(provider.id) })); }
}
export default ModelRegistry;
