import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marketing_machine.ai_client import AIClientError
from marketing_machine.campaign_catalog import default_brief_payload, load_campaign_catalog
from marketing_machine.content_generator import ContentGenerator
from marketing_machine.evidence import EvidenceVault
from marketing_machine.governance import GovernancePolicy
from marketing_machine.schemas import ApprovalRecord, ContentBrief, ContentStatus, ReviewDecision
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
    """Return realistic model output that satisfies the production quality contract."""

    brief = _GOLDEN_BY_CAMPAIGN[campaign_id]
    return copy.deepcopy(
        {
            "channel_copy": brief["channel_copy"],
            "reel": brief["reel_output"],
            # These fixtures do not claim a current trend, so public-source
            # citations would be invented rather than useful.
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


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        root = ROOT
        self.root = root
        self.policy = GovernancePolicy.from_json_file(root / "config" / "governance-policy.json")
        self.evidence = EvidenceVault.from_json_file(root / "config" / "evidence-vault.json")
        self.workflow = MarketingWorkflow(
            self.policy,
            evidence_vault=self.evidence,
            content_generator=ContentGenerator([SafeStructuredAIClient()]),
        )

    def make_brief(self):
        campaign = next(item for item in load_campaign_catalog(self.root) if item["id"] == "k1")
        return ContentBrief(**default_brief_payload(campaign, content_id="k1-qa-001"))

    def test_workflow_pauses_for_human_review(self):
        state = self.workflow.run_until_review(self.make_brief())
        self.assertTrue(state.requires_human_review)
        self.assertEqual(state.next_step, "human_review")
        self.assertEqual(state.brief.status, ContentStatus.NEEDS_HUMAN_REVIEW)
        self.assertIn("QA-Risikoaudit anfragen", state.brief.public_copy)
        self.assertTrue(state.brief.review_notes)
        self.assertEqual(state.brief.generation["status"], "ai_generated")
        self.assertTrue(state.brief.channel_copy)

    def test_no_client_fallback_requests_regeneration_and_cannot_be_approved(self):
        workflow = MarketingWorkflow(
            self.policy,
            evidence_vault=self.evidence,
            content_generator=ContentGenerator(),
        )

        state = workflow.run_until_review(self.make_brief())

        self.assertEqual(state.brief.generation["status"], "deterministic_fallback")
        self.assertEqual(state.brief.status, ContentStatus.BLOCKED)
        self.assertEqual(state.next_step, "regenerate")
        self.assertFalse(state.requires_human_review)
        self.assertIn("successful AI-generated draft", "; ".join(state.errors))

        approval = ApprovalRecord(
            content_id=state.brief.id,
            reviewer="reviewer@example.invalid",
            decision=ReviewDecision.APPROVED,
            brand_score=100,
            fact_check_passed=True,
            privacy_check_passed=True,
            ai_disclosure_check_passed=True,
        )
        result = workflow.resume_after_review(state, approval)

        self.assertEqual(result.brief.status, ContentStatus.BLOCKED)
        self.assertIsNone(result.approval)
        self.assertEqual(result.scheduler_payload, {})
        self.assertIn("blocked content cannot be approved", "; ".join(result.errors))

    def test_secondary_model_success_is_blocked_until_primary_route_regenerates(self):
        class FailedPrimary:
            provider = "approved-local-primary"
            model = "primary-model"
            route_name = "local_content_draft"

            def complete_json(self, **_kwargs):
                raise AIClientError("connection_error", "primary route unavailable", attempts=1)

        workflow = MarketingWorkflow(
            self.policy,
            evidence_vault=self.evidence,
            content_generator=ContentGenerator([FailedPrimary(), SafeStructuredAIClient()]),
        )

        state = workflow.run_until_review(self.make_brief())

        self.assertEqual(state.brief.generation["status"], "ai_generated")
        self.assertTrue(state.brief.generation["fallback_used"])
        self.assertEqual(state.brief.status, ContentStatus.BLOCKED)
        self.assertEqual(state.next_step, "regenerate")
        self.assertFalse(state.requires_human_review)
        self.assertEqual(state.scheduler_payload, {})
        self.assertIn("approved primary AI route", "; ".join(state.errors))

        # A stored record cannot bypass the same gate by changing only its
        # visible workflow status back to "awaiting review".
        state.brief.status = ContentStatus.NEEDS_HUMAN_REVIEW
        state.next_step = "human_review"
        state.requires_human_review = True
        state.errors = []
        approval = ApprovalRecord(
            content_id=state.brief.id,
            reviewer="reviewer@example.invalid",
            decision=ReviewDecision.APPROVED,
            brand_score=100,
            fact_check_passed=True,
            privacy_check_passed=True,
            ai_disclosure_check_passed=True,
        )

        result = workflow.resume_after_review(state, approval)

        self.assertEqual(result.brief.status, ContentStatus.BLOCKED)
        self.assertEqual(result.next_step, "blocked")
        self.assertIsNone(result.approval)
        self.assertEqual(result.scheduler_payload, {})
        self.assertIn("approved primary AI route", "; ".join(result.errors))

    def test_approved_review_creates_scheduler_payload(self):
        state = self.workflow.run_until_review(self.make_brief())
        approval = ApprovalRecord(
            content_id=state.brief.id,
            reviewer="reviewer@example.invalid",
            decision=ReviewDecision.APPROVED,
            brand_score=95,
            fact_check_passed=True,
            privacy_check_passed=True,
            ai_disclosure_check_passed=True,
        )
        result = self.workflow.resume_after_review(state, approval)
        self.assertEqual(result.brief.status, ContentStatus.READY_TO_SCHEDULE)
        self.assertEqual(result.next_step, "scheduler")
        self.assertEqual(result.scheduler_payload["status"], "draft_only_requires_final_platform_approval")
        self.assertEqual(result.scheduler_payload["copy"], result.brief.public_copy)
        self.assertEqual(result.scheduler_payload["generation"], result.brief.generation)
        self.assertEqual(result.scheduler_payload["channel_copy"], result.brief.channel_copy)
        self.assertEqual(result.scheduler_payload["postiz_mode"], "draft_only")
        self.assertEqual(result.scheduler_payload["evidence_records"][0]["id"], "Kampagnen/kampagne_1_consulting_qa.json")

    def test_missing_proof_stops_before_drafting(self):
        brief = self.make_brief()
        brief.proof_sources = []
        state = self.workflow.run_until_review(brief)
        self.assertEqual(state.brief.status, ContentStatus.BLOCKED)
        self.assertIn("at least one proof source is required", state.errors)

    def test_unknown_proof_source_stops_before_drafting(self):
        brief = self.make_brief()
        brief.proof_sources = ["Kampagnen/unapproved_claim.json"]

        state = self.workflow.run_until_review(brief)

        self.assertEqual(state.brief.status, ContentStatus.BLOCKED)
        self.assertIn("proof source is not in approved evidence vault", "; ".join(state.errors))

    def test_weak_approval_routes_to_revision_not_scheduler(self):
        state = self.workflow.run_until_review(self.make_brief())
        approval = ApprovalRecord(
            content_id=state.brief.id,
            reviewer="reviewer@example.invalid",
            decision=ReviewDecision.APPROVED,
            brand_score=89,
            fact_check_passed=True,
            privacy_check_passed=True,
            ai_disclosure_check_passed=True,
        )
        result = self.workflow.resume_after_review(state, approval)
        self.assertEqual(result.brief.status, ContentStatus.REVISION_REQUESTED)
        self.assertEqual(result.next_step, "revision")
        self.assertEqual(result.scheduler_payload, {})

    def test_blocked_state_cannot_be_approved(self):
        brief = self.make_brief()
        brief.proof_sources = []
        state = self.workflow.run_until_review(brief)
        approval = ApprovalRecord(
            content_id=brief.id,
            reviewer="reviewer@example.invalid",
            decision=ReviewDecision.APPROVED,
            brand_score=100,
            fact_check_passed=True,
            privacy_check_passed=True,
            ai_disclosure_check_passed=True,
        )

        result = self.workflow.resume_after_review(state, approval)

        self.assertEqual(result.brief.status, ContentStatus.BLOCKED)
        self.assertEqual(result.next_step, "blocked")
        self.assertEqual(result.scheduler_payload, {})
        self.assertIsNone(result.approval)
        self.assertIn("blocked content cannot be approved", "; ".join(result.errors))

    def test_evidence_is_revalidated_at_approval_time(self):
        state = self.workflow.run_until_review(self.make_brief())
        state.brief.proof_sources = ["Kampagnen/removed-after-drafting.json"]
        approval = ApprovalRecord(
            content_id=state.brief.id,
            reviewer="reviewer@example.invalid",
            decision=ReviewDecision.APPROVED,
            brand_score=100,
            fact_check_passed=True,
            privacy_check_passed=True,
            ai_disclosure_check_passed=True,
        )

        result = self.workflow.resume_after_review(state, approval)

        self.assertEqual(result.brief.status, ContentStatus.BLOCKED)
        self.assertEqual(result.next_step, "blocked")
        self.assertIn("not in approved evidence vault", "; ".join(result.errors))

    def test_trend_gate_requires_two_independent_public_sources(self):
        brief = self.make_brief()
        brief.content_mode = "current_trend"
        brief.trend_id = "trend-1"
        brief.trend_summary = "Aktuelles QA-Signal"
        brief.trend_sources = ["https://example.test/a", "https://example.test/b"]
        brief.trend_verification_status = "verified_recent"

        state = self.workflow.run_until_review(brief)

        self.assertEqual(state.brief.status, ContentStatus.BLOCKED)
        self.assertIn("two independent domains", "; ".join(state.errors))

    def test_workflow_calls_injected_ai_client(self):
        payload = release_quality_model_payload("k1")

        class FakeClient:
            provider = "fake-local"
            model = "qwen-fake"
            route_name = "local_content_draft"

            def __init__(self):
                self.called = False

            def complete_json(self, **kwargs):
                self.called = True
                return payload

        client = FakeClient()
        workflow = MarketingWorkflow(self.policy, evidence_vault=self.evidence, ai_client=client)

        state = workflow.run_until_review(self.make_brief())

        self.assertTrue(client.called)
        self.assertEqual(state.brief.generation["status"], "ai_generated")
        self.assertEqual(state.brief.generation["provider"], "fake-local")
        self.assertIn("priorisieren", state.brief.public_copy)

    def test_ai_draft_that_misses_business_quality_is_sent_to_regeneration(self):
        payload = release_quality_model_payload("k1")
        payload["channel_copy"]["headline"] = "Employer Branding prüfen"

        class LowQualityClient:
            provider = "test-local-ai"
            model = "schema-valid-but-low-quality"
            route_name = "local_content_draft"

            def complete_json(self, **_kwargs):
                return payload

        workflow = MarketingWorkflow(
            self.policy,
            evidence_vault=self.evidence,
            content_generator=ContentGenerator([LowQualityClient()]),
        )

        state = workflow.run_until_review(self.make_brief())

        self.assertEqual(state.brief.status, ContentStatus.BLOCKED)
        self.assertEqual(state.next_step, "regenerate")
        self.assertFalse(state.requires_human_review)
        self.assertFalse(state.brief.quality_evaluation["release_ready"])
        self.assertTrue(state.brief.quality_evaluation["hard_blockers"])
        self.assertIn("content quality gate failed", "; ".join(state.errors))

    def test_quality_is_recomputed_when_a_stored_draft_is_tampered_before_approval(self):
        state = self.workflow.run_until_review(self.make_brief())
        self.assertTrue(state.brief.quality_evaluation["release_ready"])
        state.brief.public_copy = state.brief.public_copy.replace(state.brief.cta, "")
        approval = ApprovalRecord(
            content_id=state.brief.id,
            reviewer="reviewer@example.invalid",
            decision=ReviewDecision.APPROVED,
            brand_score=100,
            fact_check_passed=True,
            privacy_check_passed=True,
            ai_disclosure_check_passed=True,
        )

        result = self.workflow.resume_after_review(state, approval)

        self.assertEqual(result.brief.status, ContentStatus.BLOCKED)
        self.assertEqual(result.next_step, "blocked")
        self.assertFalse(result.brief.quality_evaluation["release_ready"])
        self.assertEqual(result.scheduler_payload, {})
        self.assertIsNone(result.approval)

    def test_rejected_approval_blocks_content(self):
        state = self.workflow.run_until_review(self.make_brief())
        approval = ApprovalRecord(
            content_id=state.brief.id,
            reviewer="reviewer@example.invalid",
            decision=ReviewDecision.REJECTED,
            brand_score=95,
            fact_check_passed=True,
            privacy_check_passed=True,
            ai_disclosure_check_passed=True,
        )
        result = self.workflow.resume_after_review(state, approval)
        self.assertEqual(result.brief.status, ContentStatus.BLOCKED)
        self.assertEqual(result.next_step, "revision")
        self.assertEqual(result.scheduler_payload, {})

    def test_policy_blocks_unproved_private_ai_guarantees(self):
        unsafe_phrases = [
            "Ihre Daten verbleiben in Ihrer Kontrolle.",
            "Die Lösung kommt ohne externe Cloud-Dienste aus.",
            "Die Infrastruktur wird den Anforderungen an Datenschutz und Compliance gerecht.",
            "Innovation ohne Ihre Datenhoheit aufzugeben.",
        ]

        for phrase in unsafe_phrases:
            with self.subTest(phrase=phrase):
                self.assertEqual(self.policy.check_content(phrase).action.value, "deny")

    def test_people_campaign_reaches_review_but_cannot_be_approved_without_media_and_consent(self):
        campaign = next(item for item in load_campaign_catalog(self.root) if item["id"] == "k4")
        brief = ContentBrief(**default_brief_payload(campaign, content_id="k4-team-plan"))

        state = self.workflow.run_until_review(brief)

        self.assertEqual(state.brief.status, ContentStatus.NEEDS_HUMAN_REVIEW)
        self.assertEqual(state.next_step, "human_review")
        self.assertTrue(state.requires_human_review)
        self.assertEqual(state.errors, [])

        approval = ApprovalRecord(
            content_id=state.brief.id,
            reviewer="reviewer@example.invalid",
            decision=ReviewDecision.APPROVED,
            brand_score=95,
            fact_check_passed=True,
            privacy_check_passed=True,
            ai_disclosure_check_passed=True,
        )
        rejected = self.workflow.resume_after_review(state, approval)
        self.assertEqual(rejected.brief.status, ContentStatus.BLOCKED)
        self.assertIn("real video", "; ".join(rejected.errors))

        evidenced = self.workflow.run_until_review(brief)
        evidenced.approved_media_assets = [
            {
                "status": "approved",
                "media_type": "video",
                "postiz_media_id": "postiz-k4-video",
                "postiz_path": "https://postiz.invalid/k4.mp4",
                "sha256": "a" * 64,
                "reviewer": "reviewer@example.invalid",
                "approved_at": "2026-07-13T08:00:00+00:00",
                "source_ref": "creative-review:k4",
                "preview_ref": "postiz-preview:k4",
                "verification_method": "operator_postiz_ui",
                "provider_verified": True,
                "provider_sha256": "a" * 64,
                "provider_path": "https://postiz.invalid/k4.mp4",
                "provider_verification_method": "postiz_public_url_sha256",
                "consent_refs": ["consent:k4-person-1"],
                "brand_check_passed": True,
                "fact_check_passed": True,
                "privacy_check_passed": True,
                "ai_disclosure_check_passed": True,
            }
        ]
        approved = self.workflow.resume_after_review(evidenced, approval)
        self.assertEqual(approved.brief.status, ContentStatus.READY_TO_SCHEDULE)
        self.assertEqual(approved.next_step, "scheduler")


if __name__ == "__main__":
    unittest.main()
