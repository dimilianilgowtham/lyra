# Lyra

A personal assistant for macOS, built with React, Electron, and a local Python backend.

## Current scope

- Chat, writing, analysis, translation, study, and code assistance.
- Document attachments and local conversation history.
- Desktop text and voice conversations, personal memory review, and terminal access.
- Approval-controlled local file tools, desktop actions, web search, and multiple model providers.
- Persistent tasks, cancellation, resume after interruption, verified file receipts, and durable reminders while the backend runs.

The app opens the chat workspace. Use **Desktop** for the focused desktop assistant. Trading, 3D scenes, video studios, Agent Forge, simulated telemetry, unused login flows, the legacy dry-run planner, and duplicate cloud conversation sync have been removed.

## Run

```sh
npm install
python3 -m venv lyra-backend/.venv
lyra-backend/.venv/bin/python -m pip install -r lyra-backend/requirements.txt
```

Configure provider keys in `.env` using `.env.example`. Then:

```sh
npm run build
npm start
```

Electron starts the Python backend. For a browser preview, run `npm run dev`; desktop backend features also require `lyra-backend/.venv/bin/python lyra-backend/main.py`. The legacy `node agentic/tool-server.js` entry point now launches the same authenticated Python backend. It does not open a separate execution server.

## Saved data

Backend conversations, personal memories, and session metadata use SQLite at `lyra-backend/data/lyra.db`, or the configured absolute `DATABASE_PATH`. Existing `session_memory.json` is imported once on backend initialization and retained as a recovery copy. It is no longer written by the session-memory class.

Backend SQLite is authoritative for conversations and tasks. Existing browser conversations are imported additively, with local IndexedDB records retained as an offline cache and migration recovery source. Presentation preferences remain in localStorage. Text and desktop voice requests use the same task controller and conversation context.

## Verify

```sh
npm test
npm run build
```

Backend tests use a temporary database and do not write to saved user data. Live microphones, provider availability, and native macOS automation require separate testing on the host.

See [ROADMAP.md](ROADMAP.md) for remaining assistant work.

## Document retrieval

`POST /api/rag` uses the same `ExecutionPolicy` as the file tools. Local and Git search roots must be existing directories under `LYRA_WORKSPACE_ROOTS` (a path-separated list); relative paths resolve from the first configured root. Omitting `base_path` searches that root. Invalid roots return a client error before any search or model request.

Document search skips credential paths, symbolic links, dependency/build directories, binary files, and non-regular files. Each search examines at most 5,000 directory entries, reads at most 100 KiB per file and 10 MiB in total, and retains only the highest-ranked chunks. Results use keyword/path relevance with file and line citations.

Git retrieval requires a regular `.git` directory inside the selected root; linked worktrees and symlinked Git metadata are skipped. It disables external diffs, text converters, filesystem-monitor commands and pagers, ignores inherited Git repository overrides, caps command output, and terminates timed-out or cancelled processes.

Validation on 16 November 2026: **200 tests passed** (56 frontend, 144 backend), including 27 retrieval regressions; the frontend production build passed. Retrieval tests use synthetic files and a stubbed model, with a real temporary Git repository for history verification. They make no model requests.

## Terminal workspace

Open **Terminal workspace** from the sidebar. Set the working directory and, for an assessment, its scope or evidence context. Describe the work in plain language, for example: “Find which security tools are already installed; do not install anything or contact any hosts.” Lyra proposes commands for approval, executes accepted steps, and shows stdout, stderr, exit codes, and duration. Follow-up instructions retain recent command evidence.

Use **Shell command** only when you want to submit an exact command. Processes are non-interactive; password prompts and interactive applications are unsupported. Commands time out after 30 seconds by default (up to 300 when requested by the agent). Stop controls terminate the process group. Shell commands run on the host after approval; the working-directory policy is not an OS sandbox.

## Voice input

Click the microphone, speak, then click stop to transcribe. The transcript fills your draft for review. Recording stops after 30 seconds, and transcription can be cancelled. Microphone permission is required in the browser and macOS privacy settings.

Install the optional multilingual local model explicitly:

```sh
lyra-backend/.venv/bin/python scripts/setup_local_voice.py --install
```

The setup command downloads the optional model explicitly. Ordinary recording requests load only cached model files. `STT_PROVIDER=auto` prefers an installed local model; set `STT_PROVIDER=local` in the backend environment to prevent cloud fallback. Larger models can be installed with `--model base`, then selected using `LOCAL_STT_MODEL=base`. `GET /api/stt/status` reports actual configuration and local cache availability.

Offline transcription has been verified using generated speech and silence. Physical microphone and speaker behavior depends on host hardware and permissions.

## macOS application

The installer targets `/Applications/Lyra.app`; Dock integration is optional. Launching Lyra starts and monitors its bundled backend automatically. The installed app loads its built interface directly; it does not need Vite, Node, or the development Python environment.

Saved chats, configuration, and logs live in `~/Library/Application Support/Lyra/`. Installation imports existing data only when no installed profile exists, using SQLite's online backup so committed WAL changes are preserved. The original project data is retained. Credentials are stored in the private user configuration, never in the application bundle.

Rebuild on an Apple Silicon Mac:

```sh
lyra-backend/.venv/bin/python -m pip install -r packaging/requirements-build.txt
npm run package:mac
npm run install:mac
lyra-backend/.venv/bin/python scripts/pin_macos_dock.py
```

The package is ad-hoc signed for local use. Public distribution and notarization require an Apple developer signing identity. Inspect startup issues in `~/Library/Application Support/Lyra/logs/backend.log`. Closing the window keeps Lyra available; use **Lyra → Quit Lyra** to exit and stop its owned backend.

Packaging checks: `scripts/verify_frozen_backend.py` tests authenticated startup and offline speech without relying on a development Python executable. Desktop lifecycle, installed paths, and migration are also covered by `npm test`.
