from __future__ import annotations

import ipaddress
import json
import os
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable

from .http_safety import DEFAULT_JSON_RESPONSE_LIMIT, credential_safe_urlopen, read_limited


def urlopen(request: str | urllib.request.Request, timeout: float) -> Any:
    """Compatibility seam backed by the credential-safe no-redirect opener."""

    return credential_safe_urlopen(request, timeout=timeout)


@dataclass(frozen=True)
class SearchResult:
    """One public-source signal before campaign grouping.

    ``published_at`` is the source publication time. ``retrieved_at`` is when
    the adapter observed the result; retrieval time must never be used as a
    substitute for publication time when proving recency.
    """

    source: str
    platform: str
    title: str
    url: str
    snippet: str = ""
    published_at: str = ""
    retrieved_at: str = ""
    metrics: dict[str, int] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_citation(self, *, retrieved_at: str = "") -> dict[str, str]:
        retrieved = self.retrieved_at or retrieved_at
        reference = parse_datetime(retrieved)
        return {
            "title": _clean_text(self.title, limit=240),
            "domain": source_domain(self.url) or ("internal" if self.source == "campaign_brief" else ""),
            "published": normalize_published(self.published_at, reference=reference),
            "retrieved": normalize_published(retrieved, reference=reference),
            "snippet": _clean_text(self.snippet, limit=500),
            "url": self.url.strip(),
        }


class TrendSearchClient:
    def search(
        self,
        query: str,
        *,
        platform: str,
        lookback_start: datetime,
        now: datetime,
        limit: int = 5,
    ) -> list[SearchResult]:
        raise NotImplementedError

    def available_sources(self) -> list[str]:
        return []

    def estimated_external_calls(self, platform: str) -> int:
        """Conservative cost of one logical search for fan-out planning."""

        return 1

    def telemetry(self) -> list[dict[str, Any]]:
        """Return adapter health without secrets, queries, or response bodies."""

        return [
            {
                "adapter": source,
                "status": "available",
                "attempts": None,
                "successful_requests": None,
                "result_count": None,
                "errors": [],
            }
            for source in self.available_sources()
        ]


@dataclass
class _AdapterTelemetry:
    attempts: int = 0
    successful_requests: int = 0
    result_count: int = 0
    budget_skipped: int = 0
    errors: dict[str, int] = field(default_factory=dict)

    def add_error(self, message: str) -> None:
        safe_message = _clean_text(message, limit=240) or "Unknown adapter error"
        self.errors[safe_message] = self.errors.get(safe_message, 0) + 1

    def to_dict(self, adapter: str) -> dict[str, Any]:
        if self.budget_skipped and (self.successful_requests or self.result_count):
            status = "partial"
        elif self.budget_skipped:
            status = "budget_exhausted"
        elif self.errors and self.successful_requests:
            status = "partial"
        elif self.errors:
            status = "error"
        elif self.result_count:
            status = "success"
        elif self.attempts:
            status = "empty"
        else:
            status = "configured"
        return {
            "adapter": adapter,
            "status": status,
            "attempts": self.attempts,
            "successful_requests": self.successful_requests,
            "result_count": self.result_count,
            "budget_skipped": self.budget_skipped,
            "errors": [
                {"message": message, "count": count}
                for message, count in sorted(self.errors.items())
            ],
        }


@dataclass
class ExternalCallBudget:
    """Thread-safe hard ceiling for adapter calls made by one research request."""

    limit: int
    used: int = 0
    denied: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def __post_init__(self) -> None:
        self.limit = max(0, int(self.limit))

    def try_acquire(self) -> bool:
        with self._lock:
            if self.used >= self.limit:
                self.denied += 1
                return False
            self.used += 1
            return True

    def snapshot(self) -> dict[str, int | bool]:
        with self._lock:
            return {
                "limit": self.limit,
                "used": self.used,
                "remaining": max(0, self.limit - self.used),
                "denied": self.denied,
                "exhausted": self.used >= self.limit,
            }


class ConfiguredTrendSearchClient(TrendSearchClient):
    """Search public trend signals through configured, terms-respecting APIs."""

    def __init__(
        self,
        env: dict[str, str] | None = None,
        timeout: int = 8,
        *,
        call_budget: ExternalCallBudget | None = None,
    ) -> None:
        self.env = env if env is not None else os.environ
        self.timeout = timeout
        self.call_budget = call_budget
        self._adapter_telemetry: dict[str, _AdapterTelemetry] = {}

    def available_sources(self) -> list[str]:
        sources: list[str] = []
        if self._firecrawl_mode() != "unavailable":
            sources.append("firecrawl_v2")
        if self.env.get("SEARXNG_BASE_URL"):
            sources.append("searxng")
        if self.env.get("GOOGLE_CSE_API_KEY") and self.env.get("GOOGLE_CSE_ID"):
            sources.append("google_cse")
        if self.env.get("REDDIT_BEARER_TOKEN"):
            sources.append("reddit_api")
        if self.env.get("TIKTOK_RESEARCH_CLIENT_TOKEN"):
            sources.append("tiktok_research_api")
        return sources

    def _firecrawl_mode(self) -> str:
        return firecrawl_endpoint_mode(
            self.env.get("FIRECRAWL_BASE_URL", ""),
            self.env.get("FIRECRAWL_API_KEY", ""),
            allow_unauthenticated_self_hosted=_truthy(
                self.env.get("FIRECRAWL_ALLOW_UNAUTHENTICATED_SELF_HOSTED", "")
            ),
        )

    def telemetry(self) -> list[dict[str, Any]]:
        return [
            self._adapter_telemetry.get(adapter, _AdapterTelemetry()).to_dict(adapter)
            for adapter in self.available_sources()
        ]

    def begin_request(self, call_budget: ExternalCallBudget) -> None:
        """Bind fresh per-request accounting before any adapter can run."""

        self.call_budget = call_budget
        self._adapter_telemetry = {}

    def estimated_external_calls(self, platform: str) -> int:
        sources = set(self.available_sources())
        total = len(sources & {"firecrawl_v2", "searxng", "google_cse"})
        if platform == "reddit" and "reddit_api" in sources:
            total += 1
        if platform == "tiktok" and "tiktok_research_api" in sources:
            total += 1
        return total

    def budget_telemetry(self) -> dict[str, int | bool] | None:
        return self.call_budget.snapshot() if self.call_budget is not None else None

    def search(
        self,
        query: str,
        *,
        platform: str,
        lookback_start: datetime,
        now: datetime,
        limit: int = 5,
    ) -> list[SearchResult]:
        results: list[SearchResult] = []
        if platform == "reddit" and self.env.get("REDDIT_BEARER_TOKEN"):
            self._collect(
                results,
                "reddit_api",
                lambda: self._search_reddit(query, lookback_start=lookback_start, now=now, limit=limit),
            )
        if platform == "tiktok" and self.env.get("TIKTOK_RESEARCH_CLIENT_TOKEN"):
            self._collect(
                results,
                "tiktok_research_api",
                lambda: self._search_tiktok(query, lookback_start=lookback_start, now=now, limit=limit),
            )

        web_query = platform_query(query, platform)
        if self._firecrawl_mode() != "unavailable":
            self._collect(
                results,
                "firecrawl_v2",
                lambda: self._search_firecrawl(web_query, lookback_start=lookback_start, now=now, limit=limit),
            )
        if self.env.get("GOOGLE_CSE_API_KEY") and self.env.get("GOOGLE_CSE_ID"):
            self._collect(
                results,
                "google_cse",
                lambda: self._search_google_cse(web_query, lookback_start=lookback_start, now=now, limit=limit),
            )
        if self.env.get("SEARXNG_BASE_URL"):
            self._collect(
                results,
                "searxng",
                lambda: self._search_searxng(web_query, lookback_start=lookback_start, now=now, limit=limit),
            )
        return dedupe_results(results)[:limit]

    def _collect(self, output: list[SearchResult], adapter: str, operation: Callable[[], list[SearchResult]]) -> None:
        state = self._adapter_telemetry.setdefault(adapter, _AdapterTelemetry())
        if self.call_budget is not None and not self.call_budget.try_acquire():
            state.budget_skipped += 1
            return
        try:
            found = operation()
        except (KeyError, TypeError, ValueError, OSError) as exc:
            state.add_error(f"Adapter processing failed: {type(exc).__name__}")
            return
        state.result_count += len(found)
        output.extend(found)

    def _search_firecrawl(
        self,
        query: str,
        *,
        lookback_start: datetime,
        now: datetime,
        limit: int,
    ) -> list[SearchResult]:
        base_url = self.env["FIRECRAWL_BASE_URL"].rstrip("/")
        if base_url.endswith("/v2/search"):
            url = base_url
        elif base_url.endswith("/v2"):
            url = f"{base_url}/search"
        else:
            url = f"{base_url}/v2/search"

        date_range = (
            "sbd:1,cdr:1,"
            f"cd_min:{lookback_start.astimezone(timezone.utc).strftime('%m/%d/%Y')},"
            f"cd_max:{now.astimezone(timezone.utc).strftime('%m/%d/%Y')}"
        )
        body: dict[str, Any] = {
            "query": query[:500],
            "limit": max(1, min(limit, 20)),
            "sources": ["web", "news"],
            "tbs": date_range,
            "country": self.env.get("FIRECRAWL_COUNTRY", "DE"),
            "timeout": max(1_000, self.timeout * 1_000),
            "ignoreInvalidURLs": True,
        }
        location = self.env.get("FIRECRAWL_LOCATION", "").strip()
        if location:
            body["location"] = location
        headers = {"Content-Type": "application/json"}
        api_key = self.env.get("FIRECRAWL_API_KEY", "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        payload = self._request_json(request, adapter="firecrawl_v2", require_success=True)
        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        typed_items: list[tuple[str, dict[str, Any]]] = []
        if isinstance(data, list):
            typed_items.extend(("web", item) for item in data if isinstance(item, dict))
        elif isinstance(data, dict):
            for source_kind in ("web", "news"):
                items = data.get(source_kind, [])
                if isinstance(items, list):
                    typed_items.extend((source_kind, item) for item in items if isinstance(item, dict))

        retrieved_at = now.isoformat()
        results: list[SearchResult] = []
        for source_kind, item in typed_items:
            metadata = item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {}
            result_url = str(item.get("url") or metadata.get("sourceURL") or metadata.get("url") or "")
            if not source_domain(result_url):
                continue
            published_at = normalize_published(
                _first_value(
                    item,
                    metadata,
                    keys=(
                        "date",
                        "published",
                        "publishedAt",
                        "published_at",
                        "publishedDate",
                        "publishedTime",
                        "article:published_time",
                        "og:published_time",
                    ),
                ),
                reference=now,
            )
            if published_at and not date_is_recent(published_at, lookback_start, now=now):
                continue
            snippet = str(
                item.get("description")
                or item.get("snippet")
                or metadata.get("description")
                or metadata.get("ogDescription")
                or ""
            )
            results.append(
                SearchResult(
                    source="firecrawl_v2",
                    platform=platform_from_url(result_url),
                    title=str(item.get("title") or metadata.get("title") or result_url),
                    url=result_url,
                    snippet=_clean_text(snippet, limit=500),
                    published_at=published_at,
                    retrieved_at=retrieved_at,
                    raw={
                        "source_kind": source_kind,
                        "category": item.get("category", ""),
                        "position": item.get("position"),
                        "request_id": payload.get("id", "") if isinstance(payload, dict) else "",
                    },
                )
            )
        return dedupe_results(results)[: max(1, limit)]

    def _search_google_cse(
        self,
        query: str,
        *,
        lookback_start: datetime,
        now: datetime,
        limit: int,
    ) -> list[SearchResult]:
        lookback_days = max(1, (now.date() - lookback_start.date()).days)
        params = {
            "key": self.env["GOOGLE_CSE_API_KEY"],
            "cx": self.env["GOOGLE_CSE_ID"],
            "q": query,
            "num": str(max(1, min(limit, 10))),
            "dateRestrict": f"d{lookback_days}",
            "safe": "active",
        }
        url = "https://www.googleapis.com/customsearch/v1?" + urllib.parse.urlencode(params)
        payload = self._request_json(url, adapter="google_cse")
        items = payload.get("items", []) if isinstance(payload, dict) else []
        results: list[SearchResult] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            result_url = str(item.get("link", ""))
            if not source_domain(result_url):
                continue
            published_at = normalize_published(_published_from_google_item(item), reference=now)
            if published_at and not date_is_recent(published_at, lookback_start, now=now):
                continue
            results.append(
                SearchResult(
                    source="google_cse",
                    platform=platform_from_url(result_url),
                    title=str(item.get("title", "")),
                    url=result_url,
                    snippet=str(item.get("snippet", "")),
                    published_at=published_at,
                    retrieved_at=now.isoformat(),
                    raw={"display_link": item.get("displayLink", "")},
                )
            )
        return results

    def _search_searxng(
        self,
        query: str,
        *,
        lookback_start: datetime,
        now: datetime,
        limit: int,
    ) -> list[SearchResult]:
        base_url = self.env["SEARXNG_BASE_URL"].rstrip("/")
        lookback_days = max(1, (now.date() - lookback_start.date()).days)
        time_range = "day" if lookback_days <= 1 else "week" if lookback_days <= 7 else "month"
        params = {
            "q": query,
            "format": "json",
            "language": self.env.get("TREND_RESEARCH_LANGUAGE", "de-DE"),
            "time_range": time_range,
            "safesearch": "1",
        }
        payload = self._request_json(f"{base_url}/search?" + urllib.parse.urlencode(params), adapter="searxng")
        items = payload.get("results", []) if isinstance(payload, dict) else []
        results: list[SearchResult] = []
        for item in items[: max(limit, 1)]:
            if not isinstance(item, dict):
                continue
            result_url = str(item.get("url", ""))
            if not source_domain(result_url):
                continue
            published_at = normalize_published(_published_from_searx_item(item), reference=now)
            if published_at and not date_is_recent(published_at, lookback_start, now=now):
                continue
            results.append(
                SearchResult(
                    source="searxng",
                    platform=platform_from_url(result_url),
                    title=str(item.get("title", "")),
                    url=result_url,
                    snippet=str(item.get("content", "")),
                    published_at=published_at,
                    retrieved_at=now.isoformat(),
                    raw={"engine": item.get("engine", "")},
                )
            )
        return results

    def _search_reddit(
        self,
        query: str,
        *,
        lookback_start: datetime,
        now: datetime,
        limit: int,
    ) -> list[SearchResult]:
        params = {"q": query, "sort": "new", "t": "month", "limit": str(max(1, min(limit, 25))), "raw_json": "1"}
        request = urllib.request.Request(
            "https://oauth.reddit.com/search?" + urllib.parse.urlencode(params),
            headers={
                "Authorization": f"Bearer {self.env['REDDIT_BEARER_TOKEN']}",
                "User-Agent": self.env.get("REDDIT_USER_AGENT", "wamocon-marketing-machine/0.1"),
            },
        )
        payload = self._request_json(request, adapter="reddit_api")
        children = (((payload or {}).get("data") or {}).get("children") or []) if isinstance(payload, dict) else []
        results: list[SearchResult] = []
        for child in children:
            data = child.get("data", {}) if isinstance(child, dict) else {}
            created_utc = data.get("created_utc")
            published_at = ""
            if isinstance(created_utc, (int, float)):
                published_at = datetime.fromtimestamp(created_utc, tz=timezone.utc).isoformat()
                if not date_is_recent(published_at, lookback_start, now=now):
                    continue
            permalink = str(data.get("permalink", ""))
            result_url = "https://www.reddit.com" + permalink if permalink.startswith("/") else str(data.get("url", ""))
            if not source_domain(result_url):
                continue
            results.append(
                SearchResult(
                    source="reddit_api",
                    platform="reddit",
                    title=str(data.get("title", "")),
                    url=result_url,
                    snippet=str(data.get("selftext", ""))[:500],
                    published_at=published_at,
                    retrieved_at=now.isoformat(),
                    metrics={"score": _safe_int(data.get("score")), "comments": _safe_int(data.get("num_comments"))},
                    raw={"subreddit": data.get("subreddit", "")},
                )
            )
        return results

    def _search_tiktok(
        self,
        query: str,
        *,
        lookback_start: datetime,
        now: datetime,
        limit: int,
    ) -> list[SearchResult]:
        token = self.env["TIKTOK_RESEARCH_CLIENT_TOKEN"]
        query_tokens = tokens(query, min_length=4)
        keyword = query_tokens[0] if query_tokens else query[:40]
        body = {
            "query": {
                "and": [
                    {
                        "operation": "EQ",
                        "field_name": "hashtag_name",
                        "field_values": [keyword.lstrip("#")],
                    }
                ]
            },
            "start_date": lookback_start.date().isoformat(),
            "end_date": now.date().isoformat(),
            "max_count": max(1, min(limit, 20)),
        }
        params = urllib.parse.urlencode({"fields": "id,video_description,create_time,share_count,view_count,like_count,comment_count"})
        request = urllib.request.Request(
            "https://open.tiktokapis.com/v2/research/video/query/?" + params,
            data=json.dumps(body).encode("utf-8"),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            method="POST",
        )
        payload = self._request_json(request, adapter="tiktok_research_api")
        videos = payload.get("data", {}).get("videos", []) if isinstance(payload, dict) else []
        results: list[SearchResult] = []
        for video in videos:
            if not isinstance(video, dict):
                continue
            created = video.get("create_time")
            published_at = ""
            if isinstance(created, (int, float)):
                published_at = datetime.fromtimestamp(created, tz=timezone.utc).isoformat()
                if not date_is_recent(published_at, lookback_start, now=now):
                    continue
            results.append(
                SearchResult(
                    source="tiktok_research_api",
                    platform="tiktok",
                    title=str(video.get("video_description", ""))[:120] or f"TikTok signal for #{keyword}",
                    url=f"https://www.tiktok.com/@/video/{video.get('id', '')}",
                    snippet=str(video.get("video_description", "")),
                    published_at=published_at,
                    retrieved_at=now.isoformat(),
                    metrics={
                        "views": _safe_int(video.get("view_count")),
                        "likes": _safe_int(video.get("like_count")),
                        "shares": _safe_int(video.get("share_count")),
                        "comments": _safe_int(video.get("comment_count")),
                    },
                )
            )
        return results

    def _request_json(
        self,
        url_or_request: str | urllib.request.Request,
        *,
        adapter: str,
        require_success: bool = False,
    ) -> Any:
        state = self._adapter_telemetry.setdefault(adapter, _AdapterTelemetry())
        state.attempts += 1
        try:
            with urlopen(url_or_request, timeout=self.timeout) as response:
                body = read_limited(
                    response,
                    max_bytes=DEFAULT_JSON_RESPONSE_LIMIT,
                    label=f"{adapter} response",
                )
                payload = json.loads(body.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            state.add_error(f"HTTP {exc.code}: {exc.reason or 'request failed'}")
            return {}
        except urllib.error.URLError as exc:
            state.add_error(f"Network error: {self._safe_error(exc.reason)}")
            return {}
        except TimeoutError:
            state.add_error("Request timed out")
            return {}
        except (json.JSONDecodeError, UnicodeDecodeError):
            state.add_error("Adapter returned invalid JSON")
            return {}
        except ValueError:
            state.add_error("Adapter response exceeded the safe size limit")
            return {}
        except OSError as exc:
            state.add_error(f"Transport error: {type(exc).__name__}")
            return {}

        if require_success and (not isinstance(payload, dict) or payload.get("success") is not True):
            error = payload.get("error", "API reported failure") if isinstance(payload, dict) else "Malformed API response"
            state.add_error(f"API error: {self._safe_error(error)}")
            return {}
        state.successful_requests += 1
        return payload

    def _safe_error(self, value: Any) -> str:
        message = _clean_text(str(value), limit=180) or type(value).__name__
        for key, secret in self.env.items():
            if secret and any(marker in key.upper() for marker in ("KEY", "TOKEN", "SECRET", "PASSWORD")):
                message = message.replace(secret, "[redacted]")
        message = re.sub(r"(?i)bearer\s+[a-z0-9._~+/=-]+", "Bearer [redacted]", message)
        return message


def source_domain(url: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(url.strip())
        hostname = (parsed.hostname or "").lower().strip(".")
        # Access-controlled or ambiguous URLs cannot serve as public evidence.
        if "@" in parsed.netloc or parsed.username or parsed.password:
            return ""
        # Force validation of malformed ports such as :not-a-number.
        _ = parsed.port
    except ValueError:
        return ""
    if parsed.scheme.lower() not in {"http", "https"}:
        return ""
    if hostname.startswith("www."):
        hostname = hostname[4:]
    if not hostname:
        return ""
    try:
        address = ipaddress.ip_address(hostname)
        return hostname if address.is_global else ""
    except ValueError:
        pass
    if hostname == "localhost" or hostname.endswith(
        (
            ".localhost",
            ".local",
            ".localdomain",
            ".internal",
            ".intranet",
            ".private",
            ".lan",
            ".home",
            ".home.arpa",
            ".corp",
        )
    ):
        return ""
    if hostname.endswith((".example", ".invalid", ".test", ".onion")):
        return ""
    labels = hostname.split(".")
    # Single-label Docker/service names (for example core-n8n or intranet) are
    # routable inside a private network but are not registrable public sources.
    if len(labels) < 2:
        return ""
    try:
        ascii_labels = [label.encode("idna").decode("ascii") for label in labels]
    except UnicodeError:
        return ""
    if any(
        not label
        or len(label) > 63
        or label.startswith("-")
        or label.endswith("-")
        or not re.fullmatch(r"[a-z0-9-]+", label)
        for label in ascii_labels
    ):
        return ""
    if len(ascii_labels[-1]) < 2:
        return ""
    labels = ascii_labels
    if len(labels) <= 2:
        return ".".join(labels)
    common_two_part_suffixes = {
        "co.uk",
        "org.uk",
        "ac.uk",
        "com.au",
        "net.au",
        "org.au",
        "co.nz",
        "co.jp",
        "co.in",
        "com.br",
        "com.cn",
        "com.mx",
        "co.za",
        "com.tr",
    }
    suffix = ".".join(labels[-2:])
    return ".".join(labels[-3:]) if suffix in common_two_part_suffixes and len(labels) >= 3 else suffix


def firecrawl_endpoint_mode(
    base_url: str,
    api_key: str,
    *,
    allow_unauthenticated_self_hosted: bool = False,
) -> str:
    """Return the only safe authentication mode for a Firecrawl endpoint.

    Firecrawl Cloud needs an API key. Credentialless self-hosting is accepted
    only with explicit operator opt-in and an unambiguously local/private host.
    This prevents an environment typo from sending research queries to a
    public unauthenticated service.
    """

    try:
        parsed = urllib.parse.urlsplit(base_url.strip())
        hostname = (parsed.hostname or "").strip().casefold().rstrip(".")
        _ = parsed.port
    except ValueError:
        return "unavailable"
    if parsed.scheme not in {"http", "https"} or not hostname or parsed.username or parsed.password:
        return "unavailable"
    if api_key.strip():
        return "api_key"
    if not allow_unauthenticated_self_hosted:
        return "unavailable"
    try:
        address = ipaddress.ip_address(hostname)
        private_endpoint = address.is_private or address.is_loopback or address.is_link_local
    except ValueError:
        private_endpoint = (
            hostname == "localhost"
            or "." not in hostname
            or hostname.endswith(
                (
                    ".localhost",
                    ".local",
                    ".internal",
                    ".intranet",
                    ".private",
                    ".lan",
                    ".home",
                    ".home.arpa",
                    ".docker",
                )
            )
        )
    return "private_self_hosted_no_auth" if private_endpoint else "unavailable"


def _truthy(value: str) -> bool:
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def normalize_published(value: Any, *, reference: datetime | None = None) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
        except (OSError, OverflowError, ValueError):
            return ""
    raw = _clean_text(str(value), limit=120)
    if not raw:
        return ""
    parsed = parse_datetime(raw)
    if parsed:
        return parsed.astimezone(timezone.utc).isoformat()

    now = (reference or datetime.now(timezone.utc)).astimezone(timezone.utc)
    lowered = raw.lower()
    if lowered in {"today", "heute"}:
        return now.isoformat()
    if lowered in {"yesterday", "gestern"}:
        return (now - timedelta(days=1)).isoformat()
    relative = re.search(
        r"(?:vor\s+)?(\d+)\s*(minute|minuten|min|hour|hours|stunde|stunden|day|days|tag|tage|tagen|week|weeks|woche|wochen|month|months|monat|monate|monaten)(?:\s+ago)?",
        lowered,
    )
    if not relative:
        return ""
    amount = int(relative.group(1))
    unit = relative.group(2)
    if unit.startswith(("minute", "min")):
        delta = timedelta(minutes=amount)
    elif unit.startswith(("hour", "stunde")):
        delta = timedelta(hours=amount)
    elif unit.startswith(("day", "tag")):
        delta = timedelta(days=amount)
    elif unit.startswith(("week", "woche")):
        delta = timedelta(weeks=amount)
    else:
        delta = timedelta(days=30 * amount)
    return (now - delta).isoformat()


def parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    cleaned = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(cleaned)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    try:
        parsed = parsedate_to_datetime(cleaned)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError, OverflowError):
        pass
    for pattern in ("%d.%m.%Y", "%d/%m/%Y", "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(cleaned, pattern).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _published_from_searx_item(item: dict[str, Any]) -> str:
    """Return only adapter/page metadata, never date-looking result text.

    Search snippets and titles are publisher-controlled prose. A relative
    phrase such as ``vor 2 Tagen`` there may describe a different event and
    cannot prove when the page itself was published.
    """

    metadata = item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {}
    value = _first_value(
        item,
        metadata,
        keys=(
            "publishedDate",
            "pubdate",
            "published_at",
            "publishedAt",
            "datePublished",
            "date",
            "article:published_time",
            "og:published_time",
        ),
    )
    return str(value) if value not in (None, "") else ""


def date_is_recent(value: str, lookback_start: datetime, *, now: datetime | None = None) -> bool:
    parsed = parse_datetime(value)
    if not parsed:
        return False
    lower = lookback_start if lookback_start.tzinfo else lookback_start.replace(tzinfo=timezone.utc)
    upper = now or datetime.now(timezone.utc)
    upper = upper if upper.tzinfo else upper.replace(tzinfo=timezone.utc)
    return lower.astimezone(timezone.utc) <= parsed.astimezone(timezone.utc) <= upper.astimezone(timezone.utc) + timedelta(minutes=5)


def platform_from_url(url: str) -> str:
    domain = source_domain(url)
    if domain.endswith("instagram.com"):
        return "instagram"
    if domain.endswith("tiktok.com"):
        return "tiktok"
    if domain.endswith("reddit.com"):
        return "reddit"
    if domain.endswith("youtube.com") or domain == "youtu.be":
        return "youtube"
    return "web"


def platform_query(query: str, platform: str) -> str:
    if platform == "instagram":
        return f"{query} site:instagram.com/reel OR site:instagram.com/p"
    if platform == "tiktok":
        return f"{query} site:tiktok.com"
    if platform == "reddit":
        return f"{query} site:reddit.com"
    if platform == "forums":
        return f"{query} forum OR community OR discussion"
    return query


def dedupe_results(results: list[SearchResult]) -> list[SearchResult]:
    seen: set[str] = set()
    deduped: list[SearchResult] = []
    for result in results:
        if result.source != "campaign_brief" and not source_domain(result.url):
            continue
        normalized_url = _normalized_url(result.url)
        key = normalized_url or _clean_text(result.title).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(result)
    return deduped


def tokens(text: str, *, min_length: int = 3) -> list[str]:
    return [item.lower() for item in re.findall(r"[^\W_][\w-]*", text or "", flags=re.UNICODE) if len(item) >= min_length]


def _normalized_url(url: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(url.strip())
        hostname = (parsed.hostname or "").lower()
        port = f":{parsed.port}" if parsed.port else ""
    except ValueError:
        return ""
    if parsed.scheme.lower() not in {"http", "https"}:
        return url.strip()
    query_pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    filtered_query = urllib.parse.urlencode(
        [(key, value) for key, value in query_pairs if not key.lower().startswith("utm_")]
    )
    path = parsed.path.rstrip("/") or "/"
    return urllib.parse.urlunsplit((parsed.scheme.lower(), hostname + port, path, filtered_query, ""))


def _published_from_google_item(item: dict[str, Any]) -> str:
    pagemap = item.get("pagemap", {}) if isinstance(item.get("pagemap"), dict) else {}
    for records in pagemap.values():
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, dict):
                continue
            for key in ("article:published_time", "og:published_time", "datepublished"):
                value = record.get(key)
                if value:
                    return str(value)
    return ""


def _first_value(*mappings: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        for mapping in mappings:
            value = mapping.get(key)
            if value not in (None, ""):
                return value
    return ""


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError, OverflowError):
        return 0


def _clean_text(value: str, *, limit: int = 500) -> str:
    return re.sub(r"\s+", " ", value or "").strip()[:limit]
