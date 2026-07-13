from __future__ import annotations

import argparse
import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .schemas import ContentStatus
from .storage import JsonStore, _write_json_atomic, brief_from_dict
from .trend_research import validate_trend_brief_against_run


TERMINAL_CONTENT_STATUSES = {
    ContentStatus.APPROVED.value,
    ContentStatus.READY_TO_SCHEDULE.value,
    ContentStatus.SCHEDULED.value,
    ContentStatus.PUBLISHED.value,
}


def remediate_invalid_trend_draft(
    store: JsonStore,
    content_id: str,
    *,
    apply: bool = False,
    operator: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Archive and block a draft whose stored trend evidence no longer validates.

    The command is dry-run by default. Applying it writes immutable snapshots of
    the original state and research run before changing the active state to
    ``blocked``. It never rewrites the trend run and refuses terminal content.
    A fresh research run must produce any future replacement draft.
    """

    current = store.load_state(content_id)
    prior_history = current.get("remediation_history", [])
    if isinstance(prior_history, list) and any(
        isinstance(item, dict) and item.get("kind") == "trend_evidence_invalidated"
        for item in prior_history
    ):
        return {
            "status": "already_remediated",
            "content_id": content_id,
            "dry_run": not apply,
            "idempotent": True,
        }

    brief_data = current.get("brief")
    if not isinstance(brief_data, dict):
        raise ValueError("stored state has no valid brief")
    brief = brief_from_dict(brief_data)
    if not brief.trend_id or not brief.trend_run_id:
        raise ValueError("content is not backed by a stored trend run")
    if brief.status.value in TERMINAL_CONTENT_STATUSES or current.get("approval") is not None:
        raise ValueError("terminal or already reviewed content must not be remediated in place")
    if current.get("scheduler_payload"):
        raise ValueError("content with a scheduler payload must not be remediated in place")

    trend_run = store.load_trend_run(brief.trend_run_id)
    checked_at = now or datetime.now(timezone.utc)
    validation_errors = validate_trend_brief_against_run(brief, trend_run, now=checked_at)
    if not validation_errors:
        raise ValueError("stored trend evidence still validates; refusing remediation")

    timestamp = checked_at.astimezone(timezone.utc)
    timestamp_text = timestamp.isoformat()
    archive_name = f"{timestamp.strftime('%Y%m%dT%H%M%SZ')}-{content_id}"
    archive_dir = store.root / "archive" / "trend-evidence" / archive_name
    archive_ref = archive_dir.relative_to(store.root).as_posix()
    summary = {
        "status": "would_block" if not apply else "blocked",
        "content_id": content_id,
        "trend_run_id": brief.trend_run_id,
        "dry_run": not apply,
        "idempotent": False,
        "validation_errors": validation_errors,
        "archive": archive_ref,
    }
    if not apply:
        return summary
    if not str(operator).strip():
        raise ValueError("operator is required when applying remediation")
    if archive_dir.exists():
        raise FileExistsError(f"archive already exists: {archive_ref}")

    archive_dir.mkdir(parents=True, exist_ok=False)
    _write_json_atomic(archive_dir / "state.json", current)
    _write_json_atomic(archive_dir / "trend-run.json", trend_run)
    manifest = {
        "kind": "trend_evidence_invalidated",
        "content_id": content_id,
        "trend_run_id": brief.trend_run_id,
        "archived_at": timestamp_text,
        "operator": str(operator).strip(),
        "validation_errors": validation_errors,
        "state_sha256": _json_sha256(current),
        "trend_run_sha256": _json_sha256(trend_run),
    }
    _write_json_atomic(archive_dir / "manifest.json", manifest)

    updated = copy.deepcopy(current)
    updated_brief = updated["brief"]
    previous_status = str(updated_brief.get("status", ""))
    previous_next_step = str(updated.get("next_step", ""))
    updated_brief["status"] = ContentStatus.BLOCKED.value
    updated_brief["trend_verification_status"] = "source_verification_failed"
    updated_brief["updated_at"] = timestamp_text
    risk_flags = [str(item) for item in updated_brief.get("risk_flags", []) if str(item)]
    if "exact_topic_corroboration_failed" not in risk_flags:
        risk_flags.append("exact_topic_corroboration_failed")
    updated_brief["risk_flags"] = risk_flags
    error = "trend evidence invalidated: " + "; ".join(validation_errors)
    errors = [str(item) for item in updated.get("errors", []) if str(item)]
    if error not in errors:
        errors.append(error)
    updated["errors"] = errors
    updated["next_step"] = "research"
    updated["requires_human_review"] = False
    updated["scheduler_payload"] = {}
    history = list(prior_history) if isinstance(prior_history, list) else []
    history.append(
        {
            **manifest,
            "archive": archive_ref,
            "previous_status": previous_status,
            "previous_next_step": previous_next_step,
        }
    )
    updated["remediation_history"] = history
    store.save_state(updated)
    store.append_event(
        "trend_evidence_remediation",
        {
            **manifest,
            "archive": archive_ref,
            "previous_status": previous_status,
            "previous_next_step": previous_next_step,
            "new_status": ContentStatus.BLOCKED.value,
            "next_step": "research",
        },
    )
    return summary


def _json_sha256(payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Archive and block a persisted draft whose exact trend-topic evidence no longer validates."
    )
    parser.add_argument("content_id")
    parser.add_argument("--data-dir", type=Path, default=None)
    parser.add_argument("--operator", default="")
    parser.add_argument("--apply", action="store_true", help="Apply after the default dry-run has been reviewed.")
    args = parser.parse_args(argv)
    store = JsonStore(args.data_dir) if args.data_dir else JsonStore()
    result = remediate_invalid_trend_draft(
        store,
        args.content_id,
        apply=args.apply,
        operator=args.operator,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
