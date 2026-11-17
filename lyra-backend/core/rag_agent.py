"""
LYRA — RAG (Retrieval-Augmented Generation) Agent
Searches web, local files, and git history, then synthesises an AI answer
grounded in the retrieved context.
"""

import asyncio
import html
import logging
import os
import re
import time
import httpx

from core.document_memory import DocumentMemory, MAX_QUERY_LENGTH, resolve_retrieval_root
from core.execution_policy import ExecutionPolicy, PolicyError

logger = logging.getLogger("LYRA.RAG")

# ── Constants ────────────────────────────────────────────────────

_CONTEXT_CHAR_LIMIT = 4000
_SEARCH_TIMEOUT = 10.0
_GIT_TIMEOUT = 10.0
_MAX_GIT_OUTPUT_BYTES = 64 * 1024


class RAGAgent:
    """Retrieval-Augmented Generation agent for LYRA."""

    def __init__(self, ai_orchestrator, *, policy: ExecutionPolicy | None = None) -> None:
        self.ai = ai_orchestrator
        self.policy = policy if policy is not None else ExecutionPolicy()

    # ── Web search (DuckDuckGo Lite) ─────────────────────────────

    async def search_web(self, query: str) -> list[dict]:
        """Fetch top-5 results from DuckDuckGo Lite (HTML scrape)."""
        try:
            async with httpx.AsyncClient(
                timeout=_SEARCH_TIMEOUT,
                follow_redirects=True,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                },
            ) as client:
                resp = await client.post(
                    "https://lite.duckduckgo.com/lite/",
                    data={"q": query},
                )
                resp.raise_for_status()
                return self._parse_ddg_html(resp.text)
        except httpx.TimeoutException:
            logger.warning("DuckDuckGo search timed out for query: %s", query)
            return []
        except httpx.HTTPStatusError as exc:
            logger.warning("DuckDuckGo HTTP %s for query: %s", exc.response.status_code, query)
            return []
        except Exception as exc:
            logger.error("Web search failed: %s", exc, exc_info=True)
            return []

    @staticmethod
    def _parse_ddg_html(raw_html: str) -> list[dict]:
        """Extract up to 5 results from DuckDuckGo Lite HTML."""
        results: list[dict] = []
        try:
            # DuckDuckGo Lite wraps each result link in <a class="result-link">
            # but the markup varies — use a broad regex approach.
            link_pattern = re.compile(
                r'<a[^>]+rel="nofollow"[^>]+href="([^"]+)"[^>]*>\s*(.*?)\s*</a>',
                re.DOTALL,
            )
            # Snippet lines sit in <td> after the link row
            snippet_pattern = re.compile(
                r'<td\s+class="result-snippet"[^>]*>(.*?)</td>',
                re.DOTALL,
            )

            links = link_pattern.findall(raw_html)
            snippets = snippet_pattern.findall(raw_html)

            for idx, (url, title_raw) in enumerate(links[:5]):
                title = re.sub(r"<[^>]+>", "", title_raw).strip()
                title = html.unescape(title)
                snippet = ""
                if idx < len(snippets):
                    snippet = re.sub(r"<[^>]+>", "", snippets[idx]).strip()
                    snippet = html.unescape(snippet)
                if url and title:
                    results.append({"title": title, "snippet": snippet, "url": url})
        except Exception as exc:
            logger.error("HTML parse error: %s", exc)
        return results

    # ── Local file search ────────────────────────────────────────

    async def search_local(
        self,
        query: str,
        base_path: str | None = None,
    ) -> list[dict]:
        """Search local documents with chunking and structured citations."""
        # Capture request-scoped roots before moving file reads to a worker.
        policy = ExecutionPolicy(self.policy.roots)
        root = resolve_retrieval_root(base_path, policy=policy)
        memory = DocumentMemory(str(root), policy=policy)
        return await asyncio.to_thread(memory.search_documents, query)


    # ── Git history search ───────────────────────────────────────

    async def search_git(
        self,
        query: str,
        repo_path: str | None = None,
    ) -> dict:
        """Search git log (message grep + pickaxe) and show uncommitted diff."""
        repo = resolve_retrieval_root(repo_path, policy=ExecutionPolicy(self.policy.roots))

        # Linked metadata may target files beyond the selected search root.
        metadata = repo / ".git"
        if metadata.is_symlink() or not metadata.is_dir():
            logger.warning("Not a valid git repo: %s", repo)
            return {"commits": [], "pickaxe": [], "uncommitted": ""}

        async def _git(*args: str) -> str:
            proc = None
            try:
                # Inherited Git overrides must not redirect a query to another repo.
                env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
                env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                           GIT_OPTIONAL_LOCKS="0", GIT_TERMINAL_PROMPT="0")
                proc = await asyncio.create_subprocess_exec(
                    "git", "--no-pager", "-c", "core.fsmonitor=false", *args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    cwd=str(repo),
                    env=env,
                )

                async def collect() -> str:
                    output = bytearray()
                    while True:
                        chunk = await proc.stdout.read(min(8192, _MAX_GIT_OUTPUT_BYTES + 1 - len(output)))
                        if not chunk:
                            break
                        output.extend(chunk)
                        if len(output) > _MAX_GIT_OUTPUT_BYTES:
                            raise ValueError("Git search output exceeded its byte limit.")
                    code = await proc.wait()
                    return output.decode(errors="replace").strip() if code == 0 else ""

                return await asyncio.wait_for(collect(), timeout=_GIT_TIMEOUT)
            except asyncio.TimeoutError:
                logger.warning("Git command timed out: git %s", " ".join(args))
                return ""
            except Exception as exc:
                logger.warning("Git search failed: %s", type(exc).__name__)
                return ""
            finally:
                if proc is not None and proc.returncode is None:
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        pass
                    await proc.wait()

        # Run all three in parallel
        log_out, pickaxe_out, diff_out = await asyncio.gather(
            _git("log", "--no-ext-diff", "--no-textconv", "--no-show-signature", "--all", "--oneline", f"--grep={query}", "-n", "15"),
            _git("log", "--no-ext-diff", "--no-textconv", "--no-show-signature", "--all", "--oneline", f"-S{query}", "-n", "10"),
            _git("diff", "--no-ext-diff", "--no-textconv", "--stat", "HEAD"),
        )

        def _parse_oneline(text: str) -> list[dict]:
            entries: list[dict] = []
            for line in text.splitlines():
                parts = line.split(None, 1)
                if len(parts) == 2:
                    entries.append({"hash": parts[0], "message": parts[1]})
            return entries

        return {
            "commits": _parse_oneline(log_out),
            "pickaxe": _parse_oneline(pickaxe_out),
            "uncommitted": diff_out,
        }

    # ── Top-level query (retrieve → augment → generate) ──────────

    async def query(
        self,
        user_query: str,
        sources: list[str] | None = None,
        base_path: str | None = None,
    ) -> dict:
        """Run RAG pipeline: search → build context → synthesise answer."""
        if not isinstance(user_query, str) or not user_query.strip() or len(user_query) > MAX_QUERY_LENGTH:
            raise ValueError(f"Query must be non-empty text of at most {MAX_QUERY_LENGTH} characters.")
        if sources is None:
            sources = ["local", "git"]
        if (not isinstance(sources, list) or not 1 <= len(sources) <= 3
                or any(not isinstance(source, str) or source not in {"web", "local", "git"} for source in sources)):
            raise ValueError("Sources must contain one to three entries from web, local, and git.")
        sources = list(dict.fromkeys(sources))
        if base_path is not None and (not isinstance(base_path, str) or not base_path.strip() or len(base_path) > 4096):
            raise ValueError("Retrieval path must be a non-empty path of at most 4096 characters.")
        if {"local", "git"}.intersection(sources):
            # Fail before any web request, subprocess, worker, or AI synthesis.
            base_path = str(resolve_retrieval_root(base_path, policy=ExecutionPolicy(self.policy.roots)))

        t0 = time.perf_counter()
        result_counts: dict[str, int] = {}
        context_parts: list[str] = []

        # ── 1. Gather results in parallel ─────────────────────────
        tasks: dict[str, asyncio.Task] = {}

        if "web" in sources:
            tasks["web"] = asyncio.ensure_future(self.search_web(user_query))
        if "local" in sources:
            tasks["local"] = asyncio.ensure_future(self.search_local(user_query, base_path))
        if "git" in sources:
            tasks["git"] = asyncio.ensure_future(self.search_git(user_query, base_path))

        gathered = await asyncio.gather(*tasks.values(), return_exceptions=True)
        for result in gathered:
            if isinstance(result, PolicyError):
                raise result
        results = dict(zip(tasks.keys(), gathered))

        # ── 2. Assemble context ───────────────────────────────────
        # Web
        web_results = results.get("web", [])
        if isinstance(web_results, Exception):
            logger.error("Web search raised: %s", web_results)
            web_results = []
        result_counts["web"] = len(web_results)
        if web_results:
            lines = ["## Web Results"]
            for r in web_results[:5]:
                lines.append(f"- **{r['title']}**: {r['snippet']} ({r['url']})")
            context_parts.append("\n".join(lines))

        # Local
        local_results = results.get("local", [])
        if isinstance(local_results, Exception):
            logger.error("Local search raised: %s", local_results)
            local_results = []
        result_counts["local"] = len(local_results)
        if local_results:
            lines = ["## Local Code & Documents (with Citations)"]
            for r in local_results[:8]:
                citation = r.get("citation", f"[Source: {r.get('file', 'unknown')}]")
                lines.append(f"### {citation}\n```\n{r.get('content', '')}\n```\n")
            context_parts.append("\n".join(lines))

        # Git
        git_results = results.get("git", {})
        if isinstance(git_results, Exception):
            logger.error("Git search raised: %s", git_results)
            git_results = {}
        git_count = len(git_results.get("commits", [])) + len(git_results.get("pickaxe", []))
        result_counts["git"] = git_count
        if git_count:
            lines = ["## Git History"]
            for c in git_results.get("commits", []):
                lines.append(f"- [{c['hash']}] {c['message']}")
            if git_results.get("pickaxe"):
                lines.append("### Code-change commits (pickaxe)")
                for c in git_results["pickaxe"]:
                    lines.append(f"- [{c['hash']}] {c['message']}")
            if git_results.get("uncommitted"):
                lines.append(f"### Uncommitted changes\n```\n{git_results['uncommitted']}\n```")
            context_parts.append("\n".join(lines))

        context = "\n\n".join(context_parts)
        if len(context) > _CONTEXT_CHAR_LIMIT:
            context = context[:_CONTEXT_CHAR_LIMIT] + "\n…(truncated)"

        # ── 4. Synthesise answer via AI ───────────────────────────
        try:
            answer = await self.ai.chat_with_context(user_query, context)
        except Exception as exc:
            logger.error("AI synthesis failed: %s", exc)
            answer = "I retrieved some results but couldn't generate a summary."

        elapsed_ms = round((time.perf_counter() - t0) * 1000, 1)
        logger.info(
            "RAG query completed in %.1f ms — web:%d local:%d git:%d",
            elapsed_ms,
            result_counts.get("web", 0),
            result_counts.get("local", 0),
            result_counts.get("git", 0),
        )

        return {
            "answer": answer,
            "sources_used": [s for s in sources if result_counts.get(s, 0) > 0],
            "result_counts": result_counts,
            "timing_ms": elapsed_ms,
        }
