from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .governance import GovernancePolicy, PolicyAction
from .schemas import ContentBrief


DEFAULT_PLATFORMS = ["instagram", "tiktok", "reddit", "forums", "web"]
GENERIC_PROMPT_WORDS = {
    "make",
    "more",
    "less",
    "like",
    "style",
    "format",
    "hook",
    "hooks",
    "video",
    "reel",
    "reels",
    "short",
    "shorts",
    "caption",
    "captions",
    "script",
    "voiceover",
    "animation",
    "animated",
    "creative",
    "funny",
    "serious",
    "professional",
    "german",
    "english",
    "deutsch",
    "question",
    "answer",
    "interview",
    "teardown",
    "myth",
    "fact",
    "pov",
    "explain",
    "explainer",
    "better",
    "different",
    "another",
    "faster",
    "slower",
    "clearer",
    "bolder",
    "trend",
    "topic",
    "campaign",
    "audience",
    "intro",
    "outro",
    "cta",
}


@dataclass(frozen=True)
class SearchResult:
    source: str
    platform: str
    title: str
    url: str
    snippet: str = ""
    published_at: str = ""
    metrics: dict[str, int] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


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


class ConfiguredTrendSearchClient(TrendSearchClient):
    """Search public trend signals through configured, terms-respecting sources."""

    def __init__(self, env: dict[str, str] | None = None, timeout: int = 8) -> None:
        self.env = env or os.environ
        self.timeout = timeout

    def available_sources(self) -> list[str]:
        sources: list[str] = []
        if self.env.get("SEARXNG_BASE_URL"):
            sources.append("searxng")
        if self.env.get("GOOGLE_CSE_API_KEY") and self.env.get("GOOGLE_CSE_ID"):
            sources.append("google_cse")
        if self.env.get("REDDIT_BEARER_TOKEN"):
            sources.append("reddit_api")
        if self.env.get("TIKTOK_RESEARCH_CLIENT_TOKEN"):
            sources.append("tiktok_research_api")
        return sources

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
            results.extend(self._search_reddit(query, lookback_start=lookback_start, limit=limit))
        if platform == "tiktok" and self.env.get("TIKTOK_RESEARCH_CLIENT_TOKEN"):
            results.extend(self._search_tiktok(query, lookback_start=lookback_start, now=now, limit=limit))

        web_query = _platform_query(query, platform)
        if self.env.get("GOOGLE_CSE_API_KEY") and self.env.get("GOOGLE_CSE_ID"):
            results.extend(self._search_google_cse(web_query, lookback_start=lookback_start, limit=limit))
        if self.env.get("SEARXNG_BASE_URL"):
            results.extend(self._search_searxng(web_query, limit=limit))
        return _dedupe_results(results)[:limit]

    def _search_google_cse(self, query: str, *, lookback_start: datetime, limit: int) -> list[SearchResult]:
        params = {
            "key": self.env["GOOGLE_CSE_API_KEY"],
            "cx": self.env["GOOGLE_CSE_ID"],
            "q": query,
            "num": str(max(1, min(limit, 10))),
            "dateRestrict": "d10",
            "safe": "active",
        }
        url = "https://www.googleapis.com/customsearch/v1?" + urllib.parse.urlencode(params)
        payload = self._request_json(url)
        items = payload.get("items", []) if isinstance(payload, dict) else []
        results: list[SearchResult] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            published_at = _published_from_google_item(item)
            if published_at and not _date_is_recent(published_at, lookback_start):
                continue
            results.append(
                SearchResult(
                    source="google_cse",
                    platform=_platform_from_url(item.get("link", "")),
                    title=str(item.get("title", "")),
                    url=str(item.get("link", "")),
                    snippet=str(item.get("snippet", "")),
                    published_at=published_at,
                    raw={"display_link": item.get("displayLink", "")},
                )
            )
        return results

    def _search_searxng(self, query: str, *, limit: int) -> list[SearchResult]:
        base_url = self.env["SEARXNG_BASE_URL"].rstrip("/")
        params = {
            "q": query,
            "format": "json",
            "language": self.env.get("TREND_RESEARCH_LANGUAGE", "de-DE"),
            "time_range": "month",
            "safesearch": "1",
        }
        payload = self._request_json(f"{base_url}/search?" + urllib.parse.urlencode(params))
        items = payload.get("results", []) if isinstance(payload, dict) else []
        results: list[SearchResult] = []
        for item in items[: max(limit, 1)]:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url", ""))
            results.append(
                SearchResult(
                    source="searxng",
                    platform=_platform_from_url(url),
                    title=str(item.get("title", "")),
                    url=url,
                    snippet=str(item.get("content", "")),
                    published_at=str(item.get("publishedDate", "") or ""),
                    raw={"engine": item.get("engine", "")},
                )
            )
        return results

    def _search_reddit(self, query: str, *, lookback_start: datetime, limit: int) -> list[SearchResult]:
        params = {"q": query, "sort": "new", "t": "week", "limit": str(max(1, min(limit, 25))), "raw_json": "1"}
        request = urllib.request.Request(
            "https://oauth.reddit.com/search?" + urllib.parse.urlencode(params),
            headers={
                "Authorization": f"Bearer {self.env['REDDIT_BEARER_TOKEN']}",
                "User-Agent": self.env.get("REDDIT_USER_AGENT", "wamocon-marketing-machine/0.1"),
            },
        )
        payload = self._request_json(request)
        children = (((payload or {}).get("data") or {}).get("children") or []) if isinstance(payload, dict) else []
        results: list[SearchResult] = []
        for child in children:
            data = child.get("data", {}) if isinstance(child, dict) else {}
            created_utc = data.get("created_utc")
            published_at = ""
            if isinstance(created_utc, (int, float)):
                published_at = datetime.fromtimestamp(created_utc, tz=timezone.utc).isoformat()
                if not _date_is_recent(published_at, lookback_start):
                    continue
            permalink = str(data.get("permalink", ""))
            url = "https://www.reddit.com" + permalink if permalink.startswith("/") else str(data.get("url", ""))
            results.append(
                SearchResult(
                    source="reddit_api",
                    platform="reddit",
                    title=str(data.get("title", "")),
                    url=url,
                    snippet=str(data.get("selftext", ""))[:500],
                    published_at=published_at,
                    metrics={"score": int(data.get("score", 0) or 0), "comments": int(data.get("num_comments", 0) or 0)},
                    raw={"subreddit": data.get("subreddit", "")},
                )
            )
        return results

    def _search_tiktok(self, query: str, *, lookback_start: datetime, now: datetime, limit: int) -> list[SearchResult]:
        token = self.env["TIKTOK_RESEARCH_CLIENT_TOKEN"]
        keyword = _tokens(query, min_length=4)[0] if _tokens(query, min_length=4) else query[:40]
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
        payload = self._request_json(request)
        videos = payload.get("data", {}).get("videos", []) if isinstance(payload, dict) else []
        results: list[SearchResult] = []
        for video in videos:
            if not isinstance(video, dict):
                continue
            created = video.get("create_time")
            published_at = ""
            if isinstance(created, (int, float)):
                published_at = datetime.fromtimestamp(created, tz=timezone.utc).isoformat()
            results.append(
                SearchResult(
                    source="tiktok_research_api",
                    platform="tiktok",
                    title=str(video.get("video_description", ""))[:120] or f"TikTok signal for #{keyword}",
                    url=f"https://www.tiktok.com/@/video/{video.get('id', '')}",
                    snippet=str(video.get("video_description", "")),
                    published_at=published_at,
                    metrics={
                        "views": int(video.get("view_count", 0) or 0),
                        "likes": int(video.get("like_count", 0) or 0),
                        "shares": int(video.get("share_count", 0) or 0),
                        "comments": int(video.get("comment_count", 0) or 0),
                    },
                )
            )
        return results

    def _request_json(self, url_or_request: str | urllib.request.Request) -> Any:
        try:
            with urllib.request.urlopen(url_or_request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
            return {}


def load_campaigns(root: Path) -> list[dict[str, Any]]:
    campaigns: list[dict[str, Any]] = []
    for path in sorted((root / "Kampagnen").glob("kampagne_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        campaign = data.get("campaign", {})
        if not isinstance(campaign, dict):
            continue
        evidence_ref = path.relative_to(root).as_posix()
        campaigns.append(
            {
                "id": path.stem,
                "name": str(campaign.get("name", path.stem)),
                "description": str(campaign.get("description", "")),
                "master_prompt": str(campaign.get("masterPrompt", "")),
                "keywords": [str(item) for item in campaign.get("campaignKeywords", [])],
                "channels": [str(item) for item in campaign.get("channels", [])],
                "evidence_ref": evidence_ref,
                "start_date": str(campaign.get("startDate", "")),
                "end_date": str(campaign.get("endDate", "")),
            }
        )
    return campaigns


def run_trend_research(
    root: Path,
    *,
    payload: dict[str, Any] | None = None,
    policy: GovernancePolicy | None = None,
    search_client: TrendSearchClient | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    payload = payload or {}
    now = now or datetime.now(timezone.utc)
    lookback_days = _int_between(payload.get("lookback_days", 10), minimum=1, maximum=30)
    limit_per_campaign = _int_between(payload.get("limit_per_campaign", 4), minimum=1, maximum=8)
    requested_platforms = payload.get("platforms") or DEFAULT_PLATFORMS
    platforms = [item for item in requested_platforms if item in DEFAULT_PLATFORMS] or DEFAULT_PLATFORMS
    selected_campaign_ids = set(payload.get("campaign_ids") or [])
    lookback_start = now - timedelta(days=lookback_days)

    if policy is not None:
        decision = policy.check_tool("search_public_sources")
        if decision.action == PolicyAction.DENY:
            raise ValueError(decision.reason)

    client = search_client or ConfiguredTrendSearchClient()
    campaigns = load_campaigns(root)
    if selected_campaign_ids:
        campaigns = [campaign for campaign in campaigns if campaign["id"] in selected_campaign_ids]

    run_id = f"trend-{now.strftime('%Y%m%d%H%M%S')}-{_stable_id(json.dumps(payload, sort_keys=True), length=6)}"
    campaign_results: list[dict[str, Any]] = []
    for campaign in campaigns:
        signals = _search_campaign_signals(
            campaign,
            platforms=platforms,
            lookback_start=lookback_start,
            now=now,
            client=client,
        )
        campaign_results.append(
            {
                "campaign": campaign,
                "trends": _build_campaign_trends(
                    campaign,
                    signals=signals,
                    run_id=run_id,
                    lookback_start=lookback_start,
                    now=now,
                    limit=limit_per_campaign,
                ),
                "raw_signal_count": len(signals),
            }
        )

    status = "verified_sources" if any(_external_evidence_count(trend) >= 2 for result in campaign_results for trend in result["trends"]) else "needs_live_sources"
    return {
        "id": run_id,
        "status": status,
        "run_started_at": now.isoformat(),
        "lookback_days": lookback_days,
        "lookback_start": lookback_start.isoformat(),
        "platforms": platforms,
        "source_adapters": client.available_sources(),
        "campaigns": campaign_results,
        "guardrails": [
            "Use public/search APIs only; do not bypass platform terms or private login walls.",
            "Treat platform/web results as trend signals, not publishable claims.",
            "Every approved reel still requires human fact, privacy, brand, and AI-disclosure checks.",
        ],
    }


def generate_reel_concepts(
    trend_run: dict[str, Any],
    *,
    campaign_id: str,
    trend_id: str,
    user_prompt: str = "",
    variant_count: int = 4,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    campaign_result = _find_campaign_result(trend_run, campaign_id)
    trend = _find_trend(campaign_result, trend_id)
    campaign = campaign_result["campaign"]
    prompt_errors = validate_user_prompt(user_prompt, campaign, trend)
    if prompt_errors:
        raise ValueError("; ".join(prompt_errors))

    count = _int_between(variant_count, minimum=1, maximum=6)
    formats = _format_suggestions(campaign, trend)
    variants: list[dict[str, Any]] = []
    for index, format_name in enumerate(formats[:count]):
        variants.append(_reel_variant(campaign, trend, format_name, index=index, user_prompt=user_prompt))

    bundle_id = f"concept-{_stable_id(trend_run['id'] + campaign_id + trend_id + user_prompt + now.isoformat(), length=12)}"
    for index, variant in enumerate(variants):
        variant["id"] = f"{bundle_id}-v{index + 1}"

    return {
        "id": bundle_id,
        "status": "draft",
        "run_id": trend_run["id"],
        "campaign_id": campaign_id,
        "trend_id": trend_id,
        "created_at": now.isoformat(),
        "user_prompt": user_prompt.strip(),
        "campaign": campaign,
        "trend": trend,
        "variants": variants,
        "guardrails": [
            "Topic-locked regeneration only.",
            "No invented numbers, client names, employee stories, or ROI promises.",
            "Approved concept becomes a draft brief and still stops at human review.",
        ],
    }


def concept_to_content_brief(concept_bundle: dict[str, Any], *, variant_id: str | None = None) -> ContentBrief:
    campaign = concept_bundle["campaign"]
    trend = concept_bundle["trend"]
    variants = concept_bundle.get("variants", [])
    variant = _select_variant(variants, variant_id)
    content_id = f"reel-{variant['id']}"
    campaign_name = campaign["name"]
    cta = _cta_for_campaign(campaign_name)
    return ContentBrief(
        id=content_id,
        campaign=campaign_name,
        persona=_persona_for_campaign(campaign_name),
        channel="Instagram",
        format="reel",
        objective=f"Ein trendnahes, kampagnenkonformes Instagram Reel fuer {campaign_name} erstellen.",
        cta=cta,
        proof_sources=[campaign["evidence_ref"]],
        utm={
            "utm_source": "instagram",
            "utm_medium": "organic_reel",
            "utm_campaign": _slug(campaign_name),
        },
        hypothesis=f"Ein trendnahes Reel zu {trend['topic']} erzeugt mehr relevante Saves, Profilbesuche und Anfragen.",
        test_variable="trend_reel_format",
        language="de-DE",
        hashtags=variant.get("hashtags", [])[:5],
        trend_id=trend["id"],
        trend_summary=trend["topic"],
        trend_sources=trend.get("source_urls", []),
        reel_concept=variant,
        user_prompt=concept_bundle.get("user_prompt", ""),
    )


def validate_user_prompt(user_prompt: str, campaign: dict[str, Any], trend: dict[str, Any]) -> list[str]:
    prompt = user_prompt.strip()
    if not prompt:
        return []
    blocked_patterns = [
        r"(?i)\b(guaranteed|garantiert)\b.*\b(roi|results|umsatz|conversion)\b",
        r"(?i)\b(api[_-]?key|secret|password|token)\b",
        r"(?i)\b(customer|kunde|employee|mitarbeiter|bewerber)\b.*\b(without consent|ohne einwilligung)\b",
        r"(?i)\b(politics|election|crypto|casino|betting|adult|weapon|medical cure)\b",
    ]
    for pattern in blocked_patterns:
        if re.search(pattern, prompt):
            return ["prompt violates campaign/content guardrails"]

    prompt_words = [word for word in _tokens(prompt, min_length=4) if word not in GENERIC_PROMPT_WORDS]
    if len(prompt_words) < 4:
        return []

    allowed_text = " ".join(
        [
            campaign.get("name", ""),
            campaign.get("description", ""),
            " ".join(campaign.get("keywords", [])),
            trend.get("topic", ""),
            trend.get("angle", ""),
            " ".join(trend.get("reel_hooks", [])),
            " ".join(trend.get("format_suggestions", [])),
        ]
    )
    allowed_words = set(_tokens(allowed_text, min_length=4)) | GENERIC_PROMPT_WORDS
    overlap = [word for word in prompt_words if word in allowed_words]
    if len(overlap) < 1 and len(prompt_words) >= 4:
        return ["prompt must stay related to the selected campaign and trend"]
    off_topic_ratio = 1 - (len(overlap) / max(len(prompt_words), 1))
    if off_topic_ratio > 0.85 and len(prompt_words) >= 8:
        return ["prompt is mostly outside the selected campaign topic"]
    return []


def _search_campaign_signals(
    campaign: dict[str, Any],
    *,
    platforms: list[str],
    lookback_start: datetime,
    now: datetime,
    client: TrendSearchClient,
) -> list[SearchResult]:
    results: list[SearchResult] = []
    for platform in platforms:
        query = _query_for_campaign(campaign, platform=platform)
        results.extend(client.search(query, platform=platform, lookback_start=lookback_start, now=now, limit=5))
    if not results:
        return [
            SearchResult(
                source="campaign_brief",
                platform="internal",
                title=f"Campaign-only signal: {campaign['name']}",
                url=campaign["evidence_ref"],
                snippet="No configured live trend source returned results. Configure SearxNG, Google CSE, Reddit, or TikTok Research API for verified live trend discovery.",
                published_at=now.isoformat(),
            )
        ]
    return _dedupe_results(results)


def _build_campaign_trends(
    campaign: dict[str, Any],
    *,
    signals: list[SearchResult],
    run_id: str,
    lookback_start: datetime,
    now: datetime,
    limit: int,
) -> list[dict[str, Any]]:
    keyword_groups = _keyword_groups(campaign, signals)
    trends: list[dict[str, Any]] = []
    for theme, evidence in keyword_groups[:limit]:
        external = [item for item in evidence if item.source != "campaign_brief"]
        dated_recent = [item for item in external if item.published_at and _date_is_recent(item.published_at, lookback_start)]
        source_urls = [item.url for item in evidence if item.url]
        verification_status = "verified_recent" if len(external) >= 2 and dated_recent else "source_verified_date_unconfirmed"
        if len(external) == 1:
            verification_status = "single_source_review"
        if not external:
            verification_status = "requires_live_sources"
        topic = _topic_for_theme(campaign, theme, evidence)
        trend_id = f"{campaign['id']}-{_stable_id(run_id + topic, length=10)}"
        trends.append(
            {
                "id": trend_id,
                "topic": topic,
                "campaign_fit": _campaign_fit(campaign, topic),
                "angle": _angle_for_campaign(campaign, theme),
                "platforms": sorted({item.platform for item in evidence}),
                "source_urls": source_urls[:8],
                "evidence": [item.to_dict() for item in evidence[:8]],
                "verification": {
                    "status": verification_status,
                    "evidence_count": len(external),
                    "dated_recent_count": len(dated_recent),
                    "lookback_start": lookback_start.isoformat(),
                    "last_checked_at": now.isoformat(),
                    "note": _verification_note(verification_status),
                },
                "score": _trend_score(campaign, topic, evidence, lookback_start=lookback_start),
                "reel_hooks": _hooks_for_campaign(campaign, theme),
                "format_suggestions": _format_suggestions(campaign, {"topic": topic}),
                "creative_notes": _creative_notes(campaign, theme),
                "hashtags": _hashtags(campaign, theme),
            }
        )
    return sorted(trends, key=lambda item: item["score"], reverse=True)


def _keyword_groups(campaign: dict[str, Any], signals: list[SearchResult]) -> list[tuple[str, list[SearchResult]]]:
    keywords = campaign.get("keywords", [])[:6] or [campaign["name"]]
    groups: list[tuple[str, list[SearchResult]]] = []
    for keyword in keywords:
        key_tokens = set(_tokens(keyword, min_length=3))
        matching = []
        for signal in signals:
            haystack = f"{signal.title} {signal.snippet}".lower()
            if any(token in haystack for token in key_tokens):
                matching.append(signal)
        if matching:
            groups.append((keyword, matching))
    if groups:
        return groups
    return [(campaign.get("keywords", [campaign["name"]])[0], signals)]


def _query_for_campaign(campaign: dict[str, Any], *, platform: str) -> str:
    keywords = " ".join(campaign.get("keywords", [])[:3])
    name = campaign["name"]
    if platform == "instagram":
        return f'"{keywords or name}" Instagram Reels trend short video'
    if platform == "tiktok":
        return f'"{keywords or name}" TikTok trend short video'
    if platform == "reddit":
        return f'"{keywords or name}" reddit discussion'
    if platform == "forums":
        return f'"{keywords or name}" forum discussion latest'
    return f'"{keywords or name}" latest trend B2B marketing short video'


def _platform_query(query: str, platform: str) -> str:
    if platform == "instagram":
        return f"{query} site:instagram.com/reel OR site:instagram.com/p"
    if platform == "tiktok":
        return f"{query} site:tiktok.com"
    if platform == "reddit":
        return f"{query} site:reddit.com"
    if platform == "forums":
        return f"{query} forum OR community OR discussion"
    return query


def _topic_for_theme(campaign: dict[str, Any], theme: str, evidence: list[SearchResult]) -> str:
    strongest = evidence[0].title if evidence else theme
    clean_title = re.sub(r"\s+", " ", strongest).strip(" -|")
    if len(clean_title) > 90:
        clean_title = clean_title[:87].rstrip() + "..."
    return f"{theme}: {clean_title}" if theme.lower() not in clean_title.lower() else clean_title


def _angle_for_campaign(campaign: dict[str, Any], theme: str) -> str:
    name = campaign["name"].lower()
    if "qa" in name or "test" in name or "qualit" in name:
        return f"{theme} als sichtbaren Risiko-Check mit einem konkreten Pruefschritt zeigen."
    if "ki" in name or "sokrates" in name:
        return f"{theme} mit privater, datensouveraener KI-Nutzung ohne Hype verbinden."
    if "azubi" in name or "lfa" in name:
        return f"{theme} als echten Ausbildungs- oder Lernsystem-Moment zeigen."
    if "mitarbeiter" in name:
        return f"{theme} nutzen, um Teamvertrauen und Recruiting-Naehe sichtbar zu machen."
    if "app" in name:
        return f"{theme} als Umsetzungsbeweis zeigen: Problem, Bauentscheidung, Ergebnis."
    return f"{theme} in einen kampagnen passenden Short-Form-Insight uebersetzen."


def _campaign_fit(campaign: dict[str, Any], topic: str) -> str:
    tokens = set(_tokens(topic, min_length=4))
    keyword_tokens = set(_tokens(" ".join(campaign.get("keywords", [])), min_length=4))
    overlap = sorted(tokens & keyword_tokens)
    if overlap:
        return f"Matches campaign keywords: {', '.join(overlap[:5])}."
    return "Weak lexical match; keep as inspiration until a human confirms relevance."


def _hooks_for_campaign(campaign: dict[str, Any], theme: str) -> list[str]:
    name = campaign["name"].lower()
    if "qa" in name or "test" in name:
        return [
            f"Dein QA-Dashboard kann gruen aussehen, waehrend {theme} schon Zeit kostet.",
            f"Eine Frage, bevor ich einem {theme}-Prozess vertraue:",
            "Wenn das im Sprint passiert, ist es kein reines Testerproblem mehr.",
        ]
    if "ki" in name or "sokrates" in name:
        return [
            f"Bevor du das naechste KI-Tool einfuehrst: Wohin gehen bei {theme} die Daten?",
            "Die KI-Frage im Mittelstand ist nicht nur Tempo. Es ist Kontrolle.",
            "Diesen Private-KI-Check ueberspringen viele Unternehmen.",
        ]
    if "azubi" in name or "lfa" in name:
        return [
            f"POV: Deine erste IT-Ausbildungswoche hat bei {theme} endlich Struktur.",
            "Was Azubis wirklich brauchen, ist kein weiterer PDF-Ordner.",
            "20 Sekunden: So sollte modernes FIAE-Lernen aussehen.",
        ]
    if "mitarbeiter" in name:
        return [
            f"So pruefst du ein Consulting-Team: Schau, wie es ueber {theme} spricht.",
            "Keine polierte Employer-Branding-Behauptung. Ein echter Team-Moment.",
            "Frag das im Interview, wenn du die Kultur wirklich verstehen willst.",
        ]
    return [
        f"Viele App-Projekte scheitern nicht am Code. Sie scheitern, wenn {theme} unklar bleibt.",
        "So wird aus einem chaotischen internen Prozess ein nutzbarer App-Screen.",
        "Build or buy ist nicht die erste Frage. Frag zuerst das hier.",
    ]


def _format_suggestions(campaign: dict[str, Any], trend: dict[str, Any]) -> list[str]:
    name = campaign["name"].lower()
    base = [
        "Q&A-Einwandbehandlung",
        "Mythos vs Fakt mit Kinetic Captions",
        "Screenrecording-Analyse",
        "3-Schritte-Checkliste",
        "POV aus dem Alltag",
        "Kommentarantwort-Erklaervideo",
    ]
    if "azubi" in name or "mitarbeiter" in name:
        return ["POV aus dem Alltag", "Street-Style-Q&A", "Kommentarantwort-Erklaervideo", "Vorher-nachher-Routine", "3-Schritte-Checkliste"]
    if "app" in name:
        return ["Screenrecording-Analyse", "Vorher-nachher-Workflow", "Build-Decision-Breakdown", "Q&A-Einwandbehandlung", "Mythos vs Fakt mit Kinetic Captions"]
    return base


def _creative_notes(campaign: dict[str, Any], theme: str) -> list[str]:
    return [
        "Mit einem 1,5-Sekunden-Pattern-Interrupt und grossen Captions starten.",
        "Jeden Beat unter 4 Sekunden halten; Jump Cuts oder UI-Zooms zwischen Beats nutzen.",
        "Untertitel, Quellen-/Proof-Karten und eine klare CTA-Endkarte nutzen.",
        f"{theme} nicht ueberhoehen; als aktuelles Signal zur Pruefung rahmen.",
    ]


def _reel_variant(campaign: dict[str, Any], trend: dict[str, Any], format_name: str, *, index: int, user_prompt: str) -> dict[str, Any]:
    hook = (trend.get("reel_hooks") or _hooks_for_campaign(campaign, trend.get("topic", "")))[index % 3]
    cta = _cta_for_campaign(campaign["name"])
    beats = _beats_for_format(format_name, campaign, trend)
    shot_list = _shot_list_for_format(format_name, campaign)
    caption = _caption_for_variant(campaign, trend, hook, cta, user_prompt)
    return {
        "format": format_name,
        "hook": hook,
        "beats": beats,
        "shot_list": shot_list,
        "animation_notes": _animation_for_format(format_name),
        "caption": caption,
        "cta": cta,
        "creator_direction": user_prompt.strip(),
        "hashtags": trend.get("hashtags", [])[:5],
        "evidence_to_verify": trend.get("source_urls", [])[:5],
        "guardrails": [
            "No customer, applicant, or employee identity without consent.",
            "No guaranteed ROI, security, compliance, or outcome claim.",
            "Use trend source links as internal review material only.",
        ],
    }


def _beats_for_format(format_name: str, campaign: dict[str, Any], trend: dict[str, Any]) -> list[str]:
    topic = trend.get("topic", "the trend")
    angle = trend.get("angle", "")
    if "Q&A" in format_name or "Street" in format_name:
        return [
            f"Frage auf dem Screen: 'Warum ist {topic} gerade relevant?'",
            f"Antwort in einem Satz: {angle}",
            "Einen Proof- oder Prozess-Ausschnitt ohne private Daten zeigen.",
            f"Mit CTA schliessen: {_cta_for_campaign(campaign['name'])}.",
        ]
    if "Myth" in format_name:
        return [
            f"Mythos: '{topic} ist nur ein weiterer Content-Trend.'",
            "Fakt: Wichtig ist der Pain Point hinter dem Signal.",
            f"Auf den WAMOCON-Kampagnenwinkel uebersetzen: {angle}",
            "Zum Speichern auffordern, wenn die Zuschauer eine praktische Checkliste brauchen.",
        ]
    if "Screen" in format_name or "workflow" in format_name or "Build" in format_name:
        return [
            "Mit dem unklaren Vorher-Zustand starten.",
            f"Die konkrete Reibung rund um {topic} markieren.",
            "Einen klaren Workflow, eine Checkliste oder einen App-Screen als Loesung zeigen.",
            "Mit einem konkreten naechsten Schritt enden.",
        ]
    return [
        f"Aktuelles Signal benennen: {topic}.",
        "Erklaeren, warum die Zielgruppe der Kampagne jetzt darauf achten sollte.",
        "Eine praktische Handlung fuer diese Woche geben.",
        f"Mit CTA schliessen: {_cta_for_campaign(campaign['name'])}.",
    ]


def _shot_list_for_format(format_name: str, campaign: dict[str, Any]) -> list[str]:
    if "Screen" in format_name or "workflow" in format_name or "Build" in format_name:
        return ["Screenrecording mit Cursor-Zoom", "kurzer Cutaway zur Sprecherperson", "Vorher-nachher-Split-Screen", "CTA-Endkarte"]
    if "POV" in format_name or "Street" in format_name:
        return ["Handheld-Opener", "schnelle Fragenkarte", "zwei schnelle Antworten", "Office- oder Desk-Cutaway", "CTA-Endkarte"]
    return ["Talking-Head-Hook", "grosse Textkarte", "Proof-/Prozess-Cutaway", "drei captioned Beats", "CTA-Endkarte"]


def _animation_for_format(format_name: str) -> str:
    if "Myth" in format_name:
        return "Rot/gruene Split-Cards, MYTHOS/FAKT-Stempel, schnelle Caption-Pops."
    if "Screen" in format_name:
        return "UI-Zooms, Cursor-Halo, Highlight-Rechtecke, 0,2s Swipe-Transitions."
    if "POV" in format_name:
        return "Native Handheld-Cuts, Caption-Bounce auf Kernwoertern, dezenter Speed-Ramp."
    return "Kinetic Captions, Snap-Zoom auf die Kernaussage, Quellenkarte vor dem CTA."


def _caption_for_variant(campaign: dict[str, Any], trend: dict[str, Any], hook: str, cta: str, user_prompt: str) -> str:
    tags = " ".join(f"#{tag}" for tag in trend.get("hashtags", [])[:5])
    return (
        f"{hook}\n\n"
        f"Trend-Signal: {trend.get('topic', '')}\n"
        f"Wichtig fuer {campaign['name']}: {trend.get('angle', '')}\n\n"
        f"{cta}\n\n"
        f"{tags}"
    ).strip()


def _trend_score(campaign: dict[str, Any], topic: str, evidence: list[SearchResult], *, lookback_start: datetime) -> int:
    score = 20
    score += min(len([item for item in evidence if item.source != "campaign_brief"]) * 15, 45)
    score += min(sum(sum(item.metrics.values()) for item in evidence) // 100, 20)
    score += 15 if any(item.published_at and _date_is_recent(item.published_at, lookback_start) for item in evidence) else 0
    score += 10 if set(_tokens(topic, min_length=4)) & set(_tokens(" ".join(campaign.get("keywords", [])), min_length=4)) else 0
    return min(score, 100)


def _verification_note(status: str) -> str:
    notes = {
        "verified_recent": "At least two external sources plus a recent dated signal were found in the lookback window.",
        "source_verified_date_unconfirmed": "Multiple external sources were found, but dates need manual confirmation before claiming recency.",
        "single_source_review": "Only one external source was found; use as inspiration until corroborated.",
        "requires_live_sources": "No live source adapter returned results; configure search credentials before treating this as a trend.",
    }
    return notes.get(status, "Manual review required.")


def _external_evidence_count(trend: dict[str, Any]) -> int:
    return int(((trend.get("verification") or {}).get("evidence_count") or 0))


def _find_campaign_result(trend_run: dict[str, Any], campaign_id: str) -> dict[str, Any]:
    for item in trend_run.get("campaigns", []):
        if item.get("campaign", {}).get("id") == campaign_id:
            return item
    raise ValueError(f"campaign not found in trend run: {campaign_id}")


def _find_trend(campaign_result: dict[str, Any], trend_id: str) -> dict[str, Any]:
    for trend in campaign_result.get("trends", []):
        if trend.get("id") == trend_id:
            return trend
    raise ValueError(f"trend not found: {trend_id}")


def _select_variant(variants: list[dict[str, Any]], variant_id: str | None) -> dict[str, Any]:
    if variant_id:
        for variant in variants:
            if variant.get("id") == variant_id:
                return variant
        raise ValueError(f"variant not found: {variant_id}")
    if not variants:
        raise ValueError("concept bundle has no variants")
    return variants[0]


def _cta_for_campaign(campaign_name: str) -> str:
    name = campaign_name.lower()
    if "qa" in name or "test" in name:
        return "QA-Risikoaudit anfragen"
    if "ki" in name or "sokrates" in name:
        return "Private-KI-Erstgespraech anfragen"
    if "azubi" in name or "lfa" in name:
        return "LFA-Demo oder Ausbildungsplatz-Info anfragen"
    if "mitarbeiter" in name:
        return "Team kennenlernen"
    if "app" in name:
        return "App-Modernisierungscheck anfragen"
    return "Erstgespraech anfragen"


def _persona_for_campaign(campaign_name: str) -> str:
    name = campaign_name.lower()
    if "azubi" in name or "lfa" in name:
        return "Azubi, Ausbilder oder HR-Verantwortliche"
    if "mitarbeiter" in name:
        return "Bewerber und B2B-Entscheider"
    if "ki" in name:
        return "Geschaeftsfuehrer oder IT-Leiter"
    return "IT-Leiter und B2B-Entscheider"


def _hashtags(campaign: dict[str, Any], theme: str) -> list[str]:
    raw = [theme, *campaign.get("keywords", [])[:4]]
    tags: list[str] = []
    for item in raw:
        tag = re.sub(r"[^a-zA-Z0-9_]", "", item.title().replace(" ", ""))
        if tag and tag.lower() not in {existing.lower() for existing in tags}:
            tags.append(tag[:28])
    return tags[:5]


def _published_from_google_item(item: dict[str, Any]) -> str:
    pagemap = item.get("pagemap", {}) if isinstance(item.get("pagemap"), dict) else {}
    for records in pagemap.values():
        if not isinstance(records, list):
            continue
        for record in records:
            if not isinstance(record, dict):
                continue
            for key in ("article:published_time", "datepublished", "date", "og:updated_time"):
                value = record.get(key)
                if value:
                    return str(value)
    return ""


def _date_is_recent(value: str, lookback_start: datetime) -> bool:
    parsed = _parse_datetime(value)
    return bool(parsed and parsed >= lookback_start)


def _parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    cleaned = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(cleaned)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _platform_from_url(url: str) -> str:
    lower = url.lower()
    if "instagram.com" in lower:
        return "instagram"
    if "tiktok.com" in lower:
        return "tiktok"
    if "reddit.com" in lower:
        return "reddit"
    if "youtube.com" in lower or "youtu.be" in lower:
        return "youtube"
    return "web"


def _dedupe_results(results: list[SearchResult]) -> list[SearchResult]:
    seen: set[str] = set()
    deduped: list[SearchResult] = []
    for result in results:
        key = result.url or result.title.lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(result)
    return deduped


def _tokens(text: str, *, min_length: int = 3) -> list[str]:
    return [item.lower() for item in re.findall(r"[a-zA-Z0-9][a-zA-Z0-9_-]+", text or "") if len(item) >= min_length]


def _stable_id(value: str, *, length: int = 10) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:length]


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.lower()).strip("_")
    return slug or "campaign"


def _int_between(value: Any, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = minimum
    return max(minimum, min(maximum, parsed))
