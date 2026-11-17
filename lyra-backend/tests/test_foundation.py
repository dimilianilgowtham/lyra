"""
Tests for LYRA Foundation: Configuration, Secrets, and Invariants.
"""

import os
import sys
import unittest
from pathlib import Path

# Add backend directory to sys.path
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from config import settings, _get_secret


class TestFoundation(unittest.TestCase):
    def test_settings_structure(self):
        """Verify settings object initializes with required fields."""
        self.assertIsNotNone(settings.PORT)
        self.assertEqual(settings.PORT, 8100)
        self.assertIsNotNone(settings.DB_PATH)
        self.assertTrue(settings.DB_PATH.endswith("lyra.db"))
        self.assertEqual(settings.OLLAMA_BASE_URL, "http://localhost:11434")

    def test_get_secret_priority(self):
        """Verify _get_secret checks primary server-side var before fallback."""
        os.environ["TEST_PRIMARY_KEY"] = "primary_value"
        os.environ["VITE_TEST_PRIMARY_KEY"] = "legacy_value"

        val = _get_secret("TEST_PRIMARY_KEY")
        self.assertEqual(val, "primary_value")

        del os.environ["TEST_PRIMARY_KEY"]
        val_fallback = _get_secret("TEST_PRIMARY_KEY")
        self.assertEqual(val_fallback, "legacy_value")

        del os.environ["VITE_TEST_PRIMARY_KEY"]

    def test_env_example_has_no_live_keys(self):
        """Verify .env.example contains no real API key patterns."""
        example_path = BACKEND_DIR.parent / ".env.example"
        self.assertTrue(example_path.exists())
        content = example_path.read_text()

        # Ensure no live key prefixes exist in example file
        self.assertNotIn("gsk_8M", content)
        self.assertNotIn("sk-proj-", content)
        self.assertNotIn("AIzaSy", content)


    def test_frontier_adapters_and_resolution(self):
        """Verify Anthropic and OpenRouter adapters and model resolution."""
        from core.model_adapter import model_registry, AnthropicAdapter, OpenRouterAdapter

        self.assertIn("anthropic", model_registry.adapters)
        self.assertIn("openrouter", model_registry.adapters)
        self.assertIsInstance(model_registry.adapters["anthropic"], AnthropicAdapter)
        self.assertIsInstance(model_registry.adapters["openrouter"], OpenRouterAdapter)

        # OpenRouter should resolve for claude and deepseek when openrouter key is present
        adapter_claude = model_registry.resolve_adapter(model="anthropic/claude-3.7-sonnet")
        self.assertTrue(adapter_claude.is_available())

        adapter_deepseek = model_registry.resolve_adapter(model="deepseek/deepseek-r1")
        self.assertTrue(adapter_deepseek.is_available())

    def test_claude_code_tool_and_schemas(self):
        """Verify run_claude_code tool and universal schema export."""
        from core.tool_registry import build_default_registry

        registry = build_default_registry()
        tool = registry.get("run_claude_code")
        self.assertIsNotNone(tool)
        self.assertTrue(tool.requires_approval)

        # Check schema generation
        gemini_schema = tool.to_gemini_schema()
        self.assertEqual(gemini_schema["name"], "run_claude_code")

        openai_schema = tool.to_openai_schema()
        self.assertEqual(openai_schema["type"], "function")
        self.assertEqual(openai_schema["function"]["name"], "run_claude_code")

        anthropic_schema = tool.to_anthropic_schema()
        self.assertEqual(anthropic_schema["name"], "run_claude_code")
        self.assertIn("input_schema", anthropic_schema)


if __name__ == "__main__":
    unittest.main()
