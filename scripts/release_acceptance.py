from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import ssl
import sys
from typing import Any, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

from marketing_machine.content_quality import (  # noqa: E402
    ContentQualityInputError,
    evaluate_content_quality,
)


EXPECTED_ACTIVE_WORKFLOW_IDS = {
    "lYfpV4r4oeEzPtuO",
    "Psaft2cYujD42MAs",
    "GqGVw06F64o7rvjI",
    "WMCTrendResearch01",
    "eTZSmmzKe6dJ1knR",
    "WMCAnalytics7d01",
    "WMCAnalytics14d1",
    "WMCAnalytics30d1",
}
EXPECTED_INACTIVE_WORKFLOW_IDS = {
    "5OzpL9oBMR8gpSJA",
    "WMCLeadRetention01",
}
EXPECTED_N8N_WORKFLOW_FILES = {
    "lYfpV4r4oeEzPtuO": "manual-content-intake.json",
    "Psaft2cYujD42MAs": "integration-health.json",
    "GqGVw06F64o7rvjI": "weekly-planning.json",
    "WMCTrendResearch01": "trend-research-intake.json",
    "eTZSmmzKe6dJ1knR": "analytics-72h.json",
    "WMCAnalytics7d01": "analytics-7d.json",
    "WMCAnalytics14d1": "analytics-14d.json",
    "WMCAnalytics30d1": "analytics-30d.json",
    "5OzpL9oBMR8gpSJA": "approval-webhook.json",
    "WMCLeadRetention01": "lead-retention-daily.json",
}
N8N_EXECUTION_EVIDENCE_WORKFLOW_ID = "WMCTrendResearch01"
N8N_WORKFLOW_ROOT = REPOSITORY_ROOT / "deploy" / "n8n" / "workflows"
COMFYUI_APPROVAL_SCHEMA_VERSION = "1.0"
COMFYUI_LICENSE_IDENTIFIER = "Apache-2.0"
COMFYUI_LICENSE_SOURCE = "black-forest-labs/FLUX.1-schnell"
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
SAFE_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
CAMPAIGN_SOURCE_IDS = {
    "k1": "kampagne_1_consulting_qa",
    "k2": "kampagne_2_ki_sokrates",
    "k3": "kampagne_3_lfa_azubis",
    "k4": "kampagne_4_mitarbeiter",
    "k5": "kampagne_5_app_entwicklung",
}
RELEASE_EVIDENCE_FRESHNESS_DAYS = 7
FORBIDDEN_STATE_MARKERS = ("demo", "mock", "smoke", "placeholder")
GENERIC_ACTORS = {
    "admin",
    "anonymous",
    "automation",
    "marketing",
    "n8n",
    "operator",
    "service",
    "unknown",
    "user",
}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        return None


@dataclass(frozen=True)
class HttpResult:
    status: int
    headers: dict[str, str]
    body: bytes
    url: str


@dataclass(frozen=True)
class OperatorCredential:
    actor: str
    password: str = field(repr=False)

    def authorization_header(self) -> str:
        encoded = base64.b64encode(f"{self.actor}:{self.password}".encode("utf-8")).decode("ascii")
        return f"Basic {encoded}"


class ReadOnlyHttpClient:
    """Trusted-TLS, GET-only client that refuses to forward credentials on redirects."""

    def __init__(self, *, ca_file: str = "", timeout: float = 12.0) -> None:
        self.timeout = timeout
        self.context = ssl.create_default_context(cafile=ca_file or None)
        self.opener = build_opener(HTTPSHandler(context=self.context), _NoRedirect())

    def get(self, url: str, *, headers: dict[str, str] | None = None) -> HttpResult:
        request = Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "wamocon-release-acceptance/1.0", **(headers or {})},
            method="GET",
        )
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                body = response.read(2_000_001)
                if len(body) > 2_000_000:
                    raise RuntimeError(f"GET {url} returned more than the 2 MB read-only limit")
                return HttpResult(
                    status=int(response.status),
                    headers={key.casefold(): value for key, value in response.headers.items()},
                    body=body,
                    url=response.geturl(),
                )
        except HTTPError as exc:
            raise RuntimeError(f"GET {url} returned HTTP {exc.code}") from exc
        except (OSError, URLError, ssl.SSLError) as exc:
            raise RuntimeError(f"GET {url} failed trusted transport validation: {type(exc).__name__}") from exc

    def get_json(self, url: str, *, headers: dict[str, str] | None = None) -> dict[str, Any]:
        result = self.get(url, headers=headers)
        if not 200 <= result.status < 300:
            raise RuntimeError(f"GET {url} returned HTTP {result.status}")
        try:
            payload = json.loads(result.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"GET {url} did not return a JSON object") from exc
        if not isinstance(payload, dict):
            raise RuntimeError(f"GET {url} did not return a JSON object")
        return payload

    def prove_plain_http_closed(self, https_url: str) -> dict[str, Any]:
        parsed = urlsplit(https_url)
        plain_url = urlunsplit(("http", parsed.netloc, parsed.path or "/", parsed.query, ""))
        request = Request(plain_url, headers={"User-Agent": "wamocon-release-acceptance/1.0"}, method="GET")
        opener = build_opener(_NoRedirect())
        try:
            with opener.open(request, timeout=self.timeout) as response:
                status = int(response.status)
                headers = {key.casefold(): value for key, value in response.headers.items()}
        except HTTPError as exc:
            status = int(exc.code)
            headers = {key.casefold(): value for key, value in exc.headers.items()}
        except (OSError, URLError, ConnectionError, TimeoutError):
            return {"url": plain_url, "outcome": "refused_or_closed"}

        if "www-authenticate" in headers or status in {401, 407}:
            raise AssertionError(f"plaintext endpoint exposed an authentication challenge: {plain_url}")
        if status in {301, 302, 303, 307, 308}:
            location = urljoin(plain_url, headers.get("location", ""))
            destination = urlsplit(location)
            if (
                destination.scheme != "https"
                or destination.hostname != parsed.hostname
                or destination.port != parsed.port
                or destination.username
                or destination.password
            ):
                raise AssertionError(f"plaintext endpoint returned an unsafe redirect: {plain_url}")
            return {"url": plain_url, "outcome": "https_redirect", "status": status}
        if status in {400, 403, 404, 421, 426}:
            return {"url": plain_url, "outcome": "non_usable_response", "status": status}
        raise AssertionError(f"plaintext endpoint remained usable or returned an unapproved status {status}: {plain_url}")


def _secret_file(path_text: str, *, label: str) -> str:
    path = Path(path_text).expanduser()
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError(f"cannot read {label} file {path}: {exc}") from exc
    if not value:
        raise RuntimeError(f"{label} file is empty: {path}")
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        raise RuntimeError(f"{label} contains a control character")
    if os.name == "posix" and path.stat().st_mode & 0o077:
        raise RuntimeError(f"{label} file must not be readable by group or other users: {path}")
    return value


def load_operator(path_text: str) -> OperatorCredential:
    value = _secret_file(path_text, label="operator credential")
    if ":" not in value:
        raise RuntimeError("operator credential must contain one named account and password separated by ':'")
    actor, password = value.split(":", 1)
    actor = actor.strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]+", actor) or actor.casefold() in GENERIC_ACTORS:
        raise RuntimeError("operator credential must identify a named person, not a generic role")
    if not password:
        raise RuntimeError("operator credential password is empty")
    return OperatorCredential(actor=actor, password=password)


def _https_base(value: str, *, label: str) -> str:
    parsed = urlsplit(value.strip().rstrip("/"))
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise RuntimeError(f"{label} must be an https URL without embedded credentials")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def _api_url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _recent_aware_timestamp(value: Any, *, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise AssertionError(f"{label} is not a valid ISO-8601 timestamp") from exc
    _require(parsed.tzinfo is not None, f"{label} has no timezone")
    observed = parsed.astimezone(timezone.utc)
    now = datetime.now(timezone.utc)
    _require(observed <= now + timedelta(minutes=5), f"{label} is in the future")
    _require(
        observed >= now - timedelta(days=RELEASE_EVIDENCE_FRESHNESS_DAYS),
        f"{label} is older than {RELEASE_EVIDENCE_FRESHNESS_DAYS} days",
    )
    return observed


def _citation_domain(value: Any) -> str:
    parsed = urlsplit(str(value).strip())
    _require(parsed.scheme in {"http", "https"}, "trend citation is not an absolute public HTTP(S) URL")
    _require(bool(parsed.hostname), "trend citation has no hostname")
    _require(parsed.username is None and parsed.password is None, "trend citation embeds user information")
    host = str(parsed.hostname).casefold().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def _verify_campaign_research(
    *,
    console_url: str,
    campaign_items: list[dict[str, Any]],
    headers: dict[str, str],
    client: ReadOnlyHttpClient,
) -> list[dict[str, Any]]:
    run_cache: dict[str, dict[str, Any]] = {}
    evidence: list[dict[str, Any]] = []
    by_campaign = {
        str(item.get("id", "")).casefold(): item
        for item in campaign_items
        if isinstance(item, dict)
    }
    for campaign_id, source_id in CAMPAIGN_SOURCE_IDS.items():
        campaign = by_campaign.get(campaign_id, {})
        research = campaign.get("research", {}) if isinstance(campaign, dict) else {}
        _require(isinstance(research, dict), f"{campaign_id} has no research evidence")
        _require(research.get("status") == "verified_recent", f"{campaign_id} has no current verified trend")
        _require(int(research.get("verified_trend_count", 0) or 0) > 0, f"{campaign_id} has no eligible trend")
        run_id = str(research.get("run_id", "")).strip()
        _require(bool(run_id), f"{campaign_id} research has no durable run id")
        if run_id not in run_cache:
            run_cache[run_id] = client.get_json(
                _api_url(console_url, f"/workflows/trend-research/runs/{run_id}"),
                headers=headers,
            )
        run = run_cache[run_id]
        _recent_aware_timestamp(run.get("run_started_at"), label=f"{campaign_id} trend run")
        matching_results = [
            result
            for result in run.get("campaigns", [])
            if isinstance(result, dict)
            and isinstance(result.get("campaign"), dict)
            and str(result["campaign"].get("id", "")) == source_id
        ]
        _require(len(matching_results) == 1, f"{campaign_id} trend run does not contain one canonical campaign result")
        verified_trends: list[dict[str, Any]] = []
        for trend in matching_results[0].get("trends", []):
            if not isinstance(trend, dict):
                continue
            verification = trend.get("verification", {})
            if not isinstance(verification, dict):
                continue
            if verification.get("status") != "verified_recent" or verification.get("eligible_for_content") is not True:
                continue
            citations = [item for item in trend.get("citations", []) if isinstance(item, dict)]
            domains = {_citation_domain(item.get("url", "")) for item in citations}
            if len(citations) < 2 or len(domains) < 2:
                continue
            if not any(str(item.get("published", "")).strip() for item in citations):
                continue
            verified_trends.append(trend)
        _require(bool(verified_trends), f"{campaign_id} has no two-domain, dated, currently eligible trend evidence")
        evidence.append({"campaign_id": campaign_id, "run_id": run_id, "verified_trends": len(verified_trends)})
    return evidence


def _verify_current_campaign_content(
    *,
    console_url: str,
    campaign_items: list[dict[str, Any]],
    headers: dict[str, str],
    client: ReadOnlyHttpClient,
) -> list[dict[str, Any]]:
    by_campaign = {
        str(item.get("id", "")).casefold(): item
        for item in campaign_items
        if isinstance(item, dict)
    }
    evidence: list[dict[str, Any]] = []
    valid_review_states = {
        "needs_human_review",
        "revision_requested",
        "ready_to_schedule",
        "scheduled",
        "published",
    }
    for campaign_id in CAMPAIGN_SOURCE_IDS:
        campaign = by_campaign.get(campaign_id, {})
        content = campaign.get("content", {}) if isinstance(campaign, Mapping) else {}
        latest = content.get("latest", {}) if isinstance(content, Mapping) else {}
        _require(isinstance(latest, Mapping), f"{campaign_id} has no current revision head")
        content_id = str(latest.get("content_id", "")).strip()
        _require(
            bool(SAFE_IDENTIFIER_RE.fullmatch(content_id)),
            f"{campaign_id} current revision head has an invalid content id",
        )
        _require(
            str(latest.get("campaign_id", "")).casefold() == campaign_id,
            f"{campaign_id} current revision summary has a mismatched campaign identity",
        )
        _require(
            not any(marker in content_id.casefold() for marker in FORBIDDEN_STATE_MARKERS),
            f"{campaign_id} current revision head is test or demo content",
        )
        state = client.get_json(
            _api_url(console_url, f"/workflows/states/{quote(content_id, safe='')}"),
            headers=headers,
        )
        brief = state.get("brief", {})
        _require(isinstance(brief, Mapping), f"{campaign_id} current revision has no full brief")
        _require(str(brief.get("id", "")).strip() == content_id, f"{campaign_id} full brief id does not match its current head")
        _require(
            str(brief.get("campaign_id", "")).casefold() == campaign_id,
            f"{campaign_id} full brief has a mismatched campaign identity",
        )
        status = str(brief.get("status", "")).strip()
        _require(status in valid_review_states, f"{campaign_id} current revision is not in a valid review state")
        _recent_aware_timestamp(brief.get("updated_at"), label=f"{campaign_id} current AI draft")

        generation = brief.get("generation", {})
        _require(isinstance(generation, Mapping), f"{campaign_id} current revision has no AI provenance")
        _require(generation.get("status") == "ai_generated", f"{campaign_id} current revision is not AI-generated")
        _require(generation.get("provider") == "local_qwen", f"{campaign_id} current revision did not use the governed local Qwen provider")
        _require(generation.get("fallback_used") is False, f"{campaign_id} current revision used or omitted fallback provenance")
        model = str(generation.get("model", "")).strip()
        _require(bool(model), f"{campaign_id} current revision has no local Qwen model identity")

        stored_quality = brief.get("quality_evaluation", {})
        _require(isinstance(stored_quality, Mapping), f"{campaign_id} current revision has no stored quality decision")
        _require(
            stored_quality.get("release_ready") is True
            and stored_quality.get("decision") == "pass"
            and stored_quality.get("hard_blockers") == [],
            f"{campaign_id} stored deterministic quality decision is not release-ready",
        )
        try:
            recomputed = evaluate_content_quality(state, repo_root=REPOSITORY_ROOT)
        except (ContentQualityInputError, OSError, ValueError, TypeError) as exc:
            raise AssertionError(f"{campaign_id} deterministic quality evaluation could not be recomputed") from exc
        _require(
            recomputed.get("release_ready") is True
            and recomputed.get("decision") == "pass"
            and recomputed.get("hard_blockers") == [],
            f"{campaign_id} current full content fails the deterministic release rubric",
        )
        _require(
            stored_quality.get("schema_version") == recomputed.get("schema_version")
            and stored_quality.get("rubric_version") == recomputed.get("rubric_version")
            and stored_quality.get("overall_score") == recomputed.get("overall_score"),
            f"{campaign_id} stored quality decision is stale or inconsistent with the full content",
        )
        evidence.append(
            {
                "campaign_id": campaign_id,
                "content_id": content_id,
                "model": model,
                "quality_score": recomputed.get("overall_score"),
                "rubric_version": recomputed.get("rubric_version"),
            }
        )
    return evidence


def _required_check(payload: dict[str, Any], name: str) -> dict[str, Any]:
    checks = payload.get("checks", [])
    found = next((item for item in checks if isinstance(item, dict) and item.get("name") == name), None)
    if found is None:
        raise AssertionError(f"integration status did not include {name}")
    return found


def _canonical_json_sha256(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _canonical_workflow_definition(workflow: Mapping[str, Any]) -> dict[str, Any]:
    """Return the release-significant n8n export without server-generated IDs.

    n8n adds an opaque credential ID when a named credential is bound.  The
    repository deliberately stores only the credential type and approved name,
    so IDs are normalized away while every credential name remains hash-bound.
    All other node, connection, setting, name, state, and stable-ID fields are
    retained exactly.
    """

    nodes = workflow.get("nodes")
    connections = workflow.get("connections")
    settings = workflow.get("settings")
    if not isinstance(nodes, list) or not isinstance(connections, Mapping) or not isinstance(settings, Mapping):
        raise AssertionError("n8n workflow definition is missing nodes, connections, or settings")

    canonical_nodes: list[dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, Mapping):
            raise AssertionError("n8n workflow definition contains a malformed node")
        canonical_node = dict(node)
        credentials = canonical_node.get("credentials")
        if credentials is not None:
            if not isinstance(credentials, Mapping):
                raise AssertionError("n8n workflow node contains malformed credential references")
            canonical_credentials: dict[str, dict[str, str]] = {}
            for credential_type, reference in credentials.items():
                if not isinstance(reference, Mapping):
                    raise AssertionError("n8n workflow node contains malformed credential references")
                unexpected = set(reference) - {"id", "name"}
                name = str(reference.get("name", "")).strip()
                if unexpected or not name:
                    raise AssertionError("n8n workflow node contains an unapproved credential reference")
                canonical_credentials[str(credential_type)] = {"name": name}
            canonical_node["credentials"] = canonical_credentials
        canonical_nodes.append(canonical_node)

    workflow_id = str(workflow.get("id", "")).strip()
    name = str(workflow.get("name", "")).strip()
    active = workflow.get("active")
    if not workflow_id or not name or not isinstance(active, bool):
        raise AssertionError("n8n workflow definition is missing its stable id, name, or active state")
    return {
        "id": workflow_id,
        "name": name,
        "active": active,
        "nodes": canonical_nodes,
        "connections": dict(connections),
        "settings": dict(settings),
    }


def _expected_n8n_contract() -> dict[str, dict[str, Any]]:
    contract: dict[str, dict[str, Any]] = {}
    expected_ids = EXPECTED_ACTIVE_WORKFLOW_IDS | EXPECTED_INACTIVE_WORKFLOW_IDS
    _require(set(EXPECTED_N8N_WORKFLOW_FILES) == expected_ids, "local n8n release manifest IDs are inconsistent")
    for workflow_id, filename in EXPECTED_N8N_WORKFLOW_FILES.items():
        path = N8N_WORKFLOW_ROOT / filename
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AssertionError(f"cannot read canonical n8n workflow {filename}") from exc
        _require(isinstance(payload, Mapping), f"canonical n8n workflow {filename} is malformed")
        canonical = _canonical_workflow_definition(payload)
        _require(canonical["id"] == workflow_id, f"canonical n8n workflow {filename} has the wrong stable id")
        expected_active = workflow_id in EXPECTED_ACTIVE_WORKFLOW_IDS
        _require(canonical["active"] is expected_active, f"canonical n8n workflow {filename} has the wrong active state")
        contract[workflow_id] = {
            "definition": canonical,
            "sha256": _canonical_json_sha256(canonical),
        }
    return contract


def _named_reviewer(value: Any, *, label: str) -> str:
    reviewer = str(value or "").strip()
    _require(
        bool(re.fullmatch(r"[A-Za-z0-9._-]+", reviewer)) and reviewer.casefold() not in GENERIC_ACTORS,
        f"{label} must identify a named person, not a generic role",
    )
    return reviewer


def _safe_evidence_reference(value: Any, *, label: str) -> str:
    reference = str(value or "").strip()
    _require(0 < len(reference) <= 500, f"{label} is missing or too long")
    _require(not any(ord(character) < 0x20 or ord(character) == 0x7F for character in reference), f"{label} contains control characters")
    return reference


def _comfyui_live_binding(comfyui: Mapping[str, Any]) -> tuple[dict[str, str], datetime]:
    binding = {
        "output_sha256": str(comfyui.get("last_output_sha256", "")).strip().casefold(),
        "prompt_id": str(comfyui.get("qualification_prompt_id", "")).strip(),
        "workflow_sha256": str(comfyui.get("qualified_workflow_sha256", "")).strip().casefold(),
        "runtime_identity_sha256": str(
            comfyui.get("qualification_runtime_identity_sha256", "")
        ).strip().casefold(),
        "model_files_sha256": str(comfyui.get("qualification_model_files_sha256", "")).strip().casefold(),
    }
    for key in ("output_sha256", "workflow_sha256", "runtime_identity_sha256", "model_files_sha256"):
        _require(bool(SHA256_RE.fullmatch(binding[key])), f"ComfyUI technical qualification has no valid {key}")
    _require(
        bool(SAFE_IDENTIFIER_RE.fullmatch(binding["prompt_id"])),
        "ComfyUI technical qualification has no valid prompt id",
    )
    completed_at = _recent_aware_timestamp(
        comfyui.get("qualification_completed_at"),
        label="ComfyUI qualification completion",
    )
    return binding, completed_at


def _validate_comfyui_human_approvals(
    evidence: Mapping[str, Any],
    *,
    live_binding: Mapping[str, str],
    qualification_completed_at: datetime,
) -> dict[str, Any]:
    _require(
        evidence.get("schema_version") == COMFYUI_APPROVAL_SCHEMA_VERSION,
        "ComfyUI approval evidence uses an unsupported schema",
    )
    recorded_binding = evidence.get("qualification_binding")
    if not isinstance(recorded_binding, Mapping):
        raise AssertionError("ComfyUI approval evidence has no qualification binding")
    normalized_binding = {
        str(key): (
            str(value).strip().casefold()
            if str(key).endswith("sha256")
            else str(value).strip()
        )
        for key, value in recorded_binding.items()
    }
    _require(normalized_binding == dict(live_binding), "ComfyUI approval evidence is not bound to the live qualified output")
    binding_sha256 = _canonical_json_sha256(dict(live_binding))

    approvals: dict[str, dict[str, Any]] = {}
    reviewers: list[str] = []
    for key, label in (("visual_approval", "visual approval"), ("license_approval", "license approval")):
        approval = evidence.get(key)
        if not isinstance(approval, Mapping):
            raise AssertionError(f"ComfyUI {label} is missing")
        _require(approval.get("approved") is True, f"ComfyUI {label} has not been granted")
        reviewer = _named_reviewer(approval.get("reviewer"), label=f"ComfyUI {label} reviewer")
        approved_at = _recent_aware_timestamp(approval.get("approved_at"), label=f"ComfyUI {label} timestamp")
        _require(approved_at >= qualification_completed_at, f"ComfyUI {label} predates the qualified output")
        _require(
            str(approval.get("qualification_binding_sha256", "")).strip().casefold() == binding_sha256,
            f"ComfyUI {label} is not bound to the qualified output, prompt, workflow, runtime, and models",
        )
        evidence_ref = _safe_evidence_reference(approval.get("evidence_ref"), label=f"ComfyUI {label} evidence reference")
        reviewers.append(reviewer)
        approvals[key] = {
            "reviewer": reviewer,
            "approved_at": approved_at.isoformat(),
            "evidence_ref": evidence_ref,
        }

    _require(reviewers[0] != reviewers[1], "ComfyUI visual and license approvals require distinct named reviewers")
    license_approval = evidence["license_approval"]
    assert isinstance(license_approval, Mapping)
    _require(
        str(license_approval.get("license_identifier", "")).strip() == COMFYUI_LICENSE_IDENTIFIER,
        "ComfyUI license approval does not identify the reviewed Apache-2.0 license",
    )
    _require(
        str(license_approval.get("source_repository", "")).strip() == COMFYUI_LICENSE_SOURCE,
        "ComfyUI license approval does not identify the pinned official model source",
    )
    return {
        "binding_sha256": binding_sha256,
        "visual_reviewer": approvals["visual_approval"]["reviewer"],
        "license_reviewer": approvals["license_approval"]["reviewer"],
    }


def _fetch_n8n_workflows(client: ReadOnlyHttpClient, n8n_url: str, api_key: str) -> list[dict[str, Any]]:
    headers = {"X-N8N-API-KEY": api_key}
    cursor = ""
    workflows: list[dict[str, Any]] = []
    seen_cursors: set[str] = set()
    for _ in range(100):
        query: list[tuple[str, str]] = [("limit", "100")]
        if cursor:
            query.append(("cursor", cursor))
        payload = client.get_json(_api_url(n8n_url, f"/api/v1/workflows?{urlencode(query)}"), headers=headers)
        page = payload.get("data", [])
        if not isinstance(page, list):
            raise AssertionError("n8n workflow API returned a malformed data list")
        workflows.extend(item for item in page if isinstance(item, dict))
        next_cursor = str(payload.get("nextCursor") or "").strip()
        if not next_cursor:
            return workflows
        if next_cursor in seen_cursors:
            raise AssertionError("n8n workflow API repeated a pagination cursor")
        seen_cursors.add(next_cursor)
        cursor = next_cursor
    raise AssertionError("n8n workflow API exceeded the pagination safety limit")


def run_acceptance(
    *,
    console_url: str,
    n8n_url: str,
    operators: Iterable[OperatorCredential],
    n8n_api_key: str,
    comfyui_approval_evidence: Mapping[str, Any],
    client: ReadOnlyHttpClient,
) -> list[dict[str, Any]]:
    console_url = _https_base(console_url, label="console URL")
    n8n_url = _https_base(n8n_url, label="n8n URL")
    operator_list = list(operators)
    actors = [item.actor for item in operator_list]
    _require(len(operator_list) >= 2, "release acceptance requires at least two named operator accounts")
    _require(len(set(actors)) == len(actors), "release acceptance operator accounts must be distinct")

    checks: list[dict[str, Any]] = []
    checks.append({"name": "console_plain_http_closed", **client.prove_plain_http_closed(_api_url(console_url, "/ui"))})
    checks.append({"name": "n8n_plain_http_closed", **client.prove_plain_http_closed(_api_url(n8n_url, "/healthz"))})

    primary_headers = {"Authorization": operator_list[0].authorization_header()}
    ui = client.get(_api_url(console_url, "/ui"), headers=primary_headers)
    _require(200 <= ui.status < 300, "console UI did not return a successful response")
    csp = ui.headers.get("content-security-policy", "").casefold()
    _require("frame-ancestors 'none'" in csp, "console is missing CSP frame-ancestors 'none'")
    _require(ui.headers.get("x-frame-options", "").casefold() == "deny", "console is missing X-Frame-Options: DENY")
    _require("max-age=" in ui.headers.get("strict-transport-security", "").casefold(), "console is missing HSTS")
    checks.append({"name": "console_tls_and_clickjacking_headers", "status": "ok"})

    for operator in operator_list:
        session = client.get_json(
            _api_url(console_url, "/session"),
            headers={"Authorization": operator.authorization_header()},
        )
        _require(session.get("authenticated") is True, f"session did not authenticate named actor {operator.actor}")
        _require(session.get("actor") == operator.actor, f"session actor did not match named account {operator.actor}")
        _require(session.get("authentication") == "edge_attested", "session identity is not edge-attested")
    checks.append({"name": "two_named_edge_attested_operators", "actors": actors})

    health = client.get_json(_api_url(console_url, "/healthz"), headers=primary_headers)
    instance = health.get("instance", {})
    _require(health.get("status") == "ok", "production health is not ok")
    _require(instance.get("mode") == "production", "release target does not identify as production")
    _require(instance.get("disposable_data") is False, "production target incorrectly identifies data as disposable")

    ready = client.get_json(_api_url(console_url, "/readyz"), headers=primary_headers)
    _require(ready.get("status") == "ready", "authorization readiness is not ready")
    _require(ready.get("mutation_authorization", {}).get("safe") is True, "mutation authorization is unsafe")
    actor_auth = ready.get("actor_authentication", {})
    _require(actor_auth.get("safe") is True and actor_auth.get("production_ready") is True, "actor authentication is not production-ready")
    checks.append({"name": "production_identity_and_authorization", "status": "ok"})

    campaigns = client.get_json(_api_url(console_url, "/campaigns"), headers=primary_headers)
    campaign_items = campaigns.get("items", [])
    campaign_ids = {str(item.get("id", "")).casefold() for item in campaign_items if isinstance(item, dict)}
    _require(campaigns.get("count") == 5 and campaign_ids == {"k1", "k2", "k3", "k4", "k5"}, "production does not expose exactly K1-K5")
    _require(campaigns.get("demo_data_included") is False, "campaign response included demo data")

    states = client.get_json(_api_url(console_url, "/workflows/states?limit=100&include_demo=false"), headers=primary_headers)
    _require(states.get("demo_data_included") is False, "state response included demo data")
    state_items = [item for item in states.get("items", []) if isinstance(item, dict)]
    for item in state_items:
        content_id = str(item.get("content_id", "")).casefold() if isinstance(item, dict) else ""
        _require(not any(marker in content_id for marker in FORBIDDEN_STATE_MARKERS), f"test/demo state escaped production filtering: {content_id}")
    generation_evidence = _verify_current_campaign_content(
        console_url=console_url,
        campaign_items=campaign_items,
        headers=primary_headers,
        client=client,
    )
    research_evidence = _verify_campaign_research(
        console_url=console_url,
        campaign_items=campaign_items,
        headers=primary_headers,
        client=client,
    )
    checks.append(
        {
            "name": "five_canonical_campaigns_with_current_ai_and_research",
            "generations": generation_evidence,
            "research": research_evidence,
        }
    )

    integrations = client.get_json(_api_url(console_url, "/integrations/status"), headers=primary_headers)
    _require(integrations.get("status") == "ok", "required integration status is degraded")
    for item in integrations.get("required", []):
        _require(isinstance(item, dict) and item.get("ok") is True, "a required integration is not ready")
    local_openai = _required_check(integrations, "local_openai")
    _require(local_openai.get("used_successfully") is True, "local Qwen has no successful generation evidence")
    _require(bool(local_openai.get("last_generation_model")), "local Qwen successful-use evidence has no model")
    comfyui = _required_check(integrations, "comfyui")
    _require(comfyui.get("model_bundle_ready") is True, "ComfyUI has no complete recognized model bundle")
    _require(comfyui.get("runtime_compatible") is True, "ComfyUI runtime packages do not match the pinned core")
    _require(not comfyui.get("package_mismatches"), "ComfyUI still reports package mismatches")
    _require(comfyui.get("used_successfully") is True, "ComfyUI has no successful qualified workflow evidence")
    _require(
        comfyui.get("workflow_qualification") == "history_verified",
        "ComfyUI workflow qualification is not backed by verified history",
    )
    _require(bool(comfyui.get("last_output_artifact")), "ComfyUI qualification has no output artifact")
    live_comfy_binding, qualification_completed_at = _comfyui_live_binding(comfyui)
    checks.append(
        {
            "name": "comfyui_technical_qualification",
            "status": "qualified_not_release_approved",
            "prompt_id": live_comfy_binding["prompt_id"],
            "output_sha256": live_comfy_binding["output_sha256"],
            "workflow_sha256": live_comfy_binding["workflow_sha256"],
            "runtime_identity_sha256": live_comfy_binding["runtime_identity_sha256"],
            "model_files_sha256": live_comfy_binding["model_files_sha256"],
        }
    )
    human_approval = _validate_comfyui_human_approvals(
        comfyui_approval_evidence,
        live_binding=live_comfy_binding,
        qualification_completed_at=qualification_completed_at,
    )
    checks.append(
        {
            "name": "comfyui_named_visual_and_license_approval",
            "status": "approved",
            **human_approval,
        }
    )
    n8n_integration = _required_check(integrations, "n8n")
    _require(n8n_integration.get("used_successfully") is True, "n8n has no persisted workflow execution evidence")
    _require(
        n8n_integration.get("verification_basis") == "persisted_trend_workflow_execution",
        "n8n verification is only an operator/environment attestation",
    )
    _require(bool(n8n_integration.get("last_execution_id")), "n8n verification has no execution id")
    searxng = _required_check(integrations, "searxng")
    _require(searxng.get("reachable") is True and searxng.get("used_successfully") is True, "SearxNG has no successful source-run evidence")
    phase_status = client.get_json(_api_url(console_url, "/workflows/phase-status"), headers=primary_headers)
    phases = {
        str(item.get("id", "")): item
        for item in phase_status.get("phases", [])
        if isinstance(item, dict)
    }
    for phase_id in ("08_lead_plane", "09_publishing_plane"):
        phase = phases.get(phase_id)
        _require(phase is not None, f"phase status did not include {phase_id}")
        assert phase is not None
        _require(
            phase.get("metadata", {}).get("external_writes_enabled") is False,
            f"external provider writes are enabled in {phase_id}; release acceptance requires them disabled",
        )
    checks.append({"name": "required_integrations_provenance_and_write_lock", "status": "ok"})

    n8n_health = client.get(_api_url(n8n_url, "/healthz"), headers={"X-N8N-API-KEY": n8n_api_key})
    _require(200 <= n8n_health.status < 300, "n8n health endpoint is not successful")
    workflows = _fetch_n8n_workflows(client, n8n_url, n8n_api_key)
    expected_contract = _expected_n8n_contract()
    expected_ids = set(expected_contract)
    by_id: dict[str, list[dict[str, Any]]] = {}
    for workflow in workflows:
        workflow_id = str(workflow.get("id", "")).strip()
        _require(bool(workflow_id), "n8n workflow API returned a row without a stable id")
        by_id.setdefault(workflow_id, []).append(workflow)
    _require(
        len(workflows) == len(expected_ids) and set(by_id) == expected_ids,
        "n8n live workflow set does not exactly match the ten-definition release manifest",
    )

    headers = {"X-N8N-API-KEY": n8n_api_key}
    verified_workflows: list[dict[str, str | bool]] = []
    for workflow_id, expected in expected_contract.items():
        matches = by_id.get(workflow_id, [])
        _require(len(matches) == 1, f"n8n workflow {workflow_id} is not present exactly once")
        live = client.get_json(
            _api_url(n8n_url, f"/api/v1/workflows/{quote(workflow_id, safe='')}"),
            headers=headers,
        )
        canonical_live = _canonical_workflow_definition(live)
        live_hash = _canonical_json_sha256(canonical_live)
        expected_definition = expected["definition"]
        _require(
            canonical_live["name"] == expected_definition["name"],
            f"n8n workflow {workflow_id} has an unexpected name",
        )
        _require(
            canonical_live["active"] is expected_definition["active"],
            f"n8n workflow {workflow_id} has an unexpected active state",
        )
        _require(
            live_hash == expected["sha256"],
            f"n8n workflow {workflow_id} definition, settings, or credential references drifted",
        )
        verified_workflows.append(
            {
                "id": workflow_id,
                "name": str(canonical_live["name"]),
                "active": bool(canonical_live["active"]),
                "definition_sha256": live_hash,
            }
        )

    execution_id = str(n8n_integration.get("last_execution_id", "")).strip()
    _require(
        bool(SAFE_IDENTIFIER_RE.fullmatch(execution_id)),
        "n8n verification has an unsafe or invalid execution id",
    )
    execution = client.get_json(
        _api_url(
            n8n_url,
            f"/api/v1/executions/{quote(execution_id, safe='')}?includeData=false",
        ),
        headers=headers,
    )
    _require(str(execution.get("id", "")).strip() == execution_id, "n8n execution evidence id does not match")
    _require(
        str(execution.get("workflowId", "")).strip() == N8N_EXECUTION_EVIDENCE_WORKFLOW_ID,
        "n8n execution evidence is not from the required verified-trend workflow",
    )
    _require(execution.get("status") == "success", "n8n execution evidence was not successful")
    _require(execution.get("finished") is True, "n8n execution evidence is not finished")
    execution_completed_at = _recent_aware_timestamp(
        execution.get("stoppedAt"),
        label="n8n verified trend execution",
    )
    checks.append(
        {
            "name": "n8n_exact_marketing_workflow_state",
            "workflows": sorted(verified_workflows, key=lambda item: str(item["id"])),
            "execution": {
                "id": execution_id,
                "workflow_id": N8N_EXECUTION_EVIDENCE_WORKFLOW_ID,
                "completed_at": execution_completed_at.isoformat(),
                "status": "success",
            },
        }
    )
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only, fail-closed production release acceptance for the WAMOCON Marketing-Maschine."
    )
    parser.add_argument("--console-url", required=True, help="Trusted HTTPS URL for the production marketing console.")
    parser.add_argument("--n8n-url", required=True, help="Trusted HTTPS URL for production n8n.")
    parser.add_argument(
        "--operator-credentials-file",
        action="append",
        required=True,
        help="Repeat for at least two protected files containing distinct named-account credentials as username:password.",
    )
    parser.add_argument("--n8n-api-key-file", required=True, help="Protected file containing a read-only-capable n8n API key.")
    parser.add_argument(
        "--comfyui-approval-file",
        required=True,
        help="Protected JSON evidence containing distinct named visual and license approvals bound to the live qualification.",
    )
    parser.add_argument("--ca-file", default="", help="Optional private CA bundle. TLS verification and hostname checks remain mandatory.")
    parser.add_argument("--timeout", type=float, default=12.0, help="Per-request timeout in seconds.")
    args = parser.parse_args()

    operators = [load_operator(path) for path in args.operator_credentials_file]
    n8n_api_key = _secret_file(args.n8n_api_key_file, label="n8n API key")
    approval_path = Path(args.comfyui_approval_file).expanduser()
    try:
        if approval_path.is_symlink():
            raise RuntimeError("ComfyUI approval evidence must not be a symbolic link")
        if os.name == "posix" and approval_path.stat().st_mode & 0o022:
            raise RuntimeError("ComfyUI approval evidence must not be writable by group or other users")
        comfyui_approval_evidence = json.loads(approval_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"cannot read ComfyUI approval evidence file {approval_path}") from exc
    if not isinstance(comfyui_approval_evidence, dict):
        raise RuntimeError("ComfyUI approval evidence must be a JSON object")
    client = ReadOnlyHttpClient(ca_file=args.ca_file, timeout=max(1.0, min(args.timeout, 60.0)))
    checks = run_acceptance(
        console_url=args.console_url,
        n8n_url=args.n8n_url,
        operators=operators,
        n8n_api_key=n8n_api_key,
        comfyui_approval_evidence=comfyui_approval_evidence,
        client=client,
    )
    print(json.dumps({"status": "ok", "read_only": True, "checks": checks}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "failed", "read_only": True, "error": str(exc)}, indent=2), file=sys.stderr)
        raise SystemExit(1)
