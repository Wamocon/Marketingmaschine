# Hardened shared observability

This directory is a reviewed replacement for the stopped NVIDIA host stack in
`/home/wamocon/shared-infra`. It intentionally does not start Redis or Loki in
the default monitoring path.

## Safety properties

- Prometheus and Grafana bind to `127.0.0.1`, not every host interface.
- Prometheus 3.13.0 LTS and Grafana 13.1.0 are pinned by immutable digest.
- Grafana anonymous access and user registration are disabled.
- Prometheus has explicit 30-day and 20 GB retention limits.
- Services restart after host reboot and expose Docker health checks.
- The marketing metrics contain counts and status labels only, never prompts,
  captions, citations, source URLs, personal data, or credential values.
- Shared Redis lives in the separate `docker-compose.optional-cache.yml`, is
  password-protected by a Docker secret, and has no host port. Its secret is
  never interpolated into the monitoring Compose model or Redis process
  arguments. n8n must use a separate Redis on its own private network.
- Loki remains opt-in until its deprecated storage schema is migrated and
  Grafana Alloy is configured for container logs.

## Maintenance-window rollout

1. Back up the four existing named volumes and the complete shared-infra folder.
2. Clone the Prometheus and Grafana volumes. Point `.env` only at the clones;
   major-version startup can migrate data and must never touch rollback volumes.
3. Copy these files into a new staging folder beside the existing deployment.
4. Create a private `.env` with the cloned volume names and a new Grafana
   password. Do not commit it. The env value does **not** rotate an existing
   Grafana database; use the CLI step below on the stopped clone.
5. Validate the rendered definition and both configuration files.
6. Start only Prometheus, then Grafana. Do not use an unscoped `up -d` command.
7. Verify Prometheus can scrape `wmc-marketing-agent:8080/metrics` and that the
   dashboard reports exactly five configured campaigns.
8. Add the same two-operator restriction used by the marketing nginx proxy
   before offering Grafana on the LAN or through Cloudflare Access.

Clone the stopped volumes without changing either original:

```bash
for service in prometheus grafana; do
  source="shared-infra_shared-${service}-data"
  clone="shared-infra-stage_shared-${service}-data"
  docker volume create "$clone"
  docker run --rm --user 0:0 \
    -v "$source:/source:ro" -v "$clone:/clone" \
    alpine@sha256:5b10f432ef3da1b8d4c7eb6c487f2f5a8f096bc91145e68878dd4a5019afde11 \
    sh -ec 'cp -a /source/. /clone/'
done
```

Reset the admin password in the cloned Grafana database while the service is
stopped, then verify the new credential after startup. `GF_SECURITY_ADMIN_PASSWORD`
alone only seeds a new database and cannot rotate an existing one.

```bash
read -rsp 'New staged Grafana admin password: ' GRAFANA_NEW_PASSWORD; echo
docker compose --env-file .env -f docker-compose.hardened.yml run --rm --no-deps \
  shared-grafana grafana cli admin reset-admin-password "$GRAFANA_NEW_PASSWORD"
docker compose --env-file .env -f docker-compose.hardened.yml up -d shared-grafana
curl --fail --user "$GRAFANA_ADMIN_USER:$GRAFANA_NEW_PASSWORD" \
  http://127.0.0.1:3030/api/user >/dev/null
unset GRAFANA_NEW_PASSWORD
```

```bash
docker compose -f docker-compose.hardened.yml config -q
docker run --rm --entrypoint promtool \
  -v "$PWD/prometheus.yml:/etc/prometheus/prometheus.yml:ro" \
  -v "$PWD/rules:/etc/prometheus/rules:ro" \
  prom/prometheus:v3.13.0@sha256:c6b27ea434f8389bfe233fbc7be381cf50587c286e871bc842008f5a1b1908a7 \
  check config /etc/prometheus/prometheus.yml
docker compose -f docker-compose.hardened.yml up -d shared-prometheus
docker compose -f docker-compose.hardened.yml up -d shared-grafana
```

If a separately approved workload genuinely needs the optional shared cache,
create a private 64-hex secret file and validate/start its isolated definition:

```bash
umask 077
openssl rand -hex 32 > /run/secrets/wamocon-shared-redis
cp .env.optional-cache.example .env.optional-cache
docker compose --env-file .env.optional-cache \
  -f docker-compose.optional-cache.yml config -q
docker compose --env-file .env.optional-cache \
  -f docker-compose.optional-cache.yml up -d shared-redis
```

Rollback by stopping these two services and starting the saved original compose
definition. Named volumes are preserved and deliberately use their existing
names.
