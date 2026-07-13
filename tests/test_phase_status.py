import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marketing_machine.phases import build_phase_status


class PhaseStatusTests(unittest.TestCase):
    def test_business_capabilities_fail_closed_without_success_or_production_access(self):
        result = build_phase_status(
            integrations={"status": "degraded", "checks": []},
            env={},
            workflows_dir=Path("missing"),
        )

        capabilities = result["business_capabilities"]
        self.assertEqual(
            set(capabilities),
            {
                "research",
                "content_generation",
                "media_generation",
                "approval",
                "scheduler_handoff",
            },
        )
        self.assertTrue(all(item["ready"] is False for item in capabilities.values()))
        self.assertTrue(all(item["can_run"] is False for item in capabilities.values()))
        self.assertTrue(
            all(
                item["available_for_controlled_run"] is item["can_run"]
                for item in capabilities.values()
            )
        )
        self.assertTrue(all(item["status"] == "blocked" for item in capabilities.values()))
        self.assertTrue(all(item["reason_code"] for item in capabilities.values()))
        self.assertTrue(all(item["business_message"] for item in capabilities.values()))

    def test_business_capabilities_report_partial_when_services_are_only_prepared(self):
        result = build_phase_status(
            integrations={
                "status": "degraded",
                "checks": [
                    {"name": "ollama", "ok": True},
                    {
                        "name": "local_openai",
                        "ok": True,
                        "configured": True,
                        "reachable": True,
                    },
                    {
                        "name": "searxng",
                        "ok": True,
                        "configured": True,
                        "reachable": True,
                        "used_successfully": True,
                    },
                    {
                        "name": "comfyui",
                        "ok": False,
                        "reachable": True,
                        "model_bundle_ready": False,
                    },
                    {
                        "name": "postiz",
                        "configured": True,
                        "reachable": True,
                        "write_ready": True,
                    },
                ],
            },
            env={
                "MARKETING_MACHINE_MUTATION_AUTH_MODE": "required",
                "MARKETING_MACHINE_MUTATION_TOKEN": "a" * 40,
                "MARKETING_MACHINE_ACTOR_AUTH_MODE": "required",
                "MARKETING_MACHINE_EDGE_ATTESTATION": "b" * 64,
                "MARKETING_MACHINE_ENABLE_EXTERNAL_WRITES": "true",
                "POSTIZ_CREATE_DRAFT_PATH": "/api/public/v1/posts",
                "POSTIZ_API_KEY": "synthetic-test-value",
                "POSTIZ_CONTRACT_VERIFIED": "true",
                "POSTIZ_LINKEDIN_INTEGRATION_ID": "linkedin-test",
                "POSTIZ_INSTAGRAM_INTEGRATION_ID": "instagram-test",
            },
            workflows_dir=Path("missing"),
        )

        capabilities = result["business_capabilities"]
        self.assertEqual(capabilities["research"]["status"], "partial")
        self.assertEqual(capabilities["content_generation"]["status"], "partial")
        self.assertEqual(capabilities["media_generation"]["status"], "blocked")
        self.assertEqual(capabilities["scheduler_handoff"]["status"], "partial")
        self.assertTrue(capabilities["research"]["can_run"])
        self.assertTrue(capabilities["content_generation"]["can_run"])
        self.assertFalse(capabilities["media_generation"]["can_run"])
        self.assertTrue(capabilities["scheduler_handoff"]["can_run"])
        self.assertFalse(capabilities["research"]["ready"])
        self.assertFalse(capabilities["content_generation"]["ready"])
        self.assertFalse(capabilities["media_generation"]["ready"])
        self.assertTrue(capabilities["approval"]["ready"])
        self.assertFalse(capabilities["scheduler_handoff"]["ready"])

    def test_fresh_candidate_can_run_text_checks_despite_unrelated_global_block(self):
        env = {
            "MARKETING_MACHINE_MUTATION_AUTH_MODE": "required",
            "MARKETING_MACHINE_MUTATION_TOKEN": "a" * 40,
            "MARKETING_MACHINE_ACTOR_AUTH_MODE": "required",
            "MARKETING_MACHINE_EDGE_ATTESTATION": "b" * 64,
        }
        integrations = {
            "status": "degraded",
            "checks": [
                {
                    "name": "local_openai",
                    "ok": True,
                    "configured": True,
                    "reachable": True,
                    "used_successfully": False,
                },
                {
                    "name": "searxng",
                    "ok": True,
                    "configured": True,
                    "reachable": True,
                    "used_successfully": False,
                },
                {
                    "name": "comfyui",
                    "ok": False,
                    "reachable": False,
                    "model_bundle_ready": False,
                    "runtime_compatible": False,
                },
            ],
        }

        result = build_phase_status(
            integrations=integrations,
            env=env,
            workflows_dir=Path("missing"),
        )

        capabilities = result["business_capabilities"]
        self.assertEqual(result["status"], "blocked")
        for name in ("research", "content_generation"):
            self.assertTrue(capabilities[name]["can_run"])
            self.assertTrue(capabilities[name]["available_for_controlled_run"])
            self.assertFalse(capabilities[name]["ready"])
            self.assertEqual(capabilities[name]["status"], "partial")
        self.assertFalse(capabilities["media_generation"]["can_run"])
        self.assertEqual(capabilities["media_generation"]["status"], "blocked")

    def test_fresh_candidate_services_fail_closed_without_protected_access(self):
        integrations = {
            "status": "ok",
            "checks": [
                {
                    "name": "local_openai",
                    "ok": True,
                    "configured": True,
                    "reachable": True,
                },
                {
                    "name": "searxng",
                    "ok": True,
                    "configured": True,
                    "reachable": True,
                },
            ],
        }

        result = build_phase_status(
            integrations=integrations,
            env={},
            workflows_dir=Path("missing"),
        )

        capabilities = result["business_capabilities"]
        for name in ("research", "content_generation", "approval"):
            self.assertFalse(capabilities[name]["can_run"])
            self.assertFalse(capabilities[name]["ready"])
            self.assertEqual(capabilities[name]["status"], "blocked")

    def test_business_capabilities_keep_media_blocked_without_a_governed_job(self):
        env = {
            "MARKETING_MACHINE_MUTATION_AUTH_MODE": "required",
            "MARKETING_MACHINE_MUTATION_TOKEN": "a" * 40,
            "MARKETING_MACHINE_ACTOR_AUTH_MODE": "required",
            "MARKETING_MACHINE_EDGE_ATTESTATION": "b" * 64,
            "MARKETING_MACHINE_ENABLE_EXTERNAL_WRITES": "true",
            "POSTIZ_CREATE_DRAFT_PATH": "/api/public/v1/posts",
            "POSTIZ_API_KEY": "synthetic-test-value",
            "POSTIZ_CONTRACT_VERIFIED": "true",
            "POSTIZ_LINKEDIN_INTEGRATION_ID": "linkedin-test",
            "POSTIZ_INSTAGRAM_INTEGRATION_ID": "instagram-test",
        }
        integrations = {
            "status": "ok",
            "checks": [
                {"name": "ollama", "ok": True},
                {"name": "local_openai", "ok": True, "used_successfully": True},
                {"name": "searxng", "ok": True, "used_successfully": True},
                {"name": "trend_research", "ok": True, "used_successfully": True},
                {
                    "name": "comfyui",
                    "ok": True,
                    "reachable": True,
                    "model_bundle_ready": True,
                    "runtime_compatible": True,
                    "package_mismatches": [],
                    "used_successfully": True,
                },
                {
                    "name": "postiz",
                    "write_ready": True,
                    "used_successfully": True,
                },
            ],
        }

        result = build_phase_status(
            integrations=integrations,
            env=env,
            workflows_dir=Path("missing"),
        )

        capabilities = result["business_capabilities"]
        governed_business_capabilities = {
            name: item for name, item in capabilities.items() if name != "media_generation"
        }
        self.assertTrue(all(item["ready"] for item in governed_business_capabilities.values()))
        self.assertTrue(all(item["can_run"] for item in governed_business_capabilities.values()))
        self.assertTrue(all(item["status"] == "green" for item in governed_business_capabilities.values()))
        media = capabilities["media_generation"]
        self.assertFalse(media["ready"])
        self.assertFalse(media["can_run"])
        self.assertEqual(media["status"], "blocked")
        self.assertEqual(media["reason_code"], "governed_media_job_unavailable")
        self.assertIn("außerhalb dieses Arbeitsbereichs", media["business_message"])

    def test_phase_status_marks_core_operational_and_write_planes_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            workflows = Path(tmp)
            for name in ("analytics-72h.json", "analytics-7d.json", "analytics-14d.json", "analytics-30d.json"):
                (workflows / name).write_text("{}", encoding="utf-8")
            integrations = {
                "status": "ok",
                "checks": [
                    {"name": "ollama", "ok": True},
                    {"name": "local_openai", "ok": True},
                    {"name": "kimi", "ok": False, "configured": True},
                ],
            }

            result = build_phase_status(
                integrations=integrations,
                env={"MARKETING_MACHINE_ENABLE_EXTERNAL_WRITES": "false"},
                workflows_dir=workflows,
            )

        self.assertEqual(result["status"], "blocked")
        phases = {phase["id"]: phase for phase in result["phases"]}
        self.assertEqual(phases["02_model_plane"]["status"], "partial")
        self.assertEqual(phases["03_cloud_backup"]["status"], "partial")
        self.assertEqual(phases["04_content_workflow"]["status"], "partial")
        self.assertEqual(
            phases["04_content_workflow"]["next_actions"],
            [
                "Run and record one successful local AI generation",
                "Find an exact-topic trend supported by two domains and one recent dated source",
            ],
        )
        self.assertEqual(phases["06_n8n_rhythm"]["status"], "partial")
        self.assertFalse(phases["06_n8n_rhythm"]["metadata"]["execution_verified"])
        self.assertEqual(phases["08_lead_plane"]["status"], "partial")
        self.assertEqual(phases["09_publishing_plane"]["status"], "partial")
        self.assertFalse(phases["03_cloud_backup"]["critical"])
        self.assertTrue(phases["10_creative_plane"]["critical"])
        self.assertEqual(phases["10_creative_plane"]["status"], "blocked")

    def test_creative_plane_is_release_critical_and_requires_bundle_runtime_and_recorded_use(self):
        base_check = {
            "name": "comfyui",
            "reachable": True,
            "model_bundle_ready": True,
            "runtime_compatible": True,
            "package_mismatches": [],
        }
        incomplete = build_phase_status(
            integrations={"status": "ok", "checks": [{**base_check, "ok": True}]},
            env={},
            workflows_dir=Path("missing"),
        )
        complete = build_phase_status(
            integrations={
                "status": "ok",
                "checks": [{**base_check, "ok": True, "used_successfully": True}],
            },
            env={},
            workflows_dir=Path("missing"),
        )

        incomplete_phase = next(
            phase for phase in incomplete["phases"] if phase["id"] == "10_creative_plane"
        )
        complete_phase = next(
            phase for phase in complete["phases"] if phase["id"] == "10_creative_plane"
        )
        self.assertTrue(incomplete_phase["critical"])
        self.assertEqual(incomplete_phase["status"], "partial")
        self.assertEqual(incomplete["status"], "blocked")
        self.assertEqual(complete_phase["status"], "complete")
        self.assertTrue(complete_phase["metadata"]["model_bundle_ready"])
        self.assertTrue(complete_phase["metadata"]["runtime_compatible"])

    def test_inference_and_research_are_complete_only_after_successful_use(self):
        with tempfile.TemporaryDirectory() as tmp:
            integrations = {
                "status": "ok",
                "checks": [
                    {"name": "ollama", "ok": True, "reachable": True, "required": True},
                    {
                        "name": "local_openai",
                        "ok": True,
                        "configured": True,
                        "reachable": True,
                        "used_successfully": True,
                        "required": True,
                    },
                    {
                        "name": "searxng",
                        "ok": True,
                        "configured": True,
                        "reachable": True,
                        "used_successfully": True,
                    },
                    {
                        "name": "trend_research",
                        "ok": True,
                        "configured": True,
                        "reachable": None,
                        "used_successfully": True,
                    },
                ],
            }

            result = build_phase_status(integrations=integrations, env={}, workflows_dir=Path(tmp))

        phases = {phase["id"]: phase for phase in result["phases"]}
        self.assertEqual(phases["02_model_plane"]["status"], "complete")
        self.assertEqual(phases["04_content_workflow"]["status"], "complete")

    def test_n8n_phase_accepts_recorded_execution_evidence_from_integration_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            workflows = Path(tmp)
            for name in ("analytics-72h.json", "analytics-7d.json", "analytics-14d.json", "analytics-30d.json"):
                (workflows / name).write_text("{}", encoding="utf-8")
            integrations = {
                "status": "ok",
                "checks": [
                    {"name": "n8n", "ok": True, "required": True, "used_successfully": True},
                ],
            }

            result = build_phase_status(integrations=integrations, env={}, workflows_dir=workflows)

        phases = {phase["id"]: phase for phase in result["phases"]}
        self.assertEqual(phases["06_n8n_rhythm"]["status"], "complete")
        self.assertTrue(phases["06_n8n_rhythm"]["metadata"]["execution_verified"])

    def test_n8n_environment_attestation_without_execution_cannot_complete_phase(self):
        with tempfile.TemporaryDirectory() as tmp:
            workflows = Path(tmp)
            for name in ("analytics-72h.json", "analytics-7d.json", "analytics-14d.json", "analytics-30d.json"):
                (workflows / name).write_text("{}", encoding="utf-8")
            result = build_phase_status(
                integrations={
                    "status": "ok",
                    "checks": [{"name": "n8n", "ok": True, "required": True, "used_successfully": False}],
                },
                env={"MARKETING_MACHINE_N8N_WORKFLOWS_VERIFIED": "true"},
                workflows_dir=workflows,
            )

        phase = next(item for item in result["phases"] if item["id"] == "06_n8n_rhythm")
        self.assertEqual(phase["status"], "partial")
        self.assertFalse(phase["metadata"]["execution_verified"])

    def test_write_flags_cannot_mark_unreachable_or_unproven_targets_complete(self):
        configured = {
            "MARKETING_MACHINE_ENABLE_EXTERNAL_WRITES": "true",
            "POSTIZ_CREATE_DRAFT_PATH": "/api/public/v1/posts",
            "POSTIZ_API_KEY": "configured-secret",
            "POSTIZ_CONTRACT_VERIFIED": "true",
            "POSTIZ_LINKEDIN_INTEGRATION_ID": "linkedin-id",
            "POSTIZ_INSTAGRAM_INTEGRATION_ID": "instagram-id",
            "TWENTY_CREATE_CONTACT_PATH": "/rest/people",
            "TWENTY_API_KEY": "configured-secret",
            "TWENTY_CONTRACT_VERIFIED": "true",
            "MAUTIC_CREATE_CONTACT_PATH": "/api/contacts/new",
            "MAUTIC_API_KEY": "configured-secret",
            "MAUTIC_CONTRACT_VERIFIED": "true",
        }
        integrations = {
            "status": "ok",
            "checks": [
                {"name": "postiz", "reachable": False, "write_ready": False},
                {"name": "twenty", "reachable": True, "write_ready": True, "used_successfully": False},
                {"name": "mautic", "reachable": True, "write_ready": True, "used_successfully": True},
            ],
        }

        result = build_phase_status(integrations=integrations, env=configured, workflows_dir=Path("missing"))
        phases = {phase["id"]: phase for phase in result["phases"]}

        self.assertEqual(phases["08_lead_plane"]["status"], "partial")
        self.assertEqual(phases["09_publishing_plane"]["status"], "partial")
        self.assertFalse(phases["09_publishing_plane"]["metadata"]["postiz_ready"])
        self.assertEqual(
            phases["08_lead_plane"]["metadata"]["write_targets_ready"],
            {"postiz": False, "twenty": False, "mautic": True},
        )

    def test_first_postiz_staging_send_does_not_require_prior_success(self):
        configured = {
            "MARKETING_MACHINE_ENABLE_EXTERNAL_WRITES": "true",
            "POSTIZ_CREATE_DRAFT_PATH": "/api/public/v1/posts",
            "POSTIZ_API_KEY": "configured-secret",
            "POSTIZ_CONTRACT_VERIFIED": "true",
            "POSTIZ_LINKEDIN_INTEGRATION_ID": "linkedin-id",
            "POSTIZ_LINKEDIN_PROVIDER_TYPE": "linkedin",
            "POSTIZ_INSTAGRAM_INTEGRATION_ID": "instagram-id",
            "POSTIZ_INSTAGRAM_PROVIDER_TYPE": "instagram",
        }
        integrations = {
            "status": "ok",
            "checks": [
                {
                    "name": "postiz",
                    "reachable": True,
                    "configured": True,
                    "write_ready": True,
                    "used_successfully": False,
                }
            ],
        }

        result = build_phase_status(
            integrations=integrations,
            env=configured,
            workflows_dir=Path("missing"),
        )
        publishing = next(
            phase for phase in result["phases"] if phase["id"] == "09_publishing_plane"
        )

        self.assertFalse(publishing["metadata"]["postiz_ready"])
        self.assertTrue(publishing["metadata"]["postiz_first_live_write_ready"])
        self.assertEqual(publishing["status"], "partial")

    def test_n8n_analytics_phase_files_exist_and_target_all_review_windows(self):
        root = Path(__file__).resolve().parents[1]
        expected = {
            "analytics-72h.json": "72h",
            "analytics-7d.json": "7d",
            "analytics-14d.json": "14d",
            "analytics-30d.json": "30d",
        }

        for filename, review_window in expected.items():
            with self.subTest(filename=filename):
                path = root / "deploy" / "n8n" / "workflows" / filename
                data = json.loads(path.read_text(encoding="utf-8"))
                encoded = json.dumps(data)
                self.assertIn("/workflows/analytics/due", encoded)
                self.assertIn(review_window, encoded)
                self.assertNotIn('"content_id": "unknown"', encoded)


if __name__ == "__main__":
    unittest.main()
