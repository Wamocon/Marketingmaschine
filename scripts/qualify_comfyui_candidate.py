from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import time
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen
import uuid


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from marketing_machine.comfyui_qualification import (  # noqa: E402
    QUALIFICATION_BINDING_KEY,
    QUALIFICATION_CANDIDATE_ROOT,
    QUALIFICATION_CORE_COMMIT,
    QUALIFICATION_HISTORY_MAX_AGE_SECONDS,
    QUALIFICATION_MODEL,
    QUALIFICATION_MODEL_FILES,
    QUALIFICATION_OUTPUT_PREFIX,
    QUALIFICATION_REQUIRED_PACKAGES,
    QUALIFICATION_TEXT_ENCODERS,
    QUALIFICATION_VAE,
    QUALIFICATION_WORKFLOW_SHA256,
    QUALIFICATION_XET_HASHES,
    build_qualification_binding,
    build_runtime_identity,
    canonical_payload_sha256,
    canonical_workflow_sha256,
    find_qualified_history_evidence,
    inspect_qualification_png,
    observed_runtime_identity,
    qualification_seed,
)


WORKFLOW_PATH = ROOT / "deploy" / "comfyui" / "flux-schnell-qualification-api.json"
MANIFEST_PATH = ROOT / "deploy" / "comfyui" / "flux-schnell-candidate-manifest.json"
MAX_JSON_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_OUTPUT_BYTES = 64 * 1024 * 1024
MODEL_HASH_CHUNK_BYTES = 8 * 1024 * 1024
APPROVED_CORE_NODES = frozenset(
    {
        "UNETLoader",
        "DualCLIPLoader",
        "VAELoader",
        "CLIPTextEncode",
        "FluxGuidance",
        "EmptySD3LatentImage",
        "ModelSamplingFlux",
        "KSampler",
        "VAEDecode",
        "SaveImage",
    }
)


class QualificationError(RuntimeError):
    pass


def validate_isolated_candidate_url(
    base_url: str, *, expected_port: int
) -> tuple[str, str]:
    """Validate a credential-free URL for the loopback-only candidate port."""

    parsed = urlparse(base_url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise QualificationError("candidate URL must use http or https")
    if parsed.username or parsed.password:
        raise QualificationError("credentials are forbidden in the candidate URL")
    if parsed.path not in {"", "/"} or parsed.params or parsed.query or parsed.fragment:
        raise QualificationError(
            "candidate URL must contain only scheme, host, and port"
        )
    try:
        port = parsed.port
    except ValueError as exc:
        raise QualificationError("candidate URL has an invalid port") from exc
    if not parsed.hostname or port is None:
        raise QualificationError("candidate URL must include an explicit host and port")
    if port != expected_port or port == 8188:
        raise QualificationError(
            f"candidate URL must use the pinned isolated port {expected_port}; production port 8188 is forbidden"
        )

    hostname = parsed.hostname.lower()
    if hostname != "localhost":
        try:
            address = ipaddress.ip_address(hostname)
        except ValueError as exc:
            raise QualificationError(
                "candidate host must be localhost or a literal loopback address"
            ) from exc
        if not address.is_loopback:
            raise QualificationError(
                "qualification is loopback-only; use an SSH session on the candidate host"
            )

    origin_host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
    return f"{parsed.scheme}://{origin_host}:{port}", "loopback"


def load_qualification_assets() -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        workflow = json.loads(WORKFLOW_PATH.read_text(encoding="utf-8"))
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QualificationError("cannot read the pinned qualification assets") from exc
    if not isinstance(workflow, dict) or not isinstance(manifest, dict):
        raise QualificationError("qualification assets must be JSON objects")

    if canonical_workflow_sha256(workflow) != QUALIFICATION_WORKFLOW_SHA256:
        raise QualificationError(
            "qualification workflow hash does not match the pinned constant"
        )
    if qualification_seed(workflow) is None:
        raise QualificationError(
            "qualification workflow has no valid deterministic seed"
        )
    node_types = {
        str(node.get("class_type", ""))
        for node in workflow.values()
        if isinstance(node, Mapping)
    }
    if not node_types or not node_types.issubset(APPROVED_CORE_NODES):
        raise QualificationError(
            "qualification workflow contains an unapproved or custom node"
        )

    if manifest.get("scope") != "isolated-candidate-only":
        raise QualificationError(
            "candidate manifest does not attest isolated-candidate-only scope"
        )
    guard = manifest.get("production_guard")
    runtime = manifest.get("runtime")
    readiness = manifest.get("readiness")
    if not isinstance(guard, Mapping) or not isinstance(runtime, Mapping):
        raise QualificationError("candidate manifest has no runtime production guard")
    if not isinstance(readiness, Mapping):
        raise QualificationError("candidate manifest has no readiness contract")
    if guard.get("candidate_bind") != "127.0.0.1":
        raise QualificationError("candidate manifest is not pinned to loopback")
    for false_guard in (
        "allow_custom_nodes",
        "allow_model_symlinks_to_production",
        "allow_production_service_restart",
    ):
        if guard.get(false_guard) is not False:
            raise QualificationError(
                f"candidate manifest permits unsafe setting {false_guard}"
            )
    if guard.get("candidate_root") != QUALIFICATION_CANDIDATE_ROOT:
        raise QualificationError(
            "candidate manifest root does not match the application constant"
        )
    commit = str(runtime.get("commit", ""))
    if commit != QUALIFICATION_CORE_COMMIT or not _is_sha256_like(commit, length=40):
        raise QualificationError(
            "candidate manifest must pin the full verified Git commit"
        )
    packages = runtime.get("required_packages")
    if (
        not isinstance(packages, Mapping)
        or dict(packages) != QUALIFICATION_REQUIRED_PACKAGES
    ):
        raise QualificationError(
            "candidate manifest does not pin the exact package set"
        )

    model_bundle = manifest.get("model_bundle")
    files = model_bundle.get("files") if isinstance(model_bundle, Mapping) else None
    if (
        not isinstance(model_bundle, Mapping)
        or not isinstance(files, list)
        or len(files) != 4
    ):
        raise QualificationError("candidate manifest must pin exactly four model files")
    declared_models: dict[str, dict[str, Any]] = {}
    for item in files:
        if not isinstance(item, Mapping):
            raise QualificationError("candidate manifest has an invalid model row")
        path = str(item.get("path", ""))
        declared_models[path] = {
            "bytes": item.get("bytes"),
            "sha256": str(item.get("sha256", "")).lower(),
        }
        xet_hash = str(item.get("xet_hash", "")).lower()
        if (
            xet_hash != QUALIFICATION_XET_HASHES.get(path)
            or xet_hash == declared_models[path]["sha256"]
        ):
            raise QualificationError(
                "candidate manifest confuses the informational Xet hash with file SHA-256"
            )
        if len(str(item.get("source_revision", ""))) != 40:
            raise QualificationError(
                "each model source must use a full immutable revision"
            )
        if item.get("gated_source") is not False:
            raise QualificationError(
                "qualification bundle may not depend on a gated source"
            )
    if declared_models != QUALIFICATION_MODEL_FILES:
        raise QualificationError(
            "candidate manifest model hashes or sizes do not match constants"
        )
    expected_total = 0
    for expected_file in QUALIFICATION_MODEL_FILES.values():
        expected_bytes = expected_file.get("bytes")
        if not isinstance(expected_bytes, int) or isinstance(expected_bytes, bool):
            raise QualificationError("application model size constant is invalid")
        expected_total += expected_bytes
    if model_bundle.get("expected_total_bytes") != expected_total:
        raise QualificationError("candidate manifest total model size is inconsistent")
    if readiness.get("workflow_sha256") != QUALIFICATION_WORKFLOW_SHA256:
        raise QualificationError(
            "candidate manifest pins a different qualification workflow"
        )
    if readiness.get("recognized_text_encoders") != list(QUALIFICATION_TEXT_ENCODERS):
        raise QualificationError(
            "candidate manifest reverses the official FLUX text encoders"
        )
    if readiness.get("dual_clip_loader_positions") != {
        "clip_name1": QUALIFICATION_TEXT_ENCODERS[0],
        "clip_name2": QUALIFICATION_TEXT_ENCODERS[1],
    }:
        raise QualificationError(
            "candidate manifest has invalid DualCLIPLoader positions"
        )
    if (
        readiness.get("history_max_age_seconds")
        != QUALIFICATION_HISTORY_MAX_AGE_SECONDS
    ):
        raise QualificationError(
            "candidate manifest has a different history freshness window"
        )
    if readiness.get("output_bytes_and_sha256_required") is not True:
        raise QualificationError(
            "candidate manifest must require fetched output bytes and SHA-256"
        )
    if readiness.get("human_visual_approval_required") is not True:
        raise QualificationError(
            "candidate manifest must keep human visual approval mandatory"
        )
    if readiness.get("automated_visual_approval_allowed") is not False:
        raise QualificationError(
            "candidate manifest must forbid automated visual approval"
        )
    return workflow, manifest


def resolve_candidate_root(candidate_root: str, manifest: Mapping[str, Any]) -> Path:
    guard = manifest.get("production_guard")
    if not isinstance(guard, Mapping):
        raise QualificationError("candidate manifest has no production guard")
    expected = Path(str(guard.get("candidate_root", ""))).expanduser()
    supplied = Path(candidate_root).expanduser()
    if not supplied.is_absolute() or os.path.normcase(
        os.path.normpath(str(supplied))
    ) != os.path.normcase(os.path.normpath(str(expected))):
        raise QualificationError(
            "--candidate-root must exactly match the pinned isolated root"
        )
    if _path_has_symlink_component(supplied):
        raise QualificationError(
            "candidate root or one of its parent components is a symbolic link"
        )
    try:
        resolved = supplied.resolve(strict=True)
    except OSError as exc:
        raise QualificationError("candidate root does not exist") from exc
    if not resolved.is_dir() or resolved != supplied:
        raise QualificationError(
            "candidate root did not resolve to the exact pinned directory"
        )

    forbidden_roots = guard.get("forbidden_roots")
    if not isinstance(forbidden_roots, list) or not forbidden_roots:
        raise QualificationError("candidate manifest has no forbidden production roots")
    for raw_forbidden in forbidden_roots:
        forbidden = Path(str(raw_forbidden)).expanduser().resolve(strict=False)
        if resolved == forbidden or forbidden in resolved.parents:
            raise QualificationError(
                "candidate root overlaps a forbidden production root"
            )
    git_dir = resolved / ".git"
    if git_dir.is_symlink() or not git_dir.is_dir():
        raise QualificationError("candidate root is not an isolated Git checkout")
    try:
        for path in resolved.rglob("*"):
            if path.is_symlink():
                raise QualificationError(
                    f"candidate root contains symbolic link: {path.relative_to(resolved)}"
                )
    except OSError as exc:
        raise QualificationError(
            "candidate root cannot be inspected completely"
        ) from exc
    return resolved


def verify_git_checkout(
    candidate_root: Path, *, expected_commit: str
) -> dict[str, Any]:
    if not _is_sha256_like(expected_commit, length=40):
        raise QualificationError("expected core commit is not a full Git object ID")
    commit = _run_git(candidate_root, "rev-parse", "--verify", "HEAD^{commit}")
    if commit != expected_commit:
        raise QualificationError(
            "candidate checkout does not match the pinned full Git commit"
        )
    dirty = _run_git(candidate_root, "status", "--porcelain", "--untracked-files=no")
    if dirty:
        raise QualificationError("candidate checkout has modified tracked files")
    custom_nodes = candidate_root / "custom_nodes"
    if not custom_nodes.is_dir() or custom_nodes.is_symlink():
        raise QualificationError(
            "candidate checkout has no trusted core custom_nodes directory"
        )
    permitted_core_entries = {
        "__pycache__",
        "example_node.py.example",
        "websocket_image_save.py",
    }
    try:
        unexpected = sorted(
            path.name
            for path in custom_nodes.iterdir()
            if path.name not in permitted_core_entries
        )
    except OSError as exc:
        raise QualificationError(
            "candidate custom_nodes directory cannot be inspected"
        ) from exc
    if unexpected:
        raise QualificationError(
            "candidate checkout contains a third-party custom node"
        )
    return {
        "commit": commit,
        "tracked_files_clean": True,
        "third_party_custom_nodes_present": False,
    }


def verify_model_files(
    candidate_root: Path,
    manifest: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    model_bundle = manifest.get("model_bundle")
    rows = model_bundle.get("files") if isinstance(model_bundle, Mapping) else None
    if not isinstance(rows, list) or len(rows) != 4:
        raise QualificationError(
            "candidate manifest must contain exactly four model files"
        )
    evidence: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            raise QualificationError("candidate manifest contains an invalid model row")
        relative_text = str(row.get("path", ""))
        relative = PurePosixPath(relative_text)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise QualificationError("candidate manifest contains an unsafe model path")
        model_path = candidate_root.joinpath(*relative.parts)
        if _path_has_symlink_component(model_path, stop=candidate_root):
            raise QualificationError(
                f"model path contains a symbolic link: {relative_text}"
            )
        try:
            resolved = model_path.resolve(strict=True)
        except OSError as exc:
            raise QualificationError(
                f"pinned model file is missing: {relative_text}"
            ) from exc
        if candidate_root not in resolved.parents or not resolved.is_file():
            raise QualificationError(
                f"model file escaped the candidate root: {relative_text}"
            )
        actual_bytes, actual_sha256 = _sha256_regular_file(resolved)
        expected_bytes = row.get("bytes")
        if actual_bytes != expected_bytes:
            raise QualificationError(f"model file size mismatch: {relative_text}")
        expected_sha256 = str(row.get("sha256", "")).lower()
        if actual_sha256 != expected_sha256:
            raise QualificationError(f"model file hash mismatch: {relative_text}")
        evidence[relative_text] = {"bytes": actual_bytes, "sha256": actual_sha256}
    if evidence != QUALIFICATION_MODEL_FILES:
        raise QualificationError(
            "observed model bundle is not the exact pinned four-file bundle"
        )
    return dict(sorted(evidence.items()))


def request_json(
    method: str,
    origin: str,
    path: str,
    payload: Mapping[str, Any] | None = None,
    *,
    timeout: float = 15.0,
) -> dict[str, Any]:
    raw = _request_bytes(
        method, origin, path, payload, timeout=timeout, limit=MAX_JSON_RESPONSE_BYTES
    )
    try:
        result = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError("candidate returned invalid JSON") from exc
    if not isinstance(result, dict):
        raise QualificationError("candidate returned a non-object JSON response")
    return result


def request_action(
    origin: str,
    path: str,
    payload: Mapping[str, Any],
    *,
    timeout: float = 15.0,
) -> None:
    _request_bytes(
        "POST", origin, path, payload, timeout=timeout, limit=MAX_JSON_RESPONSE_BYTES
    )


def _request_bytes(
    method: str,
    origin: str,
    path: str,
    payload: Mapping[str, Any] | None,
    *,
    timeout: float,
    limit: int,
) -> bytes:
    data = (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        if payload is not None
        else None
    )
    request = Request(
        f"{origin}{path}",
        data=data,
        method=method,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "wamocon-comfyui-candidate-qualification/2.0",
        },
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(limit + 1)
    except HTTPError as exc:
        raise QualificationError(f"candidate returned HTTP {exc.code}") from exc
    except (OSError, URLError) as exc:
        raise QualificationError("candidate request failed") from exc
    if len(raw) > limit:
        raise QualificationError("candidate response exceeded the safe size limit")
    return raw


def preflight_candidate(
    origin: str,
    workflow: Mapping[str, Any],
    *,
    candidate_port: int,
) -> dict[str, Any]:
    queue = request_json("GET", origin, "/queue")
    for queue_name in ("queue_running", "queue_pending"):
        queue_items = queue.get(queue_name)
        if not isinstance(queue_items, list) or queue_items:
            raise QualificationError("isolated candidate queue must exist and be empty")

    stats = request_json("GET", origin, "/system_stats")
    try:
        observed_runtime = observed_runtime_identity(stats)
    except ValueError as exc:
        raise QualificationError(str(exc)) from exc
    _validate_runtime_argv(observed_runtime["argv"], candidate_port=candidate_port)

    required_inputs: dict[str, set[str]] = {}
    for node in workflow.values():
        if not isinstance(node, Mapping):
            raise QualificationError("qualification workflow contains an invalid node")
        class_type = str(node.get("class_type", ""))
        inputs = node.get("inputs")
        if not class_type or not isinstance(inputs, Mapping):
            raise QualificationError(
                "qualification workflow node is missing its schema"
            )
        required_inputs.setdefault(class_type, set()).update(str(key) for key in inputs)

    node_payloads: dict[str, dict[str, Any]] = {}
    for node_type, inputs in sorted(required_inputs.items()):
        payload = request_json(
            "GET", origin, f"/object_info/{quote(node_type, safe='')}"
        )
        _validate_node_schema(payload, node_type, inputs)
        node_payloads[node_type] = payload

    if QUALIFICATION_MODEL not in _loader_options(
        node_payloads["UNETLoader"], "UNETLoader", "unet_name"
    ):
        raise QualificationError("candidate does not expose the pinned FLUX model")
    clip_name1_options = _loader_options(
        node_payloads["DualCLIPLoader"], "DualCLIPLoader", "clip_name1"
    )
    clip_name2_options = _loader_options(
        node_payloads["DualCLIPLoader"], "DualCLIPLoader", "clip_name2"
    )
    if (
        QUALIFICATION_TEXT_ENCODERS[0] not in clip_name1_options
        or QUALIFICATION_TEXT_ENCODERS[1] not in clip_name2_options
    ):
        raise QualificationError("candidate does not expose both pinned text encoders")
    if QUALIFICATION_VAE not in _loader_options(
        node_payloads["VAELoader"], "VAELoader", "vae_name"
    ):
        raise QualificationError("candidate does not expose the pinned VAE")
    vae_metadata = request_json(
        "GET",
        origin,
        f"/view_metadata/vae?{urlencode({'filename': QUALIFICATION_VAE})}",
    )
    if not vae_metadata:
        raise QualificationError("candidate returned empty metadata for the pinned VAE")
    return {
        "system_stats": stats,
        "observed_runtime": observed_runtime,
        "node_schemas": sorted(node_payloads),
        "vae_metadata": vae_metadata,
    }


def submit_and_wait(
    origin: str,
    workflow: Mapping[str, Any],
    *,
    binding: Mapping[str, Any],
    prompt_id: str,
    timeout_seconds: float,
    poll_seconds: float,
) -> dict[str, Any]:
    submission_attempted = False
    try:
        submission_attempted = True
        submission = request_json(
            "POST",
            origin,
            "/prompt",
            {
                "prompt": workflow,
                "client_id": str(uuid.uuid4()),
                "prompt_id": prompt_id,
                "extra_data": {QUALIFICATION_BINDING_KEY: binding},
            },
        )
        returned_prompt_id = _safe_prompt_id(submission.get("prompt_id"))
        if returned_prompt_id != prompt_id:
            raise QualificationError(
                "candidate did not return the exact submitted prompt identifier"
            )

        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            history = request_json(
                "GET",
                origin,
                f"/history/{quote(prompt_id, safe='')}",
                timeout=min(30.0, max(5.0, poll_seconds * 2)),
            )
            record = history.get(prompt_id)
            if isinstance(record, Mapping):
                status = record.get("status")
                if isinstance(status, Mapping) and status.get("completed") is True:
                    evidence = find_qualified_history_evidence(
                        {prompt_id: record},
                        expected_binding=binding,
                    )
                    if evidence is None:
                        raise QualificationError(
                            "candidate completed without fresh bound workflow evidence"
                        )
                    return evidence
            time.sleep(poll_seconds)
        raise QualificationError("candidate qualification timed out before completion")
    except (QualificationError, KeyboardInterrupt):
        if submission_attempted:
            cancel_submitted_prompt(origin, prompt_id)
        raise


def cancel_submitted_prompt(origin: str, prompt_id: str) -> list[str]:
    """Best-effort targeted cleanup; never clear another queue or history row."""

    safe_id = _safe_prompt_id(prompt_id)
    if not safe_id:
        return ["unsafe_prompt_id"]
    errors: list[str] = []
    cleanup_actions: tuple[tuple[str, Mapping[str, Any]], ...] = (
        ("/interrupt", {"prompt_id": safe_id}),
        ("/queue", {"delete": [safe_id]}),
        ("/history", {"delete": [safe_id]}),
    )
    for path, payload in cleanup_actions:
        try:
            request_action(origin, path, payload)
        except QualificationError as exc:
            errors.append(f"{path}:{type(exc).__name__}")
    return errors


def fetch_and_verify_output(
    origin: str, prompt_evidence: Mapping[str, Any]
) -> dict[str, Any]:
    output = prompt_evidence.get("output")
    if not isinstance(output, Mapping):
        raise QualificationError("history evidence has no safe output locator")
    filename = str(output.get("filename", ""))
    subfolder = str(output.get("subfolder", ""))
    output_type = str(output.get("type", ""))
    if not _safe_output_locator(filename, subfolder, output_type):
        raise QualificationError("history evidence contains an unsafe output locator")
    query = urlencode(
        {"filename": filename, "subfolder": subfolder, "type": output_type}
    )
    payload = _request_bytes(
        "GET",
        origin,
        f"/view?{query}",
        None,
        timeout=30.0,
        limit=MAX_OUTPUT_BYTES,
    )
    try:
        verified = inspect_qualification_png(payload)
    except ValueError as exc:
        raise QualificationError(str(exc)) from exc
    return {
        "path": str(output.get("path", "")),
        "filename": filename,
        "subfolder": subfolder,
        "type": output_type,
        **verified,
    }


def build_evidence(
    *,
    manifest: Mapping[str, Any],
    candidate_root: Path,
    network_scope: str,
    started_at: datetime,
    completed_at: datetime,
    git_evidence: Mapping[str, Any],
    model_evidence: Mapping[str, Mapping[str, Any]],
    preflight: Mapping[str, Any],
    binding: Mapping[str, Any],
    prompt_evidence: Mapping[str, Any],
    output_evidence: Mapping[str, Any],
    workflow: Mapping[str, Any],
) -> dict[str, Any]:
    guard = manifest.get("production_guard")
    port = guard.get("candidate_port") if isinstance(guard, Mapping) else None
    runtime_identity = binding.get("runtime")
    if not isinstance(runtime_identity, Mapping):
        raise QualificationError("qualification binding has no runtime identity")
    return {
        "schema_version": "2.0",
        "status": "technical_qualification_passed",
        "release_ready": False,
        "qualification_started_at": started_at.astimezone(timezone.utc).isoformat(),
        "qualification_completed_at": completed_at.astimezone(timezone.utc).isoformat(),
        "candidate": {
            "scope": "isolated-candidate-only",
            "network_scope": network_scope,
            "port": port,
            "root": str(candidate_root),
            "root_resolved": True,
            "symlinks_present": False,
        },
        "runtime": {
            "git": dict(git_evidence),
            "identity": runtime_identity,
            "identity_sha256": canonical_payload_sha256(runtime_identity),
            "system_stats_snapshot": preflight["system_stats"],
            "node_schemas_verified": preflight["node_schemas"],
            "vae_metadata_snapshot": preflight["vae_metadata"],
        },
        "workflow": {
            "sha256": QUALIFICATION_WORKFLOW_SHA256,
            "seed": qualification_seed(workflow),
            "api_graph": dict(workflow),
            "model": QUALIFICATION_MODEL,
            "text_encoders": list(QUALIFICATION_TEXT_ENCODERS),
            "vae": QUALIFICATION_VAE,
            "output_prefix": QUALIFICATION_OUTPUT_PREFIX,
        },
        "model_files": model_evidence,
        "execution": {
            "status": "success",
            "prompt_id": prompt_evidence["prompt_id"],
            "completed_at": prompt_evidence["completed_at"],
            "binding": dict(binding),
            "output": dict(output_evidence),
        },
        "human_visual_approval": {
            "required": True,
            "approved": False,
            "reviewer": None,
            "approved_at": None,
            "evidence_ref": None,
            "instruction": "A named human reviewer must inspect the fetched artifact and record approval separately.",
        },
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Qualify the pinned FLUX workflow on an explicitly isolated ComfyUI candidate."
    )
    parser.add_argument(
        "--base-url", required=True, help="Loopback-only candidate origin."
    )
    parser.add_argument(
        "--candidate-root",
        required=True,
        help="Exact absolute candidate root pinned by the manifest.",
    )
    parser.add_argument(
        "--attest-isolated-candidate",
        action="store_true",
        help="Required operator attestation that this is the isolated disposable candidate.",
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Verify root, Git, model bytes, queue, runtime, nodes, and VAE without submission.",
    )
    parser.add_argument("--timeout-seconds", type=float, default=900.0)
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument(
        "--evidence-out",
        default="",
        help="Optional path for secret-free evidence JSON.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        if not args.attest_isolated_candidate:
            raise QualificationError("explicit --attest-isolated-candidate is required")
        if not 30.0 <= args.timeout_seconds <= 3600.0:
            raise QualificationError("timeout must be between 30 and 3600 seconds")
        if not 1.0 <= args.poll_seconds <= 30.0:
            raise QualificationError("poll interval must be between 1 and 30 seconds")

        started_at = datetime.now(timezone.utc)
        workflow, manifest = load_qualification_assets()
        guard = manifest["production_guard"]
        origin, network_scope = validate_isolated_candidate_url(
            args.base_url,
            expected_port=int(guard["candidate_port"]),
        )
        candidate_root = resolve_candidate_root(args.candidate_root, manifest)
        git_evidence = verify_git_checkout(
            candidate_root, expected_commit=QUALIFICATION_CORE_COMMIT
        )
        model_evidence = verify_model_files(candidate_root, manifest)
        preflight = preflight_candidate(
            origin,
            workflow,
            candidate_port=int(guard["candidate_port"]),
        )
        runtime_identity = build_runtime_identity(
            preflight["observed_runtime"],
            candidate_root=str(candidate_root),
            core_commit=str(git_evidence["commit"]),
        )
        if args.preflight_only:
            print(
                json.dumps(
                    {
                        "status": "preflight_ok",
                        "candidate_network_scope": network_scope,
                        "candidate_root": str(candidate_root),
                        "workflow_sha256": QUALIFICATION_WORKFLOW_SHA256,
                        "runtime_identity_sha256": canonical_payload_sha256(
                            runtime_identity
                        ),
                        "model_files": model_evidence,
                        "submitted": False,
                        "human_visual_approval_required": True,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0

        prompt_id = str(uuid.uuid4())
        submitted_at = datetime.now(timezone.utc)
        binding = build_qualification_binding(
            workflow,
            prompt_id=prompt_id,
            submitted_at=submitted_at,
            runtime_identity=runtime_identity,
            model_files=model_evidence,
        )
        prompt_evidence = submit_and_wait(
            origin,
            workflow,
            binding=binding,
            prompt_id=prompt_id,
            timeout_seconds=args.timeout_seconds,
            poll_seconds=args.poll_seconds,
        )
        try:
            output_evidence = fetch_and_verify_output(origin, prompt_evidence)
        except QualificationError:
            cancel_submitted_prompt(origin, prompt_id)
            raise
        completed_at = datetime.now(timezone.utc)
        evidence = build_evidence(
            manifest=manifest,
            candidate_root=candidate_root,
            network_scope=network_scope,
            started_at=started_at,
            completed_at=completed_at,
            git_evidence=git_evidence,
            model_evidence=model_evidence,
            preflight=preflight,
            binding=binding,
            prompt_evidence=prompt_evidence,
            output_evidence=output_evidence,
            workflow=workflow,
        )
        output = json.dumps(evidence, indent=2, sort_keys=True) + "\n"
        if args.evidence_out:
            evidence_path = Path(args.evidence_out)
            if evidence_path.exists() and evidence_path.is_symlink():
                raise QualificationError("evidence output must not be a symbolic link")
            evidence_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = evidence_path.with_suffix(evidence_path.suffix + ".tmp")
            if temporary_path.exists() and temporary_path.is_symlink():
                raise QualificationError(
                    "temporary evidence output must not be a symbolic link"
                )
            temporary_path.write_text(output, encoding="utf-8")
            temporary_path.replace(evidence_path)
        print(output, end="")
        return 0
    except QualificationError as exc:
        print(
            json.dumps({"status": "refused", "reason": str(exc)}, indent=2),
            file=sys.stderr,
        )
        return 2


def _run_git(candidate_root: Path, *arguments: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(candidate_root), *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise QualificationError("cannot inspect candidate Git checkout") from exc
    if result.returncode != 0:
        raise QualificationError("candidate Git checkout verification failed")
    return result.stdout.strip()


def _sha256_regular_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    descriptor = -1
    try:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise QualificationError(f"model path is not a regular file: {path.name}")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            while chunk := stream.read(MODEL_HASH_CHUNK_BYTES):
                digest.update(chunk)
        after = os.fstat(descriptor)
    except OSError as exc:
        raise QualificationError(f"cannot hash model file: {path.name}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise QualificationError(
            f"model file changed while it was being hashed: {path.name}"
        )
    return before.st_size, digest.hexdigest()


def _path_has_symlink_component(path: Path, *, stop: Path | None = None) -> bool:
    current = Path(path.anchor)
    stop_normalized = stop.resolve(strict=False) if stop is not None else None
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink():
            return True
        if (
            stop_normalized is not None
            and current.resolve(strict=False) == stop_normalized
        ):
            continue
    return False


def _validate_runtime_argv(argv: Any, *, candidate_port: int) -> None:
    if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
        raise QualificationError("candidate runtime argv is missing")
    listen = _argument_value(argv, "--listen")
    port = _argument_value(argv, "--port")
    if listen not in {"127.0.0.1", "::1", "localhost"}:
        raise QualificationError("candidate runtime is not bound to loopback")
    if port != str(candidate_port):
        raise QualificationError(
            "candidate runtime port does not match the pinned isolated port"
        )


def _argument_value(argv: list[str], name: str) -> str:
    prefix = f"{name}="
    for index, item in enumerate(argv):
        if item.startswith(prefix):
            return item[len(prefix) :]
        if item == name and index + 1 < len(argv):
            return argv[index + 1]
    return ""


def _validate_node_schema(
    payload: Mapping[str, Any],
    node_name: str,
    workflow_inputs: set[str],
) -> None:
    node = payload.get(node_name)
    if not isinstance(node, Mapping):
        raise QualificationError(
            f"candidate does not expose required core node {node_name}"
        )
    node_input = node.get("input")
    if not isinstance(node_input, Mapping):
        raise QualificationError(f"candidate returned no input schema for {node_name}")
    accepted: set[str] = set()
    for group_name in ("required", "optional", "hidden"):
        group = node_input.get(group_name, {})
        if isinstance(group, Mapping):
            accepted.update(str(key) for key in group)
    if not workflow_inputs.issubset(accepted):
        raise QualificationError(
            f"candidate node schema is incompatible with {node_name}"
        )


def _loader_options(
    payload: Mapping[str, Any], node_name: str, input_name: str
) -> list[str]:
    node = payload.get(node_name)
    node_input = node.get("input") if isinstance(node, Mapping) else None
    required = node_input.get("required") if isinstance(node_input, Mapping) else None
    options = required.get(input_name) if isinstance(required, Mapping) else None
    if not (isinstance(options, list) and options and isinstance(options[0], list)):
        return []
    return [str(item) for item in options[0] if str(item).strip()]


def _safe_prompt_id(value: Any) -> str:
    text = str(value or "")
    if not text or len(text) > 128:
        return ""
    if not all(character.isalnum() or character in "-_." for character in text):
        return ""
    return text


def _safe_output_locator(filename: str, subfolder: str, output_type: str) -> bool:
    if output_type != "output" or not filename.startswith(QUALIFICATION_OUTPUT_PREFIX):
        return False
    if PurePosixPath(filename).name != filename or len(filename) > 255:
        return False
    normalized = subfolder.replace("\\", "/")
    folder = PurePosixPath(normalized)
    return (
        not folder.is_absolute() and ".." not in folder.parts and len(normalized) <= 255
    )


def _is_sha256_like(value: str, *, length: int) -> bool:
    return len(value) == length and all(
        character in "0123456789abcdef" for character in value
    )


if __name__ == "__main__":
    raise SystemExit(main())
