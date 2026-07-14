# System Validation — 14 July 2026

> **Overall result: RED / NO-GO.** Nvidia-1 is reachable again, but reachability
> is not production readiness. Do not cut over the hardened release, enable
> external writes, or represent a push or merge to `main` as release-ready.

## Document control and evidence boundary

| Field | Value |
| --- | --- |
| Validation date | 14 July 2026 (Europe/Berlin) |
| Environment observed | Nvidia-1 through its protected SSH identity; concrete hostname and private address intentionally omitted from this public record |
| Method | Fresh read-only SSH, Docker, HTTP, workflow, application-data, dependency, backup, repository, isolated-AI, desktop/mobile, and accessibility checks |
| Release decision | **NO-GO for production cutover and release-ready `main` publication** |
| External provider writes | Disabled; must remain `false` |
| Governing principle | Reachable, configured, successfully used, release-qualified, and deployed are different states |

This record supersedes the 13 July record only for current operational state.
The older records remain timestamped evidence and must not be rewritten as if
their observations occurred on 14 July. No remote production mutation was
performed during this validation.

## Executive decision

| Decision area | Result | Fresh evidence |
| --- | --- | --- |
| Nvidia-1 connectivity | GREEN for reachability only | Strict-host-key SSH succeeds, Docker is healthy, and host capacity is ample. This is not an application release gate. |
| Production console and identity | **RED** | The operator endpoint still serves plaintext HTTP; HTTPS fails, `/session` returns 404, required security headers are absent, and certificate, key, named-account, and acceptance-credential files are absent. |
| Production artifact | **RED** | Production still uses the older `sha256:a5442c…` image. The older `sha256:1c7a6d…` candidate remains present, while the final release archive, image, and commit are absent. |
| n8n | **RED / critical** | Live n8n drifted to 2.29.11 on a mutable image. The LAN edge returns 502, the workflow manifest is non-compliant, and five webhook paths are unprotected. |
| Five-campaign data | AMBER | Production contains exactly K1–K5, eleven non-demo content states, and five 13 July drafts with local-Qwen provenance. They use the older schema and are not approvals, publications, or proof of the final candidate. |
| Current AI acceptance | **RED** | The initial isolated three-round run did not produce five releasable AI results: K1 and K2 failed safe to blocked deterministic fallbacks; K3 and K4 produced actual local-Qwen drafts that passed deterministic quality; K5 used actual local Qwen but was blocked on audience relevance. Later controlled reruns produced additional passing individual results, but also exposed a Qwen transport timeout and an unsafe rhetorical data-protection question. The local guard was extended, but the exact final source has no completed fresh all-five, three-round hardware acceptance. |
| Current research acceptance | **RED** | Qwen inference and a real SearxNG JSON search succeed now, but the production trend store contains only stale, blocked evidence and no eligible K1–K5 current-trend decision. |
| Creative path | **RED** | The production ComfyUI endpoint responds, but model metadata returns HTTP 500. The earlier isolated FLUX result still lacks the distinct named visual and licence approvals required for release. |
| Growth tools | **RED** | Postiz, Twenty, and Mautic are reachable only as unqualified dependencies; their identity, credential, tenant, contract, installation, or immutable-version gates remain open. |
| Backup and restore | **RED** | The latest verified backup is from 10 July, predates the current drafts, and has no completed restore rehearsal. |
| Observability | **RED** | Prometheus and Grafana remain stopped. |
| Repository governance | **RED** | Public `main` has no enforced branch-protection ruleset, required CI, or named review gate. |
| Production cutover | **NO-GO** | Mandatory security, workflow, dependency, evidence, backup, and governance gates remain open. |

## Fresh live inventory

### Host, agent, and operator edge

- Nvidia-1 is reachable again through the protected SSH identity. The previous
  connectivity incident is closed only as a reachability observation.
- Production and candidate external writes remain disabled.
- The live marketing console still answers without the staged TLS and identity
  contract. Unauthenticated `/ui` access succeeds, `/session` is absent, HTTPS
  does not establish, and the required anti-clickjacking and transport-security
  headers are not present.
- The release certificate, private key, htpasswd file, read-only n8n API key,
  and the two protected acceptance-credential files are not installed.

### n8n

- Live n8n reports 2.29.11. Its image identity begins `sha256:4277…`; the
  registry identity begins `sha256:ad8269…`. The mutable deployment changed and
  restarted without becoming an approved immutable release.
- Thirteen workflows exist: eleven active and two inactive. All eight required
  active workflow IDs exist, but the retired approval ID `5OzpL9oBMR8gpSJA` is
  wrongly active and `WMCLeadRetention01` is absent.
- Unexpected active workflows are `AIHIntakeV1x001` and
  `MWNvA0TBXDjuAUpU`. Unexpected inactive workflows are
  `HHiDnT8q0xHgnjVU` and `X84QLnGVbbhWG6Oq`.
- The security audit found five unprotected webhook paths, including the active
  manual intake, active trend research, and retired human-approval paths. This
  is a critical failure even though the expected active IDs are present.
- The operator LAN edge still returns 502, and the scoped read-only API key
  needed for release acceptance is absent.

### AI, research, and campaign evidence

- A fresh minimal request successfully used local `qwen3.6:35b`.
- A fresh SearxNG JSON request succeeded and returned results across multiple
  domains. This proves current adapter use, not suitable evidence for a
  campaign claim.
- Production has no current release-eligible trend run for all five campaigns.
  The retained production research remains blocked by source/date qualification.
- A separately running self-hosted Firecrawl service is healthy, but the
  marketing application is not wired to it. Firecrawl Cloud also has no
  installed key. The application must therefore report Firecrawl as
  unavailable, not active.
- In the first isolated three-round generation acceptance, K1 and K2 exhausted
  safe semantic repair and returned blocked fallbacks. K3 and K4 retained actual
  local-Qwen provenance and passed the deterministic quality gate. K5 retained
  actual local-Qwen provenance but failed the audience-relevance gate. No result
  was approved, scheduled, published, or measured.
- Subsequent controlled reruns showed that individual K1, K2, K3, K4, and K5
  drafts can be produced by local Qwen and that several score 100 under the
  deterministic evaluator. They did not form one complete accepted run. The
  latest attempt encountered a K1 transport timeout and exposed a K2 rhetorical
  question that implied comprehensive data protection. The source guard was
  extended to reject that wording, with local regression coverage, but the
  updated exact source has not completed the required fresh hardware rerun.

### Other dependencies

| Dependency | Fresh observation | Release interpretation |
| --- | --- | --- |
| Postiz | 2.21.10; registration open; no accepted API key/tenant/provider contract | No external draft handoff |
| Twenty | 2.21.0 from mutable deployment; no scoped key or accepted workspace mapping | No CRM writes |
| Mautic | 7.1.3; installer still returns HTTP 500; database has zero tables | Not installed or usable |
| ComfyUI | Service responds; model metadata returns HTTP 500 | No governed production creative path |
| Firecrawl | Separate self-hosted service healthy, application route absent | Do not report as configured or successfully used by the application |
| Prometheus/Grafana | Stopped | No production monitoring acceptance |

## Local candidate evidence boundary

The exact `a7b823b85629c27febf16e9428874297a50b39b8` source candidate retained
strong isolated evidence: its full local regression passed, and a fresh
desktop/mobile review showed exactly K1–K5, no demos, no browser errors, and no
WCAG A/AA findings. Those checks support the business interface only.

Later governed source changes invalidate the 13 July image, SBOM, and archive
identities as evidence for the final tree. Local Docker could not be brought to
a running state during the 14 July check, so no fresh final image build or
Docker Scout result exists. Do not relabel the older image digests, SBOMs, or
190-file archive as the current release artifact.

### Final local worktree gate

The source candidate validated here was an uncommitted worktree based on
`a7b823b85629c27febf16e9428874297a50b39b8`. After this gate, the operator
explicitly authorized a source-only publication: the candidate was committed
as `32c372d7bcadb28cd5a4453a416142d38f24e125` and merged with canonical
`main`. It is still not the source running in production. Its final local gate
produced the following evidence:

- Python 3.12.13 loaded 57 compatible packages. Source compilation, Ruff, and
  mypy all passed; mypy checked 44 source files.
- The complete Python suite passed with 665 tests, two platform-specific skips,
  and 269 adversarial subtests. The only warning is an upstream Starlette test
  client deprecation and does not affect the production runtime.
- The dedicated release-contract suite passed with 66 tests, one
  platform-specific skip, and 146 adversarial subtests. The credential scanner
  accepted all 84 intended Python files and rejected the malicious regression
  matrix, including indirection through helpers, lambdas, loops, instance
  fields, formatting, and string normalization.
- The governed K1-K5 golden corpus passed 5/5 at a score of 100 for every
  campaign. This is deterministic release-gate evidence, not evidence of a
  fresh production hardware-AI run.
- The isolated business UI showed exactly K1-K5 and no demo data across all six
  routes at desktop and mobile sizes. It made no unsafe HTTP requests, produced
  no console, page, or failed-response errors, had no mobile overflow, and had
  zero Axe WCAG A/AA findings. The corrected K3 campaign badge now has a 5.91:1
  contrast ratio.
- The locked npm install and high-severity audit passed with zero
  vulnerabilities. Six JavaScript files, five shell scripts, 34 project JSON
  files, 49 relative documentation links, and all 13 supported Compose render
  combinations passed validation.
- The local Docker Desktop Linux engine timed out during its final server
  probe. Compose rendering is green, but there is no truthful final container
  build, image digest, SBOM, or container smoke result for this exact tree.
- At validation time GitHub had no published workflow, ruleset, or branch
  protection for `main`. The later source-only publication made the local CI
  workflow available on `main`; it did not add a ruleset or branch protection
  and must not be interpreted as production approval while this report is RED.

The release archive, checksum, and inventories are generated outside the
source tree. Their sidecars are the authoritative artifact identities; an
archive identity must never be copied from the older 13 July candidate.

## Required next evidence

1. Build one immutable final source archive and arm64 image from the exact
   intended commit; verify target-side checksum and run it in isolation on
   Nvidia hardware.
2. Provision trusted TLS, two named operator identities, `/session`, required
   security headers, and protected acceptance credentials.
3. Pin and approve one exact n8n version/digest, close all unprotected webhooks,
   reconcile the exact workflow manifest, repair the LAN edge, and retain a
   successful persisted trend-workflow execution.
4. Produce release-eligible current research and safe actual-AI content for all
   five campaigns; retain citations and deterministic quality evidence.
5. Wire and qualify Firecrawl only if it is part of the approved research path.
6. Complete the distinct visual/licence approvals for the exact creative
   artifact and qualify Postiz, Twenty, and Mautic separately before any write.
7. Create a fresh backup and complete an isolated restore rehearsal.
8. Restore authenticated observability and enforce pull request, CI, named
   review, and no direct/force-push rules on `main`.

## Final disposition

**RED / NO-GO as of 14 July 2026.** Restored Nvidia connectivity enabled a
fresh, useful audit. It did not satisfy the production security, workflow,
content, source, dependency, rollback, or repository-governance gates. Keep
external writes disabled and do not describe the present system or `main` as a
green production release.
