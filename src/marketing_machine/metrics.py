from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .campaign_catalog import load_campaign_catalog
from .storage import JsonStore


PROMETHEUS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"
ATTENTION_STATUSES = {"needs_human_review", "revision_requested", "needs_evidence", "blocked"}


def render_prometheus_metrics(store: JsonStore | None = None) -> str:
    """Render low-cardinality operational metrics without content or personal data."""

    storage = store or JsonStore()
    states = storage.list_states(limit=100_000, include_demo=False)
    trend_runs = storage.list_trend_runs(limit=100)
    try:
        catalog = load_campaign_catalog(Path(__file__).resolve().parents[2])
        catalog_ids = {str(item.get("id", "")) for item in catalog}
        catalog_count = len(catalog)
        catalog_load_error = 0 if catalog_ids == {"k1", "k2", "k3", "k4", "k5"} else 1
    except (OSError, ValueError, TypeError):
        catalog_count = 0
        catalog_load_error = 1
    state_counts = Counter(
        (
            str(item.get("campaign_id") or "unknown"),
            str(item.get("status") or "unknown"),
        )
        for item in states
    )
    trend_counts = Counter(str(item.get("status") or "unknown") for item in trend_runs)
    ai_generated = [
        item
        for item in states
        if isinstance(item.get("generation"), dict)
        and item["generation"].get("status") == "ai_generated"
    ]
    attention_count = sum(1 for item in states if str(item.get("status")) in ATTENTION_STATUSES)

    lines = [
        "# HELP marketing_machine_up Marketing-machine metrics endpoint availability.",
        "# TYPE marketing_machine_up gauge",
        "marketing_machine_up 1",
        "# HELP marketing_machine_campaign_catalog_total Number of canonical campaigns configured for this product.",
        "# TYPE marketing_machine_campaign_catalog_total gauge",
        f"marketing_machine_campaign_catalog_total {catalog_count}",
        "# HELP marketing_machine_campaign_catalog_load_error 1 when the canonical five-campaign catalog is missing or invalid.",
        "# TYPE marketing_machine_campaign_catalog_load_error gauge",
        f"marketing_machine_campaign_catalog_load_error {catalog_load_error}",
        "# HELP marketing_machine_campaigns Number of canonical campaigns represented in stored content state.",
        "# TYPE marketing_machine_campaigns gauge",
        f"marketing_machine_campaigns {len({campaign for campaign, _status in state_counts if campaign != 'unknown'})}",
        "# HELP marketing_machine_content_items Content items by canonical campaign and workflow status.",
        "# TYPE marketing_machine_content_items gauge",
    ]
    for (campaign_id, status), count in sorted(state_counts.items()):
        lines.append(
            "marketing_machine_content_items"
            f'{{campaign_id="{_label(campaign_id)}",status="{_label(status)}"}} {count}'
        )
    lines.extend(
        [
            "# HELP marketing_machine_review_attention_items Drafts that need review, evidence, revision, or blocker resolution.",
            "# TYPE marketing_machine_review_attention_items gauge",
            f"marketing_machine_review_attention_items {attention_count}",
            "# HELP marketing_machine_ai_generated_items Active items with stored successful AI provenance.",
            "# TYPE marketing_machine_ai_generated_items gauge",
            f"marketing_machine_ai_generated_items {len(ai_generated)}",
            "# HELP marketing_machine_trend_runs Research runs by current stored run status.",
            "# TYPE marketing_machine_trend_runs gauge",
        ]
    )
    for status, count in sorted(trend_counts.items()):
        lines.append(f'marketing_machine_trend_runs{{status="{_label(status)}"}} {count}')

    latest_ai = max((_timestamp(item.get("updated_at")) for item in ai_generated), default=0.0)
    lines.extend(
        [
            "# HELP marketing_machine_last_ai_generation_timestamp_seconds Latest stored successful AI generation time.",
            "# TYPE marketing_machine_last_ai_generation_timestamp_seconds gauge",
            f"marketing_machine_last_ai_generation_timestamp_seconds {latest_ai:.3f}",
        ]
    )
    return "\n".join(lines) + "\n"


def _timestamp(value: Any) -> float:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _label(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')
