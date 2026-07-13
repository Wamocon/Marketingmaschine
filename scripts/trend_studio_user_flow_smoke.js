const assert = require("node:assert/strict");
const { chromium } = require("playwright");

const baseUrl = process.env.MARKETING_MACHINE_BASE_URL || "http://127.0.0.1:18118";

async function main() {
  assert.equal(
    String(process.env.MARKETING_MACHINE_ISOLATED_CANDIDATE || "").toLowerCase(),
    "true",
    "this browser flow creates trend/content records; set MARKETING_MACHINE_ISOLATED_CANDIDATE=true only for a disposable candidate",
  );
  const parsedTarget = new URL(baseUrl);
  assert.ok(!["8117", "18117"].includes(parsedTarget.port), "record-creating browser smoke is forbidden on production ports");
  const healthResponse = await fetch(`${baseUrl}/healthz`);
  assert.equal(healthResponse.ok, true, "candidate health marker is unavailable");
  const health = await healthResponse.json();
  assert.equal(health?.instance?.mode, "isolated-candidate", "target is not an isolated candidate");
  assert.equal(health?.instance?.disposable_data, true, "candidate data is not attested disposable");
  assert.match(String(health?.instance?.data_namespace || ""), /^candidate-/i);
  const browser = await chromium.launch();
  const mutationToken = (process.env.MARKETING_MACHINE_MUTATION_TOKEN || "").trim();
  const authenticatedActor = (process.env.MARKETING_MACHINE_TEST_ACTOR || process.env.MARKETING_MACHINE_ACTOR || "").trim();
  const edgeAttestation = (process.env.MARKETING_MACHINE_EDGE_ATTESTATION || "").trim();
  assert.ok(authenticatedActor, "MARKETING_MACHINE_TEST_ACTOR is required for the authenticated Studio flow");
  assert.ok(edgeAttestation, "MARKETING_MACHINE_EDGE_ATTESTATION is required for the authenticated Studio flow");
  const extraHTTPHeaders = {
    "X-WAMOCON-Actor": authenticatedActor,
    "X-WAMOCON-Edge-Attestation": edgeAttestation,
  };
  if (mutationToken) extraHTTPHeaders["X-WAMOCON-Mutation-Token"] = mutationToken;
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    extraHTTPHeaders,
  });
  const page = await context.newPage();
  const errors = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(`console: ${message.text()}`);
  });
  page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));

  await page.goto(`${baseUrl}/ui`, { waitUntil: "domcontentloaded" });
  await page.waitForSelector("#overviewCampaigns .campaign-card");
  await page.click('[data-route="studio"]');
  await page.waitForSelector('[data-stage="1"].is-active');
  await page.click('#studioCampaignPicker [data-pick-campaign="k1"]');
  await page.click("#toResearch");
  await page.waitForSelector('[data-stage="2"].is-active');

  const [researchResponse] = await Promise.all([
    page.waitForResponse(
      (response) => response.url().includes("/workflows/trend-research") && response.request().method() === "POST",
      { timeout: 180000 },
    ),
    page.click("#runTrendScan"),
  ]);
  assert.equal(researchResponse.ok(), true, `research returned HTTP ${researchResponse.status()}`);
  await page.waitForFunction(
    () => document.querySelector("#researchProgress")?.classList.contains("is-hidden"),
    null,
    { timeout: 180000 },
  );
  const usableTrends = page.locator('[data-select-trend]:not([disabled])');
  const usableCount = await usableTrends.count();

  if (!usableCount) {
    const gate = (await page.textContent("#researchGate")) || "";
    assert.match(gate, /Keine|gesperrt|verifiziert/i);
    const trendText = (await page.textContent("#trendResults")) || "";
    const citationUrls = await page.locator("#trendResults .citation a").evaluateAll(
      (links) => links.map((link) => link.href),
    );
    for (const value of citationUrls) {
      const url = new URL(value);
      assert.ok(["http:", "https:"].includes(url.protocol));
      assert.doesNotMatch(url.hostname, /^(localhost|0\.0\.0\.0|127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/i);
    }
    if (/Evergreen-Hinweis/.test(trendText)) {
      assert.match(trendText, /0 externe Quellen/);
      assert.doesNotMatch(trendText, /\binternal\b/i);
      assert.equal(citationUrls.length, 0);
    }
    await page.waitForTimeout(500);
    await page.screenshot({ path: "qa_output/live_source_gate.png", fullPage: true });
    await context.close();
    await browser.close();
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({
      status: "source_gate_blocked_truthfully",
      baseUrl,
      usableTrends: 0,
      gate,
      screenshot: "qa_output/live_source_gate.png",
    }, null, 2));
    return;
  }

  await usableTrends.first().click();
  await page.click("#toIdeas");
  await page.waitForSelector('[data-stage="3"].is-active');
  await page.fill("#trendUserPrompt", "Sachliches Q&A mit klarer Bildschirmaufnahme und ruhigem Tempo.");
  await page.click("#generateConcepts");
  await page.waitForSelector("#conceptResults .concept-card", { timeout: 60000 });
  assert.equal(await page.locator("#conceptResults .concept-card").count(), 4);
  await page.locator("[data-select-variant]").first().click();
  await page.click("#toReview");
  await page.waitForSelector('[data-stage="4"].is-active');
  await page.click("#approveConcept");
  await page.waitForSelector('#view-approvals.is-active [data-review-id]', { timeout: 180000 });
  const selected = page.locator('[data-review-id].is-selected').first();
  await selected.waitFor({ state: "visible" });
  const contentId = await selected.getAttribute("data-review-id");
  assert.match(contentId || "", /^content-concept-/);
  assert.match((await page.textContent("#reviewDetail")) || "", /Entstehung/);
  assert.match((await page.textContent("#reviewDetail")) || "", /Quellen & Belege/);
  assert.equal(await page.locator('#approvalForm button[type="submit"]:not([disabled])').count(), 1);

  await page.screenshot({ path: "qa_output/live_trend_to_review.png", fullPage: true });
  await context.close();
  await browser.close();
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({
    status: "verified_trend_draft_waiting_for_human_review",
    baseUrl,
    usableTrends: usableCount,
    contentId,
    screenshot: "qa_output/live_trend_to_review.png",
  }, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
