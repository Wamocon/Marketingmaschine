# Trend Studio

Trend Studio is the campaign-to-Reel workflow for the five WAMOCON campaigns. It scans recent public-source signals, groups them by campaign fit, generates multiple Instagram Reel concepts, and lets a human approve one concept into the existing content review workflow.

## What It Does

1. Run `POST /workflows/trend-research` with a default `lookback_days` value of `10`.
2. Search configured public sources for Instagram, TikTok, Reddit, forums, and broad web signals.
3. Store the run under `runtime-data/trend_runs`.
4. Show campaign-specific trend candidates in `/ui` under `Trend Studio`.
5. Generate multiple concept variants through `POST /workflows/reel-concepts`.
6. Block off-topic regenerate prompts before concept creation.
7. Approve a selected concept through `POST /workflows/reel-concepts/{concept_id}/approve`.
8. Store the resulting Instagram Reel brief as a normal content state that still requires human review before scheduling.
9. Append a learning record for future optimization and model-memory work.

## Source Adapters

Use at least one live source adapter in production:

| Source | Environment | Notes |
| --- | --- | --- |
| SearxNG | `SEARXNG_BASE_URL` | Best default for broad public web and domain-constrained queries. |
| Google Programmable Search | `GOOGLE_CSE_API_KEY`, `GOOGLE_CSE_ID` | Uses `dateRestrict=d10` and safe search. |
| Reddit API | `REDDIT_BEARER_TOKEN`, `REDDIT_USER_AGENT` | Uses OAuth search sorted by new posts in the last week. |
| TikTok Research API | `TIKTOK_RESEARCH_CLIENT_TOKEN` | Requires TikTok Research API eligibility and token access. |
| Instagram | `INSTAGRAM_ACCESS_TOKEN`, `INSTAGRAM_BUSINESS_ACCOUNT_ID` | Current implementation uses broad web search for public Instagram/Reels URLs. Add first-party Instagram Graph API expansion only for owned/eligible business account data. |

If no adapter returns live results, Trend Studio creates campaign-only placeholders with `verification.status = requires_live_sources`. Those records are useful for UI testing but must not be treated as verified trends.

## Verification Rules

Trend Studio separates trend provenance from publishable proof:

- `verified_recent`: at least two external sources and at least one dated source in the lookback window.
- `source_verified_date_unconfirmed`: multiple external sources, but date confirmation is weak.
- `single_source_review`: one external source only.
- `requires_live_sources`: no live source adapter returned results.

Trend sources are internal review material. Public claims still require approved proof sources from the evidence vault and the existing approval checklist.

## Manual and n8n Intake

`POST /workflows/create-content` and the n8n manual-content webhook use an explicit content contract:

- `content_mode: evergreen` creates campaign-led content with no trend run, trend ID, trend status, trend URLs, or trend citations attached; its generation inputs, including objective, instructions, CTA, format, and hashtags, must not request current/latest/trending claims.
- `content_mode: current_trend` accepts only `trend_run_id` and `trend_id`. The API reloads that exact stored selection, checks the campaign match, freshness, two independent publisher domains, and a recent dated source, then reconstructs the summary, URLs, status, and citations itself.
- Caller-supplied `trend_summary`, `trend_sources`, `trend_verification_status`, or `citations` are rejected in both modes.

With `MARKETING_MACHINE_REQUIRE_EXPLICIT_CONTENT_MODE=true` (the production default), a direct API request that omits `content_mode` is blocked. The active n8n manual-intake workflow safely supplies `evergreen` when its inbound request omits the mode; the API still rejects current/latest/trending language in that evergreen request. An explicit `current_trend` mode and its `trend_run_id`/`trend_id` references pass through unchanged for server-side revalidation. Setting the switch to `false` is migration-only: a direct request without a mode becomes `evergreen`; it never enables an unverified current-trend claim.

`MARKETING_MACHINE_REQUIRE_VERIFIED_TRENDS` is supported only as a deprecated compatibility alias for the explicit-mode switch. Its name does not describe the content rule: evergreen is allowed, while current-trend evidence is mandatory and server-revalidated in every configuration. Do not configure both names with conflicting values.

## Guardrails

- No private scraping, login-wall bypassing, or platform Terms bypassing.
- No customer, employee, applicant, or lead story without consent.
- No invented metrics, client names, ROI guarantees, or security/compliance absolutes.
- User regenerate prompts are topic-locked to the selected campaign and trend.
- Approved concepts become drafts only; publishing still requires human review and platform approval.

## UI Flow

1. Open `/ui`.
2. Click `Trends`.
3. Click `Run 10-day Scan`.
4. Click a campaign trend.
5. Optionally add a topic-related prompt such as `make this Q&A with stronger kinetic captions`.
6. Click `Generate`.
7. Click `Approve first variant`.
8. Review the generated content state in `Approval`.

## Production Database Shape

The Postgres schema now includes:

- `trend_research_runs`
- `trend_signals`
- `reel_concepts`
- `learning_records`
- trend fields on `content_briefs`

The local implementation persists the same contracts under `runtime-data` until the production Postgres store is enabled.
