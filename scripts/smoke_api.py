from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


def request_json(
    method: str,
    base_url: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    auth_header: tuple[str, str] | dict[str, str] | None = None,
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json", "User-Agent": "wamocon-smoke-test/0.2"}
    if isinstance(auth_header, dict):
        headers.update(auth_header)
    elif auth_header:
        headers[auth_header[0]] = auth_header[1]
    request = Request(
        url,
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        secret_values = auth_header.values() if isinstance(auth_header, dict) else (
            [auth_header[1]] if auth_header else []
        )
        for secret_value in secret_values:
            if secret_value:
                body = body.replace(secret_value, "<redacted>")
        raise RuntimeError(f"{method} {url} failed with HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"{method} {url} failed: {exc}") from exc


def load_secret(file_path: str, env_name: str) -> str:
    """Load a request credential without accepting it as a CLI value."""

    if file_path:
        path = Path(file_path).expanduser()
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RuntimeError(f"cannot read credential file {path}: {exc}") from exc
        if not value:
            raise RuntimeError(f"credential file is empty: {path}")
    else:
        value = os.environ.get(env_name, "").strip()
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in value):
        raise RuntimeError(f"credential from file or {env_name} contains a control character")
    return value


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def make_content_payload(content_id: str) -> dict[str, Any]:
    return {
        "id": content_id,
        "content_mode": "evergreen",
        "campaign": "Smoke Test QA Risk Audit",
        "persona": "IT-Leiter Thomas",
        "channel": "LinkedIn",
        "format": "expert_post",
        "language": "de-DE",
        "objective": "Den gesteuerten WAMOCON-Content-Workflow mit einem QA-Risikoaudit prüfen.",
        "cta": "QA-Risikoaudit anfragen",
        "proof_sources": ["Kampagnen/kampagne_1_consulting_qa.json"],
        "utm": {
            "utm_source": "linkedin",
            "utm_medium": "organic",
            "utm_campaign": "smoke_test_qa_risk_audit",
        },
        "hypothesis": "Ein nachweisbasierter QA-Beitrag erzeugt qualifizierte Anfragen von IT-Leitern.",
        "test_variable": "smoke_test",
    }


def make_approval_payload(content_id: str) -> dict[str, Any]:
    return {
        "content_id": content_id,
        "reviewer": "smoke-test",
        "decision": "approved",
        "brand_score": 95,
        "fact_check_passed": True,
        "privacy_check_passed": True,
        "ai_disclosure_check_passed": True,
        "notes": "Smoke-test approval. Do not publish without final human review in the scheduler.",
    }


def make_lead_payload(content_id: str, lead_id: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    return {
        "id": lead_id,
        "source_content_id": content_id,
        "campaign": "Smoke Test QA Risk Audit",
        "offer": "QA-Risikoaudit",
        "persona": "IT-Leiter Thomas",
        "contact_name": "Max Mustermann",
        "company": "Muster GmbH",
        "email": "it-leitung@muster-gmbh.de",
        "message": "Wir möchten einen QA-Risikoaudit Termin anfragen.",
        "consent_given": True,
        "consent_at": (now - timedelta(minutes=1)).isoformat(),
        "privacy_notice_version": "candidate-smoke-v1",
        "consent_source": "isolated_candidate_smoke",
        "consent_proof_ref": f"candidate-smoke-form-{lead_id}",
        "consent_purposes": ["contact_request", "marketing_automation"],
        "retention_policy": "isolated-candidate-24h",
        "retention_expires_at": (now + timedelta(hours=24)).isoformat(),
        "utm": {
            "utm_source": "linkedin",
            "utm_medium": "organic",
            "utm_campaign": "smoke_test_qa_risk_audit",
        },
    }


def test_agent_api(
    base_url: str,
    stamp: int,
    auth_header: tuple[str, str] | dict[str, str] | None = None,
) -> list[str]:
    checks: list[str] = []

    def call(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return request_json(method, base_url, path, payload, auth_header=auth_header)

    health = call("GET", "/healthz")
    assert_true(health.get("status") == "ok", f"healthz failed: {health}")
    checks.append("agent health")

    integrations = call("GET", "/integrations/status")
    assert_true(integrations.get("status") == "ok", f"integrations not ok: {integrations}")
    checks.append("n8n, ComfyUI, Ollama integration status")

    weekly = call("POST", "/workflows/weekly-planning", {})
    assert_true(weekly.get("status") == "accepted", f"weekly planning failed: {weekly}")
    assert_true(len(weekly.get("created", [])) >= 3, f"weekly planning created too few items: {weekly}")
    checks.append("rolling weekly planning")

    content_id = f"smoke-direct-{stamp}"
    created = call("POST", "/workflows/create-content", make_content_payload(content_id))
    assert_true(created.get("content_id") == content_id, f"create-content returned wrong id: {created}")
    assert_true(created.get("state", {}).get("next_step") == "human_review", f"content did not pause: {created}")
    checks.append("direct content creation with human-review pause")

    approval = call("POST", "/workflows/approve-content", make_approval_payload(content_id))
    state = approval.get("state", {})
    assert_true(state.get("next_step") == "scheduler", f"approval did not advance to scheduler: {approval}")
    assert_true(state.get("brief", {}).get("status") == "ready_to_schedule", f"approval status wrong: {approval}")
    assert_true(state.get("scheduler_payload", {}).get("status") == "draft_only_requires_final_platform_approval", f"scheduler guard missing: {approval}")
    assert_true("LinkedIn-Entwurf" in state.get("scheduler_payload", {}).get("copy", ""), f"scheduler copy missing German public post draft: {approval}")
    assert_true(bool(state.get("scheduler_payload", {}).get("evidence_records")), f"scheduler proof metadata missing: {approval}")
    checks.append("direct approval and guarded scheduler payload")

    route = call(
        "POST",
        "/workflows/route-scheduler-draft",
        {"content_id": content_id, "target": "postiz", "dry_run": True},
    )
    assert_true(route.get("status") == "prepared", f"Postiz draft route was not prepared: {route}")
    assert_true(route.get("route", {}).get("dry_run") is True, f"Postiz draft route did not stay dry-run: {route}")
    routed_state = call("GET", f"/workflows/states/{content_id}")
    assert_true(
        routed_state.get("brief", {}).get("status") == "ready_to_schedule",
        f"dry-run incorrectly advanced content lifecycle: {routed_state}",
    )
    assert_true(
        routed_state.get("lifecycle", {}).get("provider_status") != "published",
        f"dry-run fabricated a provider publication: {routed_state}",
    )
    checks.append("approved scheduler draft prepares Postiz outbox route")
    checks.append("dry-run does not fabricate scheduled or published lifecycle")

    lead = call("POST", "/workflows/lead-intake", make_lead_payload(content_id, f"smoke-lead-{stamp}"))
    assert_true(lead.get("status") == "accepted", f"lead intake failed: {lead}")
    assert_true(lead.get("routing_allowed") is True, f"lead was not routable: {lead}")
    assert_true(lead.get("lead", {}).get("next_action") == "sales_follow_up", f"lead action wrong: {lead}")
    assert_true(bool(lead.get("crm_payload")), f"CRM payload missing: {lead}")
    checks.append("lead intake scoring and CRM payload contract")

    lead_route = call(
        "POST",
        "/workflows/route-lead",
        {"lead_id": f"smoke-lead-{stamp}", "target": "twenty", "dry_run": True},
    )
    assert_true(lead_route.get("status") == "prepared", f"Twenty lead route was not prepared: {lead_route}")
    assert_true(lead_route.get("route", {}).get("dry_run") is True, f"Twenty lead route did not stay dry-run: {lead_route}")
    checks.append("qualified lead prepares Twenty outbox route")

    creative = call(
        "POST",
        "/workflows/comfyui-brief",
        {"campaign": "K5 App Development", "headline": "Proof beats promises"},
    )
    assert_true(creative.get("status") == "draft_created", f"ComfyUI brief failed: {creative}")
    assert_true(creative.get("comfyui_brief", {}).get("review_required") is True, f"creative review guard missing: {creative}")
    checks.append("ComfyUI creative brief contract")

    for review_window in ("72h", "7d", "14d", "30d"):
        due = call("GET", f"/workflows/analytics/due?review_window={review_window}")
        assert_true(due.get("writes_performed") is False, f"due lookup wrote state for {review_window}: {due}")
        assert_true(isinstance(due.get("items"), list), f"due lookup returned no item list for {review_window}: {due}")
        for item in due["items"]:
            assert_true(item.get("review_window") == review_window, f"wrong due window in {review_window}: {item}")
            assert_true(item.get("metrics_required") is True, f"due task does not require real metrics: {item}")
            assert_true(bool(item.get("published_at")) and bool(item.get("due_at")), f"due task lacks lifecycle timestamps: {item}")
            assert_true(
                item.get("action") == "collect_platform_and_crm_metrics_with_provenance",
                f"due task does not require auditable provenance: {item}",
            )
        assert_true(
            all(item.get("content_id") != content_id for item in due["items"]),
            f"unpublished dry-run content appeared in {review_window} analytics due tasks: {due}",
        )
    checks.append("read-only analytics due-task contract for 72h, 7d, 14d, and 30d")

    return checks


def test_agent_read_only(
    base_url: str,
    auth_header: tuple[str, str] | dict[str, str] | None = None,
) -> list[str]:
    """Verify a deployed instance without creating any durable records."""

    checks: list[str] = []

    def call(path: str) -> dict[str, Any]:
        return request_json("GET", base_url, path, auth_header=auth_header)

    health = call("/healthz")
    assert_true(health.get("status") == "ok", f"healthz failed: {health}")
    checks.append("agent health (read-only)")

    readiness = call("/readyz")
    assert_true(readiness.get("status") == "ready", f"readiness failed: {readiness}")
    checks.append("authorization readiness (read-only)")

    campaigns = call("/campaigns")
    campaign_items = campaigns.get("items", [])
    assert_true(campaigns.get("count") == 5, f"canonical campaign count is not five: {campaigns}")
    assert_true(
        {str(item.get("id", "")).casefold() for item in campaign_items} == {"k1", "k2", "k3", "k4", "k5"},
        f"canonical campaign IDs are not K1-K5: {campaign_items}",
    )
    checks.append("five canonical campaigns (read-only)")

    states = call("/workflows/states?limit=100&include_demo=false")
    forbidden = ("smoke", "mock", "placeholder", "demo")
    for item in states.get("items", []):
        content_id = str(item.get("content_id", "")).casefold()
        assert_true(not any(marker in content_id for marker in forbidden), f"demo state escaped filtering: {content_id}")
    checks.append("production state view excludes test data (read-only)")

    integrations = call("/integrations/status")
    assert_true(integrations.get("status") == "ok", f"integration status failed: {integrations}")
    checks.append("truthful integration status (read-only)")

    for review_window in ("72h", "7d", "14d", "30d"):
        due = call(f"/workflows/analytics/due?review_window={review_window}")
        assert_true(due.get("writes_performed") is False, f"due lookup wrote state: {due}")
        assert_true(isinstance(due.get("items"), list), f"due lookup has no item list: {due}")
    checks.append("analytics due queues (read-only)")
    return checks


def assert_isolated_candidate(
    base_url: str,
    auth_header: tuple[str, str] | dict[str, str] | None = None,
) -> None:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.port is None:
        raise RuntimeError("isolated candidate URL must include an explicit http(s) host and port")
    if parsed.port in {8117, 18117}:
        raise RuntimeError(
            "mutation smoke tests are forbidden on known production ports 8117/18117; use an isolated candidate with its own data directory"
        )
    health = request_json("GET", base_url, "/healthz", auth_header=auth_header)
    instance = health.get("instance", {})
    namespace = str(instance.get("data_namespace", ""))
    if not (
        instance.get("mode") == "isolated-candidate"
        and instance.get("disposable_data") is True
        and namespace.casefold().startswith("candidate-")
    ):
        raise RuntimeError(
            "target did not attest an isolated-candidate disposable data namespace; refusing record-creating smoke"
        )


def test_n8n_webhooks(
    n8n_url: str,
    stamp: int,
    auth_header: tuple[str, str] | None = None,
) -> list[str]:
    checks: list[str] = []
    content_id = f"smoke-n8n-{stamp}"

    def call(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return request_json(method, n8n_url, path, payload, auth_header=auth_header)

    created = call("POST", "/webhook/wamocon-marketing/content-intake", make_content_payload(content_id))
    assert_true(created.get("content_id") == content_id, f"n8n intake returned wrong id: {created}")
    assert_true(created.get("state", {}).get("next_step") == "human_review", f"n8n intake did not pause: {created}")
    checks.append("n8n manual intake webhook")

    approval = call("POST", "/webhook/wamocon-marketing/approve-content", make_approval_payload(content_id))
    state = approval.get("state", {})
    assert_true(state.get("next_step") == "scheduler", f"n8n approval did not advance: {approval}")
    assert_true(state.get("brief", {}).get("status") == "ready_to_schedule", f"n8n approval status wrong: {approval}")
    checks.append("n8n approval webhook")

    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test the WAMOCON Marketing-Maschine API and optional n8n webhooks.")
    parser.add_argument(
        "--base-url",
        required=True,
        help="Marketing API URL. It is required so the target is always chosen deliberately.",
    )
    parser.add_argument(
        "--access-token-file",
        default="",
        help="Optional file containing the direct-API mutation token. The token itself is never accepted as a CLI argument.",
    )
    parser.add_argument("--n8n-url", default="", help="Optional n8n base URL for webhook checks.")
    parser.add_argument(
        "--allow-mutations",
        action="store_true",
        help="Run record-creating checks. Allowed only on an isolated non-production candidate port.",
    )
    args = parser.parse_args()

    access_token = load_secret(args.access_token_file, "MARKETING_MACHINE_MUTATION_TOKEN")
    access_headers: dict[str, str] = {}
    if access_token:
        access_headers["X-WAMOCON-Mutation-Token"] = access_token
    test_actor = os.environ.get("MARKETING_MACHINE_TEST_ACTOR", "").strip()
    edge_attestation = os.environ.get("MARKETING_MACHINE_EDGE_ATTESTATION", "").strip()
    if bool(test_actor) != bool(edge_attestation):
        raise RuntimeError(
            "MARKETING_MACHINE_TEST_ACTOR and MARKETING_MACHINE_EDGE_ATTESTATION must be supplied together"
        )
    if test_actor:
        access_headers["X-WAMOCON-Actor"] = test_actor
        access_headers["X-WAMOCON-Edge-Attestation"] = edge_attestation
    access_header = access_headers or None
    if args.allow_mutations:
        assert_isolated_candidate(args.base_url, auth_header=access_header)
        stamp = int(time.time())
        checks = test_agent_api(args.base_url, stamp, auth_header=access_header)
    else:
        checks = test_agent_read_only(args.base_url, auth_header=access_header)
    if args.n8n_url:
        raise RuntimeError(
            "mutating n8n smoke is retired until n8n exposes a separately verified candidate-instance marker; test the candidate API only"
        )

    print(json.dumps({"status": "ok", "checks": checks}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, indent=2), file=sys.stderr)
        raise SystemExit(1)
