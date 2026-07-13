# Growth Tools

The marketing machine can connect to Postiz, Twenty, and Mautic, but these are intentionally deployed as optional profiles.

For the audited versions, exact API routes, backup commands, staging gates, and ComfyUI recovery procedure, use [Growth and Creative Integration Acceptance](growth-creative-integration-acceptance.md).

Reason: the NVIDIA host is already running a large local-AI stack. Postiz adds Temporal and Elasticsearch; Twenty adds a worker plus Postgres/Redis; Mautic adds MySQL, web, cron, and worker containers. Start one profile at a time and verify memory before enabling the next one.

## Profiles

- `postiz`: social scheduling candidate, exposed at `http://127.0.0.1:4007`.
- `twenty`: CRM candidate, exposed at `http://127.0.0.1:4019`.
- `mautic`: marketing automation candidate, exposed at `http://127.0.0.1:4020`.

These loopback addresses are health/debug bindings on the host, not operator
URLs. The canonical browser and callback URLs in the private environment file
must use the approved HTTPS edge. Postiz frontend/API URLs must use the same
authority, and Twenty's `SERVER_URL` and Mautic's site URL must also be HTTPS.

## Start One Tool

Create a private env file from `deploy/growth-tools.env.example`, fill generated
secrets, and run the fail-closed preflight before rendering or starting one
profile. The preflight reports variable names only; it never prints values.

```bash
python scripts/validate_growth_env.py \
  --env-file deploy/growth-tools.generated.env --profile twenty
docker compose --env-file deploy/growth-tools.generated.env \
  -f deploy/docker-compose.growth-tools.yml --profile twenty config -q
docker compose --env-file deploy/growth-tools.generated.env \
  -f deploy/docker-compose.growth-tools.yml --profile twenty up -d
```

Use the same pattern for `postiz` or `mautic`.

The validator also rejects credentials or database names that cannot be
embedded safely in the internal connection URI. Generate URL-safe values; do
not percent-encode a value in one place and use a different raw value in
another.

## Verify

```bash
python3 scripts/smoke_api.py \
  --base-url http://127.0.0.1:8117 \
  --access-token-file deploy/secrets/marketing_mutation_token
```

The marketing agent reports Postiz, Twenty, and Mautic as optional integrations.
Core readiness depends on n8n, the local Qwen model, and exact successful
ComfyUI qualification evidence. A reachable ComfyUI process or recognized model
bundle is not enough. Production creative readiness additionally requires the
separate named visual and licence decisions bound to the qualified output,
prompt, workflow, runtime, and model-file identities.

## Guardrails

- Do not connect social accounts until legal/business approval is clear.
- Keep public app ports behind reverse proxy/auth before external exposure.
- Keep each product database and cache on its own internal Docker network. Only
  the product frontend may also join the shared application network; the
  marketing edge must not have a route to Postgres, Redis, MySQL, Temporal, or
  Elasticsearch.
- Keep registration disabled after setup unless a controlled onboarding process exists.
- Store generated secrets only in private host env files, not in Git.
- Keep AI publishing gated by human approval; these apps are schedulers/CRMs, not autonomous publishers.
- For a Postiz-backed video or image, register the exact provider path and
  select the matching local original. The agent verifies the provider bytes
  on registration and again immediately before a draft handoff. A changed,
  redirected, unreachable, wrong-type, or mismatched asset blocks safely.
