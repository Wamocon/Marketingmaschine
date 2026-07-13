#!/usr/bin/env python3
"""Prepare the isolated, pinned ComfyUI qualification candidate on Nvidia-2.

The script is deliberately narrow: it only operates below the candidate root
declared in the release manifest, never stops or edits the production ComfyUI
service, downloads into temporary files, and promotes a model only after its
exact byte count and SHA-256 have been verified.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import signal
import socket
import subprocess
import sys
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


EXPECTED_BASE = Path("/home/wamocon/candidates/comfyui-flux-schnell-20260710")
EXPECTED_ROOT = EXPECTED_BASE / "src"
EXPECTED_PORT = 18189
EXPECTED_BIND = "127.0.0.1"
PRODUCTION_ROOTS = (Path("/home/wamocon/ComfyUI"), Path("/home/wamocon/comfyui"))
DEFAULT_SOURCE_ENV = Path("/home/wamocon/miniforge3/envs/comfyui")
DEFAULT_CONDA = Path("/home/wamocon/miniforge3/bin/conda")
DOWNLOAD_CHUNK_BYTES = 8 * 1024 * 1024
HASH_CHUNK_BYTES = 8 * 1024 * 1024
USER_AGENT = "wamocon-comfyui-isolated-candidate-setup/1.0"


class SetupRefused(RuntimeError):
    """Raised when an operation cannot prove it remains inside the candidate."""


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SetupRefused("cannot read the candidate manifest") from exc
    if not isinstance(payload, dict):
        raise SetupRefused("candidate manifest must be a JSON object")
    guard_value = payload.get("production_guard")
    runtime_value = payload.get("runtime")
    bundle_value = payload.get("model_bundle")
    if not isinstance(guard_value, Mapping):
        raise SetupRefused("candidate manifest is missing its production guard")
    if not isinstance(runtime_value, Mapping):
        raise SetupRefused("candidate manifest is missing its runtime contract")
    if not isinstance(bundle_value, Mapping):
        raise SetupRefused("candidate manifest is missing its safety contract")
    guard: Mapping[str, Any] = guard_value
    runtime: Mapping[str, Any] = runtime_value
    bundle: Mapping[str, Any] = bundle_value
    if payload.get("scope") != "isolated-candidate-only":
        raise SetupRefused("manifest is not restricted to an isolated candidate")
    if Path(str(guard.get("candidate_root", ""))) != EXPECTED_ROOT:
        raise SetupRefused("manifest candidate root differs from the approved root")
    if guard.get("candidate_bind") != EXPECTED_BIND or guard.get("candidate_port") != EXPECTED_PORT:
        raise SetupRefused("manifest candidate network scope is not the approved loopback port")
    if any(guard.get(key) is not False for key in (
        "allow_model_symlinks_to_production",
        "allow_custom_nodes",
        "allow_production_service_restart",
    )):
        raise SetupRefused("manifest permits an unsafe production interaction")
    commit = str(runtime.get("commit", ""))
    if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit):
        raise SetupRefused("manifest does not pin a full Git commit")
    files = bundle.get("files")
    if not isinstance(files, list) or len(files) != 4:
        raise SetupRefused("manifest must pin exactly four model files")
    total = 0
    seen: set[str] = set()
    for row in files:
        if not isinstance(row, Mapping):
            raise SetupRefused("manifest contains an invalid model row")
        relative = safe_relative_model_path(row.get("path"))
        digest = str(row.get("sha256", "")).lower()
        size = row.get("bytes")
        revision = str(row.get("source_revision", ""))
        if str(relative) in seen:
            raise SetupRefused("manifest contains a duplicate model path")
        seen.add(str(relative))
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            raise SetupRefused("manifest contains an invalid model byte count")
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise SetupRefused("manifest contains an invalid model SHA-256")
        if len(revision) != 40 or any(character not in "0123456789abcdef" for character in revision):
            raise SetupRefused("manifest model source is not immutable")
        if row.get("gated_source") is not False:
            raise SetupRefused("setup accepts only the declared ungated sources")
        if not str(row.get("source_repo", "")).strip() or not str(row.get("source_file", "")).strip():
            raise SetupRefused("manifest model source is incomplete")
        total += size
    if bundle.get("expected_total_bytes") != total:
        raise SetupRefused("manifest model total does not match its file rows")
    return payload


def safe_relative_model_path(value: Any) -> PurePosixPath:
    relative = PurePosixPath(str(value or ""))
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise SetupRefused("manifest contains an unsafe model path")
    if relative.parts[0] != "models":
        raise SetupRefused("model path must remain below the candidate models directory")
    return relative


def model_source_url(row: Mapping[str, Any]) -> str:
    repository = str(row["source_repo"]).strip().strip("/")
    revision = str(row["source_revision"]).strip()
    source_file = quote(str(row["source_file"]).lstrip("/"), safe="/")
    return f"https://huggingface.co/{repository}/resolve/{revision}/{source_file}"


def assert_candidate_path(path: Path, *, allow_missing: bool = True) -> Path:
    if not path.is_absolute():
        raise SetupRefused("candidate path must be absolute")
    normalized = Path(os.path.normpath(path))
    if normalized != EXPECTED_BASE and EXPECTED_BASE not in normalized.parents:
        raise SetupRefused("operation escaped the approved candidate base")
    current = Path(path.anchor)
    for part in normalized.parts[1:]:
        current /= part
        if current.is_symlink():
            raise SetupRefused(f"candidate path contains a symbolic link: {current}")
        if not current.exists() and allow_missing:
            break
    for production_root in PRODUCTION_ROOTS:
        production = production_root.resolve(strict=False)
        resolved = normalized.resolve(strict=False)
        if resolved == production or production in resolved.parents or resolved in production.parents:
            raise SetupRefused("candidate path overlaps a production root")
    return normalized


def run_checked(arguments: list[str], *, cwd: Path | None = None, timeout: float = 1800) -> str:
    try:
        result = subprocess.run(
            arguments,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SetupRefused(f"command failed to run: {arguments[0]}") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        suffix = f": {detail[-1][:300]}" if detail else ""
        raise SetupRefused(f"command refused ({arguments[0]}){suffix}")
    return result.stdout.strip()


def prepare_checkout(manifest: Mapping[str, Any]) -> None:
    assert_candidate_path(EXPECTED_BASE)
    EXPECTED_BASE.mkdir(parents=True, exist_ok=True)
    assert_candidate_path(EXPECTED_BASE, allow_missing=False)
    runtime = manifest["runtime"]
    expected_commit = str(runtime["commit"])
    repository = str(runtime["repository"])
    installing = EXPECTED_BASE / "src.installing"
    assert_candidate_path(installing)
    if installing.exists():
        raise SetupRefused("incomplete src.installing exists; inspect it before retrying")
    if not EXPECTED_ROOT.exists():
        run_checked(["git", "clone", "--filter=blob:none", "--no-checkout", repository, str(installing)])
        try:
            run_checked(["git", "checkout", "--detach", expected_commit], cwd=installing)
            installing.replace(EXPECTED_ROOT)
        except BaseException:
            # Keep the incomplete directory for explicit inspection; never delete blindly.
            raise
    verify_checkout(expected_commit)


def verify_checkout(expected_commit: str) -> None:
    assert_candidate_path(EXPECTED_ROOT, allow_missing=False)
    if not (EXPECTED_ROOT / ".git").is_dir() or (EXPECTED_ROOT / ".git").is_symlink():
        raise SetupRefused("candidate source is not an isolated Git checkout")
    commit = run_checked(["git", "rev-parse", "--verify", "HEAD^{commit}"], cwd=EXPECTED_ROOT)
    if commit != expected_commit:
        raise SetupRefused("candidate source does not match the pinned commit")
    if run_checked(["git", "status", "--porcelain", "--untracked-files=no"], cwd=EXPECTED_ROOT):
        raise SetupRefused("candidate source contains modified tracked files")
    for path in EXPECTED_ROOT.rglob("*"):
        if path.is_symlink():
            raise SetupRefused(f"candidate source contains a symbolic link: {path.relative_to(EXPECTED_ROOT)}")


def prepare_environment(
    manifest: Mapping[str, Any], *, conda: Path, source_env: Path
) -> Path:
    environment = EXPECTED_BASE / "env"
    assert_candidate_path(environment)
    python = environment / "bin" / "python"
    if environment.exists() and not python.is_file():
        raise SetupRefused("candidate environment is incomplete; inspect it before retrying")
    if not environment.exists():
        if not conda.is_file() or not source_env.is_dir():
            raise SetupRefused("approved source environment or conda executable is missing")
        run_checked(
            [str(conda), "create", "--yes", "--prefix", str(environment), "--clone", str(source_env)],
            timeout=3600,
        )
    packages = manifest["runtime"].get("required_packages")
    if not isinstance(packages, Mapping) or not packages:
        raise SetupRefused("manifest has no exact runtime package set")
    requirements = [f"{name}=={version}" for name, version in sorted(packages.items())]
    run_checked([str(python), "-m", "pip", "install", "--disable-pip-version-check", *requirements], timeout=1800)
    runtime_probe = json.loads(
        run_checked(
            [
                str(python),
                "-c",
                "import json,sys,torch; print(json.dumps({'python':sys.version.split()[0],'torch':torch.__version__}))",
            ]
        )
    )
    if runtime_probe != {
        "python": str(manifest["runtime"]["python_version"]),
        "torch": str(manifest["runtime"]["torch_build"]),
    }:
        raise SetupRefused("candidate Python or Torch runtime differs from the manifest")
    return python


def ensure_download_capacity(manifest: Mapping[str, Any]) -> None:
    minimum = manifest["model_bundle"].get("minimum_free_bytes_before_download")
    if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum <= 0:
        raise SetupRefused("manifest has no valid minimum free-space gate")
    available = shutil.disk_usage(EXPECTED_BASE).free
    if available < minimum:
        raise SetupRefused(f"candidate filesystem needs at least {minimum} free bytes")


def download_models(manifest: Mapping[str, Any]) -> None:
    ensure_download_capacity(manifest)
    for row in manifest["model_bundle"]["files"]:
        download_verified_model(row)


def download_verified_model(row: Mapping[str, Any]) -> None:
    relative = safe_relative_model_path(row["path"])
    destination = EXPECTED_ROOT.joinpath(*relative.parts)
    assert_candidate_path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    assert_candidate_path(destination.parent, allow_missing=False)
    expected_size = int(row["bytes"])
    expected_hash = str(row["sha256"]).lower()
    if destination.exists():
        size, digest = hash_regular_file(destination)
        if (size, digest) == (expected_size, expected_hash):
            print(f"verified existing model: {relative}", flush=True)
            return
        raise SetupRefused(f"existing model does not match the manifest: {relative}")
    temporary = destination.with_suffix(destination.suffix + ".part")
    assert_candidate_path(temporary)
    if temporary.is_symlink():
        raise SetupRefused(f"partial model path is a symbolic link: {relative}")
    offset = temporary.stat().st_size if temporary.exists() else 0
    if offset > expected_size:
        raise SetupRefused(f"partial model exceeds the expected size: {relative}")
    headers = {"User-Agent": USER_AGENT}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    request = Request(model_source_url(row), headers=headers)
    try:
        response = urlopen(request, timeout=120)
    except (HTTPError, URLError, OSError) as exc:
        raise SetupRefused(f"model download could not start: {relative}") from exc
    status = getattr(response, "status", response.getcode())
    mode = "ab" if offset and status == 206 else "wb"
    if mode == "wb":
        offset = 0
    downloaded = offset
    last_report = time.monotonic()
    try:
        with response, temporary.open(mode) as stream:
            while True:
                chunk = response.read(DOWNLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                stream.write(chunk)
                downloaded += len(chunk)
                if downloaded > expected_size:
                    raise SetupRefused(f"download exceeded the expected size: {relative}")
                if time.monotonic() - last_report >= 10:
                    percent = downloaded * 100 / expected_size
                    print(f"downloading {relative}: {percent:.1f}%", flush=True)
                    last_report = time.monotonic()
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise SetupRefused(f"model download was interrupted: {relative}") from exc
    size, digest = hash_regular_file(temporary)
    if (size, digest) != (expected_size, expected_hash):
        raise SetupRefused(f"downloaded model failed integrity verification: {relative}")
    temporary.replace(destination)
    print(f"downloaded and verified model: {relative}", flush=True)


def hash_regular_file(path: Path) -> tuple[int, str]:
    if path.is_symlink() or not path.is_file():
        raise SetupRefused(f"model is not a regular file: {path.name}")
    before = path.stat()
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(HASH_CHUNK_BYTES):
            digest.update(chunk)
    after = path.stat()
    identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if identity_before != identity_after:
        raise SetupRefused(f"model changed during verification: {path.name}")
    return before.st_size, digest.hexdigest()


def port_is_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True


def start_candidate(python: Path, *, expected_commit: str) -> int:
    verify_checkout(expected_commit)
    pid_path = EXPECTED_BASE / "candidate.pid"
    log_path = EXPECTED_BASE / "candidate.log"
    assert_candidate_path(pid_path)
    assert_candidate_path(log_path)
    if pid_path.exists():
        pid = read_candidate_pid(pid_path)
        if candidate_process_matches(pid):
            raise SetupRefused(f"candidate is already running as PID {pid}")
        raise SetupRefused("stale candidate.pid exists; inspect it before retrying")
    if not port_is_available(EXPECTED_BIND, EXPECTED_PORT):
        raise SetupRefused("candidate port is already in use")
    with log_path.open("ab") as log:
        process = subprocess.Popen(
            [
                str(python),
                "main.py",
                "--listen",
                EXPECTED_BIND,
                "--port",
                str(EXPECTED_PORT),
            ],
            cwd=EXPECTED_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    pid_path.write_text(f"{process.pid}\n", encoding="ascii")
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise SetupRefused("candidate exited during startup; inspect candidate.log")
        try:
            with urlopen(
                f"http://{EXPECTED_BIND}:{EXPECTED_PORT}/system_stats", timeout=3
            ) as response:
                if response.status == 200:
                    print(f"candidate ready on loopback as PID {process.pid}")
                    return process.pid
        except (HTTPError, URLError, OSError):
            time.sleep(2)
    raise SetupRefused("candidate did not become ready within 120 seconds")


def read_candidate_pid(path: Path) -> int:
    try:
        value = int(path.read_text(encoding="ascii").strip())
    except (OSError, ValueError) as exc:
        raise SetupRefused("candidate PID file is invalid") from exc
    if value <= 1:
        raise SetupRefused("candidate PID is unsafe")
    return value


def candidate_process_matches(pid: int) -> bool:
    try:
        command = (Path("/proc") / str(pid) / "cmdline").read_bytes().replace(b"\0", b" ").decode()
        cwd = (Path("/proc") / str(pid) / "cwd").resolve(strict=True)
    except (OSError, UnicodeDecodeError):
        return False
    return (
        cwd == EXPECTED_ROOT
        and "main.py" in command
        and f"--port {EXPECTED_PORT}" in command
        and f"--listen {EXPECTED_BIND}" in command
    )


def stop_candidate() -> None:
    pid_path = EXPECTED_BASE / "candidate.pid"
    assert_candidate_path(pid_path)
    if not pid_path.is_file() or pid_path.is_symlink():
        raise SetupRefused("candidate PID file is missing or unsafe")
    pid = read_candidate_pid(pid_path)
    if not candidate_process_matches(pid):
        raise SetupRefused("PID does not identify the isolated candidate; refusing to signal it")
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if not candidate_process_matches(pid):
            pid_path.unlink()
            print("isolated candidate stopped")
            return
        time.sleep(0.5)
    raise SetupRefused("candidate did not stop after SIGTERM; no broader signal was sent")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--check-manifest-only", action="store_true")
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--download-models", action="store_true")
    parser.add_argument("--start", action="store_true")
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--acknowledge-license-review-required", action="store_true")
    parser.add_argument("--conda", type=Path, default=DEFAULT_CONDA)
    parser.add_argument("--source-env", type=Path, default=DEFAULT_SOURCE_ENV)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        manifest = load_manifest(args.manifest)
        if args.check_manifest_only:
            print(json.dumps({"status": "manifest_ok", "candidate_root": str(EXPECTED_ROOT), "model_count": 4}))
            return 0
        selected = sum(bool(value) for value in (args.prepare, args.download_models, args.start, args.stop))
        if not selected:
            raise SetupRefused("choose at least one operation")
        if args.stop and selected != 1:
            raise SetupRefused("--stop must be used alone")
        if args.stop:
            stop_candidate()
            return 0
        if not args.acknowledge_license_review_required:
            raise SetupRefused(
                "--acknowledge-license-review-required is mandatory; setup never approves promotion"
            )
        prepare_checkout(manifest)
        python = prepare_environment(manifest, conda=args.conda, source_env=args.source_env)
        if args.download_models:
            download_models(manifest)
        if args.start:
            # Starting without downloads remains fail-closed because ComfyUI will not expose the pinned files.
            start_candidate(python, expected_commit=str(manifest["runtime"]["commit"]))
        print(
            json.dumps(
                {
                    "status": "candidate_prepared",
                    "production_changed": False,
                    "release_ready": False,
                    "models_requested": bool(args.download_models),
                    "started": bool(args.start),
                    "next": "run scripts/qualify_comfyui_candidate.py locally on Nvidia-2, then obtain separate named human visual approval",
                },
                indent=2,
            )
        )
        return 0
    except SetupRefused as exc:
        print(json.dumps({"status": "refused", "reason": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
