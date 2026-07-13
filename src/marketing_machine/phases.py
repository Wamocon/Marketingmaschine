from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .auth import edge_actor_authorization_status, mutation_authorization_status


def build_phase_status(
    *,
    integrations: dict[str, Any],
    env: Mapping[str, str],
    workflows_dir: Path,
) -> dict[str, Any]:
    checks = {
        str(item["name"]): item
        for item in integrations.get("checks", [])
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    required_checks = [item for item in checks.values() if item.get("required")]
    required_ok = bool(
        all(item.get("ok") for item in required_checks)
        if required_checks
        else integrations.get("status") == "ok"
    )
    local_model_reachable = _available_endpoint(checks.get("local_openai", {}))
    local_model_used = bool(
        checks.get("local_openai", {}).get("used_successfully")
        or checks.get("local_inference", {}).get("used_successfully")
    )
    local_model_status = (
        "complete"
        if local_model_reachable and local_model_used
        else "partial"
        if local_model_reachable
        else "blocked"
    )
    kimi_check = checks.get("kimi", {})
    kimi_configured = bool(kimi_check.get("configured"))
    kimi_reachable = bool(kimi_check.get("reachable"))
    kimi_used = bool(kimi_check.get("used_successfully"))
    kimi_disabled = bool(kimi_check.get("disabled_by_policy"))
    kimi_status = "complete" if kimi_used else "partial" if (kimi_configured or kimi_reachable) else "blocked"
    external_writes_enabled = _truthy(env.get("MARKETING_MACHINE_ENABLE_EXTERNAL_WRITES", ""))
    mutation_access_ready = bool(mutation_authorization_status(env).get("safe"))
    named_approval_ready = bool(edge_actor_authorization_status(env).get("production_ready"))
    configured_targets = {
        "postiz": (
            _has_target_config(
                env, "POSTIZ_CREATE_DRAFT_PATH", "POSTIZ_API_KEY", "POSTIZ_CONTRACT_VERIFIED"
            )
            and bool(env.get("POSTIZ_LINKEDIN_INTEGRATION_ID", "").strip())
            and bool(env.get("POSTIZ_INSTAGRAM_INTEGRATION_ID", "").strip())
            and env.get("POSTIZ_LINKEDIN_PROVIDER_TYPE", "linkedin").strip()
            in {"linkedin", "linkedin-page"}
            and env.get("POSTIZ_INSTAGRAM_PROVIDER_TYPE", "instagram").strip()
            in {"instagram", "instagram-standalone"}
        ),
        "twenty": _has_target_config(
            env, "TWENTY_CREATE_CONTACT_PATH", "TWENTY_API_KEY", "TWENTY_CONTRACT_VERIFIED"
        ),
        "mautic": _has_target_config(
            env, "MAUTIC_CREATE_CONTACT_PATH", "MAUTIC_API_KEY", "MAUTIC_CONTRACT_VERIFIED"
        ),
    }
    write_target_evidence = {
        name: {
            "configured": configured_targets[name],
            "write_ready": bool(checks.get(name, {}).get("write_ready")),
            "used_successfully": bool(checks.get(name, {}).get("used_successfully")),
        }
        for name in configured_targets
    }
    # Environment flags are operator intent, not proof. A write plane is only
    # complete after the read-only service check, exact contract gate, and one
    # stored successful staging/production use all agree.
    write_targets = {
        name: all(evidence.values()) for name, evidence in write_target_evidence.items()
    }
    all_write_targets_ready = all(write_targets.values())
    postiz_first_live_write_ready = bool(
        external_writes_enabled
        and write_target_evidence["postiz"]["configured"]
        and write_target_evidence["postiz"]["write_ready"]
    )

    analytics_workflows = {
        "72h": (workflows_dir / "analytics-72h.json").exists(),
        "7d": (workflows_dir / "analytics-7d.json").exists(),
        "14d": (workflows_dir / "analytics-14d.json").exists(),
        "30d": (workflows_dir / "analytics-30d.json").exists(),
    }
    n8n_reachable = bool(checks.get("n8n", {}).get("ok"))
    n8n_verified = bool(checks.get("n8n", {}).get("used_successfully"))
    live_source_used = any(
        checks.get(name, {}).get("used_successfully")
        for name in ("firecrawl", "searxng", "google_search_key", "reddit_key", "tiktok_research_key")
    )
    source_adapter_available = _research_adapter_available(checks)
    verified_research_used = bool(checks.get("trend_research", {}).get("used_successfully"))
    comfy_check = checks.get("comfyui", {})
    comfy_reachable = bool(comfy_check.get("reachable"))
    comfy_ready = bool(
        comfy_check.get("ok")
        and comfy_check.get("model_bundle_ready")
        and comfy_check.get("runtime_compatible")
        and not comfy_check.get("package_mismatches")
    )
    comfy_used = bool(comfy_check.get("used_successfully"))
    content_workflow_actions: list[str] = []
    if not local_model_used:
        content_workflow_actions.append("Run and record one successful local AI generation")
    if not verified_research_used:
        content_workflow_actions.append("Find an exact-topic trend supported by two domains and one recent dated source")

    phases = [
        _phase(
            "01_control_plane",
            "Control plane and UI",
            "complete" if required_ok else "blocked",
            [
                "FastAPI agent is deployed",
                "Browser console is available",
                "Recent states, leads, outbox, and status are queryable",
            ],
            [] if required_ok else ["Fix required service health before running campaign workflows"],
        ),
        _phase(
            "02_model_plane",
            "Local/private model plane",
            local_model_status,
            [
                "The local OpenAI-compatible model endpoint responds"
                if local_model_reachable
                else "Local model endpoint is unavailable",
                "A successful generation is recorded"
                if local_model_used
                else "No successful inference has been recorded by readiness yet",
                "Local model remains primary for private work",
            ],
            [] if local_model_status == "complete" else [
                "Run one synthetic or real structured generation and record its successful provenance"
                if local_model_reachable
                else "Restore local Ollama and local OpenAI-compatible model health"
            ],
        ),
        _phase(
            "03_cloud_backup",
            "Kimi optional cloud backup",
            kimi_status,
            [
                "Kimi is optional and not required for the marketing flow",
                "A successful Kimi inference is recorded"
                if kimi_used
                else "Kimi is configured but disabled by cloud-fallback policy"
                if kimi_disabled and kimi_configured
                else "Kimi cloud fallback is disabled by policy"
                if kimi_disabled
                else "Kimi is reachable but has not completed a recorded inference"
                if kimi_reachable
                else "Kimi is configured but reachability is not proven"
                if kimi_configured
                else "Kimi key is not configured",
            ],
            [] if kimi_used else [
                "Configure and validate the workload-appropriate Kimi endpoint, key, and model before explicitly enabling cloud fallback"
                if kimi_disabled
                else "Run and record a successful Kimi inference before relying on cloud fallback"
            ],
            critical=False,
        ),
        _phase(
            "04_content_workflow",
            "Content intake, source gate, AI draft, human approval",
            "complete" if local_model_used and verified_research_used else "partial",
            [
                "Manual brief intake is implemented",
                "Verified-source gate blocks unverified current-trend claims",
                "A successful local AI generation is recorded" if local_model_used else "No successful local AI generation is recorded yet",
                "At least one research adapter returned results" if live_source_used else "No research adapter use is recorded yet",
                "A verified trend research run is recorded" if verified_research_used else "No verified trend research run is recorded yet",
                "German-market language guard is active",
                "Approval requires brand, fact, privacy, and AI disclosure checks",
            ],
            content_workflow_actions,
        ),
        _phase(
            "05_governance",
            "Governance and guardrails",
            "complete",
            [
                "No auto-publishing",
                "No public claims without proof",
                "Consent and privacy checks are enforced",
                "Instagram hashtag cap is enforced",
            ],
        ),
        _phase(
            "06_n8n_rhythm",
            "n8n operating rhythm",
            "complete" if n8n_reachable and all(analytics_workflows.values()) and n8n_verified else "partial",
            [
                "n8n is reachable" if n8n_reachable else "n8n is not reachable",
                "Workflow templates are present; file presence alone does not prove imported active behavior",
            ],
            [] if n8n_reachable and all(analytics_workflows.values()) and n8n_verified else [
                "Import, activate, execute, and verify the production workflows before marking this phase complete"
            ],
            metadata={"analytics_workflows": analytics_workflows, "execution_verified": n8n_verified},
        ),
        _phase(
            "07_analytics_loop",
            "Performance learning loop",
            "partial",
            [
                "72h early-signal review is implemented",
                "7d and 14d optimization decisions are implemented",
                "30d scale/stop business-value decision is implemented",
                "Decision rules are implemented, but platform metric ingestion is not yet proven",
            ],
            ["Connect real platform/CRM metrics to per-content review jobs; do not create zero-metric unknown records"],
        ),
        _phase(
            "08_lead_plane",
            "Lead capture, scoring, and CRM payloads",
            "partial" if not (external_writes_enabled and all_write_targets_ready) else "complete",
            [
                "Lead intake is implemented",
                "Consent guard blocks CRM and nurture routing when consent is missing",
                "Twenty and Mautic payload contracts are prepared",
            ],
            [] if external_writes_enabled and all_write_targets_ready else [
                "Live CRM/Mautic writes remain disabled until exact API paths and tokens are configured"
            ],
            metadata={
                "write_targets_ready": write_targets,
                "write_target_evidence": write_target_evidence,
                "external_writes_enabled": external_writes_enabled,
            },
        ),
        _phase(
            "09_publishing_plane",
            "Postiz publishing handoff",
            "partial" if not (external_writes_enabled and write_targets["postiz"]) else "complete",
            [
                "Approved content creates draft-only scheduler payload",
                "Unapproved content cannot route to Postiz",
                "Postiz route is dry-run by default",
            ],
            [] if external_writes_enabled and write_targets["postiz"] else [
                "Live Postiz write remains disabled until POSTIZ_CREATE_DRAFT_PATH and POSTIZ_API_KEY are verified"
            ],
            metadata={
                "postiz_ready": write_targets["postiz"],
                "postiz_first_live_write_ready": postiz_first_live_write_ready,
                "postiz_evidence": write_target_evidence["postiz"],
                "external_writes_enabled": external_writes_enabled,
            },
        ),
        _phase(
            "10_creative_plane",
            "ComfyUI creative workflow",
            "complete" if comfy_ready and comfy_used else "partial" if comfy_reachable else "blocked",
            [
                "ComfyUI process is reachable" if comfy_reachable else "ComfyUI process is unreachable",
                "A recognized generation model is exposed by a loader"
                if comfy_ready
                else "No recognized generation model is exposed by a loader",
                "ComfyUI-ready creative briefs are generated",
                "Human visual approval is required",
            ],
            []
            if comfy_ready and comfy_used
            else [
                "Install and verify a complete licensed model bundle before queue integration"
                if not comfy_ready
                else "Run one approved workflow and record prompt, model, workflow hash, seed, and output artifact"
            ],
            metadata={
                "recognized_model_count": int(comfy_check.get("recognized_model_count", 0) or 0),
                "model_bundle_ready": bool(comfy_check.get("model_bundle_ready")),
                "runtime_compatible": bool(comfy_check.get("runtime_compatible")),
                "package_mismatches": comfy_check.get("package_mismatches", []),
                "used_successfully": comfy_used,
            },
        ),
        _phase(
            "11_langgraph_mcp",
            "LangGraph and MCP production hardening",
            "partial",
            [
                "LangGraph dependency and graph builder are present",
                "MCP allowlist and governance config are present",
            ],
            [
                "Durable LangGraph checkpoint execution is not yet the live API runtime",
                "MCP gateway enforcement is config-level, not a deployed gateway service yet",
            ],
            critical=False,
        ),
    ]

    critical = [phase for phase in phases if phase["critical"]]
    blocked_critical = [phase for phase in critical if phase["status"] == "blocked"]
    incomplete_critical = [phase for phase in critical if phase["status"] != "complete"]
    if blocked_critical:
        overall = "blocked"
    elif incomplete_critical:
        overall = "operational_with_blockers"
    else:
        overall = "operational"

    business_capabilities = _business_capabilities(
        local_model_reachable=local_model_reachable,
        local_model_used=local_model_used,
        source_adapter_available=source_adapter_available,
        live_source_used=live_source_used,
        verified_research_used=verified_research_used,
        comfy_reachable=comfy_reachable,
        comfy_ready=comfy_ready,
        comfy_used=comfy_used,
        mutation_access_ready=mutation_access_ready,
        named_approval_ready=named_approval_ready,
        external_writes_enabled=external_writes_enabled,
        postiz_evidence=write_target_evidence["postiz"],
    )

    return {
        "status": overall,
        "summary": {
            "complete": sum(1 for phase in phases if phase["status"] == "complete"),
            "partial": sum(1 for phase in phases if phase["status"] == "partial"),
            "blocked": sum(1 for phase in phases if phase["status"] == "blocked"),
            "total": len(phases),
        },
        "phases": phases,
        "business_capabilities": business_capabilities,
    }


def _business_capabilities(
    *,
    local_model_reachable: bool,
    local_model_used: bool,
    source_adapter_available: bool,
    live_source_used: bool,
    verified_research_used: bool,
    comfy_reachable: bool,
    comfy_ready: bool,
    comfy_used: bool,
    mutation_access_ready: bool,
    named_approval_ready: bool,
    external_writes_enabled: bool,
    postiz_evidence: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """Translate technical evidence into a fail-closed business capability view.

    ``can_run`` means the protected system has enough current availability for
    a controlled first execution. ``ready`` stays stricter: it additionally
    requires the recorded successful-use or release evidence appropriate for
    that capability. This distinction avoids a bootstrap deadlock without
    presenting an unproven service as production-ready.
    """

    protected_access_ready = mutation_access_ready and named_approval_ready
    research_can_run = source_adapter_available and protected_access_ready
    research_ready = research_can_run and verified_research_used and live_source_used
    if research_ready:
        research = _capability(
            True,
            True,
            "research_verified",
            "Aktuelle Themenrecherche ist durch einen erfolgreichen, quellengeprüften Lauf belegt.",
        )
    elif not protected_access_ready:
        research = _capability(
            False,
            False,
            "research_access_not_protected",
            "Die Recherche bleibt gesperrt, bis der geschützte, persönlich zuordenbare Zugang vollständig eingerichtet ist.",
        )
    elif not source_adapter_available:
        research = _capability(
            False,
            False,
            "research_source_unavailable",
            "Derzeit ist keine unterstützte öffentliche Recherchequelle erreichbar oder vollständig eingerichtet.",
        )
    elif verified_research_used or live_source_used:
        research = _capability(
            False,
            True,
            "research_evidence_incomplete",
            "Ein kontrollierter Recherchelauf ist möglich; der vollständige Quellen- und Erfolgsnachweis ist noch offen.",
        )
    else:
        research = _capability(
            False,
            True,
            "research_controlled_run_available",
            "Eine öffentliche Recherchequelle ist verfügbar. Ein kontrollierter erster Recherchelauf kann den Erfolgsnachweis erbringen.",
        )

    content_can_run = local_model_reachable and protected_access_ready
    content_ready = content_can_run and local_model_used
    if content_ready:
        content_generation = _capability(
            True,
            True,
            "content_generation_verified",
            "Die geschützte Inhaltserstellung wurde erfolgreich ausgeführt.",
        )
    elif not protected_access_ready:
        content_generation = _capability(
            False,
            False,
            "content_access_not_protected",
            "Die Inhaltserstellung bleibt gesperrt, bis der geschützte, persönlich zuordenbare Zugang vollständig eingerichtet ist.",
        )
    elif not local_model_reachable:
        content_generation = _capability(
            False,
            False,
            "content_service_unavailable",
            "Die lokale Inhaltserstellung ist derzeit nicht erreichbar.",
        )
    else:
        content_generation = _capability(
            False,
            True,
            "content_controlled_run_available",
            "Die lokale KI ist erreichbar. Ein kontrollierter erster Entwurf kann den Erfolgsnachweis erbringen.",
        )

    # The technical image runtime is deliberately not presented as a business
    # creation capability. There is no governed console action that binds a
    # campaign brief, output artifact, human approval, and publishing record;
    # video generation is not provided by this image-only runtime at all.
    media_generation = _capability(
        False,
        False,
        "governed_media_job_unavailable",
        "Bild- und Video-Assets werden derzeit außerhalb dieses Arbeitsbereichs erstellt und anschließend hier menschlich geprüft. Eine automatische Medienerstellung ist nicht freigegeben.",
    )

    if protected_access_ready:
        approval = _capability(
            True,
            True,
            "approval_access_protected",
            "Freigaben sind geschützt und werden eindeutig einer berechtigten Person zugeordnet.",
        )
    else:
        approval = _capability(
            False,
            False,
            "approval_access_blocked",
            "Freigaben bleiben gesperrt, bis der geschützte und persönlich zuordenbare Zugang eingerichtet ist.",
        )

    postiz_configured = bool(postiz_evidence.get("configured"))
    postiz_write_ready = bool(postiz_evidence.get("write_ready"))
    postiz_used = bool(postiz_evidence.get("used_successfully"))
    scheduler_can_run = bool(
        postiz_configured
        and postiz_write_ready
        and external_writes_enabled
        and protected_access_ready
    )
    scheduler_ready = scheduler_can_run and postiz_used
    if scheduler_ready:
        scheduler_handoff = _capability(
            True,
            True,
            "scheduler_handoff_verified",
            "Die Übergabe freigegebener Entwürfe an die Redaktionsplanung ist erfolgreich belegt und freigegeben.",
        )
    elif not postiz_configured:
        scheduler_handoff = _capability(
            False,
            False,
            "scheduler_not_configured",
            "Die Übergabe an die Redaktionsplanung ist noch nicht eingerichtet.",
        )
    elif not postiz_write_ready:
        scheduler_handoff = _capability(
            False,
            False,
            "scheduler_contract_not_verified",
            "Die Verbindung zur Redaktionsplanung ist vorhanden, aber die sichere Übergabe ist noch nicht bestätigt.",
        )
    elif not protected_access_ready:
        scheduler_handoff = _capability(
            False,
            False,
            "scheduler_access_not_protected",
            "Die Übergabe bleibt gesperrt, bis der geschützte, persönlich zuordenbare Zugang vollständig eingerichtet ist.",
        )
    elif not external_writes_enabled:
        scheduler_handoff = _capability(
            False,
            False,
            "scheduler_release_disabled",
            "Die Übergabe ist vorbereitet, bleibt aber bis zur bewussten Produktionsfreigabe deaktiviert.",
        )
    else:
        scheduler_handoff = _capability(
            False,
            True,
            "scheduler_controlled_run_available",
            "Die sichere Übergabe ist freigegeben. Ein kontrollierter erster Entwurf kann den Erfolgsnachweis erbringen.",
        )

    return {
        "research": research,
        "content_generation": content_generation,
        "media_generation": media_generation,
        "approval": approval,
        "scheduler_handoff": scheduler_handoff,
    }


def _capability(
    ready: bool,
    can_run: bool,
    reason_code: str,
    business_message: str,
) -> dict[str, Any]:
    return {
        "ready": ready,
        "can_run": can_run,
        "available_for_controlled_run": can_run,
        "status": "green" if ready else "partial" if can_run else "blocked",
        "reason_code": reason_code,
        "business_message": business_message,
    }


def _available_endpoint(check: Mapping[str, Any]) -> bool:
    """Return true only for a configured endpoint with a successful live probe."""

    return bool(
        check.get("ok")
        and check.get("reachable", True) is not False
        and check.get("configured", True) is not False
    )


def _research_adapter_available(checks: Mapping[str, Mapping[str, Any]]) -> bool:
    """Recognize adapters that can truthfully participate in a controlled run."""

    if _available_endpoint(checks.get("searxng", {})):
        return True
    firecrawl = checks.get("firecrawl", {})
    if firecrawl.get("configured") and firecrawl.get("reachable") is not False:
        return True
    google_key = checks.get("google_search_key", {})
    google_engine = checks.get("google_search_engine", {})
    if google_key.get("configured") and google_engine.get("configured"):
        return True
    return any(
        checks.get(name, {}).get("configured")
        for name in ("reddit_key", "tiktok_research_key")
    )


def _phase(
    phase_id: str,
    name: str,
    status: str,
    evidence: list[str],
    next_actions: list[str] | None = None,
    *,
    critical: bool = True,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": phase_id,
        "name": name,
        "status": status,
        "critical": critical,
        "evidence": evidence,
        "next_actions": next_actions or [],
        "metadata": metadata or {},
    }


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _has_target_config(
    env: Mapping[str, str],
    path_key: str,
    token_key: str,
    verification_key: str,
) -> bool:
    return bool(
        env.get(path_key, "").strip()
        and env.get(token_key, "").strip()
        and _truthy(env.get(verification_key, ""))
    )
