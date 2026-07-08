const assert = require("node:assert/strict");
const { chromium } = require("playwright");

const baseUrl = process.env.MARKETING_MACHINE_BASE_URL || "http://127.0.0.1:8080";

async function main() {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const consoleErrors = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(error.message));

  await page.goto(`${baseUrl}/ui`, { waitUntil: "networkidle" });
  await page.waitForSelector("#screen-dashboard.active", { state: "visible" });

  await page.click('[data-open-routes="true"]');
  await page.waitForSelector("#routeBackdrop.open", { state: "visible" });
  await page.click('#routeBackdrop [data-jump="trends"]');
  await page.waitForSelector("#screen-trends.active", { state: "visible" });

  await page.click("#runTrendScan");
  await page.waitForSelector("#trendCampaigns .trend-item", { state: "visible", timeout: 15000 });
  assert.match(await page.textContent("#trendRunResult"), /Scan ID:/);

  await page.click("#trendCampaigns .trend-item");
  assert.match(await page.textContent("#trendConceptResult"), /Selected idea:/);

  await page.fill("#trendUserPrompt", "Mehr Q&A, staerkere Kinetic Captions und ein klarerer Einstieg fuer Instagram.");
  await page.click("#generateTrendConcept");
  await page.waitForFunction(() => document.querySelector("#trendConceptResult")?.textContent.includes("Best options:"), null, { timeout: 15000 });
  assert.match(await page.textContent("#trendConceptResult"), /Q&A/);

  await page.click("#approveTrendConcept");
  await page.waitForFunction(() => document.querySelector("#trendConceptResult")?.textContent.includes("Sent to review:"), null, { timeout: 15000 });

  const contentId = await page.inputValue("#approvalContentId");
  assert.match(contentId, /^reel-concept-/);

  await page.click('[data-open-routes="true"]');
  await page.waitForSelector("#routeBackdrop.open", { state: "visible" });
  await page.click('#routeBackdrop [data-jump="approval"]');
  await page.waitForSelector("#screen-approval.active", { state: "visible" });
  assert.equal(await page.inputValue("#approvalContentId"), contentId);
  assert.match(await page.textContent("#postPreview"), /Instagram-Reel-Entwurf/);

  await page.click('#approvalForm button[type="submit"]');
  await page.waitForFunction(() => document.querySelector("#approvalResult")?.textContent.includes("bereit zur Planung"), null, { timeout: 15000 });
  assert.match(await page.textContent("#schedulerPreview"), /Entwurf, finale Plattformfreigabe/);

  await page.screenshot({ path: "qa_output/trend_studio_user_flow.png", fullPage: true });
  await browser.close();

  assert.deepEqual(consoleErrors, []);
  console.log(JSON.stringify({ status: "ok", contentId, screenshot: "qa_output/trend_studio_user_flow.png" }, null, 2));
}

main().catch(async (error) => {
  console.error(error);
  process.exit(1);
});
