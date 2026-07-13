#!/usr/bin/env python3
"""Fail-closed preflight for one growth-tool Compose profile.

This script prints variable names and validation errors only. It never prints
the supplied secret values.
"""

from __future__ import annotations

import argparse
import ipaddress
import re
from pathlib import Path
from typing import TypedDict
from urllib.parse import urlsplit


DIGEST_IMAGE = re.compile(r"^[^\s]+@sha256:[a-f0-9]{64}$")
PLACEHOLDER = re.compile(
    r"replace|change[ -_]?me|example|dummy|placeholder|your[-_ ]|<.+>|password$",
    re.IGNORECASE,
)

class ProfileRules(TypedDict):
    secrets: dict[str, int]
    images: tuple[str, ...]
    canonical_urls: dict[str, tuple[str, ...]]
    uri_components: tuple[str, ...]


PROFILE_RULES: dict[str, ProfileRules] = {
    "postiz": {
        "secrets": {
            "POSTIZ_JWT_SECRET": 64,
            "POSTIZ_POSTGRES_PASSWORD": 24,
            "POSTIZ_TEMPORAL_POSTGRES_PASSWORD": 24,
        },
        "images": (
            "POSTIZ_IMAGE",
            "POSTIZ_POSTGRES_IMAGE",
            "POSTIZ_REDIS_IMAGE",
            "POSTIZ_ELASTICSEARCH_IMAGE",
            "POSTIZ_TEMPORAL_POSTGRES_IMAGE",
            "POSTIZ_TEMPORAL_IMAGE",
        ),
        "canonical_urls": {
            "POSTIZ_MAIN_URL": ("", "/"),
            "POSTIZ_FRONTEND_URL": ("", "/"),
            "POSTIZ_BACKEND_URL": ("", "/", "/api"),
        },
        "uri_components": (
            "POSTIZ_POSTGRES_USER",
            "POSTIZ_POSTGRES_PASSWORD",
            "POSTIZ_POSTGRES_DB",
        ),
    },
    "twenty": {
        "secrets": {
            "TWENTY_POSTGRES_PASSWORD": 24,
            "TWENTY_ENCRYPTION_KEY": 32,
            "TWENTY_FALLBACK_ENCRYPTION_KEY": 32,
            "TWENTY_APP_SECRET": 32,
        },
        "images": (
            "TWENTY_IMAGE",
            "TWENTY_POSTGRES_IMAGE",
            "TWENTY_REDIS_IMAGE",
        ),
        "canonical_urls": {"TWENTY_SERVER_URL": ("", "/")},
        "uri_components": (
            "TWENTY_POSTGRES_USER",
            "TWENTY_POSTGRES_PASSWORD",
            "TWENTY_POSTGRES_DB",
        ),
    },
    "mautic": {
        "secrets": {
            "MAUTIC_MYSQL_ROOT_PASSWORD": 24,
            "MAUTIC_MYSQL_PASSWORD": 24,
        },
        "images": ("MAUTIC_IMAGE", "MAUTIC_MYSQL_IMAGE"),
        "canonical_urls": {"MAUTIC_CANONICAL_URL": ("", "/")},
        "uri_components": (),
    },
}


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def validate(values: dict[str, str], profiles: list[str]) -> list[str]:
    errors: list[str] = []
    for profile in profiles:
        rules = PROFILE_RULES[profile]
        for name, minimum in rules["secrets"].items():
            value = values.get(name, "")
            if not value:
                errors.append(f"{name}: missing")
            elif PLACEHOLDER.search(value):
                errors.append(f"{name}: placeholder values are forbidden")
            elif len(value) < minimum:
                errors.append(f"{name}: must contain at least {minimum} characters")
            elif len(set(value)) < 8:
                errors.append(f"{name}: insufficient character diversity")
        for name in rules["images"]:
            value = values.get(name, "")
            if not DIGEST_IMAGE.fullmatch(value):
                errors.append(f"{name}: must be pinned with an immutable sha256 digest")
        for name, allowed_paths in rules["canonical_urls"].items():
            value = values.get(name, "")
            try:
                parsed = urlsplit(value)
                host = parsed.hostname or ""
                if parsed.scheme.casefold() != "https" or not host:
                    raise ValueError
                if parsed.username is not None or parsed.password is not None:
                    raise ValueError
                if parsed.query or parsed.fragment or parsed.path not in allowed_paths:
                    raise ValueError
                if host.casefold() == "localhost":
                    raise ValueError
                try:
                    address = ipaddress.ip_address(host)
                except ValueError:
                    address = None
                if address is not None and address.is_loopback:
                    raise ValueError
            except ValueError:
                errors.append(
                    f"{name}: must be a canonical HTTPS URL without credentials, query, fragment, or localhost"
                )
        for name in rules["uri_components"]:
            value = values.get(name, "")
            if not re.fullmatch(r"[A-Za-z0-9._~-]+", value):
                errors.append(
                    f"{name}: must use URI-safe unreserved characters because Compose embeds it in a database URL"
                )

    if "postiz" in profiles and values.get("POSTIZ_DISABLE_REGISTRATION", "").casefold() != "true":
        errors.append("POSTIZ_DISABLE_REGISTRATION: must be true")
    if "postiz" in profiles:
        postiz_authorities = {
            urlsplit(values.get(name, "")).netloc.casefold()
            for name in ("POSTIZ_MAIN_URL", "POSTIZ_FRONTEND_URL", "POSTIZ_BACKEND_URL")
            if values.get(name, "")
        }
        if len(postiz_authorities) != 1:
            errors.append("POSTIZ canonical URLs must use the same protected HTTPS authority")
    if "mautic" in profiles and values.get("MAUTIC_LOAD_TEST_DATA", "").casefold() != "false":
        errors.append("MAUTIC_LOAD_TEST_DATA: must be false")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument(
        "--profile",
        action="append",
        choices=sorted(PROFILE_RULES),
        required=True,
    )
    args = parser.parse_args()
    if not args.env_file.is_file():
        parser.error(f"env file not found: {args.env_file}")
    errors = validate(load_env(args.env_file), list(dict.fromkeys(args.profile)))
    if errors:
        print("Growth-tool preflight failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Growth-tool preflight passed for: " + ", ".join(dict.fromkeys(args.profile)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
