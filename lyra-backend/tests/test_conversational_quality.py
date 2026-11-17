"""
Conversational Quality & Safety Test Suite for LYRA:
- Multi-turn continuity
- Memory consent & privacy enforcement
- Epistemic grounding & honesty rules
- Safe agent impact analysis & audit trail
- Voice interruption protocol
"""

import sys
import tempfile
import unittest
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from core.database import DatabaseManager
from core.personality_engine import PersonalityEngine
from core.agent_executor import assess_tool_impact
from core.document_memory import DocumentMemory, DocumentChunk


class TestConversationalQuality(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db = DatabaseManager(str(Path(self.temp_dir.name) / "eval.db"))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_continuity_multi_turn_flow(self):
        """Continuity Test: ensure conversation preserves context across multiple turns."""
        user = self.db.get_or_create_user("eval_user_1", name="Sarah")
        conv = self.db.get_or_create_conversation(None, user_id=user["id"], title="Project Plan")
        cid = conv["id"]

        turns = [
            ("user", "We are building an autonomous drone project called SkyNet."),
            ("assistant", "Noted, Sarah. I will remember the SkyNet autonomous drone project."),
            ("user", "We decided to use Rust for the flight controller."),
            ("assistant", "Rust is a solid choice for zero-cost abstractions and memory safety in avionics."),
            ("user", "What language did we pick for SkyNet?"),
        ]

        for role, text in turns:
            self.db.add_message(cid, user["id"], role, text)

        history = self.db.get_messages(cid)
        self.assertEqual(len(history), 5)
        # Verify 3 turns ago statement is present
        self.assertIn("SkyNet", history[0]["content"])
        self.assertIn("Rust", history[2]["content"])

    def test_memory_consent_and_privacy(self):
        """Memory Consent Test: verified consent toggle and complete forgetting."""
        uid = "consent_user"
        self.db.get_or_create_user(uid)

        mem = self.db.add_memory(uid, "User is allergic to peanuts", category="health", consented=True)
        active = self.db.get_active_memories(uid)
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["fact"], "User is allergic to peanuts")

        # Revoke consent
        self.db.update_memory(mem["id"], consented=False)
        active_after_revoke = self.db.get_active_memories(uid)
        self.assertEqual(len(active_after_revoke), 0)

        # Delete / forget permanently
        self.db.delete_memory(mem["id"])
        all_mems = self.db.list_all_memories(uid)
        self.assertEqual(len(all_mems), 0)

    def test_epistemic_grounding_and_personality(self):
        """Tone & Grounding Test: ensure system prompts strictly prohibit hallucinating OS actions."""
        prompt = PersonalityEngine.get_system_prompt()
        self.assertIn("LYRA", prompt)
        # Grounding directive test
        from core.ai_orchestrator import AIOrchestrator
        orchestrator = AIOrchestrator()
        augmented = orchestrator._build_augmented_system_prompt("test_user", is_voice=True)
        self.assertIn("EPISTEMIC GROUNDING", augmented)
        self.assertIn("Never hallucinate or claim you performed an OS action", augmented)
        self.assertIn("VOICE MODE ACTIVE", augmented)

    def test_tool_safety_and_impact_assessment(self):
        """Tool Safety Test: dangerous shell commands must be HIGH risk, reads must be LOW risk."""
        # Destructive shell command
        impact_rm = assess_tool_impact("execute_command", {"command": "rm -rf /tmp/test"})
        self.assertEqual(impact_rm["risk_tier"], "HIGH")
        self.assertTrue(impact_rm["requires_approval"])

        # Non-destructive shell command
        impact_ls = assess_tool_impact("execute_command", {"command": "ls -la"})
        self.assertEqual(impact_ls["risk_tier"], "MEDIUM")
        self.assertTrue(impact_ls["requires_approval"])

        # File write
        impact_write = assess_tool_impact("write_file", {"filepath": "/Users/test/out.txt"})
        self.assertEqual(impact_write["risk_tier"], "MEDIUM")
        self.assertTrue(impact_write["requires_approval"])

        # Safe read-only tool
        impact_read = assess_tool_impact("read_file", {"filepath": "config.py"})
        self.assertEqual(impact_read["risk_tier"], "LOW")
        self.assertFalse(impact_read["requires_approval"])

    def test_document_memory_citations(self):
        """Grounded Knowledge Test: document chunks generate verifiable source citations."""
        chunk = DocumentChunk(
            file_path="src/modules/DesktopBridge.js",
            start_line=15,
            end_line=45,
            content="class DesktopBridgeClient { ... }",
        )
        self.assertEqual(chunk.citation, "[Source: src/modules/DesktopBridge.js#L15-L45]")


if __name__ == "__main__":
    unittest.main()
