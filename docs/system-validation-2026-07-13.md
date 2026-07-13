# System Validation — 13 July 2026

> **Overall result: RED / NO-GO.** Do not cut over the hardened release, do
> not enable external writes, and do not merge or push `main` as
> release-ready. Nvidia-1 was reachable during the earlier audit but could no
> longer be resolved or reached over SSH at the final office-network check.
> Current production attestation, the production security edge, the exact n8n
> release manifest and persisted execution proof, releasable
> two-domain source evidence, named creative approval and licence confirmation,
> backup freshness and restore proof, and production-path acceptance are not
> ready. Green local engineering checks do not authorise production cutover.

## Document control and evidence boundary

| Field | Value |
| --- | --- |
| Validation date | 13 July 2026 (Europe/Berlin) |
| Environment observed | Nvidia-1 through its protected service-catalog identity; concrete hostname and private address intentionally omitted from this public record |
| Method | Earlier read-only host, container, HTTP, database, file-presence, backup-manifest, and application-data inspection; final connectivity recheck; full local regression and static analysis; dependency, configuration, Compose, archive, secret, isolated-container, content-quality, browser, and accessibility review |
| Release decision | **NO-GO for production cutover and `main` merge** |
| External provider writes | Must remain `false` |
| Governing principle | Reachable, configured, successfully used, release-qualified, and deployed are different states |

This record distinguishes live observations from local changes that have not
been deployed. It contains no credential values or private evidence payloads.
Abbreviated image identifiers below are sufficient for audit correlation, but
they are **not** a substitute for recording the full immutable digest in an
approved release record.

## External benchmark used for the review

The dashboard and content gates were compared with current authoritative
guidance, not only with the previous implementation:

- W3C requires keyboard focus to remain visibly identifiable, input errors to
  be described in text, and dynamic progress/result messages to be exposed to
  assistive technology. The candidate therefore uses persistent focus styles,
  textual next actions/errors, and live status regions rather than color-only
  state ([W3C Focus Visible](https://www.w3.org/WAI/WCAG21/Understanding/focus-visible),
  [Error Identification](https://www.w3.org/WAI/WCAG22/Understanding/error-identification),
  [Status Messages](https://www.w3.org/WAI/WCAG21/Techniques/failures/F103)).
- Google recommends people-first, original, accurate, useful content with
  clear sourcing and appropriate context about automation. The candidate
  consequently separates sourced research, deterministic directions, local-AI
  drafting, deterministic quality evaluation, and named human approval; it
  does not treat bulk AI output as publishable
  ([people-first content](https://developers.google.com/search/docs/fundamentals/creating-helpful-content),
  [generative-AI guidance](https://developers.google.com/search/docs/fundamentals/using-gen-ai-content)).
- Marketing reports need an explicit selection and time context. The candidate
  keeps campaign identity visible, records measurement windows/retrieval time,
  and renders unavailable data as unknown rather than as zero
  ([Looker Studio controls](https://support.google.com/looker-studio/answer/11335992),
  [Analytics data freshness](https://support.google.com/analytics/answer/12233314)).

These references support the interaction and evidence principles. They do not
certify this implementation; the executable and human acceptance gates below
remain authoritative.

## Executive decision

| Decision area | Result | Basis |
| --- | --- | --- |
| Nvidia-1 connectivity | RED / unavailable at final check | SSH and name resolution succeeded earlier in the audit, then the office route stopped resolving or accepting SSH. Current production state cannot be re-attested. |
| Existing production service | RED | Plaintext HTTP remains exposed; authenticated TLS/session controls are absent. |
| Hardened local code | AMBER; isolated engineering checks green | The final source regression collected 452 tests: 450 passed and 2 skipped. Static checks, dependency/configuration validation, deterministic content evaluation, authenticated desktop/mobile operator and degraded-path journeys, accessibility, local hardened amd64/arm64 image checks, and deterministic source-archive inspection pass. Actual Nvidia execution, dependency/TLS acceptance, and the current-trend journey remain blocked; nothing is deployed. |
| n8n release | RED | The raw service was last observed healthy, but the LAN edge was broken, the live workflow manifest was not approved, the image differs from the reviewed candidate, and current reachability is unavailable. |
| Five-campaign AI drafting | AMBER | A disposable local candidate produced real local-Qwen drafts for K1–K5. They passed deterministic content checks after controlled revisions, but they are not approvals or publications. A historical K1–K5 search stayed single-source per topic; the latest K1 follow-up reached four independent domains but had zero trustworthy dated sources in the lookback and therefore remained blocked. |
| Creative generation | AMBER | A loopback-only Nvidia-2 FLUX Schnell candidate passed strict technical qualification with a real generated image. Named human visual approval and licence confirmation are still missing, so no creative release is authorised. |
| Rollback readiness | RED | The verified backup predates the 13 July drafts; no current backup and restore rehearsal exist. |
| Production cutover | **NO-GO** | Mandatory gates remain open. |
| Push/merge to `main` as green | **NO-GO** | The user's condition “everything is green and ready” is not met. |
| Repository governance | RED | The public GitHub repository has no `main` branch protection or ruleset; direct pushes can bypass pull-request review and required CI. |

## Last-observed live state on Nvidia-1

### Host, agent, and candidate

- SSH access through the protected Nvidia-1 service-catalog identity succeeded
  during the earlier audit. At the final office-network check, name resolution
  failed and the known SSH route timed out. The observations below are therefore
  timestamped historical evidence, not current-health claims.
- The audit reported approximately 2.3 TB disk space and 98 GB RAM available.
  This is capacity evidence only, not application readiness evidence.
- The production marketing-agent image is `sha256:a5442cfc0e78…`. The
  production container has no Docker health check.
- The existing candidate uses tag `candidate-20260710-final` and image
  `sha256:1c7a6dc51bc9…`. It predates the current local fixes and is not the
  current release candidate.
- Production and candidate external writes are disabled.
- The local `r3` release archive is absent from Nvidia-1 and has been
  superseded by later source changes. It must not be uploaded or deployed as
  the final candidate.

### Production HTTP, TLS, and operator identity

| Check | Observed result | Release interpretation |
| --- | --- | --- |
| `<LEGACY-CONSOLE-URL>` | HTTP 200 during the earlier audit | The old console was last observed over plaintext; current reachability is unavailable. |
| HTTPS handshake on the production console edge | Fails | No trusted TLS service is established. |
| `GET /session` | HTTP 404 | Named edge-attested operator identity is not deployed. |
| HSTS | Absent | TLS hardening is not deployed. |
| Content Security Policy | Absent | Required frame protection is not demonstrated. |
| `X-Frame-Options` | Absent | Required clickjacking protection is not demonstrated. |
| CA, TLS, named-account, acceptance, and read-only n8n credential files | Absent | Provisioning and two-operator acceptance are still required. |

The current production URL must not be described as HTTPS, authenticated by a
named operator, or hardened. A browser certificate bypass would not satisfy
the release gate.

### n8n service, image drift, and dynamic-DNS failure

During the successful live audit, the n8n core reported version `2.29.10`. Its image content ID is
`sha256:d8694a…`, with registry digest `sha256:9cb605…`. Raw n8n health and
readiness checks on port `5678` returned HTTP 200.

The reviewed multi-architecture migration candidate instead pins n8n `2.29.9`
at digest prefix `e0d959…`. That is a real version and digest difference, not an
exact-live pin. Before a maintenance window, either qualify and pin the exported
live `2.29.10` image or approve `2.29.9` as a separate tested version change.

The operator-facing LAN edge on `:15678` returned HTTP 502. The root cause was a
stale upstream address cached by the long-running nginx process: it retained an
obsolete Docker-network address for `core-n8n`. The local nginx configuration has been changed to use
request-time Docker DNS for n8n and Grafana, and its targeted assertions pass.
That fix is local only and has not been deployed.

The last-observed n8n environment claimed workflow verification was true. The live
database evidence contradicts that claim, so the environment flag must not be
accepted as proof.

## Exact n8n release manifest

The following ten definitions are the complete normative repository manifest.
The first eight must be present exactly once and active. The final two must be
present exactly once and inactive.

| Required state | Workflow | Stable ID |
| --- | --- | --- |
| Active | WAMOCON Marketing — Manual Content Intake | `lYfpV4r4oeEzPtuO` |
| Active | WAMOCON Marketing — Integration Health | `Psaft2cYujD42MAs` |
| Active | WAMOCON Weekly Planning | `GqGVw06F64o7rvjI` |
| Active | WAMOCON Marketing — Verified Trend Research | `WMCTrendResearch01` |
| Active | WAMOCON 72h Due Discovery (Read Only) | `eTZSmmzKe6dJ1knR` |
| Active | WAMOCON 7d Due Discovery (Read Only) | `WMCAnalytics7d01` |
| Active | WAMOCON 14d Due Discovery (Read Only) | `WMCAnalytics14d1` |
| Active | WAMOCON 30d Due Discovery (Read Only) | `WMCAnalytics30d1` |
| Inactive | WAMOCON Marketing — Human Approval (Retired: use authenticated console) | `5OzpL9oBMR8gpSJA` |
| Inactive | WAMOCON Lead Retention — Daily Local Anonymization (Staged) | `WMCLeadRetention01` |

Read-only live database inspection found 13 workflow rows: 11 active and 2
inactive. Two release-significant deviations were proven:

- retired workflow `5OzpL9oBMR8gpSJA` is incorrectly active; and
- staged workflow `WMCLeadRetention01` is absent.

A sanitized 13-row live export was not retained with this audit. It is an
outstanding controlled evidence attachment. The remaining live IDs and names
must not be guessed. Before release, export the full list, compare it with the
ten-row manifest above, remove or formally disposition all unexpected rows,
and prove the required active/inactive state after restart. At least one real,
authenticated, persisted trend-workflow execution ID is also required before
setting workflow verification to true.

## Five campaigns, AI use, and source evidence

Live application data contains exactly the five canonical campaigns K1–K5 and
11 non-demo content states. Five week-29 drafts were created on 13 July with:

- provider `local_qwen`;
- model `qwen3.6:35b`; and
- `fallback_used=false`.

K4 is held at `needs_evidence`; K1, K2, K3, and K5 are at human review. These
records demonstrate real local-Qwen drafting. They do **not** demonstrate
approval, scheduling, publication, provider writes, or performance.

The production trend store remains insufficient: all ten stored production
runs are QA-only for `kampagne_1_consulting_qa`, and the newest is dated 10
July. A separate disposable candidate run on 13 July successfully queried
SearxNG for K1–K5 and retained nine cited candidates. Each result correctly
remained `needs_source_verification`, because only one independent source
domain supported the individual topic. A later K1-only follow-up found one
idea with four independent domains, but none supplied a trustworthy
publication date in the ten-day lookback. It correctly remained
`source_verified_date_unconfirmed`. Together these runs prove truthful
fail-closed research behavior, not a releasable trend claim. Trend-derived
continuation must remain blocked per topic until both the independent-domain
and recent-dated-source gates pass.

## Dependency status

| Dependency | Live observation | Required release proof |
| --- | --- | --- |
| Nvidia-2 Qwen | A disposable current-source candidate successfully used `qwen3.6:35b` for real K1–K5 structured drafts, including controlled evaluator-driven revisions; current reachability is unavailable after the Nvidia route loss | Preserve the provenance and evaluator reports, restore connectivity, and repeat against the exact final immutable Nvidia-1/ARM64 candidate if later changes affect the generation path. |
| SearxNG | Historical K1–K5 run: nine cited candidates, each single-source. Latest K1 follow-up: four independent domains for one idea, but zero trustworthy dated sources in the lookback. Current reachability is unavailable. | Retain an eligible per-topic decision with two independent domains and one recent dated citation; never relabel either blocked run as a trend. |
| ComfyUI / FLUX | Isolated loopback-only Nvidia-2 candidate completed a real FLUX Schnell API job and strict PNG verification; production `:8188` remained unchanged | Bind a named human visual decision and licence confirmation to the recorded output/prompt/workflow/runtime/model hashes, then qualify promotion as a separate release. |
| Firecrawl | Service is absent or unconfigured | Provision a scoped cloud key or separately reviewed private deployment, then retain one bounded successful-use record. |
| Postiz | Registration remains open | Complete owner setup, close registration, and qualify tenant/API contract in a non-production test before any write. |
| Twenty | Mutable `latest` deployment drifted to v2.20, image digest abbreviated `1d1c…` | Pin an immutable release, verify schema/role/key mapping, and test in isolation. |
| Mautic | Last-observed Docker health reported healthy while `/installer` returned HTTP 500; current reachability is unavailable | Repair and complete a separate, named-identity acceptance. |
| Observability | Prometheus/Grafana services are exited | Restore through their owning release and verify authenticated metrics and dashboards. |
| n8n | Last observed raw core 2.29.10 healthy; LAN edge 502; manifest non-compliant; reviewed migration candidate is a different 2.29.9 digest | Approve one exact version/digest, deploy the dynamic DNS/TLS edge, reconcile the workflow manifest, bind credentials, restart, and retain a persisted execution ID. |
| Kimi cloud route | A credential is configured locally, but provider-side rotation/reissue and post-rotation qualification are not recorded | Keep cloud fallback disabled, rotate or reissue the key at the provider, then qualify the scoped route without exposing the value. |

Postiz, Twenty, Mautic, Firecrawl, observability, n8n database migration,
Redis queue mode, and external provider writes are separate acceptance scopes.
Combining them with the console cutover would make rollback unsafe.

### Isolated FLUX technical qualification

The isolated Nvidia-2 candidate listened only on loopback port `18189` and used
the pinned candidate root. On 13 July it completed prompt
`d1b46fff-206b-40bc-b547-b47b8512d9ef` and produced a 512×512 RGB PNG:

- output SHA-256: `32d00b1e7688c957c769409501a71effcf544084f2f9de1a0c7e328a7bb25618`;
- workflow SHA-256: `10a93745478a805b01c36827c9168bc995098fcba460b9dc8fd0dadabe6efe76`;
- runtime identity SHA-256: `5645afade6f1ede25379daa02d7dad8886c0c31eb8bea6a067a6caa556ec43fa8`; and
- combined model-file identity SHA-256: `5d56bb5a8bf8759651ee72ea0dfa24783577f934e8395f2a44eec30873c9c36da`.

The verifier checked PNG signatures, chunk order and CRCs, dimensions, color
mode, decompression completion, scanline length/filter values, embedded
workflow identity, runtime identity, and all four model files. The artifact was
also fetched back through the candidate API and matched the recorded output
hash. This closes the machine technical-generation gate only. The evidence
record intentionally has `release_ready=false`, because a named human visual
decision and licence approval have not been recorded. The existing production
ComfyUI process was not changed.

## Backup and archive evidence

The existing pre-change backup is:

```text
<BACKUP_ROOT>/production-hardening/20260710T115858Z
```

It contains 30 files and occupies 980,954,960 bytes. Its `SHA256SUMS` manifest
contains 29 payload entries, and all 29 entries pass. This proves integrity of
the retained 10 July payload; it does not prove restoration.

The backup predates the five 13 July drafts and is therefore stale for the
current production state. Before any cutover, create a fresh, quiesced backup
that includes current runtime data, source/configuration, the complete stopped
n8n SQLite volume, workflow export, credentials/encryption material, and
checksums. Rehearse an isolated restore and record the result.

The superseded local archive
`wamocon-marketing-machine-candidate-20260710-r3.tar.gz` is absent from Nvidia-1
and must not be reused. The final local source package for this documented tree
is `qa_output/release/wamocon-marketing-machine.tar.gz`. It contains 190 governed
source files plus the embedded release inventory. Its generated external
`.sha256` sidecar matches the archive, the external inventory matches every
governed file, required release files are present, prohibited runtime, secret,
Git, dependency-cache, and QA-output paths are absent, and a recursive Gitleaks
scan reports no findings. The authoritative identity remains in the external
`.sha256` and inventory sidecars under `qa_output/release/`; it is deliberately
not embedded in this Markdown file because the file is itself part of the
archive. This closes local source packaging only. The exact archive still needs
approved transfer, target-side checksum verification, isolated Nvidia build,
and production-path acceptance.

## Local fixes completed but not deployed

The working tree contains the following release-oriented repairs:

- K4's circular media/consent gate is removed: the operator can register
  evidence during review, while approval still fails closed without a complete
  approved video and consent evidence.
- Postiz media evidence is now bound to the exact provider bytes: registration
  fetches and hashes the direct provider media path, and handoff repeats that
  check immediately before any draft request. Redirects, unsafe destinations,
  type mismatches, unavailable content, and changed bytes block safely.
- Detailed audience profiles are resolved into the runtime AI context instead
  of leaving campaign audience IDs unused.
- A meaningful review note is required for approval and revision decisions.
- The creative plane is release-critical and remains blocked when ComfyUI,
  model-bundle, compatibility, or qualified-generation evidence is incomplete.
- n8n readiness requires persisted execution evidence and the exact manifest;
  an environment assertion alone is no longer treated as truth.
- nginx uses request-time Docker DNS for n8n and Grafana.
- secret directories are excluded from the Docker build context.

These are local source facts, not production claims. None may be described as
live until a fresh image is built, tested, identified by full digest, deployed
through an approved window, and re-attested from the operator path.

## Tests recorded on 13 July

The final full local pytest regression collected **452 tests: 450 passed and 2
skipped**, with no failures or errors. The machine-readable record is
`qa_output/pytest-final.xml`. Focused reruns are corroborating evidence and must
not be added to that total.

The remaining completed local checks report:

- Ruff clean;
- mypy success across the current source tree;
- Python byte-code compilation successful;
- `npm ci` successful and `npm audit` reporting zero vulnerabilities;
- JavaScript syntax successful for the governed browser scripts;
- the current repository JSON corpus parsed successfully;
- shell syntax successful for the deployment entrypoints;
- Compose/configuration validation successful for the core, existing,
  candidate, Nvidia overlay, restricted network edge, hardened observability,
  both n8n release stages, and all growth-tool profiles;
- the deterministic content-quality golden corpus passing all five campaign
  cases with `release_ready=true`;
- an isolated container starting healthy, dropping the application to UID/GID
  `10001`, protecting readiness, exposing exactly K1–K5, retaining no demo
  records, using an empty disposable store, and keeping external writes off;
  and
- zero WCAG A/AA violations across overview, Content Studio, approvals,
  results, and setup at desktop and mobile sizes after the campaign overview
  received an accessible scroll-region label and keyboard focus.

The latest local amd64 and arm64 images built from the then-current source each
contained 97 packages and reported **0 critical, 0 high, 0 medium, and 0 low**
findings in Docker Scout. Regenerated SPDX SBOMs are retained as
`qa_output/wamocon-image-amd64-20260713.spdx.json` and
`qa_output/wamocon-image-arm64-20260713.spdx.json`. Both images ran locally with
a read-only filesystem, UID/GID `10001`, `no-new-privileges`, a `401` denial for
unauthenticated access, exactly K1–K5, and no demo records. The arm64 image ran
through QEMU and reported `aarch64`; this proves local architecture execution,
not operation on real Nvidia hardware.

The exact current local image identities are
`sha256:0ae6c4c57d2564f83929aec844bb54be5e6bca297c1b6efc00b38074478929f8`
for amd64 and
`sha256:7527599ee25d47a9475f60df763e479ce62de205cd8dd7d89737f712c5068d70`
for arm64. They were rebuilt after the final trend-intake policy correction,
then rescanned and re-exercised. Any later application, workflow, campaign,
dependency, or image change invalidates this evidence and requires both builds,
SBOMs, and affected checks to be repeated. The deterministic local archive is
final for this exact documented source tree under the separate evidence in the
backup and archive section; any later governed-file change invalidates it.

The current `final_*.png` files in `qa_output/` are final desktop/mobile UI
evidence for the exact isolated candidate that was exercised. Its authenticated
operator journeys and safe degraded journey passed. These screenshots are not
production-path or dependency-backed current-trend evidence. The older
`live_source_gate.png` remains blocked-dependency evidence and does not prove a
successful current-trend journey.

The following final evidence remains pending:

- approved transfer and target-side verification of the exact local archive;
  rebuild the archive and re-attest both platform images only if a later
  governed or image-relevant source change occurs;
- execution of the exact immutable arm64 candidate on real Nvidia hardware and
  production-path TLS/session/dependency acceptance; local QEMU execution is
  not a substitute;
- eligible current K1–K5 source evidence: the historical nine-result run was
  single-source per topic, while the latest K1 follow-up had four domains but
  zero trustworthy dated sources; both are truthfully blocked;
- production-path smoke, trusted TLS/session/header checks, current backup and
  rollback rehearsal, exact n8n reconciliation/execution evidence, named
  creative approval, and post-change verification during an approved
  maintenance window.

Earlier 10 July test results remain historical evidence only. Executable and
packaging files have changed since those runs, so they cannot close the 13 July
release gate.

## Unresolved release gates

1. Restore and stabilize the office route to Nvidia-1, then re-attest SSH,
   production endpoints, and dependency reachability without mutating live data.
2. Preserve the exact local archive, sidecars, platform-image identities, and
   SBOMs recorded here. Transfer and verify that archive on the target. If any
   governed or image-relevant source changes first, rebuild the archive and the
   affected images/evidence. Do not reuse `r3` or the old
   `candidate-20260710-final` image.
3. Verify that exact immutable candidate on real Nvidia-1 ARM64 hardware in isolation and
   prove disposable data, non-root execution, exactly K1–K5, external writes
   off, and truthful readiness.
4. Produce eligible current K1–K5 research. Preserve the historical nine-result
   single-source run and the latest K1 four-domain/zero-dated-source result as
   separate blocked evidence; neither is eligible for a current-trend claim.
5. Complete the FLUX/ComfyUI release decision by binding a named human visual
   approval and licence confirmation to the already qualified output, prompt,
   workflow, runtime, and model-file hashes.
6. Create and restore-rehearse a fresh post-13-July backup.
7. Provision trusted TLS, two named operator identities, trusted workstation
   CA installation, session attestation, and required security headers.
8. Deploy the dynamic-DNS edge and prove both plaintext closure and trusted
   HTTPS for the console and n8n.
9. Choose and approve one exact n8n image: qualify/pin live `2.29.10`, or treat
   the reviewed `2.29.9` digest as a separate tested version change. Then
   reconcile the exact ten-definition manifest, bind the two required encrypted
   credentials manually, restart, and retain a successful persisted
   trend-workflow execution ID.
10. Rotate or reissue the configured Kimi key at the provider, keep cloud
    fallback disabled, and qualify the scoped route before any production use.
11. Complete separate acceptance for any growth tool or provider before its
    write capability can be enabled.
12. Protect `main` with a GitHub ruleset: pull requests only, required CI, at
    least one named review, and no direct push or force-push bypass.
13. Record named technical, secondary, business, and rollback owners and pass
    the complete maintenance-window acceptance checklist.

Any failed gate stops the release. External writes remain false throughout
candidate testing and cutover acceptance.

## Allowed next actions

- Continue local remediation and documentation on the current feature branch.
- Preserve the completed isolated browser/image evidence and re-run affected
  checks whenever the tree changes; retain the independent review record.
- Rebuild, checksum, inspect, upload, and test a **new isolated candidate** only.
- Create a fresh production backup and perform an isolated restore rehearsal.
- Provision TLS and named identities without exposing credential material.
- Reconcile and verify n8n in an approved maintenance window.
- Qualify ComfyUI/FLUX and each external dependency as separate releases.
- Re-run this validation and issue a new dated GREEN record only when every
  mandatory gate has objective evidence.

## Claims that are not permitted

Until a later GREEN record supersedes this document, do not claim that:

- production runs the hardened dashboard or current local code;
- Nvidia-1 or its dependencies are currently reachable;
- the production console or n8n uses trusted HTTPS or named sessions;
- the n8n LAN edge is healthy or the workflow release is verified;
- the ten-definition n8n manifest is live;
- K1–K5 have current verified trend evidence;
- any of the five drafts is approved, scheduled, published, or measured;
- production FLUX/ComfyUI or Firecrawl is release-qualified;
- the Kimi cloud route is safe before provider-side key rotation and
  post-rotation qualification;
- Postiz, Twenty, Mautic, or observability is production-ready;
- the 10 July backup is current or restore-tested;
- `r3` is the current candidate or is present on Nvidia-1;
- successful isolated browser/image checks make the complete current codebase,
  dependency-backed journey, or production path green; or
- green local checks authorise production use; or
- production cutover or a release-ready `main` merge is authorised; or
- the unprotected public `main` branch provides an enforced review/CI gate.

## Final release disposition

**RED / NO-GO as of 13 July 2026.** Earlier connectivity allowed safe read-only
auditing and isolated candidate work; the route is unavailable at the final
check and the resulting observations are not current attestation. Production
remains unchanged, external writes remain disabled, and no push or merge to the
currently unprotected `main` branch may be represented as a green production
release under this record.

For historical context, see
[the 10 July validation record](system-validation-2026-07-10.md). For the
controlled procedure, use the
[Nvidia-1 deployment runbook](remote-project-runbook.md).
