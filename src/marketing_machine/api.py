from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .analytics import evaluate_performance
from .evidence import EvidenceVault
from .governance import GovernancePolicy
from .integrations import check_ollama_model, check_openai_compatible_models, check_url
from .leads import build_lead_intake
from .phases import build_phase_status
from .routing import route_lead as route_lead_to_target
from .routing import route_scheduler_draft as route_scheduler_draft_to_target
from .schemas import ApprovalRecord, ContentBrief, PerformanceRecord, ReviewDecision
from .storage import JsonStore, brief_from_dict
from .trend_research import concept_to_content_brief, generate_reel_concepts, run_trend_research
from .ui import render_marketing_console
from .workflow import MarketingWorkflow, WorkflowState


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def load_runtime_env() -> None:
    import os

    candidates = [
        os.environ.get("MARKETING_MACHINE_ENV_FILE", ""),
        str(repo_root() / "deploy" / "marketing-agent.generated.env"),
        str(repo_root() / "config" / "integrations.local.env"),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if not path.exists():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def load_policy() -> GovernancePolicy:
    return GovernancePolicy.from_json_file(repo_root() / "config" / "governance-policy.json")


def load_evidence_vault() -> EvidenceVault:
    return EvidenceVault.from_json_file(repo_root() / "config" / "evidence-vault.json")


def env_configured(name: str, *, required: bool = False, label: str | None = None) -> dict[str, Any]:
    import os

    return {
        "name": label or name.lower(),
        "ok": bool(os.environ.get(name, "").strip()),
        "required": required,
        "configured": bool(os.environ.get(name, "").strip()),
        "secret_env": name,
    }


load_runtime_env()

app = FastAPI(title="WAMOCON Marketing-Maschine Agent API", version="0.1.0")
app.mount("/static", StaticFiles(directory=Path(__file__).resolve().parent / "static"), name="static")


@app.get("/", response_class=HTMLResponse)
@app.get("/ui", response_class=HTMLResponse)
def marketing_console() -> HTMLResponse:
    return HTMLResponse(render_marketing_console())


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict[str, Any]:
    policy = load_policy()
    return {"status": "ready", "policy": policy.name, "mode": policy.governance_level}


def default_briefs() -> list[ContentBrief]:
    return [
        ContentBrief(
            id="k1-qa-risk-audit-weekly",
            campaign="K1 QA Consulting",
            persona="IT-Leiter Thomas",
            channel="LinkedIn",
            format="expert_post",
            objective="QA-Risikoaudit mit senioriger Testexpertise und belegbaren Prüfpunkten anbieten.",
            cta="QA-Risikoaudit anfragen",
            proof_sources=["Kampagnen/kampagne_1_consulting_qa.json"],
            utm={"utm_source": "linkedin", "utm_medium": "organic", "utm_campaign": "k1_qa_risk_audit"},
            hypothesis="Ein nachweisbasierter QA-Beitrag erzeugt qualifizierte Anfragen von IT-Leitern.",
            test_variable="offer",
            language="de-DE",
        ),
        ContentBrief(
            id="k2-private-ai-discovery-weekly",
            campaign="K2 Sokrates Private AI",
            persona="Geschäftsführer Markus",
            channel="LinkedIn",
            format="carousel",
            objective="Private-KI-Potenzialanalyse erklären, ohne Unternehmenswissen in öffentliche KI-Systeme zu geben.",
            cta="Private-KI-Erstgespräch anfragen",
            proof_sources=["Kampagnen/kampagne_2_ki_sokrates.json"],
            utm={"utm_source": "linkedin", "utm_medium": "organic", "utm_campaign": "k2_private_ai_discovery"},
            hypothesis="Datensouveräne KI-Positionierung erzeugt qualifizierte Gespräche mit Geschäftsführern.",
            test_variable="positioning",
            language="de-DE",
        ),
        ContentBrief(
            id="k5-app-modernization-review-weekly",
            campaign="K5 App Development",
            persona="IT-Leiter Thomas",
            channel="LinkedIn",
            format="app_demo_post",
            objective="App-Portfolio als Nachweis für einen App-Modernisierungscheck nutzen.",
            cta="App-Modernisierungscheck anfragen",
            proof_sources=["Kampagnen/kampagne_5_app_entwicklung.json"],
            utm={"utm_source": "linkedin", "utm_medium": "organic", "utm_campaign": "k5_app_modernization"},
            hypothesis="Konkrete App-Beispiele erzeugen bessere B2B-Anfragen als generische Softwaretexte.",
            test_variable="proof_asset",
            language="de-DE",
        ),
        ContentBrief(
            id="k3-lfa-azubi-weekly",
            campaign="K3 LFA Azubi",
            persona="Azubi, Ausbilder oder HR-Verantwortliche",
            channel="Instagram",
            format="reel",
            objective="LFA und moderne Fachinformatiker-Ausbildung mit authentischen Einblicken positionieren.",
            cta="LFA-Demo oder Ausbildungsplatz-Info anfragen",
            proof_sources=["Kampagnen/kampagne_3_lfa_azubis.json"],
            utm={"utm_source": "instagram", "utm_medium": "organic_reel", "utm_campaign": "k3_lfa_azubi"},
            hypothesis="Authentische LFA-Reels erzeugen Saves, Profilbesuche und qualifizierte Ausbildungs-/B2B-Anfragen.",
            test_variable="format",
            language="de-DE",
            hashtags=["Ausbildung", "FIAE", "LFA", "EdTech", "WAMOCON"],
        ),
        ContentBrief(
            id="k4-employee-brand-weekly",
            campaign="K4 Mitarbeiter",
            persona="Bewerber und B2B-Entscheider",
            channel="Instagram",
            format="reel",
            objective="WAMOCON-Team, Kultur und Consulting-Vertrauen durch menschliche Einblicke sichtbar machen.",
            cta="Team kennenlernen",
            proof_sources=["Kampagnen/kampagne_4_mitarbeiter.json"],
            utm={"utm_source": "instagram", "utm_medium": "organic_reel", "utm_campaign": "k4_employee_brand"},
            hypothesis="Mitarbeiternahe Reels bauen Vertrauen fuer Recruiting und Consulting-Anfragen auf.",
            test_variable="story_angle",
            language="de-DE",
            hashtags=["EmployerBranding", "TeamWAMOCON", "ITKarriere", "BehindTheScenes", "Eschborn"],
        ),
    ]


def create_state_for_brief(brief: ContentBrief) -> dict[str, Any]:
    workflow = MarketingWorkflow(load_policy(), evidence_vault=load_evidence_vault())
    state = workflow.run_until_review(brief)
    return state.to_dict()


@app.get("/workflows/states")
def list_states(limit: int = Query(default=25, ge=1, le=100)) -> dict[str, Any]:
    return {"items": JsonStore().list_states(limit=limit)}


@app.get("/workflows/states/{content_id}")
def get_state(content_id: str) -> dict[str, Any]:
    try:
        return JsonStore().load_state(content_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"content state not found: {content_id}") from exc


@app.post("/workflows/weekly-planning")
def weekly_planning(payload: dict[str, Any]) -> dict[str, Any]:
    store = JsonStore()
    created = []
    for brief in default_briefs():
        state = create_state_for_brief(brief)
        store.save_state(state)
        created.append({"content_id": brief.id, "status": state["brief"]["status"], "next_step": state["next_step"]})
    store.append_event("weekly_planning", {"payload": payload, "created": created})
    return {
        "status": "accepted",
        "calendar_mode": payload.get("calendar_mode", "rolling_30_day"),
        "workflow": "weekly_planning",
        "human_approval_required": True,
        "created": created,
        "next_steps": ["review generated drafts", "approve or request revision", "schedule approved draft-only payloads"]
    }


@app.post("/workflows/trend-research")
def trend_research(payload: dict[str, Any]) -> dict[str, Any]:
    store = JsonStore()
    try:
        trend_run = run_trend_research(repo_root(), payload=payload, policy=load_policy())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    store.save_trend_run(trend_run)
    store.append_event(
        "trend_research",
        {
            "run_id": trend_run["id"],
            "status": trend_run["status"],
            "lookback_days": trend_run["lookback_days"],
            "platforms": trend_run["platforms"],
            "source_adapters": trend_run["source_adapters"],
        },
    )
    return {"status": "created", "run_id": trend_run["id"], "trend_run": trend_run}


@app.get("/workflows/trend-research/runs")
def list_trend_runs(limit: int = Query(default=25, ge=1, le=100)) -> dict[str, Any]:
    return {"items": JsonStore().list_trend_runs(limit=limit)}


@app.get("/workflows/trend-research/runs/{run_id}")
def get_trend_run(run_id: str) -> dict[str, Any]:
    try:
        return JsonStore().load_trend_run(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"trend run not found: {run_id}") from exc


@app.get("/workflows/reel-concepts")
def list_reel_concepts(limit: int = Query(default=25, ge=1, le=100)) -> dict[str, Any]:
    return {"items": JsonStore().list_reel_concepts(limit=limit)}


@app.post("/workflows/reel-concepts")
def create_reel_concepts(payload: dict[str, Any]) -> dict[str, Any]:
    store = JsonStore()
    run_id = str(payload.get("run_id", "")).strip()
    campaign_id = str(payload.get("campaign_id", "")).strip()
    trend_id = str(payload.get("trend_id", "")).strip()
    if not run_id or not campaign_id or not trend_id:
        raise HTTPException(status_code=422, detail="run_id, campaign_id, and trend_id are required")
    try:
        trend_run = store.load_trend_run(run_id)
        concept = generate_reel_concepts(
            trend_run,
            campaign_id=campaign_id,
            trend_id=trend_id,
            user_prompt=str(payload.get("user_prompt", "")),
            variant_count=int(payload.get("variant_count", 4)),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    store.save_reel_concept(concept)
    store.append_event(
        "reel_concept",
        {
            "concept_id": concept["id"],
            "run_id": concept["run_id"],
            "campaign_id": concept["campaign_id"],
            "trend_id": concept["trend_id"],
            "variant_count": len(concept["variants"]),
        },
    )
    return {"status": "created", "concept_id": concept["id"], "concept": concept}


@app.post("/workflows/reel-concepts/{concept_id}/approve")
def approve_reel_concept(concept_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    store = JsonStore()
    try:
        concept = store.load_reel_concept(concept_id)
        brief = concept_to_content_brief(concept, variant_id=str(payload.get("variant_id", "") or "") or None)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    state = create_state_for_brief(brief)
    concept["status"] = "approved_for_content_brief"
    concept["approved_variant_id"] = payload.get("variant_id") or state["brief"].get("reel_concept", {}).get("id", "")
    concept["content_id"] = brief.id
    store.save_reel_concept(concept)
    store.save_state(state)
    store.append_learning(
        {
            "event": "reel_concept_approved",
            "concept_id": concept_id,
            "content_id": brief.id,
            "campaign_id": concept.get("campaign_id", ""),
            "trend_id": concept.get("trend_id", ""),
            "selected_variant_id": concept.get("approved_variant_id", ""),
            "created_at": state["brief"].get("created_at", ""),
        }
    )
    store.append_event("reel_concept_approval", {"concept_id": concept_id, "content_id": brief.id, "state": state})
    return {"status": "approved", "concept_id": concept_id, "content_id": brief.id, "state": state}


@app.post("/workflows/create-content")
def create_content(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        brief = ContentBrief(
            id=payload["id"],
            campaign=payload["campaign"],
            persona=payload["persona"],
            channel=payload.get("channel", "LinkedIn"),
            format=payload.get("format", "expert_post"),
            objective=payload["objective"],
            cta=payload["cta"],
            proof_sources=payload.get("proof_sources", []),
            utm=payload.get("utm", {}),
            hypothesis=payload.get("hypothesis", "Manual intake hypothesis pending."),
            test_variable=payload.get("test_variable", "manual_intake"),
            language=payload.get("language", "de-DE"),
            hashtags=payload.get("hashtags", []),
            risk_flags=payload.get("risk_flags", []),
        )
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=f"missing required field: {exc.args[0]}") from exc
    state = create_state_for_brief(brief)
    JsonStore().save_state(state)
    return {"status": "created", "content_id": brief.id, "state": state}


@app.post("/workflows/approve-content")
def approve_content(payload: dict[str, Any]) -> dict[str, Any]:
    store = JsonStore()
    content_id = payload.get("content_id")
    if not content_id:
        raise HTTPException(status_code=422, detail="missing required field: content_id")
    try:
        current = store.load_state(content_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"content state not found: {content_id}") from exc
    brief = brief_from_dict(current["brief"])
    state = WorkflowState(
        brief=brief,
        errors=current.get("errors", []),
        next_step=current.get("next_step", "human_review"),
        requires_human_review=bool(current.get("requires_human_review", True)),
        evidence_records=current.get("evidence_records", []),
        scheduler_payload=current.get("scheduler_payload", {}),
    )
    try:
        approval = ApprovalRecord(
            content_id=content_id,
            reviewer=payload.get("reviewer", "n8n-human-review"),
            decision=ReviewDecision(payload.get("decision", ReviewDecision.APPROVED.value)),
            brand_score=int(payload.get("brand_score", 90)),
            fact_check_passed=bool(payload.get("fact_check_passed", False)),
            privacy_check_passed=bool(payload.get("privacy_check_passed", False)),
            ai_disclosure_check_passed=bool(payload.get("ai_disclosure_check_passed", False)),
            notes=payload.get("notes", ""),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"invalid approval payload: {exc}") from exc
    result = MarketingWorkflow(load_policy(), evidence_vault=load_evidence_vault()).resume_after_review(state, approval)
    result_dict = result.to_dict()
    store.save_state(result_dict)
    store.append_event("approval", {"content_id": content_id, "result": result_dict})
    return {"status": "reviewed", "content_id": content_id, "state": result_dict}


@app.post("/workflows/comfyui-brief")
def comfyui_brief(payload: dict[str, Any]) -> dict[str, Any]:
    brief = {
        "campaign": payload.get("campaign", "K5"),
        "channel": payload.get("channel", "LinkedIn"),
        "format": payload.get("format", "app_demo_thumbnail"),
        "headline": payload.get("headline", "Proof beats promises"),
        "proof_asset_refs": payload.get("proof_asset_refs", []),
        "output_size": payload.get("output_size", "1080x1350"),
        "review_required": True,
        "submit_to_comfyui": False,
        "rules": [
            "Use approved proof assets only",
            "Do not invent customer screenshots, people, or claims",
            "Human visual approval required before public use"
        ],
    }
    JsonStore().append_event("comfyui_brief", brief)
    return {"status": "draft_created", "comfyui_brief": brief}


@app.get("/integrations/status")
def integrations_status() -> dict[str, Any]:
    import os

    n8n = os.environ.get("N8N_BASE_URL", "http://core-n8n:5678")
    comfyui = os.environ.get("COMFYUI_BASE_URL", "http://host.docker.internal:8188")
    ollama = os.environ.get("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
    local_model = os.environ.get("LOCAL_MODEL_NAME", "")
    local_openai = os.environ.get("LOCAL_OPENAI_BASE_URL", "http://host.docker.internal:11434/v1")
    local_openai_api_key = os.environ.get("LOCAL_OPENAI_API_KEY", "ollama")
    local_openai_model = os.environ.get("LOCAL_OPENAI_MODEL_NAME", "")
    litellm = os.environ.get("LITELLM_BASE_URL", "http://host.docker.internal:4000")
    opa = os.environ.get("OPA_BASE_URL", "http://host.docker.internal:8181")
    searxng = os.environ.get("SEARXNG_BASE_URL", "http://host.docker.internal:8090")
    qdrant = os.environ.get("QDRANT_BASE_URL", "http://host.docker.internal:6333")
    prometheus = os.environ.get("PROMETHEUS_BASE_URL", "http://host.docker.internal:9091")
    grafana = os.environ.get("GRAFANA_BASE_URL", "http://host.docker.internal:3030")
    postiz = os.environ.get("POSTIZ_BASE_URL", "http://wmc-postiz:5000")
    twenty = os.environ.get("TWENTY_BASE_URL", "http://wmc-twenty-server:3000")
    mautic = os.environ.get("MAUTIC_BASE_URL", "http://wmc-mautic-web:80")
    kimi = os.environ.get("KIMI_BASE_URL", os.environ.get("CLOUD_OPENAI_BASE_URL", "https://api.moonshot.ai/v1"))
    kimi_api_key = os.environ.get("KIMI_API_KEY", os.environ.get("CLOUD_OPENAI_API_KEY", ""))
    kimi_model = os.environ.get("KIMI_MODEL_NAME", os.environ.get("CLOUD_MODEL_NAME", ""))

    required_checks = [
        check_url("n8n", f"{n8n.rstrip('/')}/healthz", required=True),
        check_url("comfyui", f"{comfyui.rstrip('/')}/system_stats", required=True),
        check_ollama_model(ollama, local_model, required=True),
        check_openai_compatible_models("local_openai", local_openai, local_openai_api_key, local_openai_model, required=True),
    ]
    optional_checks = [
        check_url("litellm", f"{litellm.rstrip('/')}/health/readiness"),
        check_url("opa", f"{opa.rstrip('/')}/health"),
        check_url("searxng", f"{searxng.rstrip('/')}/"),
        env_configured("GOOGLE_CSE_API_KEY", label="google_search_key"),
        env_configured("GOOGLE_CSE_ID", label="google_search_engine"),
        env_configured("REDDIT_BEARER_TOKEN", label="reddit_key"),
        env_configured("TIKTOK_RESEARCH_CLIENT_TOKEN", label="tiktok_research_key"),
        env_configured("INSTAGRAM_ACCESS_TOKEN", label="instagram_key"),
        env_configured("INSTAGRAM_BUSINESS_ACCOUNT_ID", label="instagram_business_account"),
        check_url("qdrant", f"{qdrant.rstrip('/')}/"),
        check_url("prometheus", f"{prometheus.rstrip('/')}/-/ready"),
        check_url("grafana", f"{grafana.rstrip('/')}/api/health"),
        check_url("postiz", f"{postiz.rstrip('/')}/"),
        check_url("twenty", f"{twenty.rstrip('/')}/"),
        check_url("mautic", f"{mautic.rstrip('/')}/"),
        check_openai_compatible_models("kimi", kimi, kimi_api_key, kimi_model),
    ]
    return {
        "status": "ok" if all(check["ok"] for check in required_checks) else "degraded",
        "required": required_checks,
        "optional": optional_checks,
        "checks": required_checks + optional_checks,
    }


@app.get("/workflows/phase-status")
def phase_status() -> dict[str, Any]:
    import os

    return build_phase_status(
        integrations=integrations_status(),
        env=os.environ,
        workflows_dir=repo_root() / "deploy" / "n8n" / "workflows",
    )


@app.post("/workflows/analytics-review")
def analytics_review(payload: dict[str, Any]) -> dict[str, Any]:
    record = PerformanceRecord(
        content_id=payload.get("content_id", "unknown"),
        review_window=payload.get("review_window", "72h"),
        impressions=int(payload.get("impressions", 0)),
        saves=int(payload.get("saves", 0)),
        shares=int(payload.get("shares", 0)),
        comments_from_target_buyers=int(payload.get("comments_from_target_buyers", 0)),
        profile_visits=int(payload.get("profile_visits", 0)),
        clicks=int(payload.get("clicks", 0)),
        leads=int(payload.get("leads", 0)),
        qualified_leads=int(payload.get("qualified_leads", 0)),
        booked_calls=int(payload.get("booked_calls", 0)),
        pipeline_value_eur=float(payload.get("pipeline_value_eur", 0.0)),
        landing_page_visits=int(payload.get("landing_page_visits", 0)),
        landing_page_conversions=int(payload.get("landing_page_conversions", 0)),
    )
    decision = evaluate_performance(record)
    JsonStore().append_performance({"record": record.__dict__, "action": decision.action.value, "reason": decision.reason})
    return {
        "status": "evaluated",
        "content_id": record.content_id,
        "review_window": record.review_window,
        "action": decision.action.value,
        "reason": decision.reason,
    }


@app.get("/workflows/performance")
def list_performance(limit: int = Query(default=25, ge=1, le=100)) -> dict[str, Any]:
    return {"items": JsonStore().list_performance(limit=limit)}


@app.post("/workflows/lead-intake")
def lead_intake(payload: dict[str, Any]) -> dict[str, Any]:
    store = JsonStore()
    source_content_id = str(payload.get("source_content_id", "")).strip()
    source_verified = False
    if source_content_id:
        try:
            store.load_state(source_content_id)
            source_verified = True
        except FileNotFoundError:
            source_verified = False
    try:
        result = build_lead_intake(payload, source_verified=source_verified)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    store.append_lead(result)
    store.append_event(
        "lead_intake",
        {
            "lead_id": result["lead"]["id"],
            "source_content_id": result["lead"]["source_content_id"],
            "routing_allowed": result["routing_allowed"],
            "next_action": result["lead"]["next_action"],
        },
    )
    return {"status": "accepted", **result}


@app.get("/workflows/leads")
def list_leads(limit: int = Query(default=25, ge=1, le=100)) -> dict[str, Any]:
    return {"items": JsonStore().list_leads(limit=limit)}


@app.post("/workflows/route-scheduler-draft")
def route_scheduler_draft(payload: dict[str, Any]) -> dict[str, Any]:
    store = JsonStore()
    content_id = str(payload.get("content_id", "")).strip()
    if not content_id:
        raise HTTPException(status_code=422, detail="missing required field: content_id")
    try:
        result = route_scheduler_draft_to_target(
            store=store,
            policy=load_policy(),
            content_id=content_id,
            target=str(payload.get("target", "postiz")).strip() or "postiz",
            dry_run=bool(payload.get("dry_run", True)),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    store.append_outbox(result)
    store.append_event(
        "routing",
        {
            "route_id": result["id"],
            "kind": result["kind"],
            "target": result["target"],
            "source_id": result["source_id"],
            "status": result["status"],
            "dry_run": result["dry_run"],
        },
    )
    return {"status": result["status"], "route": result}


@app.post("/workflows/route-lead")
def route_lead(payload: dict[str, Any]) -> dict[str, Any]:
    store = JsonStore()
    lead_id = str(payload.get("lead_id", "")).strip()
    if not lead_id:
        raise HTTPException(status_code=422, detail="missing required field: lead_id")
    try:
        result = route_lead_to_target(
            store=store,
            policy=load_policy(),
            lead_id=lead_id,
            target=str(payload.get("target", "twenty")).strip() or "twenty",
            dry_run=bool(payload.get("dry_run", True)),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    store.append_outbox(result)
    store.append_event(
        "routing",
        {
            "route_id": result["id"],
            "kind": result["kind"],
            "target": result["target"],
            "source_id": result["source_id"],
            "status": result["status"],
            "dry_run": result["dry_run"],
        },
    )
    return {"status": result["status"], "route": result}


@app.get("/workflows/outbox")
def list_outbox(limit: int = Query(default=25, ge=1, le=100)) -> dict[str, Any]:
    return {"items": JsonStore().list_outbox(limit=limit)}
