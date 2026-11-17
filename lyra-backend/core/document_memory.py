"""
LYRA Document Memory & Grounding Engine
Provides indexed file chunking, full-text search with relevance ranking,
and structured citation generation [Source: filepath#Lstart-Lend].
"""

import heapq
import os
import re
import stat
from pathlib import Path

from core.execution_policy import ExecutionPolicy, PolicyError

_ALLOWED_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".md", ".json",
    ".css", ".html", ".yaml", ".yml", ".toml", ".sql", ".txt",
}

_SKIP_DIRS = {
    "node_modules", ".git", "__pycache__", "dist", "build",
    ".venv", "venv", ".next", ".cache",
}

MAX_CHUNK_LINES = 40
CHUNK_OVERLAP = 10
MAX_FILE_BYTES = 100 * 1024
MAX_TOTAL_BYTES = 10 * 1024 * 1024
MAX_SCAN_ENTRIES = 5000
MAX_RESULTS = 50
MAX_QUERY_LENGTH = 4096


def resolve_retrieval_root(raw=None, *, policy: ExecutionPolicy) -> Path:
    """Resolve caller input against the workspace policy, never against cwd."""
    if raw is not None and (not isinstance(raw, (str, Path)) or not str(raw).strip()
                            or len(str(raw)) > 4096):
        raise ValueError("Retrieval path must be a non-empty path of at most 4096 characters.")
    try:
        root = policy.resolve_path(raw if raw is not None else policy.default_root)
        if not root.is_dir():
            raise ValueError("Retrieval path must be an existing directory.")
    except (OSError, RuntimeError):
        raise PolicyError("Retrieval path could not be resolved safely.") from None
    return root


def _iter_files(root: Path, policy: ExecutionPolicy):
    """Count every directory entry, including excluded files and empty folders."""
    pending = [root]
    scanned = 0
    while pending and scanned < MAX_SCAN_ENTRIES:
        directory = pending.pop()
        try:
            if directory.is_symlink() or policy.resolve_path(directory) != directory:
                continue
            if not directory.is_relative_to(root):
                continue
            with os.scandir(directory) as entries:
                for entry in entries:
                    if scanned >= MAX_SCAN_ENTRIES:
                        return
                    scanned += 1
                    try:
                        if entry.is_symlink():
                            continue
                        path = directory / entry.name
                        resolved = policy.resolve_path(path)
                        if resolved != path or not resolved.is_relative_to(root):
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            if entry.name.lower() not in _SKIP_DIRS:
                                pending.append(resolved)
                        elif entry.is_file(follow_symlinks=False) and path.suffix.lower() in _ALLOWED_EXTENSIONS:
                            yield resolved
                    except (OSError, PolicyError, RuntimeError):
                        continue
        except (OSError, PolicyError, RuntimeError):
            continue


class DocumentChunk:
    def __init__(self, file_path: str, start_line: int, end_line: int, content: str):
        self.file_path = file_path
        self.start_line = start_line
        self.end_line = end_line
        self.content = content

    @property
    def citation(self) -> str:
        return f"[Source: {self.file_path}#L{self.start_line}-L{self.end_line}]"


class DocumentMemory:
    """Indexes and searches local codebase and documents with structured citations."""

    def __init__(self, root_dir: str | Path | None = None, *, policy: ExecutionPolicy | None = None):
        self.policy = policy if policy is not None else ExecutionPolicy()
        self.root_dir = root_dir

    def search_documents(self, query: str, max_results: int = 8) -> list[dict]:
        """
        Ranked search over codebase documents.
        Returns matches with exact file paths, line ranges, relevance scores, and citations.
        """
        if not isinstance(query, str) or len(query) > MAX_QUERY_LENGTH:
            raise ValueError(f"Search query must be text of at most {MAX_QUERY_LENGTH} characters.")
        if not isinstance(max_results, int) or isinstance(max_results, bool) or max_results < 1:
            raise ValueError("Search result limit must be a positive integer.")
        limit = min(max_results, MAX_RESULTS)
        policy = ExecutionPolicy(self.policy.roots)
        root = resolve_retrieval_root(self.root_dir, policy=policy)

        tokens = list(dict.fromkeys(t.lower() for t in re.findall(r"\w+", query) if len(t) > 2))[:64]
        if not tokens:
            return []

        # Retain only the best chunks, even when a query matches every line.
        scored_chunks: list[tuple[float, int, DocumentChunk]] = []
        total_bytes = 0
        order = 0

        for path in _iter_files(root, policy):
            if total_bytes >= MAX_TOTAL_BYTES:
                break
            try:
                if policy.resolve_path(path) != path:
                    continue
                # No-follow prevents a file replaced by a symlink from being opened.
                # Non-blocking plus fstat also makes a replacement FIFO safe to skip.
                flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
                descriptor = os.open(path, flags)
                with os.fdopen(descriptor, "rb") as stream:
                    info = os.fstat(stream.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE_BYTES:
                        continue
                    if policy.resolve_path(path) != path:
                        continue
                    remaining = MAX_TOTAL_BYTES - total_bytes
                    data = stream.read(min(MAX_FILE_BYTES, remaining) + 1)
                total_bytes += len(data)
                if total_bytes > MAX_TOTAL_BYTES:
                    break
                if len(data) > MAX_FILE_BYTES or b"\x00" in data:
                    continue
                lines = data.decode("utf-8", errors="replace").splitlines()
                rel_path = str(path.relative_to(root))
                path_lower = rel_path.lower()
            except (OSError, PolicyError, RuntimeError):
                continue

            for i in range(0, len(lines), MAX_CHUNK_LINES - CHUNK_OVERLAP):
                chunk_text = "\n".join(lines[i:i + MAX_CHUNK_LINES])
                chunk_lower = chunk_text.lower()
                score = sum(chunk_lower.count(token) * 1.5 + (3.0 if token in path_lower else 0)
                            for token in tokens)
                if score > 0:
                    chunk = DocumentChunk(rel_path, i + 1, min(len(lines), i + MAX_CHUNK_LINES), chunk_text)
                    entry = (score, -order, chunk)
                    order += 1
                    if len(scored_chunks) < limit:
                        heapq.heappush(scored_chunks, entry)
                    elif entry[:2] > scored_chunks[0][:2]:
                        heapq.heapreplace(scored_chunks, entry)

        return [{
            "file": chunk.file_path,
            "start_line": chunk.start_line,
            "end_line": chunk.end_line,
            "content": chunk.content,
            "citation": chunk.citation,
            "relevance_score": round(score, 2),
        } for score, _, chunk in sorted(scored_chunks, reverse=True)]


# Global document memory singleton
doc_memory = DocumentMemory()
