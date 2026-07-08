from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .schemas import ContentBrief, ContentStatus


def data_dir() -> Path:
    root = Path(os.environ.get("MARKETING_MACHINE_DATA_DIR", "runtime-data"))
    root.mkdir(parents=True, exist_ok=True)
    for child in ("states", "events", "performance", "leads", "outbox", "trend_runs", "reel_concepts", "learning"):
        (root / child).mkdir(parents=True, exist_ok=True)
    return root


def brief_from_dict(data: dict[str, Any]) -> ContentBrief:
    payload = dict(data)
    payload["status"] = ContentStatus(payload.get("status", ContentStatus.DRAFTING.value))
    return ContentBrief(**payload)


class JsonStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or data_dir()
        for child in ("states", "events", "performance", "leads", "outbox", "trend_runs", "reel_concepts", "learning"):
            (self.root / child).mkdir(parents=True, exist_ok=True)

    def list_states(self, limit: int = 25) -> list[dict[str, Any]]:
        states_dir = self.root / "states"
        paths = sorted(states_dir.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        items: list[dict[str, Any]] = []
        for path in paths[: max(0, limit)]:
            try:
                state = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            brief = state.get("brief", {})
            items.append(
                {
                    "content_id": brief.get("id", path.stem),
                    "campaign": brief.get("campaign", ""),
                    "persona": brief.get("persona", ""),
                    "channel": brief.get("channel", ""),
                    "status": brief.get("status", ""),
                    "next_step": state.get("next_step", ""),
                    "updated_at": brief.get("updated_at", ""),
                    "requires_human_review": bool(state.get("requires_human_review", False)),
                    "has_scheduler_payload": bool(state.get("scheduler_payload")),
                }
            )
        return items

    def save_state(self, state: dict[str, Any]) -> Path:
        content_id = state["brief"]["id"]
        path = self.root / "states" / f"{content_id}.json"
        path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def load_state(self, content_id: str) -> dict[str, Any]:
        path = self.root / "states" / f"{content_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"content state not found: {content_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def append_event(self, name: str, payload: dict[str, Any]) -> Path:
        path = self.root / "events" / f"{name}.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return path

    def append_performance(self, payload: dict[str, Any]) -> Path:
        path = self.root / "performance" / "records.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return path

    def list_performance(self, limit: int = 25) -> list[dict[str, Any]]:
        path = self.root / "performance" / "records.jsonl"
        if not path.exists():
            return []
        items: list[dict[str, Any]] = []
        for line in reversed(path.read_text(encoding="utf-8").splitlines()):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            record = payload.get("record", {})
            if not isinstance(record, dict):
                continue
            items.append(
                {
                    "content_id": record.get("content_id", ""),
                    "review_window": record.get("review_window", ""),
                    "action": payload.get("action", ""),
                    "reason": payload.get("reason", ""),
                    "qualified_leads": record.get("qualified_leads", 0),
                    "booked_calls": record.get("booked_calls", 0),
                    "pipeline_value_eur": record.get("pipeline_value_eur", 0.0),
                    "created_at": record.get("created_at", ""),
                }
            )
            if len(items) >= max(0, limit):
                break
        return items

    def append_lead(self, payload: dict[str, Any]) -> Path:
        path = self.root / "leads" / "records.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return path

    def list_leads(self, limit: int = 25) -> list[dict[str, Any]]:
        path = self.root / "leads" / "records.jsonl"
        if not path.exists():
            return []
        items: list[dict[str, Any]] = []
        for line in reversed(path.read_text(encoding="utf-8").splitlines()):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            lead = payload.get("lead", payload)
            if not isinstance(lead, dict):
                continue
            items.append(
                {
                    "id": lead.get("id", ""),
                    "source_content_id": lead.get("source_content_id", ""),
                    "campaign": lead.get("campaign", ""),
                    "company": lead.get("company", ""),
                    "qualification_score": lead.get("qualification_score", 0),
                    "next_action": lead.get("next_action", ""),
                    "routing_allowed": bool(lead.get("routing_allowed", False)),
                    "created_at": lead.get("created_at", ""),
                }
            )
            if len(items) >= max(0, limit):
                break
        return items

    def load_lead(self, lead_id: str) -> dict[str, Any]:
        path = self.root / "leads" / "records.jsonl"
        if not path.exists():
            raise FileNotFoundError(f"lead not found: {lead_id}")
        for line in reversed(path.read_text(encoding="utf-8").splitlines()):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            lead = payload.get("lead", payload)
            if isinstance(lead, dict) and lead.get("id") == lead_id:
                return payload
        raise FileNotFoundError(f"lead not found: {lead_id}")

    def append_outbox(self, payload: dict[str, Any]) -> Path:
        path = self.root / "outbox" / "records.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return path

    def list_outbox(self, limit: int = 25) -> list[dict[str, Any]]:
        path = self.root / "outbox" / "records.jsonl"
        if not path.exists():
            return []
        items: list[dict[str, Any]] = []
        for line in reversed(path.read_text(encoding="utf-8").splitlines()):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            items.append(
                {
                    "id": payload.get("id", ""),
                    "kind": payload.get("kind", ""),
                    "target": payload.get("target", ""),
                    "status": payload.get("status", ""),
                    "dry_run": bool(payload.get("dry_run", True)),
                    "source_id": payload.get("source_id", ""),
                    "reason": payload.get("reason", ""),
                    "created_at": payload.get("created_at", ""),
                }
            )
            if len(items) >= max(0, limit):
                break
        return items

    def save_trend_run(self, payload: dict[str, Any]) -> Path:
        path = self.root / "trend_runs" / f"{payload['id']}.json"
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def load_trend_run(self, run_id: str) -> dict[str, Any]:
        path = self.root / "trend_runs" / f"{run_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"trend run not found: {run_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def list_trend_runs(self, limit: int = 25) -> list[dict[str, Any]]:
        paths = sorted((self.root / "trend_runs").glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        items: list[dict[str, Any]] = []
        for path in paths[: max(0, limit)]:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            campaigns = payload.get("campaigns", [])
            trend_count = sum(len(item.get("trends", [])) for item in campaigns if isinstance(item, dict))
            items.append(
                {
                    "id": payload.get("id", path.stem),
                    "status": payload.get("status", ""),
                    "run_started_at": payload.get("run_started_at", ""),
                    "lookback_days": payload.get("lookback_days", 0),
                    "platforms": payload.get("platforms", []),
                    "campaign_count": len(campaigns) if isinstance(campaigns, list) else 0,
                    "trend_count": trend_count,
                    "source_adapters": payload.get("source_adapters", []),
                }
            )
        return items

    def save_reel_concept(self, payload: dict[str, Any]) -> Path:
        path = self.root / "reel_concepts" / f"{payload['id']}.json"
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def load_reel_concept(self, concept_id: str) -> dict[str, Any]:
        path = self.root / "reel_concepts" / f"{concept_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"reel concept not found: {concept_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def list_reel_concepts(self, limit: int = 25) -> list[dict[str, Any]]:
        paths = sorted((self.root / "reel_concepts").glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        items: list[dict[str, Any]] = []
        for path in paths[: max(0, limit)]:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            items.append(
                {
                    "id": payload.get("id", path.stem),
                    "status": payload.get("status", "draft"),
                    "run_id": payload.get("run_id", ""),
                    "campaign_id": payload.get("campaign_id", ""),
                    "trend_id": payload.get("trend_id", ""),
                    "created_at": payload.get("created_at", ""),
                    "variant_count": len(payload.get("variants", [])),
                    "user_prompt": payload.get("user_prompt", ""),
                }
            )
        return items

    def append_learning(self, payload: dict[str, Any]) -> Path:
        path = self.root / "learning" / "records.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        return path

    def cleanup_test_data(self, prefixes: tuple[str, ...] = ("mock-", "smoke-"), *, dry_run: bool = False) -> dict[str, Any]:
        """Remove generated smoke/mock records without touching real campaign data."""

        summary: dict[str, Any] = {
            "dry_run": dry_run,
            "prefixes": list(prefixes),
            "states_deleted": 0,
            "events_removed": 0,
            "performance_removed": 0,
            "leads_removed": 0,
            "outbox_removed": 0,
            "content_ids": [],
        }

        for path in sorted((self.root / "states").glob("*.json")):
            content_id = self._state_content_id(path)
            if self._is_test_id(content_id, prefixes):
                summary["states_deleted"] += 1
                summary["content_ids"].append(content_id)
                if not dry_run:
                    path.unlink()

        for path in sorted((self.root / "events").glob("*.jsonl")):
            removed = self._filter_jsonl(path, prefixes=prefixes, dry_run=dry_run)
            summary["events_removed"] += removed

        for path in sorted((self.root / "performance").glob("*.jsonl")):
            removed = self._filter_jsonl(path, prefixes=prefixes, dry_run=dry_run)
            summary["performance_removed"] += removed

        for path in sorted((self.root / "leads").glob("*.jsonl")):
            removed = self._filter_jsonl(path, prefixes=prefixes, dry_run=dry_run)
            summary["leads_removed"] += removed

        for path in sorted((self.root / "outbox").glob("*.jsonl")):
            removed = self._filter_jsonl(path, prefixes=prefixes, dry_run=dry_run)
            summary["outbox_removed"] += removed

        for path in sorted((self.root / "reel_concepts").glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if self._contains_test_id(payload, prefixes):
                if not dry_run:
                    path.unlink()

        for path in sorted((self.root / "learning").glob("*.jsonl")):
            self._filter_jsonl(path, prefixes=prefixes, dry_run=dry_run)

        summary["content_ids"] = sorted(set(summary["content_ids"]))
        return summary

    @staticmethod
    def _is_test_id(value: Any, prefixes: tuple[str, ...]) -> bool:
        return isinstance(value, str) and any(value.startswith(prefix) for prefix in prefixes)

    def _state_content_id(self, path: Path) -> str:
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            brief = state.get("brief", {})
            content_id = brief.get("id")
            return content_id if isinstance(content_id, str) else path.stem
        except (OSError, json.JSONDecodeError):
            return path.stem

    def _filter_jsonl(self, path: Path, *, prefixes: tuple[str, ...], dry_run: bool) -> int:
        if not path.exists():
            return 0
        kept: list[str] = []
        removed = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                kept.append(line)
                continue
            if self._contains_test_id(payload, prefixes):
                removed += 1
            else:
                kept.append(line)
        if removed and not dry_run:
            path.write_text(("\n".join(kept) + "\n") if kept else "", encoding="utf-8")
        return removed

    def _contains_test_id(self, value: Any, prefixes: tuple[str, ...]) -> bool:
        if self._is_test_id(value, prefixes):
            return True
        if isinstance(value, dict):
            return any(self._contains_test_id(item, prefixes) for item in value.values())
        if isinstance(value, list):
            return any(self._contains_test_id(item, prefixes) for item in value)
        return False


def make_json_safe(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, list):
        return [make_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {key: make_json_safe(item) for key, item in value.items()}
    return value
