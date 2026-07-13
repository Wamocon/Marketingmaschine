# Deployment stack (deprecated entry point)

Do not deploy `deploy/docker-compose.core.yml`. It is a legacy development
scaffold with public database/Redis ports, placeholder credentials, floating
images, and a second n8n stack; it is not a production path.

Use these maintained runbooks instead:

- [`remote-project-runbook.md`](remote-project-runbook.md) for the existing
  NVIDIA machine, marketing application, protected access, and validation.
- [`../deploy/n8n/README-hardening.md`](../deploy/n8n/README-hardening.md) for
  the staged n8n SQLite-to-Postgres migration and later queue-mode release.

The production invariant is one `core-n8n` control plane, pinned images,
private Postgres/Redis networks, explicit secrets, protected canonical URLs,
and a reversible migration with the original SQLite volume retained.
