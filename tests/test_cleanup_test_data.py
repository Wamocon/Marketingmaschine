import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cleanup_test_data import cleanup


class CleanupTestDataTests(unittest.TestCase):
    def test_cleanup_removes_only_prefixed_test_state_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for child in ("states", "events", "performance", "leads", "outbox"):
                (root / child).mkdir()
            (root / "states" / "mock-old.json").write_text("{}", encoding="utf-8")
            (root / "states" / "smoke-old.json").write_text("{}", encoding="utf-8")
            (root / "states" / "k1-real-campaign.json").write_text("{}", encoding="utf-8")

            result = cleanup(root, ("mock-", "smoke-"), apply=False)

            self.assertEqual(result["removed_state_files"], 2)
            self.assertTrue((root / "states" / "mock-old.json").exists())
            self.assertTrue((root / "states" / "smoke-old.json").exists())
            self.assertTrue((root / "states" / "k1-real-campaign.json").exists())

    def test_cleanup_rewrites_jsonl_records_with_test_content_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for child in ("states", "events", "performance", "leads", "outbox"):
                (root / child).mkdir()
            records = [
                {"record": {"content_id": "mock-old"}, "action": "stop"},
                {"record": {"content_id": "k1-real"}, "action": "scale"},
            ]
            path = root / "performance" / "records.jsonl"
            path.write_text("\n".join(json.dumps(item) for item in records) + "\n", encoding="utf-8")

            with self.assertRaises(RuntimeError):
                cleanup(root, ("mock-",), apply=True)

            remaining = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(remaining), 2)

    def test_cleanup_rewrites_jsonl_leads_with_test_content_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for child in ("states", "events", "performance", "leads", "outbox"):
                (root / child).mkdir()
            records = [
                {"lead": {"id": "mock-lead", "source_content_id": "mock-content"}},
                {"lead": {"id": "real-lead", "source_content_id": "k1-real"}},
            ]
            path = root / "leads" / "records.jsonl"
            path.write_text("\n".join(json.dumps(item) for item in records) + "\n", encoding="utf-8")

            with self.assertRaises(RuntimeError):
                cleanup(root, ("mock-",), apply=True)

            remaining = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(remaining), 2)

    def test_cleanup_rewrites_jsonl_outbox_with_test_source_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for child in ("states", "events", "performance", "leads", "outbox"):
                (root / child).mkdir()
            records = [
                {"id": "route-1", "source_id": "mock-approved"},
                {"id": "route-2", "source_id": "k1-real"},
            ]
            path = root / "outbox" / "records.jsonl"
            path.write_text("\n".join(json.dumps(item) for item in records) + "\n", encoding="utf-8")

            with self.assertRaises(RuntimeError):
                cleanup(root, ("mock-",), apply=True)

            remaining = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(len(remaining), 2)

    def test_apply_mode_is_always_refused_before_any_file_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for child in ("states", "events", "performance", "leads", "outbox"):
                (root / child).mkdir()
            marker = root / "states" / "mock-never-delete-live.json"
            marker.write_text("{}", encoding="utf-8")

            with self.assertRaises(RuntimeError):
                cleanup(root, ("mock-",), apply=True)

            self.assertTrue(marker.exists())


if __name__ == "__main__":
    unittest.main()
