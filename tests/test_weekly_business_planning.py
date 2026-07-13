import json
import os
import sys
import tempfile
import unittest
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi import HTTPException

from marketing_machine.api import default_briefs, weekly_planning
from marketing_machine.schemas import ContentBrief
from marketing_machine.storage import JsonStore


def verified_run(now: datetime, campaign_source_ids: list[str]) -> dict:
    campaign_results = []
    for source_id in campaign_source_ids:
        campaign_id = source_id.split("_")[1]
        topic = f"Software Testing Automation Signal {campaign_id}"
        urls = [
            f"https://newsroom-{campaign_id}.com/{campaign_id}-signal",
            f"https://industry-{campaign_id}.net/{campaign_id}-signal",
        ]
        campaign_results.append(
            {
                "campaign": {"id": source_id},
                "trends": [
                    {
                        "id": f"trend-{campaign_id}",
                        "topic": topic,
                        "source_urls": urls,
                        "citations": [
                            {
                                "title": topic,
                                "snippet": f"{topic} wird in dieser Quelle eingeordnet.",
                                "published": now.isoformat(),
                                "retrieved": now.isoformat(),
                                "url": url,
                            }
                            for url in urls
                        ],
                        "verification": {
                            "status": "verified_recent",
                            "verified": True,
                            "last_checked_at": now.isoformat(),
                        },
                    }
                ],
            }
        )
    return {
        "id": "trend-weekly-current",
        "run_started_at": now.isoformat(),
        "campaigns": campaign_results,
    }


class WeeklyBusinessPlanningTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]

    def test_default_weekly_briefs_include_only_active_campaigns(self):
        with patch("marketing_machine.api.repo_root", return_value=self.root):
            briefs = default_briefs(
                now=datetime(2026, 7, 13, 9, 0, tzinfo=timezone.utc)
            )

        self.assertEqual(Counter(brief.campaign_id for brief in briefs), {"k1": 3, "k2": 3, "k4": 3})
        self.assertEqual(len({brief.id for brief in briefs}), 9)
        self.assertTrue(all("-source-backed-" in brief.id for brief in briefs))
        self.assertFalse({"k3", "k5"} & {brief.campaign_id for brief in briefs})

    def test_default_weekly_briefs_use_business_timezone_for_iso_week(self):
        sunday_utc_monday_in_berlin = datetime(2026, 7, 12, 22, 30, tzinfo=timezone.utc)
        with patch.dict(
            os.environ,
            {"MARKETING_MACHINE_BUSINESS_TIMEZONE": "Europe/Berlin"},
        ), patch("marketing_machine.api.repo_root", return_value=self.root):
            briefs = default_briefs(now=sunday_utc_monday_in_berlin)

        self.assertEqual(len(briefs), 9)
        self.assertTrue(all("-2026w29-" in brief.id for brief in briefs))

    def test_weekly_planning_creates_all_nine_source_backed_slots_once(self):
        now = datetime(2026, 7, 13, 9, 0, tzinfo=timezone.utc)
        run = verified_run(
            now,
            [
                "kampagne_1_consulting_qa",
                "kampagne_2_ki_sokrates",
                "kampagne_4_mitarbeiter",
            ],
        )
        generated_briefs: list[ContentBrief] = []

        def generate(brief: ContentBrief) -> dict:
            generated_briefs.append(brief)
            payload = brief.to_dict()
            payload["status"] = "needs_human_review"
            payload["generation"] = {"status": "ai_generated", "fallback_used": False}
            return {
                "brief": payload,
                "next_step": "human_review",
                "requires_human_review": True,
            }

        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}
        ), patch("marketing_machine.api.business_now", return_value=now), patch(
            "marketing_machine.api.repo_root", return_value=self.root
        ), patch(
            "marketing_machine.api.full_trend_runs", return_value=[run]
        ), patch(
            "marketing_machine.api.create_state_for_brief", side_effect=generate
        ) as create:
            first = weekly_planning({})
            second = weekly_planning({})
            stored = JsonStore().list_states(limit=100)

        self.assertEqual(
            first["summary"],
            {
                "created_now": 9,
                "already_present": 0,
                "skipped_planned": 2,
                "ready_for_review": 9,
                "blocked_needs_regeneration": 0,
                "attention_required": 0,
                "progressed_beyond_review": 0,
            },
        )
        self.assertEqual(
            second["summary"],
            {
                "created_now": 0,
                "already_present": 9,
                "skipped_planned": 2,
                "ready_for_review": 9,
                "blocked_needs_regeneration": 0,
                "attention_required": 0,
                "progressed_beyond_review": 0,
            },
        )
        self.assertEqual(first["status"], "ready_for_human_review")
        self.assertTrue(first["human_approval_required"])
        self.assertEqual(len(first["ready_for_review"]), 9)
        self.assertEqual(first["blocked_needs_regeneration"], [])
        self.assertEqual(first["weekly_goal"]["effective_active_total"], 9)
        self.assertEqual(first["weekly_goal"]["active_campaigns"], 3)
        self.assertEqual(Counter(item["campaign_id"] for item in first["created"]), {"k1": 3, "k2": 3, "k4": 3})
        self.assertEqual({item["campaign_id"] for item in first["skipped_planned"]}, {"k3", "k5"})
        self.assertEqual(create.call_count, 9)
        self.assertEqual(len(stored), 9)
        self.assertEqual(len(generated_briefs), 9)
        self.assertTrue(all(brief.trend_run_id == run["id"] for brief in generated_briefs))
        self.assertTrue(all(brief.trend_id for brief in generated_briefs))
        self.assertTrue(all(len(brief.citations) == 2 for brief in generated_briefs))
        self.assertTrue(all(len(brief.trend_sources) == 2 for brief in generated_briefs))

    def test_weekly_planning_truthfully_reports_nine_blocked_generation_records(self):
        now = datetime(2026, 7, 13, 9, 0, tzinfo=timezone.utc)
        run = verified_run(
            now,
            [
                "kampagne_1_consulting_qa",
                "kampagne_2_ki_sokrates",
                "kampagne_4_mitarbeiter",
            ],
        )

        def blocked(brief: ContentBrief) -> dict:
            payload = brief.to_dict()
            payload["status"] = "blocked"
            payload["generation"] = {
                "status": "deterministic_fallback",
                "fallback_used": True,
                "provider": "internal-provider",
                "model": "internal-model",
            }
            return {
                "brief": payload,
                "errors": ["private generation diagnostic"],
                "next_step": "regenerate",
                "requires_human_review": False,
            }

        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}
        ), patch("marketing_machine.api.business_now", return_value=now), patch(
            "marketing_machine.api.repo_root", return_value=self.root
        ), patch(
            "marketing_machine.api.full_trend_runs", return_value=[run]
        ), patch(
            "marketing_machine.api.create_state_for_brief", side_effect=blocked
        ) as create:
            first = weekly_planning({})
            second = weekly_planning({})
            stored = JsonStore().list_states(limit=100)
            events = [
                json.loads(line)
                for line in (Path(tmp) / "events" / "weekly_planning.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ]

        self.assertEqual(first["status"], "blocked_needs_regeneration")
        self.assertFalse(first["human_approval_required"])
        self.assertEqual(first["ready_for_review"], [])
        self.assertEqual(len(first["blocked_needs_regeneration"]), 9)
        self.assertEqual(first["summary"]["created_now"], 9)
        self.assertEqual(first["summary"]["ready_for_review"], 0)
        self.assertEqual(first["summary"]["blocked_needs_regeneration"], 9)
        self.assertEqual(second["summary"]["created_now"], 0)
        self.assertEqual(second["summary"]["already_present"], 9)
        self.assertEqual(second["summary"]["blocked_needs_regeneration"], 9)
        self.assertEqual(create.call_count, 9)
        self.assertEqual(len(stored), 9)
        self.assertTrue(
            all(item["business_state"] == "blocked_needs_regeneration" for item in first["created"])
        )
        self.assertNotIn("review AI-generated drafts", first["next_steps"])
        self.assertEqual(events[0]["status"], "blocked_needs_regeneration")
        self.assertFalse(events[0]["human_approval_required"])
        self.assertEqual(len(events[0]["blocked_needs_regeneration"]), 9)

    def test_weekly_planning_separates_created_existing_and_planned(self):
        brief = ContentBrief(
            id="k1-2026w29-expert-post",
            campaign_id="k1",
            campaign="K1 QA",
            persona="IT-Leitung",
            channel="LinkedIn",
            format="expert_post",
            objective="QA-Risiken verstaendlich einordnen",
            cta="Audit anfragen",
            proof_sources=["Kampagnen/kampagne_1_consulting_qa.json"],
            utm={"utm_source": "linkedin", "utm_medium": "organic", "utm_campaign": "k1"},
            hypothesis="Qualifizierte Reaktionen",
            test_variable="hook",
        )
        campaigns = [
            {
                "id": "k1",
                "name": "K1 QA",
                "status": "active",
                "configured_weekly_target": 1,
                "effective_weekly_target": 1,
                "counts_toward_weekly_goal": True,
                "start_date": "2026-07-01",
            },
            {
                "id": "k3",
                "name": "K3 LFA",
                "status": "planned",
                "configured_weekly_target": 5,
                "effective_weekly_target": 0,
                "counts_toward_weekly_goal": False,
                "start_date": "2026-08-01",
            },
        ]
        generated = {
            "brief": {
                "id": brief.id,
                "campaign_id": "k1",
                "status": "needs_human_review",
                "generation": {"status": "ai_generated"},
            },
            "next_step": "human_review",
        }
        run = verified_run(
            datetime.now(timezone.utc),
            ["kampagne_1_consulting_qa"],
        )

        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}
        ), patch(
            "marketing_machine.api.load_campaign_catalog", return_value=campaigns
        ), patch(
            "marketing_machine.api.default_briefs", return_value=[brief]
        ), patch(
            "marketing_machine.api.full_trend_runs", return_value=[run]
        ), patch(
            "marketing_machine.api.create_state_for_brief", return_value=generated
        ):
            first = weekly_planning({})
            second = weekly_planning({})

        expected_first_summary = {
            "created_now": 1,
            "already_present": 0,
            "skipped_planned": 1,
            "ready_for_review": 1,
            "blocked_needs_regeneration": 0,
            "attention_required": 0,
            "progressed_beyond_review": 0,
        }
        expected_second_summary = {
            **expected_first_summary,
            "created_now": 0,
            "already_present": 1,
        }
        self.assertEqual(first["summary"], expected_first_summary)
        self.assertEqual(second["summary"], expected_second_summary)
        self.assertEqual(first["weekly_goal"], {"configured_total": 6, "effective_active_total": 1, "active_campaigns": 1})
        self.assertEqual(first["created"], first["created_now"])
        self.assertEqual(second["created"], second["already_present"])
        self.assertEqual(first["skipped_planned"][0]["campaign_id"], "k3")
        self.assertEqual(first["skipped_planned"][0]["effective_weekly_target"], 0)
        self.assertFalse(first["skipped_planned"][0]["counts_toward_weekly_goal"])

    def test_weekly_planning_fails_before_any_write_when_active_research_is_missing(self):
        campaigns = [
            {
                "id": "k1",
                "name": "K1 QA",
                "status": "active",
                "configured_weekly_target": 1,
                "effective_weekly_target": 1,
                "counts_toward_weekly_goal": True,
                "start_date": "2026-07-01",
            }
        ]
        brief = ContentBrief(
            id="k1-weekly-source-backed-01",
            campaign_id="k1",
            campaign="K1 QA",
            persona="IT-Leitung",
            channel="LinkedIn",
            format="expert_post",
            objective="QA-Risiken einordnen",
            cta="Audit anfragen",
            proof_sources=["Kampagnen/kampagne_1_consulting_qa.json"],
            utm={"utm_source": "linkedin", "utm_medium": "organic", "utm_campaign": "k1"},
            hypothesis="Qualifizierte Reaktionen",
            test_variable="weekly_editorial_angle_01",
            campaign_context={"weekly_slot": 1, "weekly_target": 1},
        )
        generate = Mock()

        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}
        ), patch(
            "marketing_machine.api.load_campaign_catalog", return_value=campaigns
        ), patch(
            "marketing_machine.api.default_briefs", return_value=[brief]
        ), patch(
            "marketing_machine.api.full_trend_runs", return_value=[]
        ), patch(
            "marketing_machine.api.create_state_for_brief", generate
        ):
            with self.assertRaises(HTTPException) as raised:
                weekly_planning({})
            stored = JsonStore().list_states(limit=100)

        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail["reason_code"], "current_verified_research_required")
        self.assertEqual(raised.exception.detail["missing_campaigns"][0]["campaign_id"], "k1")
        self.assertFalse(raised.exception.detail["writes_performed"])
        self.assertIn("keine Entwürfe angelegt", raised.exception.detail["message"])
        self.assertEqual(stored, [])
        generate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
