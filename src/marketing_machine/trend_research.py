from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .campaign_catalog import CAMPAIGN_META, load_campaign_catalog, resolve_campaign_id
from .governance import GovernancePolicy, PolicyAction
from .schemas import ContentBrief
from .storage import JsonStore
from .trend_sources import (
    ConfiguredTrendSearchClient,
    ExternalCallBudget,
    SearchResult,
    TrendSearchClient,
    date_is_recent,
    dedupe_results,
    parse_datetime,
    platform_query,
    source_domain,
    tokens,
)


DEFAULT_PLATFORMS = ["instagram", "tiktok", "reddit", "forums", "web"]
CORROBORATION_VERSION = "exact-topic-v1"
CURRENT_TREND_FRESHNESS_DAYS = 7
DEFAULT_EXTERNAL_CALL_BUDGET = 25
MAX_TREND_CAMPAIGNS_PER_REQUEST = 5
MAX_TREND_PLATFORMS_PER_REQUEST = 5
MAX_CAMPAIGN_PLATFORM_FANOUT = 25
TREND_REQUEST_CACHE_SECONDS = 300
TOPIC_STOP_WORDS = {
    "a",
    "an",
    "and",
    "article",
    "artikel",
    "auf",
    "das",
    "de",
    "der",
    "die",
    "ein",
    "eine",
    "for",
    "für",
    "guide",
    "how",
    "im",
    "in",
    "mit",
    "of",
    "on",
    "the",
    "to",
    "und",
    "von",
    "was",
    "wie",
    "with",
    "zur",
}
GENERIC_PROMPT_WORDS = {
    "make",
    "more",
    "less",
    "like",
    "style",
    "format",
    "hook",
    "hooks",
    "video",
    "reel",
    "reels",
    "short",
    "shorts",
    "caption",
    "captions",
    "script",
    "voiceover",
    "animation",
    "animated",
    "creative",
    "funny",
    "serious",
    "professional",
    "german",
    "english",
    "deutsch",
    "question",
    "answer",
    "interview",
    "teardown",
    "myth",
    "fact",
    "pov",
    "explain",
    "explainer",
    "better",
    "different",
    "another",
    "faster",
    "slower",
    "clearer",
    "sharper",
    "bolder",
    "trend",
    "topic",
    "campaign",
    "audience",
    "intro",
    "outro",
    "cta",
    "about",
    "with",
    "without",
    "please",
    "bitte",
    "use",
    "using",
    "nutze",
    "machen",
    "mehr",
    "weniger",
    "direkt",
    "direct",
    "punchy",
    "energetic",
    "energy",
    "pace",
    "pacing",
    "schnell",
    "langsam",
    "kinetic",
    "cuts",
    "cut",
    "checklist",
    "checkliste",
    "steps",
    "schritte",
    "sachlich",
    "sachliche",
    "sachlicher",
    "sachliches",
    "klar",
    "klare",
    "klarer",
    "klares",
    "bildschirmaufnahme",
    "screenaufnahme",
    "ruhig",
    "ruhige",
    "ruhiger",
    "ruhigem",
    "tempo",
}

_TEST_VERIFICATION_CAPABILITY = object()


class _TestVerificationOverride:
    """Unforgeable-by-payload capability used only by isolated unit tests."""

    __slots__ = ("_capability", "reason")

    def __init__(self, capability: object, reason: str) -> None:
        if capability is not _TEST_VERIFICATION_CAPABILITY:
            raise TypeError("test verification overrides must be created by the test factory")
        self._capability = capability
        self.reason = reason


def _make_test_verification_override(reason: str = "isolated unit fixture") -> _TestVerificationOverride:
    """Create an in-process test capability; this is intentionally not an API payload option."""

    return _TestVerificationOverride(_TEST_VERIFICATION_CAPABILITY, reason)


def load_campaigns(root: Path) -> list[dict[str, Any]]:
    canonical_campaigns = {
        item["source_id"]: item for item in load_campaign_catalog(root)
    }
    campaigns: list[dict[str, Any]] = []
    for path in sorted((root / "Kampagnen").glob("kampagne_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        campaign = data.get("campaign", {})
        if not isinstance(campaign, dict):
            continue
        evidence_ref = path.relative_to(root).as_posix()
        canonical = canonical_campaigns.get(path.stem, {})
        campaigns.append(
            {
                "id": path.stem,
                "name": str(campaign.get("name", path.stem)),
                "description": str(campaign.get("description", "")),
                "master_prompt": str(campaign.get("masterPrompt", "")),
                "keywords": [str(item) for item in campaign.get("campaignKeywords", [])],
                "channels": [str(item) for item in campaign.get("channels", [])],
                "default_channel": str(canonical.get("default_channel", "")),
                "default_format": str(canonical.get("default_format", "")),
                "primary_persona": str(canonical.get("primary_persona", "")),
                "offer": str(canonical.get("offer", "")),
                "generation_objective": str(canonical.get("generation_objective", "")),
                "audience_profiles": [
                    dict(item) for item in canonical.get("audience_profiles", [])
                ],
                "evidence_ref": evidence_ref,
                "start_date": str(campaign.get("startDate", "")),
                "end_date": str(campaign.get("endDate", "")),
            }
        )
    return campaigns


def normalize_requested_campaign_ids(
    campaigns: list[dict[str, Any]],
    raw_campaign_ids: Any,
) -> list[str]:
    """Resolve exact business/source aliases to existing campaign source IDs.

    An omitted or empty selection means all five campaigns. Every supplied
    value must resolve, so a typo cannot silently produce an empty (or partial)
    research run. The caller's payload is intentionally left untouched because
    it is the authoritative input to request fingerprints and idempotency.
    """

    if raw_campaign_ids is None or raw_campaign_ids == [] or raw_campaign_ids == ():
        return []
    if isinstance(raw_campaign_ids, str):
        requested: list[Any] = [raw_campaign_ids]
    elif isinstance(raw_campaign_ids, (list, tuple, set)):
        requested = list(raw_campaign_ids)
    else:
        raise ValueError("campaign_ids must be an array of campaign IDs")

    source_ids = {
        str(campaign.get("id", "")).strip()
        for campaign in campaigns
        if str(campaign.get("id", "")).strip()
    }
    aliases: dict[str, str] = {}
    for source_id in source_ids:
        aliases[source_id.casefold()] = source_id
        canonical_id = str(CAMPAIGN_META.get(source_id, {}).get("id", "")).strip()
        if canonical_id:
            aliases[canonical_id.casefold()] = source_id

    normalized: list[str] = []
    for raw_id in requested:
        if not isinstance(raw_id, str):
            raise ValueError("campaign_ids must contain only campaign IDs")
        source_id = aliases.get(raw_id.strip().casefold(), "")
        if not source_id:
            raise ValueError(
                "unknown campaign selection; choose K1, K2, K3, K4, or K5"
            )
        if source_id not in normalized:
            normalized.append(source_id)
    return normalized


def normalize_requested_platforms(raw_platforms: Any) -> list[str]:
    """Return an explicit, supported source selection without silent widening.

    Omitting ``platforms`` intentionally uses the bounded default set. Once a
    caller supplies the field, however, an empty or invalid selection is an
    operator error and must not silently expand to every source (including
    forums the operator did not choose).
    """

    if raw_platforms is None:
        return list(DEFAULT_PLATFORMS)
    if not isinstance(raw_platforms, (list, tuple, set)):
        raise ValueError("platforms must be a non-empty array of supported sources")
    requested = list(raw_platforms)
    if not requested:
        raise ValueError("platforms must contain at least one source")
    normalized: list[str] = []
    for raw in requested:
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError("platforms must contain only supported source names")
        platform = raw.strip().casefold()
        if platform not in DEFAULT_PLATFORMS:
            raise ValueError(
                "unsupported source selection; choose instagram, tiktok, reddit, forums, or web"
            )
        if platform not in normalized:
            normalized.append(platform)
    if not normalized:
        raise ValueError("platforms must contain at least one source")
    return normalized[:MAX_TREND_PLATFORMS_PER_REQUEST]


def trend_request_run_id(request_id: str) -> str:
    normalized = str(request_id).strip()
    if not normalized or len(normalized) > 256:
        raise ValueError("request_id must contain 1 to 256 characters")
    return f"trend-request-{_stable_id(normalized, length=16)}"


def trend_request_fingerprint(payload: dict[str, Any]) -> str:
    return _stable_id(json.dumps(payload, sort_keys=True, ensure_ascii=False), length=24)


def run_trend_research(
    root: Path,
    *,
    payload: dict[str, Any] | None = None,
    policy: GovernancePolicy | None = None,
    search_client: TrendSearchClient | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run one bounded research request with cross-process duplicate suppression."""

    normalized_payload = payload or {}
    # Validate before consulting the idempotency cache. This prevents a legacy
    # empty run from making a now-invalid campaign selection look successful.
    normalize_requested_campaign_ids(
        load_campaigns(root),
        normalized_payload.get("campaign_ids"),
    )
    normalize_requested_platforms(
        normalized_payload.get("platforms") if "platforms" in normalized_payload else None
    )
    request_id = str(normalized_payload.get("request_id", "")).strip()
    if not request_id:
        return _run_trend_research_once(
            root,
            payload=normalized_payload,
            policy=policy,
            search_client=search_client,
            now=now,
        )

    run_id = trend_request_run_id(request_id)
    request_fingerprint = trend_request_fingerprint(normalized_payload)
    store = JsonStore()
    with store.trend_request_lock(run_id):
        cached = store.load_trend_request_cache(run_id, max_age_seconds=TREND_REQUEST_CACHE_SECONDS)
        if cached is not None:
            if cached.get("request_fingerprint") != request_fingerprint:
                raise ValueError("request_id was already used with a different trend request")
            cached_result = cached.get("result")
            if isinstance(cached_result, dict):
                return refresh_trend_run_eligibility(cached_result, now=now)

        result = _run_trend_research_once(
            root,
            payload=normalized_payload,
            policy=policy,
            search_client=search_client,
            now=now,
        )
        store.save_trend_request_cache(
            run_id,
            request_fingerprint=request_fingerprint,
            result=result,
        )
        return result


def _run_trend_research_once(
    root: Path,
    *,
    payload: dict[str, Any] | None = None,
    policy: GovernancePolicy | None = None,
    search_client: TrendSearchClient | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    payload = payload or {}
    now = now or datetime.now(timezone.utc)
    lookback_days = _int_between(payload.get("lookback_days", 10), minimum=1, maximum=30)
    limit_per_campaign = _int_between(payload.get("limit_per_campaign", 4), minimum=1, maximum=8)
    platforms = normalize_requested_platforms(
        payload.get("platforms") if "platforms" in payload else None
    )
    lookback_start = now - timedelta(days=lookback_days)

    if policy is not None:
        decision = policy.check_tool("search_public_sources")
        if decision.action == PolicyAction.DENY:
            raise ValueError(decision.reason)

    try:
        configured_call_limit = int(
            policy.max_calls_per_request if policy is not None else DEFAULT_EXTERNAL_CALL_BUDGET
        )
    except (TypeError, ValueError, OverflowError):
        configured_call_limit = 0
    call_budget = ExternalCallBudget(max(0, configured_call_limit))
    client = search_client or ConfiguredTrendSearchClient(call_budget=call_budget)
    if isinstance(client, ConfiguredTrendSearchClient):
        client.begin_request(call_budget)
    campaigns = load_campaigns(root)
    selected_campaign_ids = set(
        normalize_requested_campaign_ids(campaigns, payload.get("campaign_ids"))
    )
    if selected_campaign_ids:
        campaigns = [campaign for campaign in campaigns if campaign["id"] in selected_campaign_ids]
    campaigns = campaigns[:MAX_TREND_CAMPAIGNS_PER_REQUEST]
    search_plan, fanout = _bounded_campaign_platform_plan(
        campaigns,
        platforms,
        client=client,
        external_call_limit=call_budget.limit,
    )

    request_id = str(payload.get("request_id", "")).strip()
    run_id = (
        trend_request_run_id(request_id)
        if request_id
        else f"trend-{now.strftime('%Y%m%d%H%M%S')}-{_stable_id(json.dumps(payload, sort_keys=True), length=6)}"
    )
    campaign_results: list[dict[str, Any]] = []
    for campaign in campaigns:
        signals = _search_campaign_signals(
            campaign,
            platforms=search_plan.get(campaign["id"], []),
            lookback_start=lookback_start,
            now=now,
            client=client,
        )
        campaign_results.append(
            {
                "campaign": campaign,
                "trends": _build_campaign_trends(
                    campaign,
                    signals=signals,
                    run_id=run_id,
                    lookback_start=lookback_start,
                    now=now,
                    limit=limit_per_campaign,
                ),
                "raw_signal_count": len(signals),
            }
        )

    all_trends = [trend for result in campaign_results for trend in result["trends"]]
    if trend_run_has_verified_sources({"campaigns": campaign_results}, now=now):
        status = "verified_sources"
    elif any(_external_evidence_count(trend) for trend in all_trends):
        status = "needs_source_verification"
    else:
        status = "needs_live_sources"
    source_telemetry = client.telemetry()
    successful_adapters = [
        item["adapter"]
        for item in source_telemetry
        if item.get("result_count") and item.get("status") in {"success", "partial"}
    ]
    source_errors = [
        {"adapter": item.get("adapter", ""), **error}
        for item in source_telemetry
        for error in item.get("errors", [])
        if isinstance(error, dict)
    ]
    actual_platforms = [
        platform
        for platform in platforms
        if any(platform in planned for planned in search_plan.values())
    ]
    if isinstance(client, ConfiguredTrendSearchClient):
        external_call_budget: dict[str, Any] = client.budget_telemetry() or call_budget.snapshot()
        external_call_budget["measurement"] = "adapter_calls"
    else:
        external_call_budget = {
            "limit": call_budget.limit,
            "used": None,
            "remaining": None,
            "denied": None,
            "exhausted": fanout["allocated_external_calls"] >= call_budget.limit,
            "measurement": "custom_client_not_instrumented",
        }
    return {
        "id": run_id,
        "request_id": request_id,
        "request_fingerprint": trend_request_fingerprint(payload) if request_id else "",
        "status": status,
        "run_started_at": now.isoformat(),
        "lookback_days": lookback_days,
        "lookback_start": lookback_start.isoformat(),
        "platforms": actual_platforms,
        "requested_platforms": platforms,
        "search_fanout": fanout,
        "external_call_budget": external_call_budget,
        "source_adapters": client.available_sources(),
        "successful_source_adapters": successful_adapters,
        "source_telemetry": source_telemetry,
        "source_errors": source_errors,
        "campaigns": campaign_results,
        "guardrails": [
            "Use public/search APIs only; do not bypass platform terms or private login walls.",
            "External adapter calls and campaign/platform fan-out are bounded by the governance request budget.",
            "Treat platform/web results as trend signals, not publishable claims.",
            "Current-trend concepts require two independent publisher domains and one structured publication date inside the current seven-day window.",
            "Every approved reel still requires human fact, privacy, brand, and AI-disclosure checks.",
        ],
    }


def generate_reel_concepts(
    trend_run: dict[str, Any],
    *,
    campaign_id: str,
    trend_id: str,
    user_prompt: str = "",
    variant_count: int = 4,
    now: datetime | None = None,
    verification_override: object | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    campaign_result = _find_campaign_result(trend_run, campaign_id)
    trend = _find_trend(campaign_result, trend_id)
    campaign = campaign_result["campaign"]
    verification_was_overridden = _require_verified_current_trend(
        trend,
        action="generate a current-trend concept",
        verification_override=verification_override,
        now=now,
    )
    prompt_errors = validate_user_prompt(user_prompt, campaign, trend)
    if prompt_errors:
        raise ValueError("; ".join(prompt_errors))

    count = _int_between(variant_count, minimum=1, maximum=6)
    prompt_application = _prompt_application(user_prompt, campaign, trend)
    formats = _directed_formats(_format_suggestions(campaign, trend), prompt_application)
    variants: list[dict[str, Any]] = []
    for index, format_name in enumerate(formats[:count]):
        variants.append(
            _reel_variant(
                campaign,
                trend,
                format_name,
                index=index,
                user_prompt=user_prompt,
                prompt_application=prompt_application,
            )
        )

    bundle_id = f"concept-{_stable_id(trend_run['id'] + campaign_id + trend_id + user_prompt + now.isoformat(), length=12)}"
    for index, variant in enumerate(variants):
        variant["id"] = f"{bundle_id}-v{index + 1}"

    return {
        "id": bundle_id,
        "status": "draft_test_override" if verification_was_overridden else "draft",
        "run_id": trend_run["id"],
        "campaign_id": campaign_id,
        "trend_id": trend_id,
        "created_at": now.isoformat(),
        "user_prompt": user_prompt.strip(),
        "prompt_application": prompt_application,
        "content_mode": "evergreen" if trend.get("trend_type") == "evergreen_placeholder" else "current_trend",
        "source_verification": {
            "verified": _trend_has_verified_sources(trend),
            "test_override_used": verification_was_overridden,
        },
        "campaign": campaign,
        "trend": trend,
        "delivery": {
            "channel": str(campaign.get("default_channel") or (campaign.get("channels") or ["LinkedIn"])[0]),
            "format": str(campaign.get("default_format") or "expert_post"),
        },
        "variants": variants,
        "guardrails": [
            "Topic-locked regeneration only.",
            "No invented numbers, client names, employee stories, or ROI promises.",
            "Approved concept becomes a draft brief and still stops at human review.",
        ],
    }


def concept_to_content_brief(
    concept_bundle: dict[str, Any],
    *,
    variant_id: str | None = None,
    verification_override: object | None = None,
) -> ContentBrief:
    campaign = concept_bundle["campaign"]
    trend = concept_bundle["trend"]
    _require_verified_current_trend(
        trend,
        action="approve a current-trend concept",
        verification_override=verification_override,
    )
    variants = concept_bundle.get("variants", [])
    variant = _select_variant(variants, variant_id)
    content_id = f"content-{variant['id']}"
    campaign_name = campaign["name"]
    canonical_campaign_id = resolve_campaign_id(campaign.get("id", "") or campaign_name)
    cta = _cta_for_campaign(campaign_name)
    is_evergreen = trend.get("trend_type") == "evergreen_placeholder"
    delivery = concept_bundle.get("delivery") or {}
    channel = str(delivery.get("channel") or campaign.get("default_channel") or "LinkedIn")
    content_format = str(delivery.get("format") or campaign.get("default_format") or "expert_post")
    is_reel = "reel" in content_format.casefold()
    return ContentBrief(
        id=content_id,
        campaign_id=canonical_campaign_id,
        campaign=campaign_name,
        campaign_context={
            "generation_direction": str(campaign.get("generation_objective") or (
                "Das ausgewählte, quellenverifizierte Trend-Signal im vorgesehenen Kampagnenformat umsetzen."
            )),
            "content_mode": "evergreen" if is_evergreen else "current_trend",
            "content_constraints": _content_constraints_for_campaign(canonical_campaign_id),
            "audience_profiles": [
                dict(item) for item in campaign.get("audience_profiles", [])
            ],
            "trend_campaign_id": "" if is_evergreen else campaign.get("id", ""),
        },
        persona=str(campaign.get("primary_persona") or _persona_for_campaign(campaign_name)),
        channel=channel,
        format=content_format,
        objective=(
            f"Einen kampagnenkonformen Evergreen-Inhalt für {campaign_name} erstellen."
            if is_evergreen
            else f"Einen quellenverifizierten, aktuellen {channel}-Inhalt für {campaign_name} erstellen."
        ),
        cta=str(campaign.get("offer") or cta),
        proof_sources=[campaign["evidence_ref"]],
        utm={
            "utm_source": _slug(channel),
            "utm_medium": "organic_reel" if is_reel else "organic",
            "utm_campaign": _slug(campaign_name),
        },
        hypothesis=(
            f"Ein praktischer Evergreen-Inhalt zu {trend['topic']} erzeugt qualifizierte Reaktionen."
            if is_evergreen
            else f"Ein quellenverifizierter Inhalt zu {trend['topic']} erzeugt qualifizierte Reaktionen und Anfragen."
        ),
        test_variable="evergreen_content_format" if is_evergreen else "trend_content_format",
        content_mode="evergreen" if is_evergreen else "current_trend",
        language="de-DE",
        hashtags=variant.get("hashtags", [])[:5],
        trend_run_id="" if is_evergreen else str(concept_bundle.get("run_id", "")),
        trend_id="" if is_evergreen else trend["id"],
        trend_summary="" if is_evergreen else trend["topic"],
        trend_sources=[] if is_evergreen else trend.get("source_urls", []),
        trend_verification_status=(
            "" if is_evergreen else str((trend.get("verification") or {}).get("status", ""))
        ),
        citations=[] if is_evergreen else list(trend.get("citations", [])),
        reel_concept=variant,
        user_prompt=concept_bundle.get("user_prompt", ""),
        risk_flags=_risk_flags_for_campaign(canonical_campaign_id),
    )


def validate_trend_brief_against_run(
    brief: ContentBrief,
    trend_run: dict[str, Any],
    *,
    now: datetime | None = None,
) -> list[str]:
    """Revalidate trend provenance against the immutable stored research run.

    Caller-provided URLs and status strings are never sufficient evidence. A
    trend-backed brief must resolve to the exact campaign/trend inside its
    stored run, and that run must still satisfy the recency/source gate.
    """

    if brief.content_mode == "evergreen":
        return []
    if not brief.trend_id:
        return ["current-trend content must reference a stored trend"]
    errors: list[str] = []
    run_id = str(trend_run.get("id", "")).strip()
    if not brief.trend_run_id or brief.trend_run_id != run_id:
        errors.append("trend-backed content must reference its stored trend run")
        return errors

    trend_campaign_id = str(brief.campaign_context.get("trend_campaign_id", "")).strip()
    campaign_result: dict[str, Any] | None = None
    if trend_campaign_id:
        try:
            campaign_result = _find_campaign_result(trend_run, trend_campaign_id)
        except ValueError:
            campaign_result = None
    if campaign_result is None:
        for candidate in trend_run.get("campaigns", []):
            if any(item.get("id") == brief.trend_id for item in candidate.get("trends", [])):
                campaign_result = candidate
                break
    if campaign_result is None:
        return ["trend campaign is not present in the stored research run"]

    campaign = campaign_result.get("campaign", {})
    if resolve_campaign_id(str(campaign.get("id", "") or campaign.get("name", ""))) != brief.campaign_id:
        errors.append("stored trend campaign does not match the content campaign")
    try:
        trend = _find_trend(campaign_result, brief.trend_id)
    except ValueError:
        return [*errors, "trend is not present in the stored research run"]

    if not _trend_has_verified_sources(trend, now=now):
        errors.append("stored trend evidence is unverified or older than seven days")
    if str((trend.get("verification") or {}).get("status", "")) != "verified_recent":
        errors.append("stored trend does not have verified_recent status")
    if brief.trend_verification_status != "verified_recent":
        errors.append("content trend verification status does not match the stored run")
    if brief.trend_summary.strip() != str(trend.get("topic", "")).strip():
        errors.append("content trend summary does not match the stored run")

    stored_urls = {str(value).strip() for value in trend.get("source_urls", []) if str(value).strip()}
    brief_urls = {str(value).strip() for value in brief.trend_sources if str(value).strip()}
    if brief_urls != stored_urls:
        errors.append("content trend sources do not match the stored run")
    cited_urls = {
        str(item.get("url", "")).strip()
        for item in brief.citations
        if isinstance(item, dict) and str(item.get("url", "")).strip()
    }
    if cited_urls - stored_urls:
        errors.append("content citations do not belong to the stored trend")
    return list(dict.fromkeys(errors))


def validate_user_prompt(user_prompt: str, campaign: dict[str, Any], trend: dict[str, Any]) -> list[str]:
    prompt = user_prompt.strip()
    if not prompt:
        return []
    blocked_patterns = [
        r"(?i)\b(guaranteed|garantiert)\b.*\b(roi|results|umsatz|conversion)\b",
        r"(?i)\b(api[_-]?key|secret|password|token)\b",
        r"(?i)\b(customer|kunde|employee|mitarbeiter|bewerber)\b.*\b(without consent|ohne einwilligung)\b",
        r"(?i)\b(politics|election|crypto|casino|betting|adult|weapon|medical cure)\b",
    ]
    for pattern in blocked_patterns:
        if re.search(pattern, prompt):
            return ["prompt violates campaign/content guardrails"]

    prompt_words = [word for word in _tokens(prompt, min_length=4) if word not in GENERIC_PROMPT_WORDS]
    if not prompt_words:
        return []

    allowed_text = " ".join(
        [
            campaign.get("name", ""),
            campaign.get("description", ""),
            " ".join(campaign.get("keywords", [])),
            trend.get("topic", ""),
            trend.get("angle", ""),
            " ".join(trend.get("reel_hooks", [])),
            " ".join(trend.get("format_suggestions", [])),
        ]
    )
    allowed_words = set(_tokens(allowed_text, min_length=4)) | GENERIC_PROMPT_WORDS
    overlap = [word for word in prompt_words if word in allowed_words]
    if len(overlap) < 1 and len(prompt_words) >= 2:
        return ["prompt must stay related to the selected campaign and trend"]
    off_topic_ratio = 1 - (len(overlap) / max(len(prompt_words), 1))
    if off_topic_ratio > 0.80 and len(prompt_words) >= 5:
        return ["prompt is mostly outside the selected campaign topic"]
    return []


def _bounded_campaign_platform_plan(
    campaigns: list[dict[str, Any]],
    platforms: list[str],
    *,
    client: TrendSearchClient,
    external_call_limit: int,
) -> tuple[dict[str, list[str]], dict[str, int | bool]]:
    """Plan a fair, finite campaign/platform fan-out before external work starts."""

    plan: dict[str, list[str]] = {str(campaign["id"]): [] for campaign in campaigns}
    remaining = max(0, int(external_call_limit))
    requested_external_calls = 0
    allocated_external_calls = 0
    planned_pairs = 0
    partial_pairs = 0
    for platform in platforms:
        try:
            estimated_cost = max(0, int(client.estimated_external_calls(platform)))
        except (TypeError, ValueError, OverflowError):
            estimated_cost = 1
        requested_external_calls += estimated_cost * len(campaigns)
        if estimated_cost == 0:
            continue
        for campaign in campaigns:
            if planned_pairs >= MAX_CAMPAIGN_PLATFORM_FANOUT or remaining <= 0:
                continue
            allocated = min(estimated_cost, remaining)
            plan[str(campaign["id"])].append(platform)
            planned_pairs += 1
            allocated_external_calls += allocated
            remaining -= allocated
            if allocated < estimated_cost:
                partial_pairs += 1

    requested_pairs = len(campaigns) * len(platforms)
    return plan, {
        "campaign_count": len(campaigns),
        "platform_count": len(platforms),
        "requested_pairs": requested_pairs,
        "planned_pairs": planned_pairs,
        "maximum_pairs": MAX_CAMPAIGN_PLATFORM_FANOUT,
        "estimated_requested_external_calls": requested_external_calls,
        "allocated_external_calls": allocated_external_calls,
        "partial_pairs": partial_pairs,
        "truncated": planned_pairs < requested_pairs,
    }


def _search_campaign_signals(
    campaign: dict[str, Any],
    *,
    platforms: list[str],
    lookback_start: datetime,
    now: datetime,
    client: TrendSearchClient,
) -> list[SearchResult]:
    results: list[SearchResult] = []
    for platform in platforms:
        query = _query_for_campaign(campaign, platform=platform, year=now.year)
        results.extend(client.search(query, platform=platform, lookback_start=lookback_start, now=now, limit=5))
    public_results = [result for result in results if source_domain(result.url)]
    if not public_results:
        return [
            SearchResult(
                source="campaign_brief",
                platform="internal",
                title=f"Evergreen campaign angle (not a live trend): {campaign['name']}",
                url=campaign["evidence_ref"],
                snippet=(
                    "Unverified evergreen placeholder only. No live adapter returned evidence; configure Firecrawl v2, "
                    "SearxNG, Google CSE, Reddit, or TikTok before making a current-trend claim."
                ),
                published_at="",
                retrieved_at=now.isoformat(),
                raw={"evidence_type": "evergreen_campaign_brief", "verified": False},
            )
        ]
    return _dedupe_results(public_results)


def _build_campaign_trends(
    campaign: dict[str, Any],
    *,
    signals: list[SearchResult],
    run_id: str,
    lookback_start: datetime,
    now: datetime,
    limit: int,
) -> list[dict[str, Any]]:
    keyword_groups = _keyword_groups(campaign, signals)
    trends: list[dict[str, Any]] = []
    current = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    requested_start = lookback_start if lookback_start.tzinfo else lookback_start.replace(tzinfo=timezone.utc)
    freshness_start = max(
        requested_start.astimezone(timezone.utc),
        current.astimezone(timezone.utc) - timedelta(days=CURRENT_TREND_FRESHNESS_DAYS),
    )
    for theme, candidate_evidence in keyword_groups[:limit]:
        candidate_external = [
            item
            for item in candidate_evidence
            if item.source != "campaign_brief" and source_domain(item.url)
        ]
        topic = (
            _topic_for_theme(campaign, theme, candidate_external)
            if candidate_external
            else f"Evergreen campaign angle: {theme}"
        )
        core_tokens = _topic_core_tokens(topic, theme=theme)
        external = [
            item
            for item in candidate_external
            if _source_supports_topic(item.title, item.snippet, core_tokens=core_tokens)
        ]
        # The topic is derived from the first result, so retain that primary source
        # as single-source evidence even when the title is too generic to establish
        # a distinctive corroboration core. It still cannot verify a live trend.
        if candidate_external and candidate_external[0] not in external:
            external.insert(0, candidate_external[0])
        evidence = external if external else candidate_evidence
        dated_recent = [
            item
            for item in external
            if item.published_at and _date_is_recent(item.published_at, freshness_start, now=now)
        ]
        citations = [item.to_citation(retrieved_at=now.isoformat()) for item in evidence[:8]]
        for citation in citations:
            original_title = str(citation.get("title", ""))
            canonical_title = _normalize_topic_text(original_title)
            if canonical_title != original_title:
                citation["original_title"] = original_title
                citation["title"] = canonical_title
        external_domains = {source_domain(item.url) for item in external if source_domain(item.url)}
        recent_domains = {source_domain(item.url) for item in dated_recent if source_domain(item.url)}
        source_urls = [citation["url"] for citation in citations if citation["url"]]
        verification_status = (
            "verified_recent"
            if len(external_domains) >= 2 and recent_domains
            else "source_verified_date_unconfirmed"
        )
        if external and len(external_domains) < 2:
            verification_status = "single_source_review"
        if not external:
            verification_status = "evergreen_unverified"
        trend_id = f"{campaign['id']}-{_stable_id(run_id + topic, length=10)}"
        verified = verification_status == "verified_recent"
        trend = {
                "id": trend_id,
                "topic": topic,
                "trend_type": (
                    "current_trend"
                    if verified
                    else "current_trend_candidate"
                    if external
                    else "evergreen_placeholder"
                ),
                "is_current_trend": verified,
                "recency_claim_allowed": verified,
                "campaign_fit": _campaign_fit(campaign, topic),
                "angle": _angle_for_campaign(campaign, theme),
                "platforms": sorted({item.platform for item in evidence}),
                "source_urls": source_urls[:8],
                "evidence": [item.to_dict() for item in evidence[:8]],
                "citations": citations,
                "verification": {
                    "status": verification_status,
                    "verified": verified,
                    "corroboration_version": CORROBORATION_VERSION,
                    "evidence_count": len(external),
                    "independent_source_count": len(external_domains),
                    "dated_recent_count": len(dated_recent),
                    "recent_source_count": len(recent_domains),
                    "candidate_evidence_count": len(candidate_external),
                    "excluded_noncorroborating_count": max(0, len(candidate_external) - len(external)),
                    "corroboration_core_tokens": sorted(core_tokens),
                    "minimum_independent_sources": 2,
                    "minimum_recent_sources": 1,
                    "lookback_start": lookback_start.isoformat(),
                    "freshness_start": freshness_start.isoformat(),
                    "freshness_days": CURRENT_TREND_FRESHNESS_DAYS,
                    "last_checked_at": now.isoformat(),
                    "note": _verification_note(verification_status),
                },
                "score": _trend_score(campaign, topic, evidence, lookback_start=lookback_start, now=now),
                "reel_hooks": _hooks_for_campaign(campaign, theme),
                "format_suggestions": _format_suggestions(campaign, {"topic": topic}),
                "creative_notes": _creative_notes(campaign, theme),
                "hashtags": _hashtags(campaign, theme),
            }
        apply_current_trend_eligibility(trend, now=now)
        trends.append(trend)
    return sorted(trends, key=lambda item: item["score"], reverse=True)


def _keyword_groups(campaign: dict[str, Any], signals: list[SearchResult]) -> list[tuple[str, list[SearchResult]]]:
    keywords = campaign.get("keywords", [])[:6] or [campaign["name"]]
    groups: list[tuple[str, list[SearchResult]]] = []
    for keyword in keywords:
        key_tokens = set(_tokens(keyword, min_length=3))
        matching = []
        for signal in signals:
            haystack = f"{signal.title} {signal.snippet}".lower()
            if any(token in haystack for token in key_tokens):
                matching.append(signal)
        if matching:
            groups.append((keyword, matching))
    if groups:
        return groups
    return [(campaign.get("keywords", [campaign["name"]])[0], signals)]


def _query_for_campaign(campaign: dict[str, Any], *, platform: str, year: int) -> str:
    name = campaign["name"]
    normalized_name = name.casefold()
    if any(term in normalized_name for term in ("qa", "test", "qualität")):
        topic = "Software Testing QA Testautomatisierung"
    elif any(term in normalized_name for term in ("sokrates", "private ki", "ki (")):
        topic = "Private KI Mittelstand Datenschutz"
    elif any(term in normalized_name for term in ("lfa", "azubi", "ausbildung")):
        topic = "Fachinformatiker Ausbildung digitales Lernsystem"
    elif any(term in normalized_name for term in ("mitarbeiter", "team", "employer")):
        topic = "Employer Branding IT Recruiting"
    elif any(term in normalized_name for term in ("app", "softwareentwicklung")):
        topic = "App Modernisierung Softwareentwicklung"
    else:
        topic = " ".join(campaign.get("keywords", [])[:2]) or name
    if platform == "instagram":
        return f"{topic} {year} Instagram Reels"
    if platform == "tiktok":
        return f"{topic} {year} TikTok"
    if platform == "reddit":
        return f"{topic} {year} discussion"
    if platform == "forums":
        return f"{topic} {year} forum discussion"
    return f"{topic} trends {year}"


def _platform_query(query: str, platform: str) -> str:
    return platform_query(query, platform)


def _topic_for_theme(campaign: dict[str, Any], theme: str, evidence: list[SearchResult]) -> str:
    strongest = evidence[0].title if evidence else theme
    clean_title = _normalize_topic_text(strongest).strip(" -|")
    if len(clean_title) > 90:
        clean_title = clean_title[:87].rstrip() + "..."
    return f"{theme}: {clean_title}" if theme.lower() not in clean_title.lower() else clean_title


def _normalize_topic_text(value: str) -> str:
    """Normalize display whitespace while preserving the canonical ISTQB acronym.

    Some search-result titles omit the leading ``I`` from ISTQB. Correcting the
    standalone typo here prevents generated topic text from propagating STQB,
    while the raw source title remains available in the evidence record.
    """

    canonical = re.sub(r"(?i)\bSTQB\b", "ISTQB", str(value or ""))
    return re.sub(r"\s+", " ", canonical).strip()


def _topic_core_tokens(topic: str, *, theme: str = "") -> set[str]:
    """Return distinctive tokens that independent sources must corroborate."""

    normalized = _normalize_topic_text(topic)
    normalized = re.sub(r"[-–—_:/+|]+", " ", normalized)
    theme_text = re.sub(r"[-–—_:/+|]+", " ", _normalize_topic_text(theme))
    theme_tokens = set(_tokens(theme_text, min_length=2))
    return {
        token
        for token in _tokens(normalized, min_length=2)
        if token not in theme_tokens
        and token not in TOPIC_STOP_WORDS
        and not token.isdigit()
        and not re.fullmatch(r"20\d{2}", token)
    }


def _source_supports_topic(title: str, snippet: str, *, core_tokens: set[str]) -> bool:
    """Require lexical support for the selected topic, not a broad campaign term.

    A source needs at least two distinctive topic tokens and roughly 40 percent
    of the extracted core. This deliberately keeps a broad Testautomatisierung
    article from corroborating an ISTQB/six-rules claim merely because both use
    the campaign keyword or the same year.
    """

    if len(core_tokens) < 2:
        return False
    source_text = _normalize_topic_text(f"{title} {snippet}")
    source_text = re.sub(r"[-–—_:/+|]+", " ", source_text)
    source_tokens = set(_tokens(source_text, min_length=2))
    overlap = core_tokens & source_tokens
    minimum_overlap = max(2, (len(core_tokens) * 2 + 4) // 5)
    return len(overlap) >= minimum_overlap


def _angle_for_campaign(campaign: dict[str, Any], theme: str) -> str:
    name = campaign["name"].lower()
    if "qa" in name or "test" in name or "qualit" in name:
        return f"{theme} als Prüffrage mit einem konkreten, belegbaren Schritt einordnen."
    if "ki" in name or "sokrates" in name:
        return f"{theme} als Frage zu Datenschutz und internem Wissen im Mittelstand einordnen."
    if "azubi" in name or "lfa" in name:
        return f"{theme} mit dem belegten digitalen Lernsystem sachlich verbinden."
    if "mitarbeiter" in name:
        return f"{theme} nur als Produktionsidee mit realen Medien und dokumentierten Einwilligungen planen."
    if "app" in name:
        return f"{theme} mit dem belegten Portfolio und einer neutralen Modernisierungsfrage verbinden."
    return f"{theme} in einen kampagnenpassenden, belegbaren Short-Form-Insight übersetzen."


def _campaign_fit(campaign: dict[str, Any], topic: str) -> str:
    tokens = set(_tokens(topic, min_length=4))
    keyword_tokens = set(_tokens(" ".join(campaign.get("keywords", [])), min_length=4))
    overlap = sorted(tokens & keyword_tokens)
    if overlap:
        return f"Matches campaign keywords: {', '.join(overlap[:5])}."
    return "Weak lexical match; keep as inspiration until a human confirms relevance."


def _hooks_for_campaign(campaign: dict[str, Any], theme: str) -> list[str]:
    name = campaign["name"].lower()
    if "qa" in name or "test" in name:
        return [
            f"Welche Prüffrage zu {theme} bleibt vor der nächsten Freigabe offen?",
            f"Eine Frage, bevor {theme} priorisiert wird:",
            f"Welcher Beleg zeigt, wo {theme} zuerst geprüft werden sollte?",
        ]
    if "ki" in name or "sokrates" in name:
        return [
            f"Welche Datenschutzfrage gehört vor einer Entscheidung zu {theme} auf die Liste?",
            "Welche Rolle spielen Datenschutz und internes Wissen bei privater KI?",
            "Welche Aussage zur KI-Nutzung ist belegt – und welche noch offen?",
        ]
    if "azubi" in name or "lfa" in name:
        return [
            f"Wie lässt sich {theme} für Fachinformatiker-Azubis verständlich einordnen?",
            "Welche Frage gehört auf eine klare Lernsystem-Checkliste?",
            "20 Sekunden: ein belegbarer Blick auf digitales Lernen in der Ausbildung.",
        ]
    if "mitarbeiter" in name:
        return [
            f"Welcher Einblick zu {theme} lässt sich mit realen Medien und Einwilligung zeigen?",
            "Was muss vor einem Team-Reel dokumentiert sein?",
            "Welche Interviewfrage lässt sich ohne erfundene Mitarbeitergeschichte stellen?",
        ]
    return [
        f"Welche Anwendung sollte bei {theme} zuerst in einen Modernisierungscheck?",
        "Welche Modernisierungsfrage lässt sich mit einem Portfolio-Nachweis verbinden?",
        "Build or buy? Zuerst den belegbaren Ausgangspunkt prüfen.",
    ]


def _format_suggestions(campaign: dict[str, Any], trend: dict[str, Any]) -> list[str]:
    name = campaign["name"].lower()
    base = [
        "Q&A-Einwandbehandlung",
        "Mythos vs Fakt mit Kinetic Captions",
        "Neutrale Prozessgrafik",
        "3-Schritte-Checkliste",
        "POV aus dem Alltag",
        "Kommentarantwort-Erklärvideo",
    ]
    if "azubi" in name or "mitarbeiter" in name:
        return ["Produktionsplan", "Street-Style-Q&A", "Kommentarantwort-Erklärvideo", "Interview-Checkliste", "3-Schritte-Checkliste"]
    if "app" in name:
        return ["Portfolio-Carousel", "Modernisierungs-Checkliste", "Build-Decision-Breakdown", "Q&A-Einwandbehandlung", "Mythos vs Fakt mit Kinetic Captions"]
    return base


def _creative_notes(campaign: dict[str, Any], theme: str) -> list[str]:
    return [
        "Mit einem 1,5-Sekunden-Pattern-Interrupt und großen Captions starten.",
        "Jeden Beat unter 4 Sekunden halten; Jump Cuts oder Grafik-Zooms zwischen Beats nutzen.",
        "Untertitel, Quellen-/Proof-Karten und eine klare CTA-Endkarte nutzen.",
        f"{theme} nicht überhöhen; als aktuelles Signal zur Prüfung rahmen.",
    ]


def _prompt_application(user_prompt: str, campaign: dict[str, Any], trend: dict[str, Any]) -> dict[str, Any]:
    lowered = user_prompt.lower()
    requested_format = ""
    format_cues = [
        (("q&a", "question", "frage", "fragen"), "Q&A"),
        (("checklist", "checkliste", "3-step", "three-step", "3 schritte", "drei schritte"), "checklist"),
        (("myth", "mythos", "fact", "fakt"), "myth"),
        (("screenrecord", "screen record", "ui demo", "workflow"), "screen"),
        (("pov", "point of view"), "POV"),
        (("interview", "street-style", "street style"), "interview"),
    ]
    for cues, label in format_cues:
        if any(cue in lowered for cue in cues):
            requested_format = label
            break

    if any(cue in lowered for cue in ("slower", "slow ", "langsam", "ruhig")):
        pace = "calm"
    elif any(cue in lowered for cue in ("faster", "fast ", "schnell", "punchy", "energetic")):
        pace = "fast"
    else:
        pace = "standard"

    if any(cue in lowered for cue in ("serious", "seriös", "professional", "sachlich")):
        tone = "professional"
    elif any(cue in lowered for cue in ("funny", "humor", "witzig", "playful")):
        tone = "playful"
    elif any(cue in lowered for cue in ("bold", "bolder", "direkt", "direct", "punchy")):
        tone = "direct"
    else:
        tone = "campaign_default"

    caption_style = "kinetic" if any(cue in lowered for cue in ("kinetic", "caption pop", "animated caption")) else "standard"
    delivery = "voiceover" if any(cue in lowered for cue in ("voiceover", "voice over", "sprechertext")) else "on_camera"
    allowed_text = " ".join(
        [
            campaign.get("name", ""),
            campaign.get("description", ""),
            " ".join(campaign.get("keywords", [])),
            trend.get("topic", ""),
            trend.get("angle", ""),
        ]
    )
    allowed_words = set(_tokens(allowed_text, min_length=4))
    focus_terms: list[str] = []
    for word in _tokens(user_prompt, min_length=4):
        if word in allowed_words and word not in focus_terms:
            focus_terms.append(word)
    applied = bool(user_prompt.strip())
    return {
        "applied": applied,
        "requested_format": requested_format,
        "pace": pace,
        "tone": tone,
        "caption_style": caption_style,
        "delivery": delivery,
        "focus_terms": focus_terms[:4],
    }


def _directed_formats(formats: list[str], prompt_application: dict[str, Any]) -> list[str]:
    requested = str(prompt_application.get("requested_format", "")).lower()
    if not requested:
        return formats
    cue_map = {
        "q&a": ("q&a", "street"),
        "checklist": ("checkliste", "schritte"),
        "myth": ("myth",),
        "screen": ("screen", "workflow", "build"),
        "pov": ("pov",),
        "interview": ("street", "q&a"),
    }
    cues = cue_map.get(requested, (requested,))
    preferred = [item for item in formats if any(cue in item.lower() for cue in cues)]
    return [*preferred, *[item for item in formats if item not in preferred]]


def _reel_variant(
    campaign: dict[str, Any],
    trend: dict[str, Any],
    format_name: str,
    *,
    index: int,
    user_prompt: str,
    prompt_application: dict[str, Any],
) -> dict[str, Any]:
    hook = (trend.get("reel_hooks") or _hooks_for_campaign(campaign, trend.get("topic", "")))[index % 3]
    if prompt_application.get("tone") == "direct" and not hook.lower().startswith(("stopp", "klartext")):
        hook = f"Klartext: {hook}"
    if prompt_application.get("requested_format") == "Q&A" and not hook.rstrip().endswith("?"):
        hook = f"Was bedeutet das konkret? {hook}"
    cta = _cta_for_campaign(campaign["name"])
    beats = _beats_for_format(format_name, campaign, trend)
    if prompt_application.get("delivery") == "voiceover":
        beats[0] = f"Voiceover: {beats[0]}"
    if prompt_application.get("pace") == "fast":
        beats = [f"{beat} (max. 3 Sekunden)" for beat in beats]
    elif prompt_application.get("pace") == "calm":
        beats = [f"{beat} (ruhig und mit Lesepause)" for beat in beats]
    focus_terms = prompt_application.get("focus_terms", [])
    if focus_terms and len(beats) > 1:
        beats[1] = f"{beats[1]} Gewünschter Fokus: {', '.join(focus_terms)}."
    shot_list = _shot_list_for_format(format_name, campaign)
    animation_notes = _animation_for_format(format_name)
    if prompt_application.get("caption_style") == "kinetic":
        animation_notes += " Nutzerwunsch: Kinetic Captions auf Schlüsselwörtern mit klarer Quellenkarte."
    if prompt_application.get("pace") == "calm":
        animation_notes += " Schnitte bewusst reduzieren und Quellenkarten mindestens 2 Sekunden stehen lassen."
    caption = _caption_for_variant(campaign, trend, hook, cta, prompt_application)
    return {
        "idea": f"{trend.get('topic', 'Thema')} als {format_name}",
        "format": format_name,
        "hook": hook,
        "beats": beats,
        "shot_list": shot_list,
        "animation_notes": animation_notes,
        "caption": caption,
        "cta": cta,
        "creator_direction": user_prompt.strip(),
        "prompt_application": prompt_application,
        "hashtags": trend.get("hashtags", [])[:5],
        "evidence_to_verify": trend.get("source_urls", [])[:5],
        "guardrails": [
            "No customer, applicant, or employee identity without consent.",
            "No guaranteed ROI, security, compliance, or outcome claim.",
            "Use trend source links as internal review material only.",
        ],
    }


def _beats_for_format(format_name: str, campaign: dict[str, Any], trend: dict[str, Any]) -> list[str]:
    topic = trend.get("topic", "the trend")
    angle = trend.get("angle", "")
    if "Q&A" in format_name or "Street" in format_name:
        return [
            f"Frage auf dem Screen: 'Warum ist {topic} gerade relevant?'",
            f"Antwort in einem Satz: {angle}",
            "Einen Proof- oder Prozess-Ausschnitt ohne private Daten zeigen.",
            f"Mit CTA schließen: {_cta_for_campaign(campaign['name'])}.",
        ]
    if "Myth" in format_name:
        return [
            f"Mythos: '{topic} ist nur ein weiterer Content-Trend.'",
            "Fakt: Wichtig ist der Pain Point hinter dem Signal.",
            f"Auf den belegbaren Kampagnenwinkel beziehen: {angle}",
            "Zum Speichern auffordern, wenn die Zuschauer eine praktische Checkliste brauchen.",
        ]
    if "Screen" in format_name or "workflow" in format_name or "Build" in format_name:
        return [
            "Mit dem unklaren Vorher-Zustand starten.",
            f"Die konkrete Reibung rund um {topic} markieren.",
            "Eine neutrale Prozesskarte oder Checkliste als Prüfstruktur zeigen.",
            "Mit dem konkreten nächsten Schritt enden.",
        ]
    return [
        f"Aktuelles Signal benennen: {topic}.",
        "Erklären, warum die Zielgruppe der Kampagne jetzt darauf achten sollte.",
        "Eine praktische Prüffrage für diese Woche geben.",
        f"Mit CTA schließen: {_cta_for_campaign(campaign['name'])}.",
    ]


def _shot_list_for_format(format_name: str, campaign: dict[str, Any]) -> list[str]:
    if "Screen" in format_name or "workflow" in format_name or "Build" in format_name:
        return ["Neutrale Prozessgrafik mit Fokus-Zoom", "Quellenkarte", "Prüffragen-Split-Screen", "CTA-Endkarte"]
    if "POV" in format_name or "Street" in format_name:
        return ["Fragenkarte", "zwei kurze Antwortkarten", "Quellenkarte", "nur bei Einwilligung: reale Szene", "CTA-Endkarte"]
    return ["Talking-Head-Hook oder Typografie", "große Textkarte", "Quellen-/Prozesskarte", "drei untertitelte Beats", "CTA-Endkarte"]


def _animation_for_format(format_name: str) -> str:
    if "Myth" in format_name:
        return "Rot-grüne Split-Cards, MYTHOS/FAKT-Stempel, schnelle Caption-Pops."
    if "Screen" in format_name:
        return "UI-Zooms, Cursor-Halo, Highlight-Rechtecke, 0,2s Swipe-Transitions."
    if "POV" in format_name:
        return "Native Handheld-Cuts, Caption-Bounce auf Kernwörtern, dezenter Speed-Ramp."
    return "Kinetic Captions, Snap-Zoom auf die Kernaussage, Quellenkarte vor dem CTA."


def _caption_for_variant(
    campaign: dict[str, Any],
    trend: dict[str, Any],
    hook: str,
    cta: str,
    prompt_application: dict[str, Any],
) -> str:
    tags = " ".join(f"#{tag}" for tag in trend.get("hashtags", [])[:5])
    framing = "Kurz und direkt" if prompt_application.get("tone") == "direct" else "Praktischer Kurzcheck"
    signal_label = "Quellengeprüftes Trend-Signal" if trend.get("recency_claim_allowed") else "Evergreen-Thema"
    return (
        f"{hook}\n\n"
        f"{framing}: {signal_label}: {trend.get('topic', '')}\n"
        f"Wichtig für {campaign['name']}: {trend.get('angle', '')}\n\n"
        f"{cta}\n\n"
        f"{tags}"
    ).strip()


def _trend_score(
    campaign: dict[str, Any],
    topic: str,
    evidence: list[SearchResult],
    *,
    lookback_start: datetime,
    now: datetime,
) -> int:
    external = [item for item in evidence if item.source != "campaign_brief"]
    independent_sources = {source_domain(item.url) for item in external if source_domain(item.url)}
    score = 10 if not external else 20
    score += min(len(independent_sources) * 18, 45)
    score += min(sum(sum(item.metrics.values()) for item in evidence) // 100, 20)
    score += 15 if any(item.published_at and _date_is_recent(item.published_at, lookback_start, now=now) for item in external) else 0
    score += 10 if set(_tokens(topic, min_length=4)) & set(_tokens(" ".join(campaign.get("keywords", [])), min_length=4)) else 0
    return min(score, 100)


def _verification_note(status: str) -> str:
    notes = {
        "verified_recent": "Two or more independent publisher domains corroborate this signal, with at least one structured publication date inside the current seven-day window.",
        "source_verified_date_unconfirmed": "Independent sources were found, but no source has a trustworthy publication date inside the lookback window.",
        "single_source_review": "Evidence resolves to fewer than two independent publisher domains; current-trend generation and approval stay blocked.",
        "evergreen_unverified": "Campaign brief only: this is an unverified evergreen placeholder and must not be presented as a current trend.",
    }
    return notes.get(status, "Manual review required.")


def _external_evidence_count(trend: dict[str, Any]) -> int:
    return int(((trend.get("verification") or {}).get("evidence_count") or 0))


def evaluate_trend_eligibility(
    trend: dict[str, Any], *, now: datetime | None = None
) -> dict[str, Any]:
    """Recompute whether stored evidence is eligible at the current instant.

    Historical status/count fields are audit data, not an evergreen grant. The
    decision is rebuilt from public, exact-topic citations and publication
    timestamps inside a fixed seven-day window.
    """

    current = now or datetime.now(timezone.utc)
    current = current if current.tzinfo else current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    freshness_start = current - timedelta(days=CURRENT_TREND_FRESHNESS_DAYS)
    verification = trend.get("verification") or {}
    metadata_verified = (
        isinstance(verification, dict)
        and verification.get("status") == "verified_recent"
        and verification.get("verified") is True
    )
    checked_at = _parse_datetime(str(verification.get("last_checked_at", ""))) if isinstance(verification, dict) else None
    checked_utc = checked_at.astimezone(timezone.utc) if checked_at else None
    check_is_valid = bool(checked_utc and checked_utc <= current + timedelta(minutes=5))

    citations = trend.get("citations", [])
    core_tokens = _topic_core_tokens(str(trend.get("topic", "")))
    independent_domains: set[str] = set()
    recent_domains: set[str] = set()
    if isinstance(citations, list) and len(core_tokens) >= 2 and check_is_valid:
        for citation in citations:
            if not isinstance(citation, dict):
                continue
            if not _source_supports_topic(
                str(citation.get("title", citation.get("label", ""))),
                str(citation.get("snippet", citation.get("supports", ""))),
                core_tokens=core_tokens,
            ):
                continue
            domain = source_domain(str(citation.get("url", "")))
            if not domain:
                continue
            independent_domains.add(domain)
            published = str(citation.get("published", citation.get("published_at", "")))
            published_at = _parse_datetime(published)
            if (
                published_at
                and checked_utc
                and published_at.astimezone(timezone.utc) <= checked_utc + timedelta(minutes=5)
                and _date_is_recent(published, freshness_start, now=current)
            ):
                recent_domains.add(domain)

    eligible = bool(
        metadata_verified
        and check_is_valid
        and len(core_tokens) >= 2
        and len(independent_domains) >= 2
        and len(recent_domains) >= 1
    )
    if eligible:
        reason = "verified_recent"
    elif not metadata_verified:
        reason = "stored_verification_not_verified"
    elif not check_is_valid:
        reason = "invalid_or_future_verification_time"
    elif len(core_tokens) < 2:
        reason = "topic_too_weak_for_corroboration"
    elif len(independent_domains) < 2:
        reason = "insufficient_independent_public_sources"
    else:
        reason = "no_structured_publication_date_in_current_window"
    return {
        "eligible_for_content": eligible,
        "eligibility_reason": reason,
        "eligibility_evaluated_at": current.isoformat(),
        "eligibility_freshness_days": CURRENT_TREND_FRESHNESS_DAYS,
        "eligibility_freshness_start": freshness_start.isoformat(),
        "current_independent_source_count": len(independent_domains),
        "current_recent_source_count": len(recent_domains),
    }


def apply_current_trend_eligibility(
    trend: dict[str, Any], *, now: datetime | None = None
) -> bool:
    """Attach the current server decision that browser clients are allowed to use."""

    evaluation = evaluate_trend_eligibility(trend, now=now)
    verification = trend.get("verification")
    if not isinstance(verification, dict):
        verification = {}
        trend["verification"] = verification
    verification.update(evaluation)
    eligible = bool(evaluation["eligible_for_content"])
    trend["is_current_trend"] = eligible
    trend["recency_claim_allowed"] = eligible
    return eligible


def refresh_trend_run_eligibility(
    trend_run: dict[str, Any], *, now: datetime | None = None
) -> dict[str, Any]:
    """Refresh all browser-facing eligibility flags on a loaded run in memory."""

    current = now or datetime.now(timezone.utc)
    current = current if current.tzinfo else current.replace(tzinfo=timezone.utc)
    trends = [
        trend
        for campaign in trend_run.get("campaigns", [])
        if isinstance(campaign, dict)
        for trend in campaign.get("trends", [])
        if isinstance(trend, dict)
    ]
    eligibility_flags = [apply_current_trend_eligibility(trend, now=current) for trend in trends]
    has_verified = any(eligibility_flags)
    if has_verified:
        trend_run["status"] = "verified_sources"
    elif any(_external_evidence_count(trend) for trend in trends):
        trend_run["status"] = "needs_source_verification"
    else:
        trend_run["status"] = "needs_live_sources"
    trend_run["eligibility_evaluated_at"] = current.astimezone(timezone.utc).isoformat()
    trend_run["eligibility_freshness_days"] = CURRENT_TREND_FRESHNESS_DAYS
    return trend_run


def _trend_has_verified_sources(trend: dict[str, Any], *, now: datetime | None = None) -> bool:
    return bool(evaluate_trend_eligibility(trend, now=now)["eligible_for_content"])


def trend_run_has_verified_sources(
    trend_run: dict[str, Any], *, now: datetime | None = None
) -> bool:
    """Re-evaluate a stored run from its citations instead of trusting its old status."""

    return any(
        _trend_has_verified_sources(trend, now=now)
        for campaign in trend_run.get("campaigns", [])
        if isinstance(campaign, dict)
        for trend in campaign.get("trends", [])
        if isinstance(trend, dict)
    )


def _require_verified_current_trend(
    trend: dict[str, Any],
    *,
    action: str,
    verification_override: object | None,
    now: datetime | None = None,
) -> bool:
    if trend.get("trend_type") == "evergreen_placeholder":
        return False
    eligibility = evaluate_trend_eligibility(trend, now=now)
    if eligibility["eligible_for_content"]:
        return False
    if (
        isinstance(verification_override, _TestVerificationOverride)
        and verification_override._capability is _TEST_VERIFICATION_CAPABILITY
    ):
        return True
    independent = int(eligibility["current_independent_source_count"])
    recent = int(eligibility["current_recent_source_count"])
    raise ValueError(
        f"cannot {action}: verified sources required "
        f"(found {independent}/2 independent domains and {recent}/1 recent dated sources)"
    )


def _find_campaign_result(trend_run: dict[str, Any], campaign_id: str) -> dict[str, Any]:
    for item in trend_run.get("campaigns", []):
        if item.get("campaign", {}).get("id") == campaign_id:
            return item
    raise ValueError(f"campaign not found in trend run: {campaign_id}")


def _find_trend(campaign_result: dict[str, Any], trend_id: str) -> dict[str, Any]:
    for trend in campaign_result.get("trends", []):
        if trend.get("id") == trend_id:
            return trend
    raise ValueError(f"trend not found: {trend_id}")


def _select_variant(variants: list[dict[str, Any]], variant_id: str | None) -> dict[str, Any]:
    if variant_id:
        for variant in variants:
            if variant.get("id") == variant_id:
                return variant
        raise ValueError(f"variant not found: {variant_id}")
    if not variants:
        raise ValueError("concept bundle has no variants")
    return variants[0]


def _cta_for_campaign(campaign_name: str) -> str:
    name = campaign_name.lower()
    if "qa" in name or "test" in name:
        return "QA-Risikoaudit anfragen"
    if "ki" in name or "sokrates" in name:
        return "Private-KI-Erstgespräch anfragen"
    if "azubi" in name or "lfa" in name:
        return "LFA-Demo oder Ausbildungsplatz-Info anfragen"
    if "mitarbeiter" in name:
        return "Team kennenlernen"
    if "app" in name:
        return "App-Modernisierungscheck anfragen"
    return "Erstgespräch anfragen"


def _persona_for_campaign(campaign_name: str) -> str:
    name = campaign_name.lower()
    if "azubi" in name or "lfa" in name:
        return "Azubi, Ausbilder oder HR-Verantwortliche"
    if "mitarbeiter" in name:
        return "Bewerber und B2B-Entscheider"
    if "ki" in name:
        return "Geschäftsführer oder IT-Leiter"
    return "IT-Leiter und B2B-Entscheider"


def _content_constraints_for_campaign(campaign_id: str) -> list[str]:
    for meta in CAMPAIGN_META.values():
        if meta.get("id") == campaign_id:
            return [str(item) for item in meta.get("content_constraints", [])]
    return []


def _risk_flags_for_campaign(campaign_id: str) -> list[str]:
    for meta in CAMPAIGN_META.values():
        if meta.get("id") == campaign_id:
            return [str(item) for item in meta.get("default_risk_flags", [])]
    return []


def _hashtags(campaign: dict[str, Any], theme: str) -> list[str]:
    raw = [theme, *campaign.get("keywords", [])[:4]]
    tags: list[str] = []
    for item in raw:
        tag = re.sub(r"[^0-9A-Za-zÄÖÜäöüß_]", "", item.title().replace(" ", ""))
        if tag and tag.lower() not in {existing.lower() for existing in tags}:
            tags.append(tag[:28])
    return tags[:5]


def _date_is_recent(value: str, lookback_start: datetime, *, now: datetime | None = None) -> bool:
    return date_is_recent(value, lookback_start, now=now)


def _parse_datetime(value: str) -> datetime | None:
    return parse_datetime(value)


def _dedupe_results(results: list[SearchResult]) -> list[SearchResult]:
    return dedupe_results(results)


def _tokens(text: str, *, min_length: int = 3) -> list[str]:
    return tokens(text, min_length=min_length)


def _stable_id(value: str, *, length: int = 10) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:length]


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.lower()).strip("_")
    return slug or "campaign"


def _int_between(value: Any, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = minimum
    return max(minimum, min(maximum, parsed))
