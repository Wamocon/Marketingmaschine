import copy
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marketing_machine.content_generator import generate_public_copy
from marketing_machine.governance import GovernancePolicy
from marketing_machine.storage import JsonStore
from marketing_machine.trend_research import (
    ConfiguredTrendSearchClient,
    DEFAULT_PLATFORMS,
    SearchResult,
    TrendSearchClient,
    _make_test_verification_override,
    concept_to_content_brief,
    generate_reel_concepts,
    load_campaigns,
    normalize_requested_platforms,
    refresh_trend_run_eligibility,
    run_trend_research,
    source_domain,
    trend_run_has_verified_sources,
    trend_request_fingerprint,
    validate_trend_brief_against_run,
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
                url=f"https://{platform}-publisher.com/{keyword.lower()}",
                snippet=f"Recent discussion about {keyword}, reels, questions, and practical checklists.",
                published_at=now.isoformat(),
                retrieved_at=now.isoformat(),
                metrics={"shares": 140, "comments": 12},
            )
        ]

    def telemetry(self):
        return [
            {
                "adapter": "fake_search",
                "status": "success",
                "attempts": 2,
                "successful_requests": 2,
                "result_count": 2,
                "errors": [],
            }
        ]


class SamePublisherTrendSearchClient(FakeTrendSearchClient):
    def search(self, query, *, platform, lookback_start, now, limit=5):
        result = super().search(query, platform=platform, lookback_start=lookback_start, now=now, limit=limit)[0]
        return [
            SearchResult(
                source=result.source,
                platform=result.platform,
                title=result.title,
                url=f"https://{platform}.same-publisher.com/qa",
                snippet=result.snippet,
                published_at=result.published_at,
                retrieved_at=result.retrieved_at,
                metrics=result.metrics,
            )
        ]


class UndatedIndependentTrendSearchClient(FakeTrendSearchClient):
    def search(self, query, *, platform, lookback_start, now, limit=5):
        result = super().search(query, platform=platform, lookback_start=lookback_start, now=now, limit=limit)[0]
        return [
            SearchResult(
                source=result.source,
                platform=result.platform,
                title=result.title,
                url=result.url,
                snippet=result.snippet,
                published_at="",
                retrieved_at=now.isoformat(),
                metrics=result.metrics,
            )
        ]


class EmptyTrendSearchClient(TrendSearchClient):
    def available_sources(self):
        return []

    def search(self, query, *, platform, lookback_start, now, limit=5):
        return []


class InternalOnlyTrendSearchClient(TrendSearchClient):
    def available_sources(self):
        return ["misconfigured_internal_search"]

    def search(self, query, *, platform, lookback_start, now, limit=5):
        return [
            SearchResult(
                source="misconfigured_internal_search",
                platform=platform,
                title="QA test automation trend",
                url="http://core-n8n:5678/internal-result",
                snippet="QA test automation trend details.",
                published_at=now.isoformat(),
                retrieved_at=now.isoformat(),
            ),
            SearchResult(
                source="misconfigured_internal_search",
                platform=platform,
                title="QA test automation trend",
                url="http://192.168.178.75/internal-result",
                snippet="QA test automation trend details.",
                published_at=now.isoformat(),
                retrieved_at=now.isoformat(),
            ),
        ]


class OldButWithinRequestedLookbackClient(FakeTrendSearchClient):
    def search(self, query, *, platform, lookback_start, now, limit=5):
        result = super().search(
            query,
            platform=platform,
            lookback_start=lookback_start,
            now=now,
            limit=limit,
        )[0]
        return [
            SearchResult(
                source=result.source,
                platform=result.platform,
                title=result.title,
                url=result.url,
                snippet=result.snippet,
                published_at=(now - timedelta(days=8)).isoformat(),
                retrieved_at=now.isoformat(),
                metrics=result.metrics,
            )
        ]


class CountingTrendSearchClient(TrendSearchClient):
    def __init__(self):
        self.call_count = 0
        self._lock = threading.Lock()

    def available_sources(self):
        return ["counting_search"]

    def search(self, query, *, platform, lookback_start, now, limit=5):
        with self._lock:
            self.call_count += 1
        return []


class BlockingCountingTrendSearchClient(CountingTrendSearchClient):
    def __init__(self):
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def search(self, query, *, platform, lookback_start, now, limit=5):
        with self._lock:
            self.call_count += 1
        self.started.set()
        if not self.release.wait(timeout=5):
            raise TimeoutError("test did not release the blocked search")
        return []


class MismatchedRecentPaddingClient(TrendSearchClient):
    """Reproduces the live Qytera topic plus unrelated recent Aqua result."""

    def available_sources(self):
        return ["fake_search"]

    def search(self, query, *, platform, lookback_start, now, limit=5):
        return [
            SearchResult(
                source="fake_search",
                platform="web",
                title="Testautomatisierung 2026: 6 goldene Regeln + STQB-Definition",
                url="https://www.qytera.de/blog/testautomatisierung-tipps-goldene-regeln",
                snippet=(
                    "Sechs goldene Regeln, die ISTQB-Definition und eine separate wirtschaftliche "
                    "Einordnung der Testautomatisierung."
                ),
                published_at=(now - timedelta(days=11)).isoformat(),
                retrieved_at=now.isoformat(),
            ),
            SearchResult(
                source="fake_search",
                platform="web",
                title="Claude Code Testautomatisierung: Kompletter Guide 2026",
                url="https://aqua-cloud.io/de/claude-code-testautomatisierung-wirklich-funktioniert/",
                snippet=(
                    "Die Kombination aus KI-gestützter Codierung und systematischem Test-Management "
                    "für moderne QA-Teams."
                ),
                published_at=(now - timedelta(days=1)).isoformat(),
                retrieved_at=now.isoformat(),
            ),
        ]


class FakeHTTPResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, size=None):
        import json

        body = json.dumps(self.payload).encode("utf-8")
        return body if size is None else body[:size]


class TrendResearchTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        self.now = datetime(2026, 7, 8, 10, 0, tzinfo=timezone.utc)

    def test_loads_all_five_campaigns(self):
        campaigns = load_campaigns(self.root)

        self.assertEqual(len(campaigns), 5)
        self.assertTrue(any(campaign["id"] == "kampagne_3_lfa_azubis" for campaign in campaigns))
        self.assertTrue(any(campaign["id"] == "kampagne_4_mitarbeiter" for campaign in campaigns))

    def test_explicit_empty_or_invalid_platform_selection_is_rejected(self):
        for value in ([], [""], ["web", "unknown-source"], "web"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                normalize_requested_platforms(value)
        with self.assertRaisesRegex(ValueError, "at least one source"):
            run_trend_research(
                self.root,
                payload={"campaign_ids": ["k1"], "platforms": []},
                search_client=CountingTrendSearchClient(),
                now=self.now,
            )

    def test_omitted_platform_selection_uses_the_bounded_default(self):
        self.assertEqual(normalize_requested_platforms(None), DEFAULT_PLATFORMS)

    def test_all_five_business_campaign_ids_resolve_to_source_campaigns(self):
        client = CountingTrendSearchClient()

        trend_run = run_trend_research(
            self.root,
            payload={
                "campaign_ids": ["k1", "k2", "k3", "k4", "k5"],
                "platforms": ["web"],
            },
            search_client=client,
            now=self.now,
        )

        self.assertEqual(
            [item["campaign"]["id"] for item in trend_run["campaigns"]],
            [
                "kampagne_1_consulting_qa",
                "kampagne_2_ki_sokrates",
                "kampagne_3_lfa_azubis",
                "kampagne_4_mitarbeiter",
                "kampagne_5_app_entwicklung",
            ],
        )
        self.assertEqual(client.call_count, 5)
        self.assertEqual(trend_run["search_fanout"]["campaign_count"], 5)

    def test_mixed_business_and_source_aliases_are_deduplicated(self):
        client = CountingTrendSearchClient()

        trend_run = run_trend_research(
            self.root,
            payload={
                "campaign_ids": [
                    "K1",
                    "kampagne_1_consulting_qa",
                    "k2",
                    "kampagne_2_ki_sokrates",
                    " k1 ",
                ],
                "platforms": ["web"],
            },
            search_client=client,
            now=self.now,
        )

        self.assertEqual(
            [item["campaign"]["id"] for item in trend_run["campaigns"]],
            ["kampagne_1_consulting_qa", "kampagne_2_ki_sokrates"],
        )
        self.assertEqual(client.call_count, 2)
        self.assertEqual(trend_run["search_fanout"]["campaign_count"], 2)

    def test_alias_normalization_preserves_raw_fingerprint_and_idempotency(self):
        client = CountingTrendSearchClient()
        payload = {
            "request_id": "canonical-source-alias-retry",
            "campaign_ids": ["k1", "kampagne_1_consulting_qa"],
            "platforms": ["web"],
        }

        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"MARKETING_MACHINE_DATA_DIR": tmp},
        ):
            first = run_trend_research(
                self.root,
                payload=payload,
                search_client=client,
                now=self.now,
            )
            retry = run_trend_research(
                self.root,
                payload=payload,
                search_client=client,
                now=self.now + timedelta(minutes=1),
            )

        self.assertEqual(first["request_fingerprint"], trend_request_fingerprint(payload))
        self.assertEqual(first["id"], retry["id"])
        self.assertEqual(client.call_count, 1)
        self.assertEqual(len(first["campaigns"]), 1)

    def test_unknown_campaign_selection_fails_before_search(self):
        client = CountingTrendSearchClient()

        with self.assertRaisesRegex(ValueError, "unknown campaign selection"):
            run_trend_research(
                self.root,
                payload={
                    "campaign_ids": ["k1", "not-a-real-campaign"],
                    "platforms": ["web"],
                },
                search_client=client,
                now=self.now,
            )

        self.assertEqual(client.call_count, 0)

    def test_omitted_campaign_ids_still_selects_the_default_five(self):
        client = CountingTrendSearchClient()

        trend_run = run_trend_research(
            self.root,
            payload={"platforms": ["web"]},
            search_client=client,
            now=self.now,
        )

        self.assertEqual(len(trend_run["campaigns"]), 5)
        self.assertEqual(client.call_count, 5)
        self.assertEqual(trend_run["search_fanout"]["campaign_count"], 5)

    def test_private_and_loopback_urls_cannot_be_public_evidence(self):
        self.assertEqual(source_domain("http://127.0.0.1/source"), "")
        self.assertEqual(source_domain("http://[::1]/source"), "")
        self.assertEqual(source_domain("http://192.168.178.75/source"), "")
        self.assertEqual(source_domain("http://service.internal/source"), "")
        self.assertEqual(source_domain("http://service.home.arpa/source"), "")
        self.assertEqual(source_domain("http://service.private/source"), "")
        self.assertEqual(source_domain("https://publisher.example/source"), "")
        self.assertEqual(source_domain("https://publisher.invalid/source"), "")
        self.assertEqual(source_domain("https://publisher.test/source"), "")
        self.assertEqual(source_domain("https://publisher.onion/source"), "")
        self.assertEqual(source_domain("http://intranet/source"), "")
        self.assertEqual(source_domain("http://core-n8n:5678/source"), "")
        self.assertEqual(source_domain("http://@example.com/source"), "")
        self.assertEqual(source_domain("http://user:password@example.com/source"), "")
        self.assertEqual(source_domain("https://news.reuters.com/source"), "reuters.com")

    def test_internal_search_results_are_discarded_not_stored_as_evidence(self):
        trend_run = run_trend_research(
            self.root,
            payload={"campaign_ids": ["kampagne_1_consulting_qa"], "platforms": ["web"]},
            search_client=InternalOnlyTrendSearchClient(),
            now=self.now,
        )

        trend = trend_run["campaigns"][0]["trends"][0]
        self.assertEqual(trend_run["status"], "needs_live_sources")
        self.assertEqual(trend["trend_type"], "evergreen_placeholder")
        self.assertEqual(trend["citations"][0]["domain"], "internal")
        self.assertFalse(any("core-n8n" in value for value in trend["source_urls"]))

    def test_trend_run_builds_verified_campaign_trends(self):
        trend_run = run_trend_research(
            self.root,
            payload={"lookback_days": 10, "campaign_ids": ["kampagne_1_consulting_qa"], "platforms": ["instagram", "reddit"]},
            search_client=FakeTrendSearchClient(),
            now=self.now,
        )

        self.assertEqual(trend_run["status"], "verified_sources")
        self.assertEqual(trend_run["successful_source_adapters"], ["fake_search"])
        self.assertFalse(trend_run["source_errors"])
        campaign = trend_run["campaigns"][0]
        self.assertEqual(campaign["campaign"]["id"], "kampagne_1_consulting_qa")
        self.assertTrue(campaign["trends"])
        self.assertEqual(campaign["trends"][0]["verification"]["status"], "verified_recent")
        self.assertEqual(campaign["trends"][0]["verification"]["independent_source_count"], 2)
        self.assertTrue(campaign["trends"][0]["verification"]["eligible_for_content"])
        self.assertEqual(campaign["trends"][0]["verification"]["eligibility_freshness_days"], 7)
        citation = campaign["trends"][0]["citations"][0]
        self.assertEqual(
            set(citation),
            {"title", "domain", "published", "retrieved", "snippet", "url"},
        )
        self.assertTrue(citation["published"])
        self.assertTrue(citation["retrieved"])

    def test_trend_request_id_makes_retry_run_id_stable(self):
        payload = {
            "request_id": "n8n-execution-123",
            "campaign_ids": ["kampagne_1_consulting_qa"],
            "platforms": ["web"],
        }
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}
        ):
            first = run_trend_research(
                self.root,
                payload=payload,
                search_client=FakeTrendSearchClient(),
                now=self.now,
            )
            retry = run_trend_research(
                self.root,
                payload=payload,
                search_client=FakeTrendSearchClient(),
                now=self.now + timedelta(minutes=5),
            )

        self.assertEqual(first["id"], retry["id"])
        self.assertEqual(first["request_fingerprint"], retry["request_fingerprint"])

    def test_governance_budget_is_a_hard_external_adapter_call_ceiling(self):
        client = ConfiguredTrendSearchClient(
            env={
                "FIRECRAWL_BASE_URL": "https://api.firecrawl.dev",
                "FIRECRAWL_API_KEY": "test-firecrawl-key",
                "GOOGLE_CSE_API_KEY": "test-google-key",
                "GOOGLE_CSE_ID": "test-google-cse",
                "SEARXNG_BASE_URL": "https://search.example.com",
            }
        )
        policy = GovernancePolicy(
            name="two-call-test",
            allowed_tools=["search_public_sources"],
            max_calls_per_request=2,
        )

        with patch.object(client, "_request_json", return_value={}) as request_json:
            trend_run = run_trend_research(
                self.root,
                payload={"campaign_ids": ["kampagne_1_consulting_qa"], "platforms": ["web", "reddit"]},
                policy=policy,
                search_client=client,
                now=self.now,
            )

        self.assertEqual(request_json.call_count, 2)
        self.assertEqual(trend_run["external_call_budget"]["limit"], 2)
        self.assertEqual(trend_run["external_call_budget"]["used"], 2)
        self.assertEqual(trend_run["external_call_budget"]["denied"], 1)
        self.assertTrue(trend_run["external_call_budget"]["exhausted"])
        self.assertEqual(trend_run["search_fanout"]["planned_pairs"], 1)
        self.assertEqual(trend_run["search_fanout"]["partial_pairs"], 1)
        telemetry = {item["adapter"]: item for item in trend_run["source_telemetry"]}
        self.assertEqual(telemetry["searxng"]["budget_skipped"], 1)

    def test_campaign_platform_fanout_is_capped_before_search_calls(self):
        client = CountingTrendSearchClient()
        policy = GovernancePolicy(
            name="three-call-test",
            allowed_tools=["search_public_sources"],
            max_calls_per_request=3,
        )

        trend_run = run_trend_research(
            self.root,
            payload={"platforms": [*DEFAULT_PLATFORMS, "web", "reddit"]},
            policy=policy,
            search_client=client,
            now=self.now,
        )

        self.assertEqual(client.call_count, 3)
        self.assertEqual(trend_run["search_fanout"]["campaign_count"], 5)
        self.assertEqual(trend_run["search_fanout"]["platform_count"], 5)
        self.assertEqual(trend_run["search_fanout"]["requested_pairs"], 25)
        self.assertEqual(trend_run["search_fanout"]["planned_pairs"], 3)
        self.assertTrue(trend_run["search_fanout"]["truncated"])

    def test_duplicate_concurrent_request_uses_one_search_execution(self):
        client = BlockingCountingTrendSearchClient()
        payload = {
            "request_id": "same-n8n-execution",
            "campaign_ids": ["kampagne_1_consulting_qa"],
            "platforms": ["web"],
        }
        results: list[dict] = []
        failures: list[BaseException] = []

        def invoke() -> None:
            try:
                results.append(
                    run_trend_research(
                        self.root,
                        payload=payload,
                        search_client=client,
                        now=self.now,
                    )
                )
            except BaseException as exc:  # pragma: no cover - asserted below
                failures.append(exc)

        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}
        ):
            first = threading.Thread(target=invoke)
            second = threading.Thread(target=invoke)
            first.start()
            self.assertTrue(client.started.wait(timeout=2))
            second.start()
            client.release.set()
            first.join(timeout=5)
            second.join(timeout=5)

        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(client.call_count, 1)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["id"], results[1]["id"])

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
        self.assertEqual(brief.channel, "LinkedIn")
        self.assertEqual(brief.format, "expert_post")
        self.assertEqual(concept["delivery"], {"channel": "LinkedIn", "format": "expert_post"})
        self.assertTrue(all(variant.get("idea") for variant in concept["variants"]))
        self.assertEqual(brief.trend_id, trend["id"])
        self.assertEqual(brief.trend_run_id, trend_run["id"])
        self.assertNotIn("master_prompt", brief.campaign_context)
        self.assertTrue(brief.campaign_context["content_constraints"])
        self.assertEqual(
            [item["profile_id"] for item in brief.campaign_context["audience_profiles"]],
            ["z1", "z2", "z3", "z5"],
        )
        self.assertTrue(brief.campaign_context["audience_profiles"][0]["pain_points"])
        self.assertEqual(brief.risk_flags, ["outcome_claims_require_evidence"])
        self.assertEqual(validate_trend_brief_against_run(brief, trend_run, now=self.now), [])
        self.assertTrue(brief.reel_concept)
        self.assertEqual(brief.reel_concept["creator_direction"], "Make it a sharper Q&A about QA risk with kinetic captions.")
        self.assertEqual(concept["prompt_application"]["caption_style"], "kinetic")
        self.assertIn("Nutzerwunsch: Kinetic Captions", concept["variants"][0]["animation_notes"])
        self.assertLessEqual(len(brief.hashtags), 5)
        self.assertTrue(generated.channel_copy["body"])
        self.assertEqual(
            generated.public_copy,
            "\n\n".join(
                [
                    generated.channel_copy["headline"],
                    generated.channel_copy["body"],
                    brief.cta,
                ]
            ),
        )
        self.assertNotIn("#", generated.public_copy)
        self.assertNotIn("Creator-Richtung", generated.public_copy)
        self.assertNotIn("Interne Trendquellen", generated.public_copy)

    def test_stored_trend_provenance_rejects_tampering_and_stale_runs(self):
        trend_run = run_trend_research(
            self.root,
            payload={"campaign_ids": ["kampagne_1_consulting_qa"], "platforms": ["instagram", "reddit"]},
            search_client=FakeTrendSearchClient(),
            now=self.now,
        )
        trend = trend_run["campaigns"][0]["trends"][0]
        concept = generate_reel_concepts(
            trend_run,
            campaign_id="kampagne_1_consulting_qa",
            trend_id=trend["id"],
            now=self.now,
        )
        brief = concept_to_content_brief(concept)

        brief.trend_sources = ["https://attacker.invalid/forged"]
        self.assertIn(
            "sources do not match",
            "; ".join(validate_trend_brief_against_run(brief, trend_run, now=self.now)),
        )
        brief.trend_sources = list(trend["source_urls"])
        stale_run = copy.deepcopy(trend_run)
        self.assertTrue(stale_run["campaigns"][0]["trends"][0]["verification"]["eligible_for_content"])
        refresh_trend_run_eligibility(stale_run, now=self.now + timedelta(days=8))
        stale_verification = stale_run["campaigns"][0]["trends"][0]["verification"]
        self.assertFalse(stale_verification["eligible_for_content"])
        self.assertEqual(stale_verification["current_recent_source_count"], 0)
        self.assertEqual(stale_run["status"], "needs_source_verification")
        self.assertFalse(trend_run_has_verified_sources(trend_run, now=self.now + timedelta(days=8)))
        self.assertIn(
            "older than seven days",
            "; ".join(
                validate_trend_brief_against_run(
                    brief,
                    trend_run,
                    now=self.now + timedelta(days=8),
                )
            ),
        )

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

    def test_short_off_topic_prompt_is_also_blocked(self):
        trend_run = run_trend_research(
            self.root,
            payload={"campaign_ids": ["kampagne_1_consulting_qa"], "platforms": ["instagram", "reddit"]},
            search_client=FakeTrendSearchClient(),
            now=self.now,
        )
        trend = trend_run["campaigns"][0]["trends"][0]

        with self.assertRaisesRegex(ValueError, "selected campaign and trend"):
            generate_reel_concepts(
                trend_run,
                campaign_id="kampagne_1_consulting_qa",
                trend_id=trend["id"],
                user_prompt="football gossip",
                now=self.now,
            )

    def test_prompt_changes_format_delivery_and_pacing(self):
        trend_run = run_trend_research(
            self.root,
            payload={"campaign_ids": ["kampagne_1_consulting_qa"], "platforms": ["instagram", "reddit"]},
            search_client=FakeTrendSearchClient(),
            now=self.now,
        )
        trend = trend_run["campaigns"][0]["trends"][0]

        concept = generate_reel_concepts(
            trend_run,
            campaign_id="kampagne_1_consulting_qa",
            trend_id=trend["id"],
            user_prompt="Use a slower voiceover checklist about QA risk.",
            now=self.now,
        )

        self.assertIn("Checkliste", concept["variants"][0]["format"])
        self.assertEqual(concept["prompt_application"]["pace"], "calm")
        self.assertEqual(concept["prompt_application"]["delivery"], "voiceover")
        self.assertIn("Voiceover:", concept["variants"][0]["beats"][0])
        self.assertIn("Lesepause", concept["variants"][0]["beats"][0])

    def test_german_style_only_prompt_is_not_misclassified_as_off_topic(self):
        trend_run = run_trend_research(
            self.root,
            payload={"campaign_ids": ["kampagne_1_consulting_qa"], "platforms": ["instagram", "reddit"]},
            search_client=FakeTrendSearchClient(),
            now=self.now,
        )
        trend = trend_run["campaigns"][0]["trends"][0]

        concept = generate_reel_concepts(
            trend_run,
            campaign_id="kampagne_1_consulting_qa",
            trend_id=trend["id"],
            user_prompt="Sachliches Q&A mit klarer Bildschirmaufnahme und ruhigem Tempo.",
            now=self.now,
        )

        self.assertEqual(len(concept["variants"]), 4)
        self.assertEqual(concept["prompt_application"]["tone"], "professional")
        self.assertEqual(concept["prompt_application"]["pace"], "calm")

    def test_same_publisher_and_undated_sources_do_not_verify(self):
        same_publisher_run = run_trend_research(
            self.root,
            payload={"campaign_ids": ["kampagne_1_consulting_qa"], "platforms": ["instagram", "reddit"]},
            search_client=SamePublisherTrendSearchClient(),
            now=self.now,
        )
        same_publisher_trend = same_publisher_run["campaigns"][0]["trends"][0]
        self.assertEqual(same_publisher_run["status"], "needs_source_verification")
        self.assertEqual(same_publisher_trend["verification"]["independent_source_count"], 1)
        with self.assertRaisesRegex(ValueError, "verified sources required"):
            generate_reel_concepts(
                same_publisher_run,
                campaign_id="kampagne_1_consulting_qa",
                trend_id=same_publisher_trend["id"],
                now=self.now,
            )

        undated_run = run_trend_research(
            self.root,
            payload={"campaign_ids": ["kampagne_1_consulting_qa"], "platforms": ["instagram", "reddit"]},
            search_client=UndatedIndependentTrendSearchClient(),
            now=self.now,
        )
        undated_trend = undated_run["campaigns"][0]["trends"][0]
        self.assertEqual(undated_trend["verification"]["status"], "source_verified_date_unconfirmed")
        self.assertEqual(undated_trend["verification"]["recent_source_count"], 0)

    def test_requested_lookback_cannot_expand_current_freshness_beyond_seven_days(self):
        trend_run = run_trend_research(
            self.root,
            payload={
                "lookback_days": 30,
                "campaign_ids": ["kampagne_1_consulting_qa"],
                "platforms": ["instagram", "reddit"],
            },
            search_client=OldButWithinRequestedLookbackClient(),
            now=self.now,
        )

        trend = trend_run["campaigns"][0]["trends"][0]
        self.assertEqual(trend["verification"]["status"], "source_verified_date_unconfirmed")
        self.assertEqual(trend["verification"]["recent_source_count"], 0)
        self.assertFalse(trend["verification"]["eligible_for_content"])
        self.assertEqual(trend_run["status"], "needs_source_verification")

    def test_exact_topic_corroboration_rejects_mismatched_recent_source_padding(self):
        trend_run = run_trend_research(
            self.root,
            payload={"campaign_ids": ["kampagne_1_consulting_qa"], "platforms": ["web"]},
            search_client=MismatchedRecentPaddingClient(),
            now=self.now,
        )
        trend = trend_run["campaigns"][0]["trends"][0]

        self.assertEqual(trend_run["status"], "needs_source_verification")
        self.assertIn("ISTQB", trend["topic"])
        self.assertNotIn(" STQB", trend["topic"])
        self.assertEqual(trend["verification"]["status"], "single_source_review")
        self.assertEqual(trend["verification"]["corroboration_version"], "exact-topic-v1")
        self.assertEqual(trend["verification"]["candidate_evidence_count"], 2)
        self.assertEqual(trend["verification"]["excluded_noncorroborating_count"], 1)
        self.assertEqual(trend["verification"]["independent_source_count"], 1)
        self.assertEqual(trend["verification"]["recent_source_count"], 0)
        self.assertEqual(
            trend["source_urls"],
            ["https://www.qytera.de/blog/testautomatisierung-tipps-goldene-regeln"],
        )
        self.assertEqual(len(trend["citations"]), 1)
        self.assertIn("ISTQB", trend["citations"][0]["title"])
        self.assertIn("STQB", trend["citations"][0]["original_title"])
        self.assertIn("STQB", trend["evidence"][0]["title"])

        with self.assertRaisesRegex(ValueError, "verified sources required"):
            generate_reel_concepts(
                trend_run,
                campaign_id="kampagne_1_consulting_qa",
                trend_id=trend["id"],
                now=self.now,
            )

    def test_legacy_verified_metadata_cannot_bypass_exact_topic_corroboration(self):
        trend_run = run_trend_research(
            self.root,
            payload={"campaign_ids": ["kampagne_1_consulting_qa"], "platforms": ["web"]},
            search_client=MismatchedRecentPaddingClient(),
            now=self.now,
        )
        forged_run = copy.deepcopy(trend_run)
        trend = forged_run["campaigns"][0]["trends"][0]
        aqua_url = "https://aqua-cloud.io/de/claude-code-testautomatisierung-wirklich-funktioniert/"
        trend["source_urls"].append(aqua_url)
        trend["citations"].append(
            {
                "title": "Claude Code Testautomatisierung: Kompletter Guide 2026",
                "domain": "aqua-cloud.io",
                "published": (self.now - timedelta(days=1)).isoformat(),
                "retrieved": self.now.isoformat(),
                "snippet": "KI-gestützte Codierung und systematisches Test-Management.",
                "url": aqua_url,
            }
        )
        trend["verification"].update(
            {
                "status": "verified_recent",
                "verified": True,
                "independent_source_count": 2,
                "recent_source_count": 1,
            }
        )
        trend["trend_type"] = "current_trend"
        trend["is_current_trend"] = True
        trend["recency_claim_allowed"] = True

        self.assertFalse(trend_run_has_verified_sources(forged_run, now=self.now))

        with self.assertRaisesRegex(ValueError, "verified sources required"):
            generate_reel_concepts(
                forged_run,
                campaign_id="kampagne_1_consulting_qa",
                trend_id=trend["id"],
                now=self.now,
            )

    def test_test_capability_can_override_generation_but_not_later_approval(self):
        trend_run = run_trend_research(
            self.root,
            payload={"campaign_ids": ["kampagne_1_consulting_qa"], "platforms": ["instagram", "reddit"]},
            search_client=SamePublisherTrendSearchClient(),
            now=self.now,
        )
        trend = trend_run["campaigns"][0]["trends"][0]
        override = _make_test_verification_override()
        concept = generate_reel_concepts(
            trend_run,
            campaign_id="kampagne_1_consulting_qa",
            trend_id=trend["id"],
            now=self.now,
            verification_override=override,
        )

        self.assertEqual(concept["status"], "draft_test_override")
        with self.assertRaisesRegex(ValueError, "approve a current-trend concept"):
            concept_to_content_brief(concept)
        self.assertEqual(
            concept_to_content_brief(concept, verification_override=override).format,
            "expert_post",
        )

    def test_empty_results_are_explicit_unverified_evergreen_placeholders(self):
        trend_run = run_trend_research(
            self.root,
            payload={"campaign_ids": ["kampagne_1_consulting_qa"], "platforms": ["web"]},
            search_client=EmptyTrendSearchClient(),
            now=self.now,
        )
        trend = trend_run["campaigns"][0]["trends"][0]

        self.assertEqual(trend_run["status"], "needs_live_sources")
        self.assertEqual(trend["trend_type"], "evergreen_placeholder")
        self.assertEqual(trend["verification"]["status"], "evergreen_unverified")
        self.assertFalse(trend["recency_claim_allowed"])
        self.assertEqual(trend["citations"][0]["published"], "")
        self.assertEqual(trend["citations"][0]["domain"], "internal")
        concept = generate_reel_concepts(
            trend_run,
            campaign_id="kampagne_1_consulting_qa",
            trend_id=trend["id"],
            now=self.now,
        )
        brief = concept_to_content_brief(concept)
        self.assertEqual(concept["content_mode"], "evergreen")
        self.assertIn("Evergreen", brief.objective)

    def test_firecrawl_v2_search_contract_and_telemetry(self):
        payload = {
            "success": True,
            "id": "fc-job-1",
            "data": {
                "web": [
                    {
                        "title": "QA release risk trend",
                        "description": "Teams discuss release risk in short-form content.",
                        "url": "https://source-one.com/article",
                        "metadata": {"publishedTime": self.now.isoformat()},
                    }
                ],
                "news": [
                    {
                        "title": "QA teams adopt practical risk checks",
                        "snippet": "A second publisher covers the same QA signal.",
                        "url": "https://source-two.net/story",
                        "date": "2 days ago",
                    }
                ],
            },
        }
        client = ConfiguredTrendSearchClient(
            env={
                "FIRECRAWL_BASE_URL": "https://firecrawl.internal",
                "FIRECRAWL_API_KEY": "fc-secret-value",
            },
            timeout=3,
        )
        with patch(
            "marketing_machine.http_safety._CREDENTIAL_SAFE_OPENER.open",
            return_value=FakeHTTPResponse(payload),
        ) as urlopen:
            results = client.search(
                "QA release risk latest",
                platform="web",
                lookback_start=self.now - timedelta(days=10),
                now=self.now,
                limit=5,
            )

        request = urlopen.call_args.args[0]
        request_body = __import__("json").loads(request.data.decode("utf-8"))
        self.assertEqual(request.full_url, "https://firecrawl.internal/v2/search")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request_body["sources"], ["web", "news"])
        self.assertIn("cdr:1", request_body["tbs"])
        self.assertEqual(len(results), 2)
        self.assertTrue(all(result.published_at for result in results))
        telemetry = client.telemetry()[0]
        self.assertEqual(telemetry["adapter"], "firecrawl_v2")
        self.assertEqual(telemetry["status"], "success")
        self.assertEqual(telemetry["successful_requests"], 1)
        self.assertEqual(telemetry["result_count"], 2)
        self.assertNotIn("fc-secret-value", str(telemetry))

    def test_private_self_hosted_firecrawl_can_be_explicitly_used_without_auth(self):
        payload = {
            "success": True,
            "data": {
                "web": [
                    {
                        "title": "Private Firecrawl result",
                        "description": "A source returned by the internal candidate service.",
                        "url": "https://publisher.example.org/current-signal",
                        "metadata": {"publishedTime": self.now.isoformat()},
                    }
                ]
            },
        }
        client = ConfiguredTrendSearchClient(
            env={
                "FIRECRAWL_BASE_URL": "http://firecrawl:3002/v2",
                "FIRECRAWL_ALLOW_UNAUTHENTICATED_SELF_HOSTED": "true",
            },
            timeout=3,
        )
        with patch(
            "marketing_machine.http_safety._CREDENTIAL_SAFE_OPENER.open",
            return_value=FakeHTTPResponse(payload),
        ) as urlopen:
            results = client.search(
                "QA release risk latest",
                platform="web",
                lookback_start=self.now - timedelta(days=7),
                now=self.now,
                limit=5,
            )

        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://firecrawl:3002/v2/search")
        self.assertIsNone(request.get_header("Authorization"))
        self.assertEqual(len(results), 1)
        self.assertIn("firecrawl_v2", client.available_sources())

    def test_public_firecrawl_without_key_stays_unavailable_even_with_no_auth_opt_in(self):
        for endpoint in (
            "https://api.firecrawl.dev/v2",
            "https://firecrawl.vendor.example.com/v2",
            "https://user:password@firecrawl:3002/v2",
        ):
            client = ConfiguredTrendSearchClient(
                env={
                    "FIRECRAWL_BASE_URL": endpoint,
                    "FIRECRAWL_ALLOW_UNAUTHENTICATED_SELF_HOSTED": "true",
                }
            )
            self.assertNotIn("firecrawl_v2", client.available_sources())

    def test_searxng_uses_structured_dates_but_never_title_or_snippet_text(self):
        payload = {
            "results": [
                {
                    "title": "QA Trend A - vor 4 Tagen",
                    "content": "vor 4 Tagen ... Aktuelle Testautomatisierung.",
                    "url": "https://publisher-one.com/qa",
                    "publishedDate": None,
                    "engine": "google cse",
                },
                {
                    "title": "QA Trend B",
                    "content": "02.07.2026 ... Zweite unabhängige Quelle.",
                    "url": "https://publisher-two.net/qa",
                    "publishedDate": None,
                    "engine": "google cse",
                },
                {
                    "title": "QA Trend C",
                    "content": "A page with explicit adapter metadata.",
                    "url": "https://publisher-three.org/qa",
                    "publishedDate": None,
                    "metadata": {"publishedDate": "2 days ago"},
                    "engine": "google cse",
                },
            ]
        }
        client = ConfiguredTrendSearchClient(
            env={"SEARXNG_BASE_URL": "https://search.example.com"},
            timeout=3,
        )
        with patch(
            "marketing_machine.http_safety._CREDENTIAL_SAFE_OPENER.open",
            return_value=FakeHTTPResponse(payload),
        ):
            results = client.search(
                "Software Testing QA trends 2026",
                platform="web",
                lookback_start=self.now - timedelta(days=30),
                now=self.now,
                limit=5,
            )

        self.assertEqual(len(results), 3)
        by_title = {result.title: result for result in results}
        self.assertEqual(by_title["QA Trend A - vor 4 Tagen"].published_at, "")
        self.assertEqual(by_title["QA Trend B"].published_at, "")
        self.assertTrue(by_title["QA Trend C"].published_at.startswith("2026-07"))
        self.assertEqual(client.telemetry()[0]["status"], "success")

    def test_campaign_search_query_is_broad_and_uses_current_year(self):
        class CapturingSearchClient(EmptyTrendSearchClient):
            def __init__(self):
                self.queries = []

            def search(self, query, *, platform, lookback_start, now, limit=5):
                self.queries.append(query)
                return []

        client = CapturingSearchClient()
        run_trend_research(
            self.root,
            payload={"campaign_ids": ["kampagne_1_consulting_qa"], "platforms": ["web"]},
            search_client=client,
            now=self.now,
        )

        self.assertEqual(len(client.queries), 1)
        self.assertNotIn('"', client.queries[0])
        self.assertIn("2026", client.queries[0])
        self.assertIn("Software Testing", client.queries[0])

    def test_adapter_errors_are_visible_and_secret_safe(self):
        client = ConfiguredTrendSearchClient(
            env={
                "FIRECRAWL_BASE_URL": "https://firecrawl.internal/v2",
                "FIRECRAWL_API_KEY": "fc-secret-value",
            }
        )
        with patch(
            "marketing_machine.http_safety._CREDENTIAL_SAFE_OPENER.open",
            side_effect=urllib.error.URLError("connection refused"),
        ):
            results = client.search(
                "QA risk",
                platform="web",
                lookback_start=self.now - timedelta(days=10),
                now=self.now,
            )

        self.assertEqual(results, [])
        telemetry = client.telemetry()[0]
        self.assertEqual(telemetry["status"], "error")
        self.assertTrue(telemetry["errors"])
        self.assertIn("connection refused", str(telemetry))
        self.assertNotIn("fc-secret-value", str(telemetry))

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
