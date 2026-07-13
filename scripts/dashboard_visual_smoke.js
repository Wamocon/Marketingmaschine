const assert = require("node:assert/strict");
const { chromium } = require("playwright");

const baseUrl = process.env.MARKETING_MACHINE_BASE_URL || "http://127.0.0.1:8080";
const reviewWindows = ["72h", "7d", "14d", "30d"];
const forbiddenDemoPattern = /Mock QA|Smoke Test|Campaign-only signal|placeholder/i;
const allowDegradedIntegrations = String(
  process.env.MARKETING_MACHINE_ALLOW_DEGRADED_CANDIDATE_VISUAL || "",
).toLowerCase() === "true";
const mutationToken = (process.env.MARKETING_MACHINE_MUTATION_TOKEN || "").trim();
const authenticatedActor = (process.env.MARKETING_MACHINE_TEST_ACTOR || process.env.MARKETING_MACHINE_ACTOR || "").trim();
const edgeAttestation = (process.env.MARKETING_MACHINE_EDGE_ATTESTATION || "").trim();

function absoluteUrl(path) {
  return new URL(path, `${baseUrl.replace(/\/+$/, "")}/`).toString();
}

function matchesGet(response, path) {
  if (response.request().method() !== "GET") return false;
  const actual = new URL(response.url());
  const expected = new URL(path, "http://contract.local");
  if (actual.pathname !== expected.pathname) return false;
  return [...expected.searchParams.entries()].every(([key, value]) => actual.searchParams.get(key) === value);
}

function waitForGet(page, path) {
  return page.waitForResponse((response) => matchesGet(response, path));
}

function assertSuccessfulBrowserGet(response, label) {
  assert.ok(
    response.ok(),
    `${label} GET returned HTTP ${response.status()} (${new URL(response.url()).pathname})`,
  );
}

async function assertSuccessfulApiGet(context, path, label) {
  const response = await context.request.get(absoluteUrl(path));
  assert.ok(response.ok(), `${label} GET returned HTTP ${response.status()} (${path})`);
  return response.json();
}

function coreGetLabel(response) {
  if (response.request().method() !== "GET") return "";
  const url = new URL(response.url());
  if (url.pathname === "/campaigns") return "campaigns";
  if (url.pathname === "/workflows/states") return "workflow states";
  if (url.pathname === "/integrations/status") return "integration status";
  if (url.pathname === "/workflows/phase-status") return "phase/readiness status";
  if (url.pathname === "/workflows/outbox") return "outbox";
  if (url.pathname === "/workflows/analytics/due") return `analytics due (${url.searchParams.get("review_window") || "unknown"})`;
  if (url.pathname === "/readyz") return "authentication readiness";
  return "";
}

async function observe(page, errors) {
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(`console: ${message.text()}`);
  });
  page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
  page.on("response", (response) => {
    const label = coreGetLabel(response);
    if (label && !response.ok()) errors.push(`response: ${label} HTTP ${response.status()} ${response.url()}`);
  });
  page.on("requestfailed", (request) => {
    const url = request.url();
    errors.push(`requestfailed: ${url} ${request.failure()?.errorText || ""}`);
  });
}

async function main() {
  const browser = await chromium.launch();
  const extraHTTPHeaders = {};
  if (mutationToken) extraHTTPHeaders["X-WAMOCON-Mutation-Token"] = mutationToken;
  if (authenticatedActor) extraHTTPHeaders["X-WAMOCON-Actor"] = authenticatedActor;
  if (edgeAttestation) extraHTTPHeaders["X-WAMOCON-Edge-Attestation"] = edgeAttestation;
  const context = await browser.newContext({
    extraHTTPHeaders,
  });
  const errors = [];

  if (allowDegradedIntegrations) {
    const health = await assertSuccessfulApiGet(context, "/healthz", "candidate health marker");
    assert.equal(health.instance?.mode, "isolated-candidate");
    assert.equal(health.instance?.disposable_data, true);
    assert.match(String(health.instance?.data_namespace || ""), /^candidate-/i);
  }

  const authenticationReadiness = await assertSuccessfulApiGet(context, "/readyz", "authentication readiness");
  assert.equal(authenticationReadiness.status, "ready", "authentication readiness is degraded");
  assert.equal(authenticationReadiness.mutation_authorization?.safe, true, "mutation authorization is not safe");
  assert.equal(authenticationReadiness.mutation_authorization?.status, "protected", "mutation authorization is not protected");
  assert.equal(authenticationReadiness.actor_authentication?.safe, true, "actor authentication is not safe");
  const session = await assertSuccessfulApiGet(context, "/session", "authenticated operator session");
  assert.equal(session.authenticated, true, "operator session is not authenticated");
  assert.equal(session.authentication, "edge_attested", "operator session is not edge-attested");
  if (authenticatedActor) assert.equal(session.actor, authenticatedActor, "session actor does not match the smoke actor");

  const desktop = await context.newPage();
  await desktop.setViewportSize({ width: 1440, height: 1000 });
  await observe(desktop, errors);
  const initialCampaignsResponse = waitForGet(desktop, "/campaigns");
  const initialStatesResponse = waitForGet(desktop, "/workflows/states?limit=100");
  const initialPhaseResponse = waitForGet(desktop, "/workflows/phase-status");
  await desktop.goto(`${baseUrl}/ui`, { waitUntil: "domcontentloaded" });
  const initialResponses = await Promise.all([
    initialCampaignsResponse,
    initialStatesResponse,
    initialPhaseResponse,
  ]);
  ["campaigns", "workflow states", "phase/readiness status"].forEach((label, index) => {
    assertSuccessfulBrowserGet(initialResponses[index], label);
  });
  await desktop.waitForSelector("#overviewCampaigns .campaign-card");
  assert.equal(await desktop.locator("#overviewCampaigns .campaign-card").count(), 5);
  assert.equal(forbiddenDemoPattern.test("content-concept-k1"), false, "legitimate content-concept IDs must not match the demo filter");
  assert.match(await desktop.textContent("body"), /Fünf echte Kampagnen/);
  assert.doesNotMatch(
    await desktop.textContent("#recentWork"),
    forbiddenDemoPattern,
    "known demo/placeholder records must stay hidden without rejecting legitimate reel-concept IDs",
  );
  await desktop.screenshot({ path: "qa_output/final_dashboard_desktop.png", fullPage: true, animations: "disabled" });

  await desktop.click('[data-route="studio"]');
  await desktop.waitForSelector('[data-stage="1"].is-active');
  assert.equal(await desktop.locator("#studioCampaignPicker .pick-card").count(), 5);
  await desktop.click('#studioCampaignPicker [data-pick-campaign="k1"]');
  assert.equal(await desktop.getAttribute('#studioCampaignPicker [data-pick-campaign="k1"]', "aria-pressed"), "true");
  if (await desktop.isEnabled("#toResearch")) {
    await desktop.click("#toResearch");
    await desktop.waitForSelector('[data-stage="2"].is-active');
    await desktop.waitForTimeout(350);
    assert.match(await desktop.textContent("#researchGate"), /Ohne verifizierte Quellen/);
  } else {
    assert.equal(
      allowDegradedIntegrations,
      true,
      "research navigation is disabled even though degraded-candidate evidence was not allowed",
    );
    assert.match(
      await desktop.textContent("#businessGuard"),
      /Neue Erstellung pausiert|öffentliche Recherchequelle fehlt/i,
      "a disabled research action must have a business-readable explanation",
    );
  }
  await desktop.screenshot({ path: "qa_output/final_content_studio_desktop.png", fullPage: true, animations: "disabled" });

  const approvalOutboxResponse = waitForGet(desktop, "/workflows/outbox?limit=100");
  await desktop.click('.side-nav [data-route="approvals"]');
  assertSuccessfulBrowserGet(await approvalOutboxResponse, "outbox");
  await desktop.waitForSelector("#view-approvals.is-active #reviewQueue .queue-item");
  const reviewAttentionCount = await desktop.locator("#reviewQueue .queue-item").filter({ hasText: /Freigabe nötig|Überarbeitung|Beleg fehlt|Blockiert/ }).count();
  const readyToScheduleCount = await desktop.locator("#reviewQueue .queue-item").filter({ hasText: "Bereit zur Planung" }).count();
  assert.equal(
    Number(await desktop.textContent("#navReviewCount")),
    reviewAttentionCount + readyToScheduleCount,
    "the review badge must include review blockers and every approved item awaiting planning",
  );
  // A fresh isolated candidate has no historical remediation record. Blocked
  // items, when present, are already included in the attention-count check.
  const mediaBlockedHandoff = desktop.locator('#reviewQueue .queue-item[data-media-ready="false"]', { hasText: "Bereit zur Planung" }).first();
  if (await mediaBlockedHandoff.count()) {
    await mediaBlockedHandoff.click();
    await desktop.waitForSelector("#postizMediaForm");
    assert.equal(await desktop.locator("#schedulerHandoffForm").count(), 0, "a Reel without approved video must not expose Postiz handoff");
    assert.match(await desktop.textContent("#reviewDetail"), /Benannte Person ordnet das freigegebene Video zu/i);
    assert.match(await desktop.textContent("#reviewDetail"), /Video selbst bleibt in der Postiz-Medienbibliothek/i);
  }
  const handoffReady = desktop.locator('#reviewQueue .queue-item:not([data-media-ready="false"])', { hasText: "Bereit zur Planung" }).first();
  if (await handoffReady.count()) {
    await handoffReady.click();
    await desktop.waitForSelector("#reviewDetail .handoff-action");
    if (await desktop.locator("#schedulerHandoffForm").count()) {
      assert.equal((await desktop.textContent("#routeSchedulerDraft")).trim(), "In Postiz als Entwurf übergeben");
      assert.match(await desktop.textContent("#reviewDetail .handoff-action"), /Nur Vorschau|Externe Entwurfsübergabe bereit/);
    } else {
      assert.ok(await desktop.locator('#reviewDetail [data-reconcile-postiz]').count(), "an attempted Postiz handoff must offer reconciliation");
      assert.equal(await desktop.locator("#routeSchedulerDraft").count(), 0, "delivery-unknown/sent handoffs must not offer blind resend");
    }
  }
  const approvable = desktop.locator("#reviewQueue .queue-item", { hasText: "Freigabe nötig" }).first();
  await approvable.click();
  await desktop.waitForSelector("#approvalForm");
  assert.equal(await desktop.inputValue("#brandScore"), "");
  assert.equal(await desktop.getAttribute("#brandScore", "required"), "");
  // Playwright may scroll the selected queue card to click it. Reset before a
  // full-page capture so sticky navigation does not obscure the page heading.
  await desktop.evaluate(() => window.scrollTo(0, 0));
  await desktop.waitForTimeout(500);
  await desktop.screenshot({ path: "qa_output/final_approval_desktop.png", fullPage: true, animations: "disabled" });

  const resultsOutboxResponse = waitForGet(desktop, "/workflows/outbox?limit=20");
  const analyticsDueResponses = reviewWindows.map((reviewWindow) => (
    waitForGet(desktop, `/workflows/analytics/due?review_window=${encodeURIComponent(reviewWindow)}`)
  ));
  await desktop.click('.side-nav [data-route="results"]');
  assertSuccessfulBrowserGet(await resultsOutboxResponse, "outbox");
  const resolvedDueResponses = await Promise.all(analyticsDueResponses);
  resolvedDueResponses.forEach((response, index) => {
    assertSuccessfulBrowserGet(response, `analytics due (${reviewWindows[index]})`);
  });
  await desktop.waitForSelector("#view-results.is-active #analyticsEntryForm");
  assert.match(await desktop.textContent("#view-results"), /Übergabeprotokoll/i);
  assert.match(await desktop.textContent("#view-results"), /Fällige Auswertungen/);
  assert.equal(await desktop.getAttribute("#analyticsContentId", "type"), "hidden");
  assert.equal(await desktop.getAttribute("#analyticsSourceRef", "type"), "hidden");
  assert.equal(await desktop.getAttribute("#analyticsContentLabel", "required"), "");
  assert.equal(await desktop.getAttribute("#analyticsContentLabel", "readonly"), "");
  assert.equal(await desktop.getAttribute("#analyticsOperator", "required"), "");
  assert.equal(await desktop.getAttribute("#analyticsAttributionRule", "required"), "");
  assert.equal(await desktop.getAttribute("#analyticsSnapshotSha256", "type"), "hidden");
  assert.equal(await desktop.getAttribute("#analyticsSnapshotSha256", "pattern"), null);
  assert.match(await desktop.textContent("#analyticsEntryPanel"), /Quelle: manuell/);
  assert.equal(await desktop.locator(".analytics-evidence-card").count(), 3);
  assert.equal(await desktop.isChecked("#analyticsEvidenceEngagementEnabled"), true);
  assert.equal(await desktop.getAttribute("#analyticsEvidenceEngagementSha256", "type"), "hidden");
  assert.equal(await desktop.getAttribute("#analyticsEvidenceEngagementSha256", "pattern"), null);
  assert.equal(await desktop.locator("#analyticsCorrectionPanel:not([hidden])").count(), 0);
  const unknownHandoffs = desktop.locator("#outboxList .handoff-record.needs-reconciliation");
  if (await unknownHandoffs.count()) {
    assert.ok(await unknownHandoffs.first().locator("[data-reconcile-postiz]").count(), "delivery_unknown must offer a read-only Postiz reconciliation");
    assert.match(await unknownHandoffs.first().textContent(), /Nicht erneut senden/);
  }

  const integrationStatus = await assertSuccessfulApiGet(context, "/integrations/status", "integration status");
  if (!allowDegradedIntegrations) {
    assert.equal(integrationStatus.status, "ok", "required integration readiness is degraded");
  } else {
    assert.ok(["ok", "degraded"].includes(integrationStatus.status));
  }
  const setupPhaseResponse = waitForGet(desktop, "/workflows/phase-status");
  await desktop.click('.side-nav [data-route="setup"]');
  const setupPhase = await setupPhaseResponse;
  assertSuccessfulBrowserGet(setupPhase, "phase/readiness status");
  const setupPhasePayload = await setupPhase.json();
  if (!allowDegradedIntegrations) {
    assert.notEqual(setupPhasePayload.status, "blocked", "critical workflow readiness is blocked");
    assert.equal(setupPhasePayload.integrations?.status, "ok", "Setup reports degraded required integrations");
  }
  await desktop.waitForSelector("#view-setup.is-active #readinessSummary .readiness-card");
  assert.equal(await desktop.locator("#readinessSummary .readiness-card").count(), 3);
  if (!allowDegradedIntegrations) {
    assert.equal(
      await desktop.locator("#globalHealth .signal-ok").count(),
      1,
      `Setup readiness is degraded: ${(await desktop.textContent("#globalHealth")).trim()}`,
    );
  }
  await desktop.waitForTimeout(700);
  await desktop.screenshot({ path: "qa_output/final_setup_desktop.png", fullPage: true, animations: "disabled" });

  const mobile = await context.newPage();
  await mobile.setViewportSize({ width: 390, height: 844 });
  await observe(mobile, errors);
  const mobileCampaignsResponse = waitForGet(mobile, "/campaigns");
  const mobileStatesResponse = waitForGet(mobile, "/workflows/states?limit=100");
  const mobilePhaseResponse = waitForGet(mobile, "/workflows/phase-status");
  await mobile.goto(`${baseUrl}/ui`, { waitUntil: "domcontentloaded" });
  const mobileResponses = await Promise.all([
    mobileCampaignsResponse,
    mobileStatesResponse,
    mobilePhaseResponse,
  ]);
  ["mobile campaigns", "mobile workflow states", "mobile phase/readiness status"].forEach((label, index) => {
    assertSuccessfulBrowserGet(mobileResponses[index], label);
  });
  await mobile.waitForSelector("#overviewCampaigns .campaign-card");
  assert.equal(await mobile.locator(".mobile-nav button").count(), 5);
  const overflow = await mobile.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  assert.ok(overflow <= 1, `mobile horizontal overflow: ${overflow}px`);
  await mobile.screenshot({ path: "qa_output/final_dashboard_mobile.png", fullPage: true, animations: "disabled" });

  await context.close();
  await browser.close();
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({
    status: "ok",
    baseUrl,
    screenshots: [
      "qa_output/final_dashboard_desktop.png",
      "qa_output/final_content_studio_desktop.png",
      "qa_output/final_approval_desktop.png",
      "qa_output/final_setup_desktop.png",
      "qa_output/final_dashboard_mobile.png",
    ],
  }, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
