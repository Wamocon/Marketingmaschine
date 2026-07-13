from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request

from .comfyui_qualification import (
    QUALIFICATION_MODEL,
    QUALIFICATION_NODE_INPUTS,
    QUALIFICATION_REQUIRED_PACKAGES,
    QUALIFICATION_TEXT_ENCODERS,
    QUALIFICATION_VAE,
    QUALIFICATION_WORKFLOW_SHA256,
    find_qualified_history_evidence,
    inspect_qualification_png,
    observed_runtime_identity,
)
from .trend_sources import firecrawl_endpoint_mode
from .http_safety import DEFAULT_JSON_RESPONSE_LIMIT, credential_safe_urlopen, read_limited


def urlopen(request: Request, timeout: float) -> Any:
    """Compatibility seam backed by the credential-safe no-redirect opener."""

    return credential_safe_urlopen(request, timeout=timeout)


def check_url(
    name: str,
    url: str,
    *,
    required: bool = False,
    capture_json: bool = False,
) -> dict[str, Any]:
    try:
        request = Request(url, headers={"User-Agent": "wamocon-marketing-machine/0.1"})
        with urlopen(request, timeout=5) as response:
            result = {
                "name": name,
                "ok": True,
                "required": required,
                "reachable": True,
                "configured": True,
                "used_successfully": False,
                "status": response.status,
                "url": url,
            }
            if capture_json:
                try:
                    payload = json.loads(
                        read_limited(response, max_bytes=DEFAULT_JSON_RESPONSE_LIMIT).decode("utf-8")
                    )
                except (json.JSONDecodeError, UnicodeDecodeError):
                    payload = None
                result["_probe_json"] = payload
            return result
    except (OSError, HTTPError, URLError, ValueError) as exc:
        return {
            "name": name,
            "ok": False,
            "required": required,
            "reachable": False,
            "configured": True,
            "used_successfully": False,
            "url": url,
            "error": str(exc),
        }


def check_growth_service(
    name: str,
    base_url: str,
    *,
    probe_path: str,
    endpoint_path: str,
    api_key: str,
    contract_verified: bool = False,
) -> dict[str, Any]:
    """Check a growth tool without confusing its public UI with API readiness.

    The probe is deliberately read-only. A reachable login page or health route
    proves that the service responds; it does not prove that an API token, exact
    write path, workspace schema, or payload contract has been accepted.
    """

    base_url = base_url.strip().rstrip("/")
    probe_url = f"{base_url}/{probe_path.lstrip('/')}" if base_url else ""
    endpoint_configured = bool(endpoint_path.strip())
    token_configured = bool(api_key.strip())
    configured = bool(base_url and endpoint_configured and token_configured)

    if not probe_url:
        return {
            "name": name,
            "ok": False,
            "required": False,
            "reachable": False,
            "configured": False,
            "used_successfully": False,
            "capability": "read_only_api_preflight",
            "endpoint_path_configured": endpoint_configured,
            "token_configured": token_configured,
            "write_ready": False,
            "contract_verified": contract_verified,
            "error": "base URL not configured",
        }

    result = check_url(name, probe_url, capture_json=name == "postiz")
    reachable = bool(result.get("reachable"))
    probe_payload = result.pop("_probe_json", None)
    registration_open = (
        probe_payload.get("register")
        if name == "postiz" and isinstance(probe_payload, dict)
        else None
    )
    registration_safe = name != "postiz" or registration_open is False
    if reachable and not registration_safe:
        result["ok"] = False
    result.update(
        {
            "configured": configured,
            "used_successfully": False,
            "capability": "read_only_api_preflight",
            "endpoint_path_configured": endpoint_configured,
            "token_configured": token_configured,
            "contract_verified": contract_verified,
            "registration_open": registration_open,
            "security_safe": registration_safe,
            "write_ready": reachable and configured and contract_verified and registration_safe,
            "action": (
                "Disable public registration and verify /api/auth/can-register returns register=false."
                if name == "postiz" and not registration_safe
                else "Service and write configuration are present; complete an approved, reversible contract test before enabling writes."
                if reachable and configured and not contract_verified
                else "Service, scoped credential, and staging-verified contract are ready; external writes remain governed separately."
                if reachable and configured and contract_verified
                else "Service is reachable, but its exact API path and scoped credential are not configured."
                if reachable
                else "Restore the service before configuring or testing its API contract."
            ),
        }
    )
    return result


def check_comfyui_generation_readiness(base_url: str, *, required: bool = False) -> dict[str, Any]:
    """Read-only verification of the exact qualified local generation runtime."""

    base_url = base_url.strip().rstrip("/")
    stats_url = f"{base_url}/system_stats" if base_url else ""
    result: dict[str, Any] = {
        "name": "comfyui",
        "ok": False,
        "required": required,
        "reachable": False,
        "configured": bool(base_url),
        "used_successfully": False,
        "capability": "generation_preflight",
        "url": stats_url,
        "recognized_models": [],
        "package_mismatches": [],
        "package_telemetry_complete": False,
        "model_bundle_ready": False,
        "runtime_compatible": False,
        "node_schemas_compatible": False,
        "workflow_qualification": "not_evaluated",
        "qualified_workflow_sha256": QUALIFICATION_WORKFLOW_SHA256,
        "last_output_artifact": "",
        "last_output_sha256": "",
        "last_output_bytes": 0,
        "qualification_runtime_identity_sha256": "",
        "qualification_model_files_sha256": "",
        "human_visual_approval_required": True,
        "human_visual_approval_verified": False,
    }
    if not base_url:
        result["error"] = "base URL not configured"
        return result

    try:
        stats = _get_json(stats_url)
        system = stats.get("system", {}) if isinstance(stats, dict) else {}
        package_mismatches = _comfy_package_mismatches(system)
        runtime_error = ""
        runtime_observation: dict[str, Any] | None = None
        try:
            runtime_observation = observed_runtime_identity(stats)
        except ValueError as exc:
            runtime_error = str(exc)

        node_payloads: dict[str, dict[str, Any]] = {}
        node_schema_errors: list[str] = []
        for node_name, required_inputs in QUALIFICATION_NODE_INPUTS.items():
            payload = _get_json(f"{base_url}/object_info/{quote(node_name, safe='')}")
            node_payloads[node_name] = payload
            if not _node_schema_accepts(payload, node_name, required_inputs):
                node_schema_errors.append(node_name)
        node_schemas_compatible = not node_schema_errors

        model_list = _loader_options(node_payloads["UNETLoader"], "UNETLoader", "unet_name")
        clip_name1_options = _loader_options(
            node_payloads["DualCLIPLoader"],
            "DualCLIPLoader",
            "clip_name1",
        )
        clip_name2_options = _loader_options(
            node_payloads["DualCLIPLoader"],
            "DualCLIPLoader",
            "clip_name2",
        )
        clip_names = sorted(set(clip_name1_options) | set(clip_name2_options))
        vae_names = _loader_options(node_payloads["VAELoader"], "VAELoader", "vae_name")
        valid_vaes: list[str] = []
        if QUALIFICATION_VAE in vae_names:
            try:
                vae_metadata = _get_json(
                    f"{base_url}/view_metadata/vae?filename={quote(QUALIFICATION_VAE, safe='')}"
                )
                if vae_metadata:
                    valid_vaes.append(QUALIFICATION_VAE)
            except (OSError, HTTPError, URLError, json.JSONDecodeError, TypeError, ValueError):
                pass

        model_bundle_ready = bool(
            QUALIFICATION_MODEL in model_list
            and QUALIFICATION_TEXT_ENCODERS[0] in clip_name1_options
            and QUALIFICATION_TEXT_ENCODERS[1] in clip_name2_options
            and QUALIFICATION_VAE in valid_vaes
        )
        package_telemetry_complete = runtime_observation is not None
        runtime_compatible = package_telemetry_complete and not package_mismatches
        generation_ready = model_bundle_ready and runtime_compatible and node_schemas_compatible
        qualification = "history_not_verified"
        qualification_evidence: dict[str, Any] | None = None
        output_evidence: dict[str, Any] | None = None
        history_probe_error = ""
        if runtime_observation is not None:
            try:
                history = _get_json(f"{base_url}/history?max_items=64")
                qualification_evidence = find_qualified_history_evidence(
                    history,
                    expected_runtime_observation=runtime_observation,
                )
                if qualification_evidence:
                    output = qualification_evidence.get("output")
                    if not isinstance(output, dict):
                        raise ValueError("qualification history has no output locator")
                    output_payload = _get_binary(
                        _comfy_output_url(base_url, output),
                        max_bytes=64 * 1024 * 1024,
                    )
                    output_evidence = inspect_qualification_png(output_payload)
                    qualification = "history_verified"
            except (OSError, HTTPError, URLError, json.JSONDecodeError, TypeError, ValueError) as exc:
                qualification = (
                    "history_output_unverified" if qualification_evidence else "history_unavailable"
                )
                history_probe_error = type(exc).__name__

        used_successfully = qualification_evidence is not None and output_evidence is not None
        result.update(
            {
                "ok": generation_ready,
                "reachable": True,
                "status": 200,
                "comfyui_version": str(system.get("comfyui_version", "")),
                "recognized_models": model_list,
                "recognized_model_count": len(model_list),
                "text_encoders": clip_names,
                "validated_vaes": valid_vaes,
                "package_mismatches": package_mismatches,
                "package_telemetry_complete": package_telemetry_complete,
                "runtime_error": runtime_error,
                "model_bundle_ready": model_bundle_ready,
                "runtime_compatible": runtime_compatible,
                "node_schemas_compatible": node_schemas_compatible,
                "node_schema_errors": node_schema_errors,
                "used_successfully": used_successfully,
                "workflow_qualification": qualification,
                "last_output_artifact": (
                    qualification_evidence["last_output_artifact"]
                    if qualification_evidence
                    else ""
                ),
                "qualification_prompt_id": (
                    qualification_evidence["prompt_id"] if qualification_evidence else ""
                ),
                "qualification_completed_at": (
                    qualification_evidence["completed_at"] if qualification_evidence else ""
                ),
                "qualification_seed": (
                    qualification_evidence["seed"] if qualification_evidence else None
                ),
                "qualification_runtime_identity_sha256": (
                    str(qualification_evidence.get("binding", {}).get("runtime_sha256", ""))
                    if qualification_evidence
                    and isinstance(qualification_evidence.get("binding"), dict)
                    else ""
                ),
                "qualification_model_files_sha256": (
                    str(qualification_evidence.get("binding", {}).get("model_files_sha256", ""))
                    if qualification_evidence
                    and isinstance(qualification_evidence.get("binding"), dict)
                    else ""
                ),
                "last_output_sha256": (
                    output_evidence["sha256"] if output_evidence else ""
                ),
                "last_output_bytes": output_evidence["bytes"] if output_evidence else 0,
                "history_probe_error": history_probe_error,
                "action": (
                    "Technical qualification is current and output-backed; a named person must still approve the visual."
                    if generation_ready and used_successfully
                    else "Run the guarded loopback qualification and retain its bound history and fetched output evidence."
                    if generation_ready
                    else "Restore the exact nonempty package telemetry and pinned runtime before qualifying a workflow."
                    if model_bundle_ready and not runtime_compatible
                    else "Restore every required core-node schema for the pinned workflow."
                    if model_bundle_ready and not node_schemas_compatible
                    else "Install a complete, licensed model bundle and its pinned loader, then verify it appears in ComfyUI object_info."
                ),
            }
        )
        return result
    except (OSError, HTTPError, URLError, json.JSONDecodeError, TypeError, ValueError) as exc:
        result["error"] = str(exc)
        return result


def _get_json(url: str) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": "wamocon-marketing-machine/0.1"})
    with urlopen(request, timeout=8) as response:
        payload = json.loads(
            read_limited(response, max_bytes=DEFAULT_JSON_RESPONSE_LIMIT).decode("utf-8")
        )
        if not isinstance(payload, dict):
            raise ValueError(f"expected JSON object from {url}")
        return payload


def _get_binary(url: str, *, max_bytes: int) -> bytes:
    request = Request(url, headers={"User-Agent": "wamocon-marketing-machine/0.1"})
    with urlopen(request, timeout=15) as response:
        return read_limited(response, max_bytes=max_bytes, label="ComfyUI output")


def _loader_options(payload: dict[str, Any], node_name: str, input_name: str) -> list[str]:
    options = payload.get(node_name, {}).get("input", {}).get("required", {}).get(input_name, [])
    if not (isinstance(options, list) and options and isinstance(options[0], list)):
        return []
    return sorted(str(item) for item in options[0] if str(item).strip())


def _node_schema_accepts(
    payload: dict[str, Any],
    node_name: str,
    workflow_inputs: set[str],
) -> bool:
    node = payload.get(node_name)
    if not isinstance(node, dict):
        return False
    node_input = node.get("input")
    if not isinstance(node_input, dict):
        return False
    accepted: set[str] = set()
    for group_name in ("required", "optional", "hidden"):
        group = node_input.get(group_name, {})
        if isinstance(group, dict):
            accepted.update(str(key) for key in group)
    return workflow_inputs.issubset(accepted)


def _comfy_package_mismatches(system: Any) -> list[dict[str, str]]:
    if not isinstance(system, dict):
        return [{"name": "telemetry", "installed": "", "required": "pinned runtime"}]
    rows = system.get("comfy_package_versions")
    if not isinstance(rows, list) or not rows:
        return [{"name": "telemetry", "installed": "missing", "required": "exact package set"}]
    mismatches: list[dict[str, str]] = []
    observed_names: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            mismatches.append(
                {"name": "telemetry", "installed": "invalid", "required": "object row"}
            )
            continue
        installed = str(row.get("installed", ""))
        expected = str(row.get("required", ""))
        name = str(row.get("name", ""))
        if name in observed_names:
            mismatches.append(
                {"name": name, "installed": "duplicate", "required": "one row"}
            )
        observed_names.add(name)
        if not installed or not expected or installed != expected:
            mismatches.append(
                {"name": name, "installed": installed, "required": expected}
            )
        elif name not in QUALIFICATION_REQUIRED_PACKAGES:
            mismatches.append(
                {"name": name, "installed": installed, "required": "not in pinned set"}
            )
        elif installed != QUALIFICATION_REQUIRED_PACKAGES[name]:
            mismatches.append(
                {
                    "name": name,
                    "installed": installed,
                    "required": QUALIFICATION_REQUIRED_PACKAGES[name],
                }
            )
    for missing in sorted(set(QUALIFICATION_REQUIRED_PACKAGES) - observed_names):
        mismatches.append(
            {
                "name": missing,
                "installed": "missing",
                "required": QUALIFICATION_REQUIRED_PACKAGES[missing],
            }
        )
    return mismatches


def _comfy_output_url(base_url: str, output: dict[str, Any]) -> str:
    return f"{base_url}/view?{urlencode({key: str(output.get(key, '')) for key in ('filename', 'subfolder', 'type')})}"


def check_firecrawl_configuration(
    base_url: str,
    api_key: str,
    *,
    allow_unauthenticated_self_hosted: bool = False,
) -> dict[str, Any]:
    """Report Firecrawl configuration without consuming a paid search credit.

    A successful Trend Studio run records actual adapter usage separately. This
    check deliberately says *configured*, not *working*, until that happens.
    """

    authentication_mode = firecrawl_endpoint_mode(
        base_url,
        api_key,
        allow_unauthenticated_self_hosted=allow_unauthenticated_self_hosted,
    )
    configured = authentication_mode != "unavailable"
    return {
        "name": "firecrawl",
        "ok": False,
        "required": False,
        "configured": configured,
        "reachable": None,
        "used_successfully": False,
        "capability": "configuration_only",
        "authentication_mode": authentication_mode,
        "url": base_url.rstrip("/") if base_url else "",
        "action": (
            "Configured; run a verified trend scan to prove successful use."
            if configured
            else "Set FIRECRAWL_API_KEY, or explicitly allow a private self-hosted Firecrawl endpoint, before using it for current-trend claims."
        ),
    }


def disabled_cloud_model_status(
    name: str,
    *,
    configured: bool,
    model_name: str = "",
) -> dict[str, Any]:
    """Describe a cloud model without sending credentials or network traffic."""

    return {
        "name": name,
        "ok": False,
        "required": False,
        "configured": configured,
        "reachable": None,
        "used_successfully": False,
        "disabled_by_policy": True,
        "capability": "disabled_by_policy",
        "model": model_name,
        "action": (
            "Cloud fallback is disabled by policy. Configure and validate the correct "
            "workload-appropriate endpoint, API key, and model before enabling it."
        ),
    }


def check_ollama_model(base_url: str, model_name: str, *, required: bool = False) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/api/tags"
    try:
        request = Request(url, headers={"User-Agent": "wamocon-marketing-machine/0.1"})
        with urlopen(request, timeout=5) as response:
            payload = json.loads(
                read_limited(response, max_bytes=DEFAULT_JSON_RESPONSE_LIMIT).decode("utf-8")
            )
            models = sorted(item.get("name", "") for item in payload.get("models", []) if item.get("name"))
            model_present = not model_name or model_name in models
            return {
                "name": "ollama",
                "ok": response.status == 200 and model_present,
                "required": required,
                "reachable": response.status == 200,
                "configured": bool(model_name),
                "used_successfully": False,
                "capability": "model_listing_only",
                "status": response.status,
                "url": url,
                "model": model_name,
                "model_present": model_present,
                "available_models": models,
            }
    except (OSError, HTTPError, URLError, json.JSONDecodeError, ValueError) as exc:
        return {
            "name": "ollama",
            "ok": False,
            "required": required,
            "reachable": False,
            "configured": bool(model_name),
            "used_successfully": False,
            "url": url,
            "model": model_name,
            "error": str(exc),
        }


def check_openai_compatible_models(
    name: str,
    base_url: str,
    api_key: str,
    model_name: str = "",
    *,
    required: bool = False,
) -> dict[str, Any]:
    base_url = base_url.rstrip("/")
    if not base_url:
        return {"name": name, "ok": False, "required": required, "configured": False, "error": "base URL not configured"}
    if not api_key:
        return {
            "name": name,
            "ok": False,
            "required": required,
            "configured": False,
            "reachable": False,
            "used_successfully": False,
            "url": f"{base_url}/models",
            "model": model_name,
            "error": "API key not configured",
        }

    url = f"{base_url}/models"
    try:
        request = Request(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "User-Agent": "wamocon-marketing-machine/0.1",
            },
        )
        with urlopen(request, timeout=8) as response:
            payload = json.loads(
                read_limited(response, max_bytes=DEFAULT_JSON_RESPONSE_LIMIT).decode("utf-8")
            )
            models = sorted(item.get("id", "") for item in payload.get("data", []) if item.get("id"))
            model_present = not model_name or model_name in models
            return {
                "name": name,
                "ok": response.status == 200 and model_present,
                "required": required,
                "configured": True,
                "reachable": response.status == 200,
                "used_successfully": False,
                "capability": "model_listing_only",
                "status": response.status,
                "url": url,
                "model": model_name,
                "model_present": model_present,
                "available_models": models,
            }
    except (OSError, HTTPError, URLError, json.JSONDecodeError, ValueError) as exc:
        return {
            "name": name,
            "ok": False,
            "required": required,
            "configured": True,
            "reachable": False,
            "used_successfully": False,
            "url": url,
            "model": model_name,
            "error": str(exc),
        }
