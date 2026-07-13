from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_BUSINESS_TIMEZONE = "Europe/Berlin"
BUSINESS_TIMEZONE_ENV = "MARKETING_MACHINE_BUSINESS_TIMEZONE"


def business_timezone(environ: Mapping[str, str] | None = None) -> ZoneInfo:
    values = os.environ if environ is None else environ
    name = str(values.get(BUSINESS_TIMEZONE_ENV, DEFAULT_BUSINESS_TIMEZONE)).strip()
    if not name:
        name = DEFAULT_BUSINESS_TIMEZONE
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"invalid business timezone: {name}") from exc


def business_now(
    value: datetime | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> datetime:
    zone = business_timezone(environ)
    if value is None:
        return datetime.now(zone)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("business datetime must include a timezone")
    return value.astimezone(zone)


CAMPAIGN_META: dict[str, dict[str, Any]] = {
    "kampagne_1_consulting_qa": {
        "id": "k1",
        "code": "K1",
        "short_name": "QA-Consulting",
        "primary_persona": "IT-Leiter und QA-Verantwortliche",
        "offer": "QA-Risikoaudit anfragen",
        "generation_objective": "Erklären, wie ein strukturierter QA-Risikoaudit Transparenz über QA-Risiken, Testabdeckung und Freigabeprozesse schaffen kann.",
        "content_constraints": [
            "Nur die freigegebene Prüfen-und-Priorisieren-Aussage als WAMOCON-Leistung formulieren.",
            "Allgemeine QA-Beobachtungen als Frage oder Möglichkeit formulieren, nicht als unbewiesene Tatsache.",
            "Keine Ergebnis-, Effizienz- oder Entscheidungssicherheitsversprechen ergänzen.",
        ],
        "default_risk_flags": ["outcome_claims_require_evidence"],
        "default_channel": "LinkedIn",
        "default_format": "expert_post",
        "weekly_target": 3,
        "content_mix": ["2 LinkedIn-Posts", "1 Carousel", "1 Blog-Entwurf/Monat"],
        "accent": "#0b7668",
    },
    "kampagne_2_ki_sokrates": {
        "id": "k2",
        "code": "K2",
        "short_name": "Sokrates · Private KI",
        "primary_persona": "Geschäftsführer und IT-Leiter",
        "offer": "Private-KI-Erstgespräch anfragen",
        "generation_objective": "Die freigegebene Positionierung von Sokrates für private KI im Mittelstand mit Fokus auf Datenschutz und internes Wissen erklären, ohne Sicherheits-, Compliance- oder Ergebnisversprechen.",
        "content_constraints": [
            "Nur eine Positionierung beschreiben, keine Aussage über vorhandene Architektur oder Implementierung.",
            "Nicht behaupten, wo Daten bleiben, dass keine Cloud nötig ist oder dass Datenschutz, DSGVO, Compliance oder Sicherheit erfüllt sind.",
            "Die Wörter sicher, konform, geschützt und garantiert nicht als Produkteigenschaft verwenden.",
        ],
        "default_risk_flags": ["architecture_and_compliance_claims_require_evidence"],
        "default_channel": "LinkedIn",
        "default_format": "carousel",
        "weekly_target": 3,
        "content_mix": ["2 LinkedIn-Posts", "1 Carousel", "1 Fallstudie/Quartal"],
        "accent": "#1f5f8b",
    },
    "kampagne_3_lfa_azubis": {
        "id": "k3",
        "code": "K3",
        "short_name": "LFA · Ausbildung",
        "primary_persona": "Schüler, Azubis und Ausbilder",
        "offer": "LFA-Demo oder Ausbildungsplatz-Info anfragen",
        "generation_objective": "LFA als strukturiertes digitales Lernsystem für Fachinformatiker-Azubis und Ausbilder erklären, ohne Personen, Produktoberflächen oder Ergebnisse zu erfinden.",
        "content_constraints": [
            "Ein umsetzbares 9:16-Reel-Konzept liefern und die Arbeitsanweisung nicht im öffentlichen Text wiederholen.",
            "Keine Person, Produktoberfläche, Lernfunktion, Ausbildungsqualität oder Lernergebnis erfinden.",
            "Nur neutrale, neu zu produzierende Motive wie Karten, Checklisten oder Typografie vorschlagen.",
        ],
        "default_risk_flags": ["product_ui_and_outcome_claims_require_evidence"],
        "default_channel": "Instagram",
        "default_format": "reel",
        "weekly_target": 5,
        "content_mix": ["3 Reels/TikToks", "1 LinkedIn-Post", "1 Story-Strecke"],
        "accent": "#c3652e",
    },
    "kampagne_4_mitarbeiter": {
        "id": "k4",
        "code": "K4",
        "short_name": "Team & Arbeitgebermarke",
        "primary_persona": "Bewerber und B2B-Entscheider",
        "offer": "Team kennenlernen",
        "generation_objective": "Einen nur mit Personenfreigaben umsetzbaren Team- oder Arbeitsalltagseinblick für Employer Branding und Vertrauensaufbau vorbereiten, ohne Mitarbeitergeschichten zu erfinden.",
        "content_constraints": [
            "Das Ergebnis ist ein Reel-Produktionsplan; alle Personenaufnahmen müssen als erst nach Einwilligung zu filmen markiert sein.",
            "Der öffentliche Text darf nicht behaupten, dass bereits echte oder authentische Einblicke, Aufnahmen oder Aussagen vorliegen.",
            "Keine Unternehmenskultur, Werte, Mitarbeiterzitate oder Alltagsszenen als Tatsache erfinden.",
        ],
        "default_risk_flags": ["people_consent_and_real_assets_required"],
        "default_channel": "Instagram",
        "default_format": "reel",
        "weekly_target": 3,
        "content_mix": ["1 Interview-Post", "1 Behind-the-Scenes", "1 Team-Moment"],
        "accent": "#8b4b63",
    },
    "kampagne_5_app_entwicklung": {
        "id": "k5",
        "code": "K5",
        "short_name": "App-Entwicklung · 50+ Apps",
        "primary_persona": "IT-Leiter und Geschäftsführer",
        "offer": "App-Modernisierungscheck anfragen",
        "generation_objective": "Den freigegebenen Portfolio-Nachweis von mehr als 50 Anwendungen in sieben Kategorien mit einem App-Modernisierungscheck verbinden; einzelne App-Beispiele nur bei gesondertem Nachweis nennen.",
        "content_constraints": [
            "Die freigegebene Angabe nur als Portfolio von mehr als 50 Anwendungen in sieben Kategorien formulieren.",
            "Keine Zeitspanne, erfolgreiche Realisierung, individuelle Anpassung, App-Kategorie, Lieferleistung oder Ergebniswirkung ergänzen.",
            "Kein einzelnes App-Beispiel oder App-Spotlight erfinden; einen belegbaren Portfolio-Carousel erstellen.",
        ],
        "default_risk_flags": ["individual_app_examples_require_evidence"],
        "default_channel": "LinkedIn",
        "default_format": "portfolio_carousel",
        "weekly_target": 2,
        "content_mix": [
            "1 App-Spotlight",
            "1 Build-Story",
            "1 Portfolio-Carousel/Monat",
        ],
        "accent": "#825b16",
    },
}


AUDIENCE_IDS = {
    "zielgruppe_1_itleiter": "z1",
    "zielgruppe_2_recruiterin": "z2",
    "zielgruppe_3_qaengineer": "z3",
    "zielgruppe_4_azubi_fiae": "z4",
    "zielgruppe_5_b2b_ki": "z5",
}


# The campaign export keeps target audiences as opaque UUIDs while the
# audience export omits those UUIDs. Keep the one-to-one export mapping here so
# runtime briefs can use the authored audience research instead of guessing
# from a campaign name or a generic persona string.
AUDIENCE_REF_IDS = {
    "6740a735-d73c-4c0b-9780-5d78448544ca": "z1",
    "5bcedca4-cf35-47a9-85f9-fbce9300bac8": "z2",
    "de57114e-9695-4fd0-9377-beb47a0a8a5a": "z3",
    "9c29e5e3-4e14-43fe-b5b0-3356db002dd3": "z4",
    "de21c685-491b-4c6b-9eb8-733b0b5fb9f8": "z5",
}


def load_campaign_catalog(
    root: Path, *, today: date | None = None
) -> list[dict[str, Any]]:
    today = today or business_now().date()
    audiences_by_id = {item["id"]: item for item in load_audience_catalog(root)}
    campaigns: list[dict[str, Any]] = []
    for path in sorted((root / "Kampagnen").glob("kampagne_*.json")):
        meta = CAMPAIGN_META.get(path.stem)
        if not meta:
            continue
        document = json.loads(path.read_text(encoding="utf-8"))
        raw = document.get("campaign", {})
        start = _parse_date(raw.get("startDate"))
        end = _parse_date(raw.get("endDate"))
        configured_status = str(raw.get("status", "planned"))
        lifecycle_status = _lifecycle_status(configured_status, start, end, today)
        configured_weekly_target = max(0, int(meta.get("weekly_target", 0) or 0))
        counts_toward_weekly_goal = lifecycle_status == "active"
        target_audience_refs = [str(item) for item in raw.get("targetAudiences", [])]
        campaign = {
            **meta,
            "source_id": path.stem,
            "source_ref": f"Kampagnen/{path.name}",
            "name": raw.get("name", meta["short_name"]),
            "description": raw.get("description", ""),
            "master_prompt": raw.get("masterPrompt", ""),
            "configured_status": configured_status,
            "status": lifecycle_status,
            "configured_weekly_target": configured_weekly_target,
            "effective_weekly_target": (
                configured_weekly_target if counts_toward_weekly_goal else 0
            ),
            "counts_toward_weekly_goal": counts_toward_weekly_goal,
            "start_date": start.isoformat() if start else "",
            "end_date": end.isoformat() if end else "",
            "budget_eur": int(raw.get("budget", 0) or 0),
            "spent_eur": int(raw.get("spent", 0) or 0),
            "channels": list(raw.get("channels", [])),
            "keywords": list(raw.get("campaignKeywords", [])),
            "target_audience_refs": target_audience_refs,
            "audience_profiles": [
                _audience_generation_profile(audiences_by_id[audience_id])
                for ref in target_audience_refs
                if (audience_id := AUDIENCE_REF_IDS.get(ref)) in audiences_by_id
            ],
            "seed_kpis": dict(raw.get("kpis", {})),
        }
        campaigns.append(campaign)
    return campaigns


def load_audience_catalog(root: Path) -> list[dict[str, Any]]:
    audiences: list[dict[str, Any]] = []
    for path in sorted((root / "Zielgruppen").glob("zielgruppe_*.json")):
        raw = json.loads(path.read_text(encoding="utf-8")).get("audience", {})
        audiences.append(
            {
                "id": AUDIENCE_IDS.get(path.stem, path.stem),
                "source_id": path.stem,
                "source_ref": f"Zielgruppen/{path.name}",
                **raw,
            }
        )
    return audiences


def get_campaign(root: Path, campaign_id: str) -> dict[str, Any]:
    normalized = str(campaign_id or "").strip().lower()
    for campaign in load_campaign_catalog(root):
        if normalized in {
            campaign["id"],
            campaign["code"].lower(),
            campaign["source_id"],
        }:
            return campaign
    raise KeyError(f"unknown campaign: {campaign_id}")


def resolve_campaign_id(value: str) -> str:
    text = str(value or "").casefold()
    if text in {"k1", "k2", "k3", "k4", "k5"}:
        return text
    aliases = {
        "k1": ("kampagne_1", "qa", "qualit", "testmanagement"),
        "k2": ("kampagne_2", "sokrates", "private ai", "private ki"),
        "k3": ("kampagne_3", "lfa", "azubi", "ausbildung"),
        "k4": ("kampagne_4", "mitarbeiter", "employer", "team"),
        "k5": ("kampagne_5", "app", "softwareentwicklung", "50+"),
    }
    for campaign_id, terms in aliases.items():
        if any(term in text for term in terms):
            return campaign_id
    return ""


def current_revision_heads(states: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project immutable content history to its current revision heads.

    Revision records retain an immutable pointer to their direct predecessor in
    ``revision_source.content_id``.  A predecessor must therefore stop
    contributing to business totals as soon as one of its replacement records
    is present.  Standalone records and parallel revision branches remain
    visible.  This function is deliberately a non-mutating projection so the
    caller can continue to expose the complete audit history separately.

    Only relationships with an exact positive predecessor state revision and
    two matching canonical campaign identities are trusted. Corrupt, ambiguous,
    or legacy pointers fail open; cycles are preserved rather than silently
    hiding every record in the cycle.
    """

    rows = list(states)
    records_by_id: dict[str, dict[str, Any]] = {}
    for item in rows:
        content_id = str(item.get("content_id", "")).strip()
        if content_id:
            records_by_id.setdefault(content_id, item)

    predecessor_by_child: dict[str, str] = {}
    for item in rows:
        child_id = str(item.get("content_id", "")).strip()
        revision_source = item.get("revision_source")
        if not child_id or not isinstance(revision_source, dict):
            continue
        predecessor_id = str(revision_source.get("content_id", "")).strip()
        source_revision = revision_source.get("revision")
        child_revision = item.get("state_revision")
        if (
            not predecessor_id
            or predecessor_id == child_id
            or predecessor_id not in records_by_id
            or isinstance(source_revision, bool)
            or not isinstance(source_revision, int)
            or source_revision < 1
            or isinstance(child_revision, bool)
            or not isinstance(child_revision, int)
            or child_revision < 1
        ):
            continue
        predecessor = records_by_id[predecessor_id]
        predecessor_revision = predecessor.get("state_revision")
        child_campaign = _state_campaign_identity(item)
        predecessor_campaign = _state_campaign_identity(predecessor)
        if (
            not child_campaign
            or not predecessor_campaign
            or child_campaign != predecessor_campaign
            or isinstance(predecessor_revision, bool)
            or not isinstance(predecessor_revision, int)
            or predecessor_revision != source_revision
        ):
            continue
        predecessor_by_child[child_id] = predecessor_id

    cycle_nodes: set[str] = set()
    checked: set[str] = set()
    for start in predecessor_by_child:
        if start in checked:
            continue
        path: list[str] = []
        position: dict[str, int] = {}
        current = start
        while current in predecessor_by_child and current not in checked:
            if current in position:
                cycle_nodes.update(path[position[current] :])
                break
            position[current] = len(path)
            path.append(current)
            current = predecessor_by_child[current]
        checked.update(path)

    superseded_ids = set(predecessor_by_child.values()) - cycle_nodes
    return [
        item
        for item in rows
        if str(item.get("content_id", "")).strip() not in superseded_ids
    ]


def _state_campaign_identity(item: Mapping[str, Any]) -> str:
    explicit = resolve_campaign_id(str(item.get("campaign_id", "")))
    return explicit or resolve_campaign_id(str(item.get("campaign", "")))


def campaign_dashboard(
    root: Path,
    states: Iterable[dict[str, Any]],
    *,
    trend_runs: Iterable[dict[str, Any]] = (),
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    current = business_now(now)
    iso_year, iso_week, _ = current.isocalendar()
    campaigns = load_campaign_catalog(root, today=current.date())
    state_rows = list(states)
    run_rows = list(trend_runs)
    for campaign in campaigns:
        all_campaign_history = [
            item
            for item in state_rows
            if _state_campaign_identity(item) == campaign["id"]
        ]
        all_campaign_states = current_revision_heads(all_campaign_history)
        campaign_states = [
            item
            for item in all_campaign_states
            if _state_is_in_iso_week(item, iso_year=iso_year, iso_week=iso_week)
        ]
        status_counts: dict[str, int] = {}
        for item in campaign_states:
            status = str(item.get("status", "drafting"))
            status_counts[status] = status_counts.get(status, 0) + 1
        approved = sum(
            status_counts.get(key, 0)
            for key in ("approved", "ready_to_schedule", "scheduled", "published")
        )
        in_review = status_counts.get("needs_human_review", 0)
        blocked = status_counts.get("blocked", 0) + status_counts.get(
            "needs_evidence", 0
        )
        configured_target = max(0, int(campaign["configured_weekly_target"]))
        target = max(0, int(campaign["effective_weekly_target"]))
        latest_run, campaign_research = _latest_campaign_research(
            run_rows, campaign, now=current
        )
        campaign["content"] = {
            "total": len(campaign_states),
            "all_time_total": len(all_campaign_states),
            "in_review": in_review,
            "approved": approved,
            "blocked": blocked,
            # ``weekly_target`` remains for existing clients and now reflects
            # the truthful effective goal. Planned campaigns therefore expose
            # zero instead of silently inflating the active weekly target.
            "weekly_target": target,
            "configured_weekly_target": configured_target,
            "effective_weekly_target": target,
            "counts_toward_weekly_goal": bool(campaign["counts_toward_weekly_goal"]),
            "progress_percent": min(100, round((approved / target) * 100))
            if target
            else 0,
            "status_counts": status_counts,
            "week": f"{iso_year}-W{iso_week:02d}",
            "latest": all_campaign_states[0] if all_campaign_states else None,
            "latest_this_week": campaign_states[0] if campaign_states else None,
        }
        campaign["research"] = {
            "status": campaign_research["status"],
            "run_id": (latest_run or {}).get("id", ""),
            "source_adapters": (latest_run or {}).get("source_adapters", []),
            "last_run_at": (latest_run or {}).get("run_started_at", ""),
            "verified_trend_count": campaign_research["verified_trend_count"],
            "trend_count": campaign_research["trend_count"],
            "eligibility_evaluated_at": campaign_research["eligibility_evaluated_at"],
            "freshness_days": campaign_research["freshness_days"],
        }
        campaign["next_action"] = _next_action(campaign)
    return campaigns


def default_brief_payload(
    campaign: dict[str, Any], *, content_id: str
) -> dict[str, Any]:
    channel = campaign["default_channel"]
    return {
        "id": content_id,
        "campaign_id": campaign["id"],
        "campaign": campaign["name"],
        "persona": campaign["primary_persona"],
        "channel": channel,
        "format": campaign["default_format"],
        "objective": campaign["generation_objective"],
        "cta": campaign["offer"],
        "proof_sources": [campaign["source_ref"]],
        "utm": {
            "utm_source": channel.casefold(),
            "utm_medium": "organic",
            "utm_campaign": f"{campaign['id']}_{_slug(campaign['short_name'])}",
        },
        "hypothesis": f"Ein klarer, belegter Beitrag für {campaign['primary_persona']} erzeugt qualifizierte Reaktionen.",
        "test_variable": "hook_and_format",
        "content_mode": "evergreen",
        "language": "de-DE",
        "hashtags": [str(item).replace(" ", "") for item in campaign["keywords"][:5]],
        "campaign_context": {
            "generation_direction": campaign["generation_objective"],
            "content_constraints": campaign.get("content_constraints", []),
            "audience_profiles": [
                dict(item) for item in campaign.get("audience_profiles", [])
            ],
            "keywords": campaign["keywords"],
            "content_mix": campaign["content_mix"],
        },
        "risk_flags": campaign.get("default_risk_flags", []),
    }


def _lifecycle_status(
    configured: str, start: date | None, end: date | None, today: date
) -> str:
    if configured in {"paused", "cancelled", "completed"}:
        return configured
    if start and today < start:
        return "planned"
    if end and today > end:
        return "completed"
    return "active"


def _audience_generation_profile(audience: dict[str, Any]) -> dict[str, Any]:
    """Return only non-identifying fields that help the model choose framing.

    Names and demographic attributes in the imported persona documents are
    intentionally excluded. Audience research guides tone and relevance; it is
    not evidence for public claims.
    """

    return {
        "profile_id": str(audience.get("id", ""))[:40],
        "role": str(audience.get("jobTitle", ""))[:240],
        "audience_type": str(audience.get("type", ""))[:40],
        "segment": str(audience.get("segment", ""))[:40],
        "journey_phase": str(audience.get("journeyPhase", ""))[:80],
        "pain_points": [str(item)[:500] for item in audience.get("painPoints", [])[:3]],
        "goals": [str(item)[:500] for item in audience.get("goals", [])[:3]],
        "decision_context": str(audience.get("decisionProcess", ""))[:800],
    }


def _next_action(campaign: dict[str, Any]) -> dict[str, str]:
    content = campaign["content"]
    research = campaign["research"]
    if campaign["status"] == "planned":
        return {
            "kind": "prepare",
            "label": "Kampagne vorbereiten",
            "detail": f"Start am {campaign['start_date']}",
        }
    if research["status"] not in {"verified_sources", "verified_recent"}:
        return {
            "kind": "research",
            "label": "Quellen prüfen",
            "detail": "Noch kein verifizierter Trend-Scan",
        }
    if content["blocked"]:
        return {
            "kind": "blocked",
            "label": "Blocker lösen",
            "detail": f"{content['blocked']} Inhalt(e) blockiert",
        }
    if content["in_review"]:
        return {
            "kind": "review",
            "label": "Entwurf freigeben",
            "detail": f"{content['in_review']} Entwurf/Entwürfe warten",
        }
    if content["approved"] < content["weekly_target"]:
        missing = content["weekly_target"] - content["approved"]
        return {
            "kind": "create",
            "label": "Content erstellen",
            "detail": f"Noch {missing} bis zum Wochenziel",
        }
    return {
        "kind": "results",
        "label": "Ergebnisse prüfen",
        "detail": "Wochenziel erreicht",
    }


def _state_is_in_iso_week(
    item: dict[str, Any], *, iso_year: int, iso_week: int
) -> bool:
    """Count progress only in the requested ISO week.

    Canonical weekly IDs are the strongest signal because a later review can
    update an older item's timestamp. Manually created content falls back to
    its timestamp. Undated legacy records stay visible in all-time history but
    cannot truthfully contribute to a weekly target.
    """

    content_id = str(item.get("content_id", ""))
    id_week = re.search(r"-(\d{4})w(\d{2})(?:-|$)", content_id, flags=re.IGNORECASE)
    if id_week:
        return (int(id_week.group(1)), int(id_week.group(2))) == (iso_year, iso_week)

    for key in ("created_at", "updated_at"):
        value = str(item.get(key, "")).strip()
        if not value:
            continue
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            continue
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            parsed = parsed.replace(tzinfo=business_timezone())
        else:
            parsed = parsed.astimezone(business_timezone())
        parsed_year, parsed_week, _ = parsed.isocalendar()
        return (parsed_year, parsed_week) == (iso_year, iso_week)
    return False


def _latest_campaign_research(
    run_rows: list[dict[str, Any]],
    campaign: dict[str, Any],
    *,
    now: datetime,
) -> tuple[dict[str, Any] | None, dict[str, int | str]]:
    """Derive research state from this campaign's trends, never run-global status."""

    # Local import avoids the module-level campaign_catalog <-> trend_research
    # dependency cycle while keeping one authoritative eligibility evaluator.
    from .trend_research import (
        apply_current_trend_eligibility,
        CURRENT_TREND_FRESHNESS_DAYS,
    )

    for run in run_rows:
        campaign_results = run.get("campaigns")
        if isinstance(campaign_results, list):
            for result in campaign_results:
                if not isinstance(result, dict):
                    continue
                raw_campaign = result.get("campaign", {})
                raw_id = (
                    raw_campaign.get("id", "") if isinstance(raw_campaign, dict) else ""
                )
                if resolve_campaign_id(str(raw_id)) != campaign["id"]:
                    continue
                trends = [
                    item for item in result.get("trends", []) if isinstance(item, dict)
                ]
                verification_statuses = {
                    str((trend.get("verification") or {}).get("status", ""))
                    for trend in trends
                    if isinstance(trend.get("verification") or {}, dict)
                }
                verified_count = sum(
                    1
                    for trend in trends
                    if apply_current_trend_eligibility(trend, now=now)
                )
                if verified_count:
                    status = "verified_recent"
                elif verification_statuses - {"", "evergreen_unverified"}:
                    status = "needs_source_verification"
                else:
                    status = "needs_live_sources"
                return run, {
                    "status": status,
                    "verified_trend_count": verified_count,
                    "trend_count": len(trends),
                    "eligibility_evaluated_at": now.astimezone(
                        timezone.utc
                    ).isoformat(),
                    "freshness_days": CURRENT_TREND_FRESHNESS_DAYS,
                }

        # Older run summaries do not include the campaign-level evidence
        # required to inherit a run-global success status.
        campaign_ids = {str(item) for item in run.get("campaign_ids", [])}
        if campaign["source_id"] in campaign_ids or campaign["id"] in campaign_ids:
            return run, {
                "status": "needs_source_verification",
                "verified_trend_count": 0,
                "trend_count": int(run.get("trend_count", 0) or 0),
                "eligibility_evaluated_at": now.astimezone(timezone.utc).isoformat(),
                "freshness_days": CURRENT_TREND_FRESHNESS_DAYS,
            }

    return None, {
        "status": "not_run",
        "verified_trend_count": 0,
        "trend_count": 0,
        "eligibility_evaluated_at": now.astimezone(timezone.utc).isoformat(),
        "freshness_days": CURRENT_TREND_FRESHNESS_DAYS,
    }


def _parse_date(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _slug(value: str) -> str:
    return "_".join(
        "".join(ch.lower() if ch.isalnum() else " " for ch in value).split()
    )
