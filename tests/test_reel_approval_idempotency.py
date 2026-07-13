from concurrent.futures import ThreadPoolExecutor
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marketing_machine.api import approve_reel_concept
from marketing_machine.schemas import ContentBrief
from marketing_machine.storage import JsonStore


class ReelApprovalIdempotencyTests(unittest.TestCase):
    def setUp(self) -> None:
        actor = "Marketing Operator"
        actor_patch = patch(
            "marketing_machine.api.require_human_actor",
            return_value=actor,
        )
        identity_patch = patch(
            "marketing_machine.api.identity_audit_fields",
            return_value={
                "authenticated_actor": actor,
                "authenticated_request_fingerprint": "reel-approval-test-request",
            },
        )
        actor_patch.start()
        identity_patch.start()
        self.addCleanup(identity_patch.stop)
        self.addCleanup(actor_patch.stop)

    @staticmethod
    def concept(*, status: str = "draft") -> dict:
        return {
            "id": "concept-race-safe",
            "status": status,
            "run_id": "trend-run-safe",
            "campaign_id": "k1",
            "trend_id": "trend-safe",
            "created_at": "2026-07-10T12:00:00+00:00",
            "user_prompt": "",
            "campaign": {"id": "k1", "name": "K1 QA"},
            "trend": {"id": "trend-safe", "topic": "QA"},
            "variants": [
                {"id": "variant-one", "hook": "Hook one"},
                {"id": "variant-two", "hook": "Hook two"},
            ],
        }

    @staticmethod
    def brief() -> ContentBrief:
        return ContentBrief(
            id="reel-variant-one",
            campaign_id="k1",
            campaign="K1 QA",
            persona="IT-Leiter",
            channel="Instagram",
            format="reel",
            objective="QA erklären",
            cta="Audit anfragen",
            proof_sources=["Kampagnen/kampagne_1_consulting_qa.json"],
            utm={"utm_source": "instagram", "utm_medium": "organic", "utm_campaign": "k1"},
            hypothesis="Qualifizierte Reaktionen",
            test_variable="hook",
            trend_run_id="trend-run-safe",
        )

    @staticmethod
    def generated_state() -> dict:
        brief = ReelApprovalIdempotencyTests.brief().to_dict()
        brief.update(
            {
                "status": "needs_human_review",
                "generation": {
                    "status": "ai_generated",
                    "fallback_used": False,
                },
            }
        )
        return {
            "brief": brief,
            "approval": None,
            "errors": [],
            "next_step": "human_review",
            "requires_human_review": True,
            "evidence_records": [],
            "scheduler_payload": {},
        }

    @staticmethod
    def blocked_state(*, diagnostic: str = "provider-secret-diagnostic") -> dict:
        brief = ReelApprovalIdempotencyTests.brief().to_dict()
        brief.update(
            {
                "status": "blocked",
                "generation": {
                    "status": "deterministic_fallback",
                    "fallback_used": True,
                    "provider": "internal-provider-name",
                    "model": "internal-model-name",
                    "error": diagnostic,
                },
            }
        )
        return {
            "brief": brief,
            "approval": None,
            "errors": [diagnostic],
            "next_step": "regenerate",
            "requires_human_review": False,
            "evidence_records": [],
            "scheduler_payload": {},
        }

    def prepare_store(self, root: str, *, status: str = "draft") -> JsonStore:
        store = JsonStore(Path(root))
        store.save_reel_concept(self.concept(status=status), expected_revision=None)
        store.save_trend_run({"id": "trend-run-safe", "campaigns": []})
        return store

    def test_exact_retry_returns_persisted_state_without_second_generation(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            store = self.prepare_store(tmp)
            with patch(
                "marketing_machine.api.concept_to_content_brief", return_value=self.brief()
            ), patch(
                "marketing_machine.api.validate_trend_brief_against_run", return_value=[]
            ), patch(
                "marketing_machine.api.create_state_for_brief", return_value=self.generated_state()
            ) as generate:
                barrier = threading.Barrier(2)

                def approve(_index):
                    barrier.wait(timeout=5)
                    return approve_reel_concept("concept-race-safe", {"variant_id": "variant-one"})

                with ThreadPoolExecutor(max_workers=2) as executor:
                    results = list(executor.map(approve, range(2)))
                first = next(item for item in results if not item.get("idempotent", False))
                retry = next(item for item in results if item.get("idempotent", False))

                with self.assertRaises(HTTPException) as mismatch:
                    approve_reel_concept("concept-race-safe", {"variant_id": "variant-two"})

            persisted_concept = store.load_reel_concept("concept-race-safe")
            persisted_state = store.load_state("reel-variant-one")
            self.assertEqual(first["status"], "approved")
            self.assertTrue(retry["idempotent"])
            self.assertEqual(retry["state"], persisted_state)
            self.assertEqual(generate.call_count, 1)
            self.assertEqual(mismatch.exception.status_code, 409)
            self.assertEqual(
                persisted_concept["approval_fingerprint"],
                persisted_state["reel_approval_fingerprint"],
            )
            learning = (Path(tmp) / "learning" / "records.jsonl").read_text(encoding="utf-8")
            events = (Path(tmp) / "events" / "reel_concept_approval.jsonl").read_text(encoding="utf-8")
            self.assertEqual(len(learning.splitlines()), 1)
            self.assertEqual(len(events.splitlines()), 1)

    def test_blocked_generation_can_retry_same_selection_to_success(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            store = self.prepare_store(tmp)
            with patch(
                "marketing_machine.api.require_human_actor", return_value="Marketing Operator"
            ) as require_actor, patch(
                "marketing_machine.api.identity_audit_fields",
                return_value={
                    "authenticated_actor": "Marketing Operator",
                    "authenticated_request_fingerprint": "request-audit-safe",
                },
            ), patch(
                "marketing_machine.api.concept_to_content_brief", return_value=self.brief()
            ), patch(
                "marketing_machine.api.validate_trend_brief_against_run", return_value=[]
            ) as validate_provenance, patch(
                "marketing_machine.api.create_state_for_brief",
                side_effect=[self.blocked_state(), self.generated_state()],
            ) as generate:
                with self.assertRaises(HTTPException) as first_failure:
                    approve_reel_concept(
                        "concept-race-safe",
                        {"variant_id": "variant-one", "expected_revision": 1},
                    )

                first_state = store.load_state("reel-variant-one")
                first_concept = store.load_reel_concept("concept-race-safe")
                recovered = approve_reel_concept(
                    "concept-race-safe",
                    {"variant_id": "variant-one", "expected_revision": 2},
                )

            final_state = store.load_state("reel-variant-one")
            final_concept = store.load_reel_concept("concept-race-safe")

        self.assertEqual(first_failure.exception.status_code, 422)
        self.assertEqual(
            set(first_failure.exception.detail),
            {"message", "retry_allowed", "action", "content_id"},
        )
        self.assertTrue(first_failure.exception.detail["retry_allowed"])
        self.assertEqual(first_failure.exception.detail["action"], "regenerate")
        self.assertNotIn("provider-secret-diagnostic", str(first_failure.exception.detail))
        self.assertNotIn("internal-provider-name", str(first_failure.exception.detail))
        self.assertEqual(first_state["_storage_revision"], 1)
        self.assertEqual(first_concept["_storage_revision"], 2)
        self.assertEqual(recovered["status"], "approved")
        self.assertTrue(recovered["retried_generation"])
        self.assertFalse(recovered["idempotent"])
        self.assertEqual(final_state["_storage_revision"], 2)
        self.assertEqual(final_state["brief"]["generation"]["status"], "ai_generated")
        self.assertEqual(final_state["next_step"], "human_review")
        self.assertEqual(final_concept["_storage_revision"], 3)
        self.assertEqual(final_concept["status"], "approved_for_content_brief")
        self.assertEqual(generate.call_count, 2)
        self.assertGreaterEqual(validate_provenance.call_count, 3)
        self.assertEqual(require_actor.call_count, 2)

    def test_blocked_generation_retry_failure_persists_new_blocked_revision(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            store = self.prepare_store(tmp)
            with patch(
                "marketing_machine.api.require_human_actor", return_value="Marketing Operator"
            ), patch(
                "marketing_machine.api.concept_to_content_brief", return_value=self.brief()
            ), patch(
                "marketing_machine.api.validate_trend_brief_against_run", return_value=[]
            ), patch(
                "marketing_machine.api.create_state_for_brief",
                side_effect=[
                    self.blocked_state(diagnostic="first-private-error"),
                    self.blocked_state(diagnostic="second-private-error"),
                ],
            ) as generate:
                with self.assertRaises(HTTPException):
                    approve_reel_concept(
                        "concept-race-safe",
                        {"variant_id": "variant-one", "expected_revision": 1},
                    )
                with self.assertRaises(HTTPException) as retry_failure:
                    approve_reel_concept(
                        "concept-race-safe",
                        {"variant_id": "variant-one", "expected_revision": 2},
                    )

            state = store.load_state("reel-variant-one")
            concept = store.load_reel_concept("concept-race-safe")

        self.assertEqual(retry_failure.exception.status_code, 422)
        self.assertEqual(retry_failure.exception.detail["action"], "regenerate")
        self.assertNotIn("second-private-error", str(retry_failure.exception.detail))
        self.assertNotIn("internal-model-name", str(retry_failure.exception.detail))
        self.assertEqual(state["_storage_revision"], 2)
        self.assertEqual(state["brief"]["status"], "blocked")
        self.assertEqual(state["next_step"], "regenerate")
        self.assertEqual(concept["_storage_revision"], 3)
        self.assertEqual(concept["status"], "content_generation_blocked")
        self.assertEqual(generate.call_count, 2)

    def test_blocked_generation_never_accepts_a_different_selection(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            store = self.prepare_store(tmp)
            with patch(
                "marketing_machine.api.concept_to_content_brief", return_value=self.brief()
            ), patch(
                "marketing_machine.api.validate_trend_brief_against_run", return_value=[]
            ), patch(
                "marketing_machine.api.create_state_for_brief",
                return_value=self.blocked_state(),
            ) as generate:
                with self.assertRaises(HTTPException):
                    approve_reel_concept(
                        "concept-race-safe",
                        {"variant_id": "variant-one", "expected_revision": 1},
                    )
                with self.assertRaises(HTTPException) as mismatch:
                    approve_reel_concept(
                        "concept-race-safe",
                        {"variant_id": "variant-two", "expected_revision": 2},
                    )

            state = store.load_state("reel-variant-one")
            concept = store.load_reel_concept("concept-race-safe")

        self.assertEqual(mismatch.exception.status_code, 409)
        self.assertEqual(generate.call_count, 1)
        self.assertEqual(state["_storage_revision"], 1)
        self.assertEqual(concept["approved_variant_id"], "variant-one")

    def test_blocked_generation_retry_revalidates_current_trend_before_generation(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            store = self.prepare_store(tmp)
            with patch(
                "marketing_machine.api.concept_to_content_brief", return_value=self.brief()
            ), patch(
                "marketing_machine.api.validate_trend_brief_against_run",
                side_effect=[[], ["private stale provenance detail"]],
            ), patch(
                "marketing_machine.api.create_state_for_brief",
                return_value=self.blocked_state(),
            ) as generate:
                with self.assertRaises(HTTPException):
                    approve_reel_concept(
                        "concept-race-safe",
                        {"variant_id": "variant-one", "expected_revision": 1},
                    )
                with self.assertRaises(HTTPException) as stale:
                    approve_reel_concept(
                        "concept-race-safe",
                        {"variant_id": "variant-one", "expected_revision": 2},
                    )

            state = store.load_state("reel-variant-one")
            concept = store.load_reel_concept("concept-race-safe")

        self.assertEqual(stale.exception.status_code, 409)
        self.assertEqual(stale.exception.detail["action"], "refresh_research")
        self.assertFalse(stale.exception.detail["retry_allowed"])
        self.assertNotIn("private stale provenance detail", str(stale.exception.detail))
        self.assertEqual(generate.call_count, 1)
        self.assertEqual(state["_storage_revision"], 1)
        self.assertEqual(concept["_storage_revision"], 2)

    def test_reviewable_ai_state_is_idempotent_and_never_regenerated(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            self.prepare_store(tmp)
            with patch(
                "marketing_machine.api.concept_to_content_brief", return_value=self.brief()
            ), patch(
                "marketing_machine.api.validate_trend_brief_against_run", return_value=[]
            ), patch(
                "marketing_machine.api.create_state_for_brief",
                return_value=self.generated_state(),
            ) as generate:
                first = approve_reel_concept(
                    "concept-race-safe",
                    {"variant_id": "variant-one", "expected_revision": 1},
                )
                retry = approve_reel_concept(
                    "concept-race-safe",
                    {"variant_id": "variant-one", "expected_revision": 2},
                )

        self.assertEqual(first["status"], "approved")
        self.assertTrue(retry["idempotent"])
        self.assertFalse(retry["retry_allowed"])
        self.assertEqual(generate.call_count, 1)

    def test_terminal_concept_is_rejected_before_brief_or_generation(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            self.prepare_store(tmp, status="approved_for_content_brief")
            with patch("marketing_machine.api.concept_to_content_brief") as convert, patch(
                "marketing_machine.api.create_state_for_brief"
            ) as generate:
                with self.assertRaises(HTTPException) as raised:
                    approve_reel_concept("concept-race-safe", {"variant_id": "variant-one"})

            self.assertEqual(raised.exception.status_code, 409)
            convert.assert_not_called()
            generate.assert_not_called()

    def test_existing_reviewed_content_is_rejected_before_generation(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            store = self.prepare_store(tmp)
            store.save_state(
                {
                    "brief": {"id": "reel-variant-one", "status": "ready_to_schedule"},
                    "approval": {"decision": "approved"},
                    "next_step": "scheduler",
                    "requires_human_review": False,
                },
                expected_revision=None,
            )
            with patch(
                "marketing_machine.api.concept_to_content_brief", return_value=self.brief()
            ), patch(
                "marketing_machine.api.validate_trend_brief_against_run", return_value=[]
            ), patch("marketing_machine.api.create_state_for_brief") as generate:
                with self.assertRaises(HTTPException) as raised:
                    approve_reel_concept("concept-race-safe", {"variant_id": "variant-one"})

            self.assertEqual(raised.exception.status_code, 409)
            generate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
