from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from typing import Any

from .campaign_catalog import resolve_campaign_id
from .schemas import LeadRecord


GENERIC_EMAIL_DOMAINS = {
    "gmail.com",
    "googlemail.com",
    "hotmail.com",
    "icloud.com",
    "outlook.com",
    "web.de",
    "yahoo.com",
    "gmx.de",
}

INTENT_KEYWORDS = (
    "audit",
    "check",
    "risiko",
    "termin",
    "beratung",
    "angebot",
    "anfrage",
    "modernisierung",
    "ki",
)

CRM_CONSENT_PURPOSES = {"contact_request", "sales_follow_up"}
MAUTIC_CONSENT_PURPOSE = "marketing_automation"
LEAD_LIFECYCLE_ACTIONS = {
    "suppress",
    "withdraw_consent",
    "anonymize",
    "erase",
    "expire_retention",
}
PII_FIELDS = ("company", "email", "contact_name", "phone", "message")
CANONICAL_CAMPAIGN_IDS = frozenset({"k1", "k2", "k3", "k4", "k5"})
RETENTION_POLICY_MAX_DURATIONS = {
    "contact-leads-365d": timedelta(days=365),
}


def build_lead_intake(
    payload: dict[str, Any],
    *,
    source_verified: bool,
    source_campaign_id: str = "",
    source_verification_reason: str = "",
) -> dict[str, Any]:
    errors = validate_lead_payload(payload)
    if errors:
        raise ValueError("; ".join(errors))

    consent_given = coerce_bool(payload.get("consent_given"))
    consent_at = normalized_timestamp(payload.get("consent_at"), field="consent_at")
    retention_expires_at = normalized_timestamp(
        payload.get("retention_expires_at"), field="retention_expires_at"
    )
    privacy_notice_version = normalize(payload.get("privacy_notice_version"))
    consent_source = normalize(payload.get("consent_source"))
    consent_proof_ref = normalize(payload.get("consent_proof_ref"))
    consent_purposes = normalize_string_list(
        payload.get("consent_purposes"), field="consent_purposes"
    )
    retention_policy = normalize(payload.get("retention_policy"))
    submitted_campaign_id = canonical_campaign_id(
        payload.get("campaign_id") or payload.get("campaign")
    )
    verified_campaign_id = canonical_campaign_id(source_campaign_id)
    if source_verified and not verified_campaign_id:
        # Direct library callers can still provide the legacy boolean, but the
        # stored attribution is always an explicit canonical campaign ID.
        verified_campaign_id = submitted_campaign_id
    if source_verified and (
        not verified_campaign_id or submitted_campaign_id != verified_campaign_id
    ):
        source_verified = False
        source_verification_reason = "lead campaign does not match its canonical source state"
    email = normalize(payload.get("email"))
    company = normalize(payload.get("company"))
    message = normalize(payload.get("message"))
    phone = normalize(payload.get("phone"))
    utm = normalize_utm(payload.get("utm", {}))
    warnings = lead_warnings(
        payload,
        source_verified=source_verified,
        source_verification_reason=source_verification_reason,
    )
    risk_flags = list(warnings)
    score = score_lead(
        email=email,
        company=company,
        phone=phone,
        message=message,
        consent_given=consent_given,
        source_verified=source_verified,
        utm=utm,
    )
    next_action = decide_next_action(
        qualification_score=score,
        consent_given=consent_given,
        email=email,
        phone=phone,
        source_verified=source_verified,
    )
    routing_allowed = (
        consent_given
        and bool(email or phone)
        and next_action in {"sales_follow_up", "manual_qualification"}
        and bool(set(consent_purposes) & (CRM_CONSENT_PURPOSES | {MAUTIC_CONSENT_PURPOSE}))
    )

    submitted_id = normalize(payload.get("id"))
    submitted_request_id = normalize(payload.get("request_id"))
    canonical_request = {
        "id": submitted_id,
        "request_id": submitted_request_id,
        "source_content_id": normalize(payload.get("source_content_id")),
        "campaign_id": verified_campaign_id or submitted_campaign_id,
        "campaign": normalize(payload.get("campaign")),
        "offer": normalize(payload.get("offer")),
        "persona": normalize(payload.get("persona")),
        "utm": utm,
        "consent_given": consent_given,
        "consent_at": consent_at,
        "privacy_notice_version": privacy_notice_version,
        "consent_source": consent_source,
        "consent_proof_ref": consent_proof_ref,
        "consent_purposes": consent_purposes,
        "retention_policy": retention_policy,
        "retention_expires_at": retention_expires_at,
        "company": company,
        "email": email,
        "contact_name": normalize(payload.get("contact_name")),
        "phone": phone,
        "message": message,
    }
    fingerprint = fingerprint_payload(canonical_request)
    explicit_id = submitted_id or submitted_request_id
    if (
        canonical_request["id"]
        and canonical_request["request_id"]
        and canonical_request["id"] != canonical_request["request_id"]
    ):
        raise ValueError("id and request_id must match when both are supplied")
    natural_key = {
        "source_content_id": canonical_request["source_content_id"],
        "consent_source": consent_source,
        "consent_proof_ref": consent_proof_ref,
    }
    lead_id = explicit_id or f"lead-{fingerprint_payload(natural_key)[:20]}"

    record = LeadRecord(
        id=lead_id,
        source_content_id=normalize(payload.get("source_content_id")),
        campaign_id=verified_campaign_id or submitted_campaign_id,
        campaign=normalize(payload.get("campaign")),
        offer=normalize(payload.get("offer")),
        persona=normalize(payload.get("persona")),
        utm=utm,
        consent_given=consent_given,
        consent_at=consent_at,
        privacy_notice_version=privacy_notice_version,
        consent_source=consent_source,
        consent_proof_ref=consent_proof_ref,
        consent_purposes=consent_purposes,
        retention_policy=retention_policy,
        retention_expires_at=retention_expires_at,
        company=company,
        email=email,
        contact_name=normalize(payload.get("contact_name")),
        phone=phone,
        message=message,
        qualification_score=score,
        next_action=next_action,
        source_verified=source_verified,
        routing_allowed=routing_allowed,
        risk_flags=risk_flags,
    )

    crm_allowed = bool(set(consent_purposes) & CRM_CONSENT_PURPOSES)
    mautic_allowed = MAUTIC_CONSENT_PURPOSE in consent_purposes
    return {
        "lead": record.to_dict(),
        "request_fingerprint": fingerprint,
        "revision": 1,
        "source_verified": source_verified,
        "routing_allowed": routing_allowed,
        "warnings": warnings,
        "crm_payload": crm_payload(record) if routing_allowed and crm_allowed else {},
        "mautic_payload": (
            mautic_payload(record) if routing_allowed and mautic_allowed and bool(email) else {}
        ),
        "privacy": {
            "status": "active",
            "consent_status": "granted",
            "suppression_status": "active",
            "erasure_status": "not_requested",
            "external_privacy_action_required": False,
            "external_privacy_action_targets": [],
            "provider_erasure_status": "not_requested",
            "retention_policy": retention_policy,
            "retention_expires_at": retention_expires_at,
            "last_action": "intake",
            "updated_at": record.created_at,
        },
    }


def validate_lead_payload(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = ("source_content_id", "campaign", "offer", "persona")
    for key in required:
        if not normalize(payload.get(key)):
            errors.append(f"{key} is required")

    if "consent_given" not in payload:
        errors.append("consent_given is required")
    elif not isinstance(payload.get("consent_given"), bool):
        errors.append("consent_given must be the JSON boolean true or false")
    elif payload.get("consent_given") is not True:
        errors.append("consent_given must be affirmative (true)")

    for key in (
        "consent_at",
        "privacy_notice_version",
        "consent_source",
        "consent_proof_ref",
        "retention_policy",
        "retention_expires_at",
    ):
        if not normalize(payload.get(key)):
            errors.append(f"{key} is required")

    try:
        consent_at = aware_timestamp(payload.get("consent_at"), field="consent_at")
        retention_expires_at = aware_timestamp(
            payload.get("retention_expires_at"), field="retention_expires_at"
        )
        now = datetime.now(timezone.utc)
        if consent_at > now + timedelta(minutes=5):
            errors.append("consent_at cannot be in the future")
        if retention_expires_at <= consent_at:
            errors.append("retention_expires_at must be after consent_at")
        if retention_expires_at <= now:
            errors.append("retention_expires_at must be in the future")
        retention_policy = normalize(payload.get("retention_policy"))
        max_duration = RETENTION_POLICY_MAX_DURATIONS.get(retention_policy)
        if max_duration is None:
            errors.append(f"unsupported retention_policy: {retention_policy or 'missing'}")
        elif retention_expires_at > consent_at + max_duration:
            errors.append(
                "retention_expires_at exceeds the configured maximum for "
                f"retention_policy {retention_policy}"
            )
    except ValueError as exc:
        errors.append(str(exc))

    try:
        purposes = normalize_string_list(
            payload.get("consent_purposes"), field="consent_purposes"
        )
        if not purposes:
            errors.append("consent_purposes must contain at least one purpose")
    except ValueError as exc:
        errors.append(str(exc))

    email = normalize(payload.get("email"))
    if email and not valid_email(email):
        errors.append("email is invalid")

    utm = payload.get("utm", {})
    if not isinstance(utm, dict):
        errors.append("utm must be an object")

    return errors


def apply_lead_lifecycle(
    current: dict[str, Any],
    *,
    action: str,
    operator: str,
    reason: str,
    occurred_at: str,
) -> dict[str, Any]:
    """Return a privacy-safe next lead state; storage performs the atomic CAS."""

    normalized_action = normalize(action).lower()
    if normalized_action not in LEAD_LIFECYCLE_ACTIONS:
        raise ValueError(f"unsupported lead lifecycle action: {action}")
    if normalized_action == "erase":
        normalized_action = "anonymize"
    occurred = aware_timestamp(occurred_at, field="occurred_at")
    if occurred > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise ValueError("occurred_at cannot be in the future")

    result = deepcopy(current)
    lead = result.get("lead", {})
    privacy = result.get("privacy", {})
    if not isinstance(lead, dict):
        raise ValueError("lead is missing its privacy lifecycle record")
    if not isinstance(privacy, dict) or not privacy:
        if normalized_action != "anonymize":
            raise ValueError("lead is missing its privacy lifecycle record")
        privacy = {
            "status": "legacy_unverified",
            "consent_status": "unverified",
            "suppression_status": "suppressed",
            "erasure_status": "requested",
            "retention_policy": str(lead.get("retention_policy", "legacy_unspecified")),
            "retention_expires_at": str(lead.get("retention_expires_at", ""))
            or occurred.isoformat(),
        }
    if privacy.get("status") == "anonymized":
        if normalized_action == "anonymize":
            return result
        raise ValueError("anonymized leads cannot transition to another lifecycle state")

    retention_expires_at = aware_timestamp(
        privacy.get("retention_expires_at") or lead.get("retention_expires_at"),
        field="retention_expires_at",
    )
    if normalized_action == "expire_retention" and occurred < retention_expires_at:
        raise ValueError("retention has not expired")

    if normalized_action == "suppress":
        privacy["status"] = "suppressed"
        privacy["suppression_status"] = "suppressed"
    elif normalized_action == "withdraw_consent":
        privacy["status"] = "withdrawn"
        privacy["consent_status"] = "withdrawn"
        privacy["suppression_status"] = "suppressed"
        privacy["withdrawn_at"] = occurred.isoformat()
        lead["consent_given"] = False
    else:
        privacy["status"] = "anonymized"
        privacy["consent_status"] = "withdrawn"
        privacy["suppression_status"] = "suppressed"
        privacy["erasure_status"] = "anonymized"
        privacy["anonymized_at"] = occurred.isoformat()
        if normalized_action == "expire_retention":
            privacy["retention_disposition"] = "expired_and_anonymized"
        for field_name in PII_FIELDS:
            lead[field_name] = ""
        lead["utm"] = {}
        lead["consent_given"] = False
        lead["consent_proof_ref"] = ""
        lead["consent_source"] = ""
        lead["consent_purposes"] = []

    privacy["last_action"] = normalized_action
    privacy["last_operator"] = operator
    privacy["last_reason"] = reason
    privacy["updated_at"] = occurred.isoformat()
    result["lead"] = lead
    result["privacy"] = privacy
    result["routing_allowed"] = False
    lead["routing_allowed"] = False
    result["crm_payload"] = {}
    result["mautic_payload"] = {}
    return result


def lead_routing_block_reason(
    lead_result: dict[str, Any],
    *,
    target: str,
    now: datetime | None = None,
) -> str:
    """Fail closed when consent, suppression, retention, or purpose is invalid."""

    lead = lead_result.get("lead", {})
    privacy = lead_result.get("privacy", {})
    if not isinstance(lead, dict) or not isinstance(privacy, dict):
        return "lead has no verified privacy lifecycle record"
    if not lead_result.get("routing_allowed"):
        return f"lead is not routable: {lead.get('next_action', 'unknown')}"
    if lead_result.get("source_verified") is not True or lead.get("source_verified") is not True:
        return "lead source attribution is not verified"
    campaign_id = canonical_campaign_id(lead.get("campaign_id"))
    if not campaign_id:
        return "lead source attribution has no canonical K1-K5 campaign"
    if lead.get("consent_given") is not True or privacy.get("consent_status") != "granted":
        return "lead consent is not active"
    if privacy.get("status") != "active" or privacy.get("suppression_status") != "active":
        return f"lead privacy status blocks routing: {privacy.get('status', 'unknown')}"
    try:
        consent_at = aware_timestamp(lead.get("consent_at"), field="consent_at")
        expires_at = aware_timestamp(
            privacy.get("retention_expires_at") or lead.get("retention_expires_at"),
            field="retention_expires_at",
        )
    except ValueError:
        return "lead retention evidence is invalid"
    retention_policy = normalize(
        privacy.get("retention_policy") or lead.get("retention_policy")
    )
    max_duration = RETENTION_POLICY_MAX_DURATIONS.get(retention_policy)
    if max_duration is None:
        return "lead retention policy is unsupported"
    if expires_at > consent_at + max_duration:
        return "lead retention period exceeds its configured policy maximum"
    if expires_at <= (now or datetime.now(timezone.utc)):
        return "lead retention period has expired"
    purposes = set(lead.get("consent_purposes", []))
    if target == "twenty" and not purposes.intersection(CRM_CONSENT_PURPOSES):
        return "lead consent does not cover CRM sales follow-up"
    if target == "mautic" and MAUTIC_CONSENT_PURPOSE not in purposes:
        return "lead consent does not cover marketing automation"
    if target == "twenty" and not lead_result.get("crm_payload"):
        return "lead CRM payload is unavailable"
    if target == "mautic" and not lead_result.get("mautic_payload"):
        return "lead marketing payload is unavailable"
    return ""


def lead_warnings(
    payload: dict[str, Any],
    *,
    source_verified: bool,
    source_verification_reason: str = "",
) -> list[str]:
    warnings: list[str] = []
    email = normalize(payload.get("email"))
    phone = normalize(payload.get("phone"))
    if not source_verified:
        warnings.append(
            source_verification_reason
            or "source_content_id was not found in stored canonical campaign states"
        )
    if not email and not phone:
        warnings.append("lead has no email or phone for follow-up")
    if email and email_domain(email) in GENERIC_EMAIL_DOMAINS:
        warnings.append("email uses a generic domain; qualify manually")
    utm = normalize_utm(payload.get("utm", {}))
    missing_utm = [key for key in ("utm_source", "utm_medium", "utm_campaign") if not utm.get(key)]
    if missing_utm:
        warnings.append(f"missing UTM fields: {', '.join(missing_utm)}")
    if not coerce_bool(payload.get("consent_given")):
        warnings.append("consent missing; do not route to marketing automation")
    return warnings


def score_lead(
    *,
    email: str,
    company: str,
    phone: str,
    message: str,
    consent_given: bool,
    source_verified: bool,
    utm: dict[str, str],
) -> int:
    score = 0
    if source_verified:
        score += 20
    if all(utm.get(key) for key in ("utm_source", "utm_medium", "utm_campaign")):
        score += 15
    if consent_given:
        score += 25
    if company:
        score += 15
    if email:
        score += 8 if email_domain(email) in GENERIC_EMAIL_DOMAINS else 15
    if phone:
        score += 5
    if any(keyword in message.lower() for keyword in INTENT_KEYWORDS):
        score += 5
    return min(score, 100)


def decide_next_action(
    *,
    qualification_score: int,
    consent_given: bool,
    email: str,
    phone: str,
    source_verified: bool,
) -> str:
    if not consent_given:
        return "consent_required"
    if not email and not phone:
        return "contact_missing"
    if not source_verified:
        return "manual_source_review"
    if qualification_score >= 75:
        return "sales_follow_up"
    if qualification_score >= 55:
        return "manual_qualification"
    return "nurture_or_disqualify"


def crm_payload(record: LeadRecord) -> dict[str, Any]:
    return {
        "external_id": record.id,
        "source_content_id": record.source_content_id,
        "campaign": record.campaign,
        "persona": record.persona,
        "offer": record.offer,
        "qualification_score": record.qualification_score,
        "next_action": record.next_action,
        "contact": {
            "name": record.contact_name,
            "company": record.company,
            "email": record.email,
            "phone": record.phone,
        },
        "utm": record.utm,
        "message": record.message,
        "risk_flags": record.risk_flags,
    }


def mautic_payload(record: LeadRecord) -> dict[str, Any]:
    return {
        "email": record.email,
        "firstname": record.contact_name,
        "company": record.company,
        "tags": [
            "wamocon-marketing-machine",
            slug(record.campaign),
            slug(record.persona),
            slug(record.offer),
        ],
        "utm": record.utm,
        "source_content_id": record.source_content_id,
    }


def normalize(value: Any) -> str:
    return str(value or "").strip()


def normalize_utm(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): normalize(item) for key, item in value.items()}


def normalize_string_list(value: Any, *, field: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array of non-empty strings")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{field} must contain only non-empty strings")
        normalized = item.strip().lower()
        if normalized not in result:
            result.append(normalized)
    return result


def aware_timestamp(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc)


def normalized_timestamp(value: Any, *, field: str) -> str:
    return aware_timestamp(value, field=field).isoformat()


def fingerprint_payload(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    raise ValueError("consent_given must be the JSON boolean true or false")


def valid_email(value: str) -> bool:
    return bool(re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value))


def email_domain(value: str) -> str:
    return value.rsplit("@", 1)[-1].lower() if "@" in value else ""


def slug(value: str) -> str:
    clean = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return clean or "unknown"


def canonical_campaign_id(value: Any) -> str:
    campaign_id = resolve_campaign_id(normalize(value))
    return campaign_id if campaign_id in CANONICAL_CAMPAIGN_IDS else ""


def published_source_evidence_error(source_state: dict[str, Any], brief: dict[str, Any]) -> str:
    """Return why a content state is not a provider-confirmed public source."""

    if normalize(brief.get("status")).casefold() != "published":
        return "source content is not provider-confirmed as published"
    lifecycle = source_state.get("lifecycle", {})
    if not isinstance(lifecycle, dict) or not lifecycle:
        return "source content has no provider publication evidence"
    provider_post_id = normalize(lifecycle.get("provider_post_id"))
    route_id = normalize(lifecycle.get("route_id"))
    verification_method = normalize(lifecycle.get("verification_method")).casefold()
    source_ref = normalize(lifecycle.get("source_ref"))
    if (
        normalize(lifecycle.get("provider")).casefold() != "postiz"
        or normalize(lifecycle.get("provider_status")).casefold() != "published"
        or not provider_post_id
        or not route_id
        or not source_ref
        or verification_method not in {"postiz_api", "operator_postiz_ui"}
    ):
        return "source content publication evidence is incomplete"
    if verification_method == "operator_postiz_ui" and not normalize(lifecycle.get("operator")):
        return "source content publication evidence has no named reviewer"
    try:
        published_at = aware_timestamp(lifecycle.get("published_at"), field="published_at")
        observed_at = aware_timestamp(lifecycle.get("last_observed_at"), field="last_observed_at")
    except ValueError:
        return "source content publication timestamps are invalid"
    if observed_at + timedelta(minutes=5) < published_at:
        return "source content publication timestamps are inconsistent"
    events = lifecycle.get("events", [])
    if not isinstance(events, list) or not any(
        isinstance(event, dict)
        and normalize(event.get("provider")).casefold() == "postiz"
        and normalize(event.get("provider_status")).casefold() == "published"
        and normalize(event.get("provider_post_id")) == provider_post_id
        and normalize(event.get("route_id")) == route_id
        and normalize(event.get("verification_method")).casefold() == verification_method
        and bool(re.fullmatch(r"[a-f0-9]{64}", normalize(event.get("request_fingerprint")).casefold()))
        for event in events
    ):
        return "source content has no matching immutable publication event"
    return ""


def verify_lead_source_attribution(
    lead_payload: dict[str, Any],
    source_state: dict[str, Any] | None,
    *,
    source_is_demo: bool,
) -> tuple[bool, str, str]:
    """Bind a lead to one non-demo content state from the canonical K1-K5 catalog."""

    if not isinstance(source_state, dict):
        return False, "", "source_content_id was not found in stored campaign states"
    brief = source_state.get("brief", {})
    if not isinstance(brief, dict):
        return False, "", "source content state has no valid campaign brief"
    source_content_id = normalize(lead_payload.get("source_content_id"))
    if not source_content_id or normalize(brief.get("id")) != source_content_id:
        return False, "", "source_content_id does not match the stored source state"
    if source_is_demo:
        return False, "", "source content is demo or unverified and cannot route a lead"
    publication_error = published_source_evidence_error(source_state, brief)
    if publication_error:
        return False, "", publication_error
    source_campaign_id = canonical_campaign_id(
        brief.get("campaign_id") or brief.get("campaign")
    )
    if not source_campaign_id:
        return False, "", "source content is not assigned to a canonical K1-K5 campaign"
    submitted_campaign_id = canonical_campaign_id(
        lead_payload.get("campaign_id") or lead_payload.get("campaign")
    )
    if submitted_campaign_id != source_campaign_id:
        return (
            False,
            source_campaign_id,
            "lead campaign does not match its canonical source state",
        )
    return True, source_campaign_id, ""


def make_json_safe(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    return value
