# WAMOCON Marketing-Maschine

The WAMOCON Marketing-Maschine is a human-governed campaign control room for five real campaigns. It combines a simple German browser interface with local AI drafting, public-source trend research, explicit editorial review, and n8n orchestration. The hardened implementation in this repository is a staged candidate under validation; the older live containers remain unchanged until the approved maintenance window.

**Current status, 13 July 2026: RED / no-go for production work.** The final
office-network check could no longer resolve or reach Nvidia-1 over SSH. The
released console was last observed earlier on 13 July as the unchanged
restricted-LAN HTTP version, but it is not currently re-attested. Do not use it
for new work. Its protected service-catalog reference is:

```text
<LEGACY-CONSOLE-URL>
```

Do not enter credentials into that plaintext endpoint if connectivity returns.
After the staged TLS release is activated and accepted in an approved
maintenance window, the normal operator URL comes from the internal service
catalog:

```text
<KONSOLEN-URL>
```

Use the company/LAN CA certificate and a named account; never bypass a browser
certificate warning. The old HTTP endpoint must disappear as part of that
same cutover.

## What the staged candidate implements

- Exactly five campaign definitions (`K1`–`K5`) are loaded from `Kampagnen/`; demo and smoke records are hidden from normal views.
- The dashboard shows campaign lifecycle, weekly progress, source status, review work, and one clear next action.
- SearxNG performs live public-web research. A topic can move into trend-based content only when it has at least two independent source domains and at least one recent dated citation.
- The Content Studio first presents four deterministic, source-grounded editorial directions. These are planning aids, not four AI drafts. A marketer must explicitly select one direction before the local AI creates the complete format-specific draft.
- A local Qwen model generates the selected structured German content through an OpenAI-compatible API. If that model does not return a valid result, the deterministic safety fallback remains blocked and cannot be reviewed, approved, or scheduled; the marketer must regenerate after the capability is restored.
- The completed draft presents the campaign-specific idea, format, hook, public copy or script, production guidance, caption, CTA, and clickable citations. The marketer view reports its creation status in business language and does not expose provider/model names, latency, raw hashes, or internal asset/content IDs.
- Human review requires a named reviewer, brand score, fact check, privacy check, and AI-disclosure check. Revisions create a new version and preserve the earlier audit record.
- n8n provides scheduled planning, authenticated trend/manual intake, health checks, retention discovery, and review-window jobs. The former shared-token approval webhook is retired; human approval belongs only to the named-account console.
- Approval can prepare a Postiz **draft** for a configured LinkedIn or Instagram integration. The system never publishes a public post automatically. For K4, the marketer copies the Postiz media reference/link and selects the exact local original file; the browser computes the integrity proof locally and does not upload that file to the console. The service then reads that exact Postiz media path, verifies that its bytes match, and repeats the check immediately before handoff. The Reel remains blocked until media, preview, reviewer, and consent checks are complete.
- Ambiguous Postiz delivery is never retried blindly. An operator can perform a read-only provider reconciliation, which records the confirmed Postiz ID and lifecycle state locally.
- The **Arbeitsfähigkeit** view reduces dependency health to five business capabilities: research, ideas & copy, media, approval, and editorial planning. Each is shown as ready, review open, or blocked with one useful next step.

## Last-observed live system and staged target

| Component | Last successfully observed on 13 July 2026 | After an approved staged cutover |
| --- | --- | --- |
| Marketing console/API | restricted-LAN HTTP `:18117`; old release, no `/session` | named-account TLS `https://<host>:18117`; raw loopback stays `http://127.0.0.1:8117` |
| n8n | existing single-container 2.29.10 service at restricted-LAN HTTP `:15678`; different digest from the reviewed candidate and non-compliant workflow state | explicitly approved immutable version/digest, TLS edge, and the exact manifest of eight active and two inactive workflow definitions |
| SearxNG / Qwen | successful isolated use was demonstrated before the route loss; current reachability is unavailable | re-attested dependencies with truthful successful-use telemetry |
| Runtime store | production `runtime-data/` on Nvidia-1 | same production store only after backup and cutover; candidate uses a fixed isolated Docker volume |

The final office check could not reach Nvidia-1, so none of the last-observed
rows is a current health statement. The restricted nginx proxy is the intended
LAN entry point. Raw agent and n8n ports remain loopback-only so a workstation
cannot bypass the allowlist.

## Five campaign sources

| Code | Campaign | Configured weekly target | Effective target on 13 July |
| --- | --- | ---: | ---: |
| K1 | Consulting Test- und Qualitätsmanagement | 3 | 3 |
| K2 | KI (Sokrates) | 3 | 3 |
| K3 | LFA – Lernzentrum für Azubis | 5 | 0 (planned) |
| K4 | Mitarbeiter / Arbeitgebermarke | 3 | 3 |
| K5 | Maßgeschneiderte App-Entwicklung (50+ Portfolio) | 2 | 0 (planned) |

Campaign status is derived from the configured dates. On 13 July 2026, K1, K2,
and K4 are active, so the effective weekly target is **9**. K3 and K5 remain
visible as planned campaigns but contribute **0** until their 1 August 2026
start; they must not appear as overdue work before then.

## Important limits

- Firecrawl Cloud support is implemented, but no cloud API key is installed. A private self-hosted Firecrawl instance can be enabled explicitly without a key after separate review. SearxNG is the last successfully demonstrated source adapter; current Nvidia connectivity is unavailable.
- Platform analytics ingestion is not complete. The result view and scheduled review windows must not be treated as automatic Instagram, LinkedIn, TikTok, or Postiz measurement.
- External Postiz, Twenty, and Mautic writes remain disabled in production until their exact paths, scoped credentials, tenant integration IDs, and staging acceptance evidence are approved.
- Manual analytics are accepted only for provider-confirmed published content and require source, measurement period, retrieval time, named operator, and attribution rule. For every reported metric group, the marketer selects the exact provider export; the browser computes its proof locally and does not upload the export.
- ComfyUI is not production-qualified. On 13 July, an isolated loopback-only FLUX Schnell candidate on Nvidia-2 completed a real API generation and strict PNG decode with exact model, runtime, workflow, prompt, and output hashes. That is technical qualification evidence, not release approval. A named human must still record the visual decision and confirm the model/asset licence before this candidate can be promoted; the existing production ComfyUI service remains unchanged.
- The deployed n8n service was last observed as single-container 2.29.10 with a different digest from the reviewed multi-architecture 2.29.9 candidate pin. Either qualify and pin the exact 2.29.10 image or approve 2.29.9 as a separate tested version change. Queue-mode/Postgres hardening remains an operations follow-up.
- Cloud fallback is disabled by default. The configured Kimi credential must be rotated or reissued at the provider before any production use, then the scoped route must be requalified. Private campaign prompts remain local until that separate approval.
- The public GitHub repository currently has no `main` branch protection or ruleset. Before release, require pull requests, successful CI, at least one named reviewer, and block direct pushes to `main`.

## Production change boundary

The hardened work reviewed on 13 July 2026 is a staged candidate, not an
authorisation to recreate production containers, import/publish n8n workflows,
migrate n8n data, or enable external writes. Perform those actions in the next
approved maintenance window with the verified backup, named operator, go/no-go
checks, and tested rollback from the [remote runbook](docs/remote-project-runbook.md).
Keep the n8n database migration, queue-mode activation, and Postiz live-write
qualification as separate releases.

### Latest isolated-candidate evidence

- The authenticated desktop and mobile operator journeys, including the safe
  degraded path, passed against the current isolated candidate. The retained
  desktop/mobile screenshots are final UI evidence for that isolated candidate,
  and the tested views reported zero WCAG A/AA violations.
- The latest local amd64 and arm64 image builds each contained 97 packages and
  reported zero critical, high, medium, or low findings in Docker Scout. Their
  SPDX SBOMs were regenerated. Both images passed local isolation checks with a
  read-only filesystem, UID/GID `10001`, `no-new-privileges`, a `401` response
  for unauthenticated access, exactly K1–K5, and no demo records.
- The arm64 image executed locally through QEMU and reported `aarch64`; this is
  architecture evidence, not execution on real Nvidia hardware. Actual Nvidia
  execution, trusted TLS and dependency acceptance, current-trend research, n8n
  reconciliation, and backup/restore rehearsal remain blocked. The deterministic
  local source archive and its external checksum/inventory sidecars pass content
  and credential inspection, but that archive has not been transferred to or
  exercised on Nvidia hardware.

These checks apply to the exact current local image identities:
`sha256:0ae6c4c57d2564f83929aec844bb54be5e6bca297c1b6efc00b38074478929f8`
for amd64 and
`sha256:7527599ee25d47a9475f60df763e479ce62de205cd8dd7d89737f712c5068d70`
for arm64. Any later application, workflow, campaign, dependency, or image
change invalidates this evidence and requires both builds and their affected
checks to be repeated. The exact local image evidence does not alter the RED
production status or authorise a push or merge to the unprotected `main`
branch.

## Governed deployment smoke

The normal smoke check is read-only and requires an explicit target. On the
host, use the loopback agent plus a protected token file:

```bash
python3 scripts/smoke_api.py \
  --base-url http://127.0.0.1:8117 \
  --access-token-file deploy/secrets/marketing_mutation_token
```

Record-creating checks are refused on the known production ports. Run them only
against the isolated candidate on `:18118`, which uses the fixed
`wamocon_marketing_candidate_validation_data` Docker volume. Provide only a protected file path or the environment variable;
never put a token value on the command line:

```bash
python3 scripts/smoke_api.py \
  --base-url http://127.0.0.1:18118 --allow-mutations \
  --access-token-file deploy/secrets/candidate_mutation_token
python3 scripts/mock_pipeline_test.py \
  --base-url http://127.0.0.1:18118 --isolated-candidate \
  --access-token-file deploy/secrets/candidate_mutation_token
```

Mutating n8n checks are deliberately not part of the generic smoke script.
They remain disabled until a separate n8n candidate exposes a verifiable
disposable-instance marker; pointing a candidate API at production n8n is
never permitted. The candidate API itself must attest
`mode=isolated-candidate`, a `candidate-*` data namespace, and disposable data
before any record-creating smoke starts.

The scripts verify the four read-only analytics due windows. They do not invent
metrics or submit analytics for unpublished dry-run content.

## Developer checks

From the repository root:

```powershell
$env:PYTHONPATH="src"
python -m pytest -q
python -m ruff check .
python -m mypy src
python -m compileall -q src tests
```

Run the API locally:

```powershell
python -m pip install --require-hashes -r requirements/runtime.lock
$env:PYTHONPATH="src"
$env:MARKETING_MACHINE_MUTATION_AUTH_MODE="local-dev-disabled" # loopback development only
python -m uvicorn marketing_machine.api:app --host 127.0.0.1 --port 8080
```

`local-dev-disabled` is intentionally reported as unsafe by `/readyz` and only
accepts requests whose client address is loopback. Never use it with a LAN or
container-network bind. Deployed environments use the Docker secret described
in [the network-access runbook](docs/network-access.md); the restricted proxy
injects the token without exposing it to browser JavaScript.

Production images use the same hash-locked Linux dependency set and a digest-pinned
Python 3.12 base. The lock contains the 44 packages required by FastAPI, Uvicorn
Standard, and the existing LangGraph helper. The application does not require the
OpenAI SDK: local and optional cloud model calls use the repository's guarded
OpenAI-compatible HTTP client.

At container start, a minimal entrypoint gives the existing `/data` bind mount to
the fixed `marketing` account and then drops the API process to UID/GID `10001`.
The root bootstrap is limited to `/data`; an unexpected data path is rejected.

Regenerate the runtime lock only when a production dependency changes:

```powershell
uv pip compile pyproject.toml --extra prod --python-version 3.12 `
  --python-platform linux --generate-hashes `
  --output-file requirements/runtime.lock
```

Review both `pyproject.toml` and the generated lock in the same change. A normal
container build fails if a downloaded artifact does not match the recorded hash.

In a second terminal, verify the responsive dashboard:

```powershell
npm ci
npm audit
npm run smoke:dashboard
```

## Documentation

- [End-user workflow](docs/end-user-workflow.md) — German how-to for marketers.
- [Business and operations handbook (Markdown)](docs/WAMOCON-MARKETING-HANDBOOK.md) — controlled source for marketer and operator guidance.
- [Business and operations handbook (Word)](docs/WAMOCON-Marketing-Handbuch.docx) — formatted distribution copy generated from the controlled source.
- [Remote project runbook](docs/remote-project-runbook.md) — deploy, import, publish, restart, and verify.
- [Network access](docs/network-access.md) — loopback bindings and workstation allowlist.
- [Trend research](docs/trend-studio.md) — source adapters and evidence policy.
- [Current validation record](docs/system-validation-2026-07-13.md) — RED/no-go evidence, tested behavior, and remaining blockers.
- [Historical validation record](docs/system-validation-2026-07-10.md) — earlier completed evidence retained for traceability.
- [Compliance guardrails](docs/compliance-guardrails.md) — mandatory publishing and privacy controls.

The Markdown handbook is the controlled source. After its final review, rebuild
the Word distribution copy and render every page for visual inspection:

```powershell
python scripts/build_handbook_docx.py
python scripts/render_handbook.py
```

Do not edit the generated Word file as an independent source. Concrete private
hostnames, IP addresses, usernames, and host paths belong in the internal
service catalog or change record, not this public repository.

The governing rule is simple: AI may research and draft; a named human decides what may leave the system.
