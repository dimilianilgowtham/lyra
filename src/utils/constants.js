/**
 * LYRA — Shared Constants v3.0
 * Central location for all app-wide constants, modes, and configuration.
 * 
 * v3.0 additions:
 * - Study, Career, and Code modes
 * - Expanded Indian language support (Marathi, Gujarati, Marwadi, Kannada, Tamil)
 * - Mode-specific system prompt directives
 */

// ── Work Modes ─────────────────────────────────────────────────────────────────
export const MODES = [
  { id: "chat",      icon: "⬡", label: "Assistant",  desc: "Chat, brainstorm, and explore ideas",              color: "#6b8afd" },
  { id: "draft",     icon: "⬢", label: "Draft",       desc: "Write documents, emails, and proposals",           color: "#c8b89a" },
  { id: "analyze",   icon: "◉", label: "Analyze",     desc: "Analyze data and generate insights",               color: "#9dd4b0" },
  { id: "summarize", icon: "⊞", label: "Summarize",   desc: "Condense content into key takeaways",              color: "#d4a8c8" },
  { id: "review",    icon: "⊡", label: "Review",      desc: "Review and improve your writing",                  color: "#d4c89a" },
  { id: "translate", icon: "🌐", label: "Translate",   desc: "Translate between languages",                      color: "#a8d8d4" },
  { id: "study",     icon: "◬", label: "Study",       desc: "Turn notes into flashcards, Cornell notes & exams", color: "#a8d4e8" },
  { id: "career",    icon: "◈", label: "Career",      desc: "Resume review, ATS scoring, interview prep",        color: "#d4c89a" },
  { id: "code",      icon: "⟨⟩", label: "Code",       desc: "Multi-file review, debugging, security scan",       color: "#9dd4b0" },
  { id: "agent",     icon: "🤖", label: "Agentic Core", desc: "Local tools — terminal, files, screenshots",   color: "#7b61ff" },
];

// ── Mode-Specific System Prompt Directives ─────────────────────────────────────
export const MODE_DIRECTIVES = {
  chat: "",
  draft: "DRAFT mode: create structured professional documents with clear headings.",
  analyze: "ANALYZE mode: structured analysis with key findings and actionable recommendations.",
  summarize: "SUMMARIZE mode: extract key points in concise, organized format.",
  review: "REVIEW mode: identify issues, suggest improvements, provide improved version.",
  translate: "TRANSLATE mode: Detect source language and translate.",
  study: `STUDY mode: You are a study assistant. When given raw notes, a lecture transcript, or a document:
1. Start with a 3-bullet **Key Concepts** summary
2. Create a **Cornell Notes** section (main notes column + cue questions column)
3. Generate exactly 10 **Flashcards** in format: Q: ... / A: ...
4. Write 5 **Likely Exam Questions** ranked by difficulty
5. End with a **Topic Timeline** if chronological content is present
Always use markdown headers to separate each section clearly.`,
  career: `CAREER mode: You are a senior HR consultant and ATS expert.
When given a job description and/or resume:
1. **ATS Keyword Analysis**: List keywords in JD not present in resume (mark as MISSING)
2. **Resume Gaps**: Specific skills, experiences, or formats that weaken the application
3. **Rewrite Suggestions**: 3 bullet-point rewrites that are stronger + more ATS-compatible
4. **Fit Score**: Give a 0-100 score with brief justification
5. **Top 10 Interview Questions**: Role-specific, ranked by likelihood
6. **One Red Flag**: The single biggest weakness in this application and how to address it
Be direct. No filler. A recruiter reads this in 7 seconds — act accordingly.`,
  code: `CODE mode: You are a senior engineer doing a formal code review.
Structure your response as:
1. **Language + Framework Detection** (auto-detected)
2. **Critical Bugs** (with file + line reference if available)
3. **Security Vulnerabilities** (OWASP top 10 check)
4. **Performance Issues** (n+1 queries, memory leaks, blocking calls)
5. **Code Quality** (naming, structure, DRY violations)
6. **Refactored Snippet** (show the most important fix as working code)
7. **Overall Score** (A/B/C/D/F with brief rationale)
Reference specific line numbers. Be surgical, not verbose.`,
  agent: `AGENTIC CORE mode: You are Lyra, a sovereign AI assistant with full local system access.
You can read/write files, run terminal commands, list directories, and capture screenshots using the available tools.
Be precise, efficient, and always explain what tool you're about to use and why.
Never execute destructive operations without explicit justification.
Confirm file changes using tool results before claiming completion.
For multi-step tasks, plan ahead and execute step by step.`,
};

// ── Mode-Specific Quick Prompts ────────────────────────────────────────────────
export const MODE_PROMPTS = {
  chat: [
    "Explain a complex topic in simple terms",
    "Brainstorm 10 creative ideas for a presentation",
    "Help me prepare for a job interview",
    "Create a weekly productivity plan",
    "Compare two options and help me decide",
  ],
  draft: [
    "Draft a professional email about a project update",
    "Write a leave application for 3 days",
    "Create a client proposal for web development",
    "Write a formal complaint letter",
    "Draft a cover letter for a software engineer role",
  ],
  analyze: [
    "Analyze the pros and cons of this decision",
    "SWOT analysis of this business idea",
    "Risk assessment for this project plan",
    "Compare these two approaches and recommend one",
    "Break down this data and find key insights",
  ],
  summarize: [
    "Summarize this article into 5 key takeaways",
    "Extract definitions and key concepts",
    "Create study notes from this content",
    "Bullet-point summary of this document",
    "Highlight the most important findings",
  ],
  review: [
    "Review this code for bugs and improvements",
    "Check this essay for grammar and clarity",
    "Audit this document for logical errors",
    "Improve the structure of this writing",
    "Find security vulnerabilities in this code",
  ],
  translate: [
    "Translate this text to Hindi",
    "Translate this email to Telugu formally",
    "Convert this English paragraph to Hindi",
    "Translate this technical document to simple English",
    "Translate this conversation to Telugu",
  ],
  study: [
    "Turn these lecture notes into flashcards",
    "Create Cornell notes from this chapter",
    "Generate exam questions from this topic",
    "Make a study timeline for this syllabus",
    "Summarize this PDF for quick revision",
  ],
  career: [
    "Review my resume against this job description",
    "What keywords am I missing for this role?",
    "Generate 10 interview questions for this position",
    "How can I improve this bullet point?",
    "Rate my resume's ATS compatibility",
  ],
  code: [
    "Review this code for bugs and security issues",
    "Refactor this function for better performance",
    "Explain what this code does line by line",
    "Find the bug in this code",
    "Write unit tests for this function",
  ],
  agent: [
    "List all files in my Desktop folder",
    "Create a new folder called 'projects' on Desktop",
    "Read the README in my project folder",
    "Take a screenshot of my current screen",
    "Create a note file on Desktop with my project goals",
  ],
};

// Backward compat — generic prompts
export const QUICK_PROMPTS = MODE_PROMPTS.chat;

// ── Tone Presets (for Draft mode) ──────────────────────────────────────────────
export const TONE_PRESETS = [
  { id: "professional", label: "Professional", icon: "💼", desc: "Standard business tone" },
  { id: "diplomatic",   label: "Diplomatic",   icon: "🤝", desc: "Tactful, avoids blame" },
  { id: "assertive",    label: "Assertive",     icon: "💪", desc: "Direct and firm" },
  { id: "apologetic",   label: "Apologetic",    icon: "🙏", desc: "Humble, takes responsibility" },
  { id: "friendly",     label: "Friendly",      icon: "😊", desc: "Warm and casual" },
  { id: "formal",       label: "Formal",        icon: "📜", desc: "Legal or official language" },
];

// ── Response Length Presets ─────────────────────────────────────────────────────
export const RESPONSE_LENGTHS = [
  { id: "brief",      label: "Brief",      icon: "⚡", tokens: 512,  instruction: "Respond in 2-3 sentences maximum. Be extremely concise." },
  { id: "standard",   label: "Standard",   icon: "◆",  tokens: 2048, instruction: "" },
  { id: "detailed",   label: "Detailed",   icon: "◈",  tokens: 4096, instruction: "Be thorough and comprehensive. Cover all aspects." },
  { id: "exhaustive", label: "Exhaustive", icon: "📚", tokens: 8192, instruction: "Provide an exhaustive, in-depth analysis. Cover every edge case and detail." },
];

export const SUPPORTED_FILE_TYPES = [
  // Documents
  ".txt", ".md", ".pdf", ".docx", ".doc", ".rtf",
  // Data
  ".csv", ".json", ".xml", ".yaml", ".yml", ".xlsx", ".xls",
  // Code
  ".js", ".jsx", ".ts", ".tsx", ".py", ".html", ".css", ".java", ".c", ".cpp", ".go", ".rs", ".rb", ".php", ".sql",
  // Archives (for Code mode multi-file review)
  ".zip",
  // Logs
  ".log", ".env",
];

// ── Voice Languages (expanded for Indian language support) ─────────────────────
export const VOICE_LANGUAGES = [
  { code: "en-US",  label: "English",   flag: "🇺🇸" },
  { code: "hi-IN",  label: "Hindi",     flag: "🇮🇳" },
  { code: "te-IN",  label: "Telugu",    flag: "🇮🇳" },
  { code: "mr-IN",  label: "Marathi",   flag: "🇮🇳" },
  { code: "gu-IN",  label: "Gujarati",  flag: "🇮🇳" },
  { code: "raj-IN", label: "Marwadi",   flag: "🇮🇳" },
  { code: "kn-IN",  label: "Kannada",   flag: "🇮🇳" },
  { code: "ta-IN",  label: "Tamil",     flag: "🇮🇳" },
];

export const PROMPT_IMPROVEMENT_MODES = [
  { id: "simple",    label: "Simple",    icon: "✨", desc: "Improve clarity & structure",      color: "#6b8afd" },
  { id: "developer", label: "Developer", icon: "⚙️", desc: "Technical precision & constraints", color: "#9dd4b0" },
  { id: "creative",  label: "Creative",  icon: "🎨", desc: "Vivid language & creativity",      color: "#d4a8c8" },
];

// ── Desktop Control Constants ──────────────────────────────────────────────────
export const DESKTOP_ACTIONS = {
  open_app:           { icon: "🚀", label: "Open App",           desc: "Launch an application" },
  open_url:           { icon: "🌐", label: "Open URL",           desc: "Open a website" },
  search_web:         { icon: "🔍", label: "Search Web",         desc: "Web search" },
  create_folder:      { icon: "📁", label: "Create Folder",      desc: "Create a new folder" },
  open_file_or_folder: { icon: "📂", label: "Open File/Folder",  desc: "Open a file or directory" },
  copy_to_clipboard:  { icon: "📋", label: "Copy to Clipboard",  desc: "Copy text" },
  type_text:          { icon: "⌨️", label: "Type Text",          desc: "Type into focused app" },
  press_hotkey:       { icon: "⌥",  label: "Press Hotkey",       desc: "Keyboard shortcut" },
  get_active_window:  { icon: "🪟", label: "Active Window",      desc: "Check focused app" },
};

export const DESKTOP_RISK_LEVELS = {
  low:    { label: "Low Risk",    color: "#00E5FF", icon: "🟢" },
  medium: { label: "Medium Risk", color: "#FFB020", icon: "🟡" },
  high:   { label: "High Risk",   color: "#FF2A2A", icon: "🔴" },
};
