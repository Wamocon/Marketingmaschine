from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from .quality import german_market_language_errors


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ContentStatus(str, Enum):
    DRAFTING = "drafting"
    NEEDS_EVIDENCE = "needs_evidence"
    NEEDS_HUMAN_REVIEW = "needs_human_review"
    REVISION_REQUESTED = "revision_requested"
    APPROVED = "approved"
    READY_TO_SCHEDULE = "ready_to_schedule"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    BLOCKED = "blocked"


class ReviewDecision(str, Enum):
    APPROVED = "approved"
    MINOR_REVISION = "minor_revision"
    MAJOR_REVISION = "major_revision"
    REJECTED = "rejected"


class OptimizationAction(str, Enum):
    SCALE = "scale"
    ITERATE = "iterate"
    FIX_LANDING_PAGE = "fix_landing_page"
    FIX_AUDIENCE_OR_OFFER = "fix_audience_or_offer"
    STOP = "stop"
    WAIT_FOR_MORE_DATA = "wait_for_more_data"


@dataclass
class ContentBrief:
    id: str
    campaign: str
    persona: str
    channel: str
    format: str
    objective: str
    cta: str
    proof_sources: list[str]
    utm: dict[str, str]
    hypothesis: str
    test_variable: str
    language: str = "de-DE"
    status: ContentStatus = ContentStatus.DRAFTING
    risk_flags: list[str] = field(default_factory=list)
    hashtags: list[str] = field(default_factory=list)
    trend_id: str = ""
    trend_summary: str = ""
    trend_sources: list[str] = field(default_factory=list)
    reel_concept: dict[str, Any] = field(default_factory=dict)
    user_prompt: str = ""
    draft: str = ""
    public_copy: str = ""
    review_notes: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def validate(self) -> list[str]:
        errors: list[str] = []
        required = {
            "id": self.id,
            "campaign": self.campaign,
            "persona": self.persona,
            "channel": self.channel,
            "format": self.format,
            "objective": self.objective,
            "cta": self.cta,
            "hypothesis": self.hypothesis,
            "test_variable": self.test_variable,
            "language": self.language,
        }
        for key, value in required.items():
            if not value:
                errors.append(f"{key} is required")
        for utm_key in ("utm_source", "utm_medium", "utm_campaign"):
            if not self.utm.get(utm_key):
                errors.append(f"{utm_key} is required")
        if not self.proof_sources:
            errors.append("at least one proof source is required")
        if self.channel.lower() == "instagram" and len(self.hashtags) > 5:
            errors.append("instagram posts must use no more than 5 hashtags")
        errors.extend(german_market_language_errors(self))
        return errors

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


@dataclass
class ApprovalRecord:
    content_id: str
    reviewer: str
    decision: ReviewDecision
    brand_score: int
    fact_check_passed: bool
    privacy_check_passed: bool
    ai_disclosure_check_passed: bool
    notes: str = ""
    created_at: str = field(default_factory=utc_now)

    @property
    def is_publishable(self) -> bool:
        return (
            self.decision == ReviewDecision.APPROVED
            and self.brand_score >= 90
            and self.fact_check_passed
            and self.privacy_check_passed
            and self.ai_disclosure_check_passed
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["decision"] = self.decision.value
        return data


@dataclass
class PerformanceRecord:
    content_id: str
    review_window: str
    impressions: int = 0
    saves: int = 0
    shares: int = 0
    comments_from_target_buyers: int = 0
    profile_visits: int = 0
    clicks: int = 0
    leads: int = 0
    qualified_leads: int = 0
    booked_calls: int = 0
    pipeline_value_eur: float = 0.0
    landing_page_visits: int = 0
    landing_page_conversions: int = 0
    created_at: str = field(default_factory=utc_now)

    @property
    def click_through_rate(self) -> float:
        return self.clicks / self.impressions if self.impressions else 0.0

    @property
    def lead_conversion_rate(self) -> float:
        return self.leads / self.clicks if self.clicks else 0.0

    @property
    def landing_page_conversion_rate(self) -> float:
        if not self.landing_page_visits:
            return 0.0
        return self.landing_page_conversions / self.landing_page_visits


@dataclass
class LeadRecord:
    id: str
    source_content_id: str
    campaign: str
    offer: str
    persona: str
    utm: dict[str, str]
    consent_given: bool
    company: str = ""
    email: str = ""
    contact_name: str = ""
    phone: str = ""
    message: str = ""
    qualification_score: int = 0
    next_action: str = "review"
    source_verified: bool = False
    routing_allowed: bool = False
    risk_flags: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvidenceItem:
    id: str
    claim: str
    source_type: str
    source_ref: str
    approved_for_public_use: bool
    consent_ref: str = ""
    owner: str = ""
    created_at: str = field(default_factory=utc_now)


@dataclass
class ExperimentRecord:
    id: str
    hypothesis: str
    variable: str
    campaign: str
    persona: str
    status: str = "running"
    decision: OptimizationAction = OptimizationAction.WAIT_FOR_MORE_DATA
    notes: str = ""
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
