# WAMOCON Marketing-Maschine

This repository is the implementation scaffold for the WAMOCON always-on AI marketing operating system.

The original strategy documents define campaigns, audiences, and bot roles. The added scaffold turns that strategy into an executable operating model:

- governed agent workflow with human approval
- rolling 30-day planning and 72-hour optimization rhythm
- data contracts for briefs, approvals, leads, experiments, and KPI records
- lead intake with consent guard, qualification scoring, and CRM/Mautic payload contracts
- governed routing outbox for Postiz/Twenty/Mautic handoff with dry-run first
- Trend Studio for 10-day public-source trend scans, campaign-aligned Instagram Reel concepts, topic-locked regeneration, and approval into the review workflow
- local-model routing for private work
- integration templates for n8n, Postiz/Metricool, Mautic/Twenty/HubSpot, ComfyUI, and MCP tools

## Current State

This is not yet a fully deployed production stack. It is a repo-ready foundation that can be tested locally and then connected to the real infrastructure.

Implemented now:

- Python workflow skeleton that creates, reviews, pauses, approves, and schedules content items.
- Governance policy that blocks auto-publishing and risky claims.
- Lead intake endpoint that scores enquiries, blocks no-consent routing, and prepares CRM/Mautic payloads.
- Routing outbox endpoints that prepare Postiz drafts and CRM lead handoff without live writes unless explicitly enabled.
- Phase-readiness endpoint and UI tab that shows complete, partial, and blocked implementation phases.
- KPI performance listing endpoint for recent optimization decisions.
- Trend research and Reel concept endpoints with JSON persistence and UI wiring.
- Database schema for the evidence vault, approvals, audits, experiments, leads, and performance data.
- Deployment templates for core services and n8n workflows.
- Runbooks for operations, testing cadence, and compliance.

## Quick Test

From the repo root:

```powershell
$env:PYTHONPATH="src"
python -m marketing_machine.cli demo
python -m unittest discover -s tests
```

Expected behavior:

- The demo produces one draft content item.
- The workflow stops before publishing and requires human approval.
- Tests verify governance blocks unsafe publishing, approval pause/resume works, and analytics rules produce optimization actions.

## Deployed Smoke Test

On the NVIDIA host, after starting `deploy/docker-compose.existing-stack.yml`:

```bash
python3 scripts/smoke_api.py --base-url http://127.0.0.1:8117 --n8n-url http://127.0.0.1:5678
```

This verifies the agent API, n8n webhook pass-throughs, ComfyUI/Ollama/n8n connectivity, approval pause/resume, guarded scheduler payloads, creative brief contract, and the 72-hour analytics decision endpoint.

For a stricter deployed mock-data pass, run:

```bash
python3 scripts/mock_pipeline_test.py --base-url http://127.0.0.1:8117 --n8n-url http://127.0.0.1:5678
```

This verifies missing proof, Instagram hashtag spam, weak approval, final scheduler guard, growth-tool connectivity, and 72-hour/7-day/14-day/30-day optimization decisions.

## Phase Readiness

Use the `Phases` tab in the console or this endpoint:

```text
http://192.168.178.75:18117/workflows/phase-status
```

It reports which phases are complete, partial, or blocked. The expected production blockers until credentials are verified are live Postiz/Twenty/Mautic writes, actual ComfyUI queue submission, optional Kimi backup, and durable LangGraph/MCP gateway hardening.

## Cloud Backup API

Local Qwen remains the default for private work. Kimi can be configured as an optional OpenAI-compatible cloud backup for fallback or final review tasks only:

```bash
cp deploy/marketing-agent.env.example deploy/marketing-agent.generated.env
# add KIMI_API_KEY and optionally KIMI_MODEL_NAME in the generated file
docker compose --env-file deploy/marketing-agent.generated.env -f deploy/docker-compose.existing-stack.yml up -d --build
```

The integration status endpoint checks Kimi without exposing the API key.

## Optional Growth Tools

Postiz, Twenty, and Mautic are available through `deploy/docker-compose.growth-tools.yml` as opt-in profiles. Start one profile at a time because the NVIDIA host is already memory-heavy.

```bash
docker compose --env-file deploy/growth-tools.generated.env -f deploy/docker-compose.growth-tools.yml --profile twenty up -d
```

See `docs/growth-tools.md` for setup, ports, and guardrails.

## Network Access

The default compose files keep tools on `127.0.0.1`. For LAN access, start the restricted nginx proxy:

```bash
docker compose -f deploy/docker-compose.network-access.yml up -d
```

See `docs/network-access.md` for URLs and exposure rules.

## End-User Console

Use the browser console for campaign intake, human approval, lead scoring, routing, creative briefs, and KPI reviews:

```text
http://192.168.178.75:18117/ui
```

See `docs/end-user-workflow.md` for the two n8n pipelines and the simple browser procedure.

Trend Studio is available in the same console. Configure at least one live source adapter (`SEARXNG_BASE_URL`, Google Programmable Search, Reddit OAuth, or TikTok Research API) before treating results as verified trends. See `docs/trend-studio.md`.

## Production Direction

Use the local DGX-class machine for private work:

- Qwen3.6-35B-A3B via vLLM or SGLang for private strategy, drafts, and internal reasoning.
- Optional frontier/cloud model only for high-risk review or final polishing.
- LangGraph for durable stateful workflows.
- n8n queue mode for scheduled jobs, retries, and external integrations.
- ComfyUI for reusable branded creative generation.
- Postiz or Metricool for approved scheduling.
- Mautic plus Twenty/HubSpot for lead capture, scoring, and CRM follow-up.

No AI-generated public post should be published without human approval.
External writes to Postiz, Twenty, or Mautic should stay dry-run until credentials, endpoint paths, and final approval rules are verified.
