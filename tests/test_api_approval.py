from concurrent.futures import ThreadPoolExecutor
import copy
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marketing_machine.api import approve_content
from marketing_machine.campaign_catalog import default_brief_payload, load_campaign_catalog
from marketing_machine.content_generator import ContentGenerator
from marketing_machine.evidence import EvidenceVault
from marketing_machine.governance import GovernancePolicy
from marketing_machine.schemas import ContentBrief
from marketing_machine.storage import JsonStore
from marketing_machine.workflow import MarketingWorkflow


ROOT = Path(__file__).resolve().parents[1]
_GOLDEN_ITEMS = json.loads(
    (ROOT / "tests" / "fixtures" / "content_quality" / "golden_pass_k1_k5.json").read_text(
        encoding="utf-8"
    )
)["items"]
_GOLDEN_BY_CAMPAIGN = {
    item["brief"]["campaign_id"]: item["brief"] for item in _GOLDEN_ITEMS
}


def release_quality_model_payload(campaign_id: str) -> dict:
    brief = _GOLDEN_BY_CAMPAIGN[campaign_id]
    return copy.deepcopy(
        {
            "channel_copy": brief["channel_copy"],
            "reel": brief["reel_output"],
            "citations": [],
            "review_notes": [],
        }
    )


class SafeStructuredAIClient:
    provider = "test-local-ai"
    model = "schema-valid-test-model"
    route_name = "local_content_draft"

    def complete_json(self, **kwargs):
        prompt = str(kwargs.get("user_prompt", ""))
        campaign_id = "k4" if '"cta_exact":"Team kennenlernen"' in prompt else "k1"
        return release_quality_model_payload(campaign_id)


class ApprovalEndpointTests(unittest.TestCase):
    def setUp(self):
        self.env_patch = patch.dict(
            os.environ,
            {
                "MARKETING_MACHINE_INSTANCE_MODE": "development",
                "MARKETING_MACHINE_ACTOR_AUTH_MODE": "local-optional",
            },
            clear=False,
        )
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        root = ROOT
        self.root = root
        self.policy = GovernancePolicy.from_json_file(root / "config" / "governance-policy.json")
        self.evidence = EvidenceVault.from_json_file(root / "config" / "evidence-vault.json")
        self.workflow = MarketingWorkflow(
            self.policy,
            evidence_vault=self.evidence,
            content_generator=ContentGenerator([SafeStructuredAIClient()]),
        )

    def pending_state(self, content_id: str) -> dict:
        campaign = next(item for item in load_campaign_catalog(self.root) if item["id"] == "k1")
        brief = ContentBrief(**default_brief_payload(campaign, content_id=content_id))
        return self.workflow.run_until_review(brief).to_dict()

    def people_pending_state(self, content_id: str) -> dict:
        campaign = next(item for item in load_campaign_catalog(self.root) if item["id"] == "k4")
        brief = ContentBrief(**default_brief_payload(campaign, content_id=content_id))
        return self.workflow.run_until_review(brief).to_dict()

    @staticmethod
    def approval_payload(content_id: str, **overrides) -> dict:
        payload = {
            "content_id": content_id,
            "reviewer": "reviewer@example.invalid",
            "decision": "approved",
            "brand_score": 95,
            "fact_check_passed": True,
            "privacy_check_passed": True,
            "ai_disclosure_check_passed": True,
            "notes": "Quellen und Freigaben geprüft.",
        }
        payload.update(overrides)
        return payload

    def test_identical_retry_is_unchanged_and_conflict_returns_409(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            store = JsonStore()
            store.save_state(self.pending_state("k1-approval-retry"))
            payload = self.approval_payload("k1-approval-retry")

            first = approve_content(payload)
            saved_after_first = store.load_state("k1-approval-retry")
            second = approve_content(dict(payload))
            saved_after_retry = store.load_state("k1-approval-retry")

            self.assertTrue(second["idempotent"])
            self.assertEqual(first["state"], saved_after_first)
            self.assertEqual(second["state"], saved_after_first)
            self.assertEqual(saved_after_retry, saved_after_first)
            self.assertEqual(saved_after_retry["errors"], [])
            event_path = Path(tmp) / "events" / "approval.jsonl"
            self.assertEqual(len(event_path.read_text(encoding="utf-8").splitlines()), 1)

            with self.assertRaises(HTTPException) as raised:
                approve_content(self.approval_payload("k1-approval-retry", notes="Andere Entscheidungsspur"))
            self.assertEqual(raised.exception.status_code, 409)
            self.assertEqual(store.load_state("k1-approval-retry"), saved_after_first)
            self.assertEqual(len(event_path.read_text(encoding="utf-8").splitlines()), 1)

    def test_no_client_fallback_cannot_enter_or_pass_the_approval_endpoint(self):
        workflow = MarketingWorkflow(
            self.policy,
            evidence_vault=self.evidence,
            content_generator=ContentGenerator(),
        )
        brief = ContentBrief(
            id="k1-fallback-approval-blocked",
            campaign="K1 QA",
            campaign_id="k1",
            persona="IT-Leiter Thomas",
            channel="LinkedIn",
            format="expert_post",
            objective="QA-Risikoaudit mit senioriger Testexpertise anbieten.",
            cta="QA-Risikoaudit anfragen",
            proof_sources=["Kampagnen/kampagne_1_consulting_qa.json"],
            utm={"utm_source": "linkedin", "utm_medium": "organic", "utm_campaign": "k1_qa_audit"},
            hypothesis="Nachweisbasierter QA-Content erzeugt qualifizierte Anfragen.",
            test_variable="offer",
        )
        fallback_state = workflow.run_until_review(brief).to_dict()

        self.assertEqual(fallback_state["brief"]["generation"]["status"], "deterministic_fallback")
        self.assertEqual(fallback_state["brief"]["status"], "blocked")
        self.assertEqual(fallback_state["next_step"], "regenerate")
        self.assertFalse(fallback_state["requires_human_review"])

        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            store = JsonStore()
            store.save_state(fallback_state)

            with self.assertRaises(HTTPException) as raised:
                approve_content(self.approval_payload(brief.id))

            self.assertEqual(raised.exception.status_code, 409)
            self.assertIn("not awaiting a review", str(raised.exception.detail))
            self.assertEqual(store.load_state(brief.id), fallback_state)
            self.assertFalse((Path(tmp) / "events" / "approval.jsonl").exists())

    def test_tampered_secondary_route_draft_cannot_pass_approval_endpoint(self):
        content_id = "k1-secondary-route-approval-blocked"
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            store = JsonStore()
            pending = self.pending_state(content_id)
            pending["brief"]["generation"]["fallback_used"] = True
            pending["brief"]["generation"]["fallback_reason"] = "connection_error"
            store.save_state(pending)

            response = approve_content(self.approval_payload(content_id))

            self.assertEqual(response["state"]["brief"]["status"], "blocked")
            self.assertEqual(response["state"]["next_step"], "blocked")
            self.assertFalse(response["state"]["requires_human_review"])
            self.assertEqual(response["state"]["scheduler_payload"], {})
            self.assertIsNone(response["state"]["approval"])
            self.assertIn(
                "approved primary AI route",
                "; ".join(response["state"]["errors"]),
            )

    def test_tampered_content_quality_is_recomputed_persisted_and_blocked(self):
        content_id = "k1-quality-tamper-blocked"
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            store = JsonStore()
            pending = self.pending_state(content_id)
            self.assertTrue(pending["brief"]["quality_evaluation"]["release_ready"])
            pending["brief"]["public_copy"] = pending["brief"]["public_copy"].replace(
                pending["brief"]["cta"], ""
            )
            store.save_state(pending)

            response = approve_content(self.approval_payload(content_id))

            saved = store.load_state(content_id)
            self.assertEqual(response["state"], saved)
            self.assertEqual(saved["brief"]["status"], "blocked")
            self.assertEqual(saved["next_step"], "blocked")
            self.assertFalse(saved["brief"]["quality_evaluation"]["release_ready"])
            self.assertTrue(saved["brief"]["quality_evaluation"]["hard_blockers"])
            self.assertEqual(saved["scheduler_payload"], {})
            self.assertIsNone(saved["approval"])

    def test_people_campaign_approval_requires_complete_media_and_consent_without_mutating_on_failure(self):
        content_id = "k4-consent-gated-approval"
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            store = JsonStore()
            pending = self.people_pending_state(content_id)
            store.save_state(pending)

            with self.assertRaises(HTTPException) as missing:
                approve_content(self.approval_payload(content_id))

            self.assertEqual(missing.exception.status_code, 409)
            self.assertIn("consent evidence", str(missing.exception.detail))
            self.assertEqual(store.load_state(content_id), pending)

            evidenced = store.load_state(content_id)
            evidenced["approved_media_assets"] = [
                {
                    "asset_id": "k4-real-video",
                    "status": "approved",
                    "media_type": "video",
                    "postiz_media_id": "postiz-k4-real-video",
                    "postiz_path": "https://uploads.postiz.invalid/k4.mp4",
                    "sha256": "b" * 64,
                    "reviewer": "reviewer@example.invalid",
                    "approved_at": "2026-07-13T08:00:00+00:00",
                    "source_ref": "creative-review:k4",
                    "preview_ref": "postiz-preview:k4",
                    "verification_method": "operator_postiz_ui",
                    "provider_verified": True,
                    "provider_sha256": "b" * 64,
                    "provider_path": "https://uploads.postiz.invalid/k4.mp4",
                    "provider_verification_method": "postiz_public_url_sha256",
                    "consent_refs": ["consent:k4-person-1"],
                    "brand_check_passed": True,
                    "fact_check_passed": True,
                    "privacy_check_passed": True,
                    "ai_disclosure_check_passed": True,
                }
            ]
            store.save_state(evidenced, expected_revision=JsonStore.state_revision(evidenced))
            approved = approve_content(self.approval_payload(content_id))

            self.assertEqual(approved["state"]["brief"]["status"], "ready_to_schedule")
            self.assertEqual(
                approved["state"]["approved_media_assets"][0]["asset_id"],
                "k4-real-video",
            )

    def test_concurrent_identical_approval_writes_one_terminal_event(self):
        content_id = "k1-concurrent-approval"
        barrier = threading.Barrier(2)
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            store = JsonStore()
            store.save_state(self.pending_state(content_id))

            def approve(_index):
                barrier.wait(timeout=5)
                return approve_content(self.approval_payload(content_id))

            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(approve, range(2)))

            event_path = Path(tmp) / "events" / "approval.jsonl"
            self.assertEqual(
                sorted(bool(item.get("idempotent", False)) for item in results),
                [False, True],
            )
            self.assertEqual(len(event_path.read_text(encoding="utf-8").splitlines()), 1)

    def test_terminal_state_without_matching_audit_returns_409_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            store = JsonStore()
            state = self.pending_state("k1-terminal-without-audit")
            state["brief"]["status"] = "ready_to_schedule"
            state["next_step"] = "scheduler"
            state["requires_human_review"] = False
            store.save_state(state)
            before = json.dumps(store.load_state("k1-terminal-without-audit"), sort_keys=True)

            with self.assertRaises(HTTPException) as raised:
                approve_content(self.approval_payload("k1-terminal-without-audit"))

            self.assertEqual(raised.exception.status_code, 409)
            after = json.dumps(store.load_state("k1-terminal-without-audit"), sort_keys=True)
            self.assertEqual(after, before)
            self.assertFalse((Path(tmp) / "events" / "approval.jsonl").exists())

    def test_trend_approval_without_stored_run_id_is_rejected_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            store = JsonStore()
            state = self.pending_state("k1-trend-without-run")
            state["brief"]["trend_id"] = "trend-1"
            store.save_state(state)
            before = store.load_state("k1-trend-without-run")

            with self.assertRaises(HTTPException) as raised:
                approve_content(self.approval_payload("k1-trend-without-run"))

            self.assertEqual(raised.exception.status_code, 422)
            self.assertEqual(store.load_state("k1-trend-without-run"), before)

    def test_stale_expected_revision_is_rejected_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            store = JsonStore()
            store.save_state(self.pending_state("k1-stale-review"))
            before = store.load_state("k1-stale-review")
            payload = self.approval_payload("k1-stale-review", expected_revision=0)

            with self.assertRaises(HTTPException) as raised:
                approve_content(payload)

            self.assertEqual(raised.exception.status_code, 409)
            self.assertEqual(store.load_state("k1-stale-review"), before)
            self.assertFalse((Path(tmp) / "events" / "approval.jsonl").exists())

    def test_brand_score_must_be_explicit_and_between_zero_and_one_hundred(self):
        invalid_scores = (None, -1, 101, 95.5, True)
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            store = JsonStore()
            for index, score in enumerate(invalid_scores):
                content_id = f"k1-invalid-brand-score-{index}"
                state = self.pending_state(content_id)
                store.save_state(state)
                payload = self.approval_payload(content_id)
                if score is None:
                    payload.pop("brand_score")
                else:
                    payload["brand_score"] = score

                with self.subTest(score=score), self.assertRaises(HTTPException) as raised:
                    approve_content(payload)

                self.assertEqual(raised.exception.status_code, 422)
                self.assertEqual(store.load_state(content_id), state)

    def test_approval_note_is_required_and_whitespace_is_rejected_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"MARKETING_MACHINE_DATA_DIR": tmp}, clear=False
        ):
            store = JsonStore()
            for index, note in enumerate((None, "", "   ")):
                content_id = f"k1-missing-approval-note-{index}"
                state = self.pending_state(content_id)
                store.save_state(state)
                payload = self.approval_payload(content_id, notes=note)

                with self.subTest(note=note), self.assertRaises(HTTPException) as raised:
                    approve_content(payload)

                self.assertEqual(raised.exception.status_code, 422)
                self.assertIn("notes is required", str(raised.exception.detail))
                self.assertEqual(store.load_state(content_id), state)


if __name__ == "__main__":
    unittest.main()
