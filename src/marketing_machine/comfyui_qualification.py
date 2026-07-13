from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import PurePosixPath
import struct
from typing import Any, Mapping
import zlib


QUALIFICATION_WORKFLOW_SHA256 = (
    "10a93745478a805b01c36827c9168bc995098fcba460b9dc8fd0dadabe6efe76"
)
QUALIFICATION_OUTPUT_NODE = "11"
QUALIFICATION_OUTPUT_PREFIX = "wamocon_qualification_flux1_schnell_v1"
QUALIFICATION_MODEL = "flux1-schnell.safetensors"
QUALIFICATION_TEXT_ENCODERS = (
    "t5xxl_fp8_e4m3fn.safetensors",
    "clip_l.safetensors",
)
QUALIFICATION_VAE = "ae.safetensors"
QUALIFICATION_SEED_NODE = "9"
QUALIFICATION_BINDING_KEY = "wamocon_qualification"
QUALIFICATION_BINDING_SCHEMA_VERSION = "1.0"
QUALIFICATION_HISTORY_MAX_AGE_SECONDS = 24 * 60 * 60
QUALIFICATION_FUTURE_SKEW_SECONDS = 5 * 60
QUALIFICATION_CORE_COMMIT = "bd39bbf0678ebd31c972fd365733a8c729f2cd74"
QUALIFICATION_CANDIDATE_ROOT = (
    "/home/wamocon/candidates/comfyui-flux-schnell-20260710/src"
)
QUALIFICATION_COMFYUI_VERSION = "0.25.0"
QUALIFICATION_PYTHON_VERSION = "3.12.13"
QUALIFICATION_TORCH_BUILD = "2.11.0+cu130"
QUALIFICATION_REQUIRED_PACKAGES = {
    "comfy-aimdo": "0.4.10",
    "comfy-kitchen": "0.2.10",
    "comfyui-embedded-docs": "0.5.4",
    "comfyui-frontend-package": "1.45.15",
    "comfyui-workflow-templates": "0.10.0",
}
QUALIFICATION_MODEL_FILES = {
    "models/diffusion_models/flux1-schnell.safetensors": {
        "bytes": 23_782_506_688,
        "sha256": "9403429e0052277ac2a87ad800adece5481eecefd9ed334e1f348723621d2a0a",
    },
    "models/text_encoders/clip_l.safetensors": {
        "bytes": 246_144_152,
        "sha256": "660c6f5b1abae9dc498ac2d21e1347d2abdb0cf6c0c0c8576cd796491d9a6cdd",
    },
    "models/text_encoders/t5xxl_fp8_e4m3fn.safetensors": {
        "bytes": 4_893_934_904,
        "sha256": "7d330da4816157540d6bb7838bf63a0f02f573fc48ca4d8de34bb0cbfd514f09",
    },
    "models/vae/ae.safetensors": {
        "bytes": 335_304_388,
        "sha256": "afc8e28272cd15db3919bacdb6918ce9c1ed22e96cb12c4d5ed0fba823529e38",
    },
}
QUALIFICATION_XET_HASHES = {
    "models/diffusion_models/flux1-schnell.safetensors": "df5d997365ef3f1e30100e6ce56e0c4e1dcc34e7caa59d1cf46aa61bb8b048d7",
    "models/text_encoders/clip_l.safetensors": "645ba23540a1ce97d9c44332759ded7c2b5b8449914b8890eefd73d88e6e0229",
    "models/text_encoders/t5xxl_fp8_e4m3fn.safetensors": "ca49b49b9b4ef106396a18f76600a52b6a07cd1322408c83337483ce56b803ba",
    "models/vae/ae.safetensors": "f73eecf7c469ff442523dc712cc161d631df071bf4d9d793494fbf00cdd80a82",
}
QUALIFICATION_NODE_INPUTS = {
    "UNETLoader": {"unet_name", "weight_dtype"},
    "DualCLIPLoader": {"clip_name1", "clip_name2", "type", "device"},
    "VAELoader": {"vae_name"},
    "CLIPTextEncode": {"text", "clip"},
    "FluxGuidance": {"guidance", "conditioning"},
    "EmptySD3LatentImage": {"width", "height", "batch_size"},
    "ModelSamplingFlux": {"max_shift", "base_shift", "width", "height", "model"},
    "KSampler": {
        "seed",
        "steps",
        "cfg",
        "sampler_name",
        "scheduler",
        "denoise",
        "model",
        "positive",
        "negative",
        "latent_image",
    },
    "VAEDecode": {"samples", "vae"},
    "SaveImage": {"filename_prefix", "images"},
}

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
PNG_MAX_DIMENSION = 8192
PNG_MAX_PIXELS = 16_777_216
PNG_SUPPORTED_COLOR_CHANNELS = {2: 3, 6: 4}


def canonical_workflow_sha256(workflow: Mapping[str, Any]) -> str:
    """Return the stable hash used to bind qualification history to one graph."""

    return canonical_payload_sha256(workflow)


def canonical_payload_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def qualification_seed(workflow: Mapping[str, Any]) -> int | None:
    node = workflow.get(QUALIFICATION_SEED_NODE)
    inputs = node.get("inputs") if isinstance(node, Mapping) else None
    seed = inputs.get("seed") if isinstance(inputs, Mapping) else None
    if isinstance(seed, int) and not isinstance(seed, bool) and seed >= 0:
        return seed
    return None


def observed_runtime_identity(system_stats: Mapping[str, Any]) -> dict[str, Any]:
    """Return stable, fail-closed runtime identity fields from ``/system_stats``.

    Volatile RAM and VRAM counters remain in the raw evidence snapshot but are
    intentionally excluded from the identity hash. Package telemetry is
    mandatory and must contain exactly the five packages pinned by the core
    commit. An empty list is therefore never interpreted as compatible.
    """

    system = system_stats.get("system")
    devices = system_stats.get("devices")
    if not isinstance(system, Mapping):
        raise ValueError("system_stats has no system object")
    if not isinstance(devices, list) or not devices:
        raise ValueError("system_stats has no device telemetry")

    comfyui_version = str(system.get("comfyui_version", "")).strip()
    python_version = str(system.get("python_version", "")).strip()
    pytorch_version = str(system.get("pytorch_version", "")).strip()
    if comfyui_version != QUALIFICATION_COMFYUI_VERSION:
        raise ValueError("ComfyUI version does not match the pinned runtime")
    if not python_version.startswith(QUALIFICATION_PYTHON_VERSION):
        raise ValueError("Python version does not match the pinned runtime")
    if pytorch_version != QUALIFICATION_TORCH_BUILD:
        raise ValueError("PyTorch build does not match the pinned runtime")

    package_rows = system.get("comfy_package_versions")
    if not isinstance(package_rows, list) or not package_rows:
        raise ValueError("ComfyUI package telemetry is missing or empty")
    package_versions: dict[str, str] = {}
    for row in package_rows:
        if not isinstance(row, Mapping):
            raise ValueError("ComfyUI package telemetry contains a non-object row")
        name = str(row.get("name", "")).strip()
        installed = str(row.get("installed", "")).strip()
        required = str(row.get("required", "")).strip()
        if not name or not installed or not required or name in package_versions:
            raise ValueError("ComfyUI package telemetry is incomplete or duplicated")
        if installed != required:
            raise ValueError(
                f"ComfyUI package {name} does not match its reported requirement"
            )
        package_versions[name] = installed
    if package_versions != QUALIFICATION_REQUIRED_PACKAGES:
        raise ValueError(
            "ComfyUI package telemetry does not match the exact pinned package set"
        )

    argv = system.get("argv")
    if (
        not isinstance(argv, list)
        or not argv
        or not all(isinstance(item, str) for item in argv)
    ):
        raise ValueError("ComfyUI argv telemetry is missing")

    device_identity: list[dict[str, Any]] = []
    for device in devices:
        if not isinstance(device, Mapping):
            raise ValueError("ComfyUI device telemetry contains a non-object row")
        name = str(device.get("name", "")).strip()
        device_type = str(device.get("type", "")).strip()
        index = device.get("index")
        if (
            not name
            or not device_type
            or (
                index is not None
                and (not isinstance(index, int) or isinstance(index, bool))
            )
        ):
            raise ValueError("ComfyUI device telemetry is incomplete")
        device_identity.append({"name": name, "type": device_type, "index": index})

    return {
        "comfyui_version": comfyui_version,
        "python_version": python_version,
        "pytorch_version": pytorch_version,
        "packages": dict(sorted(package_versions.items())),
        "argv": list(argv),
        "deploy_environment": system.get("deploy_environment"),
        "devices": device_identity,
    }


def build_runtime_identity(
    observed: Mapping[str, Any],
    *,
    candidate_root: str,
    core_commit: str,
) -> dict[str, Any]:
    return {
        "candidate_root": candidate_root,
        "core_commit": core_commit,
        "observed": dict(observed),
    }


def build_qualification_binding(
    workflow: Mapping[str, Any],
    *,
    prompt_id: str,
    submitted_at: datetime,
    runtime_identity: Mapping[str, Any],
    model_files: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    seed = qualification_seed(workflow)
    if seed is None:
        raise ValueError("qualification workflow has no valid seed")
    if submitted_at.tzinfo is None:
        raise ValueError("submission timestamp must be timezone-aware")
    normalized_models = _normalize_model_files(model_files)
    runtime = dict(runtime_identity)
    return {
        "schema_version": QUALIFICATION_BINDING_SCHEMA_VERSION,
        "prompt_id": prompt_id,
        "submitted_at": submitted_at.astimezone(timezone.utc).isoformat(),
        "workflow_sha256": canonical_workflow_sha256(workflow),
        "seed": seed,
        "runtime": runtime,
        "runtime_sha256": canonical_payload_sha256(runtime),
        "model_files": normalized_models,
        "model_files_sha256": canonical_payload_sha256(normalized_models),
    }


def find_qualified_history_evidence(
    history: Mapping[str, Any],
    *,
    expected_runtime_observation: Mapping[str, Any] | None = None,
    expected_binding: Mapping[str, Any] | None = None,
    now: datetime | None = None,
    max_age_seconds: int = QUALIFICATION_HISTORY_MAX_AGE_SECONDS,
) -> dict[str, Any] | None:
    """Find fresh history bound to the pinned graph, runtime, weights, and output.

    History is untrusted. The binding is written into this prompt's own
    ``extra_data`` before submission. A caller still has to fetch the returned
    output locator and verify the output bytes; history alone never proves an
    artifact exists or is unchanged.
    """

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    candidates: list[tuple[int, int, dict[str, Any]]] = []
    for position, (history_key, record) in enumerate(history.items()):
        if not isinstance(record, Mapping) or not _history_succeeded(record):
            continue
        workflow = _history_workflow(record)
        if (
            workflow is None
            or canonical_workflow_sha256(workflow) != QUALIFICATION_WORKFLOW_SHA256
        ):
            continue
        seed = qualification_seed(workflow)
        artifact = _qualified_output_artifact(record)
        if seed is None or artifact is None:
            continue
        prompt_id = _safe_identifier(record.get("prompt_id")) or _safe_identifier(
            history_key
        )
        if not prompt_id:
            continue
        completed_at_ms = _history_success_timestamp_ms(record)
        if not _timestamp_is_fresh(
            completed_at_ms, current, max_age_seconds=max_age_seconds
        ):
            continue
        binding = _history_binding(record)
        if not _binding_is_valid(
            binding,
            prompt_id=prompt_id,
            seed=seed,
            completed_at_ms=completed_at_ms,
            expected_runtime_observation=expected_runtime_observation,
            expected_binding=expected_binding,
        ):
            continue
        evidence: dict[str, Any] = {
            "prompt_id": prompt_id,
            "last_output_artifact": artifact["path"],
            "output": artifact,
            "workflow_sha256": QUALIFICATION_WORKFLOW_SHA256,
            "seed": seed,
            "completed_at": datetime.fromtimestamp(
                completed_at_ms / 1000,
                tz=timezone.utc,
            ).isoformat(),
            "binding": dict(binding),
        }
        candidates.append((completed_at_ms, position, evidence))

    if not candidates:
        return None
    return max(candidates, key=lambda item: (item[0], item[1]))[2]


def inspect_qualification_png(payload: bytes) -> dict[str, Any]:
    """Decode-check a fetched PNG and bind its prompt to the pinned graph.

    Metadata alone is not image evidence.  The parser therefore enforces the
    PNG chunk order, one supported IHDR, contiguous IDAT data, exact scanline
    length, valid row filters, zlib end-of-stream, and a terminal IEND with no
    trailing bytes.  The deliberately narrow RGB/RGBA 8-bit profile matches
    ComfyUI output and keeps decompression limits deterministic.
    """

    if len(payload) < 1024 or not payload.startswith(PNG_SIGNATURE):
        raise ValueError("qualification output is not a nonempty PNG")
    offset = 8
    embedded_prompt: Mapping[str, Any] | None = None
    width = 0
    height = 0
    channels = 0
    saw_header = False
    saw_image_data = False
    image_data_closed = False
    image_data: list[bytes] = []
    saw_end = False
    chunk_index = 0
    while offset + 12 <= len(payload):
        length = struct.unpack(">I", payload[offset : offset + 4])[0]
        if length > len(payload) - offset - 12:
            raise ValueError("qualification PNG contains an invalid chunk length")
        chunk_type = payload[offset + 4 : offset + 8]
        if len(chunk_type) != 4 or not all(
            65 <= character <= 90 or 97 <= character <= 122
            for character in chunk_type
        ):
            raise ValueError("qualification PNG contains an invalid chunk type")
        data_start = offset + 8
        data_end = data_start + length
        chunk_data = payload[data_start:data_end]
        expected_crc = struct.unpack(">I", payload[data_end : data_end + 4])[0]
        actual_crc = zlib.crc32(chunk_type + chunk_data) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise ValueError("qualification PNG contains a corrupt chunk")
        offset = data_end + 4
        if chunk_index == 0 and chunk_type != b"IHDR":
            raise ValueError("qualification PNG must start with IHDR")
        if chunk_type == b"IHDR":
            if saw_header or chunk_index != 0 or length != 13:
                raise ValueError("qualification PNG has an invalid IHDR")
            (
                width,
                height,
                bit_depth,
                color_type,
                compression_method,
                filter_method,
                interlace_method,
            ) = struct.unpack(">IIBBBBB", chunk_data)
            if (
                width < 1
                or height < 1
                or width > PNG_MAX_DIMENSION
                or height > PNG_MAX_DIMENSION
                or width * height > PNG_MAX_PIXELS
            ):
                raise ValueError("qualification PNG dimensions are outside the safe limit")
            channels = PNG_SUPPORTED_COLOR_CHANNELS.get(color_type, 0)
            if bit_depth != 8 or not channels:
                raise ValueError("qualification PNG must be 8-bit RGB or RGBA")
            if compression_method != 0 or filter_method != 0 or interlace_method != 0:
                raise ValueError("qualification PNG uses an unsupported encoding profile")
            saw_header = True
        elif chunk_type == b"IDAT":
            if not saw_header or image_data_closed or not chunk_data:
                raise ValueError("qualification PNG has invalid or non-contiguous IDAT data")
            saw_image_data = True
            image_data.append(chunk_data)
        elif chunk_type == b"IEND":
            if length != 0 or not saw_header or not saw_image_data:
                raise ValueError("qualification PNG has an invalid IEND")
            saw_end = True
            break
        else:
            if saw_image_data:
                image_data_closed = True
            # Unknown critical chunks change image interpretation and cannot be
            # safely ignored. PLTE is known but unnecessary for RGB/RGBA.
            if chunk_type[0] & 0x20 == 0 and chunk_type != b"PLTE":
                raise ValueError("qualification PNG contains an unsupported critical chunk")
        if chunk_type == b"tEXt" and b"\x00" in chunk_data:
            keyword, value = chunk_data.split(b"\x00", 1)
            if keyword == b"prompt":
                if embedded_prompt is not None:
                    raise ValueError("qualification PNG has ambiguous prompt metadata")
                try:
                    decoded = json.loads(value.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ValueError(
                        "qualification PNG has invalid prompt metadata"
                    ) from exc
                if isinstance(decoded, Mapping):
                    embedded_prompt = decoded
                else:
                    raise ValueError("qualification PNG prompt metadata is not an object")
        chunk_index += 1
    if not saw_end:
        raise ValueError("qualification PNG has no IEND chunk")
    if offset != len(payload):
        raise ValueError("qualification PNG contains trailing bytes after IEND")
    if embedded_prompt is None:
        raise ValueError("qualification PNG has no embedded prompt metadata")

    expected_scanline_bytes = height * (1 + width * channels)
    decompressor = zlib.decompressobj()
    try:
        decoded_pixels = decompressor.decompress(
            b"".join(image_data), expected_scanline_bytes + 1
        )
        decoded_pixels += decompressor.flush()
    except zlib.error as exc:
        raise ValueError("qualification PNG image data cannot be decoded") from exc
    if (
        not decompressor.eof
        or decompressor.unused_data
        or decompressor.unconsumed_tail
        or len(decoded_pixels) != expected_scanline_bytes
    ):
        raise ValueError("qualification PNG image data has an invalid decoded length")
    row_bytes = 1 + width * channels
    if any(decoded_pixels[row * row_bytes] > 4 for row in range(height)):
        raise ValueError("qualification PNG contains an invalid scanline filter")

    embedded_hash = canonical_workflow_sha256(embedded_prompt)
    if embedded_hash != QUALIFICATION_WORKFLOW_SHA256:
        raise ValueError("qualification PNG is not bound to the pinned workflow")
    return {
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "embedded_workflow_sha256": embedded_hash,
        "width": width,
        "height": height,
        "color_mode": "RGBA" if channels == 4 else "RGB",
    }


def _normalize_model_files(
    model_files: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    normalized: dict[str, dict[str, Any]] = {}
    for path, evidence in model_files.items():
        size = evidence.get("bytes")
        digest = str(evidence.get("sha256", "")).lower()
        if (
            not path
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size <= 0
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError("model file evidence is incomplete")
        normalized[str(path)] = {"bytes": size, "sha256": digest}
    if normalized != QUALIFICATION_MODEL_FILES:
        raise ValueError("model file evidence does not match the exact pinned bundle")
    return dict(sorted(normalized.items()))


def _history_succeeded(record: Mapping[str, Any]) -> bool:
    status = record.get("status")
    return bool(
        isinstance(status, Mapping)
        and status.get("completed") is True
        and status.get("status_str") == "success"
    )


def _history_workflow(record: Mapping[str, Any]) -> Mapping[str, Any] | None:
    prompt = record.get("prompt")
    if isinstance(prompt, list) and len(prompt) > 2 and isinstance(prompt[2], Mapping):
        return prompt[2]
    if isinstance(prompt, Mapping):
        nested = prompt.get("prompt")
        if isinstance(nested, Mapping):
            return nested
        if all(isinstance(value, Mapping) for value in prompt.values()):
            return prompt
    return None


def _history_binding(record: Mapping[str, Any]) -> Mapping[str, Any]:
    prompt = record.get("prompt")
    extra: Any = None
    if isinstance(prompt, list) and len(prompt) > 3 and isinstance(prompt[3], Mapping):
        extra = prompt[3]
    elif isinstance(prompt, Mapping):
        extra = prompt.get("extra_data")
    if not isinstance(extra, Mapping):
        return {}
    binding = extra.get(QUALIFICATION_BINDING_KEY)
    return binding if isinstance(binding, Mapping) else {}


def _binding_is_valid(
    binding: Mapping[str, Any],
    *,
    prompt_id: str,
    seed: int,
    completed_at_ms: int,
    expected_runtime_observation: Mapping[str, Any] | None,
    expected_binding: Mapping[str, Any] | None,
) -> bool:
    if expected_binding is not None and dict(binding) != dict(expected_binding):
        return False
    if (
        binding.get("schema_version") != QUALIFICATION_BINDING_SCHEMA_VERSION
        or binding.get("prompt_id") != prompt_id
        or binding.get("workflow_sha256") != QUALIFICATION_WORKFLOW_SHA256
        or binding.get("seed") != seed
    ):
        return False
    submitted_at = _parse_iso_datetime(binding.get("submitted_at"))
    if submitted_at is None or int(submitted_at.timestamp() * 1000) > completed_at_ms:
        return False

    runtime = binding.get("runtime")
    if not isinstance(runtime, Mapping):
        return False
    if (
        runtime.get("candidate_root") != QUALIFICATION_CANDIDATE_ROOT
        or runtime.get("core_commit") != QUALIFICATION_CORE_COMMIT
        or binding.get("runtime_sha256") != canonical_payload_sha256(runtime)
    ):
        return False
    observed = runtime.get("observed")
    if not isinstance(observed, Mapping):
        return False
    if expected_runtime_observation is not None and dict(observed) != dict(
        expected_runtime_observation
    ):
        return False

    model_files = binding.get("model_files")
    if not isinstance(model_files, Mapping):
        return False
    try:
        normalized = _normalize_model_files(model_files)
    except ValueError:
        return False
    return binding.get("model_files_sha256") == canonical_payload_sha256(normalized)


def _qualified_output_artifact(record: Mapping[str, Any]) -> dict[str, str] | None:
    outputs = record.get("outputs")
    if not isinstance(outputs, Mapping):
        return None
    output = outputs.get(QUALIFICATION_OUTPUT_NODE)
    if not isinstance(output, Mapping):
        return None
    images = output.get("images")
    if not isinstance(images, list):
        return None

    for image in images:
        if not isinstance(image, Mapping) or image.get("type") != "output":
            continue
        filename = _safe_filename(image.get("filename"))
        if not filename or not filename.startswith(QUALIFICATION_OUTPUT_PREFIX):
            continue
        subfolder = _safe_subfolder(image.get("subfolder"))
        if subfolder is None:
            continue
        return {
            "filename": filename,
            "subfolder": subfolder,
            "type": "output",
            "path": f"{subfolder}/{filename}" if subfolder else filename,
        }
    return None


def _history_success_timestamp_ms(record: Mapping[str, Any]) -> int:
    status = record.get("status")
    if not isinstance(status, Mapping):
        return 0
    messages = status.get("messages")
    if not isinstance(messages, list):
        return 0
    newest = 0
    for message in messages:
        if not (
            isinstance(message, list)
            and len(message) > 1
            and message[0] == "execution_success"
            and isinstance(message[1], Mapping)
        ):
            continue
        raw = message[1].get("timestamp")
        if not isinstance(raw, (int, float)) or isinstance(raw, bool):
            continue
        value = float(raw)
        if 1_000_000_000 <= value < 10_000_000_000:
            value *= 1000
        if 1_000_000_000_000 <= value < 10_000_000_000_000:
            newest = max(newest, int(value))
    return newest


def _timestamp_is_fresh(
    timestamp_ms: int,
    now: datetime,
    *,
    max_age_seconds: int,
) -> bool:
    if timestamp_ms <= 0 or max_age_seconds <= 0:
        return False
    age_seconds = now.timestamp() - (timestamp_ms / 1000)
    return -QUALIFICATION_FUTURE_SKEW_SECONDS <= age_seconds <= max_age_seconds


def _parse_iso_datetime(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _safe_identifier(value: Any) -> str:
    text = str(value or "")
    if not text or len(text) > 128:
        return ""
    if not all(character.isalnum() or character in "-_." for character in text):
        return ""
    return text


def _safe_filename(value: Any) -> str:
    text = str(value or "")
    if not text or len(text) > 255 or PurePosixPath(text).name != text:
        return ""
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in text):
        return ""
    return text


def _safe_subfolder(value: Any) -> str | None:
    text = str(value or "").replace("\\", "/")
    if not text:
        return ""
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts or len(text) > 255:
        return None
    if any(ord(character) < 0x20 or ord(character) == 0x7F for character in text):
        return None
    return str(path)
