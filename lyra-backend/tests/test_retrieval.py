"""Retrieval must honor the same file boundaries as approved workspace tools."""

import asyncio
from contextlib import nullcontext
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings
from core.document_memory import DocumentMemory
from core.execution_policy import ExecutionPolicy, PolicyError, approved_tool_context
from core.rag_agent import RAGAgent


class DocumentRetrievalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "workspace"
        self.root.mkdir()
        self.outside = self.root.parent / "outside"
        self.outside.mkdir()
        self.roots = patch.object(settings, "WORKSPACE_ROOTS", (self.root, self.outside))
        self.roots.start()
        self.addCleanup(self.roots.stop)

    def test_public_documents_keep_ranked_content_and_exact_line_citations(self):
        (self.root / "notes.md").write_text("Introduction\nretrieval works\n", encoding="utf-8")
        result = DocumentMemory(str(self.root)).search_documents("retrieval")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["file"], "notes.md")
        self.assertEqual(result[0]["content"], "Introduction\nretrieval works")
        self.assertEqual(result[0]["citation"], "[Source: notes.md#L1-L2]")

    def test_credential_files_and_private_directories_are_excluded(self):
        (self.root / "public.md").write_text("retrieval public")
        secret_paths = ["credentials.json", "service-account.json", ".env", ".env.local.json",
                        ".aws/settings.json", ".ssh/notes.txt", ".config/account.json",
                        ".codex/config.toml", ".git/config.json"]
        for name in secret_paths:
            path = self.root / name
            path.parent.mkdir(exist_ok=True)
            path.write_text("retrieval synthetic secret")
        results = DocumentMemory(str(self.root)).search_documents("retrieval", max_results=50)
        self.assertEqual([r["file"] for r in results], ["public.md"])

    def test_symlinks_do_not_import_files_even_from_another_allowed_root(self):
        (self.outside / "external.txt").write_text("retrieval outside")
        (self.root / "public.md").write_text("retrieval public")
        (self.root / "escaped.txt").symlink_to(self.outside / "external.txt")
        (self.root / "escaped-directory").symlink_to(self.outside, target_is_directory=True)
        (self.root / "internal-link.md").symlink_to(self.root / "public.md")
        results = DocumentMemory(str(self.root)).search_documents("retrieval", max_results=50)
        self.assertEqual([r["file"] for r in results], ["public.md"])

    def test_root_is_checked_against_configured_policy(self):
        with patch.object(settings, "WORKSPACE_ROOTS", (self.root,)):
            for path in [self.outside, self.root / ".." / "outside", self.root / ".aws"]:
                with self.subTest(path=path), self.assertRaises(PolicyError):
                    DocumentMemory(str(path)).search_documents("retrieval")

    def test_default_root_comes_from_policy(self):
        (self.root / "notes.md").write_text("retrieval default workspace")
        results = DocumentMemory().search_documents("retrieval")
        self.assertEqual(len(results), 1)
        self.assertIn("default workspace", results[0]["content"])

    def test_large_binary_and_non_regular_files_are_skipped(self):
        (self.root / "public.md").write_text("retrieval public")
        (self.root / "large.txt").write_bytes(b"retrieval " * 11000)
        (self.root / "binary.txt").write_bytes(b"retrieval\x00binary")
        os.mkfifo(self.root / "pipe.txt")
        results = DocumentMemory(str(self.root)).search_documents("retrieval", max_results=50)
        self.assertEqual([r["file"] for r in results], ["public.md"])

    def test_symlink_root_cannot_escape_workspace_policy(self):
        (self.root / "escape").symlink_to(self.outside, target_is_directory=True)
        with patch.object(settings, "WORKSPACE_ROOTS", (self.root,)), self.assertRaises(PolicyError):
            DocumentMemory(str(self.root / "escape")).search_documents("retrieval")

    def test_file_replaced_by_symlink_at_open_is_skipped(self):
        path = self.root / "notes.txt"
        path.write_text("retrieval public")
        outside = self.outside / "outside.txt"
        outside.write_text("retrieval synthetic-outside-marker")
        real_open = os.open

        def replace_before_open(candidate, flags):
            if candidate == path:
                path.unlink()
                path.symlink_to(outside)
            return real_open(candidate, flags)

        with patch("core.document_memory.os.open", side_effect=replace_before_open):
            self.assertEqual(DocumentMemory(str(self.root)).search_documents("retrieval"), [])

    def test_scan_budget_counts_irrelevant_entries(self):
        for name in ["a.bin", "b.bin", "c.md"]:
            (self.root / name).write_text("retrieval evidence")
        real_scandir = os.scandir

        def ordered_scandir(directory):
            with real_scandir(directory) as entries:
                return nullcontext(iter(sorted(entries, key=lambda entry: entry.name)))

        with patch("core.document_memory.MAX_SCAN_ENTRIES", 2), patch("core.document_memory.os.scandir", side_effect=ordered_scandir):
            self.assertEqual(DocumentMemory(str(self.root)).search_documents("retrieval"), [])

    def test_total_read_budget_stops_before_importing_another_document(self):
        for index in range(3):
            (self.root / f"{index}.txt").write_text("retrieval " * 6)
        with patch("core.document_memory.MAX_TOTAL_BYTES", 100):
            results = DocumentMemory(str(self.root)).search_documents("retrieval")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["content"], "retrieval " * 6)

    def test_growing_file_cannot_bypass_the_read_limit(self):
        path = self.root / "growing.txt"
        path.write_text("retrieval " * 11000)
        stale_stat = SimpleNamespace(st_size=1, st_mode=path.stat().st_mode)
        with patch("core.document_memory.os.fstat", return_value=stale_stat):
            self.assertEqual(DocumentMemory(str(self.root)).search_documents("retrieval"), [])

    def test_later_better_matches_win_with_a_bounded_result_count(self):
        for index in range(1, 6):
            (self.root / f"{index}.md").write_text("retrieval " * index)
        results = DocumentMemory(str(self.root)).search_documents("retrieval", max_results=2)
        self.assertEqual([r["file"] for r in results], ["5.md", "4.md"])

    def test_explicit_policy_and_relative_search_root_are_supported(self):
        nested = self.root / "docs"
        nested.mkdir()
        (nested / "guide.md").write_text("retrieval guide")
        with patch.object(settings, "WORKSPACE_ROOTS", (self.outside,)):
            result = DocumentMemory("docs", policy=ExecutionPolicy([self.root])).search_documents("retrieval")
        self.assertEqual(result[0]["file"], "guide.md")


class RAGBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / "workspace"
        self.root.mkdir()
        self.outside = self.root.parent / "outside"
        self.outside.mkdir()
        self.roots = patch.object(settings, "WORKSPACE_ROOTS", (self.root,))
        self.roots.start()
        self.addCleanup(self.roots.stop)
        self.ai = AsyncMock()
        self.ai.chat_with_context.return_value = "Grounded answer"
        self.agent = RAGAgent(self.ai)

    async def test_invalid_root_rejected_before_any_search_or_model_request(self):
        for sources in [["local"], ["git"], ["web", "local", "git"]]:
            with self.subTest(sources=sources), patch.object(self.agent, "search_web", new_callable=AsyncMock) as web:
                with self.assertRaises(PolicyError):
                    await self.agent.query("retrieval", sources, str(self.outside))
                web.assert_not_awaited()
        self.ai.chat_with_context.assert_not_awaited()

    async def test_direct_git_search_rejects_outside_root(self):
        (self.outside / ".git").mkdir()
        with patch("core.rag_agent.asyncio.create_subprocess_exec", new_callable=AsyncMock) as spawn:
            with self.assertRaises(PolicyError):
                await self.agent.search_git("retrieval", str(self.outside))
        spawn.assert_not_awaited()

    async def test_direct_local_search_rejects_outside_root(self):
        with self.assertRaises(PolicyError):
            await self.agent.search_local("retrieval", str(self.outside))

    async def test_git_metadata_symlink_is_not_followed(self):
        metadata = self.outside / ".git"
        metadata.mkdir()
        (self.root / ".git").symlink_to(metadata, target_is_directory=True)
        with patch("core.rag_agent.asyncio.create_subprocess_exec", new_callable=AsyncMock) as spawn:
            result = await self.agent.search_git("retrieval", str(self.root))
        self.assertEqual(result, {"commits": [], "pickaxe": [], "uncommitted": ""})
        spawn.assert_not_awaited()

    async def test_git_search_keeps_real_history_and_ignores_inherited_repo_overrides(self):
        env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)

        def git(*args):
            subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false",
                            "-c", "user.name=Lyra Test", "-c", "user.email=lyra@example.invalid", *args],
                           cwd=self.root, env=env, check=True, capture_output=True)

        git("init")
        (self.root / "public.md").write_text("retrieval public evidence")
        git("add", "--", "public.md")
        git("commit", "-m", "retrieval public change")
        with patch.dict(os.environ, {"GIT_DIR": str(self.outside / "missing"), "GIT_WORK_TREE": str(self.outside)}):
            result = await self.agent.search_git("retrieval", str(self.root))
        self.assertEqual(result["commits"][0]["message"], "retrieval public change")
        self.assertEqual(result["pickaxe"][0]["message"], "retrieval public change")

    def git_processes(self, data=None):
        processes = []
        for _ in range(3):
            stream = asyncio.StreamReader()
            if data is not None:
                stream.feed_data(data)
                stream.feed_eof()
            process = SimpleNamespace(stdout=stream, returncode=None, wait=AsyncMock(return_value=-9))
            process.kill = Mock(side_effect=lambda process=process: setattr(process, "returncode", -9))
            processes.append(process)
        return processes

    async def test_git_timeout_terminates_every_started_process(self):
        (self.root / ".git").mkdir()
        processes = self.git_processes()
        with patch("core.rag_agent._GIT_TIMEOUT", 0.01), patch("core.rag_agent.asyncio.create_subprocess_exec", new_callable=AsyncMock, side_effect=processes):
            result = await self.agent.search_git("retrieval", str(self.root))
        self.assertEqual(result["commits"], [])
        for process in processes:
            process.kill.assert_called_once()
            process.wait.assert_awaited()

    async def test_git_output_budget_terminates_oversized_results(self):
        (self.root / ".git").mkdir()
        processes = self.git_processes(b"synthetic git output" * 10)
        with patch("core.rag_agent._MAX_GIT_OUTPUT_BYTES", 32), patch("core.rag_agent.asyncio.create_subprocess_exec", new_callable=AsyncMock, side_effect=processes):
            result = await self.agent.search_git("retrieval", str(self.root))
        self.assertEqual(result, {"commits": [], "pickaxe": [], "uncommitted": ""})
        for process in processes:
            process.kill.assert_called_once()

    async def test_git_cancellation_terminates_started_processes(self):
        (self.root / ".git").mkdir()
        processes = self.git_processes()
        with patch("core.rag_agent.asyncio.create_subprocess_exec", new_callable=AsyncMock, side_effect=processes) as spawn:
            task = asyncio.create_task(self.agent.search_git("retrieval", str(self.root)))
            for _ in range(100):
                if spawn.await_count == 3:
                    break
                await asyncio.sleep(0)
            self.assertEqual(spawn.await_count, 3)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        for process in processes:
            process.kill.assert_called_once()

    async def test_worker_search_preserves_request_specific_policy(self):
        (self.root / "notes.md").write_text("retrieval scoped workspace")
        with patch.object(settings, "WORKSPACE_ROOTS", (self.outside,)):
            with approved_tool_context(False, policy=ExecutionPolicy([self.root])):
                result = await self.agent.search_local("retrieval", str(self.root))
        self.assertEqual(len(result), 1)
        self.assertIn("scoped workspace", result[0]["content"])

    async def test_only_public_content_is_sent_to_the_model(self):
        (self.root / "public.md").write_text("retrieval public evidence")
        (self.root / "credentials.json").write_text("retrieval synthetic-secret-marker")
        (self.outside / "external.txt").write_text("retrieval synthetic-outside-marker")
        (self.root / "escape.txt").symlink_to(self.outside / "external.txt")
        result = await self.agent.query("retrieval", ["local"], str(self.root))
        context = self.ai.chat_with_context.await_args.args[1]
        self.assertIn("public evidence", context)
        self.assertIn("[Source: public.md#L1-L1]", context)
        self.assertNotIn("synthetic-secret-marker", context)
        self.assertNotIn("synthetic-outside-marker", context)
        self.assertEqual(result["result_counts"]["local"], 1)


class RetrievalAPITests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from main import app
        self.client = TestClient(app, headers={"Authorization": f"Bearer {settings.BACKEND_AUTH_TOKEN}"})

    def test_outside_root_is_an_error_without_model_synthesis(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "workspace"
            root.mkdir()
            outside = Path(temp) / "outside"
            outside.mkdir()
            with patch.object(settings, "WORKSPACE_ROOTS", (root,)), patch("main.rag_agent.ai.chat_with_context", new_callable=AsyncMock, return_value="unexpected synthesis") as model:
                response = self.client.post("/api/rag", json={"query": "retrieval", "sources": ["local"], "base_path": str(outside)})
        self.assertEqual(response.status_code, 400, response.text)
        model.assert_not_awaited()

    def test_invalid_payloads_return_client_errors_without_synthesis(self):
        payloads = [{"query": "   "}, {"query": ["retrieval"]}, {"query": "x" * 4097},
                    {"query": "retrieval", "sources": "local"}, {"query": "retrieval", "sources": []},
                    {"query": "retrieval", "sources": ["unknown"]}, {"query": "retrieval", "sources": [{}]},
                    {"query": "retrieval", "base_path": ["/tmp"]}, {"query": "retrieval", "base_path": ""}]
        with patch("main.rag_agent.ai.chat_with_context", new_callable=AsyncMock, return_value="unexpected synthesis") as model:
            for payload in payloads:
                with self.subTest(payload=payload):
                    response = self.client.post("/api/rag", json=payload)
                    self.assertEqual(response.status_code, 400, response.text)
        model.assert_not_awaited()

    def test_default_workspace_retrieval_preserves_response_and_citations(self):
        with tempfile.TemporaryDirectory() as temp:
            (Path(temp) / "notes.md").write_text("retrieval public evidence")
            (Path(temp) / "credentials.json").write_text("retrieval synthetic-secret-marker")
            with patch.object(settings, "WORKSPACE_ROOTS", (Path(temp),)), patch("main.rag_agent.ai.chat_with_context", new_callable=AsyncMock, return_value="Grounded answer") as model:
                response = self.client.post("/api/rag", json={"query": "retrieval", "sources": ["local"]})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["answer"], "Grounded answer")
        self.assertEqual(response.json()["sources_used"], ["local"])
        self.assertIn("[Source: notes.md#L1-L1]", model.await_args.args[1])
        self.assertNotIn("synthetic-secret-marker", model.await_args.args[1])

    def test_retrieval_still_requires_local_authentication(self):
        from fastapi.testclient import TestClient
        from main import app
        with patch("main.rag_agent.query", new_callable=AsyncMock) as query:
            response = TestClient(app).post("/api/rag", json={"query": "retrieval"})
        self.assertEqual(response.status_code, 401)
        query.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
