import multiprocessing
import json
import sys
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marketing_machine.storage import JsonStore, StateRevisionConflict
from marketing_machine.ui import render_marketing_console


def _concurrent_cas_writer(root: str, marker: str, ready, start, results) -> None:
    store = JsonStore(Path(root))
    state = store.load_state("cas-content")
    revision = store.state_revision(state)
    state["marker"] = marker
    ready.put(marker)
    if not start.wait(10):
        results.put("timeout")
        return
    try:
        store.save_state(state, expected_revision=revision)
        results.put("saved")
    except StateRevisionConflict:
        results.put("conflict")


class UiAndStorageTests(unittest.TestCase):
    def test_marketing_console_contains_end_user_forms(self):
        html = render_marketing_console()
        static_root = Path(__file__).resolve().parents[1] / "src" / "marketing_machine" / "static"
        javascript = (static_root / "console.js").read_text(encoding="utf-8")

        self.assertIn("WAMOCON Marketing-Konsole", html)
        self.assertNotIn('id="uiLanguage"', html)
        self.assertIn("Ihre Kampagnen", html)
        self.assertIn("Content Studio", html)
        self.assertIn("MENSCHLICHE FREIGABE", html)
        self.assertIn("Ablauf / Kernpunkte", javascript)
        self.assertIn("Reel-Produktionsplan", javascript)
        self.assertIn("Carousel-Slides", javascript)
        self.assertIn("people_consent_and_real_assets_required", javascript)
        self.assertIn("Shotlist", javascript)
        self.assertIn("Caption", javascript)
        self.assertIn("Referenzen", javascript)
        self.assertIn("/campaigns", javascript)
        self.assertIn("/workflows/approve-content", javascript)
        self.assertIn("/workflows/trend-research", javascript)
        self.assertIn("/workflows/reel-concepts", javascript)
        self.assertIn("Vier belegte redaktionelle Richtungen sind bereit", javascript)
        self.assertIn("erst danach erstellt die lokale KI den vollständigen Entwurf", javascript)
        self.assertNotIn("Varianten wurden mit ${generation.model", javascript)
        self.assertNotIn(
            "citationsOf(concept).length ? citationsOf(concept) : citationsOf(state.selectedTrend",
            javascript,
        )
        self.assertNotIn("marketing-workflow-hero.png", html)
        self.assertNotIn('<pre id="intakeResult"', html)
        self.assertIn("const reviewQueue = reviewAttentionItems(state.recent);", javascript)
        self.assertIn('const handoffQueue = currentItems.filter((item) => item.status === "ready_to_schedule");', javascript)
        self.assertIn('$("navReviewCount").textContent = String(queue.length);', javascript)
        self.assertIn('$("reviewCount").textContent = String(queue.length);', javascript)
        self.assertIn('id="brandScore" min="0" max="100" step="1" required', javascript)
        self.assertNotIn('id="brandScore" min="0" max="100" value="90"', javascript)
        self.assertIn('if (!brandScoreInput || !Number.isInteger(brandScore)', javascript)

    def test_marketing_console_script_is_parseable_when_node_is_available(self):
        if not shutil.which("node"):
            self.skipTest("node is not available")

        render_marketing_console()
        script_path = Path(__file__).resolve().parents[1] / "src" / "marketing_machine" / "static" / "console.js"
        result = subprocess.run(
            ["node", "--check", str(script_path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_console_does_not_resolve_internal_evidence_as_a_public_url(self):
        script = (
            Path(__file__).resolve().parents[1] / "src" / "marketing_machine" / "static" / "console.js"
        ).read_text(encoding="utf-8")
        self.assertIn('if (!/^https?:\\/\\//i.test(raw)) return "";', script)
        self.assertNotIn("new URL(String(value || \"\"), window.location.origin)", script)
        self.assertIn('".internal", ".intranet"', script)
        self.assertIn("hasUserinfo", script)

    def test_console_selects_trends_only_from_server_computed_current_eligibility(self):
        script = (
            Path(__file__).resolve().parents[1] / "src" / "marketing_machine" / "static" / "console.js"
        ).read_text(encoding="utf-8")

        self.assertIn("return trend?.verification?.eligible_for_content === true;", script)
        self.assertNotIn('verification.status === "verified_recent"', script)

    def test_weekly_plan_ui_requires_research_and_content_capabilities(self):
        script = (
            Path(__file__).resolve().parents[1] / "src" / "marketing_machine" / "static" / "console.js"
        ).read_text(encoding="utf-8")

        self.assertIn('const weeklyPlanReady = researchReady && contentCanRun;', script)
        self.assertIn('$("createWeeklyPlan").disabled = !weeklyPlanReady;', script)
        self.assertNotIn('$("createWeeklyPlan").disabled = !contentReady;', script)
        self.assertIn('action === "create"', script)
        self.assertIn('? !researchCanRun', script)
        self.assertIn('? !contentCanRun', script)

    def test_limited_results_are_labeled_as_view_samples_not_totals(self):
        script = (
            Path(__file__).resolve().parents[1] / "src" / "marketing_machine" / "static" / "console.js"
        ).read_text(encoding="utf-8")

        self.assertIn('request("/workflows/performance?limit=20")', script)
        self.assertIn('request("/workflows/leads?limit=20")', script)
        self.assertIn('request("/workflows/outbox?limit=20")', script)
        self.assertIn('"letzte bis zu 20 Einträge"', script)
        self.assertIn('"bis zu 100 aktuelle Inhalte · bereit / geplant / live"', script)
        self.assertIn('"letzte bis zu 20 Einträge · alle Messfenster"', script)
        self.assertIn('leads.unavailable ? "Nicht geladen" : qualified', script)
        self.assertIn('performance.unavailable ? "Nicht geladen" : perfItems.length', script)
        self.assertNotIn('`${leadItems.length} gesamt`', script)

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
        self.assertEqual(items[0]["state_revision"], 1)

    def test_store_reads_complete_history_in_pages_while_browser_slice_stays_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonStore(Path(tmp))
            for number in range(105):
                store.save_state(
                    {
                        "brief": {
                            "id": f"k1-history-{number:03d}",
                            "campaign_id": "k1",
                            "campaign": "K1 QA",
                            "status": "blocked",
                        }
                    },
                    expected_revision=None,
                )

            pages = list(store.iter_state_pages(page_size=32, include_demo=False))
            browser_slice = store.list_states(limit=100, include_demo=False)
            complete = store.list_all_states(include_demo=False, page_size=32)

        self.assertEqual([len(page) for page in pages], [32, 32, 32, 9])
        self.assertEqual(len(browser_slice), 100)
        self.assertEqual(len(complete), 105)
        self.assertEqual(
            {item["content_id"] for item in complete},
            {f"k1-history-{number:03d}" for number in range(105)},
        )

    def test_state_summary_exposes_safe_quality_and_only_exact_provider_media_binding(self):
        valid_sha256 = "a" * 64
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonStore(Path(tmp))
            store.save_state(
                {
                    "brief": {
                        "id": "k1-quality-media",
                        "campaign_id": "k1",
                        "campaign": "K1 QA",
                        "channel": "Instagram",
                        "format": "Reel",
                        "status": "ready_to_schedule",
                        "quality_evaluation": {
                            "release_ready": True,
                            "decision": "pass",
                            "overall_score": 96.5,
                            "evaluated_at": "2026-07-13T09:00:00+00:00",
                            "hard_blockers": [],
                            "dimensions": {"private": "must not be projected"},
                        },
                    },
                    "approved_media_assets": [
                        {
                            "asset_id": "verified-video",
                            "status": "approved",
                            "media_type": "video",
                            "postiz_media_id": "postiz-video-1",
                            "postiz_path": "https://uploads.postiz.example/video.mp4",
                            "sha256": valid_sha256,
                            "provider_verified": True,
                            "provider_verification_method": "postiz_public_url_sha256",
                            "provider_sha256": valid_sha256,
                            "provider_path": "https://uploads.postiz.example/video.mp4",
                        },
                        {
                            "asset_id": "path-mismatch",
                            "status": "approved",
                            "media_type": "video",
                            "postiz_media_id": "postiz-video-2",
                            "postiz_path": "https://uploads.postiz.example/approved.mp4",
                            "sha256": "b" * 64,
                            "provider_verified": True,
                            "provider_verification_method": "postiz_public_url_sha256",
                            "provider_sha256": "b" * 64,
                            "provider_path": "https://uploads.postiz.example/different.mp4",
                        },
                    ],
                },
                expected_revision=None,
            )

            summary = store.list_states(limit=1)[0]

        self.assertEqual(
            summary["quality_evaluation"],
            {
                "release_ready": True,
                "decision": "pass",
                "overall_score": 96.5,
                "evaluated_at": "2026-07-13T09:00:00+00:00",
                "blocker_codes": [],
                "blocker_count": 0,
            },
        )
        self.assertNotIn("dimensions", summary["quality_evaluation"])
        self.assertEqual(summary["approved_media_count"], 2)
        self.assertEqual(summary["provider_verified_media_count"], 1)
        self.assertTrue(summary["postiz_media_ready"])

    def test_postiz_media_summary_fails_closed_on_checksum_or_path_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonStore(Path(tmp))
            store.save_state(
                {
                    "brief": {
                        "id": "k1-unbound-media",
                        "campaign_id": "k1",
                        "campaign": "K1 QA",
                        "channel": "Instagram",
                        "format": "Reel",
                        "quality_evaluation": {
                            "release_ready": False,
                            "decision": "fail",
                            "overall_score": 70.0,
                            "evaluated_at": "2026-07-13T10:00:00+00:00",
                            "hard_blockers": [
                                {
                                    "code": "missing_approved_claim",
                                    "message": "private evaluator explanation",
                                }
                            ],
                        },
                    },
                    "approved_media_assets": [
                        {
                            "status": "approved",
                            "media_type": "video",
                            "postiz_media_id": "postiz-video-1",
                            "postiz_path": "https://uploads.postiz.example/video.mp4",
                            "sha256": "a" * 64,
                            "provider_verified": True,
                            "provider_verification_method": "postiz_public_url_sha256",
                            "provider_sha256": "b" * 64,
                            "provider_path": "https://uploads.postiz.example/video.mp4",
                        }
                    ],
                },
                expected_revision=None,
            )

            summary = store.list_states(limit=1)[0]

        self.assertEqual(summary["provider_verified_media_count"], 0)
        self.assertFalse(summary["postiz_media_ready"])
        self.assertEqual(
            summary["quality_evaluation"],
            {
                "release_ready": False,
                "decision": "fail",
                "overall_score": 70.0,
                "evaluated_at": "2026-07-13T10:00:00+00:00",
                "blocker_codes": ["missing_approved_claim"],
                "blocker_count": 1,
            },
        )
        self.assertNotIn("private evaluator explanation", str(summary))

    def test_store_projects_only_safe_immutable_revision_relationships(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonStore(Path(tmp))

            def save(content_id: str, status: str, source: dict | None = None) -> None:
                payload = {
                    "brief": {
                        "id": content_id,
                        "campaign_id": "k1",
                        "campaign": "K1 QA",
                        "channel": "LinkedIn",
                        "format": "Post",
                        "status": status,
                        "generation": {"status": "ai_generated"},
                    },
                    "next_step": "human_review" if status == "needs_human_review" else "regenerate",
                    "requires_human_review": status == "needs_human_review",
                }
                if source is not None:
                    payload["revision_source"] = source
                store.save_state(payload, expected_revision=None)

            save("content-original", "revision_requested")
            save(
                "content-revision-one",
                "blocked",
                {
                    "content_id": "content-original",
                    "revision": 1,
                    "authenticated_actor": "Private Operator",
                    "authenticated_request_fingerprint": "a" * 64,
                },
            )
            save(
                "content-revision-two",
                "needs_human_review",
                {"content_id": "content-revision-one", "revision": 1},
            )
            save("standalone-blocked", "blocked")

            summaries = {item["content_id"]: item for item in store.list_states(limit=10)}

        self.assertEqual(summaries["content-original"]["revision_source"], {})
        self.assertEqual(
            summaries["content-revision-one"]["revision_source"],
            {"content_id": "content-original", "revision": 1},
        )
        self.assertEqual(
            summaries["content-revision-two"]["revision_source"],
            {"content_id": "content-revision-one", "revision": 1},
        )
        self.assertEqual(summaries["standalone-blocked"]["revision_source"], {})
        self.assertTrue(all(item["state_revision"] == 1 for item in summaries.values()))
        self.assertNotIn(
            "authenticated_actor",
            summaries["content-revision-one"]["revision_source"],
        )
        self.assertNotIn(
            "authenticated_request_fingerprint",
            summaries["content-revision-one"]["revision_source"],
        )

    def test_console_keeps_only_latest_actionable_revision_in_business_queues(self):
        if not shutil.which("node"):
            self.skipTest("node is not available")

        script = (
            Path(__file__).resolve().parents[1]
            / "src"
            / "marketing_machine"
            / "static"
            / "console.js"
        ).read_text(encoding="utf-8")
        helper_start = script.index("  function currentContentVersions(items) {")
        helper_end = script.index("\n  function reviewAttentionItems(items) {", helper_start)
        helper = script[helper_start:helper_end]
        records = [
            {
                "content_id": "content-original",
                "campaign_id": "k1",
                "state_revision": 1,
                "status": "revision_requested",
                "revision_source": {},
            },
            {
                "content_id": "content-revision-one",
                "campaign_id": "k1",
                "state_revision": 1,
                "status": "blocked",
                "revision_source": {"content_id": "content-original", "revision": 1},
            },
            {
                "content_id": "content-revision-two",
                "campaign_id": "k1",
                "state_revision": 1,
                "status": "needs_human_review",
                "revision_source": {"content_id": "content-revision-one", "revision": 1},
            },
            {
                "content_id": "standalone-blocked",
                "campaign_id": "k1",
                "state_revision": 1,
                "status": "blocked",
                "revision_source": {},
            },
        ]
        probe = (
            f"{helper}\n"
            f"const rows = {json.dumps(records)};\n"
            "process.stdout.write(JSON.stringify(currentContentVersions(rows).map((item) => item.content_id)));"
        )
        result = subprocess.run(
            ["node", "-e", probe],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            ["content-revision-two", "standalone-blocked"],
        )
        self.assertIn(
            "const visible = currentContentVersions(state.recent).slice(0, 6);",
            script,
        )
        self.assertIn(
            "const handoffQueue = currentItems.filter((item) => item.status === \"ready_to_schedule\");",
            script,
        )

    def test_store_hides_unverified_placeholder_content_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonStore(Path(tmp))
            store.save_state(
                {
                    "brief": {
                        "id": "reel-concept-placeholder-v1",
                        "campaign": "K1 QA",
                        "persona": "IT-Leiter Thomas",
                        "channel": "Instagram",
                        "status": "needs_human_review",
                        "trend_summary": "Campaign-only signal: K1 QA",
                        "trend_sources": ["Kampagnen/kampagne_1_consulting_qa.json"],
                    },
                    "next_step": "human_review",
                    "requires_human_review": True,
                    "scheduler_payload": {},
                }
            )

            self.assertEqual(store.list_states(), [])
            self.assertEqual(len(store.list_states(include_demo=True)), 1)

    def test_store_exposes_request_id_in_trend_run_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonStore(Path(tmp))
            store.save_trend_run(
                {
                    "id": "trend-request-n8n",
                    "request_id": "174306",
                    "status": "verified_sources",
                    "run_started_at": "2026-07-10T12:00:00+00:00",
                    "campaigns": [],
                    "successful_source_adapters": ["searxng"],
                }
            )

            summary = store.list_trend_runs(limit=1)[0]

        self.assertEqual(summary["request_id"], "174306")

    def test_store_rejects_path_traversal_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonStore(Path(tmp))
            with self.assertRaises(ValueError):
                store.save_state({"brief": {"id": "../escape"}})

    def test_state_compare_and_swap_allows_only_one_cross_process_writer(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonStore(Path(tmp))
            initial = {"brief": {"id": "cas-content", "status": "drafting"}}
            store.save_state(initial, expected_revision=None)
            self.assertEqual(store.state_revision(initial), 1)

            context = multiprocessing.get_context("spawn")
            ready = context.Queue()
            start = context.Event()
            results = context.Queue()
            processes = [
                context.Process(
                    target=_concurrent_cas_writer,
                    args=(tmp, marker, ready, start, results),
                )
                for marker in ("one", "two")
            ]
            for process in processes:
                process.start()
            self.assertEqual({ready.get(timeout=10), ready.get(timeout=10)}, {"one", "two"})
            start.set()
            outcomes = sorted(results.get(timeout=15) for _ in processes)
            for process in processes:
                process.join(timeout=15)
                self.assertEqual(process.exitcode, 0)

            final = store.load_state("cas-content")
            self.assertEqual(outcomes, ["conflict", "saved"])
            self.assertEqual(store.state_revision(final), 2)
            self.assertIn(final["marker"], {"one", "two"})

    def test_cleanup_test_data_is_report_only_and_never_rewrites_live_records(self):
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
            store.append_lead(
                {
                    "lead": {
                        "id": "real-lead-1",
                        "source_content_id": "k1-real-campaign",
                        "company": "Beispiel GmbH",
                    }
                }
            )
            store.append_outbox({"id": "route-mock", "source_id": "mock-old-1", "target": "postiz"})
            store.append_outbox({"id": "route-real", "source_id": "k1-real-campaign", "target": "postiz"})

            dry_run = store.cleanup_test_data(dry_run=True)
            summary = store.cleanup_test_data()
            with self.assertRaises(RuntimeError):
                store.cleanup_test_data(dry_run=False)
            items = store.list_states(limit=10)
            performance = store.list_performance(limit=10)
            leads = store.list_leads(limit=10)
            outbox = store.list_outbox(limit=10)
            all_performance = store.list_performance(limit=10, include_demo=True)
            all_leads = store.list_leads(limit=10, include_demo=True)
            all_outbox = store.list_outbox(limit=10, include_demo=True)

            self.assertEqual(dry_run["states_deleted"], 2)
            self.assertEqual(summary["states_deleted"], 2)
            self.assertEqual(summary["events_removed"], 1)
            self.assertEqual(summary["performance_removed"], 1)
            self.assertEqual(summary["leads_removed"], 1)
            self.assertEqual(summary["outbox_removed"], 1)
            self.assertEqual([item["content_id"] for item in items], ["k1-real-campaign"])
            self.assertEqual(
                [item["content_id"] for item in performance], ["k1-real-campaign"]
            )
            self.assertTrue((Path(tmp) / "states" / "mock-old-1.json").exists())
            self.assertTrue((Path(tmp) / "states" / "smoke-old-1.json").exists())
            self.assertEqual([item["id"] for item in leads], ["real-lead-1"])
            self.assertEqual(leads[0]["company"], "Beispiel GmbH")
            self.assertEqual([item["id"] for item in outbox], ["route-real"])
            self.assertEqual(
                {item["content_id"] for item in all_performance},
                {"smoke-old-1", "k1-real-campaign"},
            )
            self.assertEqual(
                {item["id"] for item in all_leads},
                {"mock-lead-1", "real-lead-1"},
            )
            self.assertEqual(
                {item["id"] for item in all_outbox}, {"route-mock", "route-real"}
            )
            self.assertIn("k1-real-campaign", (Path(tmp) / "events" / "approval.jsonl").read_text(encoding="utf-8"))
            self.assertIn("mock-old-1", (Path(tmp) / "events" / "approval.jsonl").read_text(encoding="utf-8"))

    def test_business_lists_keep_legitimate_records_when_source_state_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonStore(Path(tmp))
            store.append_performance(
                {"record": {"content_id": "k2-live-migrated"}, "action": "continue"}
            )
            store.append_lead(
                {
                    "lead": {
                        "id": "lead-2026-001",
                        "source_content_id": "k2-live-migrated",
                        "company": "Kunde AG",
                    }
                }
            )
            store.append_outbox(
                {
                    "id": "route-2026-001",
                    "source_id": "k2-live-migrated",
                    "target": "postiz",
                }
            )

            self.assertEqual(len(store.list_performance()), 1)
            self.assertEqual(store.list_leads()[0]["company"], "Kunde AG")
            self.assertEqual(len(store.list_outbox()), 1)

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

    def test_business_lists_project_campaign_from_exact_content_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonStore(Path(tmp))
            store.save_state(
                {
                    "brief": {
                        "id": "content-k4-1",
                        "campaign": "K4 · Digitales Schulungszentrum",
                    }
                }
            )
            store.append_performance(
                {
                    "record": {
                        "content_id": "content-k4-1",
                        "review_window": "72h",
                    },
                    "action": "iterate",
                }
            )
            store.append_outbox(
                {
                    "id": "route-k4-1",
                    "kind": "scheduler_draft",
                    "source_id": "content-k4-1",
                    "target": "postiz",
                }
            )

            performance = store.list_performance(limit=5)
            outbox = store.list_outbox(limit=5)

        self.assertEqual(performance[0]["campaign"], "K4 · Digitales Schulungszentrum")
        self.assertEqual(outbox[0]["campaign"], "K4 · Digitales Schulungszentrum")

    def test_business_lists_do_not_guess_campaign_for_missing_or_lead_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonStore(Path(tmp))
            store.save_state(
                {
                    "brief": {
                        "id": "shared-source-1",
                        "campaign": "K2 · Connected Operations",
                    }
                }
            )
            store.append_performance(
                {
                    "record": {
                        "content_id": "missing-content-1",
                        "review_window": "7d",
                    },
                    "action": "wait_for_more_data",
                }
            )
            store.append_outbox(
                {
                    "id": "route-lead-1",
                    "kind": "lead",
                    "source_id": "shared-source-1",
                    "target": "crm",
                }
            )

            performance = store.list_performance(limit=5)
            outbox = store.list_outbox(limit=5)

        self.assertEqual(performance[0]["campaign"], "")
        self.assertEqual(outbox[0]["campaign"], "")


if __name__ == "__main__":
    unittest.main()
