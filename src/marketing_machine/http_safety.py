from __future__ import annotations

from typing import Any
from urllib.request import HTTPRedirectHandler, Request, build_opener


DEFAULT_JSON_RESPONSE_LIMIT = 4 * 1024 * 1024


class _NoRedirectHandler(HTTPRedirectHandler):
    """Fail closed instead of forwarding credentials to a redirect target."""

    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


_CREDENTIAL_SAFE_OPENER = build_opener(_NoRedirectHandler())


def credential_safe_urlopen(request: Request | str, *, timeout: float) -> Any:
    """Open one exact URL without following redirects.

    Provider and model requests can carry bearer credentials.  Redirects are
    therefore treated as an upstream configuration error and must be reviewed
    explicitly rather than followed automatically.
    """

    return _CREDENTIAL_SAFE_OPENER.open(request, timeout=timeout)


def read_limited(
    response: Any,
    *,
    max_bytes: int = DEFAULT_JSON_RESPONSE_LIMIT,
    label: str = "HTTP response",
) -> bytes:
    """Read a bounded body and reject an oversized response before parsing."""

    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    payload = response.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise ValueError(f"{label} exceeded the safe size limit")
    return payload
