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
    headers = {"Content-Type": "application/json", "User-Agent": "wamocon-mock-pipeline-test/0.2"}
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
        with urlopen(request, timeout=25) as response:
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


def content_payload(content_id: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": content_id,
        "content_mode": "evergreen",
        "campaign": "Mock QA Risk Audit",
        "persona": "IT-Leiter Thomas",
        "channel": "LinkedIn",
        "format": "expert_post",
        "language": "de-DE",
        "objective": "Den gesteuerten Content-Workflow mit einem QA-Risikoaudit prüfen.",
        "cta": "QA-Risikoaudit anfragen",
        "proof_sources": ["Kampagnen/kampagne_1_consulting_qa.json"],
        "utm": {
            "utm_source": "linkedin",
            "utm_medium": "organic",
            "utm_campaign": "mock_qa_risk_audit",
        },
        "hypothesis": "Nachweisbasierter QA-Content erzeugt qualifizierte Anfragen von IT-Leitern.",
        "test_variable": "mock_edge_case",
    }
    payload.update(overrides)
    return payload


def approval_payload(content_id: str, **overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "content_id": content_id,
        "reviewer": "mock-test",
        "decision": "approved",
        "brand_score": 95,
        "fact_check_passed": True,
        "privacy_check_passed": True,
        "ai_disclosure_check_passed": True,
        "notes": "Mock approval. Scheduler must still keep draft-only final approval guard.",
    }
    payload.update(overrides)
    return payload


def lead_payload(content_id: str, lead_id: str, **overrides: Any) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "id": lead_id,
        "source_content_id": content_id,
        "campaign": "Mock QA Risk Audit",
        "offer": "QA-Risikoaudit",
        "persona": "IT-Leiter Thomas",
        "contact_name": "Max Mustermann",
        "company": "Muster GmbH",
        "email": "it-leitung@muster-gmbh.de",
        "message": "Wir möchten einen QA-Risikoaudit Termin anfragen.",
        "consent_given": True,
        "consent_at": (now - timedelta(minutes=1)).isoformat(),
        "privacy_notice_version": "candidate-mock-v1",
        "consent_source": "isolated_candidate_mock",
        "consent_proof_ref": f"candidate-mock-form-{lead_id}",
        "consent_purposes": ["contact_request", "marketing_automation"],
        "retention_policy": "isolated-candidate-24h",
        "retention_expires_at": (now + timedelta(hours=24)).isoformat(),
        "utm": {
            "utm_source": "linkedin",
            "utm_medium": "organic",
            "utm_campaign": "mock_qa_risk_audit",
        },
    }
    payload.update(overrides)
    return payload


def state_url(base_url: str, content_id: str) -> str:
    return f"{base_url.rstrip('/')}/workflows/states/{content_id}"


def run(
    base_url: str,
    n8n_url: str = "",
    *,
    auth_header: tuple[str, str] | dict[str, str] | None = None,
    webhook_auth_header: tuple[str, str] | None = None,
) -> dict[str, Any]:
    stamp = int(time.time())
    checks: list[str] = []
    created_ids: list[str] = []
    created_lead_ids: list[str] = []

    def api_request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return request_json(method, base_url, path, payload, auth_header=auth_header)

    def webhook_request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return request_json(method, n8n_url, path, payload, auth_header=webhook_auth_header)

    integrations = api_request("GET", "/integrations/status")
    assert_true(integrations.get("status") == "ok", f"required integrations are not ok: {integrations}")
    optional = {item["name"]: item for item in integrations.get("optional", [])}
    for name in ("postiz", "twenty", "mautic"):
        assert_true(optional.get(name, {}).get("ok") is True, f"{name} is not available: {optional.get(name)}")
    checks.append("required and growth-tool integrations")

    missing_proof = api_request(
        "POST",
        "/workflows/create-content",
        content_payload(f"mock-missing-proof-{stamp}", proof_sources=[]),
    )
    created_ids.append(f"mock-missing-proof-{stamp}")
    assert_true(missing_proof["state"]["brief"]["status"] == "blocked", f"missing proof was not blocked: {missing_proof}")
    checks.append("missing proof source is blocked")

    hashtag_spam = api_request(
        "POST",
        "/workflows/create-content",
        content_payload(
            f"mock-hashtag-spam-{stamp}",
            channel="Instagram",
            hashtags=["qa", "ki", "b2b", "testing", "automation", "software"],
            utm={"utm_source": "instagram", "utm_medium": "organic", "utm_campaign": "mock_ig"},
        ),
    )
    created_ids.append(f"mock-hashtag-spam-{stamp}")
    assert_true(hashtag_spam["state"]["brief"]["status"] == "blocked", f"hashtag spam was not blocked: {hashtag_spam}")
    checks.append("instagram hashtag spam is blocked")

    weak_id = f"mock-weak-approval-{stamp}"
    created_ids.append(weak_id)
    weak_created = api_request("POST", "/workflows/create-content", content_payload(weak_id))
    assert_true(weak_created["state"]["next_step"] == "human_review", f"weak approval setup failed: {weak_created}")
    weak_approval = api_request("POST", "/workflows/approve-content", approval_payload(weak_id, brand_score=89))
    assert_true(weak_approval["state"]["next_step"] == "revision", f"weak approval reached scheduler: {weak_approval}")
    assert_true(not weak_approval["state"].get("scheduler_payload"), f"weak approval created scheduler payload: {weak_approval}")
    checks.append("weak approval cannot schedule")

    approved_id = f"mock-approved-{stamp}"
    created_ids.append(approved_id)
    approved_created = api_request("POST", "/workflows/create-content", content_payload(approved_id))
    assert_true(approved_created["state"]["next_step"] == "human_review", f"approval setup failed: {approved_created}")
    approved = api_request("POST", "/workflows/approve-content", approval_payload(approved_id))
    assert_true(approved["state"]["next_step"] == "scheduler", f"approved content did not reach scheduler: {approved}")
    assert_true(
        approved["state"]["scheduler_payload"]["status"] == "draft_only_requires_final_platform_approval",
        f"scheduler final approval guard missing: {approved}",
    )
    assert_true(
        "LinkedIn-Entwurf" in approved["state"]["scheduler_payload"].get("copy", ""),
        f"approved scheduler payload does not contain generated German public copy: {approved}",
    )
    assert_true(
        bool(approved["state"]["scheduler_payload"].get("evidence_records")),
        f"approved scheduler payload does not contain proof metadata: {approved}",
    )
    checks.append("approved content creates guarded scheduler payload")
    checks.append("generated public copy is visible in scheduler draft")

    postiz_route = api_request(
        "POST",
        "/workflows/route-scheduler-draft",
        {"content_id": approved_id, "target": "postiz", "dry_run": True},
    )
    assert_true(postiz_route.get("status") == "prepared", f"Postiz draft route was not prepared: {postiz_route}")
    assert_true(postiz_route.get("route", {}).get("dry_run") is True, f"Postiz route performed an external write: {postiz_route}")
    assert_true(postiz_route.get("route", {}).get("payload", {}).get("status") == "draft", f"Postiz route payload is not draft: {postiz_route}")
    routed_state = api_request("GET", f"/workflows/states/{approved_id}")
    assert_true(
        routed_state.get("brief", {}).get("status") == "ready_to_schedule",
        f"dry-run incorrectly advanced content lifecycle: {routed_state}",
    )
    assert_true(
        routed_state.get("lifecycle", {}).get("provider_status") != "published",
        f"dry-run fabricated a provider publication: {routed_state}",
    )
    checks.append("approved draft is prepared for Postiz through dry-run outbox")
    checks.append("dry-run does not fabricate scheduled or published lifecycle")

    blocked_postiz_route = api_request(
        "POST",
        "/workflows/route-scheduler-draft",
        {"content_id": weak_id, "target": "postiz", "dry_run": True},
    )
    assert_true(blocked_postiz_route.get("status") == "blocked", f"weak content route was not blocked: {blocked_postiz_route}")
    checks.append("unapproved draft cannot route to Postiz")

    scored_lead_id = f"mock-lead-{stamp}"
    created_lead_ids.append(scored_lead_id)
    scored_lead = api_request("POST", "/workflows/lead-intake", lead_payload(approved_id, scored_lead_id))
    assert_true(scored_lead.get("status") == "accepted", f"lead intake failed: {scored_lead}")
    assert_true(scored_lead.get("routing_allowed") is True, f"qualified lead did not route: {scored_lead}")
    assert_true(scored_lead.get("lead", {}).get("next_action") == "sales_follow_up", f"qualified lead action wrong: {scored_lead}")
    assert_true(scored_lead.get("lead", {}).get("qualification_score", 0) >= 75, f"qualified lead score too low: {scored_lead}")
    assert_true(bool(scored_lead.get("crm_payload")), f"CRM payload missing for qualified lead: {scored_lead}")
    checks.append("qualified lead is scored and prepared for CRM follow-up")

    twenty_route = api_request(
        "POST",
        "/workflows/route-lead",
        {"lead_id": scored_lead_id, "target": "twenty", "dry_run": True},
    )
    assert_true(twenty_route.get("status") == "prepared", f"Twenty route was not prepared: {twenty_route}")
    assert_true(twenty_route.get("route", {}).get("payload", {}).get("external_id") == scored_lead_id, f"Twenty payload missing lead ID: {twenty_route}")
    checks.append("qualified lead is prepared for Twenty through dry-run outbox")

    no_consent_lead_id = f"mock-lead-no-consent-{stamp}"
    try:
        api_request(
            "POST",
            "/workflows/lead-intake",
            lead_payload(approved_id, no_consent_lead_id, consent_given=False),
        )
    except RuntimeError as exc:
        rejection = str(exc)
        assert_true("HTTP 422" in rejection and "affirmative" in rejection, f"wrong no-consent rejection: {rejection}")
    else:
        raise AssertionError("non-affirmative consent was accepted")
    checks.append("non-affirmative consent is rejected before PII storage or routing")

    for review_window in ("72h", "7d", "14d", "30d"):
        due = api_request("GET", f"/workflows/analytics/due?review_window={review_window}")
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
            all(item.get("content_id") != approved_id for item in due["items"]),
            f"unpublished dry-run content appeared in {review_window} analytics due tasks: {due}",
        )
    checks.append("read-only analytics due-task contract for all review windows")

    if n8n_url:
        if not webhook_auth_header:
            raise RuntimeError("n8n webhook checks require an inbound webhook credential")
        n8n_id = f"mock-n8n-{stamp}"
        created_ids.append(n8n_id)
        intake = webhook_request("POST", "/webhook/wamocon-marketing/content-intake", content_payload(n8n_id))
        assert_true(intake["state"]["next_step"] == "human_review", f"n8n intake did not pause: {intake}")
        n8n_approval = webhook_request("POST", "/webhook/wamocon-marketing/approve-content", approval_payload(n8n_id))
        assert_true(n8n_approval["state"]["next_step"] == "scheduler", f"n8n approval did not schedule: {n8n_approval}")
        checks.append("n8n manual intake and approval webhooks")

    return {
        "checks": checks,
        "created_content_ids": created_ids,
        "created_lead_ids": created_lead_ids,
        "fresh_result_urls": {content_id: state_url(base_url, content_id) for content_id in created_ids},
        "lead_list_url": f"{base_url.rstrip('/')}/workflows/leads",
        "outbox_url": f"{base_url.rstrip('/')}/workflows/outbox",
        "ui_url": f"{base_url.rstrip('/')}/ui",
        "approved_content_id": approved_id,
        "approved_state_url": state_url(base_url, approved_id),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run mock edge-case tests against the deployed WAMOCON pipeline.")
    parser.add_argument(
        "--base-url",
        required=True,
        help="Isolated candidate API URL. Production ports are rejected.",
    )
    parser.add_argument(
        "--access-token-file",
        default="",
        help="Optional file containing the direct-API mutation token. The token itself is never accepted as a CLI argument.",
    )
    parser.add_argument("--n8n-url", default="")
    parser.add_argument(
        "--webhook-token-file",
        default="",
        help="Optional file containing the n8n inbound webhook token. The token itself is never accepted as a CLI argument.",
    )
    parser.add_argument(
        "--isolated-candidate",
        action="store_true",
        help="Required acknowledgement that this target uses disposable candidate data.",
    )
    args = parser.parse_args()

    parsed = urlparse(args.base_url)
    if (
        not args.isolated_candidate
        or parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.port is None
        or parsed.port in {8117, 18117}
    ):
        raise RuntimeError(
            "mock pipeline tests are record-creating and may run only with --isolated-candidate on a non-production port"
        )

    if args.n8n_url:
        raise RuntimeError(
            "mutating n8n smoke is retired until n8n exposes a separately verified candidate-instance marker"
        )

    access_token = load_secret(args.access_token_file, "MARKETING_MACHINE_MUTATION_TOKEN")
    webhook_token = load_secret(args.webhook_token_file, "MARKETING_MACHINE_N8N_WEBHOOK_TOKEN")
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
    webhook_header = ("X-WAMOCON-Webhook-Token", webhook_token) if webhook_token else None
    health = request_json("GET", args.base_url, "/healthz", auth_header=access_header)
    instance = health.get("instance", {})
    namespace = str(instance.get("data_namespace", ""))
    if not (
        instance.get("mode") == "isolated-candidate"
        and instance.get("disposable_data") is True
        and namespace.casefold().startswith("candidate-")
    ):
        raise RuntimeError(
            "target did not attest an isolated-candidate disposable data namespace; refusing record-creating mock"
        )
    result = run(
        args.base_url,
        args.n8n_url,
        auth_header=access_header,
        webhook_auth_header=webhook_header,
    )
    print(json.dumps({"status": "ok", **result}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, indent=2), file=sys.stderr)
        raise SystemExit(1)
