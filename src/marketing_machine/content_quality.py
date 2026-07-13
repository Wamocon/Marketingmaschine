from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .campaign_catalog import load_campaign_catalog, resolve_campaign_id
from .content_generator import CONTENT_SCHEMA_VERSION, _campaign_claim_errors
from .governance import GovernancePolicy, PolicyAction
from .schemas import ContentBrief
from .trend_sources import source_domain


EVALUATION_SCHEMA_VERSION = "wamocon-content-quality-eval-v1"
RUBRIC_VERSION = "wamocon-k1-k5-release-rubric-v1"
RELEASE_THRESHOLD = 90.0
MINIMUM_DIMENSION_SCORE = 80.0
MAX_REFINEMENT_ATTEMPTS = 2

DIMENSION_WEIGHTS: dict[str, float] = {
    "campaign_audience_offer_fit": 20.0,
    "german_business_clarity": 15.0,
    "format_completeness": 15.0,
    "source_grounding": 20.0,
    "k4_people_assets": 10.0,
    "safety_policy": 10.0,
    "ai_provenance": 10.0,
}

AUDIENCE_PATTERNS: dict[str, str] = {
    "k1": r"(?i)\b(?:QA|Testabdeckung|Freigabeprozesse|IT-Leiter)\b",
    "k2": r"(?i)\b(?:Mittelstand|Geschäftsführer|IT-Leiter)\b",
    "k3": r"(?i)\b(?:Azubi\w*|Ausbilder|Schüler)\b",
    "k4": r"(?i)\b(?:Bewerber|B2B-Entscheider|Employer Branding)\b",
    "k5": r"(?i)\b(?:IT-Leiter|Geschäftsführer|Anwendungsportfolio)\b",
}

CROSS_CAMPAIGN_MARKERS: dict[str, tuple[str, ...]] = {
    "k1": (r"(?i)\bQA-Risikoaudit\b", r"(?i)\bTestabdeckung\b"),
    "k2": (r"(?i)\bSokrates\b", r"(?i)\bPrivate-KI\b"),
    "k3": (r"(?i)\bLFA\b", r"(?i)\bFachinformatiker-Azubis\b"),
    "k4": (r"(?i)\bEmployer Branding\b", r"(?i)\bPersonenfreigab\w*\b"),
    "k5": (r"(?i)\bmehr als 50\b", r"(?i)\bsieben Kategorien\b"),
}

RAW_TECHNICAL_PATTERN = re.compile(
    r"(?i)(?:"
    r"\bJSON\b|\bAPI(?:[_-][A-Z0-9]+)?\b|\bEndpoint\b|\bPayload\b|\bSchema\b|"
    r"\bProvider\b|\bModel[-_ ]?ID\b|\bLatency\b|\bToken(?:s)?\b|"
    r"\bWorkflow\b|\bn8n\b|\bComfyUI\b|\bDocker\b|\bSHA-?256\b|"
    r"\bFallback\b|\bPrompt\b|\bRuntime\b|\bHTTP\b|\bStack\s*Trace\b|"
    r"\bLangGraph\b|\bSQL\b|\bPython\b"
    r")"
)

RAW_FIELD_LABEL_PATTERN = re.compile(
    r"(?im)(?:^|\n)\s*(?:headline|body|caption|hook|shot[ _-]?list|"
    r"editing[ _-]?notes|review[ _-]?notes|cta)\s*:"
)

INTERNAL_MATERIAL_PATTERNS = (
    re.compile(r"(?i)\b(?:interne\s+Testhypothese|internal\s+hypothesis|test\s+hypothesis)\s*:"),
    re.compile(r"(?i)\b(?:Kampagnen|Zielgruppen|config|src|runtime-data)[\\/][^\s,;]+"),
    re.compile(r"(?i)\b[A-Z]:[\\/][^\s]+"),
    re.compile(r"(?i)(?:^|[\s(])\.\.?[\\/][^\s)]+"),
    re.compile(r"(?i)(?:api[_-]?key|secret|password|token)\s*[:=]"),
)

FALSE_LIFECYCLE_PATTERN = re.compile(
    r"(?i)\b(?:ist|wurde|wird)\s+(?:bereits\s+)?"
    r"(?:freigegeben|genehmigt|terminiert|eingeplant|veröffentlicht|publiziert)\b"
)

GERMAN_SIGNAL_PATTERN = re.compile(
    r"(?i)\b(?:der|die|das|und|für|mit|auf|als|ein|eine|wie|im|zu|von|sie|ihre|"
    r"kann|wird|sind|ist)\b"
)

REEL_FIELDS = {
    "idea",
    "format",
    "hook",
    "script",
    "shot_list",
    "on_screen_text",
    "caption",
    "cta",
    "editing_notes",
}
CHANNEL_FIELDS = {
    "headline",
    "body",
    "caption",
    "cta",
    "hashtags",
    "carousel_slides",
}


class ContentQualityInputError(ValueError):
    """Raised when an evaluation input cannot identify a canonical campaign."""


@dataclass(frozen=True)
class CampaignContract:
    campaign_id: str
    name: str
    persona: str
    channel: str
    content_format: str
    offer: str
    source_ref: str
    risk_flags: tuple[str, ...]
    approved_claim: str


@dataclass(frozen=True)
class RubricCheck:
    code: str
    passed: bool
    points: float
    message: str
    remediation: str
    critical: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "status": "pass" if self.passed else "fail",
            "points": self.points,
            "earned_points": self.points if self.passed else 0.0,
            "critical": self.critical,
            "message": self.message,
            "remediation": "" if self.passed else self.remediation,
        }


def evaluate_content_quality(
    value: Mapping[str, Any],
    *,
    repo_root: Path,
) -> dict[str, Any]:
    """Evaluate one stored brief, runtime state, or captured generation result.

    The evaluator is intentionally deterministic. It never calls a model or a
    network source, and an AI judge cannot override one of its hard blockers.
    """

    candidate = normalize_content_candidate(value)
    campaign_id = resolve_campaign_id(
        str(candidate.get("campaign_id", "") or candidate.get("campaign", ""))
    )
    if not campaign_id:
        raise ContentQualityInputError("input does not identify one of the canonical K1-K5 campaigns")
    contract = _load_contracts(repo_root).get(campaign_id)
    if contract is None:
        raise ContentQualityInputError(f"canonical campaign contract is unavailable: {campaign_id}")

    dimensions = {
        "campaign_audience_offer_fit": _campaign_fit_checks(candidate, contract, repo_root),
        "german_business_clarity": _clarity_checks(candidate),
        "format_completeness": _format_checks(candidate, contract),
        "source_grounding": _grounding_checks(candidate, contract, repo_root),
        "k4_people_assets": _k4_checks(candidate, contract),
        "safety_policy": _safety_checks(candidate, repo_root),
        "ai_provenance": _provenance_checks(candidate),
    }

    dimension_results: dict[str, dict[str, Any]] = {}
    hard_blockers: list[dict[str, str]] = []
    critique: list[dict[str, str]] = []
    overall_score = 0.0
    all_dimensions_meet_minimum = True
    for dimension, weight in DIMENSION_WEIGHTS.items():
        checks = dimensions[dimension]
        result = _dimension_result(dimension, weight, checks)
        dimension_results[dimension] = result
        overall_score += float(result["weighted_score"])
        if float(result["score"]) < MINIMUM_DIMENSION_SCORE:
            all_dimensions_meet_minimum = False
        for check in checks:
            if check.passed:
                continue
            item = {
                "dimension": dimension,
                "code": check.code,
                "message": check.message,
                "remediation": check.remediation,
            }
            critique.append(item)
            if check.critical:
                hard_blockers.append(item)

    score = round(overall_score, 2)
    release_ready = (
        score >= RELEASE_THRESHOLD
        and all_dimensions_meet_minimum
        and not hard_blockers
    )
    return {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "rubric_version": RUBRIC_VERSION,
        "campaign_id": campaign_id,
        "content_id": str(candidate.get("id", "")).strip(),
        "threshold": RELEASE_THRESHOLD,
        "minimum_dimension_score": MINIMUM_DIMENSION_SCORE,
        "overall_score": score,
        "release_ready": release_ready,
        "decision": "pass" if release_ready else "fail",
        "hard_blockers": hard_blockers,
        "dimensions": dimension_results,
        "critique": critique,
        "refinement": {
            "required": not release_ready,
            "max_attempts": MAX_REFINEMENT_ATTEMPTS,
            "remaining_attempts": MAX_REFINEMENT_ATTEMPTS if not release_ready else 0,
            "stop_conditions": [
                "release_ready",
                "no_score_improvement",
                "max_attempts_reached",
            ],
            "external_ai_called": False,
            "deterministic_blockers_are_final": True,
        },
    }


def evaluate_content_payload(value: Any, *, repo_root: Path) -> dict[str, Any]:
    """Evaluate one candidate or a deterministic batch container."""

    items = extract_content_candidates(value)
    results = [evaluate_content_quality(item, repo_root=repo_root) for item in items]
    passed = sum(1 for result in results if bool(result["release_ready"]))
    return {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "rubric_version": RUBRIC_VERSION,
        "threshold": RELEASE_THRESHOLD,
        "release_ready": passed == len(results),
        "summary": {
            "total": len(results),
            "passed": passed,
            "failed": len(results) - passed,
        },
        "results": results,
    }


def extract_content_candidates(value: Any) -> list[Mapping[str, Any]]:
    items: list[Any]
    if isinstance(value, list):
        items = value
    elif isinstance(value, Mapping) and "items" in value:
        raw_items = value.get("items")
        if not isinstance(raw_items, list):
            raise ContentQualityInputError("items must be a JSON array")
        items = raw_items
    elif isinstance(value, Mapping):
        items = [value]
    else:
        raise ContentQualityInputError("input must be a JSON object, array, or object with items")
    if not items:
        raise ContentQualityInputError("input does not contain any content candidates")
    if any(not isinstance(item, Mapping) for item in items):
        raise ContentQualityInputError("every content candidate must be a JSON object")
    return [item for item in items if isinstance(item, Mapping)]


def normalize_content_candidate(value: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize runtime-state and generator-capture wrappers without mutation."""

    candidate = dict(value)
    brief = value.get("brief")
    if isinstance(brief, Mapping):
        candidate = dict(brief)
    for wrapper in ("generated", "generation_result", "content"):
        nested = value.get(wrapper)
        if not isinstance(nested, Mapping):
            continue
        for key, nested_value in nested.items():
            if key == "reel":
                candidate["reel_output"] = nested_value
            elif key == "provenance":
                candidate["generation"] = nested_value
            else:
                candidate[key] = nested_value
    if "reel_output" not in candidate and isinstance(candidate.get("reel"), Mapping):
        candidate["reel_output"] = candidate["reel"]
    if "generation" not in candidate and isinstance(candidate.get("provenance"), Mapping):
        candidate["generation"] = candidate["provenance"]
    return candidate


def build_refinement_request(report: Mapping[str, Any], *, attempt: int) -> dict[str, Any]:
    """Build bounded, model-agnostic repair instructions from a failed report."""

    if bool(report.get("release_ready")):
        return {
            "schema_version": EVALUATION_SCHEMA_VERSION,
            "required": False,
            "attempt": attempt,
            "max_attempts": MAX_REFINEMENT_ATTEMPTS,
            "failures": [],
            "external_ai_called": False,
        }
    if attempt < 0 or attempt >= MAX_REFINEMENT_ATTEMPTS:
        raise ValueError(
            f"refinement attempt must be between 0 and {MAX_REFINEMENT_ATTEMPTS - 1}"
        )
    raw_failures = report.get("critique", [])
    failures = [dict(item) for item in raw_failures if isinstance(item, Mapping)]
    return {
        "schema_version": EVALUATION_SCHEMA_VERSION,
        "required": True,
        "attempt": attempt + 1,
        "max_attempts": MAX_REFINEMENT_ATTEMPTS,
        "remaining_after_attempt": MAX_REFINEMENT_ATTEMPTS - attempt - 1,
        "failures": failures,
        "constraints": {
            "preserve_canonical_campaign_metadata": True,
            "use_only_supplied_evidence": True,
            "do_not_override_deterministic_blockers": True,
            "return_content_schema": CONTENT_SCHEMA_VERSION,
        },
        "stop_conditions": [
            "release_ready",
            "no_score_improvement",
            "max_attempts_reached",
        ],
        "external_ai_called": False,
    }


def _load_contracts(repo_root: Path) -> dict[str, CampaignContract]:
    evidence_payload = json.loads(
        (repo_root / "config" / "evidence-vault.json").read_text(encoding="utf-8")
    )
    evidence_by_ref = {
        str(item.get("source_ref", "")): item
        for item in evidence_payload.get("items", [])
        if isinstance(item, Mapping) and bool(item.get("approved_for_public_use"))
    }
    contracts: dict[str, CampaignContract] = {}
    for campaign in load_campaign_catalog(repo_root):
        campaign_id = str(campaign.get("id", "")).strip().lower()
        if campaign_id not in AUDIENCE_PATTERNS:
            continue
        source_ref = str(campaign.get("source_ref", "")).strip()
        evidence = evidence_by_ref.get(source_ref, {})
        contracts[campaign_id] = CampaignContract(
            campaign_id=campaign_id,
            name=str(campaign.get("name", "")).strip(),
            persona=str(campaign.get("primary_persona", "")).strip(),
            channel=str(campaign.get("default_channel", "")).strip(),
            content_format=str(campaign.get("default_format", "")).strip(),
            offer=str(campaign.get("offer", "")).strip(),
            source_ref=source_ref,
            risk_flags=tuple(str(item) for item in campaign.get("default_risk_flags", [])),
            approved_claim=str(evidence.get("claim", "")).strip(),
        )
    return contracts


def _campaign_fit_checks(
    candidate: Mapping[str, Any],
    contract: CampaignContract,
    repo_root: Path,
) -> list[RubricCheck]:
    del repo_root
    public_text = _claim_text(candidate)
    risk_flags = set(_string_list(candidate.get("risk_flags")))
    required_risks = set(contract.risk_flags)
    wrong_markers: list[str] = []
    for other_id, patterns in CROSS_CAMPAIGN_MARKERS.items():
        if other_id == contract.campaign_id:
            continue
        if any(re.search(pattern, public_text) for pattern in patterns):
            wrong_markers.append(other_id)
    return [
        _check(
            "canonical_campaign_id",
            _same_text(candidate.get("campaign_id"), contract.campaign_id),
            10,
            "The content uses the canonical campaign ID.",
            f"Set campaign_id to {contract.campaign_id}.",
        ),
        _check(
            "canonical_campaign_name",
            _same_text(candidate.get("campaign"), contract.name),
            12,
            "The campaign name matches the canonical campaign.",
            "Restore the campaign name from the five-campaign catalog.",
        ),
        _check(
            "canonical_persona",
            _same_text(candidate.get("persona"), contract.persona),
            13,
            "The intended audience matches the canonical campaign.",
            f"Use the canonical audience: {contract.persona}.",
        ),
        _check(
            "canonical_channel",
            _same_text(candidate.get("channel"), contract.channel),
            10,
            "The channel matches the canonical campaign.",
            f"Use the canonical channel: {contract.channel}.",
        ),
        _check(
            "canonical_format",
            _same_text(candidate.get("format"), contract.content_format),
            10,
            "The content format matches the canonical campaign.",
            f"Use the canonical format: {contract.content_format}.",
        ),
        _check(
            "canonical_offer",
            _same_text(candidate.get("cta"), contract.offer),
            15,
            "The offer matches the canonical campaign.",
            f"Use the exact offer: {contract.offer}.",
        ),
        _check(
            "public_offer_present",
            _contains_text(str(candidate.get("public_copy", "")), contract.offer),
            10,
            "The public copy contains the exact campaign offer.",
            "Add the exact campaign offer to the final public copy.",
        ),
        _check(
            "audience_relevance",
            bool(re.search(AUDIENCE_PATTERNS[contract.campaign_id], public_text)),
            10,
            "The copy uses a campaign-specific audience or decision context.",
            "Frame the copy for the canonical audience without inventing persona facts.",
        ),
        _check(
            "no_cross_campaign_mix",
            not wrong_markers,
            5,
            "The output does not mix claims or offers from another campaign.",
            f"Remove cross-campaign material from: {', '.join(wrong_markers)}.",
        ),
        _check(
            "canonical_risk_flags",
            required_risks.issubset(risk_flags),
            5,
            "The campaign's mandatory review flags are retained.",
            "Restore every mandatory risk flag from the canonical campaign.",
        ),
    ]


def _clarity_checks(candidate: Mapping[str, Any]) -> list[RubricCheck]:
    public_copy = str(candidate.get("public_copy", "")).strip()
    user_visible = _user_visible_text(candidate)
    german_signals = {match.group(0).casefold() for match in GERMAN_SIGNAL_PATTERN.finditer(user_visible)}
    return [
        _check(
            "german_locale",
            str(candidate.get("language", "de-DE")).strip().lower().replace("_", "-")
            in {"de", "de-de"},
            20,
            "The output is marked for German business users.",
            "Set language to de-DE and regenerate the public wording in German.",
        ),
        _check(
            "no_raw_technical_terms",
            RAW_TECHNICAL_PATTERN.search(user_visible) is None,
            35,
            "The marketing output contains no backend or implementation terminology.",
            "Replace backend terminology with a plain-language business outcome or action.",
        ),
        _check(
            "no_raw_field_labels",
            RAW_FIELD_LABEL_PATTERN.search(user_visible) is None,
            20,
            "The copy reads as finished content rather than raw model fields.",
            "Remove raw field labels and present the result as finished marketing content.",
        ),
        _check(
            "german_language_signal",
            len(german_signals) >= 3,
            15,
            "The visible wording has a clear German-language signal.",
            "Rewrite the visible wording as natural, concise German business copy.",
            critical=False,
        ),
        _check(
            "business_readability",
            len(public_copy) >= 80 and "```" not in user_visible,
            10,
            "The public copy is complete and readable without code formatting.",
            "Provide a complete public caption or post of at least 80 characters without code blocks.",
            critical=False,
        ),
    ]


def _format_checks(
    candidate: Mapping[str, Any],
    contract: CampaignContract,
) -> list[RubricCheck]:
    channel = _mapping(candidate.get("channel_copy"))
    reel = _mapping(candidate.get("reel_output"))
    if contract.content_format == "reel":
        return _reel_format_checks(candidate, channel, reel, contract)
    if "carousel" in contract.content_format:
        return _carousel_format_checks(candidate, channel, reel, contract)
    return _post_format_checks(candidate, channel, reel, contract)


def _post_format_checks(
    candidate: Mapping[str, Any],
    channel: Mapping[str, Any],
    reel: Mapping[str, Any],
    contract: CampaignContract,
) -> list[RubricCheck]:
    return [
        _check(
            "structured_contract",
            _has_channel_contract(channel) and _has_reel_contract(reel),
            20,
            "The post follows the structured content contract.",
            "Return every channel_copy and reel field from the content schema.",
        ),
        _check(
            "public_copy",
            bool(str(candidate.get("public_copy", "")).strip()),
            10,
            "The final public post is present.",
            "Render the final public post from the structured fields.",
        ),
        _check(
            "headline",
            bool(str(channel.get("headline", "")).strip()),
            15,
            "The post has a headline.",
            "Add a concise German headline.",
        ),
        _check(
            "body",
            bool(str(channel.get("body", "")).strip()),
            25,
            "The post has a complete body.",
            "Add the approved claim, a useful framing question, and no invented outcome.",
        ),
        _check(
            "channel_cta",
            _same_text(channel.get("cta"), contract.offer),
            20,
            "The structured post contains the exact CTA.",
            f"Set channel_copy.cta to: {contract.offer}.",
        ),
        _check(
            "no_carousel_payload",
            not _string_list(channel.get("carousel_slides")),
            5,
            "The post does not carry an unrelated carousel payload.",
            "Remove carousel slides from this expert post.",
        ),
        _check(
            "empty_reel_contract",
            _is_empty_reel_contract(reel),
            5,
            "The unused reel object is present and empty.",
            "Return the required empty reel contract for a non-reel format.",
        ),
    ]


def _carousel_format_checks(
    candidate: Mapping[str, Any],
    channel: Mapping[str, Any],
    reel: Mapping[str, Any],
    contract: CampaignContract,
) -> list[RubricCheck]:
    slides = _string_list(channel.get("carousel_slides"))
    return [
        _check(
            "structured_contract",
            _has_channel_contract(channel) and _has_reel_contract(reel),
            15,
            "The carousel follows the structured content contract.",
            "Return every channel_copy and reel field from the content schema.",
        ),
        _check(
            "public_copy",
            bool(str(candidate.get("public_copy", "")).strip()),
            10,
            "The final public carousel post is present.",
            "Render the final public copy for the carousel.",
        ),
        _check(
            "headline",
            bool(str(channel.get("headline", "")).strip()),
            10,
            "The carousel has a headline.",
            "Add a concise German carousel headline.",
        ),
        _check(
            "body",
            bool(str(channel.get("body", "")).strip()),
            15,
            "The carousel has a supporting post body.",
            "Add a concise body grounded in the approved claim.",
        ),
        _check(
            "channel_cta",
            _same_text(channel.get("cta"), contract.offer),
            15,
            "The carousel contains the exact CTA.",
            f"Set channel_copy.cta to: {contract.offer}.",
        ),
        _check(
            "slide_count",
            3 <= len(slides) <= 10,
            20,
            "The carousel contains three to ten slides.",
            "Provide three to ten concise, evidence-bound slides.",
        ),
        _check(
            "nonempty_slides",
            bool(slides) and all(item.strip() for item in slides),
            5,
            "Every carousel slide contains usable copy.",
            "Remove empty slides and complete each remaining slide.",
        ),
        _check(
            "cta_slide",
            any(_contains_text(item, contract.offer) for item in slides),
            5,
            "A carousel slide contains the exact CTA.",
            "Use the exact campaign CTA on the final slide.",
        ),
        _check(
            "empty_reel_contract",
            _is_empty_reel_contract(reel),
            5,
            "The unused reel object is present and empty.",
            "Return the required empty reel contract for a non-reel format.",
        ),
    ]


def _reel_format_checks(
    candidate: Mapping[str, Any],
    channel: Mapping[str, Any],
    reel: Mapping[str, Any],
    contract: CampaignContract,
) -> list[RubricCheck]:
    script = _string_list(reel.get("script"))
    shots = _string_list(reel.get("shot_list"))
    on_screen = _string_list(reel.get("on_screen_text"))
    plan_text = "\n".join([*script, *on_screen])
    caption = str(reel.get("caption", "")).strip()
    return [
        _check(
            "structured_contract",
            _has_channel_contract(channel) and _has_reel_contract(reel),
            15,
            "The reel follows the structured content contract.",
            "Return every channel_copy and reel field from the content schema.",
        ),
        _check(
            "public_copy",
            bool(str(candidate.get("public_copy", "")).strip()),
            10,
            "The final reel caption is present.",
            "Render the final reel caption and CTA as public copy.",
        ),
        _check("reel_idea", bool(str(reel.get("idea", "")).strip()), 5, "The reel has an idea.", "Add a practical reel idea."),
        _check("reel_format", bool(str(reel.get("format", "")).strip()), 5, "The reel format is defined.", "Describe the production format."),
        _check("reel_hook", bool(str(reel.get("hook", "")).strip()), 10, "The reel has a hook.", "Add a concise German hook."),
        _check("reel_script", len(script) >= 3, 15, "The reel has at least three script beats.", "Provide at least three evidence-bound script beats."),
        _check("shot_list", len(shots) >= 3, 15, "The reel has at least three shots.", "Provide at least three practical production shots."),
        _check("on_screen_text", len(on_screen) >= 2, 10, "The reel has usable on-screen text.", "Provide at least two on-screen text beats."),
        _check(
            "caption_consistency",
            bool(caption) and _same_text(channel.get("caption"), caption),
            5,
            "The channel and reel captions are complete and consistent.",
            "Use the same complete caption in reel.caption and channel_copy.caption.",
        ),
        _check(
            "reel_cta",
            _same_text(reel.get("cta"), contract.offer)
            and _same_text(channel.get("cta"), contract.offer),
            5,
            "The reel and channel objects contain the exact CTA.",
            f"Set both CTA fields to: {contract.offer}.",
        ),
        _check(
            "cta_in_production_plan",
            _contains_text(plan_text, contract.offer),
            3,
            "The production plan includes the exact CTA end card or beat.",
            "Add the exact CTA to the script or on-screen end card.",
        ),
        _check(
            "editing_notes",
            bool(str(reel.get("editing_notes", "")).strip()),
            2,
            "The reel includes concise editing guidance.",
            "Add practical editing guidance for the marketing operator.",
        ),
    ]


def _grounding_checks(
    candidate: Mapping[str, Any],
    contract: CampaignContract,
    repo_root: Path,
) -> list[RubricCheck]:
    proof_sources = _string_list(candidate.get("proof_sources"))
    public_text = _claim_text(candidate)
    all_visible = _user_visible_text(candidate)
    citations = [item for item in candidate.get("citations", []) if isinstance(item, Mapping)] if isinstance(candidate.get("citations"), list) else []
    trend_sources = _string_list(candidate.get("trend_sources"))
    allowed_urls = set(trend_sources)
    cited_urls = [str(item.get("url", "")).strip() for item in citations]
    citation_domains = {source_domain(url) for url in cited_urls if source_domain(url)}
    trend_backed = bool(str(candidate.get("trend_id", "")).strip())
    citation_allowlist_ok = all(url in allowed_urls and bool(source_domain(url)) for url in cited_urls)
    if trend_backed:
        citation_sufficiency = len(set(cited_urls)) >= 2 and len(citation_domains) >= 2
    else:
        citation_sufficiency = not citations or citation_allowlist_ok
    citation_metadata_ok = all(
        bool(str(item.get("url", "")).strip())
        and bool(str(item.get("label", "")).strip())
        and bool(str(item.get("supports", "")).strip())
        for item in citations
    )
    wrong_internal_sources = [
        source
        for source in proof_sources
        if source != contract.source_ref and source.startswith("Kampagnen/")
    ]
    claim_errors = _campaign_claim_boundary_errors(candidate, public_text)
    unsupported_quantities = _unsupported_quantity_claims(public_text, contract.campaign_id)
    return [
        _check(
            "canonical_proof_source",
            contract.source_ref in proof_sources,
            10,
            "The canonical approved proof source is attached.",
            f"Attach the canonical proof source: {contract.source_ref}.",
        ),
        _check(
            "approved_claim_present",
            bool(contract.approved_claim)
            and _contains_text(public_text, contract.approved_claim),
            20,
            "The public-facing result includes the exact approved claim.",
            "Use the exact claim from the approved evidence vault; do not paraphrase factual claims.",
        ),
        _check(
            "no_wrong_campaign_source",
            not wrong_internal_sources,
            5,
            "No proof source from another campaign is attached.",
            "Remove proof sources belonging to another campaign.",
        ),
        _check(
            "no_internal_source_leak",
            contract.source_ref.casefold() not in all_visible.casefold(),
            10,
            "Internal proof paths are not exposed to the audience.",
            "Remove internal file paths from all visible content fields.",
        ),
        _check(
            "citation_allowlist",
            citation_allowlist_ok,
            10,
            "Every citation is a supplied, public, valid source URL.",
            "Use only supplied public trend URLs; remove invented or private URLs.",
        ),
        _check(
            "trend_citation_sufficiency",
            citation_sufficiency,
            10,
            "Trend-backed content has at least two independent cited domains.",
            "For a selected trend, cite at least two supplied URLs from independent domains.",
        ),
        _check(
            "citation_metadata",
            citation_metadata_ok,
            5,
            "Every citation explains what it supports.",
            "Add a readable label and a specific supports statement to each citation.",
        ),
        _check(
            "no_unsupported_quantities",
            not unsupported_quantities,
            10,
            "The copy contains no unsupported numerical result or scale claim.",
            "Remove unsupported numbers or add an approved source and a campaign-approved claim.",
        ),
        _check(
            "campaign_claim_boundary",
            not claim_errors,
            20,
            "The wording stays inside the campaign's approved factual boundary.",
            "Remove unsupported capability, outcome, architecture, authenticity, or delivery claims: "
            + "; ".join(claim_errors),
        ),
    ]


def _k4_checks(
    candidate: Mapping[str, Any],
    contract: CampaignContract,
) -> list[RubricCheck]:
    if contract.campaign_id != "k4":
        return [
            _check(
                "not_applicable",
                True,
                100,
                "People-consent production controls are specific to K4.",
                "",
            )
        ]
    risk_flags = set(_string_list(candidate.get("risk_flags")))
    reel = _mapping(candidate.get("reel_output"))
    production_text = "\n".join(_flatten_text(reel))
    public_text = _claim_text(candidate)
    consent_present = bool(
        re.search(
            r"(?is)\b(?:Einwilligung\w*|Personenfreigab\w*|Freigabe\w*)\b"
            r".{0,80}\b(?:dokumentiert|dokumentieren|erforderlich|nachweisen|Nachweis)\b|"
            r"\b(?:dokumentiert|dokumentieren|erforderlich|nachweisen|Nachweis)\b"
            r".{0,80}\b(?:Einwilligung\w*|Personenfreigab\w*|Freigabe\w*)\b",
            production_text,
        )
    )
    real_asset_present = bool(
        re.search(
            r"(?i)\b(?:reale\s+Medien|reales\s+Material|Originalaufnahmen|neu\s+filmen|"
            r"reale\s+Aufnahmen)\b",
            production_text,
        )
    )
    conditional_present = bool(
        re.search(
            r"(?i)\b(?:erst\s+nach|bevor|bis\b.{0,80}\bdokumentiert|"
            r"vor\s+der\s+Veröffentlichung)\b",
            production_text,
        )
    )
    existing_asset_claim = bool(
        re.search(
            r"(?i)\b(?:wir\s+zeigen|bereits\s+gedreht|vorhandene\s+Team-Aufnahmen|"
            r"echte\s+(?:Momente|Einblicke|Aufnahmen)|authentische\s+(?:Momente|Einblicke|Aufnahmen))\b",
            public_text,
        )
    )
    editing_notes = str(reel.get("editing_notes", ""))
    return [
        _check(
            "people_consent_risk_flag",
            "people_consent_and_real_assets_required" in risk_flags,
            15,
            "The K4 people-consent risk flag is retained.",
            "Restore the people consent and real-assets review flag.",
        ),
        _check(
            "consent_wording",
            consent_present,
            25,
            "The production plan explicitly requires consent or a person release.",
            "State that documented consent or a person release is required before use.",
        ),
        _check(
            "real_asset_wording",
            real_asset_present,
            20,
            "The production plan explicitly requires real, newly captured, or original assets.",
            "Require real approved media or newly filmed original footage.",
        ),
        _check(
            "conditional_usage",
            conditional_present,
            20,
            "Use of people assets is clearly conditional on documented approval.",
            "Use future, conditional wording such as 'erst nach dokumentierter Einwilligung'.",
        ),
        _check(
            "no_existing_asset_claim",
            not existing_asset_claim
            and bool(editing_notes.strip())
            and not FALSE_LIFECYCLE_PATTERN.search(editing_notes),
            20,
            "The draft is a production plan and does not claim released footage already exists.",
            "Remove claims of existing authentic footage and keep conditional production guidance.",
        ),
    ]


def _safety_checks(candidate: Mapping[str, Any], repo_root: Path) -> list[RubricCheck]:
    all_visible = _user_visible_text(candidate)
    policy = GovernancePolicy.from_json_file(repo_root / "config" / "governance-policy.json")
    decision = policy.check_content(all_visible)
    internal_material = any(pattern.search(all_visible) for pattern in INTERNAL_MATERIAL_PATTERNS)
    channel = _mapping(candidate.get("channel_copy"))
    hashtags = _string_list(channel.get("hashtags"))
    instagram = str(candidate.get("channel", "")).strip().casefold() == "instagram"
    return [
        _check(
            "governance_policy",
            decision.action != PolicyAction.DENY,
            40,
            "The output passes the repository's strict content-safety policy.",
            "Remove prohibited guarantees, privacy violations, deception, or unsafe claims.",
        ),
        _check(
            "no_internal_material",
            not internal_material,
            30,
            "The result exposes no secret, internal path, or test-hypothesis material.",
            "Remove secrets, internal paths, hypotheses, and implementation-only material.",
        ),
        _check(
            "no_false_lifecycle_claim",
            FALSE_LIFECYCLE_PATTERN.search(all_visible) is None,
            15,
            "The draft does not claim that approval, scheduling, or publication already happened.",
            "Describe the item as a draft or planned action until the lifecycle event is recorded.",
        ),
        _check(
            "instagram_hashtag_limit",
            not instagram or len(hashtags) <= 5,
            15,
            "Instagram content uses no more than five hashtags.",
            "Reduce the Instagram hashtag list to five or fewer relevant tags.",
        ),
    ]


def _provenance_checks(candidate: Mapping[str, Any]) -> list[RubricCheck]:
    generation = _mapping(candidate.get("generation"))
    provider = str(generation.get("provider", "")).strip()
    model = str(generation.get("model", "")).strip()
    route = str(generation.get("route", "")).strip()
    status = str(generation.get("status", "")).strip()
    structured_mode = str(generation.get("structured_output_mode", "")).strip()
    placeholder_values = {"", "unknown", "none", "n/a", "deterministic_rules", "wamocon-safe-copy-v1"}
    validation_failures = _safe_int(generation.get("validation_failures"), default=-1)
    attempts = _safe_int(generation.get("attempts"), default=-1)
    bounded = attempts >= 1 and 0 <= validation_failures <= MAX_REFINEMENT_ATTEMPTS
    return [
        _check(
            "ai_generated_status",
            status == "ai_generated",
            20,
            "The result is explicitly recorded as AI-generated.",
            "Generate the content through the configured AI route and record ai_generated provenance.",
        ),
        _check(
            "no_fallback",
            generation.get("fallback_used") is False,
            25,
            "No deterministic or alternate-route fallback was used.",
            "Treat fallback output as a failed draft and rerun the primary governed AI route.",
        ),
        _check(
            "content_schema_version",
            str(generation.get("schema_version", "")) == CONTENT_SCHEMA_VERSION,
            15,
            "The provenance names the current structured content schema.",
            f"Record schema_version as {CONTENT_SCHEMA_VERSION}.",
        ),
        _check(
            "provider_and_model",
            provider.casefold() not in placeholder_values
            and model.casefold() not in placeholder_values,
            15,
            "The real AI provider and model are recorded.",
            "Record non-placeholder provider and model identifiers from the model response.",
        ),
        _check(
            "model_route",
            bool(route),
            10,
            "The governed model route is recorded.",
            "Record the configured model route used for generation.",
        ),
        _check(
            "no_generation_error",
            not str(generation.get("error", "")).strip()
            and not str(generation.get("fallback_reason", "")).strip(),
            5,
            "The successful generation has no fallback reason or error.",
            "Resolve generation errors; do not mark a failed or fallback call as successful.",
        ),
        _check(
            "bounded_validation",
            bounded,
            5,
            "Validation and refinement stayed inside the bounded retry contract.",
            f"Record at least one attempt and no more than {MAX_REFINEMENT_ATTEMPTS} semantic validation failures.",
        ),
        _check(
            "structured_output_mode",
            bool(structured_mode) and structured_mode != "deterministic",
            5,
            "The AI structured-output mode is recorded.",
            "Record the AI server's JSON or JSON-schema compatibility mode.",
        ),
    ]


def _campaign_claim_boundary_errors(
    candidate: Mapping[str, Any],
    public_text: str,
) -> list[str]:
    brief = ContentBrief(
        id=str(candidate.get("id", "quality-eval")) or "quality-eval",
        campaign=str(candidate.get("campaign", "")),
        persona=str(candidate.get("persona", "")),
        channel=str(candidate.get("channel", "")),
        format=str(candidate.get("format", "")),
        objective=str(candidate.get("objective", "")),
        cta=str(candidate.get("cta", "")),
        proof_sources=_string_list(candidate.get("proof_sources")),
        utm={},
        hypothesis="",
        test_variable="quality_eval",
        campaign_id=str(candidate.get("campaign_id", "")),
    )
    return _campaign_claim_errors(brief, public_text)


def _unsupported_quantity_claims(text: str, campaign_id: str) -> list[str]:
    matches = re.findall(
        r"(?i)\b\d+(?:[.,]\d+)?\s*(?:%|Prozent|€|Euro|Jahre|Monate|Tage|"
        r"Kunden|Projekte|Nutzer|Anwendungen|Apps?)\b",
        text,
    )
    allowed = {"50 Anwendungen"} if campaign_id == "k5" else set()
    return [match for match in matches if _normalized_text(match) not in {_normalized_text(item) for item in allowed}]


def _dimension_result(
    dimension: str,
    weight: float,
    checks: Sequence[RubricCheck],
) -> dict[str, Any]:
    available = sum(check.points for check in checks)
    earned = sum(check.points for check in checks if check.passed)
    score = round((earned / available) * 100, 2) if available else 0.0
    return {
        "weight": weight,
        "score": score,
        "weighted_score": round(weight * score / 100, 2),
        "status": "pass" if all(check.passed for check in checks) else "fail",
        "minimum_score_met": score >= MINIMUM_DIMENSION_SCORE,
        "checks": [check.to_dict() for check in checks],
        "name": dimension,
    }


def _check(
    code: str,
    passed: bool,
    points: float,
    message: str,
    remediation: str,
    *,
    critical: bool = True,
) -> RubricCheck:
    return RubricCheck(
        code=code,
        passed=bool(passed),
        points=points,
        message=message,
        remediation=remediation,
        critical=critical,
    )


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if isinstance(item, str) and item.strip()]


def _flatten_text(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        result: list[str] = []
        for item in value.values():
            result.extend(_flatten_text(item))
        return result
    if isinstance(value, list):
        result = []
        for item in value:
            result.extend(_flatten_text(item))
        return result
    return []


def _user_visible_text(candidate: Mapping[str, Any]) -> str:
    values: list[str] = [str(candidate.get("public_copy", ""))]
    values.extend(_flatten_text(candidate.get("channel_copy")))
    values.extend(_flatten_text(candidate.get("reel_output")))
    return "\n".join(item for item in values if item)


def _claim_text(candidate: Mapping[str, Any]) -> str:
    channel = _mapping(candidate.get("channel_copy"))
    reel = _mapping(candidate.get("reel_output"))
    values = [
        str(candidate.get("public_copy", "")),
        str(channel.get("headline", "")),
        str(channel.get("body", "")),
        str(channel.get("caption", "")),
        *_string_list(channel.get("carousel_slides")),
        str(reel.get("hook", "")),
        *_string_list(reel.get("script")),
        *_string_list(reel.get("on_screen_text")),
        str(reel.get("caption", "")),
        str(reel.get("cta", "")),
    ]
    return "\n".join(item for item in values if item)


def _normalized_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().strip(". ").casefold()


def _same_text(left: Any, right: Any) -> bool:
    return bool(_normalized_text(left)) and _normalized_text(left) == _normalized_text(right)


def _contains_text(haystack: str, needle: str) -> bool:
    return bool(_normalized_text(needle)) and _normalized_text(needle) in _normalized_text(haystack)


def _has_channel_contract(channel: Mapping[str, Any]) -> bool:
    if set(channel) != CHANNEL_FIELDS:
        return False
    return (
        all(isinstance(channel.get(field), str) for field in ("headline", "body", "caption", "cta"))
        and isinstance(channel.get("hashtags"), list)
        and isinstance(channel.get("carousel_slides"), list)
    )


def _has_reel_contract(reel: Mapping[str, Any]) -> bool:
    if set(reel) != REEL_FIELDS:
        return False
    return (
        all(
            isinstance(reel.get(field), str)
            for field in ("idea", "format", "hook", "caption", "cta", "editing_notes")
        )
        and all(isinstance(reel.get(field), list) for field in ("script", "shot_list", "on_screen_text"))
    )


def _is_empty_reel_contract(reel: Mapping[str, Any]) -> bool:
    if not _has_reel_contract(reel):
        return False
    return all(not value for value in reel.values())


def _safe_int(value: Any, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def failed_check_codes(report: Mapping[str, Any]) -> set[str]:
    """Return stable fully-qualified failure codes for tests and release tooling."""

    codes: set[str] = set()
    dimensions = report.get("dimensions", {})
    if not isinstance(dimensions, Mapping):
        return codes
    for dimension, raw_result in dimensions.items():
        result = _mapping(raw_result)
        checks = result.get("checks", [])
        if not isinstance(checks, Iterable):
            continue
        for raw_check in checks:
            check = _mapping(raw_check)
            if check.get("status") == "fail":
                codes.add(f"{dimension}.{check.get('code', '')}")
    return codes
