import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marketing_machine.content_generator import generate_public_copy
from marketing_machine.storage import JsonStore
from marketing_machine.trend_research import (
    SearchResult,
    TrendSearchClient,
    concept_to_content_brief,
    generate_reel_concepts,
    load_campaigns,
    run_trend_research,
)


class FakeTrendSearchClient(TrendSearchClient):
    def available_sources(self):
        return ["fake_search"]

    def search(self, query, *, platform, lookback_start, now, limit=5):
        keyword = "QA" if "Test" in query or "QA" in query else "AI"
        return [
            SearchResult(
                source="fake_search",
                platform=platform,
                title=f"{keyword} short-form question trend on {platform}",
                url=f"https://example.test/{platform}/{keyword.lower()}",
                snippet=f"Recent discussion about {keyword}, reels, questions, and practical checklists.",
                published_at=now.isoformat(),
                metrics={"shares": 140, "comments": 12},
            )
        ]


class TrendResearchTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        self.now = datetime(2026, 7, 8, 10, 0, tzinfo=timezone.utc)

    def test_loads_all_five_campaigns(self):
        campaigns = load_campaigns(self.root)

        self.assertEqual(len(campaigns), 5)
        self.assertTrue(any(campaign["id"] == "kampagne_3_lfa_azubis" for campaign in campaigns))
        self.assertTrue(any(campaign["id"] == "kampagne_4_mitarbeiter" for campaign in campaigns))

    def test_trend_run_builds_verified_campaign_trends(self):
        trend_run = run_trend_research(
            self.root,
            payload={"lookback_days": 10, "campaign_ids": ["kampagne_1_consulting_qa"], "platforms": ["instagram", "reddit"]},
            search_client=FakeTrendSearchClient(),
            now=self.now,
        )

        self.assertEqual(trend_run["status"], "verified_sources")
        campaign = trend_run["campaigns"][0]
        self.assertEqual(campaign["campaign"]["id"], "kampagne_1_consulting_qa")
        self.assertTrue(campaign["trends"])
        self.assertEqual(campaign["trends"][0]["verification"]["status"], "verified_recent")

    def test_generates_topic_locked_reel_concepts_and_content_brief(self):
        trend_run = run_trend_research(
            self.root,
            payload={"campaign_ids": ["kampagne_1_consulting_qa"], "platforms": ["instagram", "reddit"]},
            search_client=FakeTrendSearchClient(),
            now=self.now,
        )
        campaign = trend_run["campaigns"][0]
        trend = campaign["trends"][0]

        concept = generate_reel_concepts(
            trend_run,
            campaign_id=campaign["campaign"]["id"],
            trend_id=trend["id"],
            user_prompt="Make it a sharper Q&A about QA risk with kinetic captions.",
            now=self.now,
        )
        brief = concept_to_content_brief(concept, variant_id=concept["variants"][0]["id"])
        generated = generate_public_copy(brief)

        self.assertEqual(len(concept["variants"]), 4)
        self.assertEqual(brief.channel, "Instagram")
        self.assertEqual(brief.format, "reel")
        self.assertEqual(brief.trend_id, trend["id"])
        self.assertTrue(brief.reel_concept)
        self.assertEqual(brief.reel_concept["creator_direction"], "Make it a sharper Q&A about QA risk with kinetic captions.")
        self.assertLessEqual(len(brief.hashtags), 5)
        self.assertIn("Instagram-Reel-Entwurf", generated.public_copy)
        self.assertNotIn("Creator-Richtung", generated.public_copy)
        self.assertNotIn("Interne Trendquellen", generated.public_copy)

    def test_off_topic_prompt_is_blocked(self):
        trend_run = run_trend_research(
            self.root,
            payload={"campaign_ids": ["kampagne_1_consulting_qa"], "platforms": ["instagram", "reddit"]},
            search_client=FakeTrendSearchClient(),
            now=self.now,
        )
        campaign = trend_run["campaigns"][0]
        trend = campaign["trends"][0]

        with self.assertRaises(ValueError):
            generate_reel_concepts(
                trend_run,
                campaign_id=campaign["campaign"]["id"],
                trend_id=trend["id"],
                user_prompt="Make this about football transfer gossip and celebrity dating drama.",
                now=self.now,
            )

    def test_store_persists_trend_runs_and_concepts(self):
        trend_run = run_trend_research(
            self.root,
            payload={"campaign_ids": ["kampagne_1_consulting_qa"], "platforms": ["instagram", "reddit"]},
            search_client=FakeTrendSearchClient(),
            now=self.now,
        )
        campaign = trend_run["campaigns"][0]
        concept = generate_reel_concepts(
            trend_run,
            campaign_id=campaign["campaign"]["id"],
            trend_id=campaign["trends"][0]["id"],
            now=self.now,
        )

        with tempfile.TemporaryDirectory() as tmp:
            store = JsonStore(Path(tmp))
            store.save_trend_run(trend_run)
            store.save_reel_concept(concept)

            self.assertEqual(store.load_trend_run(trend_run["id"])["id"], trend_run["id"])
            self.assertEqual(store.load_reel_concept(concept["id"])["id"], concept["id"])
            self.assertEqual(store.list_trend_runs(limit=5)[0]["trend_count"], len(campaign["trends"]))
            self.assertEqual(store.list_reel_concepts(limit=5)[0]["variant_count"], 4)


if __name__ == "__main__":
    unittest.main()
