# Growth and Creative Integration Acceptance

This document is the operator reference and release checklist for Postiz, Twenty, Mautic, and ComfyUI. It records the read-only audit performed on 10 July 2026, the isolated ComfyUI technical qualification performed on 13 July 2026, and the controls required to qualify each integration without accidentally publishing content or writing real lead data.

## Safety invariants

- Keep `MARKETING_MACHINE_ENABLE_EXTERNAL_WRITES=false` until a named operator approves a staging result.
- Keep `POSTIZ_CONTRACT_VERIFIED`, `TWENTY_CONTRACT_VERIFIED`, and `MAUTIC_CONTRACT_VERIFIED` set to `false` until the corresponding acceptance record exists.
- Use synthetic content and synthetic contacts for contract tests. Never use a customer email address in staging.
- Back up the database and persistent files before changing an application image.
- Do not print environment files, API keys, OAuth secrets, database passwords, or access tokens in shell output.
- A login page or HTTP 200 response proves reachability only. It does not prove authentication, tenant mapping, payload validity, successful processing, or rollback.

## Audited state

| Integration | Audited runtime | Demonstrated | Not demonstrated / blocker |
|---|---|---|---|
| Postiz | `v1.47.0`; image digest `sha256:1d5a5dc6...a911a9` | UI and Swagger specification respond; `/api/public/v1/posts` returns 401 without a key, confirming the route exists | Registration is open; no container health check is deployed; no API key, connected social integration, valid tenant payload, or draft acceptance exists; the running version predates the current `v2.21.x` release train |
| Twenty | `APP_VERSION=v2.19.2`; image digest `sha256:d81e5cc5...07f1da` | `/healthz` is healthy; the read-only upgrade status reports instance version `2.19.0` and `Up to date` | No scoped API key or workspace-specific REST schema mapping has been accepted; the project lead envelope is not yet a valid Twenty `Person` payload |
| Mautic | Mautic `7.1.3`, Twig `3.28.0`; image digest `sha256:373a3de0...f4d5e` | Database container responds | Installation is incomplete; the database has zero tables; following the installer redirect returns HTTP 500 because `includeWithEvent()` declares `string` but receives `Twig\Markup`; the deployed Docker health check does not follow redirects and falsely reports healthy |
| ComfyUI on Nvidia-2 | Core `0.25.0` at full commit `bd39bbf0678ebd31c972fd365733a8c729f2cd74`; Python `3.12.13`; PyTorch `2.11.0+cu130` | `/system_stats`, `/object_info`, `/queue`, and `/history` respond; queue and history are empty | No loader exposes a complete approved diffusion bundle, `ae.safetensors` is zero bytes, package versions are below the core requirements, and no generated artifact exists |

The audited growth-tool containers consume approximately 4.6 GiB combined at idle. Nvidia-1 had 79 GiB available memory and 2.3 TiB available disk during the audit. Nvidia-2 had 61 GiB available memory and 3.4 TiB available disk, so capacity is not the immediate blocker.

The ComfyUI row above describes the pre-existing production service observed
on 10 July. It was not modified. On 13 July, a separate candidate root and
loopback-only port `18189` passed the strict repository qualifier with all four
real model files and one freshly generated 512×512 RGB artifact. The evidence
binds output SHA-256 `32d00b1e7688c957c769409501a71effcf544084f2f9de1a0c7e328a7bb25618`
to prompt, graph, runtime, and model-file identities. This is a technical
candidate result only; named visual approval and licence confirmation remain
open, and production is still not qualified.

## Reproducible images

`deploy/docker-compose.growth-tools.yml` now uses explicit image variables instead of floating `latest` tags. The defaults reproduce the images that were running during the audit. This prevents a restart from silently introducing an application or database upgrade; it does not mean every pinned application is release-qualified.

Before changing a pin, record it in the private host env and create backups:

```bash
export PROJECT_ROOT="<PROJECT_ROOT>" # replace from the protected service catalog
cd "$PROJECT_ROOT"
umask 077
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "backups/growth-$stamp"

docker exec wmc-postiz-postgres sh -lc \
  'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
  > "backups/growth-$stamp/postiz.dump"

# Temporal owns scheduling/workflow state in its own Postgres cluster.
docker exec wmc-postiz-temporal-postgres sh -lc \
  'pg_dumpall -U "$POSTGRES_USER"' \
  > "backups/growth-$stamp/postiz-temporal.sql"

docker exec wmc-twenty-db sh -lc \
  'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' \
  > "backups/growth-$stamp/twenty.dump"

docker exec wmc-mautic-db sh -lc \
  'mysqldump --single-transaction -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"' \
  > "backups/growth-$stamp/mautic.sql"

sha256sum "backups/growth-$stamp"/* > "backups/growth-$stamp/SHA256SUMS"
test -s "backups/growth-$stamp/postiz.dump"
test -s "backups/growth-$stamp/postiz-temporal.sql"
test -s "backups/growth-$stamp/twenty.dump"
test -s "backups/growth-$stamp/mautic.sql"
```

Database dumps do not contain Postiz uploads/configuration, Redis AOF data,
Temporal Elasticsearch visibility indexes, Twenty local storage, or Mautic
config/media. Stop the Postiz application and Temporal services before taking a
filesystem-consistent volume snapshot (the database dumps above can be online):

```bash
docker stop --time=120 wmc-postiz wmc-postiz-temporal
docker stop --time=120 wmc-postiz-temporal-elasticsearch wmc-postiz-redis

for item in \
  'wmc-postiz:/config:postiz-config' \
  'wmc-postiz:/uploads:postiz-uploads' \
  'wmc-postiz-redis:/data:postiz-redis' \
  'wmc-postiz-temporal-elasticsearch:/usr/share/elasticsearch/data:postiz-temporal-elasticsearch'
do
  container="${item%%:*}"
  remainder="${item#*:}"
  source="${remainder%%:*}"
  label="${remainder##*:}"
  docker run --rm --volumes-from "$container:ro" \
    -v "$PWD/backups/growth-$stamp:/backup" \
    alpine@sha256:5b10f432ef3da1b8d4c7eb6c487f2f5a8f096bc91145e68878dd4a5019afde11 \
    tar -C "$source" -czf "/backup/$label.tgz" .
done

find "backups/growth-$stamp" -type f ! -name SHA256SUMS -print0 \
  | sort -z | xargs -0 sha256sum > "backups/growth-$stamp/SHA256SUMS"
(cd "backups/growth-$stamp" && sha256sum -c SHA256SUMS)
for archive in backups/growth-$stamp/*.tgz; do tar -tzf "$archive" >/dev/null; done
```

Restart the stopped production services only if no upgrade is beginning. Before
an upgrade is called reversible, restore `postiz.dump` and
`postiz-temporal.sql` into isolated Postgres containers, restore all four tar
archives into new named volumes, start an isolated Postiz/Temporal stack, and
verify that draft counts, scheduled Temporal workflows, uploads, and visibility
search match the source. Record the restore container names, row/workflow
counts, checksums, operator, and screenshots. Merely creating archives is not a
restore test.

## Postiz acceptance

Postiz's official public API uses a raw API key in the `Authorization` header. It does **not** use the `Bearer` prefix. For the bundled self-hosted image, the verified draft endpoint is `/api/public/v1/posts`. The upstream API documents `type: "draft"` as the non-publishing mode. Upload responses expose a media `id` and `path`, but no content checksum, so WAMOCON independently verifies the exact provider path against the selected local original. See the [Postiz API overview](https://docs.postiz.com/public-api/introduction), [create-post contract](https://docs.postiz.com/public-api/posts/create), [upload-from-URL contract](https://docs.postiz.com/public-api/uploads/upload-from-url), [file-upload contract](https://docs.postiz.com/public-api/uploads/upload-file), and [Temporal migration guide](https://docs.postiz.com/installation/migration).

### Required setup

1. Stage the upgrade from `v1.47.0` to a reviewed current release on a copy of the Postiz database and upload volumes. Do not jump the production database directly. The current upstream release line has security releases and Postiz requires Temporal for newer versions.
2. Create the owner account through the allowlisted UI.
3. Set `POSTIZ_DISABLE_REGISTRATION=true`, recreate only the Postiz application container, and verify that `GET /api/auth/can-register` returns `{"register":false}`.
4. Configure only the approved providers. OAuth redirect URLs must use the final HTTPS hostname, not the temporary IP address.
5. Create a dedicated Public API key under **Settings → Developers → Public API**. Store it in the host secret file, not Git.
6. Record the target integration ID and provider settings for each channel. LinkedIn profile, LinkedIn Page, Facebook-linked Instagram, and standalone Instagram use different provider types.

### Read-only authentication check

```bash
export POSTIZ_URL=http://127.0.0.1:4007
read -rsp 'Postiz API key: ' POSTIZ_API_KEY; echo
curl --fail --silent --show-error \
  -H "Authorization: $POSTIZ_API_KEY" \
  "$POSTIZ_URL/api/public/v1/integrations?group=$POSTIZ_GROUP_ID"
unset POSTIZ_API_KEY
```

### Staging draft check

Use a non-connected staging integration or a provider-approved sandbox. The request must contain `type: "draft"`, one known integration ID, the correct provider `__type`, and synthetic copy. After the call:

1. Confirm that the item appears only as a Postiz draft.
2. Confirm that no provider-side post, scheduled item, notification, or analytics record exists.
3. Delete the synthetic draft in Postiz.
4. Save the request schema, response status, Postiz version, integration type, operator, timestamp, and screenshot in the evidence vault.

The staged WAMOCON code now translates an approved item into the documented
provider-specific draft shape and refuses any media attachment that was not
byte-verified from its exact Postiz path. Registration and the final handoff
each perform an independent bounded fetch and SHA-256 comparison. This local
implementation is not evidence that the running Postiz tenant accepts the
contract. Keep `POSTIZ_CONTRACT_VERIFIED=false` until the reversible staging
test above validates the exact running version, tenant, integration, provider
type, text shape, media path, idempotency, and cleanup. Only then configure:

```dotenv
POSTIZ_CREATE_DRAFT_PATH=/api/public/v1/posts
POSTIZ_CONTRACT_VERIFIED=true
```

## Twenty acceptance

Twenty generates its REST and GraphQL APIs from each workspace's schema. There is no universal static `Person` payload. Its official documentation requires a scoped key in `Authorization: Bearer ...`; the workspace-specific API playground becomes available after creating the key. See the [Twenty API reference](https://docs.twenty.com/developers/extend/api) and [upgrade guide](https://docs.twenty.com/developers/self-host/capabilities/upgrade-guide).

### Required setup

1. Complete owner/workspace onboarding and disable any public signup mode not required by the business.
2. Define the minimum data model: Person, Company, source content ID, campaign ID, offer, qualification score, next action, consent timestamp, and UTM fields.
3. Create a dedicated role that can read/create/update only the required Person and Company fields. Do not grant metadata-administration or workspace-admin permission.
4. Create an expiring API key assigned to that role and copy it once into the host secret store.
5. Open **Settings → API & Webhooks** and export the generated REST schema for that workspace.
6. Implement a deterministic mapping from the internal `LeadRecord` envelope to this schema. Do not forward unknown nested fields.

### Read-only authentication check

```bash
export TWENTY_URL=http://127.0.0.1:4019
read -rsp 'Twenty API key: ' TWENTY_API_KEY; echo
curl --fail --silent --show-error \
  -H "Authorization: Bearer $TWENTY_API_KEY" \
  "$TWENTY_URL/rest/people?limit=1"
unset TWENTY_API_KEY
```

Run the create/update/delete contract only against a staging workspace and a synthetic address such as `acceptance.invalid`. Verify deduplication, field permissions, audit history, retry idempotency, and deletion before setting:

```dotenv
TWENTY_CREATE_CONTACT_PATH=/rest/people
TWENTY_CONTRACT_VERIFIED=true
```

## Mautic recovery and acceptance

The running Mautic image must not be installed in place. The audited installer follows `/` → `/installer` and fails with HTTP 500. The current container health check probes only the redirect response; the repository correction uses `curl --fail --location` so the 500 is visible.

### Recovery options

1. Preferred: wait for an upstream image that resolves the Mautic 7.1.3 / Twig 3.28 return-type incompatibility, pin its immutable digest, and test it on a new database.
2. Controlled fallback: test `mautic/mautic:7.1.2-20260601-apache` in staging. Mautic 7.1.2 is an upstream security release, but it must still pass the installer and security review before use.
3. Do not patch `vendor/` or change the PHP return type inside the running container. Such a patch is untracked, disappears on recreation, and bypasses the release process.

For the candidate image, accept only when all of these pass:

```bash
curl --fail --location --silent --show-error --output /dev/null \
  http://127.0.0.1:4020/

docker inspect --format '{{.State.Health.Status}}' wmc-mautic-web
docker exec wmc-mautic-web php bin/console --version
```

Then complete the installer with a real HTTPS site URL, create a non-admin integration identity, enable the API, and create an OAuth2 client-credentials application. Mautic officially supports `Authorization: Bearer ACCESS_TOKEN` and creates contacts at `POST /api/contacts/new`; see [Mautic API authentication](https://devdocs.mautic.org/en/5.x/rest_api/authentication.html) and [contact endpoints](https://devdocs.mautic.org/en/7.2/rest_api/contacts.html).

The staging contract must verify consent fields, custom UTM/source aliases, tag behavior, duplicate-email handling, audit attribution, token expiry, and deletion. Keep these values false/empty until it passes:

```dotenv
MAUTIC_CREATE_CONTACT_PATH=/api/contacts/new
MAUTIC_CONTRACT_VERIFIED=false
```

## ComfyUI recovery and acceptance

ComfyUI's local server accepts API-format workflows at `POST /prompt`; progress is available through WebSocket or `/history`. The project must not submit until the read-only preflight reports a recognized model, text encoders, and readable VAE. See the official [server routes](https://docs.comfy.org/development/comfyui-server/comms_routes), [workflow explanation](https://docs.comfy.org/development/core-concepts/workflow), and [FLUX examples](https://comfyanonymous.github.io/ComfyUI_examples/flux/).

### Two different running instances

The audit found two independent ComfyUI services:

| Host | Intended use / inventory | Current project relationship |
|---|---|---|
| Nvidia-1 `<NVIDIA1_COMFYUI_ROOT>` | LTX 2.3 checkpoint (29.1 GB), distilled LoRA (7.6 GB), Gemma text encoder (9.4 GB), spatial upscaler; no recorded history | The deployed `18188` proxy pointed here, but the marketing agent did not |
| Nvidia-2 `<NVIDIA2_PRODUCTION_COMFYUI_ROOT>` | Incomplete FLUX.1 Schnell GGUF bundle described below | The marketing agent's `COMFYUI_BASE_URL` pointed here |

This split made the operator URL and backend report different model inventories. The staged proxy requires `MARKETING_COMFYUI_UPSTREAM=<APPROVED_PRIVATE_COMFYUI_HOST>:8188` so both can use the explicitly approved Nvidia-2 target; that correction still needs deployment. Treat Nvidia-1's LTX service as a separate video capability until it has its own explicit integration name and acceptance workflow.

### Audited model inventory

| File | Size | Finding |
|---|---:|---|
| `diffusion_models/flux1-schnell-Q4_0.gguf` | 6,770,707,360 bytes | Present, but no installed loader recognizes GGUF |
| `text_encoders/clip_l.safetensors` | 246,144,152 bytes | Exposed by `DualCLIPLoader` |
| `text_encoders/t5xxl_fp8_e4m3fn.safetensors` | 4,893,934,904 bytes | Exposed by `DualCLIPLoader` |
| `vae/ae.safetensors` | 0 bytes | Invalid placeholder; `/view_metadata/vae` returns HTTP 500 |

Installed package mismatches reported by `/system_stats`:

| Package | Installed | Required by core |
|---|---:|---:|
| `comfyui-frontend-package` | 1.43.17 | 1.45.15 |
| `comfyui-workflow-templates` | 0.9.72 | 0.10.0 |
| `comfyui-embedded-docs` | 0.4.4 | 0.5.4 |
| `comfy-kitchen` | 0.2.8 | 0.2.10 |
| `comfy-aimdo` | 0.3.0 | 0.4.10 |

### Candidate-isolated remediation on Nvidia-2

Do not repair `<NVIDIA2_PRODUCTION_COMFYUI_ROOT>`, install into its Python environment, or
restart `comfyui.service`. Those actions would change the shared production
service. The qualification target is a separate root, environment, model copy,
output directory, process, and loopback port described by
[`flux-schnell-candidate-manifest.json`](../deploy/comfyui/flux-schnell-candidate-manifest.json).

The preferred candidate uses the full FLUX.1-schnell safetensors with
ComfyUI's pinned core `UNETLoader`. It does not install custom nodes. This is
larger than the incomplete Q4 GGUF already on Nvidia-2, but avoids making the
work-in-progress `ComfyUI-GGUF` extension part of the minimum trusted runtime.
The existing GGUF may be evaluated later as a separately pinned optimisation;
it is not an input to this acceptance.

The official FLUX graph order is mandatory: `DualCLIPLoader.clip_name1` loads
`t5xxl_fp8_e4m3fn.safetensors`, while `clip_name2` loads
`clip_l.safetensors`. Reversing these positions is a different, invalid graph
and cannot satisfy the pinned workflow SHA-256
`10a93745478a805b01c36827c9168bc995098fcba460b9dc8fd0dadabe6efe76`.

| Candidate artifact | Bytes | SHA-256 | Pinned source |
|---|---:|---|---|
| `flux1-schnell.safetensors` | 23,782,506,688 | `9403429e0052277ac2a87ad800adece5481eecefd9ed334e1f348723621d2a0a` | `Comfy-Org/flux1-schnell@7d679837b018bfeb28eca55734b335efcd0e7100` |
| `clip_l.safetensors` | 246,144,152 | `660c6f5b1abae9dc498ac2d21e1347d2abdb0cf6c0c0c8576cd796491d9a6cdd` | `comfyanonymous/flux_text_encoders@6af2a98e3f615bdfa612fbd85da93d1ed5f69ef5` |
| `t5xxl_fp8_e4m3fn.safetensors` | 4,893,934,904 | `7d330da4816157540d6bb7838bf63a0f02f573fc48ca4d8de34bb0cbfd514f09` | same pinned text-encoder repository |
| `ae.safetensors` | 335,304,388 | `afc8e28272cd15db3919bacdb6918ce9c1ed22e96cb12c4d5ed0fba823529e38` | Ungated mirror `Comfy-Org/Lumina_Image_2.0_Repackaged@22e393d707f2d13e736b1a461c958644258cd9d9`; byte-identical to official `black-forest-labs/FLUX.1-schnell@741f7c3ce8b383c54771c7003378a50191e9efe9` |

The bundle is 29,257,890,132 bytes (27.25 GiB). Reserve at least 60 GiB so a
temporary download, isolated environment, logs, and output can coexist. The
[official model card](https://huggingface.co/black-forest-labs/FLUX.1-schnell)
identifies FLUX.1-schnell as Apache-2.0. The pinned Comfy-Org mirrors are
currently ungated. The official immutable FLUX.1-schnell metadata at revision
`741f7c3ce8b383c54771c7003378a50191e9efe9` reports the VAE at exactly
335,304,388 bytes with SHA-256
`afc8e28272cd15db3919bacdb6918ce9c1ed22e96cb12c4d5ed0fba823529e38`,
which proves that the mirror file is byte-identical to the Apache-2.0 official
artifact rather than a Lumina-specific VAE. The table records actual
downloaded-file SHA-256 values from immutable source metadata. Hugging Face's
separate Xet CAS hashes are retained only as informational manifest fields and
must never be substituted for file SHA-256. The qualifier independently
streams and hashes every local file before it can pass. Complete the separate
named license review even though no download token is required; the upstream
repository itself is gated and this technical byte-identity check is not a
legal sign-off.

The July 13 read-only check reached Nvidia-2 through Nvidia-1 and reconfirmed
the incomplete shared bundle; it did not download a model, restart a service,
or change a shared file. Before preparing a candidate, repeat the inventory and
capture the current production queue, history, process, and Git state:

```bash
set -euo pipefail
PROD_ROOT="<NVIDIA2_PRODUCTION_COMFYUI_ROOT>"
CAND_ROOT="<NVIDIA2_COMFYUI_CANDIDATE_ROOT>"
NVIDIA_DATA_ROOT="<NVIDIA2_DATA_ROOT>"
CONDA_BIN="<NVIDIA2_CONDA_BIN>"
COMFYUI_BASE_ENV="<NVIDIA2_COMFYUI_BASE_ENV>"
CORE_COMMIT=bd39bbf0678ebd31c972fd365733a8c729f2cd74

test "$CAND_ROOT" != "$PROD_ROOT"
test ! -e "$CAND_ROOT"
available_bytes="$(df --output=avail -B1 "$NVIDIA_DATA_ROOT" | tail -n 1)"
test "$available_bytes" -ge 64424509440

install -d -m 0750 "$CAND_ROOT" "$CAND_ROOT/downloads" \
  "$CAND_ROOT/input" "$CAND_ROOT/output" "$CAND_ROOT/temp"
git clone --filter=blob:none https://github.com/Comfy-Org/ComfyUI.git \
  "$CAND_ROOT/src"
git -C "$CAND_ROOT/src" checkout --detach "$CORE_COMMIT"
test "$(git -C "$CAND_ROOT/src" rev-parse HEAD)" = \
  "$(git -C "$CAND_ROOT/src" rev-parse "$CORE_COMMIT")"

"$CONDA_BIN" create -y -p "$CAND_ROOT/env" \
  --clone "$COMFYUI_BASE_ENV"
PY="$CAND_ROOT/env/bin/python"

"$PY" -m pip install --upgrade --no-deps \
  'comfyui-frontend-package==1.45.15' \
  'comfyui-workflow-templates==0.10.0' \
  'comfyui-embedded-docs==0.5.4' \
  'comfy-kitchen==0.2.10' \
  'comfy-aimdo==0.4.10'
"$PY" -m pip check
"$PY" -c 'import sys, torch; print(sys.version); print(torch.__version__)'
```

The cloned environment is only a hardware-compatible starting snapshot; the
candidate evidence must retain its complete `pip freeze`, Python version, Torch
build, and package-difference report. Stop if Python is not `3.12.13`, Torch is
not `2.11.0+cu130`, or any version differs from the manifest. The five exact
package pins come from the requirements file at the pinned ComfyUI commit.

After license review, use a candidate-local Hugging Face home. The pinned
mirrors are ungated, so these commands contain no token and must not be
rewritten to include one:

```bash
set -euo pipefail
CAND_ROOT="<NVIDIA2_COMFYUI_CANDIDATE_ROOT>"
export HF_HOME="$CAND_ROOT/hf-home"
install -d -m 0700 "$HF_HOME"
HF="$CAND_ROOT/env/bin/hf"
test -x "$HF"

"$HF" download Comfy-Org/flux1-schnell \
  flux1-schnell.safetensors \
  --revision 7d679837b018bfeb28eca55734b335efcd0e7100 \
  --local-dir "$CAND_ROOT/downloads/unet"
"$HF" download comfyanonymous/flux_text_encoders \
  clip_l.safetensors t5xxl_fp8_e4m3fn.safetensors \
  --revision 6af2a98e3f615bdfa612fbd85da93d1ed5f69ef5 \
  --local-dir "$CAND_ROOT/downloads/text"
"$HF" download Comfy-Org/Lumina_Image_2.0_Repackaged \
  split_files/vae/ae.safetensors \
  --revision 22e393d707f2d13e736b1a461c958644258cd9d9 \
  --local-dir "$CAND_ROOT/downloads/vae"

test "$(stat -c %s "$CAND_ROOT/downloads/unet/flux1-schnell.safetensors")" \
  -eq 23782506688
test "$(stat -c %s "$CAND_ROOT/downloads/text/clip_l.safetensors")" \
  -eq 246144152
test "$(stat -c %s "$CAND_ROOT/downloads/text/t5xxl_fp8_e4m3fn.safetensors")" \
  -eq 4893934904
test "$(stat -c %s "$CAND_ROOT/downloads/vae/split_files/vae/ae.safetensors")" \
  -eq 335304388

printf '%s  %s\n' \
  9403429e0052277ac2a87ad800adece5481eecefd9ed334e1f348723621d2a0a \
  "$CAND_ROOT/downloads/unet/flux1-schnell.safetensors" \
  660c6f5b1abae9dc498ac2d21e1347d2abdb0cf6c0c0c8576cd796491d9a6cdd \
  "$CAND_ROOT/downloads/text/clip_l.safetensors" \
  7d330da4816157540d6bb7838bf63a0f02f573fc48ca4d8de34bb0cbfd514f09 \
  "$CAND_ROOT/downloads/text/t5xxl_fp8_e4m3fn.safetensors" \
  afc8e28272cd15db3919bacdb6918ce9c1ed22e96cb12c4d5ed0fba823529e38 \
  "$CAND_ROOT/downloads/vae/split_files/vae/ae.safetensors" | sha256sum -c -

install -d -m 0750 "$CAND_ROOT/src/models/diffusion_models" \
  "$CAND_ROOT/src/models/text_encoders" "$CAND_ROOT/src/models/vae"
mv "$CAND_ROOT/downloads/unet/flux1-schnell.safetensors" \
  "$CAND_ROOT/src/models/diffusion_models/"
mv "$CAND_ROOT/downloads/text/clip_l.safetensors" \
  "$CAND_ROOT/downloads/text/t5xxl_fp8_e4m3fn.safetensors" \
  "$CAND_ROOT/src/models/text_encoders/"
mv "$CAND_ROOT/downloads/vae/split_files/vae/ae.safetensors" \
  "$CAND_ROOT/src/models/vae/"
chmod 0440 "$CAND_ROOT/src/models/diffusion_models/flux1-schnell.safetensors" \
  "$CAND_ROOT/src/models/text_encoders/clip_l.safetensors" \
  "$CAND_ROOT/src/models/text_encoders/t5xxl_fp8_e4m3fn.safetensors" \
  "$CAND_ROOT/src/models/vae/ae.safetensors"
test -z "$(find "$CAND_ROOT/src/models" -type l -print -quit)"
```

Start only the isolated process on loopback; do not use `sudo`, port `8188`, or
the production systemd unit:

```bash
set -euo pipefail
CAND_ROOT="<NVIDIA2_COMFYUI_CANDIDATE_ROOT>"
CAND_PORT=18189
PY="$CAND_ROOT/env/bin/python"

systemd-run --user --collect \
  --unit wamocon-comfyui-candidate-20260710 \
  --property="WorkingDirectory=$CAND_ROOT/src" \
  "$PY" main.py --listen 127.0.0.1 --port "$CAND_PORT" \
  --disable-auto-launch --input-directory "$CAND_ROOT/input" \
  --output-directory "$CAND_ROOT/output" --temp-directory "$CAND_ROOT/temp"

curl --fail --silent "http://127.0.0.1:$CAND_PORT/system_stats" \
  | python3 -m json.tool
curl --fail --silent "http://127.0.0.1:$CAND_PORT/object_info/UNETLoader" \
  | python3 -m json.tool
curl --fail --silent "http://127.0.0.1:$CAND_PORT/object_info/DualCLIPLoader" \
  | python3 -m json.tool
curl --fail --silent \
  "http://127.0.0.1:$CAND_PORT/view_metadata/vae?filename=ae.safetensors" \
  | python3 -m json.tool
curl --fail --silent "http://127.0.0.1:$CAND_PORT/queue" \
  | python3 -m json.tool
```

An empty package list is a failure, not “no mismatches.” `/system_stats` must
report exactly the five nonempty package rows pinned by the full core commit,
and every installed value must equal its required value. All ten core node
schemas, the exact model names, and nonempty VAE metadata must also pass.

Run the repository qualifier from an SSH session on Nvidia-2. It refuses a LAN
or public URL, port `8188`, an unresolved or different candidate root, any
symbolic link in the candidate checkout, a short or wrong Git commit, tracked
source changes, a model byte/hash mismatch, missing package telemetry, an
incompatible node schema, a busy queue, or empty VAE metadata:

```bash
cd /path/to/Marketingmaschine
CAND_ROOT="<NVIDIA2_COMFYUI_CANDIDATE_ROOT>"
python3 scripts/qualify_comfyui_candidate.py \
  --base-url http://127.0.0.1:18189 \
  --candidate-root "$CAND_ROOT/src" \
  --attest-isolated-candidate \
  --preflight-only

python3 scripts/qualify_comfyui_candidate.py \
  --base-url http://127.0.0.1:18189 \
  --candidate-root "$CAND_ROOT/src" \
  --attest-isolated-candidate \
  --evidence-out /secure/operator-evidence/comfyui-technical-qualification.json
```

The submitted job uses the pinned neutral API graph and deterministic seed. Its
history row carries a binding to the full runtime identity and the four locally
observed model hashes. The qualifier accepts only a fresh (maximum 24-hour)
successful history row for its own prompt ID, fetches that exact output through
`/view`, verifies the PNG embeds the exact graph, and records output bytes and
SHA-256 plus start/end timestamps. On timeout or error it sends only targeted
interrupt, queue-delete, and history-delete requests for its own prompt ID; it
never clears a shared queue or history.

Technical evidence deliberately records `release_ready=false` and
`human_visual_approval.approved=false`. A named human must separately inspect
the fetched image and record their decision, timestamp, and evidence reference.
The script has no option that can self-attest this decision. Preserve the
production service commit, process, package snapshot, queue, and history before
and after as additional proof that production was untouched.

Only after this evidence exists should the candidate be bound to Nvidia-2's
private interface on its separate port and allowed through a host firewall from
Nvidia-1. Then set `COMFYUI_BASE_URL=<APPROVED_PRIVATE_COMFYUI_CANDIDATE_URL>` only for the
isolated marketing candidate. Do not change the production default or its
reverse proxy during qualification. Promotion remains blocked until the
technical evidence, separate human approval, network restriction, and rollback
evidence all exist.

### Network requirement

The pre-existing production ComfyUI service still listens on `0.0.0.0:8188`,
and application-level authentication was not demonstrated. The isolated
qualification candidate listened only on `127.0.0.1:18189`; it has not been
promoted or exposed to Nvidia-1. Any later candidate access must use the
private Nvidia interface plus host firewall rules that allow only Nvidia-1 and
named operator addresses. Keep the existing Nvidia-1 reverse-proxy allowlist
and add HTTPS/authentication before giving general LAN users access.

## Release gate summary

| Gate | Postiz | Twenty | Mautic | ComfyUI |
|---|---|---|---|---|
| Pinned runtime | Local compose fixed | Local compose fixed | Reproducible broken digest only; repaired candidate required | Full core commit, exact five-package set, four model files, bytes, and hashes technically verified on the isolated candidate |
| Truthful health | Local health check added, not deployed | Passes `/healthz` | Local redirect-following check added, not deployed | Missing/empty package telemetry, node-schema drift, incomplete model bundle, stale history, or unverified output now fails closed |
| Scoped auth | Missing | Missing | Installation/API client missing | Network restriction missing |
| Exact contract | Provider mapping missing; media byte verification implemented but not provider-qualified | Workspace mapping missing | Custom fields/consent mapping missing | Pinned neutral API graph executed and output bound to graph/runtime/model identities; human and licence approval remain separate |
| Reversible staging test | Missing | Missing | Missing | Strict isolated technical generation passed; promotion/rollback and named approval remain open |
| Production write enabled | No | No | No | No queue submission |

None of the four integrations is ready for unattended production writes. This is expected and enforced by configuration. Their next valid milestone is a reversible staging acceptance with evidence, not enabling all services at once.
