"""
LYRA — Tool Registry
Central registry of all tools the AI agent can invoke.
Each tool has a name, description, JSON schema, approval requirement, and handler.
"""

import logging
from copy import deepcopy
from typing import Any, Callable, Awaitable
from core.execution_policy import ExecutionPolicy

logger = logging.getLogger("LYRA.ToolRegistry")


class ToolDefinition:
    """A single tool the agent can call."""

    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict,
        handler: Callable[..., Awaitable[dict]],
        requires_approval: bool = False,
    ) -> None:
        self.name = name
        self.description = description
        self.parameters = deepcopy(parameters)
        self.parameters.setdefault("additionalProperties", False)
        self.handler = handler
        self.requires_approval = ExecutionPolicy().requires_approval(name, requires_approval)

    def to_gemini_schema(self) -> dict:
        """Convert to Gemini function calling format."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }

    def to_openai_schema(self) -> dict:
        """Convert to OpenAI / OpenRouter function calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def to_anthropic_schema(self) -> dict:
        """Convert to Anthropic tool use format."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }


class ToolRegistry:
    """Central registry of available tools."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition) -> None:
        self._tools[tool.name] = tool
        logger.info(f"🔧 Registered tool: {tool.name} (approval={tool.requires_approval})")

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def list_tools(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def get_gemini_tools(self) -> list[dict]:
        """Get all tool schemas in Gemini function calling format."""
        return [t.to_gemini_schema() for t in self._tools.values()]

    def get_openai_tools(self) -> list[dict]:
        """Get all tool schemas in OpenAI/OpenRouter format."""
        return [t.to_openai_schema() for t in self._tools.values()]

    def get_anthropic_tools(self) -> list[dict]:
        """Get all tool schemas in Anthropic tool format."""
        return [t.to_anthropic_schema() for t in self._tools.values()]

    def requires_approval(self, name: str) -> bool:
        tool = self._tools.get(name)
        return tool.requires_approval if tool else True  # Default to requiring approval


def build_default_registry() -> ToolRegistry:
    """Build the registry with all default LYRA tools."""
    from tools.shell import execute_command
    from tools.filesystem import read_file, write_file, list_directory, search_files
    from tools.vision import take_screenshot
    from desktop.control import (
        open_app,
        close_app,
        set_volume,
        mute,
        unmute,
        open_url,
        create_folder,
        get_active_window,
        toggle_dark_mode,
        get_system_stats,
    )
    from tools.web_search import web_search
    from tools.system_utils import get_clipboard, set_clipboard, send_notification, get_wifi_info, get_battery_info
    from tools.claude_code import run_claude_code

    registry = ToolRegistry()

    # ── Shell ─────────────────────────────────────────────────
    registry.register(ToolDefinition(
        name="execute_command",
        description="Run a shell command after explicit user consent. This is not an OS sandbox. Exit zero confirms process completion; verify requested changes independently.",
        parameters={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute (e.g. 'ls -la', 'git status', 'python script.py')",
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory within configured workspace roots. Defaults to the project workspace.",
                },
                "timeout": {"type": "integer", "minimum": 1, "maximum": 300, "description": "Maximum command runtime in seconds; default 30. Interactive input is unavailable."},
            },
            "required": ["command"],
        },
        handler=execute_command,
        requires_approval=True,
    ))

    # ── File Read ─────────────────────────────────────────────
    registry.register(ToolDefinition(
        name="read_file",
        description="Read the contents of a file. Returns the content with line numbers. Use to inspect source code, config files, logs, etc.",
        parameters={
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Absolute or ~-relative path to the file to read.",
                },
                "max_lines": {
                    "type": "integer",
                    "description": "Maximum number of lines to read. Default 500.",
                },
            },
            "required": ["filepath"],
        },
        handler=read_file,
        requires_approval=False,
    ))

    # ── File Write ────────────────────────────────────────────
    registry.register(ToolDefinition(
        name="write_file",
        description="Write content to a file. Creates parent directories if needed. Use for creating new files or replacing file contents entirely.",
        parameters={
            "type": "object",
            "properties": {
                "filepath": {
                    "type": "string",
                    "description": "Absolute or ~-relative path to the file to write.",
                },
                "content": {
                    "type": "string",
                    "description": "The full content to write to the file.",
                },
            },
            "required": ["filepath", "content"],
        },
        handler=write_file,
        requires_approval=True,
    ))

    # ── List Directory ────────────────────────────────────────
    registry.register(ToolDefinition(
        name="list_directory",
        description="List files and subdirectories in a given path. Useful for exploring project structure.",
        parameters={
            "type": "object",
            "properties": {
                "dirpath": {
                    "type": "string",
                    "description": "Path to the directory to list. Defaults to ~/Desktop.",
                },
            },
            "required": [],
        },
        handler=list_directory,
        requires_approval=False,
    ))

    # ── Search Files ──────────────────────────────────────────
    registry.register(ToolDefinition(
        name="search_files",
        description="Search for literal text across workspace files. Skips credentials, symlinks and dependencies; returns actual matching lines with paths and line numbers.",
        parameters={
            "type": "object",
            "properties": {
                "pattern": {
                    "type": "string",
                    "description": "The text pattern or regex to search for.",
                },
                "search_path": {
                    "type": "string",
                    "description": "Root directory to search in. Defaults to the Lyra project.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return. Default 50.",
                },
            },
            "required": ["pattern"],
        },
        handler=search_files,
        requires_approval=False,
    ))

    # ── Screenshot ────────────────────────────────────────────
    registry.register(ToolDefinition(
        name="take_screenshot",
        description="Capture a screenshot of the user's macOS screen. Returns the image as base64 PNG for visual analysis.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
        handler=take_screenshot,
        requires_approval=False,
    ))

    # ── Open App ──────────────────────────────────────────────
    registry.register(ToolDefinition(
        name="open_app",
        description="Launch a macOS application by name (e.g. 'chrome', 'vscode', 'terminal', 'spotify').",
        parameters={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Application name or alias (e.g. 'chrome', 'vscode', 'terminal').",
                },
            },
            "required": ["name"],
        },
        handler=open_app,
        requires_approval=False,
    ))

    # ── System Stats ──────────────────────────────────────────
    registry.register(ToolDefinition(
        name="get_system_stats",
        description="Get current system statistics: CPU usage, memory usage, disk usage, uptime, process count, and network speeds.",
        parameters={
            "type": "object",
            "properties": {},
            "required": [],
        },
        handler=get_system_stats,
        requires_approval=False,
    ))

    # ── Web Search (Odysseus-inspired) ────────────────────────
    registry.register(ToolDefinition(
        name="web_search",
        description="Search the web for real-time information. Use for current events, recent news, prices, weather, documentation, etc.",
        parameters={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query.",
                },
            },
            "required": ["query"],
        },
        handler=web_search,
        requires_approval=False,
    ))

    # ── Clipboard ─────────────────────────────────────────────
    registry.register(ToolDefinition(
        name="get_clipboard",
        description="Read the current clipboard contents.",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=get_clipboard,
        requires_approval=False,
    ))

    registry.register(ToolDefinition(
        name="set_clipboard",
        description="Copy text to the system clipboard.",
        parameters={
            "type": "object",
            "properties": {"text": {"type": "string", "description": "Text to copy."}},
            "required": ["text"],
        },
        handler=set_clipboard,
        requires_approval=False,
    ))

    # ── Notifications ─────────────────────────────────────────
    registry.register(ToolDefinition(
        name="send_notification",
        description="Send a macOS notification. Use to alert the user about completed tasks.",
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Notification title."},
                "message": {"type": "string", "description": "Notification body."},
            },
            "required": ["message"],
        },
        handler=send_notification,
        requires_approval=False,
    ))

    # ── System Info ───────────────────────────────────────────
    registry.register(ToolDefinition(
        name="get_wifi_info",
        description="Get the current WiFi network name, signal strength, and connection details.",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=get_wifi_info,
        requires_approval=False,
    ))

    registry.register(ToolDefinition(
        name="get_battery_info",
        description="Get current battery percentage, charging status, and power source.",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=get_battery_info,
        requires_approval=False,
    ))

    # ── macOS System & App Control ─────────────────────────────
    registry.register(ToolDefinition(
        name="close_app",
        description="Gracefully quit or close a running macOS application (e.g. 'chrome', 'spotify', 'slack').",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Name of the application to close."},
            },
            "required": ["name"],
        },
        handler=close_app,
        requires_approval=False,
    ))

    registry.register(ToolDefinition(
        name="set_volume",
        description="Set macOS system output volume to a percentage from 0 to 100.",
        parameters={
            "type": "object",
            "properties": {
                "level": {"type": "integer", "description": "Volume percentage (0-100)."},
            },
            "required": ["level"],
        },
        handler=set_volume,
        requires_approval=False,
    ))

    registry.register(ToolDefinition(
        name="mute_volume",
        description="Mute system audio output on macOS.",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=mute,
        requires_approval=False,
    ))

    registry.register(ToolDefinition(
        name="unmute_volume",
        description="Unmute system audio output on macOS.",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=unmute,
        requires_approval=False,
    ))

    registry.register(ToolDefinition(
        name="open_url",
        description="Open a web URL in the user's default macOS browser.",
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "The URL to open, e.g. 'https://github.com'."},
            },
            "required": ["url"],
        },
        handler=open_url,
        requires_approval=False,
    ))

    registry.register(ToolDefinition(
        name="create_folder",
        description="Create a new folder on the user's Desktop or Documents.",
        parameters={
            "type": "object",
            "properties": {
                "folder_name": {"type": "string", "description": "Name of the folder to create."},
                "base_path": {"type": "string", "description": "Optional parent path. Defaults to ~/Desktop."},
            },
            "required": ["folder_name"],
        },
        handler=create_folder,
        requires_approval=False,
    ))

    registry.register(ToolDefinition(
        name="get_active_window",
        description="Get the application name and window title of the frontmost window on macOS.",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=get_active_window,
        requires_approval=False,
    ))

    registry.register(ToolDefinition(
        name="toggle_dark_mode",
        description="Toggle macOS between Dark Mode and Light Mode.",
        parameters={"type": "object", "properties": {}, "required": []},
        handler=toggle_dark_mode,
        requires_approval=False,
    ))

    # ── Claude Code Autonomous Developer Tool ─────────────────
    registry.register(ToolDefinition(
        name="run_claude_code",
        description="Execute complex coding, debugging, refactoring, and project architecture tasks using the local Claude Code CLI engine. Highly recommended for multi-file edits, codebase diagnostics, and running tests.",
        parameters={
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The specific coding or refactoring instruction for Claude Code.",
                },
                "cwd": {
                    "type": "string",
                    "description": "Optional working directory path. Defaults to the current workspace root.",
                },
            },
            "required": ["prompt"],
        },
        handler=run_claude_code,
        requires_approval=True,
    ))

    logger.info(f"🔧 Tool registry built with {len(registry._tools)} tools")
    return registry
