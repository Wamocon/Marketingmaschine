from __future__ import annotations

import hashlib
import importlib
import json
import math
import os
import re
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .schemas import ContentBrief, ContentStatus


SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
STATE_REVISION_KEY = "_storage_revision"
_NO_EXPECTED_REVISION = object()
_PROCESS_LOCKS: dict[str, threading.RLock] = {}
_PROCESS_LOCKS_GUARD = threading.Lock()
_HELD_FILE_LOCKS = threading.local()


class StateRevisionConflict(RuntimeError):
    """Raised when a compare-and-swap write observes a newer state."""


def validate_identifier(value: str, *, field: str = "id") -> str:
    """Validate identifiers before they are used as local file names.

    Runtime storage is intentionally simple, but user-provided IDs must never
    be able to escape their assigned directory or overwrite arbitrary files.
    """

    candidate = str(value or "").strip()
    if not SAFE_IDENTIFIER.fullmatch(candidate):
        raise ValueError(f"{field} must use 1-128 letters, numbers, dots, dashes, or underscores")
    return candidate


def _fsync_directory(path: Path) -> None:
    """Persist a directory entry after an atomic replace on POSIX filesystems."""

    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, indent=2, ensure_ascii=False))
        handle.flush()
        os.fsync(handle.fileno())
    temporary.chmod(0o600)
    temporary.replace(path)
    path.chmod(0o600)
    _fsync_directory(path.parent)


def _write_text_atomic(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.chmod(0o600)
    temporary.replace(path)
    path.chmod(0o600)
    _fsync_directory(path.parent)


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    """Append one JSON record with a shared-file lock and private permissions."""

    lock_path = path.with_name(f".{path.name}.lock")
    with _portable_key_lock(lock_path):
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        path.chmod(0o600)
        _fsync_directory(path.parent)


def _read_jsonl_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    lock_path = path.with_name(f".{path.name}.lock")
    with _portable_key_lock(lock_path):
        return path.read_text(encoding="utf-8").splitlines()


def _process_lock(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _PROCESS_LOCKS_GUARD:
        return _PROCESS_LOCKS.setdefault(key, threading.RLock())


def _lock_file(handle: Any) -> None:
    """Acquire one byte of an advisory lock on Windows or the file on POSIX."""

    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        while True:
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                return
            except OSError:
                # LK_LOCK retries internally, but another process may hold the
                # byte longer than its retry window. Continue waiting rather
                # than allowing an unlocked write.
                continue
    else:
        fcntl = importlib.import_module("fcntl")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _unlock_file(handle: Any) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl = importlib.import_module("fcntl")
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def _portable_key_lock(path: Path) -> Iterator[None]:
    """Re-entrant thread lock backed by an inter-process advisory file lock."""

    path.parent.mkdir(parents=True, exist_ok=True)
    key = str(path.resolve())
    process_lock = _process_lock(path)
    process_lock.acquire()
    held = getattr(_HELD_FILE_LOCKS, "items", None)
    if held is None:
        held = {}
        _HELD_FILE_LOCKS.items = held

    entry = held.get(key)
    if entry is not None:
        entry["depth"] += 1
        try:
            yield
        finally:
            entry["depth"] -= 1
            process_lock.release()
        return

    handle = path.open("a+b")
    try:
        _lock_file(handle)
        held[key] = {"depth": 1, "handle": handle}
        try:
            yield
        finally:
            held.pop(key, None)
            _unlock_file(handle)
    finally:
        handle.close()
        process_lock.release()


def data_dir() -> Path:
    root = Path(os.environ.get("MARKETING_MACHINE_DATA_DIR", "runtime-data"))
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o700)
    for child in ("states", "events", "performance", "leads", "outbox", "trend_runs", "reel_concepts", "learning"):
        child_path = root / child
        child_path.mkdir(parents=True, exist_ok=True)
        child_path.chmod(0o700)
    return root


def brief_from_dict(data: dict[str, Any]) -> ContentBrief:
    payload = dict(data)
    payload["status"] = ContentStatus(payload.get("status", ContentStatus.DRAFTING.value))
    return ContentBrief(**payload)


class JsonStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or data_dir()
        for child in ("states", "events", "performance", "leads", "outbox", "trend_runs", "reel_concepts", "learning"):
            child_path = self.root / child
            child_path.mkdir(parents=True, exist_ok=True)
            child_path.chmod(0o700)

    @contextmanager
    def state_lock(self, content_id: str) -> Iterator[None]:
        """Serialize one content workflow across threads and worker processes."""

        content_id = validate_identifier(content_id, field="content_id")
        with _portable_key_lock(self.root / ".locks" / f"state-{content_id}.lock"):
            yield

    @contextmanager
    def reel_concept_lock(self, concept_id: str) -> Iterator[None]:
        """Serialize one Reel approval across threads and worker processes."""

        concept_id = validate_identifier(concept_id, field="concept_id")
        with _portable_key_lock(self.root / ".locks" / f"reel-concept-{concept_id}.lock"):
            yield

    @contextmanager
    def outbox_lock(self, route_id: str) -> Iterator[None]:
        """Serialize one external-write intent across workers and retries."""

        route_id = validate_identifier(route_id, field="route_id")
        with _portable_key_lock(self.root / ".locks" / f"outbox-{route_id}.lock"):
            yield

    @contextmanager
    def performance_lock(self, content_id: str, review_window: str) -> Iterator[None]:
        """Serialize the one allowed analytics record for a content/window pair."""

        content_id = validate_identifier(content_id, field="content_id")
        review_window = validate_identifier(review_window, field="review_window")
        with _portable_key_lock(
            self.root / ".locks" / f"performance-{content_id}-{review_window}.lock"
        ):
            yield

    @contextmanager
    def lead_lock(self, lead_id: str) -> Iterator[None]:
        """Serialize one lead using a bounded set of inter-process lock files."""

        lead_id = validate_identifier(lead_id, field="lead_id")
        bucket = hashlib.sha256(lead_id.encode("utf-8")).hexdigest()[:2]
        with _portable_key_lock(self.root / ".locks" / f"lead-{bucket}.lock"):
            yield

    @contextmanager
    def trend_request_lock(self, fingerprint_or_run_id: str) -> Iterator[None]:
        """Serialize duplicate trend research across threads and worker processes.

        A fixed bucket count keeps attacker-controlled request IDs from creating
        an unbounded number of persistent lock files. The full digest remains
        the cache key, so unrelated requests never share results.
        """

        digest = hashlib.sha256(str(fingerprint_or_run_id).encode("utf-8")).hexdigest()
        with _portable_key_lock(self.root / ".locks" / f"trend-request-{digest[:2]}.lock"):
            yield

    def load_trend_request_cache(
        self,
        fingerprint_or_run_id: str,
        *,
        max_age_seconds: int = 300,
    ) -> dict[str, Any] | None:
        """Load a short-lived completed result used only for concurrent retries."""

        digest = hashlib.sha256(str(fingerprint_or_run_id).encode("utf-8")).hexdigest()
        path = self.root / ".trend_request_cache" / f"{digest}.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            created_at = float(payload.get("created_at", 0))
        except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError, ValueError):
            return None
        age = time.time() - created_at
        if age < 0 or age > max(1, int(max_age_seconds)):
            path.unlink(missing_ok=True)
            return None
        return payload if isinstance(payload.get("result"), dict) else None

    def save_trend_request_cache(
        self,
        fingerprint_or_run_id: str,
        *,
        request_fingerprint: str,
        result: dict[str, Any],
    ) -> Path:
        """Atomically cache one completed research response and bound cache growth."""

        digest = hashlib.sha256(str(fingerprint_or_run_id).encode("utf-8")).hexdigest()
        directory = self.root / ".trend_request_cache"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{digest}.json"
        _write_json_atomic(
            path,
            {
                "created_at": time.time(),
                "request_fingerprint": str(request_fingerprint),
                "result": result,
            },
        )
        cached_with_times: list[tuple[float, Path]] = []
        for cached_path in directory.glob("*.json"):
            try:
                cached_with_times.append((cached_path.stat().st_mtime, cached_path))
            except OSError:
                continue
        cached = [
            item
            for _, item in sorted(cached_with_times, key=lambda value: value[0], reverse=True)
        ]
        for stale_path in cached[128:]:
            try:
                stale_path.unlink()
            except OSError:
                continue
        return path

    @staticmethod
    def state_revision(state: dict[str, Any]) -> int:
        raw = state.get(STATE_REVISION_KEY, 0)
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            raise ValueError("stored state revision must be a non-negative integer")
        return raw

    def _state_paths_newest_first(self) -> list[Path]:
        """Return a stable snapshot of readable state paths for one projection."""

        states_dir = self.root / "states"
        candidates: list[tuple[float, str, Path]] = []
        for path in states_dir.glob("*.json"):
            try:
                candidates.append((path.stat().st_mtime, path.name, path))
            except OSError:
                continue
        return [
            path
            for _, _, path in sorted(
                candidates,
                key=lambda item: (item[0], item[1]),
                reverse=True,
            )
        ]

    @staticmethod
    def _safe_quality_summary(brief: dict[str, Any]) -> dict[str, Any]:
        """Expose only the release fields needed by business and release views."""

        raw = brief.get("quality_evaluation", {})
        if not isinstance(raw, dict):
            raw = {}
        raw_score = raw.get("overall_score")
        score: float | None = None
        if (
            not isinstance(raw_score, bool)
            and isinstance(raw_score, (int, float))
            and math.isfinite(float(raw_score))
            and 0 <= float(raw_score) <= 100
        ):
            score = round(float(raw_score), 2)

        evaluated_at = str(raw.get("evaluated_at", "")).strip()
        try:
            parsed_evaluated_at = datetime.fromisoformat(evaluated_at.replace("Z", "+00:00"))
            if parsed_evaluated_at.tzinfo is None or parsed_evaluated_at.utcoffset() is None:
                evaluated_at = ""
        except (TypeError, ValueError, OverflowError):
            evaluated_at = ""

        hard_blockers = raw.get("hard_blockers", [])
        if not isinstance(hard_blockers, list):
            hard_blockers = []
        blocker_codes: list[str] = []
        for item in hard_blockers:
            if not isinstance(item, dict):
                continue
            code = str(item.get("code", "")).strip().casefold()
            if re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,99}", code) and code not in blocker_codes:
                blocker_codes.append(code)

        decision = str(raw.get("decision", "")).strip().casefold()
        structurally_ready = (
            raw.get("release_ready") is True
            and decision == "pass"
            and score is not None
            and bool(evaluated_at)
            and not hard_blockers
        )
        return {
            "release_ready": structurally_ready,
            "decision": decision if decision in {"pass", "fail"} else "unknown",
            "overall_score": score,
            "evaluated_at": evaluated_at,
            "blocker_codes": blocker_codes,
            "blocker_count": len(hard_blockers),
        }

    @staticmethod
    def _provider_verified_media_asset(asset: Any) -> bool:
        if not isinstance(asset, dict) or asset.get("status") != "approved":
            return False
        sha256 = str(asset.get("sha256", "")).strip().casefold()
        provider_sha256 = str(asset.get("provider_sha256", "")).strip().casefold()
        postiz_path = str(asset.get("postiz_path", "")).strip()
        provider_path = str(asset.get("provider_path", "")).strip()
        return (
            asset.get("provider_verified") is True
            and asset.get("provider_verification_method") == "postiz_public_url_sha256"
            and bool(asset.get("postiz_media_id"))
            and bool(re.fullmatch(r"[a-f0-9]{64}", sha256))
            and provider_sha256 == sha256
            and bool(postiz_path)
            and provider_path == postiz_path
        )

    @classmethod
    def project_media_asset_verification(cls, asset: dict[str, Any]) -> dict[str, Any]:
        """Return one media asset with a server-owned exact-binding verdict."""

        return {
            **asset,
            "provider_verification_valid": cls._provider_verified_media_asset(asset),
        }

    @classmethod
    def project_media_verification(cls, state: dict[str, Any]) -> dict[str, Any]:
        """Project server-derived media truth without trusting legacy flags.

        Older records may contain an approved Postiz id and path without proof
        that the provider served the exact human-approved bytes.  Browser
        consumers receive an explicit per-asset verdict plus aggregate
        readiness computed from the immutable checksum/path binding.  Any
        similarly named value already present in storage is overwritten.
        """

        projected = dict(state)
        raw_assets = state.get("approved_media_assets", [])
        if not isinstance(raw_assets, list):
            raw_assets = []
        projected_assets = [
            cls.project_media_asset_verification(asset)
            for asset in raw_assets
            if isinstance(asset, dict)
        ]
        approved_media = [
            asset for asset in projected_assets if asset.get("status") == "approved"
        ]
        provider_verified_media = [
            asset
            for asset in approved_media
            if asset.get("provider_verification_valid") is True
        ]
        brief = state.get("brief", {})
        if not isinstance(brief, dict):
            brief = {}
        channel = str(brief.get("channel", "")).strip().casefold()
        instagram_reel = channel == "instagram" and "reel" in str(
            brief.get("format", "")
        ).casefold()
        postiz_media_ready = (
            any(asset.get("media_type") == "video" for asset in provider_verified_media)
            if instagram_reel
            else bool(provider_verified_media)
            if channel == "instagram"
            else True
        )
        projected["approved_media_assets"] = projected_assets
        projected["approved_media_count"] = len(approved_media)
        projected["provider_verified_media_count"] = len(provider_verified_media)
        projected["postiz_media_ready"] = postiz_media_ready
        return projected

    def _project_state_summary(
        self,
        path: Path,
        *,
        include_demo: bool,
        campaign_id: str,
    ) -> dict[str, Any] | None:
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeError):
            return None
        if not isinstance(state, dict):
            return None
        brief = state.get("brief", {})
        if not isinstance(brief, dict):
            return None
        content_id = str(brief.get("id", path.stem)).strip()
        if not SAFE_IDENTIFIER.fullmatch(content_id):
            return None
        lifecycle = state.get("lifecycle", {})
        if not isinstance(lifecycle, dict):
            lifecycle = {}
        media_projection = self.project_media_verification(state)
        approved_media_count = int(media_projection["approved_media_count"])
        provider_verified_media_count = int(
            media_projection["provider_verified_media_count"]
        )
        projected_assets = media_projection["approved_media_assets"]
        approved_media = [
            asset
            for asset in projected_assets
            if isinstance(asset, dict) and asset.get("status") == "approved"
        ]
        demo = self._is_demo_state(state)
        resolved_campaign_id = str(brief.get("campaign_id", ""))
        if not include_demo and demo:
            return None
        if campaign_id and resolved_campaign_id != campaign_id:
            return None
        raw_revision_source = state.get("revision_source", {})
        safe_revision_source: dict[str, Any] = {}
        try:
            projected_state_revision: int | None = self.state_revision(state)
        except ValueError:
            projected_state_revision = None
        if isinstance(raw_revision_source, dict):
            source_content_id = str(raw_revision_source.get("content_id", "")).strip()
            source_revision = raw_revision_source.get("revision")
            if (
                SAFE_IDENTIFIER.fullmatch(source_content_id)
                and not isinstance(source_revision, bool)
                and isinstance(source_revision, int)
                and source_revision >= 1
            ):
                # Only the immutable predecessor pointer belongs in list
                # summaries. Authentication fingerprints and other audit
                # diagnostics remain available in the detailed state.
                safe_revision_source = {
                    "content_id": source_content_id,
                    "revision": source_revision,
                }
        generation = brief.get("generation", {})
        if not isinstance(generation, dict):
            generation = {}
        return {
            "content_id": content_id,
            "campaign_id": resolved_campaign_id,
            "campaign": brief.get("campaign", ""),
            "persona": brief.get("persona", ""),
            "channel": brief.get("channel", ""),
            "format": brief.get("format", ""),
            "status": brief.get("status", ""),
            "next_step": state.get("next_step", ""),
            "updated_at": brief.get("updated_at", ""),
            "requires_human_review": bool(state.get("requires_human_review", False)),
            "has_scheduler_payload": bool(state.get("scheduler_payload")),
            "is_demo": demo,
            "source_status": brief.get(
                "source_status", brief.get("trend_verification_status", "")
            ),
            "generation": generation,
            "quality_evaluation": self._safe_quality_summary(brief),
            "state_revision": projected_state_revision,
            "revision_source": safe_revision_source,
            "lifecycle_status": lifecycle.get("provider_status", ""),
            "provider_post_id": lifecycle.get("provider_post_id", ""),
            "scheduled_for": lifecycle.get("scheduled_for", ""),
            "published_at": lifecycle.get("published_at", ""),
            "release_url": lifecycle.get("release_url", ""),
            "approved_media_count": approved_media_count,
            "approved_media_types": sorted(
                {
                    str(asset.get("media_type", ""))
                    for asset in approved_media
                    if asset.get("media_type")
                }
            ),
            "provider_verified_media_count": provider_verified_media_count,
            "postiz_media_ready": media_projection["postiz_media_ready"],
        }

    def iter_state_pages(
        self,
        page_size: int = 100,
        *,
        include_demo: bool = False,
        campaign_id: str = "",
    ) -> Iterator[list[dict[str, Any]]]:
        """Yield every safe state summary in bounded in-memory pages."""

        if isinstance(page_size, bool) or not isinstance(page_size, int) or not 1 <= page_size <= 1000:
            raise ValueError("page_size must be an integer from 1 to 1000")
        page: list[dict[str, Any]] = []
        for path in self._state_paths_newest_first():
            item = self._project_state_summary(
                path,
                include_demo=include_demo,
                campaign_id=campaign_id,
            )
            if item is None:
                continue
            page.append(item)
            if len(page) == page_size:
                yield page
                page = []
        if page:
            yield page

    def list_all_states(
        self,
        *,
        include_demo: bool = False,
        campaign_id: str = "",
        page_size: int = 100,
    ) -> list[dict[str, Any]]:
        """Return the complete safe projection while reading it in bounded pages."""

        return [
            item
            for page in self.iter_state_pages(
                page_size=page_size,
                include_demo=include_demo,
                campaign_id=campaign_id,
            )
            for item in page
        ]

    def list_states(
        self,
        limit: int = 25,
        *,
        include_demo: bool = False,
        campaign_id: str = "",
    ) -> list[dict[str, Any]]:
        """Return a bounded browser-facing slice of recent state summaries."""

        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 0:
            raise ValueError("limit must be a non-negative integer")
        if limit == 0:
            return []
        items: list[dict[str, Any]] = []
        for page in self.iter_state_pages(
            page_size=min(limit, 1000),
            include_demo=include_demo,
            campaign_id=campaign_id,
        ):
            remaining = limit - len(items)
            items.extend(page[:remaining])
            if len(items) >= limit:
                break
        return items

    def save_state(
        self,
        state: dict[str, Any],
        *,
        expected_revision: int | None | object = _NO_EXPECTED_REVISION,
    ) -> Path:
        """Atomically write a state, optionally using compare-and-swap.

        ``expected_revision=None`` means the state must not exist. Existing
        pre-revision files are revision 0, so they can be upgraded in place.
        Omitting the argument preserves the legacy unconditional-save API.
        """

        content_id = validate_identifier(state["brief"]["id"], field="content_id")
        path = self.root / "states" / f"{content_id}.json"
        with self.state_lock(content_id):
            current: dict[str, Any] | None = None
            if path.exists():
                current = json.loads(path.read_text(encoding="utf-8"))
            current_revision = self.state_revision(current) if current is not None else None
            if expected_revision is not _NO_EXPECTED_REVISION:
                if expected_revision is not None and (
                    isinstance(expected_revision, bool)
                    or not isinstance(expected_revision, int)
                    or expected_revision < 0
                ):
                    raise ValueError("expected_revision must be a non-negative integer or None")
                if current_revision != expected_revision:
                    raise StateRevisionConflict(
                        f"content state revision changed: expected {expected_revision}, found {current_revision}"
                    )
            next_revision = (current_revision if current_revision is not None else 0) + 1
            state[STATE_REVISION_KEY] = next_revision
            _write_json_atomic(path, state)
        return path

    def load_state(self, content_id: str) -> dict[str, Any]:
        content_id = validate_identifier(content_id, field="content_id")
        path = self.root / "states" / f"{content_id}.json"
        with self.state_lock(content_id):
            if not path.exists():
                raise FileNotFoundError(f"content state not found: {content_id}")
            return json.loads(path.read_text(encoding="utf-8"))

    def append_event(self, name: str, payload: dict[str, Any]) -> Path:
        path = self.root / "events" / f"{name}.jsonl"
        _append_jsonl(path, payload)
        return path

    def append_event_once(
        self,
        name: str,
        event_id: str,
        payload: dict[str, Any],
    ) -> tuple[Path, bool]:
        """Append an audit event exactly once across retries and processes."""

        event_id = validate_identifier(event_id, field="event_id")
        safe_name = validate_identifier(name, field="event_name")
        path = self.root / "events" / f"{safe_name}.jsonl"
        lock_path = self.root / ".locks" / f"event-{safe_name}.lock"
        with _portable_key_lock(lock_path):
            if path.exists():
                for line in path.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        existing = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(existing, dict) and existing.get("_event_id") == event_id:
                        return path, True
            durable = {"_event_id": event_id, **payload}
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(durable, ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            path.chmod(0o600)
            _fsync_directory(path.parent)
        return path, False

    def append_performance(self, payload: dict[str, Any]) -> Path:
        path = self.root / "performance" / "records.jsonl"
        record = payload.get("record", {})
        content_id = str(record.get("content_id", "")) if isinstance(record, dict) else ""
        review_window = str(record.get("review_window", "")) if isinstance(record, dict) else ""
        lock_path = self.root / ".locks" / "performance-records.lock"
        if content_id and review_window:
            lock_path = self.root / ".locks" / f"performance-{content_id}-{review_window}.lock"
        with _portable_key_lock(lock_path):
            _append_jsonl(path, payload)
        return path

    def load_performance(self, content_id: str, review_window: str) -> dict[str, Any]:
        """Return the durable full analytics payload for one review window."""

        content_id = validate_identifier(content_id, field="content_id")
        review_window = validate_identifier(review_window, field="review_window")
        path = self.root / "performance" / "records.jsonl"
        if not path.exists():
            raise FileNotFoundError(
                f"performance record not found: {content_id}/{review_window}"
            )
        with self.performance_lock(content_id, review_window):
            for line in reversed(_read_jsonl_lines(path)):
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                record = payload.get("record", {})
                if not isinstance(record, dict):
                    continue
                if (
                    str(record.get("content_id", "")) == content_id
                    and str(record.get("review_window", "")) == review_window
                ):
                    return payload
        raise FileNotFoundError(
            f"performance record not found: {content_id}/{review_window}"
        )

    def save_performance_once(self, payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Create one immutable analytics decision per content/window natural key."""

        record = payload.get("record", {})
        if not isinstance(record, dict):
            raise ValueError("performance payload must contain a record object")
        content_id = validate_identifier(str(record.get("content_id", "")), field="content_id")
        review_window = validate_identifier(
            str(record.get("review_window", "")), field="review_window"
        )
        fingerprint = str(payload.get("request_fingerprint", "")).strip()
        if not fingerprint:
            raise ValueError("performance payload requires request_fingerprint")

        with self.performance_lock(content_id, review_window):
            try:
                existing = self.load_performance(content_id, review_window)
            except FileNotFoundError:
                existing = None
            if existing is not None:
                if str(existing.get("request_fingerprint", "")) == fingerprint:
                    return existing, True
                raise StateRevisionConflict(
                    f"performance record already exists: {content_id}/{review_window}; corrections require an audited revision"
                )
            payload.setdefault("revision", 1)
            self.append_performance(payload)
            return payload, False

    def save_performance_correction(
        self,
        payload: dict[str, Any],
        *,
        supersedes_fingerprint: str,
        correction_reason: str,
        operator: str,
        corrected_at: str,
    ) -> tuple[dict[str, Any], bool]:
        """Append a CAS-protected correction while retaining the original record."""

        record = payload.get("record", {})
        if not isinstance(record, dict):
            raise ValueError("performance payload must contain a record object")
        content_id = validate_identifier(str(record.get("content_id", "")), field="content_id")
        review_window = validate_identifier(
            str(record.get("review_window", "")), field="review_window"
        )
        new_fingerprint = str(payload.get("request_fingerprint", "")).strip()
        if not all((new_fingerprint, supersedes_fingerprint, correction_reason, operator, corrected_at)):
            raise ValueError("correction fingerprint, reason, operator, and corrected_at are required")

        with self.performance_lock(content_id, review_window):
            current = self.load_performance(content_id, review_window)
            current_fingerprint = str(current.get("request_fingerprint", ""))
            correction = current.get("correction", {})
            if (
                new_fingerprint == current_fingerprint
                and isinstance(correction, dict)
                and correction.get("supersedes_fingerprint") == supersedes_fingerprint
                and correction.get("reason") == correction_reason
                and correction.get("operator") == operator
                and correction.get("corrected_at") == corrected_at
            ):
                return current, True
            if current_fingerprint != supersedes_fingerprint:
                raise StateRevisionConflict(
                    f"performance correction is stale: expected {supersedes_fingerprint}, found {current_fingerprint}"
                )
            if new_fingerprint == current_fingerprint:
                raise StateRevisionConflict("performance correction must change the stored record")
            try:
                correction_time = datetime.fromisoformat(
                    corrected_at.replace("Z", "+00:00")
                ).astimezone(timezone.utc)
                current_record = current.get("record", {})
                if not isinstance(current_record, dict):
                    current_record = {}
                previous_correction = current.get("correction", {})
                if not isinstance(previous_correction, dict):
                    previous_correction = {}
                lower_bounds = [
                    datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(
                        timezone.utc
                    )
                    for value in (
                        current_record.get("created_at"),
                        current_record.get("retrieved_at"),
                        previous_correction.get("corrected_at"),
                    )
                    if str(value or "").strip()
                ]
                if not lower_bounds:
                    raise ValueError("current analytics revision has no trusted timestamp")
                lower_bound = max(lower_bounds)
            except (AttributeError, TypeError, ValueError) as exc:
                raise ValueError("analytics correction chronology is invalid") from exc
            if correction_time < lower_bound:
                raise ValueError(
                    "corrected_at cannot be before the current analytics revision"
                )
            payload["revision"] = int(current.get("revision", 1)) + 1
            payload["correction"] = {
                "supersedes_fingerprint": supersedes_fingerprint,
                "reason": correction_reason,
                "operator": operator,
                "corrected_at": corrected_at,
            }
            self.append_performance(payload)
            return payload, False

    def list_performance(
        self,
        limit: int = 25,
        *,
        include_demo: bool = False,
    ) -> list[dict[str, Any]]:
        path = self.root / "performance" / "records.jsonl"
        if not path.exists():
            return []
        items: list[dict[str, Any]] = []
        seen_keys: set[tuple[str, str]] = set()
        for line in reversed(_read_jsonl_lines(path)):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            record = payload.get("record", {})
            if not isinstance(record, dict):
                continue
            content_id = str(record.get("content_id", ""))
            if not include_demo and self._source_record_is_demo(content_id):
                continue
            natural_key = (
                content_id,
                str(record.get("review_window", "")),
            )
            if natural_key in seen_keys:
                continue
            seen_keys.add(natural_key)
            items.append(
                {
                    "content_id": record.get("content_id", ""),
                    "campaign": self._source_campaign(content_id),
                    "review_window": record.get("review_window", ""),
                    "action": payload.get("action", ""),
                    "reason": payload.get("reason", ""),
                    "impressions": record.get("impressions", 0),
                    "saves": record.get("saves", 0),
                    "shares": record.get("shares", 0),
                    "comments_from_target_buyers": record.get(
                        "comments_from_target_buyers", 0
                    ),
                    "profile_visits": record.get("profile_visits", 0),
                    "clicks": record.get("clicks", 0),
                    "leads": record.get("leads", 0),
                    "qualified_leads": record.get("qualified_leads", 0),
                    "booked_calls": record.get("booked_calls", 0),
                    "pipeline_value_eur": record.get("pipeline_value_eur", 0.0),
                    "landing_page_visits": record.get("landing_page_visits", 0),
                    "landing_page_conversions": record.get(
                        "landing_page_conversions", 0
                    ),
                    "source_system": record.get("source_system", ""),
                    "source_ref": record.get("source_ref", ""),
                    "period_start": record.get("period_start", ""),
                    "period_end": record.get("period_end", ""),
                    "retrieved_at": record.get("retrieved_at", ""),
                    "operator": record.get("operator", ""),
                    "attribution_rule": record.get("attribution_rule", ""),
                    "snapshot_sha256": record.get("snapshot_sha256", ""),
                    "evidence": record.get("evidence", []),
                    "revision": payload.get("revision", 1),
                    "correction": payload.get("correction", {}),
                    "request_fingerprint": payload.get("request_fingerprint", ""),
                    "created_at": record.get("created_at", ""),
                }
            )
            if len(items) >= max(0, limit):
                break
        return items

    def _lead_current_path(self, lead_id: str) -> Path:
        lead_id = validate_identifier(lead_id, field="lead_id")
        directory = self.root / "leads" / "current"
        directory.mkdir(parents=True, exist_ok=True)
        directory.chmod(0o700)
        return directory / f"{lead_id}.json"

    def _append_lead_history_once(
        self,
        event_id: str,
        payload: dict[str, Any],
    ) -> tuple[Path, bool]:
        """Append a PII-free lead audit event exactly once."""

        event_id = validate_identifier(event_id, field="event_id")
        path = self.root / "leads" / "history.jsonl"
        lock_path = self.root / ".locks" / "lead-history.lock"
        with _portable_key_lock(lock_path):
            if path.exists():
                for line in path.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        existing = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(existing, dict) and existing.get("_event_id") == event_id:
                        return path, True
            durable = {"_event_id": event_id, **payload}
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(durable, ensure_ascii=False) + "\n")
            path.chmod(0o600)
        return path, False

    @staticmethod
    def _lead_audit_payload(
        payload: dict[str, Any],
        *,
        action: str,
        operator: str,
        reason: str,
        occurred_at: str,
    ) -> dict[str, Any]:
        lead = payload.get("lead", {})
        privacy = payload.get("privacy", {})
        return {
            "action": action,
            "lead_id": str(lead.get("id", "")) if isinstance(lead, dict) else "",
            "source_content_id": str(lead.get("source_content_id", "")) if isinstance(lead, dict) else "",
            "campaign": str(lead.get("campaign", "")) if isinstance(lead, dict) else "",
            "revision": int(payload.get("revision", 1)),
            "request_fingerprint": str(payload.get("request_fingerprint", "")),
            "routing_allowed": bool(payload.get("routing_allowed", False)),
            "privacy_status": str(privacy.get("status", "")) if isinstance(privacy, dict) else "",
            "operator": operator,
            "reason": reason,
            "occurred_at": occurred_at,
        }

    def _scrub_legacy_lead_pii(self, lead_id: str, privacy: dict[str, Any]) -> None:
        """Remove contact data from the pre-migration JSONL operational store."""

        path = self.root / "leads" / "records.jsonl"
        if not path.exists():
            return
        lock_path = path.with_name(f".{path.name}.lock")
        with _portable_key_lock(lock_path):
            changed = False
            output: list[str] = []
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    output.append(line)
                    continue
                lead = payload.get("lead", payload) if isinstance(payload, dict) else {}
                if not isinstance(lead, dict) or str(lead.get("id", "")) != lead_id:
                    output.append(line)
                    continue
                for field_name in ("company", "email", "contact_name", "phone", "message"):
                    lead[field_name] = ""
                lead["utm"] = {}
                lead["consent_given"] = False
                lead["consent_proof_ref"] = ""
                lead["consent_source"] = ""
                lead["consent_purposes"] = []
                lead["routing_allowed"] = False
                if payload is lead:
                    payload = lead
                else:
                    payload["lead"] = lead
                    payload["routing_allowed"] = False
                    payload["crm_payload"] = {}
                    payload["mautic_payload"] = {}
                    payload["privacy"] = privacy
                output.append(json.dumps(payload, ensure_ascii=False))
                changed = True
            if changed:
                _write_text_atomic(path, "\n".join(output) + "\n")

    def _place_lead_outbox_privacy_hold(
        self,
        lead_id: str,
        *,
        action: str,
        operator: str,
        occurred_at: str,
    ) -> list[str]:
        """Cancel unsent writes, scrub copies, and report providers that may hold PII."""

        outbox_dir = self.root / "outbox"
        external_targets: set[str] = set()
        for path in outbox_dir.glob("*.json"):
            try:
                candidate = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if candidate.get("kind") != "lead" or str(candidate.get("source_id", "")) != lead_id:
                continue
            route_id = validate_identifier(str(candidate.get("id", "")), field="route_id")
            with self.outbox_lock(route_id):
                try:
                    current = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    continue
                previous_status = str(current.get("status", ""))
                current["payload"] = {}
                current["response"] = {}
                current["privacy_hold"] = {
                    "action": action,
                    "operator": operator,
                    "occurred_at": occurred_at,
                    "previous_status": previous_status,
                }
                if previous_status in {
                    "sending",
                    "delivery_unknown",
                    "sent",
                    "confirmed",
                    "reconciled",
                }:
                    target = str(current.get("target", "")).strip()
                    if target:
                        external_targets.add(target)
                    current["external_privacy_action_required"] = True
                    current["external_privacy_action_targets"] = [target] if target else []
                    current["provider_erasure_status"] = (
                        "required_unverified"
                        if action in {"anonymize", "erase", "expire_retention"}
                        else "not_requested"
                    )
                if previous_status in {
                    "prepared",
                    "failed_safe_to_retry",
                    "rate_limited",
                    "blocked",
                }:
                    current["status"] = "blocked"
                    current["reason"] = f"lead privacy lifecycle action blocks delivery: {action}"
                elif previous_status == "sending":
                    current["status"] = "delivery_unknown"
                    current["reason"] = "lead was placed on privacy hold while delivery required reconciliation"
                current["updated_at"] = occurred_at
                _write_json_atomic(path, current)

        legacy = outbox_dir / "records.jsonl"
        if not legacy.exists():
            return sorted(external_targets)
        lock_path = legacy.with_name(f".{legacy.name}.lock")
        with _portable_key_lock(lock_path):
            changed = False
            output: list[str] = []
            for line in legacy.read_text(encoding="utf-8").splitlines():
                try:
                    current = json.loads(line)
                except json.JSONDecodeError:
                    output.append(line)
                    continue
                if not isinstance(current, dict) or current.get("kind") != "lead" or str(current.get("source_id", "")) != lead_id:
                    output.append(line)
                    continue
                previous_status = str(current.get("status", ""))
                current["payload"] = {}
                current["response"] = {}
                current["privacy_hold"] = {
                    "action": action,
                    "operator": operator,
                    "occurred_at": occurred_at,
                    "previous_status": previous_status,
                }
                if previous_status in {
                    "sending",
                    "delivery_unknown",
                    "sent",
                    "confirmed",
                    "reconciled",
                }:
                    target = str(current.get("target", "")).strip()
                    if target:
                        external_targets.add(target)
                    current["external_privacy_action_required"] = True
                    current["external_privacy_action_targets"] = [target] if target else []
                    current["provider_erasure_status"] = (
                        "required_unverified"
                        if action in {"anonymize", "erase", "expire_retention"}
                        else "not_requested"
                    )
                if previous_status in {"prepared", "failed_safe_to_retry", "rate_limited", "blocked"}:
                    current["status"] = "blocked"
                    current["reason"] = f"lead privacy lifecycle action blocks delivery: {action}"
                elif previous_status == "sending":
                    current["status"] = "delivery_unknown"
                    current["reason"] = "lead was placed on privacy hold while delivery required reconciliation"
                current["updated_at"] = occurred_at
                output.append(json.dumps(current, ensure_ascii=False))
                changed = True
            if changed:
                _write_text_atomic(legacy, "\n".join(output) + "\n")
        return sorted(external_targets)

    def save_lead_once(self, payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Atomically create one lead; exact retries return the durable record."""

        lead = payload.get("lead", {})
        if not isinstance(lead, dict):
            raise ValueError("lead payload must contain a lead object")
        lead_id = validate_identifier(str(lead.get("id", "")), field="lead_id")
        fingerprint = str(payload.get("request_fingerprint", "")).strip()
        if not fingerprint:
            raise ValueError("lead payload requires request_fingerprint")
        event_id = f"lead-intake-{fingerprint}"
        path = self._lead_current_path(lead_id)
        with self.lead_lock(lead_id):
            existing: dict[str, Any] | None = None
            try:
                existing = self.load_lead(lead_id)
            except FileNotFoundError:
                pass
            if existing is not None:
                if str(existing.get("request_fingerprint", "")) != fingerprint:
                    raise StateRevisionConflict(
                        f"lead already exists with different intake data: {lead_id}"
                    )
                audit = self._lead_audit_payload(
                    existing,
                    action="intake",
                    operator="system",
                    reason="affirmative_consent_intake",
                    occurred_at=str(existing.get("lead", {}).get("created_at", "")),
                )
                self._append_lead_history_once(event_id, audit)
                return existing, True
            payload["revision"] = 1
            _write_json_atomic(path, payload)
            audit = self._lead_audit_payload(
                payload,
                action="intake",
                operator="system",
                reason="affirmative_consent_intake",
                occurred_at=str(lead.get("created_at", "")),
            )
            self._append_lead_history_once(event_id, audit)
            return payload, False

    def save_lead_transition(
        self,
        payload: dict[str, Any],
        *,
        expected_revision: int,
        transition_fingerprint: str,
        action: str,
        operator: str,
        reason: str,
        occurred_at: str,
    ) -> tuple[dict[str, Any], bool]:
        """CAS-save a lifecycle transition while retaining a PII-free audit history."""

        lead = payload.get("lead", {})
        if not isinstance(lead, dict):
            raise ValueError("lead payload must contain a lead object")
        lead_id = validate_identifier(str(lead.get("id", "")), field="lead_id")
        if not transition_fingerprint:
            raise ValueError("lead transition requires a request fingerprint")
        event_id = f"lead-lifecycle-{transition_fingerprint}"
        path = self._lead_current_path(lead_id)
        with self.lead_lock(lead_id):
            current = self.load_lead(lead_id)
            seen_transitions = {
                str(item)
                for item in current.get("transition_fingerprints", [])
                if str(item)
            }
            last_transition = str(current.get("last_transition_fingerprint", ""))
            if last_transition:
                seen_transitions.add(last_transition)
            if transition_fingerprint in seen_transitions:
                current_privacy = current.get("privacy", {})
                if not isinstance(current_privacy, dict):
                    current_privacy = {}
                # A retry of an older transition must never roll an outbox hold
                # back from a later, stricter privacy action or replace the
                # original execution timestamp with the retry clock time.
                effective_action = str(current_privacy.get("last_action") or action)
                effective_operator = str(current_privacy.get("last_operator") or operator)
                effective_occurred_at = str(
                    current_privacy.get("updated_at") or occurred_at
                )
                external_targets = self._place_lead_outbox_privacy_hold(
                    lead_id,
                    action=effective_action,
                    operator=effective_operator,
                    occurred_at=effective_occurred_at,
                )
                privacy = current.get("privacy", {})
                if isinstance(privacy, dict):
                    combined_targets = sorted(
                        {
                            *(
                                str(item)
                                for item in privacy.get(
                                    "external_privacy_action_targets", []
                                )
                                if str(item)
                            ),
                            *external_targets,
                        }
                    )
                    privacy["external_privacy_action_required"] = bool(combined_targets)
                    privacy["external_privacy_action_targets"] = combined_targets
                    if combined_targets and effective_action in {"anonymize", "erase", "expire_retention"}:
                        privacy["provider_erasure_status"] = "required_unverified"
                    else:
                        privacy.setdefault("provider_erasure_status", "not_requested")
                    current["privacy"] = privacy
                    _write_json_atomic(path, current)
                if isinstance(privacy, dict) and privacy.get("status") == "anonymized":
                    self._scrub_legacy_lead_pii(lead_id, privacy)
                audit = self._lead_audit_payload(
                    current,
                    action=action,
                    operator=operator,
                    reason=reason,
                    occurred_at=occurred_at,
                )
                self._append_lead_history_once(event_id, audit)
                return current, True
            current_revision = int(current.get("revision", 1))
            if current_revision != expected_revision:
                raise StateRevisionConflict(
                    f"lead revision changed: expected {expected_revision}, found {current_revision}"
                )
            payload["revision"] = current_revision + 1
            payload["last_transition_fingerprint"] = transition_fingerprint
            payload["transition_fingerprints"] = [
                *sorted(seen_transitions),
                transition_fingerprint,
            ][-64:]
            external_targets = self._place_lead_outbox_privacy_hold(
                lead_id,
                action=action,
                operator=operator,
                occurred_at=occurred_at,
            )
            privacy = payload.get("privacy", {})
            if isinstance(privacy, dict):
                combined_targets = sorted(
                    {
                        *(
                            str(item)
                            for item in privacy.get(
                                "external_privacy_action_targets", []
                            )
                            if str(item)
                        ),
                        *external_targets,
                    }
                )
                privacy["external_privacy_action_required"] = bool(combined_targets)
                privacy["external_privacy_action_targets"] = combined_targets
                privacy["external_privacy_action"] = action
                if combined_targets and action in {"anonymize", "erase", "expire_retention"}:
                    privacy["provider_erasure_status"] = "required_unverified"
                else:
                    privacy.setdefault("provider_erasure_status", "not_requested")
                payload["privacy"] = privacy
            _write_json_atomic(path, payload)
            if isinstance(privacy, dict) and privacy.get("status") == "anonymized":
                self._scrub_legacy_lead_pii(lead_id, privacy)
            audit = self._lead_audit_payload(
                payload,
                action=action,
                operator=operator,
                reason=reason,
                occurred_at=occurred_at,
            )
            self._append_lead_history_once(event_id, audit)
            return payload, False

    def append_lead(self, payload: dict[str, Any]) -> Path:
        """Append a legacy lead record; new intake uses ``save_lead_once``."""

        path = self.root / "leads" / "records.jsonl"
        _append_jsonl(path, payload)
        return path

    def list_leads(
        self,
        limit: int = 25,
        *,
        include_demo: bool = False,
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        current_dir = self.root / "leads" / "current"
        current_paths = sorted(
            current_dir.glob("*.json") if current_dir.exists() else [],
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
        payloads: list[dict[str, Any]] = []
        for current_path in current_paths:
            try:
                payload = json.loads(current_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                record_ref = hashlib.sha256(
                    current_path.name.encode("utf-8")
                ).hexdigest()[:16]
                payloads.append(
                    {
                        "lead": {"id": f"invalid-record-{record_ref}"},
                        "privacy": {"status": "invalid_record"},
                        "record_validation_error": "unreadable_or_invalid_json",
                    }
                )
                continue
            if isinstance(payload, dict):
                payloads.append(payload)
            else:
                record_ref = hashlib.sha256(
                    current_path.name.encode("utf-8")
                ).hexdigest()[:16]
                payloads.append(
                    {
                        "lead": {"id": f"invalid-record-{record_ref}"},
                        "privacy": {"status": "invalid_record"},
                        "record_validation_error": "record_is_not_an_object",
                    }
                )
        path = self.root / "leads" / "records.jsonl"
        for line in reversed(_read_jsonl_lines(path)) if path.exists() else []:
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                record_ref = hashlib.sha256(line.encode("utf-8")).hexdigest()[:16]
                payloads.append(
                    {
                        "lead": {"id": f"invalid-record-{record_ref}"},
                        "privacy": {"status": "invalid_record"},
                        "record_validation_error": "unreadable_or_invalid_json",
                    }
                )
                continue
            if isinstance(payload, dict):
                payloads.append(payload)
        for payload in payloads:
            lead = payload.get("lead", payload)
            if not isinstance(lead, dict):
                continue
            lead_id = str(lead.get("id", ""))
            source_content_id = str(lead.get("source_content_id", ""))
            if not include_demo and (
                self._is_demo_identifier(lead_id)
                or self._source_record_is_demo(source_content_id)
            ):
                continue
            if lead_id in seen:
                continue
            seen.add(lead_id)
            privacy = payload.get("privacy", {})
            if not isinstance(privacy, dict):
                privacy = {}
            raw_external_targets = privacy.get("external_privacy_action_targets", [])
            if not isinstance(raw_external_targets, list):
                raw_external_targets = []
            external_targets = sorted(
                {
                    str(item)
                    for item in raw_external_targets
                    if str(item)
                }
            )
            external_required = bool(
                privacy.get("external_privacy_action_required") or external_targets
            )
            provider_erasure_status = str(
                privacy.get("provider_erasure_status", "")
            ).strip() or ("required_unverified" if external_required else "not_requested")
            items.append(
                {
                    "id": lead_id,
                    "source_content_id": source_content_id,
                    "campaign_id": lead.get("campaign_id", ""),
                    "campaign": lead.get("campaign", ""),
                    "company": lead.get("company", ""),
                    "qualification_score": lead.get("qualification_score", 0),
                    "next_action": lead.get("next_action", ""),
                    "source_verified": bool(lead.get("source_verified", False)),
                    "routing_allowed": bool(lead.get("routing_allowed", False)),
                    "privacy_status": privacy.get("status", "legacy_unverified"),
                    "retention_policy": privacy.get(
                        "retention_policy", lead.get("retention_policy", "")
                    ),
                    "retention_expires_at": privacy.get("retention_expires_at", ""),
                    "external_privacy_action_required": external_required,
                    "external_privacy_action_targets": external_targets,
                    "provider_erasure_status": provider_erasure_status,
                    "record_validation_error": payload.get(
                        "record_validation_error", ""
                    ),
                    "created_at": lead.get("created_at", ""),
                }
            )
            if len(items) >= max(0, limit):
                break
        return items

    def load_lead(self, lead_id: str) -> dict[str, Any]:
        lead_id = validate_identifier(lead_id, field="lead_id")
        current_path = self._lead_current_path(lead_id)
        with self.lead_lock(lead_id):
            if current_path.exists():
                return json.loads(current_path.read_text(encoding="utf-8"))
        path = self.root / "leads" / "records.jsonl"
        if not path.exists():
            raise FileNotFoundError(f"lead not found: {lead_id}")
        for line in reversed(_read_jsonl_lines(path)):
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
        """Persist the latest state of a stable outbox intent.

        New records use one atomic JSON file per route.  The reader still
        understands the earlier JSONL format so existing operator history is
        preserved during an in-place upgrade.
        """

        route_id = validate_identifier(str(payload.get("id", "")), field="route_id")
        path = self.root / "outbox" / f"{route_id}.json"
        with self.outbox_lock(route_id):
            _write_json_atomic(path, payload)
        return path

    save_outbox = append_outbox

    def load_outbox(self, route_id: str) -> dict[str, Any]:
        route_id = validate_identifier(route_id, field="route_id")
        path = self.root / "outbox" / f"{route_id}.json"
        with self.outbox_lock(route_id):
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))

            legacy = self.root / "outbox" / "records.jsonl"
            if legacy.exists():
                for line in reversed(_read_jsonl_lines(legacy)):
                    if not line.strip():
                        continue
                    try:
                        payload = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(payload, dict) and str(payload.get("id", "")) == route_id:
                        return payload
        raise FileNotFoundError(f"outbox route not found: {route_id}")

    def list_outbox(
        self,
        limit: int = 25,
        *,
        include_demo: bool = False,
    ) -> list[dict[str, Any]]:
        outbox_dir = self.root / "outbox"
        payloads: list[tuple[float, dict[str, Any]]] = []
        seen: set[str] = set()

        paths = sorted(
            outbox_dir.glob("route-*.json"),
            key=lambda candidate: candidate.stat().st_mtime,
            reverse=True,
        )
        for path in paths:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            route_id = str(payload.get("id", path.stem))
            seen.add(route_id)
            payloads.append((path.stat().st_mtime, payload))

        legacy = outbox_dir / "records.jsonl"
        if legacy.exists():
            legacy_mtime = legacy.stat().st_mtime
            for index, line in enumerate(reversed(_read_jsonl_lines(legacy))):
                if not line.strip():
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                route_id = str(payload.get("id", ""))
                if route_id and route_id in seen:
                    continue
                if route_id:
                    seen.add(route_id)
                payloads.append((legacy_mtime - index / 1_000_000, payload))

        items: list[dict[str, Any]] = []
        for _, payload in sorted(payloads, key=lambda item: item[0], reverse=True):
            route_id = str(payload.get("id", ""))
            source_id = str(payload.get("source_id", ""))
            if not include_demo and (
                self._is_demo_identifier(route_id)
                or self._source_record_is_demo(source_id)
            ):
                continue
            external_required = bool(payload.get("external_privacy_action_required", False))
            raw_external_targets = payload.get("external_privacy_action_targets", [])
            if not isinstance(raw_external_targets, list):
                raw_external_targets = []
            external_targets = sorted(
                {
                    str(item)
                    for item in raw_external_targets
                    if str(item)
                }
            )
            target = str(payload.get("target", ""))
            if external_required and target:
                external_targets = sorted({*external_targets, target})
            provider_erasure_status = str(
                payload.get("provider_erasure_status", "")
            ).strip() or ("required_unverified" if external_required else "not_requested")
            items.append(
                {
                    "id": route_id,
                    "kind": payload.get("kind", ""),
                    "target": payload.get("target", ""),
                    "status": payload.get("status", ""),
                    "dry_run": bool(payload.get("dry_run", True)),
                    "source_id": source_id,
                    "campaign": self._source_campaign(source_id)
                    if payload.get("kind") == "scheduler_draft"
                    else "",
                    "reason": payload.get("reason", ""),
                    "external_reference": payload.get("external_reference", ""),
                    "provider_status": payload.get("provider_status", ""),
                    "external_privacy_action_required": external_required,
                    "external_privacy_action_targets": external_targets,
                    "provider_erasure_status": provider_erasure_status,
                    "created_at": payload.get("created_at", ""),
                    "updated_at": payload.get("updated_at", payload.get("created_at", "")),
                }
            )
            if len(items) >= max(0, limit):
                break
        return items

    def save_trend_run(self, payload: dict[str, Any]) -> Path:
        run_id = validate_identifier(payload["id"], field="run_id")
        path = self.root / "trend_runs" / f"{run_id}.json"
        _write_json_atomic(path, payload)
        return path

    def load_trend_run(self, run_id: str) -> dict[str, Any]:
        run_id = validate_identifier(run_id, field="run_id")
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
            campaign_ids = [
                str(item.get("campaign", {}).get("id", ""))
                for item in campaigns
                if isinstance(item, dict) and item.get("campaign", {}).get("id")
            ]
            items.append(
                {
                    "id": payload.get("id", path.stem),
                    "request_id": payload.get("request_id", ""),
                    "status": payload.get("status", ""),
                    "run_started_at": payload.get("run_started_at", ""),
                    "lookback_days": payload.get("lookback_days", 0),
                    "platforms": payload.get("platforms", []),
                    "campaign_count": len(campaigns) if isinstance(campaigns, list) else 0,
                    "trend_count": trend_count,
                    "campaign_ids": campaign_ids,
                    "source_adapters": payload.get("source_adapters", []),
                    "successful_source_adapters": payload.get("successful_source_adapters", []),
                    "source_errors": payload.get("source_errors", []),
                }
            )
        return items

    def save_reel_concept(
        self,
        payload: dict[str, Any],
        *,
        expected_revision: int | None | object = _NO_EXPECTED_REVISION,
    ) -> Path:
        concept_id = validate_identifier(payload["id"], field="concept_id")
        path = self.root / "reel_concepts" / f"{concept_id}.json"
        with self.reel_concept_lock(concept_id):
            current: dict[str, Any] | None = None
            if path.exists():
                current = json.loads(path.read_text(encoding="utf-8"))
            current_revision = self.state_revision(current) if current is not None else None
            if expected_revision is not _NO_EXPECTED_REVISION:
                if expected_revision is not None and (
                    isinstance(expected_revision, bool)
                    or not isinstance(expected_revision, int)
                    or expected_revision < 0
                ):
                    raise ValueError("expected_revision must be a non-negative integer or None")
                if current_revision != expected_revision:
                    raise StateRevisionConflict(
                        f"Reel concept revision changed: expected {expected_revision}, found {current_revision}"
                    )
            next_revision = (current_revision if current_revision is not None else 0) + 1
            payload[STATE_REVISION_KEY] = next_revision
            _write_json_atomic(path, payload)
        return path

    def load_reel_concept(self, concept_id: str) -> dict[str, Any]:
        concept_id = validate_identifier(concept_id, field="concept_id")
        path = self.root / "reel_concepts" / f"{concept_id}.json"
        with self.reel_concept_lock(concept_id):
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
        _append_jsonl(path, payload)
        return path

    @staticmethod
    def _is_demo_state(state: dict[str, Any]) -> bool:
        brief = state.get("brief", {}) if isinstance(state, dict) else {}
        if not isinstance(brief, dict):
            return True
        if bool(brief.get("is_demo", False)):
            return True
        content_id = str(brief.get("id", "")).lower()
        if content_id.startswith(("demo-", "mock-", "smoke-", "ui-test-")):
            return True
        verification = str(
            brief.get("trend_verification_status", brief.get("source_status", ""))
        ).lower()
        if verification in {"requires_live_sources", "unverified", "placeholder", "evergreen_only"}:
            return True
        trend_summary = str(brief.get("trend_summary", "")).lower()
        trend_sources = brief.get("trend_sources", [])
        if "campaign-only signal" in trend_summary:
            return True
        if trend_summary and isinstance(trend_sources, list) and trend_sources:
            external = [
                item
                for item in trend_sources
                if isinstance(item, str) and item.startswith(("http://", "https://"))
            ]
            if not external:
                return True
        return False

    @staticmethod
    def _is_demo_identifier(value: Any) -> bool:
        """Recognise identifiers that are explicitly reserved for non-live data."""

        if not isinstance(value, str):
            return False
        tokens = {
            token
            for token in re.split(r"[._-]+", value.strip().casefold())
            if token
        }
        return bool(tokens.intersection({"demo", "mock", "smoke", "placeholder"})) or (
            "ui" in tokens and "test" in tokens
        )

    def _source_record_is_demo(self, source_id: str) -> bool:
        """Classify known source records without treating missing sources as demos."""

        if not source_id:
            return False
        if self._is_demo_identifier(source_id):
            return True
        state = self._source_state(source_id)
        return self._is_demo_state(state) if state is not None else False

    def _source_state(self, source_id: str) -> dict[str, Any] | None:
        """Load an exact source state without inferring identity from its filename."""

        if not source_id:
            return None
        try:
            safe_source_id = validate_identifier(source_id, field="source_id")
            state_path = self.root / "states" / f"{safe_source_id}.json"
            if not state_path.exists():
                return None
            # State writes use an atomic replace, so business-list reads can
            # safely inspect the old or new complete file without creating a
            # lock file in what is contractually a read-only operation.
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(state, dict):
            return None
        brief = state.get("brief")
        if not isinstance(brief, dict) or str(brief.get("id", "")) != safe_source_id:
            return None
        return state

    def _source_campaign(self, source_id: str) -> str:
        """Project a campaign label only from the exact validated source state."""

        state = self._source_state(source_id)
        if state is None:
            return ""
        campaign = state["brief"].get("campaign")
        return campaign.strip() if isinstance(campaign, str) else ""

    @staticmethod
    def is_demo_state(state: dict[str, Any]) -> bool:
        """Public read-only classifier used by source-attribution gates."""

        return JsonStore._is_demo_state(state)

    def cleanup_test_data(self, prefixes: tuple[str, ...] = ("mock-", "smoke-"), *, dry_run: bool = True) -> dict[str, Any]:
        """Report generated test records; live in-place deletion is retired."""

        if not dry_run:
            raise RuntimeError(
                "in-place runtime cleanup is retired because concurrent writers can corrupt audit data; use an offline, backed-up migration"
            )

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

        for path in sorted((self.root / "outbox").glob("route-*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if self._contains_test_id(payload, prefixes):
                summary["outbox_removed"] += 1
                if not dry_run:
                    path.unlink()

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
