import sys
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marketing_machine.campaign_catalog import (
    business_now,
    campaign_dashboard,
    current_revision_heads,
    default_brief_payload,
    load_audience_catalog,
    load_campaign_catalog,
    resolve_campaign_id,
)


class CampaignCatalogTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]

    @staticmethod
    def _verified_trend(observed_at: datetime) -> dict:
        published = observed_at.isoformat()
        return {
            "topic": "Private KI Datenschutz im Mittelstand",
            "verification": {
                "status": "verified_recent",
                "verified": True,
                "last_checked_at": published,
                "evidence_count": 2,
            },
            "citations": [
                {
                    "title": "Private KI: Datenschutz im Mittelstand",
                    "snippet": "Private KI und Datenschutz fÃ¼r den Mittelstand.",
                    "url": "https://publisher-one.com/private-ki",
                    "published": published,
                },
                {
                    "title": "Mittelstand setzt auf Private KI und Datenschutz",
                    "snippet": "Datenschutz bleibt bei Private KI im Mittelstand zentral.",
                    "url": "https://publisher-two.net/private-ki",
                    "published": published,
                },
            ],
        }

    def test_catalog_contains_exactly_the_five_real_campaigns(self):
        campaigns = load_campaign_catalog(self.root, today=date(2026, 7, 10))

        self.assertEqual(
            [item["id"] for item in campaigns], ["k1", "k2", "k3", "k4", "k5"]
        )
        self.assertEqual(
            [item["status"] for item in campaigns],
            ["active", "active", "planned", "active", "planned"],
        )
        self.assertTrue(
            all(item["source_ref"].startswith("Kampagnen/") for item in campaigns)
        )

    def test_weekly_goal_counts_only_campaigns_active_on_2026_07_13(self):
        campaigns = load_campaign_catalog(self.root, today=date(2026, 7, 13))

        self.assertEqual(
            [item["id"] for item in campaigns if item["counts_toward_weekly_goal"]],
            ["k1", "k2", "k4"],
        )
        self.assertEqual(
            sum(item["configured_weekly_target"] for item in campaigns), 16
        )
        self.assertEqual(sum(item["effective_weekly_target"] for item in campaigns), 9)
        planned = [item for item in campaigns if item["status"] == "planned"]
        self.assertEqual([item["id"] for item in planned], ["k3", "k5"])
        self.assertTrue(all(item["effective_weekly_target"] == 0 for item in planned))
        self.assertTrue(
            all(item["counts_toward_weekly_goal"] is False for item in planned)
        )

    def test_business_week_and_campaign_date_follow_europe_berlin(self):
        utc_sunday = datetime(2026, 7, 12, 22, 30, tzinfo=timezone.utc)
        local_monday = business_now(utc_sunday)
        self.assertEqual(local_monday.isoformat(), "2026-07-13T00:30:00+02:00")

        dashboard = campaign_dashboard(
            self.root,
            [
                {
                    "content_id": "manual-local-monday",
                    "campaign_id": "k1",
                    "status": "needs_human_review",
                    "created_at": utc_sunday.isoformat(),
                }
            ],
            now=utc_sunday,
        )
        self.assertEqual(dashboard[0]["content"]["week"], "2026-W29")
        self.assertEqual(dashboard[0]["content"]["total"], 1)

        august_local = business_now(datetime(2026, 7, 31, 22, 30, tzinfo=timezone.utc))
        campaigns = load_campaign_catalog(self.root, today=august_local.date())
        self.assertEqual(
            next(item for item in campaigns if item["id"] == "k3")["status"], "active"
        )

    def test_invalid_business_timezone_fails_closed(self):
        with patch.dict(
            "os.environ",
            {"MARKETING_MACHINE_BUSINESS_TIMEZONE": "Not/A-Timezone"},
        ):
            with self.assertRaisesRegex(ValueError, "invalid business timezone"):
                business_now(datetime(2026, 7, 13, tzinfo=timezone.utc))

    def test_dashboard_preserves_configured_goal_but_uses_zero_effective_goal_for_planned(
        self,
    ):
        campaigns = campaign_dashboard(
            self.root,
            [],
            now=datetime(2026, 7, 13, tzinfo=timezone.utc),
        )

        k3 = next(item for item in campaigns if item["id"] == "k3")
        self.assertEqual(k3["content"]["configured_weekly_target"], 5)
        self.assertEqual(k3["content"]["effective_weekly_target"], 0)
        self.assertEqual(k3["content"]["weekly_target"], 0)
        self.assertEqual(k3["content"]["progress_percent"], 0)
        self.assertFalse(k3["content"]["counts_toward_weekly_goal"])

    def test_catalog_loads_all_five_real_audiences(self):
        audiences = load_audience_catalog(self.root)

        self.assertEqual(
            [item["id"] for item in audiences], ["z1", "z2", "z3", "z4", "z5"]
        )
        self.assertTrue(all(item.get("painPoints") for item in audiences))

    def test_all_campaigns_resolve_authored_audiences_to_privacy_safe_generation_profiles(
        self,
    ):
        campaigns = load_campaign_catalog(self.root, today=date(2026, 7, 10))
        expected_profile_ids = {
            "k1": ["z1", "z2", "z3", "z5"],
            "k2": ["z5", "z1", "z3"],
            "k3": ["z4", "z1", "z2"],
            "k4": ["z3", "z1", "z2", "z4"],
            "k5": ["z1", "z5"],
        }
        allowed_fields = {
            "profile_id",
            "role",
            "audience_type",
            "segment",
            "journey_phase",
            "pain_points",
            "goals",
            "decision_context",
        }

        self.assertEqual({item["id"] for item in campaigns}, set(expected_profile_ids))
        for campaign in campaigns:
            profiles = campaign["audience_profiles"]
            self.assertEqual(
                [item["profile_id"] for item in profiles],
                expected_profile_ids[campaign["id"]],
            )
            self.assertEqual(len(profiles), len(campaign["target_audience_refs"]))
            for profile in profiles:
                self.assertEqual(set(profile), allowed_fields)
                self.assertTrue(profile["role"])
                self.assertTrue(profile["pain_points"])
                self.assertTrue(profile["goals"])
                self.assertTrue(profile["journey_phase"])
                self.assertTrue(profile["decision_context"])

    def test_dashboard_uses_real_campaigns_and_derived_content_progress(self):
        states = [
            {
                "content_id": "k1-2026w28-post-a",
                "campaign_id": "k1",
                "campaign": "K1 QA",
                "status": "needs_human_review",
            },
            {
                "content_id": "k1-2026w28-post-b",
                "campaign_id": "k1",
                "campaign": "K1 QA",
                "status": "ready_to_schedule",
            },
            {
                "content_id": "k2-2026w28-post-a",
                "campaign_id": "k2",
                "campaign": "K2 Sokrates",
                "status": "blocked",
            },
        ]
        campaigns = campaign_dashboard(
            self.root,
            states,
            now=datetime(2026, 7, 10, tzinfo=timezone.utc),
        )

        k1 = campaigns[0]
        self.assertEqual(k1["content"]["total"], 2)
        self.assertEqual(k1["content"]["in_review"], 1)
        self.assertEqual(k1["content"]["approved"], 1)
        self.assertEqual(k1["next_action"]["kind"], "research")

    def test_dashboard_weekly_progress_excludes_prior_iso_weeks(self):
        states = [
            {
                "content_id": "k1-2026w27-old",
                "campaign_id": "k1",
                "status": "ready_to_schedule",
            },
            {
                "content_id": "manual-current",
                "campaign_id": "k1",
                "status": "needs_human_review",
                "updated_at": "2026-07-10T09:00:00+00:00",
            },
            {
                "content_id": "legacy-undated",
                "campaign_id": "k1",
                "status": "ready_to_schedule",
            },
        ]

        k1 = campaign_dashboard(
            self.root,
            states,
            now=datetime(2026, 7, 10, tzinfo=timezone.utc),
        )[0]

        self.assertEqual(k1["content"]["week"], "2026-W28")
        self.assertEqual(k1["content"]["total"], 1)
        self.assertEqual(k1["content"]["all_time_total"], 3)
        self.assertEqual(k1["content"]["approved"], 0)
        self.assertEqual(k1["content"]["in_review"], 1)

    def test_dashboard_counts_only_current_heads_across_all_five_campaigns(self):
        states = []
        expected_heads = set()
        for campaign_id in ("k1", "k2", "k3", "k4", "k5"):
            original_id = f"{campaign_id}-2026w29-content"
            revision_one_id = f"{original_id}-r1"
            revision_two_id = f"{revision_one_id}-r1"
            states.extend(
                [
                    {
                        "content_id": original_id,
                        "campaign_id": campaign_id,
                        "status": "ready_to_schedule",
                        "state_revision": 1,
                        "revision_source": {},
                    },
                    {
                        "content_id": revision_one_id,
                        "campaign_id": campaign_id,
                        "status": "blocked",
                        "state_revision": 1,
                        "revision_source": {"content_id": original_id, "revision": 1},
                    },
                    {
                        "content_id": revision_two_id,
                        "campaign_id": campaign_id,
                        "status": "needs_human_review"
                        if campaign_id == "k2"
                        else "ready_to_schedule",
                        "state_revision": 1,
                        "revision_source": {
                            "content_id": revision_one_id,
                            "revision": 1,
                        },
                    },
                ]
            )
            expected_heads.add(revision_two_id)
        states.append(
            {
                "content_id": "k1-2026w29-standalone-blocked",
                "campaign_id": "k1",
                "status": "blocked",
                "state_revision": 1,
                "revision_source": {},
            }
        )
        expected_heads.add("k1-2026w29-standalone-blocked")
        original_history = [dict(item) for item in states]
        trend_runs = [
            {
                "id": "all-campaigns-current-research",
                "run_started_at": "2026-07-13T08:00:00+00:00",
                "campaigns": [
                    {
                        "campaign": {"id": source_id},
                        "trends": [
                            self._verified_trend(
                                datetime(2026, 7, 13, 8, 0, tzinfo=timezone.utc)
                            )
                        ],
                    }
                    for source_id in (
                        "kampagne_1_consulting_qa",
                        "kampagne_2_ki_sokrates",
                        "kampagne_3_lfa_azubis",
                        "kampagne_4_mitarbeiter",
                        "kampagne_5_app_entwicklung",
                    )
                ],
            }
        ]

        heads = current_revision_heads(states)
        campaigns = campaign_dashboard(
            self.root,
            states,
            trend_runs=trend_runs,
            now=datetime(2026, 7, 13, 10, 0, tzinfo=timezone.utc),
        )
        by_id = {campaign["id"]: campaign for campaign in campaigns}

        self.assertEqual({item["content_id"] for item in heads}, expected_heads)
        self.assertEqual(states, original_history)
        self.assertEqual(by_id["k1"]["content"]["total"], 2)
        self.assertEqual(by_id["k1"]["content"]["all_time_total"], 2)
        self.assertEqual(by_id["k1"]["content"]["approved"], 1)
        self.assertEqual(by_id["k1"]["content"]["blocked"], 1)
        self.assertEqual(by_id["k1"]["next_action"]["kind"], "blocked")
        self.assertEqual(by_id["k2"]["content"]["total"], 1)
        self.assertEqual(by_id["k2"]["content"]["approved"], 0)
        self.assertEqual(by_id["k2"]["content"]["blocked"], 0)
        self.assertEqual(by_id["k2"]["content"]["in_review"], 1)
        self.assertEqual(by_id["k2"]["content"]["progress_percent"], 0)
        self.assertEqual(by_id["k2"]["next_action"]["kind"], "review")
        self.assertEqual(by_id["k4"]["content"]["approved"], 1)
        self.assertEqual(by_id["k4"]["content"]["blocked"], 0)
        self.assertEqual(by_id["k4"]["content"]["progress_percent"], 33)
        self.assertEqual(by_id["k4"]["next_action"]["kind"], "create")
        self.assertEqual(by_id["k3"]["content"]["total"], 1)
        self.assertEqual(by_id["k3"]["next_action"]["kind"], "prepare")
        self.assertEqual(by_id["k5"]["content"]["total"], 1)
        self.assertEqual(by_id["k5"]["next_action"]["kind"], "prepare")

    def test_revision_head_projection_fails_open_for_untrusted_relationships(self):
        states = [
            {
                "content_id": "cycle-a",
                "campaign_id": "k1",
                "revision_source": {"content_id": "cycle-b", "revision": 1},
            },
            {
                "content_id": "cycle-b",
                "campaign_id": "k1",
                "revision_source": {"content_id": "cycle-a", "revision": 1},
            },
            {
                "content_id": "cross-campaign-source",
                "campaign_id": "k1",
                "revision_source": {},
            },
            {
                "content_id": "cross-campaign-child",
                "campaign_id": "k2",
                "revision_source": {
                    "content_id": "cross-campaign-source",
                    "revision": 1,
                },
            },
            {
                "content_id": "malformed-source",
                "campaign_id": "k1",
                "revision_source": {},
            },
            {
                "content_id": "malformed-child",
                "campaign_id": "k1",
                "revision_source": {"content_id": "malformed-source", "revision": True},
            },
            {
                "content_id": "standalone-blocked",
                "campaign_id": "k1",
                "status": "blocked",
            },
            {
                "content_id": "zero-revision-source",
                "campaign_id": "k1",
                "state_revision": 1,
            },
            {
                "content_id": "zero-revision-child",
                "campaign_id": "k1",
                "state_revision": 1,
                "revision_source": {
                    "content_id": "zero-revision-source",
                    "revision": 0,
                },
            },
            {
                "content_id": "wrong-revision-source",
                "campaign_id": "k1",
                "state_revision": 2,
            },
            {
                "content_id": "wrong-revision-child",
                "campaign_id": "k1",
                "state_revision": 1,
                "revision_source": {
                    "content_id": "wrong-revision-source",
                    "revision": 999,
                },
            },
            {
                "content_id": "missing-campaign-source",
                "state_revision": 1,
            },
            {
                "content_id": "missing-campaign-child",
                "campaign_id": "k1",
                "state_revision": 1,
                "revision_source": {
                    "content_id": "missing-campaign-source",
                    "revision": 1,
                },
            },
        ]

        heads = current_revision_heads(states)

        self.assertEqual(
            [item["content_id"] for item in heads],
            [
                "cycle-a",
                "cycle-b",
                "cross-campaign-source",
                "cross-campaign-child",
                "malformed-source",
                "malformed-child",
                "standalone-blocked",
                "zero-revision-source",
                "zero-revision-child",
                "wrong-revision-source",
                "wrong-revision-child",
                "missing-campaign-source",
                "missing-campaign-child",
            ],
        )

    def test_research_status_is_derived_per_campaign_not_from_global_run(self):
        trend_runs = [
            {
                "id": "trend-one",
                "status": "verified_sources",
                "run_started_at": "2026-07-10T08:00:00+00:00",
                "campaigns": [
                    {
                        "campaign": {"id": "kampagne_1_consulting_qa"},
                        "trends": [
                            {
                                "verification": {
                                    "status": "single_source_review",
                                    "verified": False,
                                }
                            },
                        ],
                    },
                    {
                        "campaign": {"id": "kampagne_2_ki_sokrates"},
                        "trends": [
                            self._verified_trend(
                                datetime(2026, 7, 10, tzinfo=timezone.utc)
                            ),
                        ],
                    },
                ],
            }
        ]

        campaigns = campaign_dashboard(
            self.root,
            [],
            trend_runs=trend_runs,
            now=datetime(2026, 7, 10, tzinfo=timezone.utc),
        )

        self.assertEqual(
            campaigns[0]["research"]["status"], "needs_source_verification"
        )
        self.assertEqual(campaigns[0]["research"]["verified_trend_count"], 0)
        self.assertEqual(campaigns[1]["research"]["status"], "verified_recent")
        self.assertEqual(campaigns[1]["research"]["verified_trend_count"], 1)
        self.assertEqual(campaigns[1]["research"]["freshness_days"], 7)

    def test_dashboard_expires_stored_verification_against_current_seven_day_window(
        self,
    ):
        stored_trend = self._verified_trend(
            datetime(2026, 7, 1, 8, 0, tzinfo=timezone.utc)
        )
        trend_runs = [
            {
                "id": "trend-expired",
                "status": "verified_sources",
                "run_started_at": "2026-07-01T08:00:00+00:00",
                "campaigns": [
                    {
                        "campaign": {"id": "kampagne_2_ki_sokrates"},
                        "trends": [stored_trend],
                    }
                ],
            }
        ]

        campaign = campaign_dashboard(
            self.root,
            [],
            trend_runs=trend_runs,
            now=datetime(2026, 7, 10, tzinfo=timezone.utc),
        )[1]

        self.assertEqual(campaign["research"]["status"], "needs_source_verification")
        self.assertEqual(campaign["research"]["verified_trend_count"], 0)
        self.assertFalse(stored_trend["verification"]["eligible_for_content"])
        self.assertEqual(stored_trend["verification"]["current_recent_source_count"], 0)

    def test_default_brief_is_built_from_campaign_source(self):
        campaign = load_campaign_catalog(self.root, today=date(2026, 7, 10))[4]
        brief = default_brief_payload(
            campaign, content_id="k5-2026w28-portfolio-carousel"
        )

        self.assertEqual(brief["campaign_id"], "k5")
        self.assertEqual(
            brief["proof_sources"], ["Kampagnen/kampagne_5_app_entwicklung.json"]
        )
        self.assertEqual(brief["cta"], "App-Modernisierungscheck anfragen")
        self.assertEqual(brief["format"], "portfolio_carousel")
        self.assertNotIn("demo", brief["objective"].lower())
        self.assertEqual(brief["objective"], campaign["generation_objective"])
        self.assertEqual(
            brief["campaign_context"]["generation_direction"],
            campaign["generation_objective"],
        )
        self.assertNotIn("master_prompt", brief["campaign_context"])
        self.assertTrue(brief["campaign_context"]["content_constraints"])
        self.assertEqual(
            brief["campaign_context"]["audience_profiles"],
            campaign["audience_profiles"],
        )

    def test_people_campaign_carries_consent_and_asset_risk(self):
        campaign = load_campaign_catalog(self.root, today=date(2026, 7, 10))[3]
        brief = default_brief_payload(campaign, content_id="k4-2026w28-reel")

        self.assertEqual(
            brief["risk_flags"], ["people_consent_and_real_assets_required"]
        )

    def test_qa_campaign_surfaces_outcome_claim_risk(self):
        campaign = load_campaign_catalog(self.root, today=date(2026, 7, 10))[0]
        brief = default_brief_payload(campaign, content_id="k1-2026w28-expert-post")

        self.assertEqual(brief["risk_flags"], ["outcome_claims_require_evidence"])

    def test_legacy_names_resolve_without_duplicating_campaigns(self):
        self.assertEqual(
            resolve_campaign_id("Consulting Test- und Qualitätsmanagement"), "k1"
        )
        self.assertEqual(resolve_campaign_id("Maßgeschneiderte App-Entwicklung"), "k5")


if __name__ == "__main__":
    unittest.main()
