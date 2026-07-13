# Network Access

This page describes the **staged TLS target**. The unchanged live proxy was last
observed answering over restricted-LAN HTTP without the authenticated `/session`
contract. Nvidia-1 was not reachable at the final office-network check, so this
is historical evidence rather than current health. Do not treat the
configuration below as deployed proof; verify TLS, named login, clickjacking
headers, `/session`, and HTTP shutdown during the maintenance-window acceptance
test.

The default deployment binds business tools to `127.0.0.1` on the NVIDIA host. This is intentional: the agent API, CRM, scheduler, and automation tools should not be exposed directly with database and queue services.

Use `deploy/docker-compose.network-access.yml` when LAN access is needed. It starts one nginx proxy and exposes only browser/API entry points:

| Tool | LAN URL pattern |
| --- | --- |
| Marketing agent API | `https://<host-name>:18117` |
| n8n | `https://<host-name>:15678` |
| Postiz | `https://<host-name>:14007` |
| Twenty CRM | `https://<host-name>:14019` |
| Mautic | `https://<host-name>:14020` |
| ComfyUI | `https://<host-name>:18188` |
| Grafana | `https://<host-name>:13030` |

The proxy has a private-network backstop and every exposed operator port is
further restricted to the explicitly approved addresses or CIDRs supplied at
runtime through `MARKETING_MACHINE_ALLOWED_CLIENT_CIDRS`. The repository does
not embed a DHCP-derived workstation address. Update the protected environment
value when an authorised workstation address changes. The marketing dashboard additionally
requires a named HTTP Basic account over TLS. The proxy records
that authenticated username and overwrites `X-WAMOCON-Actor`. It also injects
an independent edge attestation known only to nginx and the agent, so browser
code cannot choose or forge its authenticated identity.

Credentials, platform sessions, and API keys must never cross plaintext HTTP.
The staged proxy therefore enables TLS on every LAN-facing operator port
(Marketing, n8n, Postiz, Twenty, Mautic, ComfyUI, and Grafana) and
refuses to start without a certificate and private key at
`deploy/secrets/marketing_tls_certificate.pem` and
`deploy/secrets/marketing_tls_private_key.pem`. Issue them from the company or
LAN CA for the actual dashboard hostname, install that CA on the two operator
workstations, and access the dashboard with `https://`. Do not bypass a browser
certificate warning for production.

Before validating or starting the edge, set the exact comma-separated LAN
authorities operators will use. Each entry is a hostname or IPv4 address only:
no scheme, port, path, regex, or wildcard. The edge refuses to start when the
list is missing or malformed, and returns `421` for every unlisted `Host`.
Include every hostname/IP covered by the certificate that is intentionally in
use; do not add aliases merely to make a failed request pass.

Set the external authorities, approved client addresses/CIDRs, and exact private
ComfyUI upstream in the protected generated environment file. Angle-bracket
values below are placeholders and must never be used literally:

```dotenv
MARKETING_MACHINE_ALLOWED_HOSTS=<TLS_HOSTNAME>,<LAN_IP>
MARKETING_MACHINE_ALLOWED_CLIENT_CIDRS=<APPROVED_IPV4_OR_CIDR>[,<APPROVED_IPV4_OR_CIDR>...]
MARKETING_COMFYUI_UPSTREAM=<APPROVED_PRIVATE_COMFYUI_HOST>:<PORT>
```

```bash
docker compose --env-file deploy/marketing-agent.generated.env \
  -f deploy/docker-compose.network-access.yml config --quiet
```

The proxy entrypoint rejects missing, malformed, duplicate, loopback, or empty
client entries and refuses an upstream that is not an exact private hostname or
IPv4 address plus port. It renders these values into a temporary runtime nginx
configuration; they are not committed to Git.

The agent separately accepts only loopback, its private Docker service name,
and exact values in `MARKETING_MACHINE_ALLOWED_HOSTS`. nginx deliberately sends
`Host: wmc-marketing-agent` upstream after validating the external host. This
keeps internal health checks and n8n automation working without allowing an
arbitrary browser-supplied authority through to FastAPI.

Create exactly one account per authorised person. Do not share passwords. The
file is a private Docker secret and must contain at least two distinct bcrypt
or SHA-512-crypt accounts before the proxy will start:

```bash
install -d -m 0700 deploy/secrets
umask 077
read -rsp 'Password for marketing-operator-1: ' password; echo
hash="$(printf '%s' "$password" | openssl passwd -6 -stdin)"
printf 'marketing-operator-1:%s\n' "$hash" \
  > deploy/secrets/marketing_operator_htpasswd
unset password hash
read -rsp 'Password for marketing-operator-2: ' password; echo
hash="$(printf '%s' "$password" | openssl passwd -6 -stdin)"
printf 'marketing-operator-2:%s\n' "$hash" \
  >> deploy/secrets/marketing_operator_htpasswd
unset password hash
chmod 0600 deploy/secrets/marketing_operator_htpasswd
```

The marketing API is fail-closed for state changes. Generate one 32-byte random
hexadecimal token and store it in `deploy/secrets/marketing_mutation_token`
(mode `0600` on the host). The same Docker secret is mounted read-only into the
agent and the access proxy. nginx injects it only on the upstream request, so it
never appears in browser JavaScript, local storage, URLs, or screenshots:

```bash
install -d -m 0700 deploy/secrets
umask 077
openssl rand -hex 32 > deploy/secrets/marketing_mutation_token
openssl rand -hex 32 > deploy/secrets/marketing_edge_attestation
test "$(cat deploy/secrets/marketing_mutation_token)" != \
  "$(cat deploy/secrets/marketing_edge_attestation)"
chmod 0600 deploy/secrets/marketing_mutation_token \
  deploy/secrets/marketing_edge_attestation
```

The second secret is mounted only into nginx and the agent. nginx overwrites
`X-WAMOCON-Edge-Attestation` together with `X-WAMOCON-Actor`; never give that
secret to n8n, an operator, browser code, or a smoke-test command. Protected
`GET /session` returns the verified account name but never returns either
secret.

nginx also overwrites the one-hop `X-Forwarded-For` value instead of appending
caller input. The agent starts Uvicorn with generic proxy-header handling
disabled and applies `X-Forwarded-For`, `X-Forwarded-Host`, and
`X-Forwarded-Proto` only when the independent edge attestation and named account
are valid. There is intentionally no `X-Forwarded-Port`: the validated original
`Host` already includes an external port when one was actually supplied, while
the container listener port is not the public port.

Dynamic console and API responses return `Cache-Control: no-store`; static
console assets are the only cacheable surface. Production and isolated
candidate instances return `404` for `/docs`, `/redoc`, and `/openapi.json`.
Framework documentation is available only in an explicit `development` or
`test` instance with `MARKETING_MACHINE_ENABLE_TECHNICAL_DOCS=true`. The
production console CSP allows same-origin scripts and connections only. Inline
scripts and `eval` remain blocked; inline styles are temporarily allowed because
the current UI sets progress widths and campaign accent colours as style
attributes. The unused browser capabilities in `Permissions-Policy` remain
disabled.

Do not add a literal mutation token to browser code, container environment, or
a committed n8n workflow. Agent-facing n8n HTTP nodes use the encrypted Header
Auth credential named `WAMOCON Agent Access Token`; the two inbound
Webhook nodes use the separate encrypted credential named
`WAMOCON Inbound Webhook Token`. Versioned JSON contains names only. After every
import, a trusted operator must explicitly bind the local credential IDs and
keep the workflows unpublished while any credential is unresolved.

The former n8n human-approval webhook is a disabled, node-free tombstone. A
shared webhook token proves a service request, not which person approved
content. Human approval is accepted only through the authenticated console. A
manual `confirmed_not_created` reconciliation is applied only after two
different signed-in accounts submit the same evidence in separate requests;
two free-text names in one request never satisfy that control.

Do not replace these credentials with expressions such as
`$env.MARKETING_MACHINE_MUTATION_TOKEN` or `$env.MARKETING_MACHINE_N8N_WEBHOOK_TOKEN`.
Secrets belong in Docker secrets for the agent/proxy and encrypted, named n8n
credentials for workflow nodes. The inbound token must be independently
generated; it is not the agent mutation token. Unauthenticated production
webhooks must return `401` before the workflow body executes.

Verify the TLS proxy interactively with a named browser account. For the
repeatable host-side deployment smoke, use the raw loopback API and supply a
secret *file path* or the
`MARKETING_MACHINE_MUTATION_TOKEN` process environment variable. The scripts do
not accept a token value as a CLI argument and do not print it:

```bash
python3 scripts/smoke_api.py \
  --base-url http://127.0.0.1:8117 \
  --access-token-file deploy/secrets/marketing_mutation_token
```

Generic mutating n8n smoke is retired because it cannot independently prove a
disposable n8n target. Use only the explicit change-window verification in the
remote runbook; never combine a candidate agent with production n8n.

n8n is proxied directly over the private `core-net` Docker network. Its host port
must remain loopback-only (`127.0.0.1:5678`) so webhooks cannot bypass this
operator allowlist.

Start it on the NVIDIA host:

```bash
docker compose --env-file deploy/marketing-agent.generated.env \
  -f deploy/docker-compose.network-access.yml up -d
```

The hardened proxy and credential changes remain staged until an approved
maintenance window. Do not recreate the production proxy or agent, publish imported workflows, or
enable an external write flag outside an approved maintenance window. Validate
the compose configuration and candidate image now; deploy and verify one layer
at a time in the next change window with the documented rollback available.

Keep these services behind VPN or LAN firewall. Do not expose them directly to the public internet without HTTPS, SSO/basic auth, platform credentials review, and rate limiting.
