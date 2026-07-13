from __future__ import annotations

import hashlib
import ipaddress
import json
import math
import os
import re
from contextvars import ContextVar
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from .analytics import evaluate_performance, validate_performance_record
from .auth import (
    ACTOR_HEADER,
    EDGE_ATTESTATION_HEADER,
    MUTATION_TOKEN_HEADER,
    ActorAuthenticationError,
    MutationAuthorizationError,
    actor_authentication_required,
    audit_request_fingerprint,
    authenticate_edge_actor,
    authorize_mutation,
    edge_actor_authorization_status,
    mutation_authorization_status,
)
from .campaign_catalog import (
    business_now,
    business_timezone,
    campaign_dashboard,
    default_brief_payload,
    get_campaign,
    load_campaign_catalog,
    resolve_campaign_id,
)
from .evidence import EvidenceVault
from .governance import GovernancePolicy
from .integrations import (
    check_comfyui_generation_readiness,
    check_firecrawl_configuration,
    check_growth_service,
    check_ollama_model,
    check_openai_compatible_models,
    check_url,
    disabled_cloud_model_status,
)
from .leads import (
    RETENTION_POLICY_MAX_DURATIONS,
    apply_lead_lifecycle,
    build_lead_intake,
    verify_lead_source_attribution,
)
from .metrics import PROMETHEUS_CONTENT_TYPE, render_prometheus_metrics
from .phases import build_phase_status
from .routing import get_json
from .routing import route_lead as route_lead_to_target
from .routing import route_scheduler_draft as route_scheduler_draft_to_target
from .routing import verify_postiz_media_url
from .schemas import (
    ApprovalRecord,
    ContentBrief,
    ContentStatus,
    PerformanceRecord,
    ReviewDecision,
)
from .storage import (
    JsonStore,
    StateRevisionConflict,
    brief_from_dict,
    validate_identifier,
)
from .trend_research import (
    concept_to_content_brief,
    generate_reel_concepts,
    load_campaigns,
    normalize_requested_campaign_ids,
    normalize_requested_platforms,
    refresh_trend_run_eligibility,
    run_trend_research,
    trend_run_has_verified_sources,
    trend_request_fingerprint,
    trend_request_run_id,
    validate_trend_brief_against_run,
)
from .trend_sources import source_domain
from .ui import render_marketing_console
from .workflow import MarketingWorkflow, WorkflowState, people_media_evidence_errors


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_runtime_env() -> None:
    import os

    candidates = [
        os.environ.get("MARKETING_MACHINE_ENV_FILE", ""),
        str(repo_root() / "deploy" / "marketing-agent.generated.env"),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def load_policy() -> GovernancePolicy:
    return GovernancePolicy.from_json_file(
        repo_root() / "config" / "governance-policy.json"
    )


def load_evidence_vault() -> EvidenceVault:
    return EvidenceVault.from_json_file(repo_root() / "config" / "evidence-vault.json")


def env_configured(
    name: str, *, required: bool = False, label: str | None = None
) -> dict[str, Any]:
    import os

    return {
        "name": label or name.lower(),
        "ok": False,
        "required": required,
        "configured": bool(os.environ.get(name, "").strip()),
        "secret_env": name,
        "reachable": None,
        "used_successfully": False,
        "capability": "configuration_only",
    }


def strict_bool(value: Any, *, field: str) -> bool:
    if isinstance(value, bool):
        return value
    if value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off", ""}:
            return False
    raise ValueError(f"{field} must be a boolean")


def request_fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def canonical_string_union(
    canonical: list[str],
    supplied: Any,
    *,
    field: str,
) -> list[str]:
    """Keep mandatory campaign values while accepting additive caller values."""

    if supplied is None:
        additions: list[Any] = []
    elif isinstance(supplied, list):
        additions = supplied
    else:
        raise ValueError(f"{field} must be an array of non-empty strings")
    result: list[str] = []
    for raw in [*canonical, *additions]:
        if not isinstance(raw, str) or not raw.strip():
            raise ValueError(f"{field} must contain only non-empty strings")
        value = raw.strip()
        if value not in result:
            result.append(value)
    return result


def reel_approval_fingerprint(concept: dict[str, Any], variant_id: str) -> str:
    """Fingerprint the immutable concept bundle and the explicit selection."""

    variants = concept.get("variants", [])
    if not isinstance(variants, list) or not any(
        isinstance(item, dict) and str(item.get("id", "")) == variant_id
        for item in variants
    ):
        raise ValueError(f"variant not found in Reel concept: {variant_id}")
    mutable_fields = {
        "status",
        "approved_variant_id",
        "approval_fingerprint",
        "content_id",
        "approval_authenticated_actor",
        "authenticated_request_fingerprint",
        "_storage_revision",
    }
    immutable_concept = {
        key: value for key, value in concept.items() if key not in mutable_fields
    }
    return request_fingerprint(
        {"concept": immutable_concept, "selected_variant_id": variant_id}
    )


def require_expected_revision(
    payload: dict[str, Any],
    stored: dict[str, Any],
    *,
    resource: str,
) -> int:
    """Validate an optional client CAS token and return the loaded revision."""

    current_revision = JsonStore.state_revision(stored)
    if "expected_revision" not in payload:
        return current_revision
    try:
        expected_revision = non_negative_int(
            payload["expected_revision"], field="expected_revision"
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if expected_revision != current_revision:
        raise HTTPException(
            status_code=409,
            detail=f"{resource} changed since it was loaded; refresh before retrying",
        )
    return current_revision


def non_negative_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a non-negative integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field} must be a non-negative integer") from exc
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"{field} must be a non-negative integer")
    if parsed < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return parsed


def non_negative_float(value: Any, *, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a non-negative number")
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field} must be a non-negative number") from exc
    if not math.isfinite(parsed) or parsed < 0:
        raise ValueError(f"{field} must be a non-negative number")
    return parsed


ANALYTICS_DELAYS = {
    "72h": timedelta(hours=72),
    "7d": timedelta(days=7),
    "14d": timedelta(days=14),
    "30d": timedelta(days=30),
}

LEAD_REASON_CODES_BY_ACTION = {
    "suppress": {
        "operator_suppression",
        "data_subject_request",
        "legal_obligation",
        "duplicate_record",
    },
    "withdraw_consent": {"consent_withdrawn", "data_subject_request"},
    "anonymize": {"data_subject_request", "legal_obligation", "legacy_migration"},
    "erase": {"data_subject_request", "legal_obligation", "legacy_migration"},
    "expire_retention": {"retention_expired"},
}
DEFAULT_LEAD_REASON_CODE = {
    "suppress": "operator_suppression",
    "withdraw_consent": "consent_withdrawn",
    "anonymize": "data_subject_request",
    "erase": "data_subject_request",
    "expire_retention": "retention_expired",
}
PROVIDER_LIFECYCLE_STATUSES = {"draft_created", "scheduled", "published", "failed"}

ALLOWED_HOSTS_ENV = "MARKETING_MACHINE_ALLOWED_HOSTS"
TECHNICAL_DOCS_ENV = "MARKETING_MACHINE_ENABLE_TECHNICAL_DOCS"
EXPLICIT_CONTENT_MODE_ENV = "MARKETING_MACHINE_REQUIRE_EXPLICIT_CONTENT_MODE"
LEGACY_VERIFIED_TRENDS_ENV = "MARKETING_MACHINE_REQUIRE_VERIFIED_TRENDS"
INTERNAL_TRUSTED_HOSTS = frozenset({"127.0.0.1", "localhost", "wmc-marketing-agent"})
TECHNICAL_SURFACE_PATHS = frozenset(
    {"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}
)
NO_STORE_CACHE_CONTROL = "no-store, max-age=0"
MAX_MUTATION_BODY_BYTES = 1024 * 1024


class MutationBodyTooLarge(ValueError):
    pass


class TrendPolicyConfigurationError(RuntimeError):
    pass


def explicit_content_mode_required() -> bool:
    """Return whether manual intake must name evergreen/current-trend mode.

    ``MARKETING_MACHINE_REQUIRE_VERIFIED_TRENDS`` is retained only as a
    deprecated deployment alias. Its historical name was misleading because
    evergreen content is valid and current-trend evidence is *always*
    revalidated, regardless of this explicitness switch.
    """

    configured = os.environ.get(EXPLICIT_CONTENT_MODE_ENV)
    legacy = os.environ.get(LEGACY_VERIFIED_TRENDS_ENV)
    try:
        preferred_value = (
            strict_bool(configured, field=EXPLICIT_CONTENT_MODE_ENV)
            if configured is not None
            else None
        )
        legacy_value = (
            strict_bool(legacy, field=LEGACY_VERIFIED_TRENDS_ENV)
            if legacy is not None
            else None
        )
    except ValueError as exc:
        raise TrendPolicyConfigurationError(str(exc)) from exc
    if (
        preferred_value is not None
        and legacy_value is not None
        and preferred_value != legacy_value
    ):
        raise TrendPolicyConfigurationError(
            f"{EXPLICIT_CONTENT_MODE_ENV} conflicts with deprecated alias "
            f"{LEGACY_VERIFIED_TRENDS_ENV}"
        )
    if preferred_value is not None:
        return preferred_value
    if legacy_value is not None:
        return legacy_value
    return True


async def bounded_mutation_body(request: Request) -> bytes:
    """Read one protected request without allowing an unbounded ASGI body."""

    content_lengths = [
        value
        for name, value in request.scope.get("headers", [])
        if name.lower() == b"content-length"
    ]
    if len(content_lengths) > 1:
        raise MutationBodyTooLarge("ambiguous content length")
    if content_lengths:
        try:
            declared = int(content_lengths[0].decode("ascii"))
        except (UnicodeError, ValueError) as exc:
            raise MutationBodyTooLarge("invalid content length") from exc
        if declared < 0 or declared > MAX_MUTATION_BODY_BYTES:
            raise MutationBodyTooLarge("request body exceeds the mutation limit")

    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_MUTATION_BODY_BYTES:
            raise MutationBodyTooLarge("request body exceeds the mutation limit")
        chunks.append(chunk)
    body = b"".join(chunks)
    # Starlette's Request.stream() serves this cached body to downstream
    # handlers, so the bounded read remains transparent to FastAPI parsing.
    setattr(request, "_body", body)
    return body


def runtime_instance_mode() -> str:
    return (
        os.environ.get("MARKETING_MACHINE_INSTANCE_MODE", "production")
        .strip()
        .casefold()
    )


def technical_docs_enabled() -> bool:
    """Expose framework documentation only in an explicitly non-production mode."""

    if runtime_instance_mode() not in {"development", "test"}:
        return False
    configured = os.environ.get(TECHNICAL_DOCS_ENV, "true").strip().casefold()
    return configured in {"1", "true", "yes", "on"}


def _is_technical_surface(path: str) -> bool:
    return any(
        path == base or path.startswith(f"{base}/") for base in TECHNICAL_SURFACE_PATHS
    )


def _normalized_host(value: str, *, allow_port: bool) -> str:
    """Return a canonical exact host or reject ambiguous Host syntax."""

    raw = value.strip()
    if not raw or any(character.isspace() for character in raw):
        raise ValueError("host is empty or contains whitespace")
    if any(character in raw for character in ("/", "\\", "@", "#", "?", ",", "*")):
        raise ValueError("host contains a forbidden character")
    if raw.startswith("["):
        closing = raw.find("]")
        if closing < 0:
            raise ValueError("bracketed host is malformed")
        host = raw[1:closing]
        suffix = raw[closing + 1 :]
        if suffix:
            if not allow_port or not suffix.startswith(":"):
                raise ValueError("host must not include a port")
            _validated_port(suffix[1:])
        try:
            return ipaddress.ip_address(host).compressed.casefold()
        except ValueError as exc:
            raise ValueError("bracketed host is not an IP address") from exc

    host = raw
    if ":" in raw:
        if not allow_port or raw.count(":") != 1:
            raise ValueError("host must not include a port")
        host, port = raw.rsplit(":", 1)
        _validated_port(port)
    host = host.rstrip(".").casefold()
    if not host or len(host) > 253 or not host.isascii():
        raise ValueError("host is invalid")
    try:
        return ipaddress.ip_address(host).compressed.casefold()
    except ValueError:
        pass
    labels = host.split(".")
    if any(
        not label
        or len(label) > 63
        or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label)
        for label in labels
    ):
        raise ValueError("host is invalid")
    return host


def _validated_port(value: str) -> int:
    if not value.isascii() or not value.isdigit():
        raise ValueError("host port is invalid")
    port = int(value)
    if not 1 <= port <= 65535:
        raise ValueError("host port is invalid")
    return port


def configured_trusted_hosts() -> frozenset[str]:
    """Build an exact allowlist; wildcard and URL-like entries fail closed."""

    hosts = set(INTERNAL_TRUSTED_HOSTS)
    configured = os.environ.get(ALLOWED_HOSTS_ENV, "").strip()
    if not configured:
        return frozenset(hosts)
    for value in configured.split(","):
        if not value.strip():
            raise ValueError(f"{ALLOWED_HOSTS_ENV} contains an empty entry")
        hosts.add(_normalized_host(value, allow_port=False))
    return frozenset(hosts)


def trusted_host_policy_status() -> dict[str, Any]:
    configured = os.environ.get(ALLOWED_HOSTS_ENV, "").strip()
    try:
        trusted_hosts = configured_trusted_hosts()
    except ValueError:
        return {
            "safe": False,
            "status": "blocked_invalid_allowed_hosts",
            "external_hosts_configured": bool(configured),
            "host_count": 0,
        }
    return {
        "safe": True,
        "status": "protected",
        "external_hosts_configured": bool(configured),
        "host_count": len(trusted_hosts),
    }


def business_timezone_policy_status() -> dict[str, Any]:
    try:
        zone = business_timezone()
    except ValueError:
        return {"safe": False, "status": "blocked_invalid_business_timezone"}
    return {"safe": True, "status": "protected", "timezone": zone.key}


def trend_intake_policy_status() -> dict[str, Any]:
    configured_key = (
        EXPLICIT_CONTENT_MODE_ENV
        if EXPLICIT_CONTENT_MODE_ENV in os.environ
        else (
            LEGACY_VERIFIED_TRENDS_ENV
            if LEGACY_VERIFIED_TRENDS_ENV in os.environ
            else "secure_default"
        )
    )
    try:
        required = explicit_content_mode_required()
    except TrendPolicyConfigurationError:
        return {
            "safe": False,
            "status": "blocked_invalid_trend_intake_policy",
            "explicit_content_mode_required": None,
            "current_trend_requires_stored_verified_evidence": True,
            "configured_key": configured_key,
        }
    return {
        "safe": True,
        "status": "protected",
        "explicit_content_mode_required": required,
        "current_trend_requires_stored_verified_evidence": True,
        "unverified_current_trends_allowed": False,
        "configured_key": configured_key,
        "deprecated_alias_in_use": configured_key == LEGACY_VERIFIED_TRENDS_ENV,
    }


def required_text(
    payload: dict[str, Any], field: str, *, max_length: int = 2000
) -> str:
    value = payload.get(field, "")
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value.strip()[:max_length]


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


def live_postiz_handoff_started(store: JsonStore, content_id: str) -> bool:
    frozen_statuses = {
        "sending",
        "sent",
        "delivery_unknown",
        "confirmed",
        "reconciled",
        "reconciled_failed",
    }
    routes = store.list_outbox(limit=100_000)
    return any(
        route.get("kind") == "scheduler_draft"
        and route.get("target") == "postiz"
        and route.get("source_id") == content_id
        and route.get("status") in frozen_statuses
        for route in routes
    )


def media_audit_event_id(content_id: str, asset_id: str, fingerprint: str) -> str:
    """Build a collision-resistant, human-locatable event id within 128 chars."""

    return f"{content_id[:40]}-{asset_id[:40]}-{fingerprint[:32]}"


def normalized_performance_evidence(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("evidence")
    if not isinstance(raw, list) or not raw:
        raise ValueError(
            "evidence must be a non-empty array of metric source artifacts"
        )
    evidence: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"evidence[{index}] must be an object")
        fields = item.get("metric_fields")
        if not isinstance(fields, list) or not fields:
            raise ValueError(
                f"evidence[{index}].metric_fields must be a non-empty array"
            )
        evidence.append(
            {
                "system": required_text(item, "system", max_length=100),
                "ref": required_text(item, "ref", max_length=1000),
                "retrieved_at": normalized_timestamp(
                    item.get("retrieved_at"),
                    field=f"evidence[{index}].retrieved_at",
                ),
                "sha256": required_text(item, "sha256", max_length=64).casefold(),
                "metric_fields": list(
                    dict.fromkeys(
                        str(field).strip() for field in fields if str(field).strip()
                    )
                ),
            }
        )
    return evidence


def authenticated_manual_analytics_payload(
    payload: dict[str, Any],
    *,
    correction: bool = False,
) -> dict[str, Any]:
    """Bind public analytics claims to the signed-in operator.

    Provider-API provenance may only be created by a future server-side
    adapter, never by a public request asserting that it called the provider.
    """

    actor = require_human_actor(
        "analytics correction" if correction else "analytics review"
    )
    if not actor:
        return payload
    source_system = str(payload.get("source_system", "manual")).strip().casefold()
    if source_system != "manual":
        raise HTTPException(
            status_code=403,
            detail="public analytics submissions must use manual provenance; provider sources are server-only",
        )
    raw_evidence = payload.get("evidence", [])
    if isinstance(raw_evidence, list):
        for item in raw_evidence:
            if not isinstance(item, dict):
                continue
            system = str(item.get("system", "")).strip().casefold().replace("-", "_")
            if system.endswith("_api") or system in {"api", "provider_api"}:
                raise HTTPException(
                    status_code=403,
                    detail="provider API evidence can only be produced by a server-side adapter",
                )
    for field in ("operator", "correction_operator") if correction else ("operator",):
        supplied = str(payload.get(field, "")).strip()
        if supplied and supplied.casefold() != actor.casefold():
            raise HTTPException(
                status_code=422,
                detail=f"{field} must match the authenticated operator account",
            )
    normalized = dict(payload)
    normalized["source_system"] = "manual"
    normalized["operator"] = actor
    if correction:
        normalized["correction_operator"] = actor
    return normalized


def full_trend_runs(store: JsonStore, *, limit: int = 100) -> list[dict[str, Any]]:
    """Load campaign-level trend evidence for truthful dashboard summaries."""

    runs: list[dict[str, Any]] = []
    for summary in store.list_trend_runs(limit=limit):
        try:
            stored = store.load_trend_run(str(summary.get("id", "")))
            runs.append(refresh_trend_run_eligibility(stored))
        except (FileNotFoundError, ValueError):
            continue
    return runs


def recorded_n8n_execution(
    runs: list[dict[str, Any]], *, workflows_verified: bool
) -> dict[str, Any] | None:
    """Return durable evidence written by the versioned n8n trend workflow.

    That workflow deliberately passes ``$execution.id`` as ``request_id``.
    Browser/API requests use UUID-like IDs, so an ASCII numeric request ID on a
    completed, source-backed run is useful persisted evidence. The operator
    verification flag is also required because request IDs are not an
    authentication boundary and a direct API caller could choose a numeric ID.
    """

    if not workflows_verified:
        return None
    for run in runs:
        request_id = str(run.get("request_id", "")).strip()
        if not (request_id.isascii() and request_id.isdigit()):
            continue
        if not run.get("successful_source_adapters"):
            continue
        return run
    return None


load_runtime_env()

app = FastAPI(title="WAMOCON Marketing-Maschine Agent API", version="0.2.0")
app.mount(
    "/static",
    StaticFiles(directory=Path(__file__).resolve().parent / "static"),
    name="static",
)

_REQUEST_IDENTITY: ContextVar[dict[str, str] | None] = ContextVar(
    "marketing_machine_request_identity",
    default=None,
)


def current_authenticated_actor() -> str:
    identity = _REQUEST_IDENTITY.get() or {}
    return str(identity.get("authenticated_actor", "")).strip()


def identity_audit_fields() -> dict[str, str]:
    """Return trusted identity metadata; caller display fields remain separate."""

    identity = _REQUEST_IDENTITY.get() or {}
    actor = str(identity.get("authenticated_actor", "")).strip()
    fingerprint = str(identity.get("request_fingerprint", "")).strip()
    result: dict[str, str] = {}
    if actor:
        result["authenticated_actor"] = actor
        if fingerprint:
            result["authenticated_request_fingerprint"] = fingerprint
    return result


def require_human_actor(operation: str) -> str:
    """Fail closed for direct calls when production actor mode is enabled."""

    actor = current_authenticated_actor()
    if actor:
        return actor
    if actor_authentication_required() or runtime_instance_mode() == "production":
        raise HTTPException(
            status_code=401,
            detail=f"a named edge-authenticated actor is required for {operation}",
        )
    return ""


def _is_explicit_false(value: Any) -> bool:
    return (
        value is False
        or value == 0
        or (
            isinstance(value, str)
            and value.strip().casefold() in {"false", "0", "no", "off"}
        )
    )


def _sensitive_operation(path: str, payload: dict[str, Any]) -> str | None:
    exact = {
        "/session": "operator_session",
        "/workflows/approve-content": "content_approval",
        "/workflows/revise-content": "content_revision",
        "/workflows/content-media-asset": "media_approval",
        "/workflows/content-media-asset/revoke": "media_revocation",
        "/workflows/content-lifecycle": "operator_content_lifecycle",
        "/workflows/analytics-review": "analytics_review",
        "/workflows/analytics-review/correct": "analytics_correction",
    }
    if path in exact:
        return exact[path]
    if re.fullmatch(r"/workflows/reel-concepts/[^/]+/approve", path):
        return "reel_concept_approval"
    if re.fullmatch(r"/workflows/outbox/[^/]+/reconcile", path):
        return "operator_outbox_reconciliation"
    if path == "/workflows/lead-lifecycle":
        # The daily retention job is a non-human, privacy-reducing automation
        # authenticated by the agent access token. Every other transition is a
        # named human operation.
        if (
            str(payload.get("action", "")).strip().casefold() == "expire_retention"
            and str(payload.get("operator", "")).strip() == "automation:n8n-retention"
        ):
            return None
        return "lead_lifecycle"
    if path == "/workflows/route-scheduler-draft" and _is_explicit_false(
        payload.get("dry_run", True)
    ):
        return "live_scheduler_route"
    if path == "/workflows/route-lead" and _is_explicit_false(
        payload.get("dry_run", True)
    ):
        return "live_lead_route"
    return None


@app.middleware("http")
async def enforce_mutation_authorization(request: Request, call_next: Any) -> Any:
    public_paths = {"/", "/ui", "/healthz", "/readyz", "/metrics"}
    technical_read = technical_docs_enabled() and _is_technical_surface(
        request.url.path
    )
    is_public_read = request.method.upper() in {"GET", "HEAD", "OPTIONS"} and (
        request.url.path in public_paths
        or request.url.path.startswith("/static/")
        or technical_read
    )
    if not is_public_read:
        try:
            authorize_mutation(
                request.headers.get(MUTATION_TOKEN_HEADER),
                client_host=request.client.host if request.client else None,
            )
        except MutationAuthorizationError as exc:
            return JSONResponse(
                status_code=exc.status_code, content={"detail": exc.detail}
            )

        try:
            body = await bounded_mutation_body(request)
        except MutationBodyTooLarge:
            return JSONResponse(
                status_code=413,
                content={"detail": "request body is too large"},
            )
        payload: dict[str, Any] = {}
        if (
            body
            and "application/json" in request.headers.get("content-type", "").casefold()
        ):
            try:
                candidate = json.loads(body)
                if isinstance(candidate, dict):
                    payload = candidate
            except (UnicodeError, json.JSONDecodeError):
                pass
        operation = _sensitive_operation(request.url.path, payload)
        actor_is_required = (
            bool(
                operation
                and (
                    actor_authentication_required()
                    or runtime_instance_mode() == "production"
                )
            )
            or request.url.path == "/session"
        )
        try:
            actor = authenticate_edge_actor(
                request.headers.get(ACTOR_HEADER),
                request.headers.get(EDGE_ATTESTATION_HEADER),
                required=actor_is_required,
            )
        except ActorAuthenticationError as exc:
            return JSONResponse(
                status_code=exc.status_code, content={"detail": exc.detail}
            )

        timezone_status = business_timezone_policy_status()
        if not timezone_status["safe"] and request.url.path != "/session":
            return JSONResponse(
                status_code=503,
                content={"detail": "business timezone configuration is invalid"},
            )

        fingerprint = audit_request_fingerprint(
            method=request.method,
            path=request.url.path,
            query=request.url.query,
            body=body,
        )
        identity = {
            "authenticated_actor": actor or "",
            "request_fingerprint": fingerprint,
            "operation": operation or "",
        }
        token = _REQUEST_IDENTITY.set(identity)
        try:
            if operation and actor:
                try:
                    JsonStore().append_event(
                        "authenticated_request",
                        {
                            "operation": operation,
                            "authenticated_actor": actor,
                            "request_fingerprint": fingerprint,
                            "authorized_at": datetime.now(timezone.utc).isoformat(),
                        },
                    )
                except (OSError, ValueError) as exc:
                    return JSONResponse(
                        status_code=503,
                        content={
                            "detail": f"authenticated audit trail is unavailable: {type(exc).__name__}"
                        },
                    )
            return await call_next(request)
        finally:
            _REQUEST_IDENTITY.reset(token)
    return await call_next(request)


def _trusted_edge_forwarding(request: Request) -> None:
    """Apply one-hop proxy data only when the independent edge proof is valid."""

    forwarded_headers = (
        request.headers.get("x-forwarded-for", ""),
        request.headers.get("x-forwarded-host", ""),
        request.headers.get("x-forwarded-proto", ""),
    )
    if not any(forwarded_headers):
        return
    try:
        authenticate_edge_actor(
            request.headers.get(ACTOR_HEADER),
            request.headers.get(EDGE_ATTESTATION_HEADER),
            required=True,
        )
    except ActorAuthenticationError:
        # The authorization middleware still rejects forged identity headers
        # on protected routes. Public reads remain usable, but untrusted proxy
        # metadata never changes their URL or client identity.
        return

    forwarded_for, forwarded_host, forwarded_proto = forwarded_headers
    if not all(forwarded_headers) or forwarded_proto != "https" or "," in forwarded_for:
        return
    try:
        client_ip = ipaddress.ip_address(forwarded_for.strip()).compressed
        _normalized_host(forwarded_host, allow_port=True)
    except ValueError:
        return

    request.scope["scheme"] = "https"
    request.scope["client"] = (client_ip, 0)
    headers = [
        (name, value)
        for name, value in request.scope["headers"]
        if name.lower() != b"host"
    ]
    headers.append((b"host", forwarded_host.encode("ascii")))
    request.scope["headers"] = headers


def _host_policy_response(request: Request) -> PlainTextResponse | None:
    host_headers = [
        value for name, value in request.scope["headers"] if name.lower() == b"host"
    ]
    if len(host_headers) != 1:
        return PlainTextResponse("Invalid host header", status_code=400)
    try:
        request_host = _normalized_host(
            host_headers[0].decode("ascii"), allow_port=True
        )
    except UnicodeError:
        return PlainTextResponse("Invalid host header", status_code=400)
    except ValueError:
        return PlainTextResponse("Invalid host header", status_code=400)
    try:
        allowed_hosts = configured_trusted_hosts()
    except ValueError:
        return PlainTextResponse("Host policy is unavailable", status_code=503)
    client_host = request.client.host if request.client else ""
    if client_host == "testclient" and request_host == "testserver":
        return None
    if request_host not in allowed_hosts:
        return PlainTextResponse("Invalid host header", status_code=400)
    return None


def _apply_dynamic_response_policy(response: Any, *, path: str) -> Any:
    if not path.startswith("/static/"):
        response.headers["Cache-Control"] = NO_STORE_CACHE_CONTROL
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.middleware("http")
async def enforce_runtime_security_boundary(request: Request, call_next: Any) -> Any:
    """Enforce host/docs/proxy/cache boundaries before application routing."""

    host_error = _host_policy_response(request)
    if host_error is not None:
        return _apply_dynamic_response_policy(host_error, path=request.url.path)
    if _is_technical_surface(request.url.path) and not technical_docs_enabled():
        hidden = JSONResponse(status_code=404, content={"detail": "Not Found"})
        return _apply_dynamic_response_policy(hidden, path=request.url.path)
    _trusted_edge_forwarding(request)
    response = await call_next(request)
    return _apply_dynamic_response_policy(response, path=request.url.path)


@app.get("/", response_class=HTMLResponse)
@app.get("/ui", response_class=HTMLResponse)
def marketing_console() -> HTMLResponse:
    return HTMLResponse(render_marketing_console())


@app.get("/healthz")
def healthz() -> dict[str, Any]:
    instance_mode = (
        os.environ.get("MARKETING_MACHINE_INSTANCE_MODE", "production")
        .strip()
        .casefold()
    )
    data_namespace = os.environ.get(
        "MARKETING_MACHINE_DATA_NAMESPACE", "production-unspecified"
    ).strip()
    disposable_data = (
        instance_mode == "isolated-candidate"
        and data_namespace.casefold().startswith("candidate-")
        and os.environ.get("MARKETING_MACHINE_DISPOSABLE_DATA", "").strip().casefold()
        in {"1", "true", "yes", "on"}
    )
    return {
        "status": "ok",
        "instance": {
            "mode": instance_mode,
            "data_namespace": data_namespace,
            "disposable_data": disposable_data,
        },
    }


@app.get("/readyz")
def readyz() -> Any:
    policy = load_policy()
    mutation_auth = mutation_authorization_status()
    actor_auth = edge_actor_authorization_status()
    host_policy = trusted_host_policy_status()
    timezone_policy = business_timezone_policy_status()
    trend_policy = trend_intake_policy_status()
    production_actor_ready = (
        runtime_instance_mode() != "production"
        or actor_auth.get("production_ready") is True
    )
    ready = (
        mutation_auth["safe"]
        and actor_auth["safe"]
        and production_actor_ready
        and host_policy["safe"]
        and timezone_policy["safe"]
        and trend_policy["safe"]
    )
    payload = {
        "status": "ready" if ready else "unsafe",
        "policy": policy.name,
        "mode": policy.governance_level,
        "mutation_authorization": mutation_auth,
        "actor_authentication": actor_auth,
        "trusted_host_policy": host_policy,
        "business_timezone_policy": timezone_policy,
        "trend_intake_policy": trend_policy,
    }
    if not ready:
        return JSONResponse(status_code=503, content=payload)
    return payload


@app.get("/session")
def operator_session() -> dict[str, Any]:
    actor = current_authenticated_actor()
    if not actor:
        raise HTTPException(
            status_code=401, detail="a named edge-authenticated actor is required"
        )
    return {
        "authenticated": True,
        "actor": actor,
        "authentication": "edge_attested",
    }


@app.get("/metrics", response_class=PlainTextResponse)
def metrics() -> PlainTextResponse:
    return PlainTextResponse(
        render_prometheus_metrics(),
        media_type=PROMETHEUS_CONTENT_TYPE,
    )


WEEKLY_EDITORIAL_ANGLES = (
    "Das belegte Signal als klare Einordnung und Entscheidungsfrage aufbauen.",
    "Das belegte Signal als praktische Prüfliste mit umsetzbaren nächsten Schritten aufbauen.",
    "Das belegte Signal aus einer eigenständigen Risiko- oder Chancenperspektive einordnen.",
)


def default_briefs(*, now: datetime | None = None) -> list[ContentBrief]:
    """Build one stable brief slot for every effective active weekly target.

    Research provenance is attached separately by ``weekly_planning`` after an
    all-campaign preflight. Keeping the slot construction deterministic makes a
    retry idempotent without reusing the legacy one-item-per-campaign ids.
    """

    current = business_now(now)
    iso_year, iso_week, _ = current.isocalendar()
    briefs: list[ContentBrief] = []
    for campaign in load_campaign_catalog(repo_root(), today=current.date()):
        if not campaign.get("counts_toward_weekly_goal", False):
            continue
        weekly_target = max(0, int(campaign.get("effective_weekly_target", 0) or 0))
        base_id = (
            f"{campaign['id']}-{iso_year}w{iso_week:02d}-"
            f"{campaign['default_format'].replace('_', '-')}"
        )
        for slot in range(1, weekly_target + 1):
            content_id = f"{base_id}-source-backed-{slot:02d}"
            brief_payload = default_brief_payload(campaign, content_id=content_id)
            campaign_context = dict(brief_payload.get("campaign_context", {}))
            base_direction = str(
                campaign_context.get("generation_direction", "")
            ).strip()
            angle = WEEKLY_EDITORIAL_ANGLES[(slot - 1) % len(WEEKLY_EDITORIAL_ANGLES)]
            campaign_context.update(
                {
                    "generation_direction": f"{base_direction} {angle}".strip(),
                    "weekly_slot": slot,
                    "weekly_target": weekly_target,
                }
            )
            brief_payload["campaign_context"] = campaign_context
            brief_payload["test_variable"] = f"weekly_editorial_angle_{slot:02d}"
            briefs.append(ContentBrief(**brief_payload))
    return briefs


def _weekly_trend_candidates(
    trend_runs: list[dict[str, Any]],
    *,
    now: datetime,
) -> dict[str, list[dict[str, Any]]]:
    """Index only currently eligible, source-backed stored trends by campaign."""

    candidates: dict[str, list[dict[str, Any]]] = {}
    seen: set[tuple[str, str, str]] = set()
    for trend_run in trend_runs:
        refreshed = refresh_trend_run_eligibility(trend_run, now=now)
        run_id = str(refreshed.get("id", "")).strip()
        if not run_id:
            continue
        for campaign_result in refreshed.get("campaigns", []):
            if not isinstance(campaign_result, dict):
                continue
            trend_campaign = campaign_result.get("campaign", {})
            if not isinstance(trend_campaign, dict):
                continue
            trend_campaign_id = str(trend_campaign.get("id", "")).strip()
            campaign_id = resolve_campaign_id(
                trend_campaign_id or str(trend_campaign.get("name", ""))
            )
            if not campaign_id:
                continue
            for trend in campaign_result.get("trends", []):
                if not isinstance(trend, dict):
                    continue
                verification = trend.get("verification", {})
                if (
                    not isinstance(verification, dict)
                    or verification.get("eligible_for_content") is not True
                ):
                    continue
                trend_id = str(trend.get("id", "")).strip()
                source_urls = list(
                    dict.fromkeys(
                        str(value).strip()
                        for value in trend.get("source_urls", [])
                        if str(value).strip()
                    )
                )
                citations: list[dict[str, Any]] = []
                cited_urls: set[str] = set()
                for citation in trend.get("citations", []):
                    if not isinstance(citation, dict):
                        continue
                    url = str(citation.get("url", "")).strip()
                    if (
                        url not in source_urls
                        or not source_domain(url)
                        or url in cited_urls
                    ):
                        continue
                    citations.append(dict(citation))
                    cited_urls.add(url)
                if not trend_id or len(cited_urls) < 2:
                    continue
                key = (run_id, trend_campaign_id, trend_id)
                if key in seen:
                    continue
                seen.add(key)
                candidates.setdefault(campaign_id, []).append(
                    {
                        "run": refreshed,
                        "run_id": run_id,
                        "trend_campaign_id": trend_campaign_id,
                        "trend": trend,
                        "source_urls": source_urls,
                        "citations": citations,
                    }
                )
    return candidates


def _weekly_briefs_with_verified_sources(
    briefs: list[ContentBrief],
    campaigns: list[dict[str, Any]],
    trend_runs: list[dict[str, Any]],
    *,
    now: datetime,
) -> tuple[list[ContentBrief], list[dict[str, str]]]:
    """Attach exact stored provenance or report every active campaign blocker."""

    candidates_by_campaign = _weekly_trend_candidates(trend_runs, now=now)
    active_campaigns = {
        str(campaign.get("id", "")): campaign
        for campaign in campaigns
        if campaign.get("counts_toward_weekly_goal", False)
        and int(campaign.get("effective_weekly_target", 0) or 0) > 0
    }
    verified_briefs: list[ContentBrief] = []
    blocked_campaign_ids: set[str] = set()

    for brief in briefs:
        if brief.campaign_id not in active_campaigns:
            continue
        candidates = candidates_by_campaign.get(brief.campaign_id, [])
        slot = max(1, int(brief.campaign_context.get("weekly_slot", 1) or 1))
        selected: ContentBrief | None = None
        for offset in range(len(candidates)):
            candidate = candidates[(slot - 1 + offset) % len(candidates)]
            trend = candidate["trend"]
            candidate_brief = replace(
                brief,
                content_mode="current_trend",
                campaign_context={
                    **brief.campaign_context,
                    "content_mode": "current_trend",
                    "trend_campaign_id": candidate["trend_campaign_id"],
                },
                trend_run_id=candidate["run_id"],
                trend_id=str(trend.get("id", "")),
                trend_summary=str(trend.get("topic", "")).strip(),
                trend_sources=list(candidate["source_urls"]),
                trend_verification_status=str(
                    (trend.get("verification") or {}).get("status", "")
                ),
                citations=[dict(item) for item in candidate["citations"]],
            )
            if not validate_trend_brief_against_run(
                candidate_brief,
                candidate["run"],
                now=now,
            ):
                selected = candidate_brief
                break
        if selected is None:
            blocked_campaign_ids.add(brief.campaign_id)
        else:
            verified_briefs.append(selected)

    for campaign_id in active_campaigns:
        if not candidates_by_campaign.get(campaign_id):
            blocked_campaign_ids.add(campaign_id)
            continue
        expected = int(
            active_campaigns[campaign_id].get("effective_weekly_target", 0) or 0
        )
        actual = sum(1 for brief in verified_briefs if brief.campaign_id == campaign_id)
        if actual != expected:
            blocked_campaign_ids.add(campaign_id)

    blockers = [
        {
            "campaign_id": campaign_id,
            "campaign": str(
                active_campaigns[campaign_id].get("name", campaign_id.upper())
            ),
            "reason_code": "current_verified_research_missing",
        }
        for campaign_id in sorted(blocked_campaign_ids)
        if campaign_id in active_campaigns
    ]
    return verified_briefs, blockers


def create_state_for_brief(brief: ContentBrief) -> dict[str, Any]:
    workflow = MarketingWorkflow(load_policy(), evidence_vault=load_evidence_vault())
    state = workflow.run_until_review(brief)
    return state.to_dict()


@app.get("/campaigns")
def list_campaigns() -> dict[str, Any]:
    store = JsonStore()
    all_states = store.list_all_states(include_demo=False, page_size=100)
    items = campaign_dashboard(
        repo_root(),
        all_states,
        trend_runs=full_trend_runs(store),
    )
    return {"items": items, "count": len(items), "demo_data_included": False}


@app.get("/campaigns/{campaign_id}")
def campaign_detail(campaign_id: str) -> dict[str, Any]:
    try:
        canonical = get_campaign(repo_root(), campaign_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    store = JsonStore()
    all_states = store.list_all_states(include_demo=False, page_size=100)
    items = campaign_dashboard(
        repo_root(),
        all_states,
        trend_runs=full_trend_runs(store),
    )
    summary = next(item for item in items if item["id"] == canonical["id"])
    campaign_history = [
        item
        for item in all_states
        if (item.get("campaign_id") or resolve_campaign_id(item.get("campaign", "")))
        == canonical["id"]
    ]
    # Keep this browser payload bounded while making the complete calculation
    # and the fact that the history view is a slice explicit.
    content_items_limit = 100
    summary["content_items"] = campaign_history[:content_items_limit]
    summary["content_items_page"] = {
        "returned": len(summary["content_items"]),
        "total": len(campaign_history),
        "limit": content_items_limit,
        "has_more": len(campaign_history) > content_items_limit,
    }
    return summary


@app.get("/workflows/states")
def list_states(
    limit: int = Query(default=25, ge=1, le=100),
    include_demo: bool = Query(default=False),
    campaign_id: str = Query(default=""),
) -> dict[str, Any]:
    if campaign_id and campaign_id not in {"k1", "k2", "k3", "k4", "k5"}:
        raise HTTPException(
            status_code=422, detail="campaign_id must be one of k1, k2, k3, k4, or k5"
        )
    return {
        "items": JsonStore().list_states(
            limit=limit, include_demo=include_demo, campaign_id=campaign_id
        ),
        "demo_data_included": include_demo,
    }


@app.get("/workflows/states/{content_id}")
def get_state(content_id: str) -> dict[str, Any]:
    try:
        state = JsonStore.project_media_verification(JsonStore().load_state(content_id))
        stored_records = state.get("evidence_records", [])
        if isinstance(stored_records, list):
            proof_sources = [
                str(item.get("id", "")).strip()
                for item in stored_records
                if isinstance(item, dict) and str(item.get("id", "")).strip()
            ]
            current_records = {
                str(item.get("id", "")): item
                for item in load_evidence_vault().records_for(proof_sources)
            }
            state["evidence_records"] = [
                {
                    **current_records.get(
                        str(item.get("id", "")).strip(),
                        {
                            "id": str(item.get("id", "")).strip(),
                            "claim": str(item.get("claim", "")).strip(),
                        },
                    ),
                    "vault_verified": str(item.get("id", "")).strip()
                    in current_records,
                }
                for item in stored_records
                if isinstance(item, dict)
            ]
        return state
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail=f"content state not found: {content_id}"
        ) from exc


def _weekly_record_business_state(item: dict[str, Any]) -> str:
    generation = item.get("generation", {})
    generation_status = (
        str(generation.get("status", "")) if isinstance(generation, dict) else ""
    )
    if (
        generation_status == "ai_generated"
        and generation.get("fallback_used") is not True
        and item.get("status") == ContentStatus.NEEDS_HUMAN_REVIEW.value
        and item.get("next_step") == "human_review"
    ):
        return "ready_for_review"
    if (
        generation_status != "ai_generated"
        and item.get("status") == ContentStatus.BLOCKED.value
        and item.get("next_step") == "regenerate"
    ):
        return "blocked_needs_regeneration"
    if item.get("status") in {
        ContentStatus.READY_TO_SCHEDULE.value,
        ContentStatus.SCHEDULED.value,
        ContentStatus.PUBLISHED.value,
    }:
        return "progressed_beyond_review"
    return "attention_required"


@app.post("/workflows/weekly-planning")
def weekly_planning(payload: dict[str, Any]) -> dict[str, Any]:
    store = JsonStore()
    current = business_now()
    campaigns = load_campaign_catalog(repo_root(), today=current.date())
    briefs, research_blockers = _weekly_briefs_with_verified_sources(
        default_briefs(now=current),
        campaigns,
        full_trend_runs(store),
        now=current,
    )
    if research_blockers:
        campaign_labels = ", ".join(
            f"{item['campaign_id'].upper()} ({item['campaign']})"
            for item in research_blockers
        )
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "Wochenplan gesperrt: Für jede aktive Kampagne werden aktuelle, "
                    f"verifizierte Quellen benötigt. Fehlend: {campaign_labels}. "
                    "Bitte zuerst die Live-Recherche für diese Kampagnen abschließen; "
                    "es wurden keine Entwürfe angelegt."
                ),
                "reason_code": "current_verified_research_required",
                "missing_campaigns": research_blockers,
                "writes_performed": False,
            },
        )
    skipped_planned = [
        {
            "campaign_id": campaign["id"],
            "campaign": campaign["name"],
            "status": "planned",
            "configured_weekly_target": campaign["configured_weekly_target"],
            "effective_weekly_target": 0,
            "counts_toward_weekly_goal": False,
            "reason_code": "campaign_not_started",
            "business_message": f"Start am {campaign['start_date']}; bis dahin zählt die Kampagne nicht zum Wochenziel.",
        }
        for campaign in campaigns
        if campaign["status"] == "planned"
    ]
    created = []
    for brief in briefs:
        with store.state_lock(brief.id):
            try:
                existing = store.load_state(brief.id)
            except FileNotFoundError:
                existing = None
            if existing is not None:
                created.append(
                    {
                        "content_id": brief.id,
                        "campaign_id": brief.campaign_id,
                        "status": existing.get("brief", {}).get("status", ""),
                        "next_step": existing.get("next_step", ""),
                        "created_now": False,
                        "generation": existing.get("brief", {}).get("generation", {}),
                        "trend_run_id": existing.get("brief", {}).get(
                            "trend_run_id", ""
                        ),
                        "trend_id": existing.get("brief", {}).get("trend_id", ""),
                        "citations": existing.get("brief", {}).get("citations", []),
                    }
                )
                continue
            state = create_state_for_brief(brief)
            try:
                store.save_state(state, expected_revision=None)
            except StateRevisionConflict as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            created.append(
                {
                    "content_id": brief.id,
                    "campaign_id": brief.campaign_id,
                    "status": state["brief"]["status"],
                    "next_step": state["next_step"],
                    "created_now": True,
                    "generation": state["brief"].get("generation", {}),
                    "trend_run_id": state["brief"].get(
                        "trend_run_id", brief.trend_run_id
                    ),
                    "trend_id": state["brief"].get("trend_id", brief.trend_id),
                    "citations": state["brief"].get("citations", brief.citations),
                }
            )
    for item in created:
        item["business_state"] = _weekly_record_business_state(item)
    created_now = [item for item in created if item["created_now"]]
    already_present = [item for item in created if not item["created_now"]]
    ready_for_review = [
        item for item in created if item["business_state"] == "ready_for_review"
    ]
    blocked_needs_regeneration = [
        item
        for item in created
        if item["business_state"] == "blocked_needs_regeneration"
    ]
    attention_required = [
        item for item in created if item["business_state"] == "attention_required"
    ]
    progressed_beyond_review = [
        item for item in created if item["business_state"] == "progressed_beyond_review"
    ]
    if blocked_needs_regeneration and ready_for_review:
        overall_status = "partial_needs_regeneration"
    elif blocked_needs_regeneration:
        overall_status = "blocked_needs_regeneration"
    elif attention_required:
        overall_status = "attention_required"
    elif ready_for_review:
        overall_status = "ready_for_human_review"
    elif progressed_beyond_review:
        overall_status = "progressed_beyond_review"
    else:
        overall_status = "no_active_records"
    human_approval_required = bool(ready_for_review)
    weekly_goal = {
        "configured_total": sum(
            int(campaign["configured_weekly_target"]) for campaign in campaigns
        ),
        "effective_active_total": sum(
            int(campaign["effective_weekly_target"]) for campaign in campaigns
        ),
        "active_campaigns": sum(
            1 for campaign in campaigns if campaign["counts_toward_weekly_goal"]
        ),
    }
    summary = {
        "created_now": len(created_now),
        "already_present": len(already_present),
        "skipped_planned": len(skipped_planned),
        "ready_for_review": len(ready_for_review),
        "blocked_needs_regeneration": len(blocked_needs_regeneration),
        "attention_required": len(attention_required),
        "progressed_beyond_review": len(progressed_beyond_review),
    }
    store.append_event(
        "weekly_planning",
        {
            "payload": payload,
            "created": created,
            "skipped_planned": skipped_planned,
            "weekly_goal": weekly_goal,
            "summary": summary,
            "status": overall_status,
            "human_approval_required": human_approval_required,
            "ready_for_review": ready_for_review,
            "blocked_needs_regeneration": blocked_needs_regeneration,
        },
    )
    next_steps: list[str] = []
    if blocked_needs_regeneration:
        next_steps.append("regenerate blocked content records with local AI")
    if ready_for_review:
        next_steps.extend(
            [
                "review AI-generated drafts",
                "approve or request revision",
                "schedule approved draft-only payloads",
            ]
        )
    if attention_required:
        next_steps.append("inspect content records that require attention")
    return {
        "status": overall_status,
        "calendar_mode": payload.get("calendar_mode", "rolling_30_day"),
        "workflow": "weekly_planning",
        "human_approval_required": human_approval_required,
        # ``created`` is retained as a list of canonical records for existing
        # clients. Review readiness is represented only by the explicit lists.
        "created": created,
        "created_now": created_now,
        "already_present": already_present,
        "ready_for_review": ready_for_review,
        "blocked_needs_regeneration": blocked_needs_regeneration,
        "skipped_planned": skipped_planned,
        "weekly_goal": weekly_goal,
        "summary": summary,
        "next_steps": next_steps,
        "idempotency": "one canonical source-backed content brief per active weekly target slot and ISO week",
    }


@app.post("/workflows/trend-research")
def trend_research(payload: dict[str, Any]) -> dict[str, Any]:
    store = JsonStore()
    try:
        # Validate before returning an existing idempotent run. Otherwise an
        # old empty result could conceal a misspelled/nonexistent campaign.
        normalize_requested_campaign_ids(
            load_campaigns(repo_root()),
            payload.get("campaign_ids"),
        )
        normalize_requested_platforms(
            payload.get("platforms") if "platforms" in payload else None
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    request_id = str(payload.get("request_id", "")).strip()
    if request_id:
        try:
            expected_run_id = trend_request_run_id(request_id)
            existing = store.load_trend_run(expected_run_id)
        except FileNotFoundError:
            existing = None
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if existing is not None:
            if existing.get("request_fingerprint") != trend_request_fingerprint(
                payload
            ):
                raise HTTPException(
                    status_code=409,
                    detail="request_id was already used with a different trend request",
                )
            refresh_trend_run_eligibility(existing)
            return {
                "status": "created",
                "run_id": existing["id"],
                "trend_run": existing,
                "idempotent": True,
            }
    try:
        trend_run = run_trend_research(
            repo_root(), payload=payload, policy=load_policy()
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    store.save_trend_run(trend_run)
    store.append_event(
        "trend_research",
        {
            "run_id": trend_run["id"],
            "status": trend_run["status"],
            "lookback_days": trend_run["lookback_days"],
            "platforms": trend_run["platforms"],
            "source_adapters": trend_run["source_adapters"],
            "successful_source_adapters": trend_run.get(
                "successful_source_adapters", []
            ),
            "source_errors": trend_run.get("source_errors", []),
        },
    )
    return {"status": "created", "run_id": trend_run["id"], "trend_run": trend_run}


@app.get("/workflows/trend-research/runs")
def list_trend_runs(limit: int = Query(default=25, ge=1, le=100)) -> dict[str, Any]:
    store = JsonStore()
    items = store.list_trend_runs(limit=limit)
    for item in items:
        try:
            refreshed = refresh_trend_run_eligibility(
                store.load_trend_run(str(item.get("id", "")))
            )
        except (FileNotFoundError, ValueError):
            continue
        item["status"] = refreshed.get("status", item.get("status", ""))
        item["eligibility_evaluated_at"] = refreshed.get("eligibility_evaluated_at", "")
        item["eligibility_freshness_days"] = refreshed.get(
            "eligibility_freshness_days", 0
        )
    return {"items": items}


@app.get("/workflows/trend-research/runs/{run_id}")
def get_trend_run(run_id: str) -> dict[str, Any]:
    try:
        return refresh_trend_run_eligibility(JsonStore().load_trend_run(run_id))
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail=f"trend run not found: {run_id}"
        ) from exc


@app.get("/workflows/reel-concepts")
def list_reel_concepts(limit: int = Query(default=25, ge=1, le=100)) -> dict[str, Any]:
    return {"items": JsonStore().list_reel_concepts(limit=limit)}


@app.post("/workflows/reel-concepts")
def create_reel_concepts(payload: dict[str, Any]) -> dict[str, Any]:
    store = JsonStore()
    run_id = str(payload.get("run_id", "")).strip()
    campaign_id = str(payload.get("campaign_id", "")).strip()
    trend_id = str(payload.get("trend_id", "")).strip()
    if not run_id or not campaign_id or not trend_id:
        raise HTTPException(
            status_code=422, detail="run_id, campaign_id, and trend_id are required"
        )
    try:
        trend_run = store.load_trend_run(run_id)
        concept = generate_reel_concepts(
            trend_run,
            campaign_id=campaign_id,
            trend_id=trend_id,
            user_prompt=str(payload.get("user_prompt", "")),
            variant_count=int(payload.get("variant_count", 4)),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    store.save_reel_concept(concept)
    store.append_event(
        "reel_concept",
        {
            "concept_id": concept["id"],
            "run_id": concept["run_id"],
            "campaign_id": concept["campaign_id"],
            "trend_id": concept["trend_id"],
            "variant_count": len(concept["variants"]),
        },
    )
    return {"status": "created", "concept_id": concept["id"], "concept": concept}


def _is_ai_review_ready(state: dict[str, Any]) -> bool:
    brief = state.get("brief", {})
    generation = brief.get("generation", {}) if isinstance(brief, dict) else {}
    return bool(
        isinstance(generation, dict)
        and generation.get("status") == "ai_generated"
        and generation.get("fallback_used") is not True
        and brief.get("status") == ContentStatus.NEEDS_HUMAN_REVIEW.value
        and state.get("next_step") == "human_review"
        and state.get("requires_human_review") is True
        and state.get("approval") is None
        and not state.get("scheduler_payload")
    )


def _is_generation_retry_candidate(state: dict[str, Any]) -> bool:
    brief = state.get("brief", {})
    generation = brief.get("generation", {}) if isinstance(brief, dict) else {}
    return bool(
        isinstance(generation, dict)
        and generation.get("status") != "ai_generated"
        and brief.get("status") == ContentStatus.BLOCKED.value
        and state.get("next_step") == "regenerate"
        and state.get("requires_human_review") is False
        and state.get("approval") is None
        and not state.get("scheduler_payload")
    )


def _generation_failure_detail(content_id: str) -> dict[str, Any]:
    return {
        "message": (
            "Der KI-Entwurf konnte noch nicht zuverlässig erstellt werden. "
            "Die ausgewählte Richtung bleibt gespeichert und kann erneut erstellt werden."
        ),
        "retry_allowed": True,
        "action": "regenerate",
        "content_id": content_id,
    }


def _provenance_blocker_detail(content_id: str = "") -> dict[str, Any]:
    detail: dict[str, Any] = {
        "message": (
            "Die ausgewählte Richtung kann nicht erneut erstellt werden, weil die "
            "zugehörigen Quellen nicht mehr aktuell bestätigt sind. Bitte zuerst neu recherchieren."
        ),
        "retry_allowed": False,
        "action": "refresh_research",
    }
    if content_id:
        detail["content_id"] = content_id
    return detail


def _revalidated_concept_brief(
    store: JsonStore,
    concept: dict[str, Any],
    variant_id: str,
    *,
    expected_content_id: str = "",
) -> tuple[ContentBrief, dict[str, Any]]:
    try:
        brief = concept_to_content_brief(concept, variant_id=variant_id)
        if expected_content_id and brief.id != expected_content_id:
            raise ValueError(
                "stored content selection no longer matches the immutable concept"
            )
        trend_run = store.load_trend_run(brief.trend_run_id)
        provenance_errors = validate_trend_brief_against_run(brief, trend_run)
        if provenance_errors:
            raise ValueError("stored trend provenance is no longer current")
    except (FileNotFoundError, KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=409,
            detail=_provenance_blocker_detail(expected_content_id),
        ) from exc
    return brief, trend_run


def _validate_retry_state_provenance(
    state: dict[str, Any],
    expected_brief: ContentBrief,
    trend_run: dict[str, Any],
) -> None:
    try:
        stored_brief = brief_from_dict(state["brief"])
        identity_matches = all(
            (
                stored_brief.id == expected_brief.id,
                stored_brief.campaign_id == expected_brief.campaign_id,
                stored_brief.trend_run_id == expected_brief.trend_run_id,
                stored_brief.trend_id == expected_brief.trend_id,
            )
        )
        provenance_errors = validate_trend_brief_against_run(stored_brief, trend_run)
        if not identity_matches or provenance_errors:
            raise ValueError(
                "blocked state provenance no longer matches the selected concept"
            )
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=409,
            detail=_provenance_blocker_detail(expected_brief.id),
        ) from exc


def _attach_reel_selection_audit(
    state: dict[str, Any],
    *,
    concept_id: str,
    fingerprint: str,
    authenticated_actor: str,
    identity_fields: dict[str, str],
) -> None:
    state["reel_concept_id"] = concept_id
    state["reel_approval_fingerprint"] = fingerprint
    if authenticated_actor:
        state["reel_approval_authenticated_actor"] = authenticated_actor
    state.update(
        {
            key: value
            for key, value in identity_fields.items()
            if key == "authenticated_request_fingerprint"
        }
    )


def _update_selected_concept(
    concept: dict[str, Any],
    *,
    variant_id: str,
    fingerprint: str,
    content_id: str,
    review_ready: bool,
    authenticated_actor: str,
    identity_fields: dict[str, str],
) -> None:
    concept["status"] = (
        "approved_for_content_brief" if review_ready else "content_generation_blocked"
    )
    concept["approved_variant_id"] = variant_id
    concept["approval_fingerprint"] = fingerprint
    concept["content_id"] = content_id
    if authenticated_actor and not concept.get("approval_authenticated_actor"):
        concept["approval_authenticated_actor"] = authenticated_actor
    concept.update(
        {
            key: value
            for key, value in identity_fields.items()
            if key == "authenticated_request_fingerprint"
        }
    )


def _record_reel_generation_success(
    store: JsonStore,
    concept: dict[str, Any],
    state: dict[str, Any],
    *,
    concept_id: str,
    content_id: str,
    identity_fields: dict[str, str],
) -> None:
    store.append_learning(
        {
            "event": "reel_concept_approved",
            "concept_id": concept_id,
            "content_id": content_id,
            "campaign_id": concept.get("campaign_id", ""),
            "trend_id": concept.get("trend_id", ""),
            "selected_variant_id": concept.get("approved_variant_id", ""),
            "created_at": state["brief"].get("created_at", ""),
            **identity_fields,
        }
    )
    store.append_event(
        "reel_concept_approval",
        {
            "concept_id": concept_id,
            "content_id": content_id,
            "state": state,
            **identity_fields,
        },
    )


@app.post("/workflows/reel-concepts/{concept_id}/approve")
def approve_reel_concept(concept_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    authenticated_actor = require_human_actor("Reel concept approval")
    identity_fields = identity_audit_fields()
    store = JsonStore()
    variant_id = str(payload.get("variant_id", "")).strip()
    if not variant_id:
        raise HTTPException(
            status_code=422,
            detail="variant_id is required; a marketer must explicitly select a Reel variant",
        )
    try:
        with store.reel_concept_lock(concept_id):
            concept = store.load_reel_concept(concept_id)
            concept_revision = JsonStore.state_revision(concept)
            fingerprint = reel_approval_fingerprint(concept, variant_id)
            persisted_fingerprint = str(concept.get("approval_fingerprint", "")).strip()
            persisted_variant_id = str(concept.get("approved_variant_id", "")).strip()
            persisted_content_id = str(concept.get("content_id", "")).strip()

            if persisted_fingerprint:
                if (
                    persisted_fingerprint != fingerprint
                    or persisted_variant_id != variant_id
                ):
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "message": "Für diese Richtung ist bereits eine andere Auswahl gespeichert.",
                            "retry_allowed": False,
                            "action": "reload_selection",
                            **(
                                {"content_id": persisted_content_id}
                                if persisted_content_id
                                else {}
                            ),
                        },
                    )
                require_expected_revision(payload, concept, resource="Reel concept")
                if not persisted_content_id:
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "message": "Die gespeicherte Auswahl ist unvollständig.",
                            "retry_allowed": False,
                            "action": "reload_selection",
                        },
                    )
                with store.state_lock(persisted_content_id):
                    try:
                        existing_state = store.load_state(persisted_content_id)
                    except FileNotFoundError as exc:
                        raise HTTPException(
                            status_code=409,
                            detail={
                                "message": "Der gespeicherte Inhalt zur Auswahl wurde nicht gefunden.",
                                "retry_allowed": False,
                                "action": "reload_selection",
                                "content_id": persisted_content_id,
                            },
                        ) from exc
                    state_revision = JsonStore.state_revision(existing_state)
                    if existing_state.get("reel_approval_fingerprint") != fingerprint:
                        raise HTTPException(
                            status_code=409,
                            detail={
                                "message": "Der gespeicherte Inhalt passt nicht mehr zur ausgewählten Richtung.",
                                "retry_allowed": False,
                                "action": "reload_selection",
                                "content_id": persisted_content_id,
                            },
                        )

                    if not _is_generation_retry_candidate(existing_state):
                        response_status = (
                            "approved"
                            if concept.get("status") == "approved_for_content_brief"
                            else "blocked"
                        )
                        return {
                            "status": response_status,
                            "concept_id": concept_id,
                            "content_id": persisted_content_id,
                            "state": existing_state,
                            "idempotent": True,
                            "retry_allowed": False,
                        }
                    if concept.get("status") != "content_generation_blocked":
                        raise HTTPException(
                            status_code=409,
                            detail={
                                "message": "Der Inhalt ist nicht für eine erneute Erstellung freigegeben.",
                                "retry_allowed": False,
                                "action": "reload_selection",
                                "content_id": persisted_content_id,
                            },
                        )

                    brief, trend_run = _revalidated_concept_brief(
                        store,
                        concept,
                        variant_id,
                        expected_content_id=persisted_content_id,
                    )
                    _validate_retry_state_provenance(existing_state, brief, trend_run)
                    retried_state = create_state_for_brief(brief)
                    if retried_state.get("brief", {}).get("id") != persisted_content_id:
                        raise HTTPException(
                            status_code=409,
                            detail={
                                "message": "Die erneute Erstellung konnte nicht sicher zugeordnet werden.",
                                "retry_allowed": False,
                                "action": "reload_selection",
                                "content_id": persisted_content_id,
                            },
                        )
                    selection_actor = (
                        str(concept.get("approval_authenticated_actor", "")).strip()
                        or authenticated_actor
                    )
                    _attach_reel_selection_audit(
                        retried_state,
                        concept_id=concept_id,
                        fingerprint=fingerprint,
                        authenticated_actor=selection_actor,
                        identity_fields=identity_fields,
                    )
                    store.save_state(retried_state, expected_revision=state_revision)

                review_ready = _is_ai_review_ready(retried_state)
                _update_selected_concept(
                    concept,
                    variant_id=variant_id,
                    fingerprint=fingerprint,
                    content_id=persisted_content_id,
                    review_ready=review_ready,
                    authenticated_actor=authenticated_actor,
                    identity_fields=identity_fields,
                )
                store.save_reel_concept(concept, expected_revision=concept_revision)
                if not review_ready:
                    raise HTTPException(
                        status_code=422,
                        detail=_generation_failure_detail(persisted_content_id),
                    )
                _record_reel_generation_success(
                    store,
                    concept,
                    retried_state,
                    concept_id=concept_id,
                    content_id=persisted_content_id,
                    identity_fields=identity_fields,
                )
                return {
                    "status": "approved",
                    "concept_id": concept_id,
                    "content_id": persisted_content_id,
                    "state": retried_state,
                    "idempotent": False,
                    "retried_generation": True,
                    "retry_allowed": False,
                }

            require_expected_revision(payload, concept, resource="Reel concept")
            if concept.get("status") not in {"draft", "draft_test_override"} or any(
                concept.get(field) for field in ("approved_variant_id", "content_id")
            ):
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "Diese Richtung wurde bereits verarbeitet und kann nicht erneut ausgewählt werden.",
                        "retry_allowed": False,
                        "action": "reload_selection",
                    },
                )

            brief, _trend_run = _revalidated_concept_brief(store, concept, variant_id)

            with store.state_lock(brief.id):
                generated_state: dict[str, Any] | None
                try:
                    generated_state = store.load_state(brief.id)
                except FileNotFoundError:
                    generated_state = None
                if generated_state is not None:
                    if generated_state.get("reel_approval_fingerprint") != fingerprint:
                        raise HTTPException(
                            status_code=409,
                            detail={
                                "message": "Für diesen Inhalt besteht bereits eine andere oder geprüfte Auswahl.",
                                "retry_allowed": False,
                                "action": "reload_selection",
                                "content_id": brief.id,
                            },
                        )
                    review_ready = _is_ai_review_ready(generated_state)
                    _update_selected_concept(
                        concept,
                        variant_id=variant_id,
                        fingerprint=fingerprint,
                        content_id=brief.id,
                        review_ready=review_ready,
                        authenticated_actor=authenticated_actor,
                        identity_fields=identity_fields,
                    )
                    store.save_reel_concept(concept, expected_revision=concept_revision)
                    return {
                        "status": "approved"
                        if concept["status"] == "approved_for_content_brief"
                        else "blocked",
                        "concept_id": concept_id,
                        "content_id": brief.id,
                        "state": generated_state,
                        "idempotent": True,
                    }

                state = create_state_for_brief(brief)
                _attach_reel_selection_audit(
                    state,
                    concept_id=concept_id,
                    fingerprint=fingerprint,
                    authenticated_actor=authenticated_actor,
                    identity_fields=identity_fields,
                )
                store.save_state(state, expected_revision=None)

                reviewable = _is_ai_review_ready(state)
                _update_selected_concept(
                    concept,
                    variant_id=variant_id,
                    fingerprint=fingerprint,
                    content_id=brief.id,
                    review_ready=reviewable,
                    authenticated_actor=authenticated_actor,
                    identity_fields=identity_fields,
                )
                store.save_reel_concept(concept, expected_revision=concept_revision)

                if not reviewable:
                    raise HTTPException(
                        status_code=422,
                        detail=_generation_failure_detail(brief.id),
                    )

                _record_reel_generation_success(
                    store,
                    concept,
                    state,
                    concept_id=concept_id,
                    content_id=brief.id,
                    identity_fields=identity_fields,
                )
                return {
                    "status": "approved",
                    "concept_id": concept_id,
                    "content_id": brief.id,
                    "state": state,
                }
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "message": "Die ausgewählte Richtung oder der zugehörige Inhalt wurde nicht gefunden.",
                "retry_allowed": False,
                "action": "reload_selection",
            },
        ) from exc
    except StateRevisionConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Der Stand wurde zwischenzeitlich geändert. Bitte neu laden.",
                "retry_allowed": True,
                "action": "reload_selection",
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Die ausgewählte Richtung konnte nicht sicher verarbeitet werden.",
                "retry_allowed": False,
                "action": "reload_selection",
            },
        ) from exc


MANUAL_TREND_ASSERTION_FIELDS = (
    "trend_summary",
    "trend_sources",
    "trend_verification_status",
    "citations",
)
EVERGREEN_RECENCY_CLAIM = re.compile(
    r"(?i)(?:\btrends?\b|\btrending\b|\blatest(?:[\s_-]*trends?)?\b|"
    r"\brecent(?:[\s_-]*trends?)?\b|\bcurrent(?:[\s_-]*trends?)?\b|\btoday\b|"
    r"\bthis\s+week\b|\baktuell\w*\b|\bneueste\w*\b|\bheute\b|\bderzeit\b|"
    r"\bmomentan\b|\bdiese\w*\s+woche\b)"
)


def _manual_intake_content_mode(payload: dict[str, Any]) -> str:
    policy_enabled = explicit_content_mode_required()
    if "content_mode" not in payload:
        if policy_enabled:
            raise ValueError(
                "content_mode is required: choose evergreen, or choose current_trend with a stored verified trend"
            )
        return "evergreen"
    raw = payload.get("content_mode")
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("content_mode must be evergreen or current_trend")
    mode = raw.strip().casefold()
    if mode not in {"evergreen", "current_trend"}:
        raise ValueError("content_mode must be evergreen or current_trend")
    return mode


def _reject_evergreen_recency_claims(payload: dict[str, Any]) -> None:
    for field in ("objective", "hypothesis", "user_prompt", "cta", "format"):
        value = payload.get(field)
        if isinstance(value, str) and EVERGREEN_RECENCY_CLAIM.search(value):
            raise ValueError(
                f"evergreen {field} must not request a current or trending claim; "
                "choose current_trend with stored verified sources"
            )
    hashtags = payload.get("hashtags")
    if isinstance(hashtags, list) and any(
        isinstance(value, str) and EVERGREEN_RECENCY_CLAIM.search(value)
        for value in hashtags
    ):
        raise ValueError(
            "evergreen hashtags must not request a current or trending claim; "
            "choose current_trend with stored verified sources"
        )


def _stored_verified_trend_selection(
    store: JsonStore,
    *,
    run_id: str,
    trend_id: str,
    campaign_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve untrusted references to one currently eligible stored trend."""

    try:
        trend_run = refresh_trend_run_eligibility(store.load_trend_run(run_id))
    except (FileNotFoundError, ValueError) as exc:
        raise ValueError(
            "stored trend selection was not found; run Trend Studio again or choose evergreen"
        ) from exc

    matches: list[tuple[dict[str, Any], dict[str, Any]]] = []
    for campaign_result in trend_run.get("campaigns", []):
        if not isinstance(campaign_result, dict):
            continue
        trend_campaign = campaign_result.get("campaign", {})
        if not isinstance(trend_campaign, dict):
            continue
        resolved_campaign_id = resolve_campaign_id(
            str(trend_campaign.get("id", "") or trend_campaign.get("name", ""))
        )
        if resolved_campaign_id != campaign_id:
            continue
        for trend in campaign_result.get("trends", []):
            if isinstance(trend, dict) and str(trend.get("id", "")).strip() == trend_id:
                matches.append((campaign_result, trend))
    if len(matches) != 1:
        raise ValueError(
            "stored trend selection does not belong to this campaign; select it again in Trend Studio"
        )

    campaign_result, trend = matches[0]
    verification = trend.get("verification", {})
    if (
        not isinstance(verification, dict)
        or verification.get("eligible_for_content") is not True
        or verification.get("status") != "verified_recent"
    ):
        raise ValueError(
            "stored trend is not currently source-verified; run Trend Studio again or choose evergreen"
        )
    return trend_run, {
        "trend_campaign_id": str((campaign_result.get("campaign") or {}).get("id", "")),
        "trend_summary": str(trend.get("topic", "")).strip(),
        "trend_sources": list(trend.get("source_urls", [])),
        "trend_verification_status": str(verification.get("status", "")),
        "citations": [
            dict(item) for item in trend.get("citations", []) if isinstance(item, dict)
        ],
    }


@app.post("/workflows/create-content")
def create_content(payload: dict[str, Any]) -> dict[str, Any]:
    intake_fingerprint = request_fingerprint(payload)
    try:
        content_mode = _manual_intake_content_mode(payload)
        supplied_assertions = [
            field for field in MANUAL_TREND_ASSERTION_FIELDS if field in payload
        ]
        if supplied_assertions:
            raise ValueError(
                "manual intake cannot assert trend evidence; provide only stored trend_run_id and trend_id references"
            )
        content_id = validate_identifier(str(payload["id"]), field="content_id")
        campaign_id = str(
            payload.get("campaign_id", "")
        ).strip().lower() or resolve_campaign_id(str(payload.get("campaign", "")))
        if campaign_id not in {"k1", "k2", "k3", "k4", "k5"}:
            raise ValueError(
                "campaign_id must resolve to one of the five real campaigns: k1, k2, k3, k4, or k5"
            )
        campaign = get_campaign(repo_root(), campaign_id)
        store = JsonStore()
        trend_run: dict[str, Any] | None = None
        trend_selection: dict[str, Any] = {}
        if content_mode == "evergreen":
            _reject_evergreen_recency_claims(payload)
            if "trend_run_id" in payload or "trend_id" in payload:
                raise ValueError(
                    "evergreen content must omit trend_run_id and trend_id so it cannot be mistaken for trend-backed content"
                )
        else:
            run_id = validate_identifier(
                str(payload.get("trend_run_id", "")), field="trend_run_id"
            )
            trend_id = validate_identifier(
                str(payload.get("trend_id", "")), field="trend_id"
            )
            trend_run, trend_selection = _stored_verified_trend_selection(
                store,
                run_id=run_id,
                trend_id=trend_id,
                campaign_id=campaign_id,
            )

        canonical_brief = default_brief_payload(campaign, content_id=content_id)
        proof_sources = canonical_string_union(
            list(canonical_brief["proof_sources"]),
            payload.get("proof_sources"),
            field="proof_sources",
        )
        risk_flags = canonical_string_union(
            list(canonical_brief["risk_flags"]),
            payload.get("risk_flags"),
            field="risk_flags",
        )
        campaign_context = {
            **dict(canonical_brief["campaign_context"]),
            "content_mode": content_mode,
        }
        if trend_selection:
            campaign_context["trend_campaign_id"] = trend_selection["trend_campaign_id"]
        brief = ContentBrief(
            id=content_id,
            campaign_id=campaign["id"],
            campaign=campaign["name"],
            campaign_context=campaign_context,
            persona=payload.get("persona", campaign["primary_persona"]),
            channel=payload.get("channel", campaign["default_channel"]),
            format=payload.get("format", campaign["default_format"]),
            objective=payload.get("objective", campaign["generation_objective"]),
            cta=payload.get("cta", campaign["offer"]),
            proof_sources=proof_sources,
            utm=payload.get("utm") or canonical_brief["utm"],
            hypothesis=payload.get("hypothesis", "Manual intake hypothesis pending."),
            test_variable=payload.get("test_variable", "manual_intake"),
            content_mode=content_mode,
            language=payload.get("language", "de-DE"),
            hashtags=payload.get("hashtags", []),
            risk_flags=risk_flags,
            user_prompt=str(payload.get("user_prompt", "")),
            trend_run_id=str(payload.get("trend_run_id", ""))
            if trend_selection
            else "",
            trend_id=str(payload.get("trend_id", "")) if trend_selection else "",
            trend_summary=str(trend_selection.get("trend_summary", "")),
            trend_sources=list(trend_selection.get("trend_sources", [])),
            trend_verification_status=str(
                trend_selection.get("trend_verification_status", "")
            ),
            citations=list(trend_selection.get("citations", [])),
        )
        if trend_run is not None:
            trend_errors = validate_trend_brief_against_run(brief, trend_run)
            if trend_errors:
                raise ValueError(
                    "stored trend selection failed current verification; run Trend Studio again or choose evergreen"
                )
    except TrendPolicyConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail="content intake is blocked because the explicit content-mode policy is invalid",
        ) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=422, detail=f"missing required field: {exc.args[0]}"
        ) from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    with store.state_lock(brief.id):
        try:
            existing = store.load_state(brief.id)
        except FileNotFoundError:
            existing = None
        if existing is not None:
            if existing.get("intake_fingerprint") == intake_fingerprint:
                return {
                    "status": "created",
                    "content_id": brief.id,
                    "state": existing,
                    "idempotent": True,
                }
            raise HTTPException(
                status_code=409,
                detail=f"content state already exists: {brief.id}; use a new content id instead of overwriting history",
            )
        state = create_state_for_brief(brief)
        state["intake_fingerprint"] = intake_fingerprint
        try:
            store.save_state(state, expected_revision=None)
        except StateRevisionConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"status": "created", "content_id": brief.id, "state": state}


@app.post("/workflows/revise-content")
def revise_content(payload: dict[str, Any]) -> dict[str, Any]:
    """Create a versioned replacement draft while preserving review history."""

    authenticated_actor = require_human_actor("content revision")
    identity_fields = identity_audit_fields()
    store = JsonStore()
    content_id = str(payload.get("content_id", "")).strip()
    editor = str(payload.get("editor", "")).strip()
    revision_notes = str(payload.get("revision_notes", "")).strip()
    if not content_id or not editor or not revision_notes:
        raise HTTPException(
            status_code=422,
            detail="content_id, editor, and revision_notes are required",
        )
    try:
        with store.state_lock(content_id):
            current = store.load_state(content_id)
            source_revision = JsonStore.state_revision(current)
            original = brief_from_dict(current["brief"])
            if original.status not in {
                ContentStatus.REVISION_REQUESTED,
                ContentStatus.BLOCKED,
            }:
                raise HTTPException(
                    status_code=409,
                    detail="only a revision_requested or blocked draft can create a new version",
                )
            if original.trend_id:
                try:
                    trend_run = store.load_trend_run(original.trend_run_id)
                except (FileNotFoundError, ValueError) as exc:
                    raise HTTPException(
                        status_code=409,
                        detail="stored trend run is unavailable; research again",
                    ) from exc
                trend_errors = validate_trend_brief_against_run(original, trend_run)
                if trend_errors:
                    raise HTTPException(
                        status_code=409,
                        detail=f"trend evidence must be refreshed: {'; '.join(trend_errors)}",
                    )

            revision_fingerprint = request_fingerprint(
                {
                    "source_content_id": content_id,
                    "source_revision": source_revision,
                    "editor": editor,
                    "revision_notes": revision_notes[:2000],
                }
            )

            # The predecessor lock is held across the complete discovery and
            # write. This serializes operators and workers on one immutable
            # history edge, while child locks continue to protect each file.
            first_available_revision_id = ""
            for number in range(1, 100):
                revision_id = validate_identifier(
                    f"{content_id}-r{number}", field="content_id"
                )
                with store.state_lock(revision_id):
                    try:
                        existing_revision = store.load_state(revision_id)
                    except FileNotFoundError:
                        existing_revision = None
                    if existing_revision is None:
                        if not first_available_revision_id:
                            first_available_revision_id = revision_id
                        continue
                    revision_source = existing_revision.get("revision_source", {})
                    is_successor = (
                        isinstance(revision_source, dict)
                        and str(revision_source.get("content_id", "")).strip()
                        == content_id
                        and revision_source.get("revision") == source_revision
                    )
                    if not is_successor:
                        continue
                    if (
                        existing_revision.get("revision_request_fingerprint")
                        == revision_fingerprint
                    ):
                        return {
                            "status": "created",
                            "source_content_id": content_id,
                            "content_id": revision_id,
                            "state": existing_revision,
                            "idempotent": True,
                        }
                    raise HTTPException(
                        status_code=409,
                        detail={
                            "code": "revision_successor_exists",
                            "message": (
                                "A replacement draft already exists for this content version; "
                                "continue with that draft instead of creating a parallel version."
                            ),
                            "source_content_id": content_id,
                            "source_revision": source_revision,
                            "existing_content_id": revision_id,
                        },
                    )

            if not first_available_revision_id:
                raise HTTPException(
                    status_code=409, detail="revision version limit reached"
                )

            require_expected_revision(payload, current, resource="source content")
            now = datetime.now(timezone.utc).isoformat()
            brief_payload = dict(current["brief"])
            context = dict(brief_payload.get("campaign_context", {}))
            context["revision_notes"] = revision_notes[:2000]
            brief_payload.update(
                {
                    "id": first_available_revision_id,
                    "campaign_context": context,
                    "status": ContentStatus.DRAFTING.value,
                    "draft": "",
                    "public_copy": "",
                    "channel_copy": {},
                    "reel_output": {},
                    "generation": {},
                    "review_notes": [],
                    "created_at": now,
                    "updated_at": now,
                }
            )
            revised_brief = brief_from_dict(brief_payload)
            revised_state = create_state_for_brief(revised_brief)
            revised_state["revision_request_fingerprint"] = revision_fingerprint
            revised_state["revision_source"] = {
                "content_id": content_id,
                "revision": source_revision,
            }
            if authenticated_actor:
                revised_state["revision_source"]["authenticated_actor"] = (
                    authenticated_actor
                )
            revised_state["revision_source"].update(
                {
                    key: value
                    for key, value in identity_fields.items()
                    if key == "authenticated_request_fingerprint"
                }
            )
            with store.state_lock(first_available_revision_id):
                store.save_state(revised_state, expected_revision=None)
            store.append_event_once(
                "revision",
                f"revision-{revision_fingerprint}",
                {
                    "source_content_id": content_id,
                    "source_revision": source_revision,
                    "content_id": first_available_revision_id,
                    "editor": editor,
                    "revision_notes": revision_notes[:2000],
                    "created_at": now,
                    **identity_fields,
                },
            )
            return {
                "status": "created",
                "source_content_id": content_id,
                "content_id": first_available_revision_id,
                "state": revised_state,
            }
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail=f"content state not found: {content_id}"
        ) from exc
    except StateRevisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=422, detail=f"invalid stored content state: {exc}"
        ) from exc


@app.post("/workflows/approve-content")
def approve_content(payload: dict[str, Any]) -> dict[str, Any]:
    require_human_actor("content approval")
    store = JsonStore()
    content_id = str(payload.get("content_id", "")).strip()
    if not content_id:
        raise HTTPException(
            status_code=422, detail="missing required field: content_id"
        )
    try:
        with store.state_lock(content_id):
            return _approve_content_locked(store, content_id, payload)
    except StateRevisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _approve_content_locked(
    store: JsonStore,
    content_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    try:
        current = store.load_state(content_id)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail=f"content state not found: {content_id}"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        reviewer = str(payload.get("reviewer", "")).strip()
        if not reviewer:
            raise ValueError("reviewer is required")
        if "decision" not in payload:
            raise ValueError("decision is required")
        if "brand_score" not in payload:
            raise ValueError("brand_score is required")
        brand_score = non_negative_int(payload["brand_score"], field="brand_score")
        if brand_score > 100:
            raise ValueError("brand_score must be between 0 and 100")
        notes = required_text(payload, "notes", max_length=2000)
        approval = ApprovalRecord(
            content_id=content_id,
            reviewer=reviewer,
            decision=ReviewDecision(payload["decision"]),
            brand_score=brand_score,
            fact_check_passed=strict_bool(
                payload.get("fact_check_passed", False), field="fact_check_passed"
            ),
            privacy_check_passed=strict_bool(
                payload.get("privacy_check_passed", False), field="privacy_check_passed"
            ),
            ai_disclosure_check_passed=strict_bool(
                payload.get("ai_disclosure_check_passed", False),
                field="ai_disclosure_check_passed",
            ),
            notes=notes,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail=f"invalid approval payload: {exc}"
        ) from exc

    existing_approval_data = current.get("approval")
    existing_approval: ApprovalRecord | None = None
    if existing_approval_data is not None:
        if not isinstance(existing_approval_data, dict):
            raise HTTPException(
                status_code=409,
                detail="stored approval audit is invalid; state was not changed",
            )
        try:
            existing_kwargs: dict[str, Any] = {
                "content_id": str(existing_approval_data["content_id"]),
                "reviewer": str(existing_approval_data["reviewer"]),
                "decision": ReviewDecision(existing_approval_data["decision"]),
                "brand_score": int(existing_approval_data["brand_score"]),
                "fact_check_passed": strict_bool(
                    existing_approval_data["fact_check_passed"],
                    field="stored fact_check_passed",
                ),
                "privacy_check_passed": strict_bool(
                    existing_approval_data["privacy_check_passed"],
                    field="stored privacy_check_passed",
                ),
                "ai_disclosure_check_passed": strict_bool(
                    existing_approval_data["ai_disclosure_check_passed"],
                    field="stored ai_disclosure_check_passed",
                ),
                "notes": str(existing_approval_data.get("notes", "") or ""),
            }
            if existing_approval_data.get("created_at"):
                existing_kwargs["created_at"] = str(
                    existing_approval_data["created_at"]
                )
            existing_approval = ApprovalRecord(**existing_kwargs)
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=409,
                detail="stored approval audit is invalid; state was not changed",
            ) from exc

        def approval_signature(record: ApprovalRecord) -> dict[str, Any]:
            signature = record.to_dict()
            signature.pop("created_at", None)
            return signature

        if approval_signature(existing_approval) == approval_signature(approval):
            return {
                "status": "reviewed",
                "content_id": content_id,
                "state": current,
                "idempotent": True,
            }
        raise HTTPException(
            status_code=409,
            detail="content already has a different terminal approval; state was not changed",
        )

    current_revision = require_expected_revision(payload, current, resource="content")
    brief = brief_from_dict(current["brief"])
    if (
        brief.id != content_id
        or brief.status.value != "needs_human_review"
        or not bool(current.get("requires_human_review", False))
        or current.get("next_step") != "human_review"
        or bool(current.get("errors"))
    ):
        raise HTTPException(
            status_code=409,
            detail="content is not awaiting a review; state was not changed",
        )

    approved_media_assets = current.get("approved_media_assets", [])
    if not isinstance(approved_media_assets, list):
        approved_media_assets = []
    if approval.is_publishable:
        people_evidence_errors = people_media_evidence_errors(
            brief,
            approved_media_assets,
        )
        if people_evidence_errors:
            raise HTTPException(
                status_code=409,
                detail=f"people and consent evidence is incomplete: {'; '.join(people_evidence_errors)}",
            )

    if brief.trend_id:
        if not brief.trend_run_id:
            raise HTTPException(
                status_code=422,
                detail="trend-backed content is missing its stored trend run id; state was not changed",
            )
        try:
            trend_run = store.load_trend_run(brief.trend_run_id)
        except FileNotFoundError as exc:
            raise HTTPException(
                status_code=409,
                detail="stored trend run is unavailable; state was not changed",
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail=f"invalid stored trend run id: {exc}"
            ) from exc
        trend_errors = validate_trend_brief_against_run(brief, trend_run)
        if trend_errors:
            raise HTTPException(
                status_code=409,
                detail=f"trend evidence no longer matches the stored run: {'; '.join(trend_errors)}",
            )

    state = WorkflowState(
        brief=brief,
        approval=existing_approval,
        errors=list(current.get("errors", [])),
        next_step=current.get("next_step", "human_review"),
        requires_human_review=bool(current.get("requires_human_review", True)),
        evidence_records=list(current.get("evidence_records", [])),
        approved_media_assets=list(approved_media_assets),
        scheduler_payload=dict(current.get("scheduler_payload", {})),
    )
    result = MarketingWorkflow(
        load_policy(), evidence_vault=load_evidence_vault()
    ).resume_after_review(state, approval)
    result_dict = dict(current)
    result_dict.update(result.to_dict())
    result_dict["approval_audit"] = {
        "reviewer_display": reviewer,
        **identity_audit_fields(),
    }
    store.save_state(result_dict, expected_revision=current_revision)
    store.append_event(
        "approval",
        {"content_id": content_id, "result": result_dict, **identity_audit_fields()},
    )
    return {"status": "reviewed", "content_id": content_id, "state": result_dict}


@app.post("/workflows/comfyui-brief")
def comfyui_brief(payload: dict[str, Any]) -> dict[str, Any]:
    brief = {
        "campaign": payload.get("campaign", "K5"),
        "channel": payload.get("channel", "LinkedIn"),
        "format": payload.get("format", "app_demo_thumbnail"),
        "headline": payload.get("headline", "Proof beats promises"),
        "proof_asset_refs": payload.get("proof_asset_refs", []),
        "output_size": payload.get("output_size", "1080x1350"),
        "review_required": True,
        "submit_to_comfyui": False,
        "rules": [
            "Use approved proof assets only",
            "Do not invent customer screenshots, people, or claims",
            "Human visual approval required before public use",
        ],
    }
    JsonStore().append_event("comfyui_brief", brief)
    return {"status": "draft_created", "comfyui_brief": brief}


@app.post("/workflows/content-media-asset")
def register_content_media_asset(payload: dict[str, Any]) -> dict[str, Any]:
    """Attach a human-approved, already uploaded Postiz media asset to content."""

    require_human_actor("media approval")
    store = JsonStore()
    try:
        content_id = validate_identifier(
            required_text(payload, "content_id", max_length=128),
            field="content_id",
        )
        asset_id = validate_identifier(
            required_text(payload, "asset_id", max_length=128),
            field="asset_id",
        )
        media_type = required_text(payload, "media_type", max_length=16).casefold()
        if media_type not in {"image", "video"}:
            raise ValueError("media_type must be image or video")
        postiz_media_id = required_text(payload, "postiz_media_id", max_length=256)
        postiz_path = required_text(payload, "postiz_path", max_length=2000)
        parsed_path = urlparse(postiz_path)
        if (
            parsed_path.scheme not in {"http", "https"}
            or not parsed_path.hostname
            or parsed_path.username is not None
            or parsed_path.password is not None
        ):
            raise ValueError(
                "postiz_path must be an absolute HTTP(S) URL without user information"
            )
        import os

        media_origin = os.environ.get("POSTIZ_MEDIA_ORIGIN", "").strip().rstrip("/")
        if not media_origin:
            raise ValueError(
                "POSTIZ_MEDIA_ORIGIN must be configured before media evidence can be registered"
            )
        parsed_origin = urlparse(media_origin)
        if (
            parsed_origin.scheme not in {"http", "https"}
            or not parsed_origin.hostname
            or parsed_origin.username is not None
            or parsed_origin.password is not None
            or parsed_origin.path not in {"", "/"}
            or parsed_origin.params
            or parsed_origin.query
            or parsed_origin.fragment
        ):
            raise ValueError(
                "POSTIZ_MEDIA_ORIGIN must be a trusted HTTP(S) origin without a path or user information"
            )
        if (parsed_path.scheme.casefold(), parsed_path.netloc.casefold()) != (
            parsed_origin.scheme.casefold(),
            parsed_origin.netloc.casefold(),
        ):
            raise ValueError("postiz_path must use the configured POSTIZ_MEDIA_ORIGIN")
        sha256 = required_text(payload, "sha256", max_length=64).casefold()
        if len(sha256) != 64 or any(
            character not in "0123456789abcdef" for character in sha256
        ):
            raise ValueError("sha256 must be a 64-character hexadecimal digest")
        reviewer = required_text(payload, "reviewer", max_length=200)
        approved_at = normalized_timestamp(
            payload.get("approved_at"), field="approved_at"
        )
        if aware_timestamp(approved_at, field="approved_at") > datetime.now(
            timezone.utc
        ) + timedelta(minutes=5):
            raise ValueError("approved_at cannot be in the future")
        source_ref = required_text(payload, "source_ref", max_length=1000)
        verification_method = required_text(
            payload, "verification_method", max_length=64
        ).casefold()
        if verification_method != "operator_postiz_ui":
            raise ValueError("verification_method must be operator_postiz_ui")
        consent_refs_raw = payload.get("consent_refs", [])
        if not isinstance(consent_refs_raw, list):
            raise ValueError("consent_refs must be an array")
        consent_refs = [
            str(item).strip()[:500] for item in consent_refs_raw if str(item).strip()
        ]
        preview_ref = required_text(payload, "preview_ref", max_length=1000)
        brand_check_passed = strict_bool(
            payload.get("brand_check_passed"), field="brand_check_passed"
        )
        fact_check_passed = strict_bool(
            payload.get("fact_check_passed"), field="fact_check_passed"
        )
        privacy_check_passed = strict_bool(
            payload.get("privacy_check_passed"), field="privacy_check_passed"
        )
        ai_disclosure_check_passed = strict_bool(
            payload.get("ai_disclosure_check_passed"),
            field="ai_disclosure_check_passed",
        )
        if not all(
            (
                brand_check_passed,
                fact_check_passed,
                privacy_check_passed,
                ai_disclosure_check_passed,
            )
        ):
            raise ValueError(
                "all media brand, fact, privacy, and AI-disclosure checks must pass"
            )
        provider_verification = verify_postiz_media_url(
            postiz_path,
            expected_sha256=sha256,
            media_type=media_type,
        )
        supersedes_asset_id = str(payload.get("supersedes_asset_id", "")).strip()
        if supersedes_asset_id:
            supersedes_asset_id = validate_identifier(
                supersedes_asset_id,
                field="supersedes_asset_id",
            )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    asset = {
        "asset_id": asset_id,
        "media_type": media_type,
        "postiz_media_id": postiz_media_id,
        "postiz_path": postiz_path,
        "sha256": sha256,
        "reviewer": reviewer,
        "approved_at": approved_at,
        "source_ref": source_ref,
        "verification_method": verification_method,
        "checksum_scope": "approved_local_artifact_and_exact_postiz_path",
        "consent_refs": consent_refs,
        "preview_ref": preview_ref,
        "brand_check_passed": brand_check_passed,
        "fact_check_passed": fact_check_passed,
        "privacy_check_passed": privacy_check_passed,
        "ai_disclosure_check_passed": ai_disclosure_check_passed,
        "supersedes_asset_id": supersedes_asset_id,
        "status": "approved",
        **provider_verification,
        **identity_audit_fields(),
    }
    fingerprint = request_fingerprint(asset)
    asset["request_fingerprint"] = fingerprint
    with store.state_lock(content_id):
        try:
            state = store.load_state(content_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        revision = JsonStore.state_revision(state)
        brief = state.get("brief", {})
        people_evidence_required = isinstance(
            brief, dict
        ) and "people_consent_and_real_assets_required" in brief.get("risk_flags", [])
        status = brief.get("status") if isinstance(brief, dict) else ""
        media_registration_allowed = (
            status == ContentStatus.READY_TO_SCHEDULE.value
            or (
                status == ContentStatus.NEEDS_HUMAN_REVIEW.value
                and people_evidence_required
            )
        )
        if not media_registration_allowed:
            raise HTTPException(
                status_code=409,
                detail=(
                    "media can be attached only to approved content awaiting Postiz handoff, "
                    "or to K4 content awaiting consent-gated human review"
                ),
            )
        if people_evidence_required and not consent_refs:
            raise HTTPException(
                status_code=422,
                detail="consent_refs are required for media depicting K4 people",
            )
        assets = list(state.get("approved_media_assets", []))
        for existing in assets:
            if not isinstance(existing, dict) or existing.get("asset_id") != asset_id:
                continue
            if existing.get("request_fingerprint") == fingerprint:
                store.append_event_once(
                    "content_media_asset",
                    media_audit_event_id(content_id, asset_id, fingerprint),
                    {"content_id": content_id, "asset": existing},
                )
                return {
                    "status": "approved",
                    "content_id": content_id,
                    "asset": JsonStore.project_media_asset_verification(existing),
                    "idempotent": True,
                }
            raise HTTPException(
                status_code=409,
                detail="asset_id already exists with different media evidence",
            )
        if live_postiz_handoff_started(store, content_id):
            raise HTTPException(
                status_code=409,
                detail="media assets are frozen after a live Postiz handoff starts; reconcile that route instead",
            )
        active_same_type = [
            existing
            for existing in assets
            if isinstance(existing, dict)
            and existing.get("status") == "approved"
            and existing.get("media_type") == media_type
        ]
        if len(active_same_type) > 1:
            raise HTTPException(
                status_code=409,
                detail="stored media state has multiple active assets of the same type; repair it before replacement",
            )
        if active_same_type:
            superseded = active_same_type[0]
            if supersedes_asset_id != superseded.get("asset_id"):
                raise HTTPException(
                    status_code=409,
                    detail="supersedes_asset_id must identify the current active asset of this media type",
                )
            try:
                superseded_approved_at = aware_timestamp(
                    superseded.get("approved_at"),
                    field="superseded approved_at",
                )
            except ValueError as exc:
                raise HTTPException(
                    status_code=409,
                    detail="the current active asset has invalid approval chronology",
                ) from exc
            if (
                aware_timestamp(approved_at, field="approved_at")
                < superseded_approved_at
            ):
                raise HTTPException(
                    status_code=422,
                    detail="replacement approved_at cannot be before the current asset approval",
                )
            superseded["status"] = "superseded"
            superseded["superseded_by"] = asset_id
            superseded["superseded_at"] = approved_at
            superseded["superseded_by_reviewer"] = reviewer
        elif supersedes_asset_id:
            raise HTTPException(
                status_code=409,
                detail="supersedes_asset_id was provided but no active asset of this media type exists",
            )
        assets.append(asset)
        state["approved_media_assets"] = assets
        try:
            store.save_state(state, expected_revision=revision)
        except StateRevisionConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        store.append_event_once(
            "content_media_asset",
            media_audit_event_id(content_id, asset_id, fingerprint),
            {"content_id": content_id, "asset": asset},
        )
    return {
        "status": "approved",
        "content_id": content_id,
        "asset": JsonStore.project_media_asset_verification(asset),
        "idempotent": False,
    }


@app.post("/workflows/content-media-asset/revoke")
def revoke_content_media_asset(payload: dict[str, Any]) -> dict[str, Any]:
    require_human_actor("media revocation")
    store = JsonStore()
    try:
        content_id = validate_identifier(
            required_text(payload, "content_id", max_length=128),
            field="content_id",
        )
        asset_id = validate_identifier(
            required_text(payload, "asset_id", max_length=128),
            field="asset_id",
        )
        reviewer = required_text(payload, "reviewer", max_length=200)
        reason = required_text(payload, "reason", max_length=1000)
        revoked_at = normalized_timestamp(payload.get("revoked_at"), field="revoked_at")
        if aware_timestamp(revoked_at, field="revoked_at") > datetime.now(
            timezone.utc
        ) + timedelta(minutes=5):
            raise ValueError("revoked_at cannot be in the future")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    revocation_identity = identity_audit_fields()
    fingerprint = request_fingerprint(
        {
            "content_id": content_id,
            "asset_id": asset_id,
            "reviewer": reviewer,
            "reason": reason,
            "revoked_at": revoked_at,
            **revocation_identity,
        }
    )
    with store.state_lock(content_id):
        try:
            state = store.load_state(content_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        revision = JsonStore.state_revision(state)
        assets = list(state.get("approved_media_assets", []))
        target = next(
            (
                asset
                for asset in assets
                if isinstance(asset, dict) and asset.get("asset_id") == asset_id
            ),
            None,
        )
        if target is None:
            raise HTTPException(
                status_code=404, detail=f"media asset not found: {asset_id}"
            )
        try:
            approved_time = aware_timestamp(
                target.get("approved_at"), field="asset approved_at"
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=409,
                detail="the active media asset has invalid approval chronology",
            ) from exc
        if aware_timestamp(revoked_at, field="revoked_at") < approved_time:
            raise HTTPException(
                status_code=422,
                detail="revoked_at cannot be before the asset approval",
            )
        existing_revoke = target.get("revocation", {})
        if (
            isinstance(existing_revoke, dict)
            and existing_revoke.get("request_fingerprint") == fingerprint
        ):
            store.append_event_once(
                "content_media_asset_revoke",
                media_audit_event_id(content_id, asset_id, fingerprint),
                {"content_id": content_id, "asset_id": asset_id, **existing_revoke},
            )
            return {
                "status": "revoked",
                "content_id": content_id,
                "asset": JsonStore.project_media_asset_verification(target),
                "idempotent": True,
            }
        if target.get("status") != "approved":
            raise HTTPException(
                status_code=409, detail="only an active approved asset can be revoked"
            )
        if live_postiz_handoff_started(store, content_id):
            raise HTTPException(
                status_code=409,
                detail="media assets are frozen after a live Postiz handoff starts; reconcile that route instead",
            )
        revocation = {
            "reviewer": reviewer,
            "reason": reason,
            "revoked_at": revoked_at,
            "request_fingerprint": fingerprint,
            **revocation_identity,
        }
        target["status"] = "revoked"
        target["revocation"] = revocation
        state["approved_media_assets"] = assets
        try:
            store.save_state(state, expected_revision=revision)
        except StateRevisionConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        store.append_event_once(
            "content_media_asset_revoke",
            media_audit_event_id(content_id, asset_id, fingerprint),
            {"content_id": content_id, "asset_id": asset_id, **revocation},
        )
    return {
        "status": "revoked",
        "content_id": content_id,
        "asset": JsonStore.project_media_asset_verification(target),
        "idempotent": False,
    }


@app.get("/integrations/status")
def integrations_status() -> dict[str, Any]:
    import os

    n8n = os.environ.get("N8N_BASE_URL", "http://core-n8n:5678")
    comfyui = os.environ.get("COMFYUI_BASE_URL", "http://host.docker.internal:8188")
    ollama = os.environ.get("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
    local_model = os.environ.get("LOCAL_MODEL_NAME", "")
    local_openai = os.environ.get(
        "LOCAL_OPENAI_BASE_URL", "http://host.docker.internal:11434/v1"
    )
    local_openai_api_key = os.environ.get("LOCAL_OPENAI_API_KEY", "ollama")
    local_openai_model = os.environ.get("LOCAL_OPENAI_MODEL_NAME", "") or local_model
    litellm = os.environ.get("LITELLM_BASE_URL", "http://host.docker.internal:4000")
    opa = os.environ.get("OPA_BASE_URL", "http://host.docker.internal:8181")
    searxng = os.environ.get("SEARXNG_BASE_URL", "http://host.docker.internal:8090")
    firecrawl = os.environ.get("FIRECRAWL_BASE_URL", "https://api.firecrawl.dev/v2")
    firecrawl_api_key = os.environ.get("FIRECRAWL_API_KEY", "")
    qdrant = os.environ.get("QDRANT_BASE_URL", "http://host.docker.internal:6333")
    prometheus = os.environ.get(
        "PROMETHEUS_BASE_URL", "http://host.docker.internal:9091"
    )
    grafana = os.environ.get("GRAFANA_BASE_URL", "http://host.docker.internal:3030")
    postiz = os.environ.get("POSTIZ_BASE_URL", "http://wmc-postiz:5000")
    twenty = os.environ.get("TWENTY_BASE_URL", "http://wmc-twenty-server:3000")
    mautic = os.environ.get("MAUTIC_BASE_URL", "http://wmc-mautic-web:80")
    postiz_endpoint = os.environ.get("POSTIZ_CREATE_DRAFT_PATH", "")
    postiz_api_key = os.environ.get(
        "POSTIZ_API_KEY", os.environ.get("POSTIZ_API_TOKEN", "")
    )
    postiz_contract_verified = os.environ.get(
        "POSTIZ_CONTRACT_VERIFIED", "false"
    ).strip().lower() in {"1", "true", "yes", "on"}
    twenty_endpoint = os.environ.get("TWENTY_CREATE_CONTACT_PATH", "")
    twenty_api_key = os.environ.get(
        "TWENTY_API_KEY", os.environ.get("TWENTY_API_TOKEN", "")
    )
    twenty_contract_verified = os.environ.get(
        "TWENTY_CONTRACT_VERIFIED", "false"
    ).strip().lower() in {"1", "true", "yes", "on"}
    mautic_endpoint = os.environ.get("MAUTIC_CREATE_CONTACT_PATH", "")
    mautic_api_key = os.environ.get(
        "MAUTIC_API_KEY", os.environ.get("MAUTIC_API_TOKEN", "")
    )
    mautic_contract_verified = os.environ.get(
        "MAUTIC_CONTRACT_VERIFIED", "false"
    ).strip().lower() in {"1", "true", "yes", "on"}
    kimi = os.environ.get(
        "KIMI_BASE_URL",
        os.environ.get("CLOUD_OPENAI_BASE_URL", "https://api.moonshot.ai/v1"),
    )
    kimi_api_key = os.environ.get(
        "KIMI_API_KEY", os.environ.get("CLOUD_OPENAI_API_KEY", "")
    )
    kimi_model = os.environ.get(
        "KIMI_MODEL_NAME", os.environ.get("CLOUD_MODEL_NAME", "")
    )
    allow_cloud_fallback = os.environ.get(
        "MARKETING_MACHINE_ALLOW_CLOUD_FALLBACK", "false"
    ).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    kimi_configured = bool(kimi.strip() and kimi_api_key.strip() and kimi_model.strip())

    from concurrent.futures import ThreadPoolExecutor

    required_builders = [
        lambda: check_url("n8n", f"{n8n.rstrip('/')}/healthz", required=True),
        lambda: check_comfyui_generation_readiness(comfyui, required=True),
        lambda: check_ollama_model(ollama, local_model, required=True),
        lambda: check_openai_compatible_models(
            "local_openai",
            local_openai,
            local_openai_api_key,
            local_openai_model,
            required=True,
        ),
    ]
    kimi_status_builder = (
        (lambda: check_openai_compatible_models("kimi", kimi, kimi_api_key, kimi_model))
        if allow_cloud_fallback
        else (
            lambda: disabled_cloud_model_status(
                "kimi",
                configured=kimi_configured,
                model_name=kimi_model,
            )
        )
    )
    optional_builders = [
        lambda: check_url("litellm", f"{litellm.rstrip('/')}/health/readiness"),
        lambda: check_url("opa", f"{opa.rstrip('/')}/health"),
        lambda: check_url("searxng", f"{searxng.rstrip('/')}/"),
        lambda: check_firecrawl_configuration(
            firecrawl,
            firecrawl_api_key,
            allow_unauthenticated_self_hosted=os.environ.get(
                "FIRECRAWL_ALLOW_UNAUTHENTICATED_SELF_HOSTED", "false"
            )
            .strip()
            .lower()
            in {"1", "true", "yes", "on"},
        ),
        lambda: env_configured("GOOGLE_CSE_API_KEY", label="google_search_key"),
        lambda: env_configured("GOOGLE_CSE_ID", label="google_search_engine"),
        lambda: env_configured("REDDIT_BEARER_TOKEN", label="reddit_key"),
        lambda: env_configured(
            "TIKTOK_RESEARCH_CLIENT_TOKEN", label="tiktok_research_key"
        ),
        lambda: env_configured("INSTAGRAM_ACCESS_TOKEN", label="instagram_key"),
        lambda: env_configured(
            "INSTAGRAM_BUSINESS_ACCOUNT_ID", label="instagram_business_account"
        ),
        lambda: check_url("qdrant", f"{qdrant.rstrip('/')}/"),
        lambda: check_url("prometheus", f"{prometheus.rstrip('/')}/-/ready"),
        lambda: check_url("grafana", f"{grafana.rstrip('/')}/api/health"),
        lambda: check_growth_service(
            "postiz",
            postiz,
            probe_path="/api/auth/can-register",
            endpoint_path=postiz_endpoint,
            api_key=postiz_api_key,
            contract_verified=postiz_contract_verified,
        ),
        lambda: check_growth_service(
            "twenty",
            twenty,
            probe_path="/healthz",
            endpoint_path=twenty_endpoint,
            api_key=twenty_api_key,
            contract_verified=twenty_contract_verified,
        ),
        lambda: check_growth_service(
            "mautic",
            mautic,
            probe_path="/",
            endpoint_path=mautic_endpoint,
            api_key=mautic_api_key,
            contract_verified=mautic_contract_verified,
        ),
        kimi_status_builder,
    ]
    with ThreadPoolExecutor(
        max_workers=12, thread_name_prefix="integration-check"
    ) as executor:
        results = list(
            executor.map(
                lambda builder: builder(), [*required_builders, *optional_builders]
            )
        )
    required_checks = results[: len(required_builders)]
    optional_checks = results[len(required_builders) :]
    local_openai_check = required_checks[3]
    store = JsonStore()
    recent_states = store.list_states(limit=100, include_demo=False)
    all_successful_generations = [
        item
        for item in recent_states
        if isinstance(item.get("generation"), dict)
        and item["generation"].get("status") == "ai_generated"
    ]
    successful_generations = [
        item
        for item in all_successful_generations
        if item["generation"].get("provider") == "local_qwen"
    ]
    if successful_generations:
        latest = successful_generations[0]
        local_openai_check["used_successfully"] = True
        local_openai_check["last_success_at"] = latest.get("updated_at", "")
        local_openai_check["last_generation_model"] = latest.get("generation", {}).get(
            "model", ""
        )
    successful_kimi_generations = [
        item
        for item in all_successful_generations
        if item["generation"].get("provider") == "kimi_backup"
    ]
    if allow_cloud_fallback and successful_kimi_generations:
        kimi_check = next(
            (item for item in optional_checks if item.get("name") == "kimi"), None
        )
        if kimi_check is not None:
            latest = successful_kimi_generations[0]
            kimi_check["used_successfully"] = True
            kimi_check["last_success_at"] = latest.get("updated_at", "")
            kimi_check["last_generation_model"] = latest.get("generation", {}).get(
                "model", ""
            )
    latest_runs = store.list_trend_runs(limit=20)
    evidence_runs = full_trend_runs(store, limit=20)
    n8n_check = required_checks[0]
    n8n_operator_verified = os.environ.get(
        "MARKETING_MACHINE_N8N_WORKFLOWS_VERIFIED", ""
    ).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    n8n_run = recorded_n8n_execution(
        latest_runs, workflows_verified=n8n_operator_verified
    )
    if n8n_run is not None:
        n8n_check["used_successfully"] = True
        n8n_check["verification_basis"] = "persisted_trend_workflow_execution"
        n8n_check["last_success_at"] = n8n_run.get("run_started_at", "")
        n8n_check["last_execution_id"] = str(n8n_run.get("request_id", ""))
        n8n_check["action"] = "A production workflow execution has been verified."
    elif n8n_operator_verified:
        n8n_check["used_successfully"] = False
        n8n_check["verification_basis"] = "operator_manifest_attested_without_execution"
        n8n_check["last_execution_id"] = ""
        n8n_check["action"] = (
            "The workflow manifest is operator-attested, but no persisted source-backed "
            "n8n execution has been recorded yet."
        )
    successful_adapters = {
        adapter
        for run in latest_runs
        for adapter in run.get("successful_source_adapters", [])
    }
    adapter_aliases = {
        "firecrawl": {"firecrawl", "firecrawl_v2"},
        "searxng": {"searxng"},
        "google_search_key": {"google_cse"},
        "google_search_engine": {"google_cse"},
        "reddit_key": {"reddit_api"},
        "tiktok_research_key": {"tiktok_research_api"},
    }
    for check in optional_checks:
        matching_adapters = adapter_aliases.get(
            str(check.get("name")), {str(check.get("name"))}
        )
        used_adapters = successful_adapters & matching_adapters
        if used_adapters:
            check["used_successfully"] = True
            check["last_success_at"] = next(
                (
                    run.get("run_started_at", "")
                    for run in latest_runs
                    if set(run.get("successful_source_adapters", [])) & used_adapters
                ),
                "",
            )
    outbox_items = store.list_outbox(limit=100_000)
    if not isinstance(outbox_items, list):
        outbox_items = []
    confirmed_routes = [
        route
        for route in outbox_items
        if route.get("status") == "confirmed" and route.get("external_reference")
    ]
    for check in optional_checks:
        name = str(check.get("name", ""))
        if name not in {"postiz", "twenty", "mautic"}:
            continue
        confirmed = next(
            (route for route in confirmed_routes if route.get("target") == name), None
        )
        if confirmed is None:
            continue
        check["used_successfully"] = True
        check["last_success_at"] = confirmed.get(
            "updated_at", confirmed.get("created_at", "")
        )
        check["verification_basis"] = "provider_confirmed_outbox_reconciliation"
    source_checks = [
        item for item in optional_checks if item.get("name") in adapter_aliases
    ]
    verified_runs = [
        run for run in evidence_runs if trend_run_has_verified_sources(run)
    ]
    optional_checks.append(
        {
            "name": "trend_research",
            "label": "verified trend research",
            "ok": bool(verified_runs),
            "required": False,
            "configured": any(item.get("configured") for item in source_checks),
            "reachable": None,
            "used_successfully": bool(verified_runs),
            "last_success_at": verified_runs[0].get("run_started_at", "")
            if verified_runs
            else "",
            "action": (
                "A source-backed trend was verified in an actual research run."
                if verified_runs
                else "Run research and verify campaign-level trends before claiming research readiness."
            ),
        }
    )
    return {
        "status": "ok" if all(check["ok"] for check in required_checks) else "degraded",
        "required": required_checks,
        "optional": optional_checks,
        "checks": required_checks + optional_checks,
    }


@app.get("/workflows/phase-status")
def phase_status() -> dict[str, Any]:
    import os

    integrations = integrations_status()
    result = build_phase_status(
        integrations=integrations,
        env=os.environ,
        workflows_dir=repo_root() / "deploy" / "n8n" / "workflows",
    )
    result["integrations"] = integrations
    return result


def _project_content_lifecycle_route(
    store: JsonStore,
    route: dict[str, Any],
    event: dict[str, Any],
) -> dict[str, Any]:
    """Repairable projection from the durable state event to outbox/audit views."""

    provider_status = str(event.get("provider_status", ""))
    provider_post_id = str(event.get("provider_post_id", "")).strip()
    routed_reference = str(route.get("external_reference", "")).strip()
    route.update(
        {
            "status": "reconciled_failed"
            if provider_status == "failed"
            else "confirmed",
            "external_reference": provider_post_id or routed_reference,
            "provider_status": provider_status,
            "reconciled_at": event.get("observed_at", ""),
            "reconciliation": {
                "event_id": event.get("event_id", ""),
                "source_ref": event.get("source_ref", ""),
                "verification_method": event.get("verification_method", ""),
            },
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    store.save_outbox(route)
    store.append_event_once(
        "content_lifecycle",
        str(event.get("event_id", "")),
        event,
    )
    return route


@app.post("/workflows/content-lifecycle")
def content_lifecycle(payload: dict[str, Any]) -> dict[str, Any]:
    require_human_actor("operator content lifecycle evidence")
    return _record_content_lifecycle(payload, provider_api_verified=False)


def _record_content_lifecycle(
    payload: dict[str, Any],
    *,
    provider_api_verified: bool,
) -> dict[str, Any]:
    """Ingest a provider-confirmed Postiz lifecycle event monotonically."""

    store = JsonStore()
    try:
        content_id = validate_identifier(
            required_text(payload, "content_id", max_length=128),
            field="content_id",
        )
        event_id = validate_identifier(
            required_text(payload, "event_id", max_length=128),
            field="event_id",
        )
        route_id = validate_identifier(
            required_text(payload, "route_id", max_length=128),
            field="route_id",
        )
        provider = required_text(payload, "provider", max_length=32).casefold()
        provider_status = required_text(
            payload, "provider_status", max_length=32
        ).casefold()
        provider_post_id = str(payload.get("provider_post_id", "")).strip()[:256]
        source_ref = required_text(payload, "source_ref", max_length=1000)
        verification_method = required_text(
            payload, "verification_method", max_length=64
        ).casefold()
        observed_at = normalized_timestamp(
            payload.get("observed_at"), field="observed_at"
        )
        observed_time = aware_timestamp(observed_at, field="observed_at")
        if provider != "postiz":
            raise ValueError("provider must be postiz")
        if provider_status not in PROVIDER_LIFECYCLE_STATUSES:
            raise ValueError(
                "provider_status must be draft_created, scheduled, published, or failed"
            )
        if provider_status != "failed" and not provider_post_id:
            raise ValueError("provider_post_id is required")
        if verification_method not in {"postiz_api", "operator_postiz_ui"}:
            raise ValueError(
                "verification_method must be postiz_api or operator_postiz_ui"
            )
        if verification_method == "postiz_api" and not provider_api_verified:
            raise HTTPException(
                status_code=403,
                detail="postiz_api lifecycle evidence can only be produced by server-side Postiz reconciliation",
            )
        operator = str(payload.get("operator", "")).strip()[:200]
        if verification_method == "operator_postiz_ui" and not operator:
            raise ValueError("operator is required for operator_postiz_ui verification")
        if observed_time > datetime.now(timezone.utc) + timedelta(minutes=5):
            raise ValueError("observed_at cannot be in the future")

        scheduled_for = ""
        published_at = ""
        if provider_status == "scheduled":
            scheduled_for = normalized_timestamp(
                payload.get("scheduled_for"), field="scheduled_for"
            )
        if provider_status == "published":
            published_at = normalized_timestamp(
                payload.get("published_at"), field="published_at"
            )
            if aware_timestamp(
                published_at, field="published_at"
            ) > observed_time + timedelta(minutes=5):
                raise ValueError("published_at cannot be after observed_at")
        provider_reason = str(payload.get("provider_reason", "")).strip()[:1000]
        if provider_status == "failed" and not provider_reason:
            raise ValueError("provider_reason is required for a failed lifecycle event")
        release_url = str(payload.get("release_url", "")).strip()[:2000]
        if release_url and not source_domain(release_url):
            raise ValueError("release_url must be an absolute public HTTP(S) URL")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    normalized_event = {
        "event_id": event_id,
        "content_id": content_id,
        "route_id": route_id,
        "provider": provider,
        "provider_status": provider_status,
        "provider_post_id": provider_post_id,
        "observed_at": observed_at,
        "scheduled_for": scheduled_for,
        "published_at": published_at,
        "release_url": release_url,
        "source_ref": source_ref,
        "verification_method": verification_method,
        "operator": operator,
        "provider_reason": provider_reason,
        **identity_audit_fields(),
    }
    event_fingerprint = request_fingerprint(
        {key: value for key, value in normalized_event.items() if key != "observed_at"}
    )

    # Every operation that needs both projections takes the content lock first
    # and the route lock second. Holding both across the read/modify/write keeps
    # lifecycle ingestion from saving a stale outbox snapshot over a concurrent
    # reconciliation event or pending two-person confirmation.
    with store.state_lock(content_id), store.outbox_lock(route_id):
        try:
            state = store.load_state(content_id)
            state_revision = JsonStore.state_revision(state)
            route = store.load_outbox(route_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        brief = state.get("brief", {})
        if not isinstance(brief, dict):
            raise HTTPException(
                status_code=409, detail="stored content brief is invalid"
            )
        current_status = str(brief.get("status", ""))
        if current_status not in {
            ContentStatus.READY_TO_SCHEDULE.value,
            ContentStatus.SCHEDULED.value,
            ContentStatus.PUBLISHED.value,
        }:
            raise HTTPException(
                status_code=409,
                detail="only approved content can receive Postiz lifecycle events",
            )
        if route.get("kind") != "scheduler_draft" or route.get("target") != "postiz":
            raise HTTPException(
                status_code=409, detail="route is not a Postiz scheduler operation"
            )
        if str(route.get("source_id", "")) != content_id:
            raise HTTPException(
                status_code=409, detail="route does not belong to this content item"
            )
        if route.get("status") not in {
            "sent",
            "delivery_unknown",
            "confirmed",
            "reconciled",
            "reconciled_failed",
        }:
            raise HTTPException(
                status_code=409,
                detail="a dry-run or blocked route cannot receive provider lifecycle events",
            )
        routed_reference = str(route.get("external_reference", "")).strip()
        if (
            routed_reference
            and provider_post_id
            and routed_reference != provider_post_id
        ):
            raise HTTPException(
                status_code=409,
                detail="provider_post_id conflicts with the routed Postiz operation",
            )

        lifecycle = (
            dict(state.get("lifecycle", {}))
            if isinstance(state.get("lifecycle"), dict)
            else {}
        )
        events = (
            list(lifecycle.get("events", []))
            if isinstance(lifecycle.get("events"), list)
            else []
        )
        for existing in events:
            if not isinstance(existing, dict) or existing.get("event_id") != event_id:
                continue
            if existing.get("request_fingerprint") == event_fingerprint:
                _project_content_lifecycle_route(store, route, existing)
                return {
                    "status": "recorded",
                    "content_id": content_id,
                    "provider_status": lifecycle.get("provider_status", ""),
                    "state": state,
                    "idempotent": True,
                }
            raise HTTPException(
                status_code=409,
                detail="lifecycle event_id already exists with different data",
            )

        existing_provider_id = str(lifecycle.get("provider_post_id", "")).strip()
        if (
            existing_provider_id
            and provider_post_id
            and existing_provider_id != provider_post_id
        ):
            raise HTTPException(
                status_code=409,
                detail="provider_post_id cannot change during a content lifecycle",
            )

        current_rank = {
            ContentStatus.READY_TO_SCHEDULE.value: 0,
            ContentStatus.SCHEDULED.value: 1,
            ContentStatus.PUBLISHED.value: 2,
        }[current_status]
        target_rank = {
            "draft_created": 0,
            "scheduled": 1,
            "published": 2,
            "failed": current_rank,
        }[provider_status]
        if target_rank < current_rank or (
            current_status == ContentStatus.PUBLISHED.value
            and provider_status != "published"
        ):
            raise HTTPException(
                status_code=409,
                detail="provider lifecycle events cannot regress published state",
            )

        event = {**normalized_event, "request_fingerprint": event_fingerprint}
        events.append(event)
        lifecycle.update(
            {
                "provider": "postiz",
                "route_id": route_id,
                "provider_status": provider_status,
                "last_observed_at": observed_at,
                "source_ref": source_ref,
                "verification_method": verification_method,
                "operator": operator,
                "provider_reason": provider_reason,
                "events": events,
            }
        )
        if provider_post_id:
            lifecycle["provider_post_id"] = provider_post_id
        if scheduled_for:
            lifecycle["scheduled_for"] = scheduled_for
        if published_at:
            lifecycle["published_at"] = published_at
        if release_url:
            lifecycle["release_url"] = release_url

        if provider_status == "draft_created":
            state["next_step"] = "postiz_final_approval"
            state["requires_human_review"] = True
        elif provider_status == "scheduled":
            brief["status"] = ContentStatus.SCHEDULED.value
            state["next_step"] = "awaiting_publication"
            state["requires_human_review"] = False
        elif provider_status == "published":
            brief["status"] = ContentStatus.PUBLISHED.value
            state["next_step"] = "analytics"
            state["requires_human_review"] = False
        else:
            state["next_step"] = "reconcile_provider"
            state["requires_human_review"] = True
        brief["updated_at"] = datetime.now(timezone.utc).isoformat()
        state["brief"] = brief
        state["lifecycle"] = lifecycle

        try:
            store.save_state(state, expected_revision=state_revision)
        except StateRevisionConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        _project_content_lifecycle_route(store, route, event)

    return {
        "status": "recorded",
        "content_id": content_id,
        "provider_status": provider_status,
        "state": state,
        "idempotent": False,
    }


@app.post("/workflows/outbox/{route_id}/reconcile")
def reconcile_outbox_delivery(route_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    require_human_actor("operator outbox reconciliation")
    return _record_outbox_reconciliation(
        route_id,
        payload,
        provider_api_verified=False,
    )


def _record_outbox_reconciliation(
    route_id: str,
    payload: dict[str, Any],
    *,
    provider_api_verified: bool,
) -> dict[str, Any]:
    """Resolve an ambiguous external delivery using auditable provider evidence."""

    store = JsonStore()
    try:
        route_id = validate_identifier(route_id, field="route_id")
        event_id = validate_identifier(
            required_text(payload, "event_id", max_length=128),
            field="event_id",
        )
        outcome = required_text(payload, "outcome", max_length=64).casefold()
        if outcome not in {
            "confirmed_created",
            "confirmed_not_created",
            "authorized_retry",
        }:
            raise ValueError(
                "outcome must be confirmed_created, confirmed_not_created, or authorized_retry"
            )
        source_ref = required_text(payload, "source_ref", max_length=1000)
        verification_method = required_text(
            payload, "verification_method", max_length=64
        ).casefold()
        if verification_method not in {"provider_api", "operator_provider_ui"}:
            raise ValueError(
                "verification_method must be provider_api or operator_provider_ui"
            )
        if verification_method == "provider_api" and not provider_api_verified:
            raise HTTPException(
                status_code=403,
                detail="provider_api reconciliation can only be produced by a server-side provider read",
            )
        operator = str(payload.get("operator", "")).strip()[:200]
        if verification_method == "operator_provider_ui" and not operator:
            raise ValueError(
                "operator is required for operator_provider_ui verification"
            )
        second_operator = str(payload.get("second_operator", "")).strip()[:200]
        authenticated_actor = current_authenticated_actor()
        if (
            outcome == "confirmed_not_created"
            and verification_method == "operator_provider_ui"
            and not authenticated_actor
            and (
                not second_operator or second_operator.casefold() == operator.casefold()
            )
        ):
            raise ValueError(
                "confirmed_not_created requires a distinct second_operator only in local optional mode"
            )
        observed_at = normalized_timestamp(
            payload.get("observed_at"), field="observed_at"
        )
        if aware_timestamp(observed_at, field="observed_at") > datetime.now(
            timezone.utc
        ) + timedelta(minutes=5):
            raise ValueError("observed_at cannot be in the future")
        provider_post_id = str(payload.get("provider_post_id", "")).strip()[:256]
        if outcome == "confirmed_created" and not provider_post_id:
            raise ValueError("provider_post_id is required for confirmed_created")
        if (
            outcome in {"confirmed_not_created", "authorized_retry"}
            and provider_post_id
        ):
            raise ValueError(f"provider_post_id must be empty for {outcome}")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    normalized = {
        "event_id": event_id,
        "route_id": route_id,
        "outcome": outcome,
        "provider_post_id": provider_post_id,
        "source_ref": source_ref,
        "verification_method": verification_method,
        "operator": operator,
        # Free-text names are display/audit fields only. They never satisfy a
        # production two-person control.
        "second_operator": second_operator if not authenticated_actor else "",
        "observed_at": observed_at,
        **identity_audit_fields(),
    }
    evidence_fingerprint = request_fingerprint(
        {
            "route_id": route_id,
            "outcome": outcome,
            "provider_post_id": provider_post_id,
            "source_ref": source_ref,
            "verification_method": verification_method,
        }
    )
    normalized["evidence_fingerprint"] = evidence_fingerprint
    fingerprint = request_fingerprint(normalized)
    with store.outbox_lock(route_id):
        try:
            route = store.load_outbox(route_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        events = list(route.get("reconciliation_events", []))
        for existing in events:
            if not isinstance(existing, dict) or existing.get("event_id") != event_id:
                continue
            if (
                existing.get("request_fingerprint") == fingerprint
                or existing.get("evidence_fingerprint") == evidence_fingerprint
            ):
                return {"status": "reconciled", "route": route, "idempotent": True}
            raise HTTPException(
                status_code=409,
                detail="reconciliation event_id already exists with different data",
            )

        current_status = str(route.get("status", ""))
        if outcome == "confirmed_not_created":
            if current_status not in {"sending", "delivery_unknown"}:
                raise HTTPException(
                    status_code=409,
                    detail="confirmed_not_created can resolve only a sending or delivery_unknown operation",
                )
            if route.get("external_reference"):
                raise HTTPException(
                    status_code=409, detail="route already has a provider reference"
                )
        elif outcome == "authorized_retry":
            if current_status != "failed_safe_to_retry":
                raise HTTPException(
                    status_code=409,
                    detail="authorized_retry applies only to a definite provider rejection",
                )
        elif current_status not in {
            "sending",
            "delivery_unknown",
            "sent",
            "failed_safe_to_retry",
            "confirmed",
        }:
            raise HTTPException(
                status_code=409,
                detail="route has no external delivery attempt to reconcile",
            )

        requires_two_authenticated_actors = bool(
            outcome == "confirmed_not_created"
            and verification_method == "operator_provider_ui"
            and authenticated_actor
        )
        if requires_two_authenticated_actors:
            pending = route.get("pending_operator_confirmation", {})
            if not isinstance(pending, dict):
                pending = {}
            now = datetime.now(timezone.utc)
            pending_recorded_at: datetime | None = None
            if pending.get("recorded_at"):
                try:
                    pending_recorded_at = aware_timestamp(
                        pending.get("recorded_at"),
                        field="pending_operator_confirmation.recorded_at",
                    )
                except ValueError:
                    pending_recorded_at = None
            if pending_recorded_at and now > pending_recorded_at + timedelta(hours=24):
                pending = {}

            if pending:
                if (
                    pending.get("event_id") != event_id
                    or pending.get("evidence_fingerprint") != evidence_fingerprint
                ):
                    raise HTTPException(
                        status_code=409,
                        detail="a different operator reconciliation is awaiting independent confirmation",
                    )
                first_actor = str(pending.get("first_authenticated_actor", ""))
                if first_actor.casefold() == authenticated_actor.casefold():
                    return {
                        "status": "pending_second_confirmation",
                        "route": route,
                        "confirmation": {
                            "event_id": event_id,
                            "evidence_fingerprint": evidence_fingerprint,
                            "first_authenticated_actor": first_actor,
                            "requires_distinct_actor": True,
                        },
                        "idempotent": True,
                    }
                normalized.update(
                    {
                        "first_authenticated_actor": first_actor,
                        "second_authenticated_actor": authenticated_actor,
                        "first_operator_display": str(
                            pending.get("first_operator_display", "")
                        ),
                        "second_operator_display": operator,
                    }
                )
                route.pop("pending_operator_confirmation", None)
                fingerprint = request_fingerprint(normalized)
            else:
                pending = {
                    "event_id": event_id,
                    "evidence_fingerprint": evidence_fingerprint,
                    "first_authenticated_actor": authenticated_actor,
                    "first_operator_display": operator,
                    "source_ref": source_ref,
                    "verification_method": verification_method,
                    "observed_at": observed_at,
                    "recorded_at": now.isoformat(),
                    "authenticated_request_fingerprint": identity_audit_fields().get(
                        "authenticated_request_fingerprint",
                        "",
                    ),
                }
                route["pending_operator_confirmation"] = pending
                route["updated_at"] = now.isoformat()
                store.save_outbox(route)
                store.append_event(
                    "outbox_reconciliation_pending",
                    {
                        "route_id": route_id,
                        **pending,
                    },
                )
                return {
                    "status": "pending_second_confirmation",
                    "route": route,
                    "confirmation": {
                        "event_id": event_id,
                        "evidence_fingerprint": evidence_fingerprint,
                        "first_authenticated_actor": authenticated_actor,
                        "requires_distinct_actor": True,
                    },
                    "idempotent": False,
                }

        event = {**normalized, "request_fingerprint": fingerprint}
        events.append(event)
        route["reconciliation_events"] = events
        route["reconciled_at"] = observed_at
        route["updated_at"] = datetime.now(timezone.utc).isoformat()
        if outcome == "confirmed_not_created":
            route["status"] = "confirmed_not_created"
            route["retry_authorized"] = True
            route["reason"] = (
                "provider evidence confirms no external object exists; one governed retry is allowed"
            )
        elif outcome == "confirmed_created":
            route["status"] = "confirmed"
            route["retry_authorized"] = False
            route["external_reference"] = provider_post_id
            route["reason"] = "provider evidence confirms the external object exists"
        else:
            route["retry_authorized"] = True
            route["reason"] = (
                "named operator authorized one retry after reviewing the definite provider rejection"
            )
        route.pop("pending_operator_confirmation", None)
        store.save_outbox(route)
        store.append_event("outbox_reconciliation", event)
    return {"status": "reconciled", "route": route, "idempotent": False}


@app.post("/workflows/reconcile-postiz")
def reconcile_postiz(payload: dict[str, Any]) -> dict[str, Any]:
    """Read Postiz and reconcile a durable outbox operation without blind resend."""

    import os

    store = JsonStore()
    try:
        route_id = validate_identifier(
            required_text(payload, "route_id", max_length=128),
            field="route_id",
        )
        route = store.load_outbox(route_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if route.get("kind") != "scheduler_draft" or route.get("target") != "postiz":
        raise HTTPException(
            status_code=409, detail="route is not a Postiz scheduler operation"
        )
    if route.get("status") not in {"sent", "delivery_unknown", "confirmed"}:
        raise HTTPException(
            status_code=409,
            detail="only an attempted Postiz operation can be reconciled",
        )

    base_url = os.environ.get("POSTIZ_BASE_URL", "").strip()
    list_path = os.environ.get("POSTIZ_LIST_POSTS_PATH", "/api/public/v1/posts").strip()
    api_key = os.environ.get(
        "POSTIZ_API_KEY", os.environ.get("POSTIZ_API_TOKEN", "")
    ).strip()
    contract_verified = os.environ.get(
        "POSTIZ_CONTRACT_VERIFIED", "false"
    ).strip().casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if not (base_url and list_path and api_key and contract_verified):
        raise HTTPException(
            status_code=503,
            detail="Postiz reconciliation requires configured base URL, list path, API key, and verified contract",
        )

    try:
        created_at = aware_timestamp(route.get("created_at"), field="route.created_at")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    observed = datetime.now(timezone.utc)
    query = urlencode(
        {
            "startDate": (created_at - timedelta(days=1)).isoformat(),
            "endDate": (observed + timedelta(days=1)).isoformat(),
        }
    )
    url = f"{base_url.rstrip('/')}/{list_path.lstrip('/')}?{query}"
    try:
        response = get_json(url, api_key)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=502, detail=f"Postiz reconciliation read failed: {exc}"
        ) from exc

    posts = response.get("posts", [])
    if not isinstance(posts, list):
        raise HTTPException(
            status_code=502, detail="Postiz list response did not contain a posts array"
        )
    expected_reference = str(route.get("external_reference", "")).strip()
    provider_payload = route.get("payload", {})
    expected_content = ""
    expected_integration = ""
    try:
        expected_post = provider_payload["posts"][0]
        expected_content = str(expected_post["value"][0]["content"])
        expected_integration = str(expected_post["integration"]["id"])
    except (KeyError, IndexError, TypeError):
        pass

    candidates: list[dict[str, Any]] = []
    for item in posts:
        if not isinstance(item, dict):
            continue
        if expected_reference and str(item.get("id", "")) == expected_reference:
            candidates.append(item)
            continue
        integration = item.get("integration", {})
        integration_id = (
            str(integration.get("id", "")) if isinstance(integration, dict) else ""
        )
        if (
            not expected_reference
            and expected_content
            and str(item.get("content", "")) == expected_content
            and (not expected_integration or integration_id == expected_integration)
        ):
            candidates.append(item)
    unique_candidates = {
        str(item.get("id", "")): item for item in candidates if item.get("id")
    }
    snapshot_hash = hashlib.sha256(
        json.dumps(
            response, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    if not unique_candidates:
        if route.get("status") not in {"sending", "delivery_unknown"}:
            raise HTTPException(
                status_code=409, detail="Postiz reconciliation found no matching post"
            )
        if observed < created_at + timedelta(minutes=5):
            raise HTTPException(
                status_code=409,
                detail="Postiz may still be indexing the operation; reconcile again after five minutes",
            )
        with store.outbox_lock(route_id):
            latest_route = store.load_outbox(route_id)
            observations = list(latest_route.get("absence_observations", []))
            previous_time: datetime | None = None
            if observations:
                try:
                    previous_time = aware_timestamp(
                        observations[-1].get("observed_at"),
                        field="absence_observation.observed_at",
                    )
                except ValueError:
                    previous_time = None
            observation = {
                "snapshot_sha256": snapshot_hash,
                "observed_at": observed.isoformat(),
                "source_ref": f"postiz:list-posts:sha256:{snapshot_hash}",
            }
            observations.append(observation)
            latest_route["absence_observations"] = observations[-10:]
            latest_route["updated_at"] = observed.isoformat()
            store.save_outbox(latest_route)

        if previous_time is None or observed < previous_time + timedelta(minutes=2):
            return {
                "status": "reconciliation_pending",
                "route_id": route_id,
                "provider_status": "absence_unconfirmed",
                "provider_post_id": "",
                "next_check_after": (observed + timedelta(minutes=2)).isoformat(),
                "clean_read_count": len(observations),
                "writes_performed": False,
            }

        pair_hash = hashlib.sha256(
            f"{observations[-2].get('snapshot_sha256', '')}:{snapshot_hash}".encode(
                "utf-8"
            )
        ).hexdigest()
        resolution = _record_outbox_reconciliation(
            route_id,
            {
                "event_id": f"postiz-not-created-{pair_hash[:20]}",
                "outcome": "confirmed_not_created",
                "source_ref": f"postiz:two-list-checks:sha256:{pair_hash}",
                "verification_method": "provider_api",
                "observed_at": observed.isoformat(),
            },
            provider_api_verified=True,
        )
        return {
            "status": "reconciled",
            "route_id": route_id,
            "provider_status": "confirmed_not_created",
            "provider_post_id": "",
            "outbox": resolution,
            "writes_performed": False,
        }
    if len(unique_candidates) != 1:
        raise HTTPException(
            status_code=409,
            detail="Postiz reconciliation found multiple matching posts; operator review is required",
        )
    matched = next(iter(unique_candidates.values()))
    post_id = str(matched.get("id", "")).strip()
    release_url = str(matched.get("releaseURL", "")).strip()
    publish_date = str(matched.get("publishDate", "")).strip()
    provider_status = "published" if release_url else "draft_created"
    if provider_status == "published" and not publish_date:
        raise HTTPException(
            status_code=502, detail="Postiz published post is missing publishDate"
        )

    event_payload = {
        "event_id": f"postiz-{snapshot_hash[:24]}",
        "content_id": str(route.get("source_id", "")),
        "route_id": route_id,
        "provider": "postiz",
        "provider_status": provider_status,
        "provider_post_id": post_id,
        "observed_at": observed.isoformat(),
        "source_ref": f"postiz:list-posts:sha256:{snapshot_hash}",
        "verification_method": "postiz_api",
        "release_url": release_url,
    }
    if provider_status == "published":
        event_payload["published_at"] = publish_date
    result = _record_content_lifecycle(event_payload, provider_api_verified=True)
    return {
        "status": "reconciled",
        "route_id": route_id,
        "provider_status": provider_status,
        "provider_post_id": post_id,
        "lifecycle": result,
        "writes_performed": False,
    }


@app.get("/workflows/analytics/due")
def analytics_due(review_window: str = Query(default="72h")) -> dict[str, Any]:
    if review_window not in ANALYTICS_DELAYS:
        raise HTTPException(
            status_code=422, detail="review_window must be 72h, 7d, 14d, or 30d"
        )
    store = JsonStore()
    now = datetime.now(timezone.utc)
    due: list[dict[str, Any]] = []
    for item in store.list_states(limit=100_000, include_demo=False):
        if item.get("status") != ContentStatus.PUBLISHED.value:
            continue
        content_id = str(item.get("content_id", ""))
        try:
            store.load_performance(content_id, review_window)
            continue
        except FileNotFoundError:
            pass
        try:
            state = store.load_state(content_id)
            lifecycle = state.get("lifecycle", {})
            published_at = aware_timestamp(
                lifecycle.get("published_at"), field="published_at"
            )
        except (FileNotFoundError, ValueError):
            continue
        due_at = published_at + ANALYTICS_DELAYS[review_window]
        if now >= due_at:
            due.append(
                {
                    "content_id": content_id,
                    "campaign_id": item.get("campaign_id"),
                    "campaign": item.get("campaign"),
                    "review_window": review_window,
                    "published_at": published_at.isoformat(),
                    "due_at": due_at.isoformat(),
                    "provider_post_id": lifecycle.get("provider_post_id", ""),
                    "provider_source_ref": lifecycle.get("source_ref", ""),
                    "metrics_required": True,
                    "action": "collect_platform_and_crm_metrics_with_provenance",
                }
            )
    due.sort(key=lambda entry: (entry["due_at"], entry["content_id"]))
    return {"items": due, "count": len(due), "writes_performed": False}


def _validated_performance_submission(
    payload: dict[str, Any],
    state: dict[str, Any],
) -> PerformanceRecord:
    """Build one evidence-backed analytics record against a published item."""

    content_id = str(payload.get("content_id", "")).strip()
    if not content_id or content_id == "unknown":
        raise HTTPException(
            status_code=422,
            detail="a real content_id is required; zero-data placeholder reviews are not accepted",
        )
    review_window = str(payload.get("review_window", "72h"))
    if review_window not in ANALYTICS_DELAYS:
        raise HTTPException(
            status_code=422, detail="review_window must be 72h, 7d, 14d, or 30d"
        )
    brief = state.get("brief", {})
    lifecycle = state.get("lifecycle", {})
    if (
        not isinstance(brief, dict)
        or brief.get("status") != ContentStatus.PUBLISHED.value
    ):
        raise HTTPException(
            status_code=409,
            detail="analytics can only be recorded for provider-confirmed published content",
        )
    try:
        published_at = aware_timestamp(
            lifecycle.get("published_at"), field="published_at"
        )
        due_at = published_at + ANALYTICS_DELAYS[review_window]
        now = datetime.now(timezone.utc)
        if now < due_at:
            raise HTTPException(
                status_code=409,
                detail=f"{review_window} analytics are not due until {due_at.isoformat()}",
            )
        evidence = normalized_performance_evidence(payload)
        first_evidence = evidence[0]
        record = PerformanceRecord(
            content_id=content_id,
            review_window=review_window,
            impressions=non_negative_int(
                payload.get("impressions", 0), field="impressions"
            ),
            saves=non_negative_int(payload.get("saves", 0), field="saves"),
            shares=non_negative_int(payload.get("shares", 0), field="shares"),
            comments_from_target_buyers=non_negative_int(
                payload.get("comments_from_target_buyers", 0),
                field="comments_from_target_buyers",
            ),
            profile_visits=non_negative_int(
                payload.get("profile_visits", 0), field="profile_visits"
            ),
            clicks=non_negative_int(payload.get("clicks", 0), field="clicks"),
            leads=non_negative_int(payload.get("leads", 0), field="leads"),
            qualified_leads=non_negative_int(
                payload.get("qualified_leads", 0), field="qualified_leads"
            ),
            booked_calls=non_negative_int(
                payload.get("booked_calls", 0), field="booked_calls"
            ),
            pipeline_value_eur=non_negative_float(
                payload.get("pipeline_value_eur", 0.0), field="pipeline_value_eur"
            ),
            landing_page_visits=non_negative_int(
                payload.get("landing_page_visits", 0), field="landing_page_visits"
            ),
            landing_page_conversions=non_negative_int(
                payload.get("landing_page_conversions", 0),
                field="landing_page_conversions",
            ),
            source_system=str(payload.get("source_system", "")).strip()[:100]
            or first_evidence["system"],
            source_ref=str(payload.get("source_ref", "")).strip()[:1000]
            or first_evidence["ref"],
            period_start=normalized_timestamp(
                payload.get("period_start"), field="period_start"
            ),
            period_end=normalized_timestamp(
                payload.get("period_end"), field="period_end"
            ),
            retrieved_at=normalized_timestamp(
                payload.get("retrieved_at"), field="retrieved_at"
            ),
            operator=str(payload.get("operator", "")).strip()[:200],
            attribution_rule=required_text(payload, "attribution_rule", max_length=200),
            snapshot_sha256=str(payload.get("snapshot_sha256", "")).strip().lower()
            or first_evidence["sha256"],
            evidence=evidence,
        )
        validation_errors = validate_performance_record(record)
        if validation_errors:
            raise ValueError("; ".join(validation_errors))
        period_start = aware_timestamp(record.period_start, field="period_start")
        period_end = aware_timestamp(record.period_end, field="period_end")
        retrieved_at = aware_timestamp(record.retrieved_at, field="retrieved_at")
        if period_start > published_at + timedelta(minutes=5):
            raise ValueError("period_start must cover the publication time")
        if period_end < due_at:
            raise ValueError(
                f"period_end must cover the complete {review_window} review window"
            )
        if retrieved_at > now + timedelta(minutes=5):
            raise ValueError("retrieved_at cannot be in the future")
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return record


def _performance_decision_payload(
    record: PerformanceRecord,
) -> tuple[dict[str, Any], Any]:
    """Create the durable decision envelope without volatile fingerprint fields."""

    decision = evaluate_performance(record)
    fingerprint_record = {
        key: value for key, value in record.__dict__.items() if key != "created_at"
    }
    fingerprint = request_fingerprint({"record": fingerprint_record})
    return (
        {
            "record": record.__dict__,
            "action": decision.action.value,
            "reason": decision.reason,
            "request_fingerprint": fingerprint,
        },
        decision,
    )


@app.post("/workflows/analytics-review")
def analytics_review(payload: dict[str, Any]) -> dict[str, Any]:
    payload = authenticated_manual_analytics_payload(payload)
    content_id = str(payload.get("content_id", "")).strip()
    store = JsonStore()
    try:
        state = store.load_state(content_id)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail=f"content state not found: {content_id}"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    record = _validated_performance_submission(payload, state)
    stored_payload, decision = _performance_decision_payload(record)
    stored_payload.update(identity_audit_fields())
    try:
        saved, idempotent = store.save_performance_once(stored_payload)
    except StateRevisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "status": "evaluated",
        "content_id": record.content_id,
        "review_window": record.review_window,
        "action": saved.get("action", decision.action.value),
        "reason": saved.get("reason", decision.reason),
        "record": saved.get("record", record.__dict__),
        "revision": saved.get("revision", 1),
        "request_fingerprint": saved.get(
            "request_fingerprint",
            stored_payload["request_fingerprint"],
        ),
        "idempotent": idempotent,
    }


@app.post("/workflows/analytics-review/correct")
def correct_analytics_review(payload: dict[str, Any]) -> dict[str, Any]:
    """Append a named, compare-and-swap correction without erasing history."""

    payload = authenticated_manual_analytics_payload(payload, correction=True)
    content_id = str(payload.get("content_id", "")).strip()
    store = JsonStore()
    try:
        state = store.load_state(content_id)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail=f"content state not found: {content_id}"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        record = _validated_performance_submission(payload, state)
        supersedes_fingerprint = required_text(
            payload,
            "supersedes_fingerprint",
            max_length=64,
        ).casefold()
        if len(supersedes_fingerprint) != 64 or any(
            character not in "0123456789abcdef" for character in supersedes_fingerprint
        ):
            raise ValueError(
                "supersedes_fingerprint must be a 64-character hexadecimal digest"
            )
        correction_reason = required_text(payload, "correction_reason", max_length=1000)
        if len(correction_reason) < 10:
            raise ValueError(
                "correction_reason must explain the correction in at least 10 characters"
            )
        correction_operator = required_text(
            payload, "correction_operator", max_length=200
        )
        corrected_at = normalized_timestamp(
            payload.get("corrected_at"), field="corrected_at"
        )
        if aware_timestamp(corrected_at, field="corrected_at") > datetime.now(
            timezone.utc
        ) + timedelta(minutes=5):
            raise ValueError("corrected_at cannot be in the future")
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    stored_payload, decision = _performance_decision_payload(record)
    stored_payload.update(identity_audit_fields())
    try:
        saved, idempotent = store.save_performance_correction(
            stored_payload,
            supersedes_fingerprint=supersedes_fingerprint,
            correction_reason=correction_reason,
            operator=correction_operator,
            corrected_at=corrected_at,
        )
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail=f"performance record not found: {record.content_id}/{record.review_window}",
        ) from exc
    except StateRevisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    correction_event_digest = request_fingerprint(
        {
            "supersedes_fingerprint": supersedes_fingerprint,
            "request_fingerprint": stored_payload["request_fingerprint"],
        }
    )
    correction_event_id = f"analytics-correction-{correction_event_digest[:32]}"
    store.append_event_once(
        "analytics_correction",
        correction_event_id,
        {
            "content_id": record.content_id,
            "review_window": record.review_window,
            "revision": saved.get("revision", 1),
            "supersedes_fingerprint": supersedes_fingerprint,
            "request_fingerprint": stored_payload["request_fingerprint"],
            "operator": correction_operator,
            "reason": correction_reason,
            "corrected_at": corrected_at,
            **identity_audit_fields(),
        },
    )
    return {
        "status": "corrected",
        "content_id": record.content_id,
        "review_window": record.review_window,
        "revision": saved.get("revision", 1),
        "action": saved.get("action", decision.action.value),
        "reason": saved.get("reason", decision.reason),
        "record": saved.get("record", record.__dict__),
        "correction": saved.get("correction", {}),
        "request_fingerprint": saved.get(
            "request_fingerprint",
            stored_payload["request_fingerprint"],
        ),
        "idempotent": idempotent,
    }


@app.get("/workflows/performance")
def list_performance(limit: int = Query(default=25, ge=1, le=100)) -> dict[str, Any]:
    return {"items": JsonStore().list_performance(limit=limit)}


@app.post("/workflows/lead-intake")
def lead_intake(payload: dict[str, Any]) -> dict[str, Any]:
    store = JsonStore()
    source_content_id = str(payload.get("source_content_id", "")).strip()
    source_state: dict[str, Any] | None = None
    if source_content_id:
        try:
            source_state = store.load_state(source_content_id)
        except (FileNotFoundError, ValueError):
            source_state = None
    source_verified, source_campaign_id, source_reason = verify_lead_source_attribution(
        payload,
        source_state,
        source_is_demo=store.is_demo_state(source_state or {}),
    )
    try:
        result = build_lead_intake(
            payload,
            source_verified=source_verified,
            source_campaign_id=source_campaign_id,
            source_verification_reason=source_reason,
        )
        saved, idempotent = store.save_lead_once(result)
    except StateRevisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    fingerprint = str(saved.get("request_fingerprint", ""))
    store.append_event_once(
        "lead_intake",
        f"lead-intake-{fingerprint}",
        {
            "lead_id": saved["lead"]["id"],
            "source_content_id": saved["lead"]["source_content_id"],
            "campaign_id": saved["lead"].get("campaign_id", ""),
            "source_verified": bool(saved.get("source_verified", False)),
            "routing_allowed": saved["routing_allowed"],
            "next_action": saved["lead"]["next_action"],
            "privacy_status": saved.get("privacy", {}).get("status", ""),
        },
    )
    return {"status": "accepted", **saved, "idempotent": idempotent}


@app.post("/workflows/lead-lifecycle")
def lead_lifecycle(payload: dict[str, Any]) -> dict[str, Any]:
    """Suppress, withdraw, or anonymize a lead without exposing its PII."""

    service_retention = bool(
        not current_authenticated_actor()
        and str(payload.get("action", "")).strip().casefold() == "expire_retention"
        and str(payload.get("operator", "")).strip() == "automation:n8n-retention"
    )
    if service_retention:
        authenticated_actor = "service:n8n-retention"
        identity_fields = {"authenticated_actor": authenticated_actor}
    else:
        authenticated_actor = require_human_actor("lead lifecycle")
        identity_fields = identity_audit_fields()
    store = JsonStore()
    try:
        lead_id = required_text(payload, "lead_id", max_length=128)
        action = required_text(payload, "action", max_length=40).lower()
        operator = required_text(payload, "operator", max_length=200)
        allowed_reason_codes = LEAD_REASON_CODES_BY_ACTION.get(action)
        if not allowed_reason_codes:
            raise ValueError(f"unsupported lead lifecycle action: {action}")
        reason_code = (
            str(payload.get("reason_code") or DEFAULT_LEAD_REASON_CODE[action])
            .strip()
            .casefold()
        )
        if reason_code not in allowed_reason_codes:
            raise ValueError(
                f"reason_code is not allowed for {action}: {reason_code or 'missing'}"
            )
        reason_ref = str(payload.get("reason_ref", "")).strip()
        if reason_ref:
            reason_ref = validate_identifier(reason_ref, field="reason_ref")
        # Free-text reasons can contain the data being erased. They are accepted
        # only for backward-compatible transport and are never fingerprinted,
        # persisted, or echoed. The durable audit stores a controlled code and
        # an optional PII-safe ticket/reference identifier.
        reason = reason_code
        occurred_at = normalized_timestamp(
            payload.get("occurred_at"), field="occurred_at"
        )
        if aware_timestamp(occurred_at, field="occurred_at") > datetime.now(
            timezone.utc
        ) + timedelta(minutes=5):
            raise ValueError("occurred_at cannot be in the future")
        current = store.load_lead(lead_id)
        effective_expiry_at = ""
        if action == "expire_retention":
            effective_expiry_at = normalized_timestamp(
                payload.get("effective_expiry_at"),
                field="effective_expiry_at",
            )
            lead_record = current.get("lead", {})
            privacy_record = current.get("privacy", {})
            stored_expiry = normalized_timestamp(
                (
                    privacy_record.get("retention_expires_at")
                    if isinstance(privacy_record, dict)
                    else ""
                )
                or (
                    lead_record.get("retention_expires_at")
                    if isinstance(lead_record, dict)
                    else ""
                ),
                field="stored retention_expires_at",
            )
            if effective_expiry_at != stored_expiry:
                raise ValueError(
                    "effective_expiry_at must match the stored retention expiry"
                )
            if aware_timestamp(occurred_at, field="occurred_at") < aware_timestamp(
                effective_expiry_at,
                field="effective_expiry_at",
            ):
                raise ValueError("occurred_at cannot precede effective_expiry_at")
        expected_revision = int(current.get("revision", 1))
        fingerprint_payload = {
            "lead_id": lead_id,
            "action": action,
            "operator": operator,
            "reason_code": reason_code,
            "reason_ref": reason_ref,
        }
        if action == "expire_retention":
            # The effective expiry is stable across n8n retries; occurred_at is
            # the truthful wall-clock execution time and is stored on first use.
            fingerprint_payload["effective_expiry_at"] = effective_expiry_at
        else:
            fingerprint_payload["occurred_at"] = occurred_at
        fingerprint = request_fingerprint(fingerprint_payload)
        seen_transitions = {
            str(item)
            for item in current.get("transition_fingerprints", [])
            if str(item)
        }
        last_transition = str(current.get("last_transition_fingerprint", ""))
        if last_transition:
            seen_transitions.add(last_transition)
        if fingerprint in seen_transitions:
            updated = current
        else:
            updated = apply_lead_lifecycle(
                current,
                action=action,
                operator=operator,
                reason=reason,
                occurred_at=occurred_at,
            )
            privacy = updated.get("privacy", {})
            if isinstance(privacy, dict):
                privacy["last_reason_code"] = reason_code
                privacy["last_reason_ref"] = reason_ref
            if authenticated_actor and isinstance(privacy, dict):
                privacy["last_authenticated_actor"] = authenticated_actor
                if identity_fields.get("authenticated_request_fingerprint"):
                    privacy["authenticated_request_fingerprint"] = identity_fields[
                        "authenticated_request_fingerprint"
                    ]
        saved, idempotent = store.save_lead_transition(
            updated,
            expected_revision=expected_revision,
            transition_fingerprint=fingerprint,
            action=action,
            operator=operator,
            reason=reason,
            occurred_at=occurred_at,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except StateRevisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    privacy = saved.get("privacy", {})
    store.append_event_once(
        "lead_lifecycle",
        f"lead-lifecycle-{fingerprint}",
        {
            "lead_id": lead_id,
            "action": action,
            "operator": operator,
            "reason_code": reason_code,
            "reason_ref": reason_ref,
            "occurred_at": occurred_at,
            "effective_expiry_at": effective_expiry_at,
            "privacy_status": privacy.get("status", "")
            if isinstance(privacy, dict)
            else "",
            "revision": saved.get("revision", 1),
            **identity_fields,
        },
    )
    return {
        "status": "recorded",
        "lead_id": lead_id,
        "privacy": privacy,
        "effective_expiry_at": effective_expiry_at,
        "reason_code": reason_code,
        "reason_ref": reason_ref,
        "revision": saved.get("revision", 1),
        "idempotent": idempotent,
    }


@app.get("/workflows/leads")
def list_leads(limit: int = Query(default=25, ge=1, le=100)) -> dict[str, Any]:
    return {"items": JsonStore().list_leads(limit=limit)}


@app.get("/workflows/leads/retention-due")
def leads_retention_due() -> dict[str, Any]:
    """Return a PII-free, read-only queue of locally expired lead records."""

    as_of = datetime.now(timezone.utc)
    due: list[dict[str, str]] = []
    invalid: list[dict[str, str]] = []
    eligible_statuses = {"active", "suppressed", "withdrawn"}
    for summary in JsonStore().list_leads(limit=100_000):
        privacy_status = str(summary.get("privacy_status", "")).strip().lower()
        if privacy_status == "anonymized":
            continue
        raw_lead_id = str(summary.get("id", ""))
        try:
            lead_id = validate_identifier(raw_lead_id, field="lead_id")
        except ValueError:
            invalid.append(
                {
                    "record_ref": f"invalid-lead-{request_fingerprint({'id': raw_lead_id})[:16]}",
                    "field": "lead_id",
                    "reason": "invalid_identifier",
                }
            )
            continue
        if summary.get("record_validation_error"):
            invalid.append(
                {
                    "record_ref": lead_id,
                    "field": "record",
                    "reason": "unreadable_or_invalid_record",
                }
            )
            continue
        if privacy_status not in eligible_statuses:
            invalid.append(
                {
                    "record_ref": lead_id,
                    "field": "privacy_status",
                    "reason": "unsupported_or_missing_status",
                }
            )
            continue
        retention_policy = str(summary.get("retention_policy", "")).strip()
        if retention_policy not in RETENTION_POLICY_MAX_DURATIONS:
            invalid.append(
                {
                    "record_ref": lead_id,
                    "field": "retention_policy",
                    "reason": "unsupported_or_missing_policy",
                }
            )
            continue
        try:
            retention_expires_at = aware_timestamp(
                summary.get("retention_expires_at"),
                field="retention_expires_at",
            )
        except ValueError:
            invalid.append(
                {
                    "record_ref": lead_id,
                    "field": "retention_expires_at",
                    "reason": "invalid_or_missing_timestamp",
                }
            )
            continue
        if retention_expires_at > as_of:
            continue
        due.append(
            {
                "lead_id": lead_id,
                "effective_expiry_at": retention_expires_at.isoformat(),
                "retention_policy": retention_policy,
            }
        )

    due.sort(key=lambda item: (item["effective_expiry_at"], item["lead_id"]))
    invalid.sort(key=lambda item: (item["record_ref"], item["field"]))
    return {
        "items": due,
        "count": len(due),
        "invalid_items": invalid,
        "invalid_count": len(invalid),
        "operator_review_required": bool(invalid),
        "as_of": as_of.isoformat(),
    }


@app.post("/workflows/route-scheduler-draft")
def route_scheduler_draft(payload: dict[str, Any]) -> dict[str, Any]:
    store = JsonStore()
    content_id = str(payload.get("content_id", "")).strip()
    if not content_id:
        raise HTTPException(
            status_code=422, detail="missing required field: content_id"
        )
    try:
        dry_run = strict_bool(payload.get("dry_run", True), field="dry_run")
        if not dry_run:
            require_human_actor("live scheduler route")
        with store.state_lock(content_id):
            result = route_scheduler_draft_to_target(
                store=store,
                policy=load_policy(),
                content_id=content_id,
                target=str(payload.get("target", "postiz")).strip() or "postiz",
                dry_run=dry_run,
            )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not result.get("idempotent"):
        store.append_event(
            "routing",
            {
                "route_id": result["id"],
                "kind": result["kind"],
                "target": result["target"],
                "source_id": result["source_id"],
                "status": result["status"],
                "dry_run": result["dry_run"],
                **identity_audit_fields(),
            },
        )
    return {"status": result["status"], "route": result}


@app.post("/workflows/route-lead")
def route_lead(payload: dict[str, Any]) -> dict[str, Any]:
    store = JsonStore()
    lead_id = str(payload.get("lead_id", "")).strip()
    if not lead_id:
        raise HTTPException(status_code=422, detail="missing required field: lead_id")
    try:
        dry_run = strict_bool(payload.get("dry_run", True), field="dry_run")
        if not dry_run:
            require_human_actor("live lead route")
        result = route_lead_to_target(
            store=store,
            policy=load_policy(),
            lead_id=lead_id,
            target=str(payload.get("target", "twenty")).strip() or "twenty",
            dry_run=dry_run,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if not result.get("idempotent"):
        store.append_event(
            "routing",
            {
                "route_id": result["id"],
                "kind": result["kind"],
                "target": result["target"],
                "source_id": result["source_id"],
                "status": result["status"],
                "dry_run": result["dry_run"],
                **identity_audit_fields(),
            },
        )
    return {"status": result["status"], "route": result}


@app.get("/workflows/outbox")
def list_outbox(limit: int = Query(default=25, ge=1, le=100)) -> dict[str, Any]:
    return {"items": JsonStore().list_outbox(limit=limit)}
