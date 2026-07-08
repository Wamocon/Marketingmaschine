# Architecture

## Goal

The WAMOCON Marketing-Maschine is an always-on operating system for B2B marketing. It should continuously research, create, approve, publish, measure, learn, and update the next rolling 30 days.

It is designed for a lean team with human approval, local/private AI, and open-source infrastructure where practical.

## Planes

| Plane | Responsibility | Initial Implementation |
| --- | --- | --- |
| Control | Agent workflow, state, approvals, audit trail | `src/marketing_machine` plus future LangGraph production graph |
| Workflow | Scheduled jobs, retries, external API glue | `deploy/n8n/workflows` and n8n queue mode compose template |
| Model | Local and optional cloud model routing | `config/model-routing.json` |
| Knowledge | Evidence vault, approved claims, consent, campaign facts, trend provenance, concept learning records | `db/schema.sql` and strategy JSON/Markdown |
| Governance | Allowlists, blocked tools, policy checks, approval gates | `config/governance-policy.json` and `governance.py` |
| Creative | Brand-safe image/video workflow contracts | `deploy/comfyui/wamocon-creative-contract.json` |
| Publishing | Draft-only scheduling after approval | Postiz/Metricool integration contracts |
| Lead | Lead capture, scoring, CRM follow-up | Mautic/Twenty/HubSpot contracts |
| Analytics | 72h, 7d, 14d, 30d optimization decisions | `analytics.py` and n8n analytics workflow |

## Data Flow

1. Orchestrator creates a content brief from campaign, persona, and current priorities.
1. Trend Studio can run a 10-day public-source scan, group source-backed signals by campaign, and generate Instagram Reel concepts.
2. Evidence gate requires proof sources before drafting.
3. Campaign agent drafts content using local/private model route by default.
4. Compliance gate checks blocked claims, proof, consent, and hashtag limits.
5. Human reviewer approves, requests revision, or rejects.
6. Scheduler creates a draft-only payload for Postiz or Metricool.
7. Published content is measured at 72h, 7d, 14d, and 30d.
8. Analytics agent recommends scale, iterate, landing-page fix, offer/audience fix, or stop.
9. Orchestrator updates the rolling 30-day plan every week.

## Model Routing

Default route is local Qwen via vLLM or SGLang for private work. Cloud frontier models are optional and must be used only for final polish or high-risk review after governance approval.

Routine work should not leave the local environment:

- strategy analysis
- content drafting
- structured extraction
- visual reasoning
- tool-agent work

Cloud usage is allowed only when:

- the content contains no confidential or personal data
- the Compliance Agent permits it
- a human reviewer approves the route

## Governance Boundaries

The system fails closed:

- unlisted tools are denied
- blocked tools are denied
- publishing tools require review
- customer and employee content requires consent
- statistics and ROI claims require evidence
- Instagram hashtags are capped at 5
- public replies are drafted only, never auto-posted

## Scaling Path

Start as a modular monolith:

- one agent API
- one Postgres database
- one Redis queue
- n8n queue mode workers
- internal ComfyUI and local model endpoints

Extract services later only when bottlenecks are real:

- analytics ingestion service
- evidence search service with pgvector
- creative job service for ComfyUI queues
- publishing adapter service
