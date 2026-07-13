from concurrent.futures import ThreadPoolExecutor
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marketing_machine.api import (
    analytics_review,
    campaign_detail,
    create_content,
    integrations_status,
    list_campaigns,
    recorded_n8n_execution,
    revise_content,
    weekly_planning,
)
from marketing_machine.schemas import ContentBrief, ContentStatus
from marketing_machine.storage import JsonStore


class ApiLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.runtime_env = patch.dict(
            os.environ,
            {
                "MARKETING_MACHINE_INSTANCE_MODE": "development",
                "MARKETING_MACHINE_ACTOR_AUTH_MODE": "local-optional",
            },
            clear=False,
        )
        self.runtime_env.start()

    def tearDown(self):
        self.runtime_env.stop()

    @staticmethod
    def _existing_state(content_id: str) -> dict:
        return {
            "brief": {
                "id": content_id,
                "campaign_id": "k1",
                "campaign": "K1 QA",
                "status": "published",
            },
            "next_step": "analytics",
            "requires_human_review": False,
            "lifecycle": {
                "provider": "postiz",
                "provider_status": "published",
                "provider_post_id": "postiz-test-post",
                "published_at": "2020-01-01T00:00:00+00:00",
                "source_ref": "postiz-test-snapshot",
            },
        }

    def test_create_content_rejects_existing_id_without_generating_or_overwriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonStore(Path(tmp))
            store.save_state(self._existing_state("existing-content"))
            original = store.load_state("existing-content")
            with patch.dict(os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}), patch(
                "marketing_machine.api.create_state_for_brief"
            ) as generate:
                with self.assertRaises(HTTPException) as caught:
                    create_content(
                        {"id": "existing-content", "campaign_id": "k1", "content_mode": "evergreen"}
                    )

            self.assertEqual(caught.exception.status_code, 409)
            generate.assert_not_called()
            self.assertEqual(store.load_state("existing-content"), original)

    def test_create_content_exact_retry_is_idempotent(self):
        payload = {"id": "retry-safe-content", "campaign_id": "k1", "content_mode": "evergreen"}
        generated = {
            "brief": {"id": "retry-safe-content", "campaign_id": "k1", "status": "needs_human_review"},
            "next_step": "human_review",
            "requires_human_review": True,
        }
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}
        ), patch("marketing_machine.api.create_state_for_brief", return_value=generated) as generate:
            first = create_content(payload)
            second = create_content(payload)

        self.assertFalse(first.get("idempotent", False))
        self.assertTrue(second["idempotent"])
        self.assertEqual(generate.call_count, 1)

    def test_concurrent_create_content_retry_runs_generation_once(self):
        payload = {
            "id": "concurrent-retry-content",
            "campaign_id": "k1",
            "content_mode": "evergreen",
        }
        calls = 0
        calls_lock = threading.Lock()

        def generate(_brief):
            nonlocal calls
            with calls_lock:
                calls += 1
            time.sleep(0.1)
            return {
                "brief": {
                    "id": "concurrent-retry-content",
                    "campaign_id": "k1",
                    "status": "needs_human_review",
                },
                "next_step": "human_review",
                "requires_human_review": True,
            }

        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}
        ), patch("marketing_machine.api.create_state_for_brief", side_effect=generate):
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda _index: create_content(dict(payload)), range(2)))

        self.assertEqual(calls, 1)
        self.assertEqual(sorted(bool(item.get("idempotent", False)) for item in results), [False, True])

    def test_concurrent_weekly_planning_generates_each_content_id_once(self):
        brief = ContentBrief(
            id="k1-2026w28-expert-post",
            campaign_id="k1",
            campaign="K1 QA",
            persona="IT-Leiter",
            channel="LinkedIn",
            format="expert_post",
            objective="QA erklären",
            cta="Audit anfragen",
            proof_sources=["Kampagnen/kampagne_1_consulting_qa.json"],
            utm={"utm_source": "linkedin", "utm_medium": "organic", "utm_campaign": "k1"},
            hypothesis="Qualifizierte Reaktionen",
            test_variable="hook",
        )
        calls = 0
        calls_lock = threading.Lock()

        def generate(_brief):
            nonlocal calls
            with calls_lock:
                calls += 1
            time.sleep(0.1)
            return {
                "brief": {
                    "id": brief.id,
                    "campaign_id": "k1",
                    "status": "needs_human_review",
                    "generation": {"status": "ai_generated"},
                },
                "next_step": "human_review",
                "requires_human_review": True,
            }

        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}
        ), patch("marketing_machine.api.default_briefs", return_value=[brief]), patch(
            "marketing_machine.api.full_trend_runs", return_value=[]
        ), patch(
            "marketing_machine.api._weekly_briefs_with_verified_sources",
            return_value=([brief], []),
        ), patch(
            "marketing_machine.api.create_state_for_brief", side_effect=generate
        ):
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda _index: weekly_planning({}), range(2)))

        self.assertEqual(calls, 1)
        self.assertEqual(
            sorted(item["created"][0]["created_now"] for item in results),
            [False, True],
        )

    def test_analytics_rejects_negative_and_malformed_metrics_as_422(self):
        invalid_metrics = {
            "impressions": -1,
            "clicks": "not-a-number",
            "leads": 1.5,
            "booked_calls": True,
            "pipeline_value_eur": "NaN",
        }
        base_payload = {
            "content_id": "real-content",
            "review_window": "72h",
            "source_system": "manual",
            "source_ref": "analytics-invalid-metric-fixture.csv",
            "period_start": "2020-01-01T00:00:00+00:00",
            "period_end": "2020-01-04T00:00:00+00:00",
            "retrieved_at": "2020-01-04T01:00:00+00:00",
            "operator": "QA Operator",
            "attribution_rule": "utm_last_touch_72h",
            "evidence": [
                {
                    "system": "manual",
                    "ref": "analytics-invalid-metric-fixture.csv",
                    "retrieved_at": "2020-01-04T01:00:00+00:00",
                    "sha256": "e" * 64,
                    "metric_fields": [
                        "impressions",
                        "clicks",
                        "leads",
                        "booked_calls",
                        "pipeline_value_eur",
                    ],
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            JsonStore(Path(tmp)).save_state(self._existing_state("real-content"))
            with patch.dict(os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}):
                for field, value in invalid_metrics.items():
                    with self.subTest(field=field, value=value), self.assertRaises(HTTPException) as caught:
                        analytics_review(
                            {
                                **base_payload,
                                field: value,
                            }
                        )
                    self.assertEqual(caught.exception.status_code, 422)
                    self.assertIn(field, str(caught.exception.detail))

    def test_revision_creates_new_version_without_overwriting_review_history(self):
        brief = ContentBrief(
            id="k1-reviewed",
            campaign_id="k1",
            campaign="K1 QA",
            persona="IT-Leiter",
            channel="LinkedIn",
            format="expert_post",
            objective="QA-Risiken erklären",
            cta="Audit anfragen",
            proof_sources=["Kampagnen/kampagne_1_consulting_qa.json"],
            utm={"utm_source": "linkedin", "utm_medium": "organic", "utm_campaign": "k1"},
            hypothesis="Qualifizierte Reaktionen",
            test_variable="hook",
            status=ContentStatus.REVISION_REQUESTED,
            public_copy="Original",
        )
        original_state = {
            "brief": brief.to_dict(),
            "approval": {"reviewer": "M. Beispiel", "decision": "major_revision"},
            "errors": ["human review did not approve publication"],
            "next_step": "revision",
            "requires_human_review": False,
            "evidence_records": [],
            "scheduler_payload": {},
        }
        revised_state = {
            "brief": {**brief.to_dict(), "id": "k1-reviewed-r1", "status": "needs_human_review"},
            "approval": None,
            "errors": [],
            "next_step": "human_review",
            "requires_human_review": True,
            "evidence_records": [],
            "scheduler_payload": {},
        }
        with tempfile.TemporaryDirectory() as tmp:
            store = JsonStore(Path(tmp))
            store.save_state(original_state)
            with patch.dict(os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}), patch(
                "marketing_machine.api.create_state_for_brief", return_value=revised_state
            ) as generate:
                result = revise_content(
                    {
                        "content_id": "k1-reviewed",
                        "editor": "M. Beispiel",
                        "revision_notes": "Hook präzisieren",
                    }
                )
                retry = revise_content(
                    {
                        "content_id": "k1-reviewed",
                        "editor": "M. Beispiel",
                        "revision_notes": "Hook präzisieren",
                    }
                )

            self.assertEqual(result["content_id"], "k1-reviewed-r1")
            self.assertTrue(retry["idempotent"])
            self.assertEqual(retry["content_id"], "k1-reviewed-r1")
            self.assertEqual(generate.call_count, 1)
            self.assertEqual(store.load_state("k1-reviewed"), original_state)
            self.assertEqual(store.load_state("k1-reviewed-r1")["brief"]["status"], "needs_human_review")

    def test_different_revision_request_points_to_existing_successor_instead_of_branching(self):
        brief = ContentBrief(
            id="k1-one-successor",
            campaign_id="k1",
            campaign="K1 QA",
            persona="IT-Leiter",
            channel="LinkedIn",
            format="expert_post",
            objective="QA-Risiken erklaeren",
            cta="Audit anfragen",
            proof_sources=["Kampagnen/kampagne_1_consulting_qa.json"],
            utm={"utm_source": "linkedin", "utm_medium": "organic", "utm_campaign": "k1"},
            hypothesis="Qualifizierte Reaktionen",
            test_variable="hook",
            status=ContentStatus.REVISION_REQUESTED,
            public_copy="Original",
        )
        original_state = {
            "brief": brief.to_dict(),
            "next_step": "revision",
            "requires_human_review": False,
        }

        def generate(revised_brief: ContentBrief) -> dict:
            return {
                "brief": {
                    **revised_brief.to_dict(),
                    "status": ContentStatus.NEEDS_HUMAN_REVIEW.value,
                },
                "next_step": "human_review",
                "requires_human_review": True,
            }

        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}
        ), patch("marketing_machine.api.create_state_for_brief", side_effect=generate) as generator:
            store = JsonStore(Path(tmp))
            store.save_state(original_state, expected_revision=None)
            first = revise_content(
                {
                    "content_id": brief.id,
                    "editor": "Operator A",
                    "revision_notes": "Use a clearer business hook",
                }
            )
            with self.assertRaises(HTTPException) as caught:
                revise_content(
                    {
                        "content_id": brief.id,
                        "editor": "Operator B",
                        "revision_notes": "Replace the hook with a different angle",
                    }
                )

            stored_ids = {item["content_id"] for item in store.list_all_states(include_demo=True)}
            audit_lines = (Path(tmp) / "events" / "revision.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()

        self.assertEqual(first["content_id"], "k1-one-successor-r1")
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(caught.exception.detail["code"], "revision_successor_exists")
        self.assertEqual(
            caught.exception.detail["existing_content_id"],
            "k1-one-successor-r1",
        )
        self.assertEqual(stored_ids, {"k1-one-successor", "k1-one-successor-r1"})
        self.assertEqual(generator.call_count, 1)
        self.assertEqual(len(audit_lines), 1)

    def test_concurrent_revision_operators_create_only_one_successor(self):
        brief = ContentBrief(
            id="k1-concurrent-successor",
            campaign_id="k1",
            campaign="K1 QA",
            persona="IT-Leiter",
            channel="LinkedIn",
            format="expert_post",
            objective="QA-Risiken erklaeren",
            cta="Audit anfragen",
            proof_sources=["Kampagnen/kampagne_1_consulting_qa.json"],
            utm={"utm_source": "linkedin", "utm_medium": "organic", "utm_campaign": "k1"},
            hypothesis="Qualifizierte Reaktionen",
            test_variable="hook",
            status=ContentStatus.REVISION_REQUESTED,
            public_copy="Original",
        )
        calls = 0
        calls_lock = threading.Lock()

        def generate(revised_brief: ContentBrief) -> dict:
            nonlocal calls
            with calls_lock:
                calls += 1
            time.sleep(0.1)
            return {
                "brief": {
                    **revised_brief.to_dict(),
                    "status": ContentStatus.NEEDS_HUMAN_REVIEW.value,
                },
                "next_step": "human_review",
                "requires_human_review": True,
            }

        requests = [
            {
                "content_id": brief.id,
                "editor": "Operator A",
                "revision_notes": "Use a business outcome hook",
            },
            {
                "content_id": brief.id,
                "editor": "Operator B",
                "revision_notes": "Use a risk reduction hook",
            },
        ]

        def invoke(request: dict) -> tuple[str, object]:
            try:
                return "created", revise_content(request)
            except HTTPException as exc:
                return "conflict", exc

        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}
        ), patch("marketing_machine.api.create_state_for_brief", side_effect=generate):
            store = JsonStore(Path(tmp))
            store.save_state(
                {
                    "brief": brief.to_dict(),
                    "next_step": "revision",
                    "requires_human_review": False,
                },
                expected_revision=None,
            )
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(invoke, requests))

            stored_ids = {item["content_id"] for item in store.list_all_states(include_demo=True)}
            audit_lines = (Path(tmp) / "events" / "revision.jsonl").read_text(
                encoding="utf-8"
            ).splitlines()

        self.assertEqual(sorted(kind for kind, _ in results), ["conflict", "created"])
        conflict = next(value for kind, value in results if kind == "conflict")
        self.assertIsInstance(conflict, HTTPException)
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.detail["existing_content_id"], "k1-concurrent-successor-r1")
        self.assertEqual(
            stored_ids,
            {"k1-concurrent-successor", "k1-concurrent-successor-r1"},
        )
        self.assertEqual(calls, 1)
        self.assertEqual(len(audit_lines), 1)

    def test_campaign_endpoints_calculate_complete_history_beyond_browser_limit(self):
        states = [
            {
                "content_id": f"k1-history-{number:03d}",
                "campaign_id": "k1",
                "campaign": "K1 QA",
                "status": "blocked",
                "state_revision": 1,
                "revision_source": {},
                "updated_at": "2026-07-13T09:00:00+00:00",
            }
            for number in range(105)
        ]
        fake_store = Mock()
        fake_store.list_all_states.return_value = states

        with patch("marketing_machine.api.JsonStore", return_value=fake_store), patch(
            "marketing_machine.api.full_trend_runs", return_value=[]
        ):
            campaigns = list_campaigns()
            detail = campaign_detail("k1")

        k1 = next(item for item in campaigns["items"] if item["id"] == "k1")
        self.assertEqual(k1["content"]["all_time_total"], 105)
        self.assertEqual(detail["content"]["all_time_total"], 105)
        self.assertEqual(len(detail["content_items"]), 100)
        self.assertEqual(
            detail["content_items_page"],
            {"returned": 100, "total": 105, "limit": 100, "has_more": True},
        )
        self.assertEqual(fake_store.list_all_states.call_count, 2)
        fake_store.list_states.assert_not_called()

    def test_readiness_attributes_actual_model_and_source_use_without_conflating_reachability(self):
        fake_store = Mock()
        fake_store.list_states.return_value = [
            {
                "updated_at": "2026-07-10T09:00:00+00:00",
                "generation": {"status": "ai_generated", "provider": "kimi_backup", "model": "kimi-model"},
            }
        ]
        fake_store.list_trend_runs.return_value = [
            {
                "request_id": "174306",
                "status": "verified_sources",
                "run_started_at": "2026-07-10T08:00:00+00:00",
                "successful_source_adapters": ["firecrawl_v2"],
            }
        ]

        def url_check(name, _url, required=False):
            return {
                "name": name,
                "ok": True,
                "required": required,
                "configured": True,
                "reachable": True,
                "used_successfully": False,
            }

        def model_check(name, _url, _key, model_name="", required=False):
            return {
                "name": name,
                "ok": True,
                "required": required,
                "configured": True,
                "reachable": True,
                "used_successfully": False,
                "model": model_name,
            }

        with patch("marketing_machine.api.JsonStore", return_value=fake_store), patch(
            "marketing_machine.api.check_url", side_effect=url_check
        ), patch(
            "marketing_machine.api.check_ollama_model",
            return_value={
                "name": "ollama",
                "ok": True,
                "required": True,
                "configured": True,
                "reachable": True,
                "used_successfully": False,
            },
        ), patch(
            "marketing_machine.api.check_openai_compatible_models", side_effect=model_check
        ), patch(
            "marketing_machine.api.check_firecrawl_configuration",
            return_value={
                "name": "firecrawl",
                "ok": False,
                "required": False,
                "configured": True,
                "reachable": None,
                "used_successfully": False,
            },
        ), patch(
            "marketing_machine.api.full_trend_runs",
            return_value=[{"campaigns": []}],
        ), patch(
            "marketing_machine.api.trend_run_has_verified_sources",
            return_value=True,
        ), patch.dict(
            os.environ,
            {
                "LOCAL_MODEL_NAME": "qwen-local",
                "LOCAL_OPENAI_MODEL_NAME": "qwen-local",
                "KIMI_API_KEY": "configured-key",
                "KIMI_MODEL_NAME": "kimi-model",
                "MARKETING_MACHINE_ALLOW_CLOUD_FALLBACK": "true",
                "MARKETING_MACHINE_N8N_WORKFLOWS_VERIFIED": "true",
            },
        ):
            result = integrations_status()

        checks = {item["name"]: item for item in result["checks"]}
        self.assertTrue(checks["n8n"]["used_successfully"])
        self.assertEqual(checks["n8n"]["last_execution_id"], "174306")
        self.assertEqual(checks["n8n"]["verification_basis"], "persisted_trend_workflow_execution")
        self.assertFalse(checks["local_openai"]["used_successfully"])
        self.assertTrue(checks["kimi"]["used_successfully"])
        self.assertTrue(checks["firecrawl"]["used_successfully"])
        self.assertTrue(checks["trend_research"]["used_successfully"])

    def test_disabled_cloud_fallback_does_not_probe_kimi_or_claim_historical_use(self):
        fake_store = Mock()
        fake_store.list_states.return_value = [
            {
                "updated_at": "2026-07-10T09:00:00+00:00",
                "generation": {"status": "ai_generated", "provider": "kimi_backup", "model": "old-model"},
            }
        ]
        fake_store.list_trend_runs.return_value = []

        def url_check(name, _url, required=False):
            return {
                "name": name,
                "ok": True,
                "required": required,
                "configured": True,
                "reachable": True,
                "used_successfully": False,
            }

        local_model_status = {
            "name": "local_openai",
            "ok": True,
            "required": True,
            "configured": True,
            "reachable": True,
            "used_successfully": False,
            "model": "qwen-local",
        }
        with patch("marketing_machine.api.JsonStore", return_value=fake_store), patch(
            "marketing_machine.api.check_url", side_effect=url_check
        ), patch(
            "marketing_machine.api.check_ollama_model",
            return_value={
                "name": "ollama",
                "ok": True,
                "required": True,
                "configured": True,
                "reachable": True,
                "used_successfully": False,
            },
        ), patch(
            "marketing_machine.api.check_openai_compatible_models",
            return_value=local_model_status,
        ) as model_check, patch(
            "marketing_machine.api.check_firecrawl_configuration",
            return_value={
                "name": "firecrawl",
                "ok": False,
                "required": False,
                "configured": False,
                "reachable": None,
                "used_successfully": False,
            },
        ), patch.dict(
            os.environ,
            {
                "LOCAL_MODEL_NAME": "qwen-local",
                "LOCAL_OPENAI_MODEL_NAME": "qwen-local",
                "KIMI_BASE_URL": "https://cloud.example.invalid/v1",
                "KIMI_API_KEY": "configured-test-key",
                "KIMI_MODEL_NAME": "configured-model",
                "MARKETING_MACHINE_ALLOW_CLOUD_FALLBACK": "false",
                "MARKETING_MACHINE_N8N_WORKFLOWS_VERIFIED": "true",
            },
        ):
            result = integrations_status()

        model_check.assert_called_once()
        self.assertEqual(model_check.call_args.args[0], "local_openai")
        checks = {item["name"]: item for item in result["checks"]}
        self.assertFalse(checks["n8n"]["used_successfully"])
        self.assertEqual(
            checks["n8n"]["verification_basis"],
            "operator_manifest_attested_without_execution",
        )
        self.assertEqual(checks["n8n"]["last_execution_id"], "")
        kimi = checks["kimi"]
        self.assertTrue(kimi["configured"])
        self.assertTrue(kimi["disabled_by_policy"])
        self.assertIsNone(kimi["reachable"])
        self.assertFalse(kimi["used_successfully"])
        self.assertNotIn("configured-test-key", str(result))
        self.assertIn("workload-appropriate endpoint", kimi["action"])

    def test_n8n_execution_evidence_rejects_non_execution_runs_but_not_source_gates(self):
        self.assertIsNone(
            recorded_n8n_execution(
                [
                    {
                        "request_id": "browser-uuid",
                        "status": "verified_sources",
                        "successful_source_adapters": ["searxng"],
                    },
                    {
                        "request_id": "174305",
                        "status": "needs_live_sources",
                        "successful_source_adapters": [],
                    },
                ],
                workflows_verified=True,
            )
        )
        self.assertIsNone(
            recorded_n8n_execution(
                [
                    {
                        "request_id": "174306",
                        "status": "verified_sources",
                        "successful_source_adapters": ["searxng"],
                    }
                ],
                workflows_verified=False,
            )
        )
        evidence = recorded_n8n_execution(
            [
                {
                    "request_id": "174306",
                    "status": "needs_source_verification",
                    "successful_source_adapters": ["searxng"],
                }
            ],
            workflows_verified=True,
        )
        self.assertIsNotNone(evidence)
        self.assertEqual(evidence["request_id"], "174306")


if __name__ == "__main__":
    unittest.main()
