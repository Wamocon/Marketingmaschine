const assert = require("node:assert/strict");
const { chromium } = require("playwright");

const baseUrl = process.env.MARKETING_MACHINE_BASE_URL || "http://127.0.0.1:18119";
const mutationToken = (process.env.MARKETING_MACHINE_MUTATION_TOKEN || "").trim();
const authenticatedActor = (process.env.MARKETING_MACHINE_TEST_ACTOR || "").trim();
const edgeAttestation = (process.env.MARKETING_MACHINE_EDGE_ATTESTATION || "").trim();

function localDateTime(date) {
  const pad = (value) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

async function capture(page, path) {
  // Selected queue items and correction prefill intentionally smooth-scroll in
  // the product. Let that animation finish before pinning the full-page capture
  // to the document origin, otherwise the sticky header obscures the heading.
  await page.waitForTimeout(650);
  await page.evaluate(() => {
    document.documentElement.style.scrollBehavior = "auto";
    document.body.style.scrollBehavior = "auto";
    window.scrollTo(0, 0);
    if (document.scrollingElement) document.scrollingElement.scrollTop = 0;
  });
  await page.waitForTimeout(120);
  assert.equal(await page.evaluate(() => Math.round(window.scrollY)), 0, "screenshot capture must start at the page origin");
  await page.screenshot({ path, fullPage: true });
}

async function selectRealInstagramReelReview(page) {
  await page.waitForSelector("#reviewQueue [data-review-id]");
  const selected = await page.locator("#reviewQueue [data-review-id]").evaluateAll((buttons) => {
    const eligible = buttons.filter((button) => {
      const campaignId = String(button.dataset.campaignId || "").toLowerCase();
      const channel = String(button.dataset.channel || "").toLowerCase();
      const format = String(button.dataset.format || "").toLowerCase();
      return /^k[1-5]$/.test(campaignId)
        && channel.includes("instagram")
        && format.includes("reel");
    });
    const awaitingReview = eligible.filter((button) => String(button.textContent || "").includes("Freigabe nötig"));
    const approvedMissingMedia = eligible.filter((button) => (
      String(button.textContent || "").includes("Bereit zur Planung")
      && button.dataset.mediaReady === "false"
    ));
    const candidates = awaitingReview.length ? awaitingReview : approvedMissingMedia;
    const preferred = candidates.find((button) => button.dataset.campaignId?.toLowerCase() === "k4") || candidates[0];
    return preferred
      ? {
        id: preferred.dataset.reviewId,
        campaign: String(preferred.textContent || "").trim(),
        approvalNeeded: String(preferred.textContent || "").includes("Freigabe nötig"),
      }
      : null;
  });
  assert.ok(
    selected?.id,
    "Disposable candidate has no real K1-K5 Instagram Reel awaiting review or approved but missing verified media",
  );
  assert.doesNotMatch(selected.id, /(?:^|[._-])(demo|mock|smoke)(?:$|[._-])/i, "review item must not be demo data");
  await page.locator("#reviewQueue [data-review-id]").evaluateAll((buttons, contentId) => {
    const button = buttons.find((candidate) => candidate.dataset.reviewId === contentId);
    if (!button) throw new Error("Selected review item disappeared before it could be opened");
    button.click();
  }, selected.id);
  return selected;
}

async function registerSelectedReelMedia(page, actor) {
  await page.waitForSelector("#postizMediaForm");
  const mediaAssetId = await page.inputValue("#mediaAssetId");
  assert.ok(mediaAssetId, "the media registration must prepare an internal asset key");
  await page.fill("#postizMediaId", "postiz-video-isolated-review");
  await page.fill("#postizMediaPath", "http://127.0.0.1:5000/media/isolated-review.mp4");
  await page.setInputFiles("#mediaOriginalFile", {
    name: "freigegebenes-kampagnenvideo.mp4",
    mimeType: "video/mp4",
    buffer: Buffer.from("isolated-candidate-video-proof"),
  });
  await page.waitForSelector("#mediaFileProof.is-ready");
  assert.match(await page.textContent("#mediaFileProof"), /durch Ihre Auswahl zugeordnet/i);
  assert.equal(await page.inputValue("#mediaReviewer"), actor);
  assert.equal(await page.getAttribute("#mediaReviewer", "readonly"), "");
  await page.fill("#mediaApprovedAt", localDateTime(new Date(Date.now() - 60_000)));
  await page.fill("#mediaSourceRef", "isolated-review:campaign-approval");
  await page.fill("#mediaPreviewRef", "isolated-review:postiz-preview");
  if (await page.locator("#mediaConsentRefs").count()) {
    await page.fill("#mediaConsentRefs", "Consent-QA-2026-001");
  }
  await page.check("#mediaBrandCheck");
  await page.check("#mediaFactCheck");
  await page.check("#mediaPrivacyCheck");
  await page.check("#mediaDisclosureCheck");
  const [registrationResponse] = await Promise.all([
    page.waitForResponse(
      (response) => response.url().includes("/workflows/content-media-asset")
        && response.request().method() === "POST",
      { timeout: 60_000 },
    ),
    page.click("#mediaSubmit"),
  ]);
  assert.equal(
    registrationResponse.ok(),
    true,
    `media registration returned HTTP ${registrationResponse.status()}`,
  );
  await page.waitForSelector(".media-assets-summary .media-asset-card");
  return mediaAssetId;
}

async function main() {
  assert.ok(mutationToken, "MARKETING_MACHINE_MUTATION_TOKEN is required for the isolated mutation smoke");
  assert.ok(authenticatedActor, "MARKETING_MACHINE_TEST_ACTOR is required for the isolated mutation smoke");
  assert.ok(edgeAttestation, "MARKETING_MACHINE_EDGE_ATTESTATION is required for the isolated mutation smoke");
  const browser = await chromium.launch();
  const context = await browser.newContext({
    extraHTTPHeaders: {
      "X-WAMOCON-Mutation-Token": mutationToken,
      "X-WAMOCON-Actor": authenticatedActor,
      "X-WAMOCON-Edge-Attestation": edgeAttestation,
    },
    viewport: { width: 1440, height: 1000 },
  });
  const page = await context.newPage();
  const errors = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(`console: ${message.text()}`);
  });
  page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
  page.on("response", (response) => {
    if (response.status() >= 400) errors.push(`HTTP ${response.status()} ${response.request().method()} ${response.url()}`);
  });

  const healthResponse = await context.request.get(`${baseUrl}/healthz`);
  assert.ok(healthResponse.ok(), `/healthz returned HTTP ${healthResponse.status()}`);
  const health = await healthResponse.json();
  assert.equal(health.instance?.mode, "isolated-candidate", "mutation smoke must use an isolated-candidate instance");
  assert.equal(health.instance?.disposable_data, true, "mutation smoke data namespace must be disposable");
  assert.match(health.instance?.data_namespace || "", /^candidate-/, "mutation smoke namespace must start with candidate-");

  await page.goto(`${baseUrl}/ui#approvals`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("#sessionIdentity.is-authenticated");
  assert.match(await page.textContent("#sessionIdentity"), new RegExp(authenticatedActor.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  const selection = await selectRealInstagramReelReview(page);
  const contentId = selection.id;
  await page.waitForFunction(() => (
    ["#approvalForm", "#postizMediaForm", "#schedulerHandoffForm", "[data-replace-media]"].some((selector) => {
      const element = document.querySelector(selector);
      return element && element.getClientRects().length > 0;
    })
  ));
  const existingReplacement = page.locator("[data-replace-media]").first();
  const schedulerAlreadyReady = await page.locator("#schedulerHandoffForm:visible").count() === 1;
  let mediaAssetId = schedulerAlreadyReady && await existingReplacement.count()
    ? await existingReplacement.getAttribute("data-replace-media") || ""
    : "";
  if (!schedulerAlreadyReady
      && await existingReplacement.count()
      && await page.locator("#postizMediaForm:visible").count() === 0) {
    await existingReplacement.click();
    await page.waitForSelector("#mediaReplacementPanel:not([hidden]) #postizMediaForm");
  }
  if (await page.locator("#postizMediaForm:visible").count()) {
    assert.equal(await page.locator("#schedulerHandoffForm").count(), 0, "Reel handoff must remain blocked without approved video");
    await capture(page, "qa_output/final_reel_media_gate_desktop.png");
    mediaAssetId = await registerSelectedReelMedia(page, authenticatedActor);
    if (selection.approvalNeeded) await page.waitForSelector("#approvalForm");
  }
  if (await page.locator("#approvalForm").count()) {
    assert.equal(await page.inputValue("#reviewerName"), authenticatedActor);
    assert.equal(await page.getAttribute("#reviewerName", "readonly"), "");
    await page.fill("#brandScore", "96");
    await page.check("#factCheck");
    await page.check("#privacyCheck");
    await page.check("#disclosureCheck");
    await page.fill("#approvalNotes", "Isolierter visueller Test der freigegebenen Reel-Version.");
    const [approvalResponse] = await Promise.all([
      page.waitForResponse(
        (response) => response.url().includes("/workflows/approve-content")
          && response.request().method() === "POST",
        { timeout: 60_000 },
      ),
      page.click('#approvalForm button[type="submit"]'),
    ]);
    assert.equal(approvalResponse.ok(), true, `approval returned HTTP ${approvalResponse.status()}`);
  } else {
    assert.equal(selection.approvalNeeded, false, "an item awaiting review must expose the approval form");
  }

  if (!mediaAssetId) {
    await page.waitForSelector("#postizMediaForm");
    assert.equal(await page.locator("#schedulerHandoffForm").count(), 0, "Reel handoff must remain blocked without approved video");
    await capture(page, "qa_output/final_reel_media_gate_desktop.png");
    mediaAssetId = await registerSelectedReelMedia(page, authenticatedActor);
  }

  await page.waitForSelector(".media-assets-summary .media-asset-card");
  await page.waitForSelector("#schedulerHandoffForm", { timeout: 30_000 });
  assert.equal(await page.locator("#schedulerHandoffForm").count(), 1, "approved Reel video must unlock governed handoff");
  assert.match(await page.textContent(".media-assets-summary"), /Bei Postiz exakt bestätigt/);
  assert.equal(await page.locator("[data-replace-media]").count(), 1);
  assert.equal(await page.locator("[data-show-media-revoke]").count(), 1);
  await capture(page, "qa_output/final_reel_media_ready_desktop.png");

  await page.click("[data-replace-media]");
  await page.waitForSelector("#mediaReplacementPanel:not([hidden]) #postizMediaForm");
  assert.equal(await page.inputValue("#mediaSupersedesAssetId"), mediaAssetId);
  await page.click("[data-cancel-media-replacement]");
  await page.click("[data-show-media-revoke]");
  const revokeForm = page.locator(".media-revoke-form").filter({ has: page.locator(`[data-media-action-result="${mediaAssetId}"]`) });
  await revokeForm.waitFor({ state: "visible" });
  await revokeForm.locator('textarea[name="reason"]').fill("Isolierter QA-Widerruf nach geprüfter Replace/Revoke-Darstellung.");
  await revokeForm.locator('button[type="submit"]').click();
  await page.waitForSelector("#postizMediaForm");
  assert.equal(await page.locator("#schedulerHandoffForm").count(), 0, "revoked video must lock Reel handoff again");
  await capture(page, "qa_output/final_reel_media_revoked_desktop.png");

  const performanceRecord = {
    content_id: contentId,
    review_window: "72h",
    action: "iterate",
    reason: "Isolierter Korrektur-UI-Nachweis",
    impressions: 1200,
    saves: 24,
    shares: 9,
    comments_from_target_buyers: 4,
    profile_visits: 76,
    clicks: 31,
    leads: 6,
    qualified_leads: 3,
    booked_calls: 1,
    pipeline_value_eur: 7500,
    landing_page_visits: 28,
    landing_page_conversions: 6,
    source_system: "manual",
    source_ref: "isolated-smoke:measurement-summary",
    period_start: "2026-07-01T08:00:00+00:00",
    period_end: "2026-07-04T08:00:00+00:00",
    retrieved_at: "2026-07-04T09:00:00+00:00",
    operator: authenticatedActor,
    attribution_rule: "Letzter belegter Kampagnenkontakt vor Lead-Erfassung",
    snapshot_sha256: "b".repeat(64),
    evidence: [
      { system: "Postiz", ref: "postiz-export-isolated-review", retrieved_at: "2026-07-04T09:00:00+00:00", sha256: "b".repeat(64), metric_fields: ["impressions", "saves", "shares", "comments_from_target_buyers", "profile_visits", "clicks"] },
      { system: "Matomo", ref: "landing-export-isolated-review", retrieved_at: "2026-07-04T09:00:00+00:00", sha256: "c".repeat(64), metric_fields: ["landing_page_visits", "landing_page_conversions"] },
      { system: "Twenty CRM", ref: "crm-export-isolated-review", retrieved_at: "2026-07-04T09:00:00+00:00", sha256: "d".repeat(64), metric_fields: ["leads", "qualified_leads", "booked_calls", "pipeline_value_eur"] },
    ],
    revision: 2,
    correction: {},
    request_fingerprint: "e".repeat(64),
    created_at: "2026-07-04T09:05:00+00:00",
  };
  await page.route("**/workflows/performance?limit=20", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [performanceRecord] }) });
  });
  await page.click('.side-nav [data-route="results"]');
  await page.waitForSelector("#analyticsEntryForm");
  assert.equal(await page.isChecked("#analyticsEvidenceEngagementEnabled"), true);
  assert.equal(await page.isDisabled("#analyticsEvidenceLandingRef"), true);
  await page.fill("#analyticsLandingVisits", "25");
  assert.equal(await page.isChecked("#analyticsEvidenceLandingEnabled"), true, "non-zero landing metric must open its evidence group");
  assert.equal(await page.isDisabled("#analyticsEvidenceLandingRef"), false);
  await capture(page, "qa_output/final_analytics_evidence_desktop.png");

  await page.locator("[data-correct-analytics]").first().click();
  await page.waitForSelector("#analyticsCorrectionPanel:not([hidden])");
  assert.equal(await page.inputValue("#analyticsContentId"), contentId);
  const analyticsContentLabel = await page.inputValue("#analyticsContentLabel");
  assert.ok(analyticsContentLabel, "analytics correction must show a business-facing content label");
  assert.notEqual(analyticsContentLabel, contentId, "the visible field must not expose the internal content ID");
  assert.equal(await page.inputValue("#analyticsImpressions"), "1200");
  assert.equal(await page.inputValue("#analyticsEvidenceCrmRef"), "crm-export-isolated-review");
  assert.equal(await page.inputValue("#analyticsOperator"), authenticatedActor);
  assert.equal(await page.inputValue("#analyticsCorrectionOperator"), authenticatedActor);
  assert.equal(await page.getAttribute("#analyticsCorrectionReason", "minlength"), "10");
  assert.match(await page.textContent("#analyticsCorrectionContext"), /Version 2/);
  await capture(page, "qa_output/final_analytics_correction_desktop.png");

  await page.setViewportSize({ width: 390, height: 844 });
  await page.click('.mobile-nav [data-route="approvals"]');
  await page.waitForSelector("#view-approvals.is-active");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  assert.ok(overflow <= 1, `mobile horizontal overflow: ${overflow}px`);
  await capture(page, "qa_output/final_reel_media_gate_mobile.png");

  await context.close();
  await browser.close();
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({
    status: "ok",
    baseUrl,
    screenshots: [
      "qa_output/final_reel_media_gate_desktop.png",
      "qa_output/final_reel_media_ready_desktop.png",
      "qa_output/final_reel_media_revoked_desktop.png",
      "qa_output/final_analytics_evidence_desktop.png",
      "qa_output/final_analytics_correction_desktop.png",
      "qa_output/final_reel_media_gate_mobile.png",
    ],
  }, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
