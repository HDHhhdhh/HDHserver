"""Synthetic export/privacy checks; never reads the real session or any key."""
import json
from pathlib import Path
import tempfile
import unittest

from scripts.export_codex_session_dialogue import export, redact


class ExportChecks(unittest.TestCase):
    def test_visible_dialogue_only_and_no_source_write(self):
        with tempfile.TemporaryDirectory(prefix="dialogue-export-") as temporary:
            root = Path(temporary)
            source = root / "fixture.jsonl"
            events = [{"type": "session_meta", "payload": {"id": "fixture-thread"}}]
            for role, channel, text in (
                ("system", None, "private-system"), ("developer", None, "private-developer"),
                ("user", None, "# AGENTS.md instructions for fixture"),
                ("user", None, "export my dialogue"), ("assistant", "analysis", "private-reasoning"),
                ("assistant", "commentary", "working"), ("assistant", "final", "finished"),
            ):
                events.append({"timestamp": "2026-10-30T00:00:00Z", "type": "response_item",
                               "payload": {"type": "message", "role": role, "channel": channel,
                                           "content": [{"type": "input_text", "text": text}]}})
            events.append({"type": "response_item", "payload": {"type": "function_call", "arguments": "private-tool"}})
            source.write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
            before = source.read_bytes()
            result = export(source, root / "out", "fixture-thread")
            rows = [json.loads(line) for line in (root / "out/dialogue.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual([r["text"] for r in rows], ["export my dialogue", "working", "finished"])
            self.assertEqual(result["messageCount"], 3)
            self.assertEqual(source.read_bytes(), before)
            with self.assertRaises(ValueError):
                export(source, root / "out", "fixture-thread")
            with self.assertRaises(ValueError):
                export(source, root / "wrong", "different-thread")
            self.assertFalse((root / "wrong").exists())

    def test_secrets_redacted_without_changing_ordinary_text(self):
        fake = "sk-" + "notarealsecret" * 3
        text, count = redact("OPENAI_API_KEY=" + fake + "\nordinary OCR discussion")
        self.assertNotIn(fake, text)
        self.assertIn("ordinary OCR discussion", text)
        self.assertEqual(count, 1)
        text, count = redact("Authorization: Bearer " + "synthetic" * 5)
        self.assertEqual(count, 1)
        self.assertIn("Bearer [REDACTED_SECRET]", text)


if __name__ == "__main__":
    unittest.main()
