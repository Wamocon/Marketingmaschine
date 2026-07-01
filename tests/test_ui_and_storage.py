import sys
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marketing_machine.storage import JsonStore
from marketing_machine.ui import render_marketing_console


class UiAndStorageTests(unittest.TestCase):
    def test_marketing_console_contains_end_user_forms(self):
        html = render_marketing_console()

        self.assertIn("WAMOCON Marketing Console", html)
        self.assertIn("Manual Content Intake", html)
        self.assertIn("Human Approval", html)
        self.assertIn("Lead Intake", html)
        self.assertIn("Routing Outbox", html)
        self.assertIn("Optimization Review", html)
        self.assertIn("Phase Readiness", html)
        self.assertIn("/workflows/create-content", html)
        self.assertIn("/workflows/approve-content", html)
        self.assertIn("/workflows/phase-status", html)
        self.assertIn("/workflows/lead-intake", html)
        self.assertIn("/workflows/leads", html)
        self.assertIn("/workflows/route-scheduler-draft", html)
        self.assertIn("/workflows/route-lead", html)
        self.assertIn("/workflows/outbox", html)
        self.assertIn("/workflows/analytics-review", html)
        self.assertIn("Created Post Preview", html)
        self.assertIn("Scheduler Draft Preview", html)
        self.assertIn("CRM/Mautic payloads", html)
        self.assertIn("Deutsch (Deutschland)", html)
        self.assertIn("AI draft language", html)
        self.assertIn("content_id", html)

    def test_marketing_console_script_is_parseable_when_node_is_available(self):
        if not shutil.which("node"):
            self.skipTest("node is not available")

        html = render_marketing_console()
        script_match = re.search(r"<script>(.*?)</script>", html, re.S)
        self.assertIsNotNone(script_match)
        script = script_match.group(1)

        result = subprocess.run(
            ["node", "--check"],
            input=script,
            text=True,
            capture_output=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_store_lists_recent_states_without_full_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonStore(Path(tmp))
            store.save_state(
                {
                    "brief": {
                        "id": "content-1",
                        "campaign": "K1 QA",
                        "persona": "IT-Leiter Thomas",
                        "channel": "LinkedIn",
                        "status": "needs_human_review",
                        "updated_at": "2026-06-30T00:00:00+00:00",
                    },
                    "next_step": "human_review",
                    "requires_human_review": True,
                    "scheduler_payload": {},
                }
            )

            items = store.list_states(limit=10)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["content_id"], "content-1")
        self.assertEqual(items[0]["campaign"], "K1 QA")
        self.assertEqual(items[0]["next_step"], "human_review")
        self.assertTrue(items[0]["requires_human_review"])
        self.assertFalse(items[0]["has_scheduler_payload"])

    def test_cleanup_test_data_keeps_real_campaign_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonStore(Path(tmp))
            for content_id in ("mock-old-1", "smoke-old-1", "k1-real-campaign"):
                store.save_state(
                    {
                        "brief": {
                            "id": content_id,
                            "campaign": "Mock" if content_id.startswith(("mock-", "smoke-")) else "K1 QA",
                            "persona": "IT-Leiter Thomas",
                            "channel": "LinkedIn",
                            "status": "ready_to_schedule",
                            "updated_at": "2026-06-30T00:00:00+00:00",
                        },
                        "next_step": "scheduler",
                        "requires_human_review": False,
                        "scheduler_payload": {},
                    }
                )
            store.append_event("approval", {"content_id": "mock-old-1", "result": "delete"})
            store.append_event("approval", {"content_id": "k1-real-campaign", "result": "keep"})
            store.append_performance({"record": {"content_id": "smoke-old-1"}, "action": "stop"})
            store.append_performance({"record": {"content_id": "k1-real-campaign"}, "action": "scale"})
            store.append_lead({"lead": {"id": "mock-lead-1", "source_content_id": "mock-old-1"}})
            store.append_lead({"lead": {"id": "real-lead-1", "source_content_id": "k1-real-campaign"}})
            store.append_outbox({"id": "route-mock", "source_id": "mock-old-1", "target": "postiz"})
            store.append_outbox({"id": "route-real", "source_id": "k1-real-campaign", "target": "postiz"})

            dry_run = store.cleanup_test_data(dry_run=True)
            summary = store.cleanup_test_data()
            items = store.list_states(limit=10)
            leads = store.list_leads(limit=10)
            outbox = store.list_outbox(limit=10)

            self.assertEqual(dry_run["states_deleted"], 2)
            self.assertEqual(summary["states_deleted"], 2)
            self.assertEqual(summary["events_removed"], 1)
            self.assertEqual(summary["performance_removed"], 1)
            self.assertEqual(summary["leads_removed"], 1)
            self.assertEqual(summary["outbox_removed"], 1)
            self.assertEqual([item["content_id"] for item in items], ["k1-real-campaign"])
            self.assertEqual([item["id"] for item in leads], ["real-lead-1"])
            self.assertEqual([item["id"] for item in outbox], ["route-real"])
            self.assertIn("k1-real-campaign", (Path(tmp) / "events" / "approval.jsonl").read_text(encoding="utf-8"))
            self.assertNotIn("mock-old-1", (Path(tmp) / "events" / "approval.jsonl").read_text(encoding="utf-8"))

    def test_store_lists_recent_performance_decisions(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonStore(Path(tmp))
            store.append_performance(
                {
                    "record": {
                        "content_id": "content-1",
                        "review_window": "72h",
                        "qualified_leads": 0,
                        "booked_calls": 0,
                        "pipeline_value_eur": 0.0,
                        "created_at": "2026-07-01T00:00:00+00:00",
                    },
                    "action": "iterate",
                    "reason": "weak early signal",
                }
            )

            items = store.list_performance(limit=5)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["content_id"], "content-1")
        self.assertEqual(items[0]["review_window"], "72h")
        self.assertEqual(items[0]["action"], "iterate")
        self.assertEqual(items[0]["reason"], "weak early signal")


if __name__ == "__main__":
    unittest.main()
