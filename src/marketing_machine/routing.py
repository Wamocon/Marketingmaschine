from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .governance import GovernancePolicy, PolicyAction
from .http_safety import read_limited
from .leads import lead_routing_block_reason, verify_lead_source_attribution
from .schemas import ContentStatus, utc_now
from .storage import JsonStore


class _NoRedirectHandler(HTTPRedirectHandler):
    """Never forward provider credentials across an HTTP redirect."""

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None


_NO_REDIRECT_OPENER = build_opener(_NoRedirectHandler())
POSTIZ_MEDIA_MAX_BYTES = 200 * 1024 * 1024


def urlopen(request: Request, timeout: int = 15) -> Any:
    """Compatibility seam for tests backed by a credential-safe opener."""

    return _NO_REDIRECT_OPENER.open(request, timeout=timeout)


def verify_postiz_media_url(
    url: str,
    *,
    expected_sha256: str,
    media_type: str,
) -> dict[str, Any]:
    """Hash the exact provider URL that will be placed in the Postiz payload.

    Postiz's public upload API returns an id and public path but no checksum.
    Fetching that exact path without credentials is therefore the strongest
    machine-verifiable binding available for a manually uploaded asset.  Live
    handoff repeats this check so an asset changed after approval fails closed.
    """

    expected = str(expected_sha256).strip().casefold()
    if len(expected) != 64 or any(character not in "0123456789abcdef" for character in expected):
        raise ValueError("approved media checksum is invalid")
    normalized_type = str(media_type).strip().casefold()
    expected_prefix = "video/" if normalized_type == "video" else "image/" if normalized_type == "image" else ""
    if not expected_prefix:
        raise ValueError("approved media type is invalid")

    request = Request(
        url,
        method="GET",
        headers={
            "Accept": f"{expected_prefix}*",
            "User-Agent": "wamocon-marketing-machine/0.1",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            get_final_url = getattr(response, "geturl", None)
            final_url = str(get_final_url() if callable(get_final_url) else url)
            if final_url != url:
                raise ValueError("Postiz media path redirected and cannot be bound safely")
            headers = getattr(response, "headers", {})
            content_type = str(headers.get("Content-Type", "")).split(";", 1)[0].strip().casefold()
            if not content_type.startswith(expected_prefix):
                raise ValueError("Postiz media content type does not match the approved asset")
            raw_length = str(headers.get("Content-Length", "")).strip()
            if raw_length:
                try:
                    content_length = int(raw_length)
                except ValueError as exc:
                    raise ValueError("Postiz media returned an invalid Content-Length") from exc
                if content_length < 1 or content_length > POSTIZ_MEDIA_MAX_BYTES:
                    raise ValueError("Postiz media size is outside the approved verification limit")

            digest = hashlib.sha256()
            total = 0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > POSTIZ_MEDIA_MAX_BYTES:
                    raise ValueError("Postiz media exceeds the approved verification limit")
                digest.update(chunk)
    except (HTTPError, URLError, OSError) as exc:
        raise ValueError("Postiz media could not be fetched for checksum verification") from exc

    observed = digest.hexdigest()
    if total < 1:
        raise ValueError("Postiz media is empty")
    if observed != expected:
        raise ValueError("Postiz media checksum does not match the human-approved artifact")
    return {
        "provider_verified": True,
        "provider_sha256": observed,
        "provider_bytes": total,
        "provider_content_type": content_type,
        "provider_verification_method": "postiz_public_url_sha256",
        "provider_verified_at": utc_now(),
        "provider_path": url,
    }


def route_scheduler_draft(
    *,
    store: JsonStore,
    policy: GovernancePolicy,
    content_id: str,
    target: str = "postiz",
    dry_run: bool = True,
) -> dict[str, Any]:
    if target != "postiz":
        return persist_outbox(store, outbox_record(
            kind="scheduler_draft",
            target=target,
            source_id=content_id,
            payload={},
            status="blocked",
            dry_run=dry_run,
            reason=f"unsupported scheduler target: {target}",
        ))

    decision = policy.check_tool("create_postiz_draft")
    if decision.action != PolicyAction.ALLOW:
        return persist_outbox(store, outbox_record(
            kind="scheduler_draft",
            target=target,
            source_id=content_id,
            payload={},
            status="blocked",
            dry_run=dry_run,
            reason=decision.reason,
        ))

    state = store.load_state(content_id)
    brief = state.get("brief", {})
    scheduler_payload = state.get("scheduler_payload", {})
    if brief.get("status") != ContentStatus.READY_TO_SCHEDULE.value or state.get("next_step") != "scheduler":
        return persist_outbox(store, outbox_record(
            kind="scheduler_draft",
            target=target,
            source_id=content_id,
            payload={},
            status="blocked",
            dry_run=dry_run,
            reason="content is not approved and ready for scheduler",
        ))
    if scheduler_payload.get("status") != "draft_only_requires_final_platform_approval":
        return persist_outbox(store, outbox_record(
            kind="scheduler_draft",
            target=target,
            source_id=content_id,
            payload={},
            status="blocked",
            dry_run=dry_run,
            reason="scheduler payload is missing draft-only approval guard",
        ))

    if not dry_run:
        for asset in state.get("approved_media_assets", []):
            if not isinstance(asset, dict) or asset.get("status") != "approved":
                continue
            if asset.get("provider_verified") is not True:
                continue
            try:
                verification = verify_postiz_media_url(
                    str(asset.get("postiz_path", "")),
                    expected_sha256=str(asset.get("sha256", "")),
                    media_type=str(asset.get("media_type", "")),
                )
            except ValueError as exc:
                return persist_outbox(store, outbox_record(
                    kind="scheduler_draft",
                    target=target,
                    source_id=content_id,
                    payload={},
                    status="blocked",
                    dry_run=True,
                    reason=f"Postiz media changed or cannot be verified immediately before handoff: {exc}",
                ))
            if verification.get("provider_sha256") != asset.get("provider_sha256"):
                return persist_outbox(store, outbox_record(
                    kind="scheduler_draft",
                    target=target,
                    source_id=content_id,
                    payload={},
                    status="blocked",
                    dry_run=True,
                    reason="Postiz media verification no longer matches the approved provider evidence",
                ))

    payload, payload_contract_ready, payload_contract_reason, payload_metadata = postiz_draft_payload(
        brief=brief,
        scheduler_payload=scheduler_payload,
        approved_media_assets=state.get("approved_media_assets", []),
    )
    result = send_or_prepare(
        kind="scheduler_draft",
        target="postiz",
        source_id=content_id,
        payload=payload,
        dry_run=dry_run,
        endpoint_env="POSTIZ_CREATE_DRAFT_PATH",
        base_url_env="POSTIZ_BASE_URL",
        token_env=("POSTIZ_API_KEY", "POSTIZ_API_TOKEN"),
        authorization_scheme="raw",
        verification_env="POSTIZ_CONTRACT_VERIFIED",
        store=store,
        payload_contract_ready=payload_contract_ready,
        payload_contract_reason=payload_contract_reason,
        payload_contract_metadata=payload_metadata,
    )
    return result


def route_lead(
    *,
    store: JsonStore,
    policy: GovernancePolicy,
    lead_id: str,
    target: str,
    dry_run: bool = True,
) -> dict[str, Any]:
    with store.lead_lock(lead_id):
        return _route_lead_locked(
            store=store,
            policy=policy,
            lead_id=lead_id,
            target=target,
            dry_run=dry_run,
        )


def _route_lead_locked(
    *,
    store: JsonStore,
    policy: GovernancePolicy,
    lead_id: str,
    target: str,
    dry_run: bool,
) -> dict[str, Any]:
    tool_name = "route_twenty_lead" if target == "twenty" else "route_mautic_lead" if target == "mautic" else "route_lead"
    decision = policy.check_tool(tool_name)
    if decision.action != PolicyAction.ALLOW:
        return persist_outbox(store, outbox_record(
            kind="lead",
            target=target,
            source_id=lead_id,
            payload={},
            status="blocked",
            dry_run=dry_run,
            reason=decision.reason,
        ))

    lead_result = store.load_lead(lead_id)
    lead = lead_result.get("lead", {})
    source_state: dict[str, Any] | None = None
    if isinstance(lead, dict):
        try:
            source_state = store.load_state(str(lead.get("source_content_id", "")))
        except (FileNotFoundError, ValueError):
            source_state = None
    source_verified, source_campaign_id, source_reason = verify_lead_source_attribution(
        lead if isinstance(lead, dict) else {},
        source_state,
        source_is_demo=store.is_demo_state(source_state or {}),
    )
    if (
        not source_verified
        or lead_result.get("source_verified") is not True
        or (isinstance(lead, dict) and lead.get("source_verified") is not True)
        or (isinstance(lead, dict) and lead.get("campaign_id") != source_campaign_id)
    ):
        return persist_outbox(store, outbox_record(
            kind="lead",
            target=target,
            source_id=lead_id,
            payload={},
            status="blocked",
            dry_run=dry_run,
            reason=source_reason or "lead source attribution is not verified",
        ))
    privacy_block_reason = lead_routing_block_reason(lead_result, target=target)
    if privacy_block_reason:
        return persist_outbox(store, outbox_record(
            kind="lead",
            target=target,
            source_id=lead_id,
            payload={},
            status="blocked",
            dry_run=dry_run,
            reason=privacy_block_reason,
        ))

    if target == "twenty":
        payload = lead_result.get("crm_payload", {})
        return send_or_prepare(
            kind="lead",
            target="twenty",
            source_id=lead_id,
            payload=payload,
            dry_run=dry_run,
            endpoint_env="TWENTY_CREATE_CONTACT_PATH",
            base_url_env="TWENTY_BASE_URL",
            token_env=("TWENTY_API_KEY", "TWENTY_API_TOKEN"),
            authorization_scheme="bearer",
            verification_env="TWENTY_CONTRACT_VERIFIED",
            store=store,
        )
    if target == "mautic":
        payload = lead_result.get("mautic_payload", {})
        return send_or_prepare(
            kind="lead",
            target="mautic",
            source_id=lead_id,
            payload=payload,
            dry_run=dry_run,
            endpoint_env="MAUTIC_CREATE_CONTACT_PATH",
            base_url_env="MAUTIC_BASE_URL",
            token_env=("MAUTIC_API_KEY", "MAUTIC_API_TOKEN"),
            authorization_scheme="bearer",
            verification_env="MAUTIC_CONTRACT_VERIFIED",
            store=store,
        )

    return persist_outbox(store, outbox_record(
        kind="lead",
        target=target,
        source_id=lead_id,
        payload={},
        status="blocked",
        dry_run=dry_run,
        reason=f"unsupported lead target: {target}",
    ))


def send_or_prepare(
    *,
    kind: str,
    target: str,
    source_id: str,
    payload: dict[str, Any],
    dry_run: bool,
    endpoint_env: str,
    base_url_env: str,
    token_env: tuple[str, ...],
    authorization_scheme: str = "bearer",
    verification_env: str = "",
    store: JsonStore | None = None,
    payload_contract_ready: bool = True,
    payload_contract_reason: str = "",
    payload_contract_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    writes_enabled = external_writes_enabled()
    base_url = os.environ.get(base_url_env, "").strip()
    endpoint_path = os.environ.get(endpoint_env, "").strip()
    token_name, token = first_env_value(token_env)
    contract_verified = bool(verification_env and truthy_env(verification_env))
    config = config_summary(
        writes_enabled,
        base_url,
        endpoint_path,
        token_name,
        token,
        authorization_scheme,
        contract_verified,
        verification_env,
    )
    config["payload_contract_ready"] = payload_contract_ready
    config.update(payload_contract_metadata or {})
    delivery_config_hash = delivery_config_fingerprint(
        base_url=base_url,
        endpoint_path=endpoint_path,
        token_name=token_name,
        token=token,
        authorization_scheme=authorization_scheme,
        contract_verified=contract_verified,
    )
    config["delivery_config_fingerprint"] = delivery_config_hash

    if not payload_contract_ready:
        return persist_outbox(
            store,
            outbox_record(
                kind=kind,
                target=target,
                source_id=source_id,
                payload=payload,
                status="blocked",
                dry_run=True,
                reason=payload_contract_reason or "provider payload contract is incomplete",
                config=config,
            ),
        )

    if dry_run:
        return persist_outbox(
            store,
            outbox_record(
            kind=kind,
            target=target,
            source_id=source_id,
            payload=payload,
            status="prepared",
            dry_run=True,
            reason="dry run: external write was not attempted",
            config=config,
            ),
        )
    if not writes_enabled:
        return persist_outbox(
            store,
            outbox_record(
            kind=kind,
            target=target,
            source_id=source_id,
            payload=payload,
            status="prepared",
            dry_run=True,
            reason="external writes are disabled; set MARKETING_MACHINE_ENABLE_EXTERNAL_WRITES=true to send",
            config=config,
            ),
        )
    if not base_url or not endpoint_path or not token:
        return persist_outbox(
            store,
            outbox_record(
            kind=kind,
            target=target,
            source_id=source_id,
            payload=payload,
            status="prepared",
            dry_run=True,
            reason="external write config incomplete; base URL, endpoint path, and token are required",
            config=config,
            ),
        )
    if not contract_verified:
        return persist_outbox(
            store,
            outbox_record(
            kind=kind,
            target=target,
            source_id=source_id,
            payload=payload,
            status="prepared",
            dry_run=True,
            reason=(
                f"external write contract is not verified; set {verification_env}=true only after an approved staging test"
            ),
            config=config,
            ),
        )

    pending = outbox_record(
        kind=kind,
        target=target,
        source_id=source_id,
        payload=payload,
        status="sending",
        dry_run=False,
        reason="external delivery started; reconciliation is required if completion is not recorded",
        config=config,
    )
    pending["delivery_config_fingerprint"] = delivery_config_hash

    def deliver(existing_record: dict[str, Any] | None = None) -> dict[str, Any]:
        if existing_record:
            pending["created_at"] = str(existing_record.get("created_at", pending["created_at"]))
            pending["reconciliation_events"] = list(existing_record.get("reconciliation_events", []))
            pending["retry_count"] = int(existing_record.get("retry_count", 0)) + (
                1 if existing_record.get("status") in {"failed_safe_to_retry", "confirmed_not_created"} else 0
            )
        persist_outbox(store, pending)
        try:
            response = post_json(
                f"{base_url.rstrip('/')}/{endpoint_path.lstrip('/')}",
                payload,
                token,
                authorization_scheme=authorization_scheme,
                idempotency_key=pending["idempotency_key"],
            )
            result = outbox_record(
            kind=kind,
            target=target,
            source_id=source_id,
            payload=payload,
            status="sent",
            dry_run=False,
            response=response,
            config=config,
            route_id=pending["id"],
            request_fingerprint=pending["request_fingerprint"],
            created_at=pending["created_at"],
            external_reference=external_reference(response),
            )
            result["delivery_config_fingerprint"] = delivery_config_hash
            result["retry_authorized"] = False
        except HTTPError as exc:
            definite_rejection = exc.code in {400, 401, 403, 404, 405, 413, 415, 422}
            rate_limited = exc.code == 429
            result = outbox_record(
                kind=kind,
                target=target,
                source_id=source_id,
                payload=payload,
                status=(
                    "rate_limited"
                    if rate_limited
                    else "failed_safe_to_retry"
                    if definite_rejection
                    else "delivery_unknown"
                ),
                dry_run=False,
                reason=(
                    f"provider definitely rejected request with HTTP {exc.code}; configuration may be corrected and retried"
                    if definite_rejection
                    else "provider rate limit reached; retry is blocked until Retry-After"
                    if rate_limited
                    else f"delivery outcome requires reconciliation before retry: HTTP {exc.code}"
                ),
                config=config,
                route_id=pending["id"],
                request_fingerprint=pending["request_fingerprint"],
                created_at=pending["created_at"],
            )
            result["delivery_config_fingerprint"] = delivery_config_hash
            if rate_limited:
                result["retry_after_at"] = retry_after_at(exc)
        except (OSError, URLError) as exc:
            # A timeout, disconnect, or HTTP error can happen after the remote
            # service committed a write.  Never invite a blind automatic retry.
            result = outbox_record(
            kind=kind,
            target=target,
            source_id=source_id,
            payload=payload,
            status="delivery_unknown",
            dry_run=False,
            reason=f"delivery outcome requires reconciliation before retry: {exc}",
            config=config,
            route_id=pending["id"],
            request_fingerprint=pending["request_fingerprint"],
            created_at=pending["created_at"],
            )
            result["delivery_config_fingerprint"] = delivery_config_hash
        if pending.get("reconciliation_events"):
            result["reconciliation_events"] = pending["reconciliation_events"]
        if pending.get("retry_count"):
            result["retry_count"] = pending["retry_count"]
        return persist_outbox(store, result)

    if store is None:
        return deliver()

    with store.outbox_lock(pending["id"]):
        try:
            existing = store.load_outbox(pending["id"])
        except FileNotFoundError:
            existing = None
        if existing is not None:
            if existing.get("request_fingerprint") != pending["request_fingerprint"]:
                raise ValueError("outbox operation id collision")
            existing_status = str(existing.get("status", ""))
            if existing_status == "rate_limited":
                retry_after = parse_utc(str(existing.get("retry_after_at", "")))
                if retry_after is None or datetime.now(timezone.utc) < retry_after:
                    result = dict(existing)
                    result["idempotent"] = True
                    return result
            if existing_status == "failed_safe_to_retry":
                config_unchanged = (
                    existing.get("delivery_config_fingerprint") == delivery_config_hash
                )
                if config_unchanged and not existing.get("retry_authorized"):
                    result = dict(existing)
                    result["idempotent"] = True
                    return result
            if existing_status in {"sending", "sent", "delivery_unknown", "confirmed", "reconciled"}:
                result = dict(existing)
                result["idempotent"] = True
                return result
        return deliver(existing)


def post_json(
    url: str,
    payload: dict[str, Any],
    token: str,
    *,
    authorization_scheme: str = "bearer",
    idempotency_key: str = "",
) -> dict[str, Any]:
    if authorization_scheme not in {"bearer", "raw"}:
        raise ValueError(f"unsupported authorization scheme: {authorization_scheme}")
    data = json.dumps(payload).encode("utf-8")
    authorization = token if authorization_scheme == "raw" else f"Bearer {token}"
    headers = {
        "Authorization": authorization,
        "Content-Type": "application/json",
        "User-Agent": "wamocon-marketing-machine/0.1",
    }
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
        headers["X-Correlation-ID"] = idempotency_key
    request = Request(
        url,
        data=data,
        method="POST",
        headers=headers,
    )
    with urlopen(request, timeout=15) as response:
        # urllib follows redirects by default and may rewrite a POST to GET for
        # 301/302/303 responses. A final 2xx at a different URL therefore does
        # not prove that the intended provider write was accepted. Preserve the
        # operation as ambiguous so reconciliation, never a blind retry, decides
        # what happened.
        get_final_url = getattr(response, "geturl", None)
        final_url = str(get_final_url() if callable(get_final_url) else url)
        if final_url != url:
            raise URLError("provider write followed a redirect; delivery outcome is ambiguous")
        try:
            raw = read_limited(response, label="provider write response").decode("utf-8")
        except (UnicodeDecodeError, ValueError) as exc:
            # The request may already have committed remotely. An unreadable or
            # oversized success response cannot prove either success or
            # rejection, so callers must reconcile instead of retrying.
            raise URLError(f"provider write response could not be verified: {exc}") from exc
        if not raw:
            body: Any = {}
        else:
            try:
                body = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise URLError("provider write returned invalid JSON; delivery outcome is ambiguous") from exc
        return {"status": response.status, "body": body}


def get_json(url: str, token: str) -> dict[str, Any]:
    """Perform a side-effect-free provider read with raw API-key auth."""

    request = Request(
        url,
        method="GET",
        headers={
            "Authorization": token,
            "Accept": "application/json",
            "User-Agent": "wamocon-marketing-machine/0.1",
        },
    )
    with urlopen(request, timeout=15) as response:
        raw = read_limited(response, label="provider reconciliation response").decode("utf-8")
        if not raw:
            return {}
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("provider read response must be a JSON object")
        return payload


def outbox_record(
    *,
    kind: str,
    target: str,
    source_id: str,
    payload: dict[str, Any],
    status: str,
    dry_run: bool,
    reason: str = "",
    response: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
    route_id: str = "",
    request_fingerprint: str = "",
    created_at: str = "",
    external_reference: str = "",
) -> dict[str, Any]:
    fingerprint = request_fingerprint or route_request_fingerprint(
        kind=kind,
        target=target,
        source_id=source_id,
        payload=payload,
        dry_run=dry_run,
    )
    now = utc_now()
    return {
        "id": route_id or f"route-{fingerprint[:20]}",
        "request_fingerprint": fingerprint,
        "idempotency_key": f"wamocon-{fingerprint}",
        "kind": kind,
        "target": target,
        "source_id": source_id,
        "status": status,
        "dry_run": dry_run,
        "reason": reason,
        "payload": payload,
        "response": response or {},
        "config": config or {},
        "external_reference": external_reference,
        "created_at": created_at or now,
        "updated_at": now,
    }


def route_request_fingerprint(
    *,
    kind: str,
    target: str,
    source_id: str,
    payload: dict[str, Any],
    dry_run: bool,
) -> str:
    encoded = json.dumps(
        {
            "kind": kind,
            "target": target,
            "source_id": source_id,
            "payload": payload,
            "dry_run": dry_run,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def delivery_config_fingerprint(
    *,
    base_url: str,
    endpoint_path: str,
    token_name: str,
    token: str,
    authorization_scheme: str,
    contract_verified: bool,
) -> str:
    # API keys are never stored. Their digest is bound to the rest of the
    # delivery config solely to detect a credential/config change after a
    # definite provider rejection.
    token_digest = hashlib.sha256(token.encode("utf-8")).hexdigest() if token else ""
    encoded = json.dumps(
        {
            "base_url": base_url,
            "endpoint_path": endpoint_path,
            "token_name": token_name,
            "token_digest": token_digest,
            "authorization_scheme": authorization_scheme,
            "contract_verified": contract_verified,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def retry_after_at(error: HTTPError) -> str:
    raw = str(error.headers.get("Retry-After", "")).strip() if error.headers else ""
    now = datetime.now(timezone.utc)
    if raw.isdigit():
        return (now + timedelta(seconds=max(1, min(int(raw), 86_400)))).isoformat()
    if raw:
        try:
            parsed = parsedate_to_datetime(raw)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).isoformat()
        except (TypeError, ValueError, OverflowError):
            pass
    return (now + timedelta(minutes=1)).isoformat()


def parse_utc(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def persist_outbox(store: JsonStore | None, record: dict[str, Any]) -> dict[str, Any]:
    if store is not None:
        store.save_outbox(record)
    return record


def external_reference(response: dict[str, Any]) -> str:
    """Extract a provider identifier without assuming one vendor response shape."""

    body: Any = response.get("body", {})
    candidates: list[Any] = [body]
    if isinstance(body, list):
        candidates.extend(body)
    if isinstance(body, dict):
        candidates.extend(body.get(key) for key in ("data", "post", "contact", "result"))
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        for key in ("id", "_id", "postId", "contactId", "external_id"):
            value = str(candidate.get(key, "")).strip()
            if value:
                return value[:256]
    return ""


def postiz_draft_payload(
    *,
    brief: dict[str, Any],
    scheduler_payload: dict[str, Any],
    approved_media_assets: Any = None,
) -> tuple[dict[str, Any], bool, str, dict[str, Any]]:
    """Translate the governed internal draft into Postiz's public API schema."""

    channel = str(brief.get("channel", "")).strip().casefold()
    media_assets = approved_media_assets if isinstance(approved_media_assets, list) else []
    active_media = [
        asset
        for asset in media_assets
        if isinstance(asset, dict) and asset.get("status") == "approved"
    ]
    approved_media = [
        asset
        for asset in active_media
        if asset.get("status") == "approved"
        and asset.get("postiz_media_id")
        and asset.get("postiz_path")
        and asset.get("provider_verified") is True
        and asset.get("provider_verification_method") == "postiz_public_url_sha256"
        and asset.get("provider_sha256") == asset.get("sha256")
        and asset.get("provider_path") == asset.get("postiz_path")
    ]
    draft_date = str(
        brief.get("updated_at")
        or brief.get("created_at")
        or "1970-01-01T00:00:00+00:00"
    )
    if channel == "linkedin":
        integration_env = "POSTIZ_LINKEDIN_INTEGRATION_ID"
        provider_type = os.environ.get("POSTIZ_LINKEDIN_PROVIDER_TYPE", "linkedin").strip()
        allowed_types = {"linkedin", "linkedin-page"}
        settings: dict[str, Any] = {
            "__type": provider_type,
            "post_as_images_carousel": False,
        }
    elif channel == "instagram":
        integration_env = "POSTIZ_INSTAGRAM_INTEGRATION_ID"
        provider_type = os.environ.get("POSTIZ_INSTAGRAM_PROVIDER_TYPE", "instagram").strip()
        allowed_types = {"instagram", "instagram-standalone"}
        settings = {
            "__type": provider_type,
            "post_type": "post",
            "is_trial_reel": False,
            "collaborators": [],
        }
    else:
        return (
            {
                "type": "draft",
                "date": draft_date,
                "shortLink": False,
                "tags": [],
                "posts": [],
            },
            False,
            f"unsupported Postiz channel: {brief.get('channel', '')}",
            {"media_asset_attached": False},
        )

    integration_id = os.environ.get(integration_env, "").strip()
    ready = bool(integration_id and provider_type in allowed_types)
    reason = ""
    if not integration_id:
        reason = f"{integration_env} is required before a Postiz draft can be sent"
    elif provider_type not in allowed_types:
        reason = (
            f"invalid provider type for {integration_env}: {provider_type}; "
            f"expected one of {', '.join(sorted(allowed_types))}"
        )
    if len(approved_media) != len(active_media):
        ready = False
        reason = (
            "attached media is not checksum-verified against the exact Postiz path; "
            "verify or replace the asset before handoff"
        )

    selected_media = approved_media
    if channel == "instagram":
        is_reel = "reel" in str(brief.get("format", "")).casefold()
        if is_reel:
            selected_media = [asset for asset in approved_media if asset.get("media_type") == "video"]
            if len(selected_media) != 1:
                ready = False
                reason = "exactly one active approved Postiz-uploaded video asset is required before this Instagram Reel draft can be handed off"
        elif not selected_media:
            ready = False
            reason = "an approved Postiz-uploaded media asset is required before an Instagram draft can be handed off"
    provider_media = [
        {"id": str(asset["postiz_media_id"]), "path": str(asset["postiz_path"])}
        for asset in selected_media
    ]

    return (
        {
            "type": "draft",
            # Postiz requires an ISO date even though it ignores scheduling for drafts.
            "date": draft_date,
            "shortLink": False,
            "tags": [],
            "posts": [
                {
                    "integration": {"id": integration_id},
                    "value": [
                        {
                            "content": str(scheduler_payload.get("copy", "")),
                            "image": provider_media,
                        }
                    ],
                    "settings": settings,
                }
            ],
        },
        ready,
        reason,
        {
            "draft_scope": "approved_media" if provider_media else "text_only",
            "media_asset_attached": bool(provider_media),
            "media_asset_count": len(provider_media),
            "media_provider_verified": len(approved_media) == len(active_media),
        },
    )


def external_writes_enabled() -> bool:
    return os.environ.get("MARKETING_MACHINE_ENABLE_EXTERNAL_WRITES", "").strip().lower() in {"1", "true", "yes", "on"}


def truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def first_env_value(names: tuple[str, ...]) -> tuple[str, str]:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return name, value
    return names[0], ""


def config_summary(
    writes_enabled: bool,
    base_url: str,
    endpoint_path: str,
    token_name: str,
    token: str,
    authorization_scheme: str = "bearer",
    contract_verified: bool = False,
    verification_env: str = "",
) -> dict[str, Any]:
    return {
        "writes_enabled": writes_enabled,
        "base_url_configured": bool(base_url),
        "endpoint_path_configured": bool(endpoint_path),
        "token_env": token_name,
        "token_configured": bool(token),
        "authorization_scheme": authorization_scheme,
        "contract_verified": contract_verified,
        "verification_env": verification_env,
    }
