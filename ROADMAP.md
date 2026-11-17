# Lyra assistant status

## Implemented and checked

- One authenticated local backend for chat, voice requests, and manual tools.
- Persistent tasks, owner-bound approvals, cancellation, explicit restart recovery, and tool receipts.
- Guarded file access with credential exclusions and verified atomic writes. Shell commands require approval; they run on the host and are not an OS sandbox.
- Document and Git retrieval enforce configured workspace roots. Local document search excludes secrets and symbolic links, bounds scan/read volume, and preserves ranked line citations. Git queries bound output and clean up cancelled or timed-out processes.
- SQLite conversations, personal memories, session metadata, and reminders. Browser conversations migrate additively; failed migrations retain their source records.
- Durable reminder scheduling and delivery status. The backend must be running for reminders to fire.
- A focused desktop workspace with searchable history, document attachments, model selection, task inspection, and approval controls.
- Chat-driven terminal tasks with working directory and assessment context, exact command mode, output/exit-code receipts, cancellation, and retained evidence for follow-up analysis.

## Validation

Automated tests cover provider protocols, task recovery, approvals, cancellation races, file boundaries, memory migration, reminders, desktop handlers, and real authenticated API file writes.

Retrieval validation on 16 November 2026: 200 automated tests passed (56 frontend and 144 backend), including 27 new checks for credential exclusion, symlink escapes, caller-supplied roots, request-scoped policy, read/scan limits, authenticated API behavior, and Git cleanup. The frontend production build passed. No live model requests were made for this verification.

A bounded live check on October 16, 2026 completed through OpenRouter using `openai/gpt-4o-mini`: read synthetic input `41`, approve one exact output write, write `42`, and read the output back. This proves that workflow with the tested provider, not that every configured provider works. Run `scripts/verify_live_agent.py` to repeat it.

## Remaining work

- Calendar, email, and contacts account integrations.
- A publicly notarized macOS release and an installed background service for reminders while Lyra is quit. A locally signed, self-contained Apple Silicon application is installed with automatic backend startup and Dock integration.
- Physical microphone, speaker, screen interpretation, and macOS permission testing on the user's actual hardware. Local offline speech recognition is installed and verified with generated speech and silence; failing cloud credentials are no longer required for the local path.
- Broader real-world task evaluations and provider-specific availability checks. Configured credentials are not proof of availability.

Voice and terminal validation on October 16, 2026: 152 automated tests passed. Cached multilingual tiny speech recognition transcribed generated WAV and WebM/Opus offline; silence was rejected. Live terminal tasks executed approved local commands, exposed missing nmap honestly, and recalled prior curl/Python paths in a follow-up without new execution.
