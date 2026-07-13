import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marketing_machine.remediation import remediate_invalid_trend_draft
from marketing_machine.schemas import ContentBrief, ContentStatus
from marketing_machine.storage import JsonStore


class TrendRemediationTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
        self.content_id = "reel-concept-216ea34bb0f7-v1"
        self.run_id = "trend-request-21625ed90770e293"
        self.trend_id = "kampagne_1_consulting_qa-e0efdd939a"

    def test_invalid_trend_draft_is_archived_then_blocked_without_overwriting_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonStore(Path(tmp))
            original_state = self._state()
            store.save_state(original_state)
            store.save_trend_run(self._trend_run())

            dry_run = remediate_invalid_trend_draft(store, self.content_id, now=self.now)
            self.assertEqual(dry_run["status"], "would_block")
            self.assertEqual(store.load_state(self.content_id), original_state)
            self.assertFalse((store.root / "archive").exists())

            result = remediate_invalid_trend_draft(
                store,
                self.content_id,
                apply=True,
                operator="QA Audit",
                now=self.now,
            )

            self.assertEqual(result["status"], "blocked")
            archive = store.root / result["archive"]
            self.assertTrue((archive / "state.json").exists())
            self.assertTrue((archive / "trend-run.json").exists())
            self.assertTrue((archive / "manifest.json").exists())
            archived_state = json.loads((archive / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(archived_state, original_state)

            active = store.load_state(self.content_id)
            self.assertEqual(active["brief"]["status"], "blocked")
            self.assertEqual(active["brief"]["trend_verification_status"], "source_verification_failed")
            self.assertIn("exact_topic_corroboration_failed", active["brief"]["risk_flags"])
            self.assertEqual(active["next_step"], "research")
            self.assertFalse(active["requires_human_review"])
            self.assertTrue(active["errors"])
            self.assertEqual(len(active["remediation_history"]), 1)

            retry = remediate_invalid_trend_draft(
                store,
                self.content_id,
                apply=True,
                operator="QA Audit",
                now=self.now + timedelta(minutes=1),
            )
            self.assertTrue(retry["idempotent"])
            self.assertEqual(len(store.load_state(self.content_id)["remediation_history"]), 1)

    def _state(self):
        brief = ContentBrief(
            id=self.content_id,
            campaign="Consulting Test- und Qualitätsmanagement",
            persona="IT-Leiter und B2B-Entscheider",
            channel="Instagram",
            format="reel",
            objective="Quellenverifiziertes Reel",
            cta="QA-Risikoaudit anfragen",
            proof_sources=["Kampagnen/kampagne_1_consulting_qa.json"],
            utm={
                "utm_source": "instagram",
                "utm_medium": "organic_reel",
                "utm_campaign": "qa",
            },
            hypothesis="Quellenverifiziertes Reel wird geprüft.",
            test_variable="trend_reel_format",
            campaign_id="k1",
            campaign_context={"trend_campaign_id": "kampagne_1_consulting_qa"},
            status=ContentStatus.NEEDS_HUMAN_REVIEW,
            trend_run_id=self.run_id,
            trend_id=self.trend_id,
            trend_summary="Testautomatisierung 2026: 6 goldene Regeln + STQB-Definition",
            trend_sources=[
                "https://www.qytera.de/blog/testautomatisierung-tipps-goldene-regeln",
                "https://aqua-cloud.io/de/claude-code-testautomatisierung-wirklich-funktioniert/",
            ],
            trend_verification_status="verified_recent",
            citations=self._citations(),
        )
        return {
            "brief": brief.to_dict(),
            "approval": None,
            "errors": [],
            "next_step": "human_review",
            "requires_human_review": True,
            "evidence_records": [],
            "scheduler_payload": {},
        }

    def _trend_run(self):
        return {
            "id": self.run_id,
            "status": "verified_sources",
            "campaigns": [
                {
                    "campaign": {
                        "id": "kampagne_1_consulting_qa",
                        "name": "Consulting Test- und Qualitätsmanagement",
                    },
                    "trends": [
                        {
                            "id": self.trend_id,
                            "topic": "Testautomatisierung 2026: 6 goldene Regeln + STQB-Definition",
                            "trend_type": "current_trend",
                            "source_urls": [item["url"] for item in self._citations()],
                            "citations": self._citations(),
                            "verification": {
                                "status": "verified_recent",
                                "verified": True,
                                "independent_source_count": 2,
                                "recent_source_count": 1,
                                "lookback_start": (self.now - timedelta(days=10)).isoformat(),
                                "last_checked_at": self.now.isoformat(),
                            },
                        }
                    ],
                }
            ],
        }

    def _citations(self):
        return [
            {
                "url": "https://www.qytera.de/blog/testautomatisierung-tipps-goldene-regeln",
                "title": "Testautomatisierung 2026: 6 goldene Regeln + STQB-Definition",
                "domain": "qytera.de",
                "published": "",
                "retrieved": self.now.isoformat(),
                "snippet": "Sechs goldene Regeln, ISTQB-Definition und wirtschaftliche Einordnung.",
            },
            {
                "url": "https://aqua-cloud.io/de/claude-code-testautomatisierung-wirklich-funktioniert/",
                "title": "Claude Code Testautomatisierung: Kompletter Guide 2026",
                "domain": "aqua-cloud.io",
                "published": (self.now - timedelta(days=1)).isoformat(),
                "retrieved": self.now.isoformat(),
                "snippet": "KI-gestützte Codierung und systematisches Test-Management.",
            },
        ]


if __name__ == "__main__":
    unittest.main()
