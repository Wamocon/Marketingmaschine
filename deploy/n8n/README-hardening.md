# n8n production hardening

The 13 July live audit found n8n 2.29.10 running as one SQLite process with a
different image digest from this candidate. These files deliberately pin the
previously reviewed, multi-architecture n8n 2.29.9 digest. That difference is
production drift, not proof that the candidate matches the live image. The
hardening remains split into two releases so image reconciliation, database
migration, and queue behavior are never changed implicitly at the same time.

## Invariants

- Keep the container/DNS name `core-n8n` and loopback port `127.0.0.1:5678`.
- Use one explicitly approved n8n image digest for both releases. Before the
  maintenance window, either qualify and pin the exact exported live 2.29.10
  image or approve the 2.29.9 candidate as a separate, tested version change.
  Never describe the current `e0d959…` pin as the exact live image.
- Copy the existing encryption key from `/home/node/.n8n/config` into the private
  `secrets/n8n_encryption_key` file. Never generate a replacement.
- Keep Postgres and Redis on `core-n8n-data-net`, which is internal and publishes
  no host ports. Do not reuse any other project's Redis.
- Never start old SQLite n8n and new Postgres n8n together; both would register
  timers and create duplicate executions.
- Never mount the legacy `lokal-ai-stack_n8n-data` volume into either Postgres
  release. Both use the separate `core-n8n-postgres-app-data` volume; the legacy
  SQLite volume remains completely unmounted and untouched for rollback.
- Do not use decrypted credential exports.

## Release 1: SQLite to Postgres

Schedule 45–90 minutes of downtime. Before stopping n8n, verify that no
execution is `running`, `waiting`, or `new`, and record the expected baseline:
13 workflows, 11 active workflows, nine active marketing workflows, two users,
the original two credentials, and the two named WAMOCON Header Auth credentials
created during the current-workflow rollout (four credentials total).

Those are the pre-change recovery-baseline counts, not the target publishing
set. The versioned catalog now contains ten marketing workflow files: eight are
publishable, the shared-credential approval workflow is retired/inactive, and
lead retention remains staged/inactive. Across those definitions there are ten
agent HTTP Request nodes and two inbound Webhook nodes. Recalculate the database
total after import and reject unexpected duplicate IDs; never reactivate the
retired approval ID merely to reproduce the old `11 active / 9 marketing`
baseline.

The release default stores errors but not routine successful, progress, or
manual execution payloads. This controls database growth and avoids retaining
unnecessary business data. `trend-research-intake.json` deliberately overrides
the success setting because its execution ID and verified source result form
release evidence. Lead-retention success payloads remain disabled; durable
privacy events live in the application audit trail. Before the maintenance
window, prove over at least two intervals that `Agent Runtime Observer` still
runs successfully without creating successful execution rows.

Set `N8N_CANONICAL_HOST` to the protected hostname without a scheme or path, and
set `N8N_WEBHOOK_URL` and `N8N_EDITOR_BASE_URL` to the corresponding canonical
HTTPS routes used by webhooks and operators. `N8N_HOST` receives that hostname;
`N8N_LISTEN_ADDRESS=0.0.0.0` is the separate container bind address. The host
port remains on `127.0.0.1`. Never use `0.0.0.0` as a hostname or canonical URL.
Compose validation intentionally fails while any canonical value is missing.

Both releases block environment access in expressions/Code, restrict file
access to `/data/knowledge` and `/data/files`, and remove Code, Execute Command,
and Read/Write Files from Disk because the approved workflow catalog uses none
of them. SSRF protection permits the exact controlled internal dependency
`wmc-marketing-agent`; do not broaden this to a private subnet or wildcard.
Version/security notifications stay enabled. Treat any missing-setting,
outdated-instance, or risky-node result from `n8n audit` as a failed gate.

Workflow secrets stay in encrypted n8n Header Auth credentials. The versioned
JSON carries names only, never credential IDs or values. Before publishing any
imported workflow, an operator must create and explicitly bind:

- `WAMOCON Agent Access Token`: header name
  `X-WAMOCON-Mutation-Token`, value from the agent's existing mutation secret.
- `WAMOCON Inbound Webhook Token`: header name
  `X-WAMOCON-Webhook-Token`, value from a separate random 32-byte secret.

Bind the first credential to every agent HTTP Request node and the second to
the manual-intake and trend Webhook nodes. The approval workflow is a disabled,
node-free tombstone because a shared credential cannot identify a person. Treat an import
with any unresolved credential as failed and keep every affected workflow
unpublished. The same encryption key is required for these credentials to
survive the database migration.

The verified recovery export created on 2026-07-10 already contains workflow,
credential, configuration, SQLite/WAL, application-state, growth-database, and
all 76 n8n entity tables with execution history. Re-verify its `SHA256SUMS`
immediately before the maintenance window. It is the rollback baseline, not the
cutover input: take one final quiesced export after stopping SQLite so no
execution can be lost between export and cutover.

Create secret files with mode `0600` and validate the compose definition before
the window. At cutover, stop the old process first and prove it is stopped:

```bash
docker stop --time=120 core-n8n
test "$(docker inspect --format '{{.State.Status}}' core-n8n)" = "exited"
```

Create a final private export folder. The pinned image reads the stopped volume;
the old n8n process must remain stopped throughout export and import:

```bash
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
final="/home/wamocon/lokal-ai/data/n8n-files/wamocon-marketing-machine/backups/production-hardening/$stamp"
install -d -m 0770 -o wamocon -g 1000 "$final/entities-with-executions"

docker run --rm --user 0:0 \
  -v lokal-ai-stack_n8n-data:/source:ro \
  -v "$final:/backup" \
  --entrypoint sh \
  docker.n8n.io/n8nio/n8n@sha256:e0d9593724e36d2584a1686148155e881233b38ae1833101c97c6463c0d36711 \
  -c 'tar -C /source -czf /backup/n8n-volume.tgz .'

# TypeORM may write SQLite journals even during an entity export. Clone the
# stopped source volume so the verified original remains untouched while the
# CLI receives a writable database filesystem.
clone="core-n8n-migration-$stamp"
docker volume create "$clone"
docker run --rm --user 0:0 \
  -v lokal-ai-stack_n8n-data:/source:ro \
  -v "$clone:/clone" \
  --entrypoint sh \
  docker.n8n.io/n8nio/n8n@sha256:e0d9593724e36d2584a1686148155e881233b38ae1833101c97c6463c0d36711 \
  -c 'cp -a /source/. /clone/'

docker run --rm --user 1000:1000 \
  -v "$clone:/home/node/.n8n" \
  -v "$final/entities-with-executions:/export" \
  docker.n8n.io/n8nio/n8n@sha256:e0d9593724e36d2584a1686148155e881233b38ae1833101c97c6463c0d36711 \
  export:entities --outputDir=/export --includeExecutionHistoryDataTables=true

tar -tzf "$final/n8n-volume.tgz" >/dev/null
find "$final" -type f ! -name SHA256SUMS -print0 \
  | sort -z | xargs -0 sha256sum > "$final/SHA256SUMS"
cd "$final" && sha256sum -c SHA256SUMS
```

Keep both the untouched source volume and the named clone for the 14-day
rollback period. Remove neither during cutover.

`import:entities` decompresses `entities.zip` in its input directory, so the
verified archive must stay read-only. Copy it to a distinct writable workspace
owned by n8n's numeric container user:

```bash
work="/home/wamocon/lokal-ai/data/n8n-files/wamocon-marketing-machine/migration-work/$stamp"
install -d -m 0770 -o wamocon -g 1000 "$work"
install -m 0660 -o wamocon -g 1000 \
  "$final/entities-with-executions/entities.zip" "$work/entities.zip"

sed "s|replace-with-final-stamp|$stamp|g" .env.migration.example > .env.migration
chmod 600 .env.migration
```

Edit `.env.migration` and set both canonical protected HTTPS URLs. The following
compose validation must fail while either value is empty; never replace them
with `0.0.0.0` or an example domain. Authentication values remain in encrypted
n8n credentials and do not belong in this environment file.

Start only Postgres and import into its empty database. Do not start the old
SQLite definition at any point:

```bash
docker compose --env-file .env.migration \
  -f core-stack.release1-postgres.yml config -q
docker compose --env-file .env.migration \
  -f core-stack.release1-postgres.yml up -d core-n8n-postgres
docker compose --env-file .env.migration \
  -f core-stack.release1-postgres.yml run --rm --no-deps core-n8n \
  import:entities --inputDir=/migration --truncateTables
docker compose --env-file .env.migration \
  -f core-stack.release1-postgres.yml up -d --no-deps core-n8n
```

Before activating schedules, open all credential-bearing nodes and verify
that neither credential shows as missing. Then prove both authentication layers
without printing either secret. The unauthenticated webhook check must return
`401`; the credential-backed request must return `2xx` and thereby prove both
the inbound Webhook credential and outbound agent credential. Retain its n8n
execution ID plus returned trend run ID as cutover evidence:

```bash
test "$(curl -sS -o /dev/null -w '%{http_code}' -X POST \
  http://127.0.0.1:5678/webhook/wamocon-marketing/trend-research \
  -H 'Content-Type: application/json' -d '{}')" = "401"

inbound_header="$(mktemp)"
chmod 600 "$inbound_header"
: "${INBOUND_TOKEN_FILE:?Set INBOUND_TOKEN_FILE to the protected inbound-token file}"
printf 'X-WAMOCON-Webhook-Token: %s\n' \
  "$(cat "$INBOUND_TOKEN_FILE")" > "$inbound_header"
curl --fail-with-body -sS -X POST \
  http://127.0.0.1:5678/webhook/wamocon-marketing/trend-research \
  -H "@$inbound_header" \
  -H 'Content-Type: application/json' \
  -d '{"campaign_ids":["kampagne_1_consulting_qa"],"platforms":["web"]}'
rm -f "$inbound_header"
```

Accept only when readiness is HTTP 200, both users can sign in, all four credentials
decrypt, the retired approval workflow is inactive, each intended marketing
workflow is active exactly once, and one idempotent trend execution plus named
console `/session` checks succeed. Keep the
untouched SQLite volume for at least 14 days.

## Release 2: queue mode

Wait at least 24 stable hours on Postgres. Then create a separate Redis password,
validate `core-stack.release2-queue.yml`, and start Redis, one worker with five
slots, and the main process. Redis uses AOF with a 384 MB data ceiling beneath
its 512 MB container limit and `noeviction`, so queue keys are never discarded
arbitrarily. Accept only when both main and worker readiness checks pass, the
queue is visible, an execution runs on the worker, scheduled workflows fire
once, webhooks remain idempotent, Redis memory alerts are active, and graceful
shutdown drains cleanly. Release 2 reuses
`core-n8n-postgres-app-data`; it must not attach the legacy SQLite volume.

## Rollback

For a database migration rollback, stop the worker/new main/Redis/Postgres,
restore the saved core compose definition, and start only the old `core-n8n`
against the untouched SQLite volume. For queue-only rollback, drain the queue,
stop the worker, and restart the main process in regular mode against the same
Postgres database. Do not delete either app-data volume during the 14-day
rollback window.

Official references: [configuration files and `_FILE` secrets](https://docs.n8n.io/hosting/configuration/configuration-methods/),
[database entity migration](https://docs.n8n.io/hosting/cli-commands/), and
[queue mode requirements](https://docs.n8n.io/hosting/scaling/queue-mode/).
