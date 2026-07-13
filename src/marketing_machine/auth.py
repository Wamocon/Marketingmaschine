from __future__ import annotations

import ipaddress
import hashlib
import hmac
import os
import re
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


MUTATION_TOKEN_ENV = "MARKETING_MACHINE_MUTATION_TOKEN"
MUTATION_TOKEN_FILE_ENV = "MARKETING_MACHINE_MUTATION_TOKEN_FILE"
MUTATION_AUTH_MODE_ENV = "MARKETING_MACHINE_MUTATION_AUTH_MODE"
MUTATION_TOKEN_HEADER = "X-WAMOCON-Mutation-Token"
EDGE_ATTESTATION_ENV = "MARKETING_MACHINE_EDGE_ATTESTATION"
EDGE_ATTESTATION_FILE_ENV = "MARKETING_MACHINE_EDGE_ATTESTATION_FILE"
ACTOR_AUTH_MODE_ENV = "MARKETING_MACHINE_ACTOR_AUTH_MODE"
EDGE_ATTESTATION_HEADER = "X-WAMOCON-Edge-Attestation"
ACTOR_HEADER = "X-WAMOCON-Actor"
REQUIRED_MODE = "required"
LOCAL_DEV_DISABLED_MODE = "local-dev-disabled"
LOCAL_OPTIONAL_MODE = "local-optional"
MINIMUM_TOKEN_CHARACTERS = 32
MINIMUM_EDGE_ATTESTATION_CHARACTERS = 64
PLACEHOLDER_TOKENS = {
    "changeme",
    "change-me",
    "replace-me",
    "replace-with-random-secret",
    "secret",
    "password",
}
RESERVED_ACTOR_NAMES = {
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
ACTOR_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@-]{1,99}$")


@dataclass(frozen=True)
class MutationAuthorizationError(Exception):
    status_code: int
    detail: str

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class ActorAuthenticationError(Exception):
    status_code: int
    detail: str

    def __str__(self) -> str:
        return self.detail


def mutation_authorization_status(env: Mapping[str, str] | None = None) -> dict[str, object]:
    values = env if env is not None else os.environ
    configured_token, token_source = _configured_token(values)
    token_present = bool(configured_token)
    token_configured = _token_is_acceptable(configured_token)
    requested_mode = values.get(MUTATION_AUTH_MODE_ENV, REQUIRED_MODE).strip().lower() or REQUIRED_MODE
    mode_valid = requested_mode in {REQUIRED_MODE, LOCAL_DEV_DISABLED_MODE}

    if token_configured:
        status = "protected"
        action = "Mutation requests require the configured header token."
    elif token_present:
        status = "blocked_weak_token"
        action = (
            f"Replace {MUTATION_TOKEN_ENV} with at least {MINIMUM_TOKEN_CHARACTERS} random characters; "
            "mutations are denied."
        )
    elif requested_mode == LOCAL_DEV_DISABLED_MODE:
        status = "unsafe_local_dev_only"
        action = (
            f"Set {MUTATION_TOKEN_ENV} before any network deployment; unauthenticated mutations are loopback-only."
        )
    elif mode_valid:
        status = "blocked_missing_token"
        action = f"Set {MUTATION_TOKEN_ENV}; mutations are denied until it is configured."
    else:
        status = "blocked_invalid_mode"
        action = (
            f"Set {MUTATION_AUTH_MODE_ENV} to {REQUIRED_MODE} or {LOCAL_DEV_DISABLED_MODE}; mutations are denied."
        )

    return {
        "status": status,
        "safe": token_configured,
        "token_configured": token_configured,
        "token_present": token_present,
        "mode": requested_mode,
        "mode_valid": mode_valid,
        "header": MUTATION_TOKEN_HEADER,
        "token_source": token_source,
        "action": action,
    }


def authorize_mutation(
    provided_token: str | None,
    *,
    client_host: str | None,
    env: Mapping[str, str] | None = None,
) -> None:
    """Authorize one state-changing request without disclosing token material."""

    values = env if env is not None else os.environ
    configured_token, _ = _configured_token(values)
    mode = values.get(MUTATION_AUTH_MODE_ENV, REQUIRED_MODE).strip().lower() or REQUIRED_MODE

    if configured_token and not _token_is_acceptable(configured_token):
        raise MutationAuthorizationError(503, "mutation authorization token is too weak; mutations are disabled")

    if configured_token:
        candidate = str(provided_token or "").strip()
        if not candidate or not secrets.compare_digest(
            candidate.encode("utf-8"), configured_token.encode("utf-8")
        ):
            raise MutationAuthorizationError(401, "valid mutation authorization is required")
        return

    if mode == LOCAL_DEV_DISABLED_MODE:
        if _is_loopback_client(client_host):
            return
        raise MutationAuthorizationError(
            403,
            "mutation authorization may be disabled only for a loopback local-development client",
        )

    if mode != REQUIRED_MODE:
        raise MutationAuthorizationError(503, "mutation authorization mode is invalid; mutations are disabled")
    raise MutationAuthorizationError(503, "mutation authorization is not configured; mutations are disabled")


def actor_authentication_required(env: Mapping[str, str] | None = None) -> bool:
    values = env if env is not None else os.environ
    return _actor_auth_mode(values) == REQUIRED_MODE


def edge_actor_authorization_status(env: Mapping[str, str] | None = None) -> dict[str, object]:
    """Describe whether nginx-attested, named human actors can be trusted.

    Local development deliberately defaults to ``local-optional``. Production
    compose sets ``required`` and mounts a second Docker secret which must be
    different from the general agent access token.
    """

    values = env if env is not None else os.environ
    mode = _actor_auth_mode(values)
    mode_valid = mode in {REQUIRED_MODE, LOCAL_OPTIONAL_MODE}
    attestation, source = _configured_edge_attestation(values)
    mutation_token, _ = _configured_token(values)
    present = bool(attestation)
    acceptable = _edge_attestation_is_acceptable(attestation, mutation_token)

    if not mode_valid:
        status = "blocked_invalid_mode"
        action = (
            f"Set {ACTOR_AUTH_MODE_ENV} to {REQUIRED_MODE} or {LOCAL_OPTIONAL_MODE}; "
            "sensitive human operations are denied."
        )
    elif acceptable:
        status = "protected" if mode == REQUIRED_MODE else "available_local_optional"
        action = "Named actors are trusted only when bound to the independent edge attestation."
    elif present or source not in {"none"}:
        status = "blocked_weak_or_reused_attestation"
        action = (
            f"Replace {EDGE_ATTESTATION_ENV} with a distinct random 32-byte hexadecimal secret; "
            "sensitive human operations are denied."
        )
    elif mode == REQUIRED_MODE:
        status = "blocked_missing_attestation"
        action = f"Set {EDGE_ATTESTATION_FILE_ENV}; sensitive human operations are denied."
    else:
        status = "local_optional_unattested"
        action = (
            f"Set {ACTOR_AUTH_MODE_ENV}={REQUIRED_MODE} and mount {EDGE_ATTESTATION_FILE_ENV} "
            "before any production deployment."
        )

    safe = bool(
        mode_valid
        and (
            acceptable
            or mode == LOCAL_OPTIONAL_MODE
            and not present
            and source == "none"
        )
    )
    return {
        "status": status,
        "safe": safe,
        "production_ready": bool(mode == REQUIRED_MODE and acceptable),
        "mode": mode,
        "mode_valid": mode_valid,
        "attestation_configured": acceptable,
        "attestation_present": present,
        "attestation_source": source,
        "actor_header": ACTOR_HEADER,
        "attestation_header": EDGE_ATTESTATION_HEADER,
        "action": action,
    }


def authenticate_edge_actor(
    provided_actor: str | None,
    provided_attestation: str | None,
    *,
    required: bool,
    env: Mapping[str, str] | None = None,
) -> str | None:
    """Return a trusted named actor only after validating edge attestation.

    An actor header by itself is caller-controlled and is never trusted. Header
    pairs are validated even in local-optional mode so an accidental or forged
    identity cannot silently enter the audit trail.
    """

    values = env if env is not None else os.environ
    mode = _actor_auth_mode(values)
    if mode not in {REQUIRED_MODE, LOCAL_OPTIONAL_MODE}:
        raise ActorAuthenticationError(503, "actor authentication mode is invalid; sensitive operations are disabled")

    actor = str(provided_actor or "").strip()
    candidate = str(provided_attestation or "").strip()
    if not actor and not candidate and not required:
        return None

    configured, _ = _configured_edge_attestation(values)
    mutation_token, _ = _configured_token(values)
    if configured and not _edge_attestation_is_acceptable(configured, mutation_token):
        raise ActorAuthenticationError(
            503,
            "edge attestation is weak or reuses the agent token; sensitive operations are disabled",
        )
    if not configured:
        if actor or candidate:
            raise ActorAuthenticationError(401, "a trusted edge actor could not be verified")
        raise ActorAuthenticationError(503, "edge actor attestation is not configured")
    if not actor or not candidate:
        raise ActorAuthenticationError(401, "a named actor with valid edge attestation is required")
    if not secrets.compare_digest(candidate.encode("utf-8"), configured.encode("utf-8")):
        raise ActorAuthenticationError(401, "a named actor with valid edge attestation is required")
    if not _actor_is_acceptable(actor):
        raise ActorAuthenticationError(403, "a distinct named human account is required")
    return actor


def audit_request_fingerprint(
    *,
    method: str,
    path: str,
    query: str,
    body: bytes,
    env: Mapping[str, str] | None = None,
) -> str:
    """Return a PII-free keyed request digest for the append-only audit log."""

    values = env if env is not None else os.environ
    material = b"\x00".join(
        (
            method.upper().encode("utf-8"),
            path.encode("utf-8"),
            query.encode("utf-8"),
            body,
        )
    )
    attestation, _ = _configured_edge_attestation(values)
    if attestation:
        return hmac.new(attestation.encode("utf-8"), material, hashlib.sha256).hexdigest()
    return hashlib.sha256(material).hexdigest()


def _configured_token(values: Mapping[str, str]) -> tuple[str, str]:
    direct = values.get(MUTATION_TOKEN_ENV, "").strip()
    if direct:
        return direct, "environment"
    token_file = values.get(MUTATION_TOKEN_FILE_ENV, "").strip()
    if not token_file:
        return "", "none"
    try:
        token = Path(token_file).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return "", "unreadable_file"
    return (token, "secret_file") if token else ("", "empty_file")


def _configured_edge_attestation(values: Mapping[str, str]) -> tuple[str, str]:
    direct = values.get(EDGE_ATTESTATION_ENV, "").strip()
    if direct:
        return direct, "environment"
    token_file = values.get(EDGE_ATTESTATION_FILE_ENV, "").strip()
    if not token_file:
        return "", "none"
    try:
        token = Path(token_file).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return "", "unreadable_file"
    return (token, "secret_file") if token else ("", "empty_file")


def _token_is_acceptable(token: str) -> bool:
    candidate = token.strip()
    return (
        len(candidate) >= MINIMUM_TOKEN_CHARACTERS
        and candidate.casefold() not in PLACEHOLDER_TOKENS
        and not any(character.isspace() for character in candidate)
    )


def _edge_attestation_is_acceptable(attestation: str, mutation_token: str) -> bool:
    candidate = attestation.strip()
    if (
        len(candidate) < MINIMUM_EDGE_ATTESTATION_CHARACTERS
        or candidate.casefold() in PLACEHOLDER_TOKENS
        or any(character not in "0123456789abcdefABCDEF" for character in candidate)
    ):
        return False
    if mutation_token and secrets.compare_digest(
        candidate.encode("utf-8"), mutation_token.strip().encode("utf-8")
    ):
        return False
    return True


def _actor_auth_mode(values: Mapping[str, str]) -> str:
    return values.get(ACTOR_AUTH_MODE_ENV, LOCAL_OPTIONAL_MODE).strip().lower() or LOCAL_OPTIONAL_MODE


def _actor_is_acceptable(actor: str) -> bool:
    return bool(
        ACTOR_PATTERN.fullmatch(actor)
        and actor.casefold() not in RESERVED_ACTOR_NAMES
        and not actor.casefold().startswith(("service-", "automation-", "service.", "automation."))
    )


def _is_loopback_client(client_host: str | None) -> bool:
    candidate = str(client_host or "").strip().lower()
    if candidate == "localhost":
        return True
    try:
        return ipaddress.ip_address(candidate).is_loopback
    except ValueError:
        return False
