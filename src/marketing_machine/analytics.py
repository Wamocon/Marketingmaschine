from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from .schemas import OptimizationAction, PerformanceRecord


@dataclass
class OptimizationDecision:
    action: OptimizationAction
    reason: str


SHA256_HEX = re.compile(r"^[a-fA-F0-9]{64}$")
PERFORMANCE_METRIC_FIELDS = {
    "impressions",
    "saves",
    "shares",
    "comments_from_target_buyers",
    "profile_visits",
    "clicks",
    "leads",
    "qualified_leads",
    "booked_calls",
    "pipeline_value_eur",
    "landing_page_visits",
    "landing_page_conversions",
}


def validate_performance_record(record: PerformanceRecord) -> list[str]:
    """Validate funnel consistency and the evidence needed to audit a decision."""

    errors: list[str] = []
    if record.qualified_leads > record.leads:
        errors.append("qualified_leads cannot exceed leads")
    if record.booked_calls > record.qualified_leads:
        errors.append("booked_calls cannot exceed qualified_leads")
    if record.landing_page_conversions > record.landing_page_visits:
        errors.append("landing_page_conversions cannot exceed landing_page_visits")
    if record.pipeline_value_eur > 0 and not (record.qualified_leads or record.booked_calls):
        errors.append("pipeline_value_eur requires at least one qualified lead or booked call")

    if not record.source_system.strip():
        errors.append("source_system is required")
    if not record.source_ref.strip():
        errors.append("source_ref is required")
    if record.source_system.strip().lower() == "manual" and not record.operator.strip():
        errors.append("operator is required for manual analytics entry")
    if not record.attribution_rule.strip():
        errors.append("attribution_rule is required")

    parsed: dict[str, datetime] = {}
    for field_name in ("period_start", "period_end", "retrieved_at"):
        value = str(getattr(record, field_name, "")).strip()
        if not value:
            errors.append(f"{field_name} is required")
            continue
        try:
            timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            errors.append(f"{field_name} must be an ISO-8601 timestamp")
            continue
        if timestamp.tzinfo is None:
            errors.append(f"{field_name} must include a timezone")
            continue
        parsed[field_name] = timestamp.astimezone(timezone.utc)
    if parsed.get("period_start") and parsed.get("period_end"):
        if parsed["period_end"] < parsed["period_start"]:
            errors.append("period_end cannot be before period_start")
    if parsed.get("period_end") and parsed.get("retrieved_at"):
        if parsed["retrieved_at"] < parsed["period_end"]:
            errors.append("retrieved_at cannot be before period_end")

    if record.snapshot_sha256 and not SHA256_HEX.fullmatch(record.snapshot_sha256.strip()):
        errors.append("snapshot_sha256 must be a 64-character hexadecimal SHA-256 digest")
    if not isinstance(record.evidence, list) or not record.evidence:
        errors.append("evidence must contain at least one metric source artifact")
    else:
        covered: set[str] = set()
        for index, item in enumerate(record.evidence):
            prefix = f"evidence[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{prefix} must be an object")
                continue
            if not str(item.get("system", "")).strip():
                errors.append(f"{prefix}.system is required")
            if not str(item.get("ref", "")).strip():
                errors.append(f"{prefix}.ref is required")
            digest = str(item.get("sha256", "")).strip()
            if not SHA256_HEX.fullmatch(digest):
                errors.append(f"{prefix}.sha256 must be a 64-character hexadecimal SHA-256 digest")
            try:
                retrieved = datetime.fromisoformat(
                    str(item.get("retrieved_at", "")).replace("Z", "+00:00")
                )
                if retrieved.tzinfo is None:
                    raise ValueError
                retrieved = retrieved.astimezone(timezone.utc)
                if parsed.get("period_end") and retrieved < parsed["period_end"]:
                    errors.append(f"{prefix}.retrieved_at cannot be before period_end")
                if parsed.get("retrieved_at") and retrieved > parsed["retrieved_at"]:
                    errors.append(
                        f"{prefix}.retrieved_at cannot be after the submission retrieved_at"
                    )
            except ValueError:
                errors.append(f"{prefix}.retrieved_at must be an ISO-8601 timestamp with timezone")
            fields = item.get("metric_fields", [])
            if not isinstance(fields, list) or not fields:
                errors.append(f"{prefix}.metric_fields must be a non-empty array")
                continue
            unknown = {str(field) for field in fields} - PERFORMANCE_METRIC_FIELDS
            if unknown:
                errors.append(f"{prefix}.metric_fields contains unsupported fields: {', '.join(sorted(unknown))}")
            covered.update(str(field) for field in fields if str(field) in PERFORMANCE_METRIC_FIELDS)

        nonzero = {
            field
            for field in PERFORMANCE_METRIC_FIELDS
            if float(getattr(record, field, 0) or 0) > 0
        }
        missing_coverage = nonzero - covered
        if missing_coverage:
            errors.append(
                "evidence does not cover non-zero metric fields: "
                + ", ".join(sorted(missing_coverage))
            )
    return errors


def evaluate_performance(record: PerformanceRecord) -> OptimizationDecision:
    if record.review_window == "72h":
        if record.impressions < 250 and record.clicks == 0 and record.comments_from_target_buyers == 0:
            return OptimizationDecision(OptimizationAction.ITERATE, "weak early signal; test stronger hook or thumbnail")
        return OptimizationDecision(OptimizationAction.WAIT_FOR_MORE_DATA, "early signal exists; wait for weekly read")

    if record.review_window in {"7d", "14d"}:
        if record.clicks > 0 and record.leads == 0:
            return OptimizationDecision(OptimizationAction.FIX_LANDING_PAGE, "clicks without leads indicate landing-page or offer friction")
        if record.comments_from_target_buyers == 0 and record.leads == 0 and record.impressions >= 1000:
            return OptimizationDecision(OptimizationAction.FIX_AUDIENCE_OR_OFFER, "reach without buyer signal indicates audience or offer mismatch")
        if record.qualified_leads > 0 or record.booked_calls > 0:
            return OptimizationDecision(OptimizationAction.SCALE, "qualified commercial signal detected")
        if record.review_window == "14d":
            return OptimizationDecision(OptimizationAction.STOP, "no useful business signal after 14 days")

    if record.review_window == "30d":
        if record.qualified_leads >= 3 or record.booked_calls >= 1 or record.pipeline_value_eur > 0:
            return OptimizationDecision(OptimizationAction.SCALE, "30-day business value threshold met")
        return OptimizationDecision(OptimizationAction.STOP, "30-day test did not produce qualified business value")

    return OptimizationDecision(OptimizationAction.WAIT_FOR_MORE_DATA, "review window not decisive")
