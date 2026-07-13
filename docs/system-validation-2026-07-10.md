# System Validation - 10 July 2026

This is an evidence record for the 10 July hardening work. It separates the
unchanged production installation from the isolated release candidate. It is
not a production-cutover record and it is not evidence that an external
provider integration is ready for live writes.

## Release decision

The hardened release candidate is **not deployed to production**. The existing
production console and n8n installation remain unchanged until an approved
maintenance window. The candidate may be used for isolated validation only.

## Deployment state at the end of validation

| Scope | Address | Demonstrated state |
| --- | --- | --- |
| Existing production console | `http://192.168.178.75:18117/ui` | Last verified as the older restricted-LAN HTTP release with `GET /session` returning `404`. Nvidia-1 later became unreachable, so its current state cannot be re-attested. |
| Existing production n8n | `http://192.168.178.75:15678` | Last verified as the unchanged single-container installation. The versioned workflow release was not imported or published; Nvidia-1 later became unreachable. |
| Nvidia-1 candidate | host loopback `http://127.0.0.1:18118` | Last verified healthy, isolated, and backed by `wamocon_marketing_candidate_validation_data`, with candidate/disposable runtime attestation. The host later disappeared from mDNS/router DNS and stopped answering its documented IP, so this is not a current-health claim. |
| Candidate dependency routes | private Docker/LAN routes | Local Qwen and SearxNG were exercised successfully. Reachability of another service is recorded separately from successful use. |

Production ports `:18117` and `:15678` must not be described as HTTPS or as
running the hardened candidate until the maintenance acceptance checks below
have passed. The candidate's `:18118` port is bound to loopback and is not a
new operator-facing production URL.

## Candidate behavior demonstrated

### Five canonical campaigns and local AI drafts

The candidate exposes only the five canonical campaigns, K1 through K5. Its
weekly-planning flow created one structured draft for each campaign using the
local OpenAI-compatible Qwen route:

| Campaign | Model evidence | Candidate outcome |
| --- | --- | --- |
| K1 | `local_qwen`, `qwen3.6:35b`, one attempt, 6,128 ms | AI-generated draft |
| K2 | `local_qwen`, `qwen3.6:35b`, one attempt, 6,887 ms | AI-generated draft |
| K3 | `local_qwen`, `qwen3.6:35b`, one attempt, 7,989 ms | AI-generated draft with deterministic structure completion recorded |
| K4 | `local_qwen`, `qwen3.6:35b`, two attempts, 16,209 ms | AI-generated draft after semantic repair; held as `needs_evidence` |
| K5 | `local_qwen`, `qwen3.6:35b`, two attempts, 19,840 ms | AI-generated draft after semantic repair |

All five records report `fallback_used=false` and retain JSON-schema
generation provenance. These are candidate drafts, not production approvals,
scheduled posts, or published content.

### Latest public-source research

Candidate research run `trend-request-291010b724f2cfe8` exercised SearxNG for
all five campaigns. It completed five external source calls without an adapter
error and stored ten citations. The final status is
`needs_source_verification`: zero trends met the exact-topic requirement for
two independent domains plus a recent dated source.

The correct outcome is therefore a visible editorial block. Ten stored links
do not by themselves make a trend eligible, and trend-based AI continuation
must remain unavailable until the evidence gate passes.

### Governance and operator flows

The isolated candidate demonstrated the following repository behavior:

- exactly K1-K5 in normal campaign views, with demo/mock/smoke records hidden;
- structured Reel idea, format, hook, script, shot list, edit direction,
  caption, CTA, and source references;
- named human review, revision history, idempotent/CAS lifecycle protection,
  and terminal-state protection;
- media evidence registration, replacement, revocation, and publish gating for
  an Instagram Reel;
- provider outbox and read-only reconciliation without blind resend after an
  ambiguous result;
- evidence-bearing analytics entry and append-only correction history; and
- consent-aware lead handling, retention discovery, and privacy-safe audit
  reasons.

External provider writes were and remain disabled in the candidate. No
candidate test is evidence of a Postiz, Twenty, Mautic, social-platform, or CRM
production write.

## Recorded automated and visual evidence

The following results were recorded during the hardening run. They are stated
with their scope so an earlier full run is not mistaken for a final cutover
test:

| Check | Recorded result | Scope note |
| --- | --- | --- |
| Windows unit suite | 280 tests collected: 279 passed, 1 expected skip | Final full run after the release-acceptance, ComfyUI compatibility, and private Firecrawl changes; the skipped check is POSIX mode-bit specific and is exercised in Linux. |
| Targeted runtime-packaging checks | 20 passed | Completed after the entrypoint adjustment. |
| Linux image unit suite | 280 tests run, 2 expected skips | Final full run in rebuilt image `sha256:8b22d120c6e9882261c501cb95769a7bf8241a086a844ad040b2973394533c39`; the image intentionally contains no Node runtime. |
| Linux storage checks | 4 passed | Explicitly included POSIX ownership and permission behavior. |
| Project-image Python dependencies | `pip check` passed | This does not claim that the host's unrelated global Python environment is conflict-free. |
| JavaScript dependencies | `npm audit` reported 0 vulnerabilities | Repository dependency audit only. |
| Repository configuration | 12/12 Compose renders, 31/31 JSON files, 4/4 JavaScript files, and 3/3 shell scripts passed validation | Includes both n8n release layers, candidate overlays, network edge, observability, and growth-tool profiles. |
| Remote browser flow | Playwright journey passed through an SSH tunnel to the last-verified Nvidia-1 candidate on `:18118` | Earlier candidate dashboard, approval, media, analytics, and mobile evidence; not a current-health claim and not production `:18117`. |
| Final local browser flow | Authenticated Playwright journey passed against the rebuilt disposable candidate on `http://127.0.0.1:18118`; all five current captures were regenerated and manually inspected | Exactly five campaign cards, truthful degraded-service states, review/media badge parity, Reel-video handoff blocking, blank human-review inputs, source/provenance presentation, mobile overflow, API responses, request failures, and browser console errors were checked. The smoke actor was edge-attested as `qa.candidate`; no external writes were enabled. |
| Strict integration smoke | Blocked | The required ComfyUI generation-readiness gate remains false. Package mismatches now explicitly keep readiness false even when the service and model files are reachable. |

The last-verified ARM64 Nvidia candidate image was
`sha256:1c7a6dc51bc958705f0377e9ffeb9d74ca71af82b240eab773cad349768c130f`.
It predates the latest local safety changes and cannot be called the final
candidate while Nvidia-1 is offline. Image IDs are architecture-specific, so
an eventual rebuilt ARM64 ID will differ from the local Docker Desktop image
ID above. Rerun both suites if later executable or packaging files change.

Browser artifacts generated by the candidate validation are stored locally in
the git-ignored `qa_output/` directory:

- `final_dashboard_desktop.png`
- `final_content_studio_desktop.png`
- `final_approval_desktop.png`
- `final_setup_desktop.png`
- `final_dashboard_mobile.png`
- `final_reel_media_gate_desktop.png`
- `final_reel_media_ready_desktop.png`
- `final_reel_media_revoked_desktop.png`
- `final_reel_media_gate_mobile.png`
- `final_analytics_evidence_desktop.png`
- `final_analytics_correction_desktop.png`

These files are release-run artifacts rather than application assets. Their
presence does not prove that the same UI is deployed on production.

## Versioned n8n release versus live n8n

The repository contains eight publishable workflows:

| Purpose | Stable ID |
| --- | --- |
| Manual content intake | `lYfpV4r4oeEzPtuO` |
| Integration health | `Psaft2cYujD42MAs` |
| Weekly planning | `GqGVw06F64o7rvjI` |
| Verified trend research | `WMCTrendResearch01` |
| 72-hour analytics due discovery | `eTZSmmzKe6dJ1knR` |
| 7-day analytics due discovery | `WMCAnalytics7d01` |
| 14-day analytics due discovery | `WMCAnalytics14d1` |
| 30-day analytics due discovery | `WMCAnalytics30d1` |

The retired human-approval workflow `5OzpL9oBMR8gpSJA` is a zero-node inactive
tombstone in version control. `WMCLeadRetention01` is also staged inactive and
is not one of the eight publishable workflows. JSON `active` flags are release
intent only; they do not prove the current live n8n state. Live activation must
be verified after import, credential binding, explicit publication, and n8n
restart in the maintenance window.

## Backup and rollback evidence

A pre-change production backup is stored on Nvidia-1 at:

```text
/home/wamocon/lokal-ai/data/n8n-files/wamocon-marketing-machine/backups/production-hardening/20260710T115858Z
```

The recorded backup is approximately 936 MiB and includes checksum evidence,
n8n workflows/credentials/configuration/encryption material, SQLite database
files and execution data, plus Postiz, Temporal, Twenty, and Mautic
database/configuration material. Operators must verify the checksum manifest
and that the decryption material is recoverable before using this as rollback
evidence. Backup existence is not a restore test.

## Known blockers and incomplete integrations

| Capability | Candidate evidence | Required next proof |
| --- | --- | --- |
| ComfyUI generation | Last service route was reachable, but strict readiness was false. The shared bundle had no recognised complete model/validated VAE and reported package mismatches; readiness now fails closed on either condition. | Use the pinned candidate-only FLUX manifest at `deploy/comfyui/flux-schnell-candidate-manifest.json`, qualify it on loopback `:18189`, and rerun strict smoke without altering shared production assets. |
| Firecrawl | Cloud adapter and explicit private self-hosted/no-auth mode are implemented; no cloud key or currently reachable self-hosted Nvidia service is verified. | Provision a scoped cloud key or verify a private candidate service, execute a bounded real search, and retain successful-use evidence. |
| Postiz | Provider route may be reachable; tenant key, integration IDs, and exact contract are not release-qualified. | Validate a synthetic draft in non-production and retain request, response, tenant, version, cleanup, and idempotency evidence. |
| Twenty and Mautic | Credentials/contracts are not configured for this release; external writes are disabled. | Complete each product's isolated acceptance before enabling any write. |
| Social analytics | Evidence-aware manual entry and due discovery exist; platform metrics are not automatically ingested. | Compare authenticated provider imports with platform reports before automating decisions. |
| Prometheus and Grafana | Versioned configuration exists, but the shared services were stopped/unreachable during candidate validation. | Restore through the owning infrastructure release and prove authenticated metrics/dashboard use. |
| n8n durability | Production remains the existing single-container installation. Postgres/Redis queue-mode files are staged only. | Perform the database migration and queue-mode release in separate approved windows with recovery tests. |
| TLS and named operator identity | Versioned proxy configuration contains TLS, Basic Auth, actor attestation, and anti-clickjacking headers. Production was last verified on the older HTTP edge with `/session` returning `404`; the host is now unreachable. | Restore connectivity, then deploy and verify every maintenance acceptance check below. |
| Nvidia connectivity | After candidate/browser validation, Nvidia-1, Nvidia-2, and Nvidia-3 aliases stopped resolving; Nvidia-1's documented IP no longer answers TCP/22 or service ports. | Restore host power/network/DNS through the infrastructure owner, then re-audit all runtime state before any upload, restart, or cutover. |

## Mandatory maintenance acceptance checks

Do not mark the hardened release live until one named primary operator and one
secondary operator record all of these checks in the change record:

1. Verify the backup checksum manifest and identify the exact rollback image,
   configuration, data path, n8n export, encryption material, and rollback
   owner.
2. Record the digest of the exact candidate image and rerun the full release
   test suites against that artifact.
3. Prove a trusted TLS handshake on the authorised-workstation endpoints for
   both the console (`:18117`) and n8n (`:15678`). A bypassed certificate
   warning is a failure.
4. Prove that plaintext HTTP no longer serves the console or n8n. It may be
   refused or return only a safe redirect to HTTPS; it must never expose a
   usable UI, API response, credential prompt, or session over plaintext.
5. Through the TLS edge, verify `GET /session` returns the authenticated named
   operator and verify `/readyz` reports ready with safe mutation and actor
   authentication. A free-text browser actor is not acceptable evidence.
6. Verify console responses include both
   `Content-Security-Policy: frame-ancestors 'none'` and
   `X-Frame-Options: DENY`.
7. In live n8n, prove each of the eight stable IDs above is active exactly once
   and prove retired approval workflow `5OzpL9oBMR8gpSJA` is inactive. Also
   confirm `WMCLeadRetention01` remains inactive unless it has its own approved
   release.
8. Run the read-only production smoke and verify exactly five campaigns, no
   demo/mock/smoke records, successful local-Qwen provenance, truthful source
   status, and no mutation without valid edge credentials.
9. Confirm `MARKETING_MACHINE_ENABLE_EXTERNAL_WRITES=false` and that no
   Postiz, Twenty, Mautic, or social-provider write occurred during cutover.
10. Exercise or formally rehearse rollback, including restoration of the old
    agent/proxy and n8n workflow export, then recheck the service and active
    workflow list. Stop and roll back on any failed gate.

Use the [Nvidia-1 deployment runbook](remote-project-runbook.md) for the
procedural commands. Keep the n8n Postgres migration, Redis queue-mode change,
ComfyUI qualification, and external provider-write qualification as separate
releases rather than expanding this cutover.

## Governing interpretation

"Reachable", "configured", "successfully used", "release-qualified", and
"deployed to production" are different states. This record claims only the
state for which evidence is listed. AI may research and draft; a named human
must decide what may leave the system.
