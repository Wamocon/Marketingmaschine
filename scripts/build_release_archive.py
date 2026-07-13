#!/usr/bin/env python3
"""Build a deterministic, fail-closed Marketing Machine release archive.

The release is assembled from an explicit set of project roots.  Runtime data,
local environments, caches, credentials and existing build artifacts are never
copied.  Files are read and validated before the archive is opened, so a failed
validation cannot leave a seemingly usable release behind.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import math
import os
import re
import stat
import sys
import tarfile
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Iterable, cast
from urllib.parse import unquote, urlsplit


SCHEMA_VERSION = 1
DEFAULT_ARCHIVE_ROOT = "wamocon-marketing-machine"
DEFAULT_SOURCE_DATE_EPOCH = 0
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_RELEASE_BYTES = 512 * 1024 * 1024
MAX_DOCX_EXPANDED_BYTES = 64 * 1024 * 1024

PROJECT_DIRECTORIES = (
    "config",
    "db",
    "deploy",
    "docs",
    "Kampagnen",
    "requirements",
    "scripts",
    "src",
    "tests",
    "Zielgruppen",
)

ROOT_FILES = {
    ".gitattributes",
    ".dockerignore",
    ".gitignore",
    "Dockerfile",
    "README.md",
    "bot_architektur.json",
    "package-lock.json",
    "package.json",
    "pyproject.toml",
}

EXCLUDED_DIRECTORY_NAMES = {
    ".git",
    ".mypy_cache",
    ".nox",
    ".pytest_cache",
    ".ruff_cache",
    ".runtime-lock-check",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "candidate-runtime-data",
    "dist",
    "node_modules",
    "qa_output",
    "runtime-data",
    "test-results",
    "venv",
}

# These locations may legitimately exist on an operator workstation.  They are
# excluded without reading them; credential-like files elsewhere fail closed.
PRIVATE_DIRECTORY_NAMES = {
    ".credentials",
    ".secrets",
    "certificates",
    "certs",
    "credentials",
    "private",
    "secrets",
}

RUNTIME_SUFFIXES = {
    ".bak",
    ".db",
    ".log",
    ".sqlite",
    ".sqlite3",
    ".swp",
    ".tmp",
}
PRIVATE_SUFFIXES = {
    ".cer",
    ".crt",
    ".der",
    ".jks",
    ".key",
    ".keystore",
    ".p12",
    ".pem",
    ".pfx",
}
ARCHIVE_SUFFIXES = (
    ".7z",
    ".bz2",
    ".gz",
    ".rar",
    ".tar",
    ".tar.bz2",
    ".tar.gz",
    ".tar.xz",
    ".tgz",
    ".txz",
    ".xz",
    ".zip",
)
IMAGE_SIGNATURES = {
    ".gif": (b"GIF87a", b"GIF89a"),
    ".ico": (b"\x00\x00\x01\x00",),
    ".jpeg": (b"\xff\xd8\xff",),
    ".jpg": (b"\xff\xd8\xff",),
    ".png": (b"\x89PNG\r\n\x1a\n",),
    ".webp": (b"RIFF",),
}
SAFE_DOCX_PATH = "docs/WAMOCON-Marketing-Handbuch.docx"
SAFE_ARCHIVE_ROOT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")

SECRET_NAME_RE = re.compile(
    r"(?:^|[._-])(?:api[_-]?key|client[_-]?secret|credential|htpasswd|"
    r"password|passwd|private[_-]?key|secret|token)(?:$|[._-])",
    re.IGNORECASE,
)
PEM_RE = re.compile(
    r"-----BEGIN\s+(?:(?:RSA|EC|OPENSSH|DSA)\s+)?(?:PRIVATE KEY|CERTIFICATE)-----",
    re.IGNORECASE,
)
KNOWN_CREDENTIAL_RES = (
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    re.compile(r"\bgh[pousr]_[0-9A-Za-z]{30,}\b"),
    re.compile(r"\bsk-[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\bxox[baprs]-[0-9A-Za-z-]{20,}\b"),
    re.compile(r"\beyJ[0-9A-Za-z_-]{8,}\.[0-9A-Za-z_-]{8,}\.[0-9A-Za-z_-]{8,}\b"),
)
SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"(?im)(?<![A-Za-z0-9])"
    r"[\"']?(?:api[_-]?key|private[_-]?key|encryption[_-]?key|"
    r"(?:[A-Za-z0-9]+[_-])+(?:secret|token|password|passwd)|"
    r"secret|token|password|passwd)[\"']?"
    r"[ \t]*[:=][ \t]*"
    r"(?:\$\{(?P<shell>[^{}\r\n]{1,256})\}|"
    r"\"(?P<double>[^\"\r\n]*)\"|'(?P<single>[^'\r\n]*)'|(?P<bare>[^\s,#]+))"
)
SAFE_PLACEHOLDER_VALUES = frozenset(
    {
        "change-me",
        "changeme",
        "configured",
        "demo",
        "dummy",
        "example",
        "fake",
        "local-dev-key",
        "mock",
        "not-configured",
        "placeholder",
        "redacted",
        "replace-me",
        "replace-with-32-random-bytes-or-valid-key",
        "replace-with-64-random-characters",
        "replace-with-a-long-random-password",
        "replace-with-random-app-secret",
        "replace-with-random-password",
        "replace-with-random-root-password",
        "sample",
        "secret-value",
        "test",
        "your-key",
        "your-secret",
        "your-token",
    }
)
SHELL_PLACEHOLDER_RE = re.compile(
    r"\$\{[A-Za-z_][A-Za-z0-9_]*(?::[?+\-=][^{}\r\n]{0,160})?\}\Z"
)
ANGLE_PLACEHOLDER_RE = re.compile(r"<[A-Z][A-Z0-9_.:-]{1,80}>\Z")
TEMPLATE_PLACEHOLDER_RE = re.compile(r"=?\{\{[^{}\r\n]{1,256}\}\}\Z")
RUNTIME_SECRET_LOOKUP_RE = re.compile(
    r"(?:os\.environ\.get|os\.getenv|getenv|self\.env\.get|config\.get|settings\.get|checks\.get|"
    r"load_secret|_secret_file)"
    r"\(\s*(?:[\"'][A-Za-z_][A-Za-z0-9_]*[\"']|"
    r"[A-Za-z_][A-Za-z0-9_.]{0,127})(?:\s*,[^)]*)?\)?\Z"
)
RUNTIME_SECRET_FILE_LOOKUP_RE = re.compile(
    r"\$\$?\(cat (?:/run/secrets|deploy/secrets)/"
    r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\)\Z"
)
PROCESS_ENV_LOOKUP_RE = re.compile(
    r"process\.env\.[A-Za-z_][A-Za-z0-9_]*\Z"
)
ENV_MAPPING_LOOKUP_RE = re.compile(
    r"(?:self\.)?env\[[\"'][A-Za-z_][A-Za-z0-9_]*[\"']\]\Z"
)
SOURCE_CALL_EXPRESSION_RE = re.compile(
    r"[A-Za-z_][A-Za-z0-9_.]*\([A-Za-z_][A-Za-z0-9_.]*(?:\s*,\s*[A-Za-z_][A-Za-z0-9_.]*)*\)?\Z"
)
PYTHON_SECRET_FILE_LOOKUP_RE = re.compile(
    r"Path\([A-Za-z_][A-Za-z0-9_.]*\)\.read_text\(encoding=[\"']utf-8[\"']\)\.strip\(\)\Z"
)


class ReleaseBuildError(RuntimeError):
    """Raised when a source tree cannot be packaged safely."""


@dataclass(frozen=True)
class ReleaseFile:
    path: str
    content: bytes
    mode: int
    sha256: str

    @property
    def size(self) -> int:
        return len(self.content)


@dataclass(frozen=True)
class BuildResult:
    archive: Path
    sha256_sidecar: Path
    inventory: Path
    archive_sha256: str
    archive_size: int
    file_count: int


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_generated_env(name: str) -> bool:
    lowered = name.lower()
    return lowered.endswith(".generated.env") or lowered.endswith(".env.generated")


def _is_env_file(name: str) -> bool:
    lowered = name.lower()
    return (
        lowered == ".env"
        or lowered.startswith(".env.")
        or lowered.endswith(".env")
        or ".env." in lowered
    )


def _is_example_env(name: str) -> bool:
    lowered = name.lower()
    markers = ("example", "sample", "template")
    return _is_env_file(lowered) and any(
        lowered.endswith(f".{marker}")
        or lowered.endswith(f".{marker}.env")
        or f".{marker}.env." in lowered
        for marker in markers
    )


def _is_existing_archive(name: str) -> bool:
    lowered = name.lower()
    return any(lowered.endswith(suffix) for suffix in ARCHIVE_SUFFIXES)


def _is_root_file_allowed(path: Path) -> bool:
    return path.name in ROOT_FILES or path.suffix.lower() == ".md"


def _has_control_characters(value: str) -> bool:
    return any(ord(character) < 32 for character in value)


def _entropy(value: str) -> float:
    if not value:
        return 0.0
    frequencies: dict[str, int] = {}
    for character in value:
        frequencies[character] = frequencies.get(character, 0) + 1
    length = len(value)
    return -sum(
        (count / length) * math.log2(count / length)
        for count in frequencies.values()
    )


def _looks_like_real_secret(value: str) -> bool:
    candidate = value.strip()
    if len(candidate) >= 2 and candidate[0] == candidate[-1] and candidate[0] in "\"'":
        candidate = candidate[1:-1]
    lowered = candidate.lower()
    if not candidate or lowered in SAFE_PLACEHOLDER_VALUES:
        return False
    if (
        SHELL_PLACEHOLDER_RE.fullmatch(candidate)
        or ANGLE_PLACEHOLDER_RE.fullmatch(candidate)
        or TEMPLATE_PLACEHOLDER_RE.fullmatch(candidate)
        or RUNTIME_SECRET_LOOKUP_RE.fullmatch(candidate)
        or RUNTIME_SECRET_FILE_LOOKUP_RE.fullmatch(candidate)
        or PROCESS_ENV_LOOKUP_RE.fullmatch(candidate)
        or ENV_MAPPING_LOOKUP_RE.fullmatch(candidate)
        or SOURCE_CALL_EXPRESSION_RE.fullmatch(candidate)
        or PYTHON_SECRET_FILE_LOOKUP_RE.fullmatch(candidate)
    ):
        return False
    return len(candidate) >= 24 and _entropy(candidate) >= 3.5


def _scan_text_for_credentials(text: str, relative_path: str) -> None:
    if PEM_RE.search(text):
        raise ReleaseBuildError(f"certificate or private key material found in {relative_path}")
    for pattern in KNOWN_CREDENTIAL_RES:
        if pattern.search(text):
            raise ReleaseBuildError(f"credential material found in {relative_path}")
    for match in SENSITIVE_ASSIGNMENT_RE.finditer(text):
        shell_value = match.group("shell")
        value = (
            f"${{{shell_value}}}"
            if shell_value is not None
            else next(
                (
                    group
                    for group in (
                        match.group("double"),
                        match.group("single"),
                        match.group("bare"),
                    )
                    if group is not None
                ),
                "",
            )
        )
        if (
            match.group("bare") is not None
            and match.group(0)[:1] in {"\"", "'"}
            and value.endswith(match.group(0)[0])
        ):
            value = value[:-1]
        if _looks_like_real_secret(value):
            raise ReleaseBuildError(f"high-entropy credential assignment found in {relative_path}")


def _safe_local_hyperlink(target: str, relative_path: str) -> bool:
    """Return whether a relative Word hyperlink stays inside the release root."""

    parsed = urlsplit(target)
    if (
        parsed.scheme
        or parsed.netloc
        or parsed.query
        or target.startswith(("/", "\\"))
        or "\\" in target
    ):
        return False

    decoded_path = unquote(parsed.path)
    if (
        not (decoded_path or parsed.fragment)
        or decoded_path.startswith(("/", "\\"))
        or "\\" in decoded_path
        or ":" in decoded_path
        or _has_control_characters(decoded_path)
    ):
        return False

    resolved_parts = list(PurePosixPath(relative_path).parent.parts)
    for part in PurePosixPath(decoded_path).parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not resolved_parts:
                return False
            resolved_parts.pop()
            continue
        resolved_parts.append(part)
    return bool(resolved_parts or parsed.fragment)


def _validate_external_relationships(payload: bytes, relative_path: str) -> None:
    try:
        relationships = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise ReleaseBuildError(f"invalid Word relationship XML in {relative_path}") from exc
    for relationship in relationships:
        if relationship.attrib.get("TargetMode", "").casefold() != "external":
            continue
        relationship_type = relationship.attrib.get("Type", "")
        target = relationship.attrib.get("Target", "")
        parsed = urlsplit(target)
        is_hyperlink = relationship_type.casefold().endswith("/hyperlink")
        is_safe_https_hyperlink = (
            parsed.scheme.casefold() == "https"
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and not _has_control_characters(target)
            and not _has_control_characters(unquote(target))
        )
        is_safe_hyperlink = is_hyperlink and (
            is_safe_https_hyperlink or _safe_local_hyperlink(target, relative_path)
        )
        if not is_safe_hyperlink:
            raise ReleaseBuildError(f"unsafe external Word relationship found in {relative_path}")


def _validate_docx(content: bytes, relative_path: str) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as document:
            member_names = document.namelist()
            names = set(member_names)
            if len(names) != len(member_names):
                raise ReleaseBuildError(f"duplicate Word package member in {relative_path}")
            if "[Content_Types].xml" not in names or "word/document.xml" not in names:
                raise ReleaseBuildError(f"invalid Word document structure in {relative_path}")

            expanded_size = 0
            for entry in document.infolist():
                member = entry.filename
                member_path = PurePosixPath(member)
                if (
                    "\\" in member
                    or member.startswith("/")
                    or ".." in member_path.parts
                    or _has_control_characters(member)
                ):
                    raise ReleaseBuildError(f"unsafe Word package member in {relative_path}")
                unix_mode = (entry.external_attr >> 16) & 0xFFFF
                if unix_mode and stat.S_ISLNK(unix_mode):
                    raise ReleaseBuildError(f"symlink found inside Word document {relative_path}")
                if entry.flag_bits & 0x1:
                    raise ReleaseBuildError(f"encrypted Word package member in {relative_path}")
                lowered = member.lower()
                if (
                    "vbaproject" in lowered
                    or lowered.startswith("word/activex/")
                    or lowered.startswith("word/embeddings/")
                ):
                    raise ReleaseBuildError(f"active or embedded content found in {relative_path}")
                expanded_size += entry.file_size
                if expanded_size > MAX_DOCX_EXPANDED_BYTES:
                    raise ReleaseBuildError(f"expanded Word document is too large: {relative_path}")
                if lowered.endswith((".xml", ".rels")):
                    payload = document.read(entry)
                    if lowered.endswith(".rels"):
                        _validate_external_relationships(payload, relative_path)
                    _scan_text_for_credentials(
                        payload.decode("utf-8", errors="replace"), relative_path
                    )
            bad_member = document.testzip()
            if bad_member:
                raise ReleaseBuildError(
                    f"corrupt Word package member {bad_member!r} in {relative_path}"
                )
    except (zipfile.BadZipFile, OSError) as exc:
        raise ReleaseBuildError(f"invalid Word document {relative_path}: {exc}") from exc


def _validate_content(content: bytes, relative_path: str) -> None:
    suffix = Path(relative_path).suffix.lower()
    if relative_path == SAFE_DOCX_PATH:
        _validate_docx(content, relative_path)
        return
    if suffix == ".docx":
        raise ReleaseBuildError(
            f"unexpected Word document {relative_path}; only {SAFE_DOCX_PATH} is allowed"
        )
    if suffix in IMAGE_SIGNATURES:
        signatures = IMAGE_SIGNATURES[suffix]
        if not any(content.startswith(signature) for signature in signatures):
            raise ReleaseBuildError(f"invalid image signature in {relative_path}")
        if suffix == ".webp" and content[8:12] != b"WEBP":
            raise ReleaseBuildError(f"invalid WebP signature in {relative_path}")
        return
    if b"\x00" in content:
        raise ReleaseBuildError(f"unsupported binary file in release source: {relative_path}")
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReleaseBuildError(f"non-UTF-8 file in release source: {relative_path}") from exc
    _scan_text_for_credentials(text, relative_path)


def _relative_posix(path: Path, root: Path) -> str:
    relative = path.relative_to(root).as_posix()
    if (
        not relative
        or relative.startswith("/")
        or "\\" in relative
        or ".." in PurePosixPath(relative).parts
        or _has_control_characters(relative)
    ):
        raise ReleaseBuildError(f"unsafe release path: {relative!r}")
    return relative


def _classify_path(path: Path, relative_path: str) -> str:
    """Return ``include``, ``exclude`` or raise for unsafe path names."""

    name = path.name
    lowered = name.lower()
    if name.startswith("~$"):
        return "exclude"
    if _is_generated_env(name):
        return "exclude"
    if _is_env_file(name) and not _is_example_env(name):
        raise ReleaseBuildError(f"private environment file found: {relative_path}")
    if lowered.endswith(".pdf") or _is_existing_archive(name):
        return "exclude"
    if path.suffix.lower() in RUNTIME_SUFFIXES:
        return "exclude"
    if path.suffix.lower() in PRIVATE_SUFFIXES:
        raise ReleaseBuildError(f"private key or certificate file found: {relative_path}")
    if SECRET_NAME_RE.search(name):
        raise ReleaseBuildError(f"secret-looking file name found: {relative_path}")
    return "include"


def _read_release_file(path: Path, root: Path) -> ReleaseFile | None:
    relative_path = _relative_posix(path, root)
    if _classify_path(path, relative_path) == "exclude":
        return None
    try:
        before = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise ReleaseBuildError(f"cannot inspect {relative_path}: {exc}") from exc
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise ReleaseBuildError(f"unsupported filesystem object: {relative_path}")
    if before.st_size > MAX_FILE_BYTES:
        raise ReleaseBuildError(f"release source file exceeds size limit: {relative_path}")
    try:
        content = path.read_bytes()
        after = path.stat(follow_symlinks=False)
    except OSError as exc:
        raise ReleaseBuildError(f"cannot read {relative_path}: {exc}") from exc
    stable_fields = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns")
    if any(getattr(before, field) != getattr(after, field) for field in stable_fields):
        raise ReleaseBuildError(f"release source changed while being read: {relative_path}")
    if len(content) != before.st_size:
        raise ReleaseBuildError(f"release source changed while being read: {relative_path}")
    _validate_content(content, relative_path)
    mode = 0o755 if path.suffix.lower() == ".sh" else 0o644
    return ReleaseFile(relative_path, content, mode, _sha256(content))


def _walk_directory(
    directory: Path,
    root: Path,
    ignored_paths: set[Path],
) -> Iterable[ReleaseFile]:
    try:
        entries = sorted(os.scandir(directory), key=lambda item: item.name)
    except OSError as exc:
        relative = _relative_posix(directory, root)
        raise ReleaseBuildError(f"cannot scan {relative}: {exc}") from exc

    for entry in entries:
        path = Path(entry.path)
        relative_path = _relative_posix(path, root)
        resolved = path.resolve(strict=False)
        if resolved in ignored_paths:
            continue
        if entry.is_symlink():
            raise ReleaseBuildError(f"symlink found in release source: {relative_path}")
        if entry.is_dir(follow_symlinks=False):
            lowered = entry.name.lower()
            if lowered in EXCLUDED_DIRECTORY_NAMES or lowered in PRIVATE_DIRECTORY_NAMES:
                continue
            if SECRET_NAME_RE.search(entry.name):
                raise ReleaseBuildError(f"secret-looking directory found: {relative_path}")
            yield from _walk_directory(path, root, ignored_paths)
            continue
        if not entry.is_file(follow_symlinks=False):
            raise ReleaseBuildError(f"unsupported filesystem object: {relative_path}")
        release_file = _read_release_file(path, root)
        if release_file is not None:
            yield release_file


def collect_release_files(
    root: Path,
    *,
    ignored_paths: Iterable[Path] = (),
) -> list[ReleaseFile]:
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ReleaseBuildError(f"release root is not a directory: {root}")
    ignored = {path.resolve(strict=False) for path in ignored_paths}
    files: list[ReleaseFile] = []

    try:
        root_entries = sorted(os.scandir(root), key=lambda item: item.name)
    except OSError as exc:
        raise ReleaseBuildError(f"cannot scan release root: {exc}") from exc

    project_directories = {name.casefold() for name in PROJECT_DIRECTORIES}
    for entry in root_entries:
        path = Path(entry.path)
        resolved = path.resolve(strict=False)
        if resolved in ignored:
            continue
        if entry.is_symlink():
            if entry.name.casefold() in project_directories or _is_root_file_allowed(path):
                raise ReleaseBuildError(f"symlink found in release source: {entry.name}")
            continue
        if entry.is_dir(follow_symlinks=False):
            if entry.name.casefold() in project_directories:
                files.extend(_walk_directory(path, root, ignored))
            continue
        if not entry.is_file(follow_symlinks=False):
            continue

        relative_path = _relative_posix(path, root)
        # Root-level private material must fail closed even though it is outside
        # the normal project-file allowlist.
        classification = _classify_path(path, relative_path)
        if classification == "exclude" or not _is_root_file_allowed(path):
            continue
        release_file = _read_release_file(path, root)
        if release_file is not None:
            files.append(release_file)

    files.sort(key=lambda item: item.path)
    if not files:
        raise ReleaseBuildError("release source contains no eligible files")
    duplicate_paths = [
        files[index].path
        for index in range(1, len(files))
        if files[index - 1].path == files[index].path
    ]
    if duplicate_paths:
        raise ReleaseBuildError(f"duplicate release paths: {duplicate_paths}")
    total_bytes = sum(item.size for item in files)
    if total_bytes > MAX_RELEASE_BYTES:
        raise ReleaseBuildError("release source exceeds total size limit")
    return files


def _inventory_payload(
    files: Iterable[ReleaseFile],
    archive_root: str,
    source_date_epoch: int,
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "archive_format": "tar+gzip",
        "archive_root": archive_root,
        "source_date_epoch": source_date_epoch,
        "files": [
            {
                "path": item.path,
                "archive_path": f"{archive_root}/{item.path}",
                "sha256": item.sha256,
                "size": item.size,
                "mode": f"{item.mode:04o}",
            }
            for item in files
        ],
    }


def _json_bytes(payload: dict[str, object]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


def _tar_info(name: str, *, mode: int, size: int, mtime: int, is_directory: bool) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name + ("/" if is_directory and not name.endswith("/") else ""))
    info.type = tarfile.DIRTYPE if is_directory else tarfile.REGTYPE
    info.mode = mode
    info.size = 0 if is_directory else size
    info.mtime = mtime
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    return info


def _archive_directories(archive_root: str, file_paths: Iterable[str]) -> list[str]:
    directories = {archive_root}
    for file_path in file_paths:
        parent = PurePosixPath(file_path).parent
        while parent != PurePosixPath("."):
            directories.add(f"{archive_root}/{parent.as_posix()}")
            parent = parent.parent
    return sorted(directories, key=lambda value: (value.count("/"), value))


def _write_archive(
    destination: Path,
    files: list[ReleaseFile],
    embedded_inventory: bytes,
    archive_root: str,
    source_date_epoch: int,
) -> None:
    member_paths = [item.path for item in files] + ["RELEASE-INVENTORY.json"]
    with destination.open("wb") as raw_output:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            compresslevel=9,
            fileobj=raw_output,
            mtime=source_date_epoch,
        ) as compressed_output:
            with tarfile.open(
                mode="w",
                fileobj=cast(BinaryIO, compressed_output),
                format=tarfile.GNU_FORMAT,
            ) as archive:
                for directory in _archive_directories(archive_root, member_paths):
                    archive.addfile(
                        _tar_info(
                            directory,
                            mode=0o755,
                            size=0,
                            mtime=source_date_epoch,
                            is_directory=True,
                        )
                    )
                for item in files:
                    archive.addfile(
                        _tar_info(
                            f"{archive_root}/{item.path}",
                            mode=item.mode,
                            size=item.size,
                            mtime=source_date_epoch,
                            is_directory=False,
                        ),
                        io.BytesIO(item.content),
                    )
                archive.addfile(
                    _tar_info(
                        f"{archive_root}/RELEASE-INVENTORY.json",
                        mode=0o644,
                        size=len(embedded_inventory),
                        mtime=source_date_epoch,
                        is_directory=False,
                    ),
                    io.BytesIO(embedded_inventory),
                )


def _validate_archive_root(value: str) -> str:
    candidate = value.strip()
    path = PurePosixPath(candidate)
    if (
        not candidate
        or path.is_absolute()
        or len(path.parts) != 1
        or path.name in {".", ".."}
        or "\\" in candidate
        or _has_control_characters(candidate)
        or SAFE_ARCHIVE_ROOT_RE.fullmatch(candidate) is None
    ):
        raise ReleaseBuildError(f"invalid archive root: {value!r}")
    return candidate


def build_release(
    root: Path,
    output: Path,
    *,
    source_date_epoch: int = DEFAULT_SOURCE_DATE_EPOCH,
    archive_root: str = DEFAULT_ARCHIVE_ROOT,
) -> BuildResult:
    root = root.resolve(strict=True)
    if output.is_symlink():
        raise ReleaseBuildError(f"output path is a symlink: {output}")
    output = output.resolve(strict=False)
    archive_root = _validate_archive_root(archive_root)
    if source_date_epoch < 0 or source_date_epoch > 0xFFFFFFFF:
        raise ReleaseBuildError("source-date-epoch must be between 0 and 4294967295")
    sha256_sidecar = Path(f"{output}.sha256")
    inventory_path = Path(f"{output}.inventory.json")
    output_paths = (output, sha256_sidecar, inventory_path)
    existing_outputs = [path for path in output_paths if path.exists() or path.is_symlink()]
    if existing_outputs:
        rendered = ", ".join(str(path) for path in existing_outputs)
        raise ReleaseBuildError(f"release output already exists: {rendered}")
    ignored_paths = {output, sha256_sidecar, inventory_path}
    files = collect_release_files(root, ignored_paths=ignored_paths)
    embedded_payload = _inventory_payload(files, archive_root, source_date_epoch)
    embedded_inventory = _json_bytes(embedded_payload)

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_paths: list[Path] = []
    published_paths: list[Path] = []
    try:
        with tempfile.NamedTemporaryFile(
            prefix=".release-archive-", suffix=".tmp", dir=output.parent, delete=False
        ) as temporary_archive_file:
            temporary_archive = Path(temporary_archive_file.name)
        temporary_paths.append(temporary_archive)
        _write_archive(
            temporary_archive,
            files,
            embedded_inventory,
            archive_root,
            source_date_epoch,
        )
        archive_content = temporary_archive.read_bytes()
        archive_sha256 = _sha256(archive_content)

        external_payload = {
            **embedded_payload,
            "archive": {
                "name": output.name,
                "sha256": archive_sha256,
                "size": len(archive_content),
            },
        }
        sidecar_content = f"{archive_sha256}  {output.name}\n".encode("ascii")
        inventory_content = _json_bytes(external_payload)

        for label, content in (
            ("sha256", sidecar_content),
            ("inventory", inventory_content),
        ):
            with tempfile.NamedTemporaryFile(
                prefix=f".release-{label}-", suffix=".tmp", dir=output.parent, delete=False
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                temporary_file.write(content)
            temporary_paths.append(temporary_path)

        os.replace(temporary_archive, output)
        published_paths.append(output)
        temporary_paths.remove(temporary_archive)
        os.replace(temporary_paths[0], sha256_sidecar)
        published_paths.append(sha256_sidecar)
        temporary_paths.pop(0)
        os.replace(temporary_paths[0], inventory_path)
        published_paths.append(inventory_path)
        temporary_paths.pop(0)
    except Exception:
        for published_path in reversed(published_paths):
            try:
                published_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise
    finally:
        for temporary_path in temporary_paths:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass

    return BuildResult(
        archive=output,
        sha256_sidecar=sha256_sidecar,
        inventory=inventory_path,
        archive_sha256=archive_sha256,
        archive_size=output.stat().st_size,
        file_count=len(files),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a deterministic, credential-safe Nvidia deployment archive."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Project root (default: repository containing this script).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("dist/wamocon-marketing-machine.tar.gz"),
        help="Archive destination; .sha256 and .inventory.json sidecars are added.",
    )
    parser.add_argument(
        "--source-date-epoch",
        type=int,
        default=int(os.environ.get("SOURCE_DATE_EPOCH", str(DEFAULT_SOURCE_DATE_EPOCH))),
        help="Normalized gzip/tar modification time (default: SOURCE_DATE_EPOCH or 0).",
    )
    parser.add_argument(
        "--archive-root",
        default=DEFAULT_ARCHIVE_ROOT,
        help=f"Single top-level archive directory (default: {DEFAULT_ARCHIVE_ROOT}).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build_release(
            args.root,
            args.output,
            source_date_epoch=args.source_date_epoch,
            archive_root=args.archive_root,
        )
    except (OSError, ReleaseBuildError, ValueError) as exc:
        print(f"release archive rejected: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "archive": str(result.archive),
                "sha256": result.archive_sha256,
                "sha256_sidecar": str(result.sha256_sidecar),
                "inventory": str(result.inventory),
                "files": result.file_count,
                "bytes": result.archive_size,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
