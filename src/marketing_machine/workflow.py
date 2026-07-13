from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .content_generator import ContentGenerator, StructuredContentClient
from .content_quality import ContentQualityInputError, evaluate_content_quality
from .evidence import EvidenceVault
from .governance import AuditTrail, GovernancePolicy, PolicyAction
from .schemas import ApprovalRecord, ContentBrief, ContentStatus, ReviewDecision, utc_now
from .trend_sources import source_domain


@dataclass
class WorkflowState:
    brief: ContentBrief
    approval: ApprovalRecord | None = None
    errors: list[str] = field(default_factory=list)
    next_step: str = "orchestrator"
    requires_human_review: bool = False
    evidence_records: list[dict[str, object]] = field(default_factory=list)
    approved_media_assets: list[dict[str, Any]] = field(default_factory=list)
    scheduler_payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "brief": self.brief.to_dict(),
            "approval": self.approval.to_dict() if self.approval else None,
            "errors": self.errors,
            "next_step": self.next_step,
            "requires_human_review": self.requires_human_review,
            "evidence_records": self.evidence_records,
            "approved_media_assets": self.approved_media_assets,
            "scheduler_payload": self.scheduler_payload,
        }


class MarketingWorkflow:
    """Deterministic workflow skeleton matching the planned LangGraph graph."""

    def __init__(
        self,
        policy: GovernancePolicy,
        audit: AuditTrail | None = None,
        evidence_vault: EvidenceVault | None = None,
        content_generator: ContentGenerator | None = None,
        ai_client: StructuredContentClient | None = None,
    ) -> None:
        if content_generator is not None and ai_client is not None:
            raise ValueError("pass content_generator or ai_client, not both")
        self.policy = policy
        self.audit = audit or AuditTrail()
        self.evidence_vault = evidence_vault
        if content_generator is not None:
            self.content_generator = content_generator
        elif ai_client is not None:
            self.content_generator = ContentGenerator([ai_client])
        else:
            self.content_generator = ContentGenerator.from_environment()

    def run_until_review(self, brief: ContentBrief) -> WorkflowState:
        state = WorkflowState(brief=brief)
        self._orchestrator(state)
        if state.errors:
            return state
        self._evidence_gate(state)
        if state.errors:
            return state
        self._trend_gate(state)
        if state.errors:
            return state
        self._draft_content(state)
        self._compliance_gate(state)
        return state

    def resume_after_review(self, state: WorkflowState, approval: ApprovalRecord) -> WorkflowState:
        transition_error = self._review_transition_error(state, approval)
        if transition_error:
            self.audit.log(
                "compliance",
                "write_approval_record",
                PolicyAction.DENY.value,
                self.policy.name,
                reason=transition_error,
            )
            if transition_error not in state.errors:
                state.errors.append(transition_error)
            if state.brief.status == ContentStatus.BLOCKED:
                state.next_step = "blocked"
                state.requires_human_review = False
                state.scheduler_payload = {}
            return state

        revalidation_errors = self._approval_gate_errors(state)
        if approval.is_publishable:
            revalidation_errors.extend(
                people_media_evidence_errors(
                    state.brief,
                    state.approved_media_assets,
                )
            )
        if revalidation_errors:
            state.errors.extend(error for error in revalidation_errors if error not in state.errors)
            state.brief.status = ContentStatus.BLOCKED
            state.requires_human_review = False
            state.next_step = "blocked"
            state.scheduler_payload = {}
            self.audit.log(
                "compliance",
                "write_approval_record",
                PolicyAction.DENY.value,
                self.policy.name,
                reason="; ".join(revalidation_errors),
            )
            return state

        state.approval = approval
        self.audit.log("compliance", "write_approval_record", PolicyAction.ALLOW.value, self.policy.name)
        if approval.is_publishable:
            state.brief.status = ContentStatus.READY_TO_SCHEDULE
            state.requires_human_review = False
            state.next_step = "scheduler"
            self._create_scheduler_payload(state)
            return state

        state.requires_human_review = False
        state.next_step = "revision"
        if approval.decision == ReviewDecision.REJECTED:
            state.brief.status = ContentStatus.BLOCKED
        else:
            state.brief.status = ContentStatus.REVISION_REQUESTED
        state.errors.append("human review did not approve publication")
        return state

    def _review_transition_error(self, state: WorkflowState, approval: ApprovalRecord) -> str:
        if state.brief.status == ContentStatus.BLOCKED:
            return "blocked content cannot be approved; create or regenerate a valid draft"
        if approval.content_id != state.brief.id:
            return "approval content_id does not match the draft"
        if state.brief.status != ContentStatus.NEEDS_HUMAN_REVIEW:
            return "content is not awaiting human review"
        if not state.requires_human_review or state.next_step != "human_review":
            return "workflow is not paused at the human review gate"
        if state.errors:
            return "content with unresolved workflow errors cannot be approved"
        return ""

    def _approval_gate_errors(self, state: WorkflowState) -> list[str]:
        errors = state.brief.validate()
        if self.evidence_vault is not None:
            errors.extend(self.evidence_vault.validate_proof_sources(state.brief.proof_sources))
        errors.extend(self._trend_errors(state.brief))
        errors.extend(self._citation_errors(state.brief))
        if not state.brief.public_copy.strip():
            errors.append("publishable channel copy is missing")
        errors.extend(self._generation_gate_errors(state.brief))
        errors.extend(self._quality_gate_errors(state.brief))
        content_decision = self.policy.check_content(state.brief.public_copy)
        if content_decision.action == PolicyAction.DENY:
            errors.append(content_decision.reason)
        return _dedupe(errors)

    @staticmethod
    def _generation_gate_errors(brief: ContentBrief) -> list[str]:
        """Require the approved primary AI path, not merely AI-shaped output.

        Secondary model routes are useful for diagnostics, but their output has
        not passed the release qualification assigned to the primary local
        route.  Missing provenance also fails closed so a stored state cannot
        be made approvable by deleting the marker.
        """

        generation = brief.generation if isinstance(brief.generation, dict) else {}
        if str(generation.get("status", "")) != "ai_generated":
            return ["a successful AI-generated draft is required before approval"]
        if generation.get("fallback_used") is not False:
            return [
                "the draft was not created through the approved primary AI route; regenerate it before approval"
            ]
        return []

    @staticmethod
    def _quality_gate_errors(brief: ContentBrief) -> list[str]:
        try:
            report = evaluate_content_quality(
                brief.to_dict(),
                repo_root=Path(__file__).resolve().parents[2],
            )
        except (ContentQualityInputError, OSError, TypeError, ValueError):
            brief.quality_evaluation = {
                "release_ready": False,
                "decision": "fail",
                "evaluated_at": utc_now(),
                "hard_blockers": [{"code": "quality_evaluation_unavailable"}],
            }
            return ["deterministic content quality evaluation is unavailable"]
        report["evaluated_at"] = utc_now()
        brief.quality_evaluation = report
        if report.get("release_ready") is True:
            return []
        codes = [
            str(item.get("code", "")).strip()
            for item in report.get("hard_blockers", [])
            if isinstance(item, dict) and str(item.get("code", "")).strip()
        ]
        suffix = f": {', '.join(codes[:8])}" if codes else ""
        return [f"deterministic content quality gate failed{suffix}"]

    def _orchestrator(self, state: WorkflowState) -> None:
        decision = self.policy.check_tool("write_content_brief")
        self.audit.log("orchestrator", "write_content_brief", decision.action.value, self.policy.name, reason=decision.reason)
        if decision.action == PolicyAction.DENY:
            state.errors.append(decision.reason)
            state.brief.status = ContentStatus.BLOCKED
            return
        validation_errors = state.brief.validate()
        if validation_errors:
            state.errors.extend(validation_errors)
            state.brief.status = ContentStatus.BLOCKED
            return
        state.next_step = "evidence_gate"

    def _evidence_gate(self, state: WorkflowState) -> None:
        if not state.brief.proof_sources:
            state.errors.append("content cannot proceed without proof sources")
            state.brief.status = ContentStatus.NEEDS_EVIDENCE
            return
        if self.evidence_vault is not None:
            evidence_errors = self.evidence_vault.validate_proof_sources(state.brief.proof_sources)
            if evidence_errors:
                state.errors.extend(evidence_errors)
                state.brief.status = ContentStatus.BLOCKED
                state.next_step = "blocked"
                return
            state.evidence_records = self.evidence_vault.records_for(state.brief.proof_sources)
        self.audit.log("evidence-vault", "read_evidence_vault", PolicyAction.ALLOW.value, self.policy.name)
        state.next_step = "trend_gate"

    def _trend_gate(self, state: WorkflowState) -> None:
        errors = self._trend_errors(state.brief)
        if errors:
            state.errors.extend(errors)
            state.brief.status = ContentStatus.BLOCKED
            state.next_step = "blocked"
            self.audit.log(
                "research-agent",
                "search_public_sources",
                PolicyAction.DENY.value,
                self.policy.name,
                reason="; ".join(errors),
            )
            return
        self.audit.log("research-agent", "search_public_sources", PolicyAction.ALLOW.value, self.policy.name)
        state.next_step = "draft_content"

    def _trend_errors(self, brief: ContentBrief) -> list[str]:
        if brief.content_mode == "evergreen":
            return []
        errors: list[str] = []
        if not brief.trend_id:
            errors.append("current-trend content requires a stored trend id")
        if not brief.trend_summary.strip():
            errors.append("trend-backed content requires a trend summary")
        if not brief.trend_run_id.strip():
            errors.append("trend-backed content requires a stored trend run id")
        verification_status = brief.trend_verification_status.strip().lower()
        if verification_status != "verified_recent":
            errors.append("current-trend content requires verified_recent source status")
        valid_urls: list[str] = []
        domains: set[str] = set()
        for raw in brief.trend_sources:
            value = str(raw).strip()
            parsed = urlsplit(value)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                continue
            if value not in valid_urls:
                valid_urls.append(value)
            domain = source_domain(value)
            if domain:
                domains.add(domain)
        if len(valid_urls) < 2:
            errors.append("trend-backed content requires at least two public source URLs")
        if len(domains) < 2:
            errors.append("trend-backed content requires corroboration from two independent domains")
        return errors

    def _citation_errors(self, brief: ContentBrief) -> list[str]:
        if brief.content_mode == "evergreen":
            return []
        allowed_urls = {
            str(value).strip()
            for value in brief.trend_sources
            if urlsplit(str(value).strip()).scheme in {"http", "https"}
            and urlsplit(str(value).strip()).hostname
        }
        cited_urls = {
            str(item.get("url", "")).strip()
            for item in brief.citations
            if isinstance(item, dict) and str(item.get("url", "")).strip()
        }
        errors: list[str] = []
        if len(cited_urls) < 2:
            errors.append("trend-backed content requires at least two visible citations")
        if cited_urls - allowed_urls:
            errors.append("content citations must come from the verified trend source set")
        return errors

    def _draft_content(self, state: WorkflowState) -> None:
        generated = self.content_generator.generate(state.brief, evidence_records=state.evidence_records)
        state.brief.public_copy = generated.public_copy
        state.brief.review_notes = generated.review_notes
        state.brief.channel_copy = generated.channel_copy
        state.brief.reel_output = generated.reel
        state.brief.citations = generated.citations
        state.brief.generation = generated.provenance
        state.brief.updated_at = utc_now()
        state.brief.draft = (
            f"{generated.public_copy}\n\n"
            "Internal review notes:\n"
            + "\n".join(f"- {note}" for note in generated.review_notes)
        )
        state.brief.status = ContentStatus.DRAFTING
        self._quality_gate_errors(state.brief)
        state.next_step = "compliance_gate"
        self.audit.log(
            "campaign-agent",
            "write_draft",
            PolicyAction.ALLOW.value,
            self.policy.name,
            provider=generated.provenance.get("provider", ""),
            model=generated.provenance.get("model", ""),
            latency_ms=generated.provenance.get("latency_ms", 0),
            fallback_used=generated.provenance.get("fallback_used", False),
        )

    def _compliance_gate(self, state: WorkflowState) -> None:
        citation_errors = self._citation_errors(state.brief)
        if citation_errors:
            state.errors.extend(error for error in citation_errors if error not in state.errors)
            state.brief.status = ContentStatus.BLOCKED
            state.requires_human_review = False
            state.next_step = "blocked"
            self.audit.log(
                "compliance",
                "write_approval_record",
                PolicyAction.DENY.value,
                self.policy.name,
                reason="; ".join(citation_errors),
            )
            return
        generation_errors = self._generation_gate_errors(state.brief)
        if generation_errors:
            state.errors.extend(error for error in generation_errors if error not in state.errors)
            state.brief.status = ContentStatus.BLOCKED
            state.requires_human_review = False
            state.next_step = "regenerate"
            state.scheduler_payload = {}
            self.audit.log(
                "compliance",
                "write_approval_record",
                PolicyAction.DENY.value,
                self.policy.name,
                reason="; ".join(generation_errors),
            )
            return
        quality_errors = self._quality_gate_errors(state.brief)
        if quality_errors:
            state.errors.extend(error for error in quality_errors if error not in state.errors)
            state.brief.status = ContentStatus.BLOCKED
            state.requires_human_review = False
            state.next_step = "regenerate"
            state.scheduler_payload = {}
            self.audit.log(
                "compliance",
                "write_approval_record",
                PolicyAction.DENY.value,
                self.policy.name,
                reason="; ".join(quality_errors),
            )
            return
        content_decision = self.policy.check_content(state.brief.draft)
        self.audit.log("compliance", "write_approval_record", content_decision.action.value, self.policy.name, reason=content_decision.reason)
        if content_decision.action == PolicyAction.DENY:
            state.errors.append(content_decision.reason)
            state.brief.status = ContentStatus.BLOCKED
            state.next_step = "blocked"
            return
        brief_decision = self.policy.check_brief(state.brief)
        if brief_decision.action == PolicyAction.DENY:
            state.errors.append(brief_decision.reason)
            state.brief.status = ContentStatus.BLOCKED
            state.next_step = "blocked"
            return
        state.brief.status = ContentStatus.NEEDS_HUMAN_REVIEW
        state.requires_human_review = True
        state.next_step = "human_review"

    def _create_scheduler_payload(self, state: WorkflowState) -> None:
        decision = self.policy.check_tool("create_scheduler_payload")
        self.audit.log("scheduler", "create_scheduler_payload", decision.action.value, self.policy.name, reason=decision.reason)
        if decision.action == PolicyAction.DENY:
            state.errors.append(decision.reason)
            state.brief.status = ContentStatus.BLOCKED
            return
        state.scheduler_payload = {
            "content_id": state.brief.id,
            "campaign": state.brief.campaign,
            "channel": state.brief.channel,
            "format": state.brief.format,
            "status": "draft_only_requires_final_platform_approval",
            "utm": state.brief.utm,
            "copy": state.brief.public_copy or state.brief.draft,
            "channel_copy": state.brief.channel_copy,
            "reel": state.brief.reel_output,
            "citations": state.brief.citations,
            "generation": state.brief.generation,
            "review_notes": state.brief.review_notes,
            "evidence_records": state.evidence_records,
            "postiz_mode": "draft_only",
        }


def _dedupe(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def people_media_evidence_errors(
    brief: ContentBrief,
    approved_media_assets: list[dict[str, Any]],
) -> list[str]:
    """Validate the K4 real-media and consent gate at final approval time."""

    if "people_consent_and_real_assets_required" not in brief.risk_flags:
        return []
    active_videos = [
        asset
        for asset in approved_media_assets
        if isinstance(asset, dict)
        and asset.get("status") == "approved"
        and asset.get("media_type") == "video"
    ]
    if not active_videos:
        return [
            "K4 approval requires one active, human-approved real video with documented consent"
        ]
    for asset in active_videos:
        consent_refs = asset.get("consent_refs", [])
        required_text_fields = (
            "postiz_media_id",
            "postiz_path",
            "sha256",
            "reviewer",
            "approved_at",
            "source_ref",
            "preview_ref",
            "verification_method",
        )
        if (
            not isinstance(consent_refs, list)
            or not any(str(item).strip() for item in consent_refs)
            or any(not str(asset.get(field, "")).strip() for field in required_text_fields)
            or asset.get("verification_method") != "operator_postiz_ui"
            or asset.get("provider_verified") is not True
            or asset.get("provider_verification_method") != "postiz_public_url_sha256"
            or asset.get("provider_sha256") != asset.get("sha256")
            or asset.get("provider_path") != asset.get("postiz_path")
            or any(
                asset.get(field) is not True
                for field in (
                    "brand_check_passed",
                    "fact_check_passed",
                    "privacy_check_passed",
                    "ai_disclosure_check_passed",
                )
            )
        ):
            return [
                "K4 approval requires complete media proof and consent references for every visible person"
            ]
    return []


def build_langgraph_app(policy: GovernancePolicy) -> Any:
    """Build the production LangGraph app when langgraph is installed.

    The stdlib workflow above keeps local tests dependency-free. Production deploys
    should install the `prod` extras and use this function for durable execution.
    """

    try:
        from langgraph.graph import END, START, StateGraph
    except ImportError as exc:
        raise RuntimeError("Install production dependencies with `pip install -e .[prod]` to use LangGraph") from exc

    graph = StateGraph(dict)
    workflow = MarketingWorkflow(policy)

    def run_until_review_node(state: dict[str, Any]) -> dict[str, Any]:
        brief = state["brief"]
        result = workflow.run_until_review(brief)
        return result.to_dict()

    graph.add_node("run_until_review", run_until_review_node)
    graph.add_edge(START, "run_until_review")
    graph.add_edge("run_until_review", END)
    return graph.compile()
