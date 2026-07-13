# Nvidia-1 Deployment Runbook

This how-to is for operators maintaining the deployed Marketing-Maschine. It covers the existing Nvidia-1 installation; it does not replace host backup, firewall, or identity-management policy.

## Workstation-only candidate QA routes

When an authorised office workstation tests the disposable local candidate,
obtain the two SSH aliases from the protected service catalog and restore the
three loopback-only dependency routes with either explicit parameters:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts/start_candidate_qa_tunnels.ps1 `
  -Nvidia1Host "<NVIDIA1_SSH_HOST>" `
  -Nvidia2Host "<NVIDIA2_SSH_HOST>"
```

or session-only environment variables:

```powershell
$env:WAMOCON_NVIDIA1_SSH_HOST="<NVIDIA1_SSH_HOST>"
$env:WAMOCON_NVIDIA2_SSH_HOST="<NVIDIA2_SSH_HOST>"
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/start_candidate_qa_tunnels.ps1
```

The script starts hidden SSH processes with forward-failure checks and
keepalives, then verifies SearxNG, Qwen/Ollama, and the isolated ComfyUI
qualification endpoint. Existing healthy routes are reused. These forwards are
for candidate QA only: they bind to `127.0.0.1`, do not expose a LAN service,
and do not promote or modify any remote dependency. The helper contains no
embedded host aliases and fails closed when either host value, SSH connection,
forward, or endpoint probe is unavailable.

## Deployment facts

| Item | Value |
| --- | --- |
| Project root | `<PROJECT_ROOT>` from the protected service catalog |
| Agent container | `wmc-marketing-agent` |
| Agent raw port | `127.0.0.1:8117` |
| Agent authorised-workstation proxy after TLS cutover | `<KONSOLEN-URL>` |
| n8n container | `core-n8n` |
| n8n raw port | `127.0.0.1:5678` |
| n8n authorised-workstation proxy after TLS cutover | `<N8N-URL>` |
| Docker network | `core-net` |
| Runtime data | `<project-root>/runtime-data` |
| n8n import mount on host | `<N8N_FILES_ROOT>/workflows` |
| n8n import mount in container | `/data/files/wamocon-marketing-machine/workflows` |

Keep the raw agent and n8n ports bound to loopback. The restricted nginx proxy
in `deploy/docker-compose.network-access.yml` is the LAN entry point and permits
only the addresses or CIDRs supplied through
`MARKETING_MACHINE_ALLOWED_CLIENT_CIDRS`; no DHCP-derived client address is
embedded in the repository.

## Change-window boundary until explicit approval

The repository, candidate image, configuration, backups, and validation results
may be prepared locally. Production mutation is deferred to the next approved
maintenance window. Unless an incident commander authorises an emergency
change, do **not**:

- recreate the production agent or restricted proxy;
- import, rebind, publish, or restart production n8n workflows;
- enable `MARKETING_MACHINE_ENABLE_EXTERNAL_WRITES`;
- run a live Postiz, Twenty, or Mautic write;
- migrate n8n from SQLite to Postgres or enable Redis queue mode; or
- alter production registration, identity, firewall, or data-retention policy.

Permitted staging work is read-only audit, backup/hash verification, compose
validation, candidate build, loopback candidate smoke, and documentation. In
the next window, release the protected agent/proxy first, verify it, then bind
and publish n8n credentials/workflows, and qualify Postiz in a separate staging
step. Keep the n8n database migration and queue-mode release in their own later
windows. Stop after any failed gate; do not combine rollbacks across layers.

Before the next window, the change record must name the technical owner,
secondary operator, business approver, rollback owner, start/end time,
acceptable downtime, candidate image digest, verified backup checksum, and
stakeholder contact channel. Notify stakeholders 24 hours before the window,
at start, every 15 minutes while work is active, and at completion or rollback.
The go/no-go decision requires healthy current services, accessible rollback
media, both operators present, and no unresolved backup, credential, or
allowlist warning.

## 1. Prepare the runtime environment

Work from the project root:

```bash
export PROJECT_ROOT="<PROJECT_ROOT>" # replace from the protected service catalog
cd "$PROJECT_ROOT"
cp -n deploy/marketing-agent.env.example deploy/marketing-agent.generated.env
chmod 600 deploy/marketing-agent.generated.env
```

Create or verify the fail-closed mutation secret before starting either the
agent or access proxy. This command never prints it; the file is git-ignored:

```bash
install -d -m 0700 deploy/secrets
if [ ! -s deploy/secrets/marketing_mutation_token ]; then
  umask 077
  openssl rand -hex 32 > deploy/secrets/marketing_mutation_token
fi
chmod 600 deploy/secrets/marketing_mutation_token
grep -Eq '^[a-f0-9]{64}$' deploy/secrets/marketing_mutation_token
if [ ! -s deploy/secrets/marketing_edge_attestation ]; then
  umask 077
  openssl rand -hex 32 > deploy/secrets/marketing_edge_attestation
fi
chmod 600 deploy/secrets/marketing_edge_attestation
grep -Eq '^[a-f0-9]{64}$' deploy/secrets/marketing_edge_attestation
test "$(cat deploy/secrets/marketing_mutation_token)" != \
  "$(cat deploy/secrets/marketing_edge_attestation)"
```

These are distinct Docker secrets mounted read-only in the agent and proxy.
The mutation token authorises API access; the edge attestation proves nginx set
the named operator identity. Keep
`MARKETING_MACHINE_MUTATION_TOKEN=` empty in the generated environment file;
the deployment reads `MARKETING_MACHINE_MUTATION_TOKEN_FILE`. Do not copy the
secret into a compose value, shell argument, browser bundle, or log.

Set these deployment values in `deploy/marketing-agent.generated.env` without printing secrets to shell history or logs:

```dotenv
LOCAL_OPENAI_BASE_URL=http://<NVIDIA2_PRIVATE_HOST>:11434/v1
LOCAL_OPENAI_API_KEY=ollama
LOCAL_OPENAI_MODEL_NAME=qwen3.6:35b
LOCAL_MODEL_NAME=qwen3.6:35b
OLLAMA_BASE_URL=http://<NVIDIA2_PRIVATE_HOST>:11434
COMFYUI_BASE_URL=http://<NVIDIA2_PRIVATE_HOST>:8188

SEARXNG_BASE_URL=http://ux-searxng:8080
MARKETING_MACHINE_ALLOWED_CLIENT_CIDRS=<APPROVED_OPERATOR_IPV4_OR_CIDR>[,<APPROVED_OPERATOR_IPV4_OR_CIDR>...]
MARKETING_COMFYUI_UPSTREAM=<APPROVED_PRIVATE_COMFYUI_HOST>:8188
MARKETING_MACHINE_AI_ENABLED=true
MARKETING_MACHINE_ALLOW_CLOUD_FALLBACK=false
MARKETING_MACHINE_REQUIRE_EXPLICIT_CONTENT_MODE=true
MARKETING_MACHINE_ENABLE_EXTERNAL_WRITES=false
```

Keep `MARKETING_MACHINE_REQUIRE_EXPLICIT_CONTENT_MODE=true` in production. Direct API intake must then declare `content_mode`. The active n8n manual-content webhook supplies `evergreen` when the inbound mode is omitted; the API rejects current/latest/trending language in evergreen requests. An explicit `current_trend` request passes its stored `trend_run_id` and `trend_id` through unchanged, and the API reloads and revalidates that exact evidence. `false` is migration-only and merely defaults a missing direct-API mode to `evergreen`; it never allows an unverified current-trend claim. `MARKETING_MACHINE_REQUIRE_VERIFIED_TRENDS` remains a deprecated compatibility alias for this explicit-mode switch; do not configure both names with conflicting values.

Firecrawl is optional. Leave `FIRECRAWL_API_KEY` empty when no key has been provisioned; the source adapter will be skipped and SearxNG remains active. To enable it later, set:

```dotenv
FIRECRAWL_BASE_URL=https://api.firecrawl.dev/v2
FIRECRAWL_API_KEY=<secret>
```

For an existing private self-hosted Firecrawl deployment, the upstream project
allows authentication to be omitted. Enable that mode only when the endpoint
is loopback, RFC1918, a private suffix, or a single-label Docker service and is
not exposed to an untrusted LAN. The explicit opt-in is deliberately separate
from the cloud setting:

```dotenv
FIRECRAWL_BASE_URL=http://firecrawl:3002/v2
FIRECRAWL_API_KEY=
FIRECRAWL_ALLOW_UNAUTHENTICATED_SELF_HOSTED=true
```

Keep the flag `false` for Firecrawl Cloud and for every public hostname. The
agent rejects credentialless public endpoints even if the flag is set. Before
using a self-hosted service, verify its container/network ownership and run one
bounded candidate search; only the resulting successful-use telemetry—not the
environment flag—counts as readiness evidence.

Replace every angle-bracket placeholder with the exact value from the protected
service catalog. Never use a placeholder value as a key or runtime authority.
`MARKETING_MACHINE_ALLOWED_CLIENT_CIDRS` must contain only explicitly approved
operator IPv4 addresses/CIDRs. `MARKETING_COMFYUI_UPSTREAM` must be the exact
approved private hostname or IPv4 address plus port. Restart the agent after
changing environment values.

### Build and exercise the isolated candidate

The candidate has its own container, secrets, port, and fixed candidate-only
Docker volume (`wamocon_marketing_candidate_validation_data`). It cannot be
redirected to a host bind mount, does not inherit production runtime data, and
its compose file hard-disables all external writes:

```bash
install -d -m 0700 deploy/secrets
umask 077
openssl rand -hex 32 > deploy/secrets/candidate_mutation_token
openssl rand -hex 32 > deploy/secrets/candidate_edge_attestation
chmod 0600 deploy/secrets/candidate_*
export MARKETING_MACHINE_CANDIDATE_NAMESPACE="candidate-$(date -u +%Y%m%dT%H%M%SZ)"
export LOCAL_OPENAI_BASE_URL="http://<APPROVED_MODEL_HOST>:11434/v1"
export OLLAMA_BASE_URL="http://<APPROVED_MODEL_HOST>:11434"
export COMFYUI_BASE_URL="http://<APPROVED_COMFYUI_HOST>:18189"
docker compose \
  -f deploy/docker-compose.candidate.yml \
  -f deploy/docker-compose.candidate.nvidia.yml \
  config --quiet
docker compose \
  -f deploy/docker-compose.candidate.yml \
  -f deploy/docker-compose.candidate.nvidia.yml \
  up -d --build
unset LOCAL_OPENAI_BASE_URL OLLAMA_BASE_URL COMFYUI_BASE_URL
```

The Nvidia candidate overlay deliberately has no embedded model or ComfyUI
address. Compose refuses to render until all three approved private URLs are
supplied. Confirm their destination hosts and ports against the change record;
never point an isolated candidate at an unapproved or public model endpoint.

Verify the server-issued marker before creating records, then run the protected
smokes with one clearly named test actor. Values are held only in the current
shell and are removed immediately afterward:

```bash
export MARKETING_MACHINE_MUTATION_TOKEN="$(cat deploy/secrets/candidate_mutation_token)"
export MARKETING_MACHINE_EDGE_ATTESTATION="$(cat deploy/secrets/candidate_edge_attestation)"
export MARKETING_MACHINE_TEST_ACTOR="qa.candidate"
python3 scripts/smoke_api.py \
  --base-url http://127.0.0.1:18118 --allow-mutations
python3 scripts/mock_pipeline_test.py \
  --base-url http://127.0.0.1:18118 --isolated-candidate
MARKETING_MACHINE_BASE_URL=http://127.0.0.1:18118 \
  node scripts/dashboard_visual_smoke.js
unset MARKETING_MACHINE_MUTATION_TOKEN \
  MARKETING_MACHINE_EDGE_ATTESTATION MARKETING_MACHINE_TEST_ACTOR
```

Acceptance requires `/healthz` to report `isolated-candidate`, a
`candidate-*` namespace, and `disposable_data: true`. A port number alone is
not isolation proof. Confirm `docker inspect wmc-marketing-candidate` names the
fixed candidate volume before mutation. Never mount `runtime-data/` or the
production secret files into this compose project.

## 2. Build or restart the agent

The Docker build consumes `requirements/runtime.lock` with hash enforcement and
uses the digest-pinned Python base declared in `Dockerfile`. Do not replace the
digest with a floating tag during an incident or routine deployment.

The container starts with a narrowly scoped ownership bootstrap for `/data`, then
runs Uvicorn as UID/GID `10001`. On the first start after this change, the host's
`runtime-data/` files will therefore become owned by `10001:10001`. Back up the
directory before deployment and verify that the API can create a new runtime
record after restart. The entrypoint refuses a data directory outside `/data`.

When a production dependency intentionally changes, regenerate and validate the
Linux lock on a development workstation before copying the release to Nvidia-1:

```powershell
uv pip compile pyproject.toml --extra prod --python-version 3.12 `
  --python-platform linux --generate-hashes `
  --output-file requirements/runtime.lock
uv pip install --dry-run --require-hashes --python 3.12 `
  --python-platform linux --target .runtime-lock-check `
  -r requirements/runtime.lock
```

Remove the temporary `.runtime-lock-check` directory after validation. For a base
image update, inspect the exact official manifest first and record the selected
multi-platform digest in `Dockerfile`; changing only the human-readable tag is not
a reproducible update.

Build and start only the marketing agent:

```bash
docker compose \
  --env-file deploy/marketing-agent.generated.env \
  -f deploy/docker-compose.existing-stack.yml \
  up -d --build wmc-marketing-agent
```

After an environment-only change, recreate the container so Docker applies it:

```bash
docker compose \
  --env-file deploy/marketing-agent.generated.env \
  -f deploy/docker-compose.existing-stack.yml \
  up -d --force-recreate wmc-marketing-agent
```

Verify the process and recent logs:

```bash
docker ps --filter name=wmc-marketing-agent
docker logs --since=5m wmc-marketing-agent
curl -fsS http://127.0.0.1:8117/healthz
curl -fsS http://127.0.0.1:8117/readyz | python3 -c \
  "import json,sys; d=json.load(sys.stdin); assert d['status']=='ready' and d['mutation_authorization']['safe'] is True"
test "$(curl -sS -o /dev/null -w '%{http_code}' -X POST \
  http://127.0.0.1:8117/workflows/trend-research \
  -H 'Content-Type: application/json' -d '{}')" = "401"
```

## 3. Start or update the restricted LAN proxy

Confirm that `deploy/marketing-agent.generated.env` contains the exact approved
`MARKETING_MACHINE_ALLOWED_CLIENT_CIDRS` and
`MARKETING_COMFYUI_UPSTREAM`. The entrypoint validates both and renders the
runtime nginx configuration; repository defaults are intentionally absent.
Then run:

```bash
docker compose --env-file deploy/marketing-agent.generated.env \
  -f deploy/docker-compose.network-access.yml up -d
docker logs --since=5m wmc-marketing-access
```

From an authorised workstation, verify:

```text
<KONSOLEN-URL>
<N8N-URL>
```

Do not change the raw n8n binding to `0.0.0.0:5678`. That would bypass the workstation allowlist.

## 4. Back up n8n before an import

An import can update workflows and deactivate them. Create an export before every release:

```bash
stamp=$(date -u +%Y%m%dT%H%M%SZ)
backup_dir="/data/files/wamocon-marketing-machine/backups/$stamp"
docker exec core-n8n mkdir -p "$backup_dir"
docker exec core-n8n n8n export:workflow --backup --output="$backup_dir"
```

The backup is visible on the host under:

```text
<N8N_FILES_ROOT>/backups/<timestamp>/
```

Confirm that the directory contains workflow JSON files before continuing.

## 5. Import the versioned n8n workflows

The last live audit found n8n `2.29.10` with a different digest from the
reviewed multi-architecture `2.29.9` migration candidate (`e0d959…`). Before
this section, the change record must either qualify and pin the exact exported
live `2.29.10` image or approve `2.29.9` as a separate tested version change.
Do not let the database migration silently change the application version.

Create two encrypted Header Auth credentials in the current restricted n8n UI
before importing. Do not put either value in workflow JSON, container
environment, shell history, or execution data:

1. `WAMOCON Agent Access Token` with header name
   `X-WAMOCON-Mutation-Token`; enter the value from
   `deploy/secrets/marketing_mutation_token` through the operator's secure
   clipboard/password manager.
2. `WAMOCON Inbound Webhook Token` with header name
   `X-WAMOCON-Webhook-Token`; generate a separate random 32-byte value, store it
   in the ignored `deploy/secrets/n8n_inbound_webhook_token` file (mode `0600`)
   or the operator vault, and enter it through the same protected UI:

```bash
umask 077
openssl rand -hex 32 > deploy/secrets/n8n_inbound_webhook_token
```

Creating a credential by name does not prove an imported node is bound to its
local credential ID. Keep the imported workflows unpublished until every
credential-bearing node has been opened and explicitly rebound. The retired
human-approval workflow contains no nodes and must remain unpublished; a shared
n8n credential is not proof of a human identity.

Do not use n8n expressions such as `$env.MARKETING_MACHINE_MUTATION_TOKEN` or
`$env.MARKETING_MACHINE_N8N_WEBHOOK_TOKEN`. The outbound agent header comes
only from the encrypted `WAMOCON Agent Access Token` credential, and inbound
Webhook authentication comes only from the independently generated encrypted
`WAMOCON Inbound Webhook Token` credential. A missing local credential ID is a
release failure, not a reason to fall back to an environment expression.

Copy the repository definitions into the n8n file mount and import them:

```bash
export N8N_FILES_ROOT="<N8N_FILES_ROOT>" # replace from the protected service catalog
docker exec -u 0 core-n8n mkdir -p /data/files/wamocon-marketing-machine/workflows
docker exec -u 0 core-n8n chown -R node:node /data/files/wamocon-marketing-machine
cp deploy/n8n/workflows/*.json \
  "$N8N_FILES_ROOT/workflows/"

docker exec core-n8n n8n import:workflow \
  --separate \
  --input=/data/files/wamocon-marketing-machine/workflows
```

In the n8n UI, bind `WAMOCON Agent Access Token` to every HTTP Request node:
manual intake, integration health, weekly planning, verified
trend research, and all four daily analytics due-discovery workflows.
Bind `WAMOCON Inbound Webhook Token` to the Webhook node in manual intake,
and verified trend research. Save each workflow and confirm no
node reports a missing credential. This is a fail-closed publish gate.

Treat import as deactivating the imported workflows, even when a JSON file contains `"active": true`. Publish the exact stable IDs explicitly:

```bash
docker exec core-n8n n8n publish:workflow --id=lYfpV4r4oeEzPtuO
docker exec core-n8n n8n publish:workflow --id=Psaft2cYujD42MAs
docker exec core-n8n n8n publish:workflow --id=GqGVw06F64o7rvjI
docker exec core-n8n n8n publish:workflow --id=WMCTrendResearch01
docker exec core-n8n n8n publish:workflow --id=eTZSmmzKe6dJ1knR
docker exec core-n8n n8n publish:workflow --id=WMCAnalytics7d01
docker exec core-n8n n8n publish:workflow --id=WMCAnalytics14d1
docker exec core-n8n n8n publish:workflow --id=WMCAnalytics30d1
```

The IDs map to manual intake, integration health, weekly
planning, verified trend research, and four daily read-only due-discovery
windows. Those four GET workflows surface due items in their saved n8n
executions; they do not claim to ingest Postiz metrics or make analytics
decisions. Do not publish a newly duplicated ID; restore the backup and
investigate first.

Restart n8n so schedules and production webhooks are re-registered:

```bash
docker restart core-n8n
docker logs --since=5m core-n8n
```

Verify active workflows after the restart:

```bash
docker exec core-n8n n8n list:workflow --active=true
```

All eight IDs above must appear exactly once, and retired approval workflow ID
`5OzpL9oBMR8gpSJA` must not be active. Also open
`<N8N-URL>` from an authorised workstation and confirm each
workflow is published/active. Import success alone is not activation proof. The
certificate must be trusted and the operator must use a named account.

## 6. Verify SearxNG and Qwen from the agent network

Confirm that SearxNG is running and attached to `core-net`:

```bash
docker ps --filter name=ux-searxng
docker inspect ux-searxng --format '{{json .NetworkSettings.Networks}}'
```

Check SearxNG from inside the agent container:

```bash
docker exec wmc-marketing-agent python -c \
  "import json,urllib.parse,urllib.request; u='http://ux-searxng:8080/search?'+urllib.parse.urlencode({'q':'WAMOCON QA Trends','format':'json'}); d=json.load(urllib.request.urlopen(u,timeout=20)); print('results',len(d.get('results',[])))"
```

Check the overall integration view:

```bash
agent_header="$(mktemp)"
chmod 600 "$agent_header"
printf 'X-WAMOCON-Mutation-Token: %s\n' \
  "$(cat deploy/secrets/marketing_mutation_token)" > "$agent_header"
curl -fsS -H "@$agent_header" \
  http://127.0.0.1:8117/integrations/status | python3 -m json.tool
```

This endpoint distinguishes configured, reachable, and successfully used. A reachable Qwen endpoint is not proof of generation; run the idempotent weekly planning action when the current week's five real drafts are intended:

```bash
curl -fsS -X POST http://127.0.0.1:8117/workflows/weekly-planning \
  -H "@$agent_header" \
  -H 'Content-Type: application/json' \
  -d '{"calendar_mode":"rolling_30_day"}' | python3 -m json.tool
rm -f "$agent_header"
```

Inspect each returned `generation` record. The expected status is `ai_generated` with the local Qwen model, not `deterministic_fallback`. Repeating this command in the same ISO week returns the existing canonical drafts instead of overwriting history.

## 7. Verify the n8n production webhooks

Use the host-loopback n8n port for an operator smoke request. This keeps the raw endpoint off the LAN:

```bash
test "$(curl -sS -o /dev/null -w '%{http_code}' -X POST \
  http://127.0.0.1:5678/webhook/wamocon-marketing/trend-research \
  -H 'Content-Type: application/json' -d '{}')" = "401"

inbound_header="$(mktemp)"
chmod 600 "$inbound_header"
printf 'X-WAMOCON-Webhook-Token: %s\n' \
  "$(cat deploy/secrets/n8n_inbound_webhook_token)" > "$inbound_header"
curl -fsS -X POST \
  http://127.0.0.1:5678/webhook/wamocon-marketing/trend-research \
  -H "@$inbound_header" \
  -H 'Content-Type: application/json' \
  -d '{
    "request_id":"operator-trend-smoke-2026-07-10",
    "lookback_days":10,
    "campaign_ids":["kampagne_1_consulting_qa"],
    "platforms":["web"]
  }' | python3 -m json.tool
rm -f "$inbound_header"
```

The response must contain source telemetry. A result may honestly remain blocked when it does not have two independent domains and a recent dated citation; a non-empty search response is not sufficient verification.

### Remediate a draft that fails stricter source revalidation

Never edit or delete the active JSON by hand. Preview the archival/blocking action first:

```bash
docker exec wmc-marketing-agent python -m marketing_machine.remediation \
  <content-id> --data-dir /data
```

Review the validation errors and archive target. Then apply with a named operator:

```bash
docker exec wmc-marketing-agent python -m marketing_machine.remediation \
  <content-id> --data-dir /data --apply --operator "<operator name>"
```

The command stores the original state, source run, and checksum manifest below `/data/archive/trend-evidence/`, marks the active draft blocked, and returns it to research. It refuses reviewed, terminal, or scheduled content. Start a fresh research request afterward; do not reuse the invalidated run.

## 8. Qualify Postiz without publishing

Do this only in a separate approved staging window. Keep production external
writes disabled while discovering tenant configuration and validating the
payload contract.

1. Confirm public registration is disabled and the dedicated Postiz Public API
   key is scoped to the intended tenant.
2. Read the tenant integrations through Postiz's Public API. Record the exact
   integration ID for each approved channel; an account name, handle, provider
   label, or group ID is not an integration ID.
3. Match the provider type to that integration. Supported values are
   `linkedin` or `linkedin-page` for LinkedIn and `instagram` or
   `instagram-standalone` for Instagram.
4. Save a synthetic staging request/response, Postiz version, integration ID,
   provider type, operator, timestamp, and cleanup proof in the acceptance
   record. Only then set `POSTIZ_CONTRACT_VERIFIED=true`.

The private agent environment then contains the tenant-specific values:

```dotenv
POSTIZ_CREATE_DRAFT_PATH=/api/public/v1/posts
POSTIZ_LIST_POSTS_PATH=/api/public/v1/posts
POSTIZ_LINKEDIN_INTEGRATION_ID=<exact-Postiz-integration-id>
POSTIZ_LINKEDIN_PROVIDER_TYPE=linkedin
POSTIZ_INSTAGRAM_INTEGRATION_ID=<exact-Postiz-integration-id>
POSTIZ_INSTAGRAM_PROVIDER_TYPE=instagram
POSTIZ_CONTRACT_VERIFIED=true
MARKETING_MACHINE_ENABLE_EXTERNAL_WRITES=false
```

Do not enable the final flag merely because the service is reachable. First
prove a dry-run outbox record. In a later, explicitly approved staging step,
enable writes for one synthetic, human-approved draft and verify that Postiz
contains exactly one draft and no scheduled or published provider item.

The application does not upload media in this release. Upload the synthetic or
approved asset to the intended Postiz media path first, then register the exact
provider media reference and direct path while selecting the identical local
original in the console. Registration fetches the provider bytes without
following redirects, enforces a bounded image/video response, and stores a
matching SHA-256 verification. Immediately before a live draft request, the
agent fetches and hashes that same provider path again. A changed, redirected,
unreachable, wrong-type, oversized, or mismatched asset blocks the handoff.
The Postiz draft payload may attach only this provider-verified media. In
Postiz, still verify crop, audio, subtitles, consent, alt text, and the final
platform preview. Never schedule a media-dependent item with an empty or
different attachment list.

If a write returns `delivery_unknown`, do not call the draft route again. In
the console choose **Status mit Postiz abgleichen**. That action performs a
read-only Postiz list lookup, requires one unique match, stores the provider ID
and evidence hash locally, and never resends the post. A `409` means no unique
match or a state conflict; `502` means the provider result could not be trusted.
Investigate either response manually before any retry. Reconcile again after
the final Postiz action so only a provider-confirmed `published` event can start
analytics timing.

Retain the detailed database/file backup and provider acceptance evidence from
[the growth and creative integration checklist](growth-creative-integration-acceptance.md).

## 9. Verify the deployment with protected smoke scripts

Run the normal read-only production smoke against the raw host-loopback API
with the protected token file:

```bash
python3 scripts/smoke_api.py \
  --base-url http://127.0.0.1:8117 \
  --access-token-file deploy/secrets/marketing_mutation_token
```

Run record-creating tests only against a disposable candidate on a non-production
port. The server marker is checked in addition to the command-line acknowledgement:

```bash
python3 scripts/smoke_api.py \
  --base-url http://127.0.0.1:18118 --allow-mutations \
  --access-token-file deploy/secrets/candidate_mutation_token
python3 scripts/mock_pipeline_test.py \
  --base-url http://127.0.0.1:18118 --isolated-candidate \
  --access-token-file deploy/secrets/candidate_mutation_token
```

Do not pass an n8n target to either record-creating smoke script. Generic
mutating n8n smoke is retired until a separate n8n candidate exposes its own
verifiable disposable-instance marker. A candidate API plus production n8n is
not an isolated test. Use the explicit, single-workflow verification in
section 7 only inside its approved change window.

The scripts may read `MARKETING_MACHINE_MUTATION_TOKEN` from their process
environment, but the protected file is preferred. They do not accept secret
values as CLI options or include them in output. Before mutations they require
the server to attest `mode=isolated-candidate`, a `candidate-*` namespace, and
disposable data. Both scripts verify the four read-only due-task endpoints and
explicitly prove their new dry-run content is absent. They do not post
fabricated analytics.

## 10. Release acceptance checks

The last-observed production installation does not yet satisfy these gates,
and the final office-network check could not reach Nvidia-1.
Run them only after the approved maintenance deployment, and attach the output
to the change record rather than treating candidate evidence as live proof.

Run the read-only service checks after every deployment:

```bash
python3 scripts/smoke_api.py \
  --base-url http://127.0.0.1:8117 \
  --access-token-file deploy/secrets/marketing_mutation_token
docker exec core-n8n n8n list:workflow --active=true
```

Then run the fail-closed operator-edge acceptance from an authorised
workstation. It performs only `GET` requests, requires trusted TLS and two
distinct named accounts, refuses plaintext credential prompts, and verifies
the exact active/inactive marketing workflow IDs through the n8n public API:

```bash
export KONSOLEN_URL="<KONSOLEN-URL>" # replace from the protected service catalog
export N8N_URL="<N8N-URL>"           # replace from the protected service catalog
python3 scripts/release_acceptance.py \
  --console-url "$KONSOLEN_URL" \
  --n8n-url "$N8N_URL" \
  --operator-credentials-file deploy/secrets/acceptance_primary_basic_auth \
  --operator-credentials-file deploy/secrets/acceptance_secondary_basic_auth \
  --n8n-api-key-file deploy/secrets/n8n_readonly_api_key \
  --comfyui-approval-file deploy/secrets/comfyui_release_approval.json \
  --ca-file deploy/secrets/marketing_operator_ca.pem
unset KONSOLEN_URL N8N_URL
```

Each operator file contains one `named.account:password` value. Populate these
files from the approved password manager only for the acceptance session,
protect them with mode `0600`, and remove the plaintext copies afterward. The
n8n key must have only the `workflow:list` scope when the installed n8n edition
supports granular scopes. Omit `--ca-file` only when the certificate chain is
already trusted by the workstation. The script intentionally has no insecure
TLS option and never accepts a password, API key, or bearer token directly on
the command line. Save its JSON result in the change record without adding
the credential files.

The ComfyUI approval file is also protected evidence, not a configuration
shortcut. It must bind the exact qualified output SHA-256, prompt ID, workflow
SHA-256, runtime-identity SHA-256, and model-files SHA-256. It contains two
separate decisions: `visual_approval` by a named creative reviewer and
`license_approval` by a different named legal/licence reviewer. Each decision
records time, evidence reference, and the canonical qualification-binding
hash; the licence record also identifies the approved licence and source
repository. The technical qualifier cannot create or self-attest either
approval. Protect this JSON with mode `0600`, never store it in Git, and do not
reuse it after any bound value changes.

Run the built-in n8n security audit in the same read-only acceptance period:

```bash
docker exec core-n8n n8n audit
```

Attach and triage its credential, database, file-system, risky-node, webhook,
security-setting, and version findings. Do not waive an unprotected webhook,
missing security setting, unexpected community/custom node, or outdated
instance merely because the eight workflow IDs are correct.

Acceptance conditions:

- A trusted TLS handshake succeeds from an authorised workstation for both
  `<KONSOLEN-URL>` and `<N8N-URL>`. Continuing through a certificate warning is
  a failed gate.
- Plain HTTP no longer serves either operator interface. It may be refused or
  return only a safe HTTPS redirect, but it must not expose a UI, API response,
  credential prompt, or session over plaintext.
- Through the TLS edge, `/session` returns the authenticated named operator and
  `/readyz` reports ready with safe mutation and actor authentication. A
  caller-supplied actor name is not identity evidence.
- Console responses include
  `Content-Security-Policy: frame-ancestors 'none'` and
  `X-Frame-Options: DENY`.
- `/campaigns` reports exactly five campaigns.
- Normal state listings contain no demo, mock, smoke, or placeholder trend records.
- Qwen has at least one recorded successful inference.
- SearxNG is reachable and has at least one recorded source run.
- ComfyUI reports one fresh history-verified technical qualification, and the
  protected approval evidence binds distinct named visual and licence
  decisions to exactly that output, prompt, workflow, runtime, and model-file
  identity.
- The eight publishable marketing workflow IDs listed in section 5 are active
  exactly once. Retired approval workflow `5OzpL9oBMR8gpSJA` is inactive, and
  staged retention workflow `WMCLeadRetention01` remains inactive unless it
  has its own approved release. The API contains no unexpected workflow, each
  full definition matches the canonical file hash and required credential
  reference, and the retained trend execution ID resolves to a finished,
  successful execution of `WMCTrendResearch01`.
- The console is usable at desktop and mobile widths without browser errors.
- All four analytics due endpoints are read-only, return lifecycle timestamps,
  and exclude content without a provider-confirmed publication.
- A manual analytics record includes source system/reference, period,
  retrieval time, named operator, attribution rule, and optional export
  SHA-256; an identical retry is idempotent and a conflicting retry is rejected.
- Any Postiz `delivery_unknown` record has been uniquely reconciled or remains
  visibly blocked without a blind retry.
- External writes remain disabled unless a separate, approved integration release explicitly enables them.
- The configured Kimi credential has been rotated or reissued at the provider
  and the route requalified, or cloud fallback remains disabled.
- GitHub `main` enforces pull requests, required CI, at least one named review,
  and no direct or force-push bypass.
- The exact pre-change backup checksum has been reverified and the two named
  operators have rehearsed the rollback in section 11. A backup directory that
  has not been checksum-verified and made recoverable is not an accepted
  rollback.

## 11. Roll back

For an agent regression, restore the previously released project files, then rebuild the single service with the same generated environment file. Do not delete `runtime-data/`.

For an n8n regression:

1. Unpublish the affected new workflow in the n8n UI.
2. Import the JSON files from the timestamped backup.
3. Publish the restored stable IDs explicitly.
4. Restart `core-n8n`.
5. Verify the active list and production webhook again.

Never use `git reset --hard`, delete the n8n volume, or remove `runtime-data/` as a rollback shortcut.

## Known operational gaps

- Nvidia-1 could not be resolved or reached over SSH at the final office check;
  all earlier host/dependency observations require fresh read-only attestation.
- Firecrawl Cloud is not active until a real key is installed. A private self-hosted instance may instead use the explicit no-auth candidate mode, but it is not active until its service and one bounded search are verified.
- Automatic social-platform analytics ingestion is incomplete; scheduled review jobs only identify due items.
- Postiz, Twenty, and Mautic external writes are disabled and not release-qualified.
- The isolated ComfyUI candidate is technically qualified, but production
  promotion and governed campaign-output queue submission remain blocked until
  the protected distinct visual/licence approval record and separate release
  acceptance exist.
- The existing n8n deployment is not yet hardened into Postgres/Redis queue mode.
- Live n8n was last observed at 2.29.10, while the reviewed migration candidate
  pins 2.29.9; the exact release version and digest are not yet approved.
- The configured Kimi credential still requires provider-side rotation or
  reissue and post-rotation qualification; cloud fallback remains disabled.
- The public GitHub repository still lacks enforced protection for `main`.
