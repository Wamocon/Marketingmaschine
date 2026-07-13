const assert = require("node:assert/strict");
const { AxeBuilder } = require("@axe-core/playwright");
const { chromium } = require("playwright");

const baseUrl = process.env.MARKETING_MACHINE_BASE_URL || "http://127.0.0.1:8080";
const mutationToken = (process.env.MARKETING_MACHINE_MUTATION_TOKEN || "").trim();
const authenticatedActor = (
  process.env.MARKETING_MACHINE_TEST_ACTOR
  || process.env.MARKETING_MACHINE_ACTOR
  || ""
).trim();
const edgeAttestation = (process.env.MARKETING_MACHINE_EDGE_ATTESTATION || "").trim();
const routes = ["overview", "studio", "approvals", "results", "setup"];
const wcagTags = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"];

function headers() {
  const values = {};
  if (mutationToken) values["X-WAMOCON-Mutation-Token"] = mutationToken;
  if (authenticatedActor) values["X-WAMOCON-Actor"] = authenticatedActor;
  if (edgeAttestation) values["X-WAMOCON-Edge-Attestation"] = edgeAttestation;
  return values;
}

function compactViolation(route, viewport, violation) {
  return {
    route,
    viewport,
    id: violation.id,
    impact: violation.impact || "unknown",
    help: violation.help,
    helpUrl: violation.helpUrl,
    targets: violation.nodes.map((node) => node.target),
  };
}

async function scan(page, route, viewport) {
  if (route !== "overview") {
    await page.click(`[data-route="${route}"]`);
  }
  await page.locator(`#view-${route}.is-active`).waitFor();
  await page.waitForTimeout(250);
  const result = await new AxeBuilder({ page }).withTags(wcagTags).analyze();
  return result.violations.map((violation) => compactViolation(route, viewport, violation));
}

async function main() {
  const browser = await chromium.launch();
  const context = await browser.newContext({
    extraHTTPHeaders: headers(),
    viewport: { width: 1440, height: 1000 },
  });
  const page = await context.newPage();
  const runtimeErrors = [];
  page.on("pageerror", (error) => runtimeErrors.push(`pageerror: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error") runtimeErrors.push(`console: ${message.text()}`);
  });

  await page.goto(`${baseUrl.replace(/\/+$/, "")}/ui`, { waitUntil: "domcontentloaded" });
  await page.locator("#overviewCampaigns .campaign-card").first().waitFor();

  const violations = [];
  for (const route of routes) {
    violations.push(...await scan(page, route, "desktop"));
  }

  await page.setViewportSize({ width: 390, height: 844 });
  await page.click('.mobile-nav [data-route="overview"]');
  violations.push(...await scan(page, "overview", "mobile"));

  await context.close();
  await browser.close();

  assert.deepEqual(runtimeErrors, [], `Browser runtime errors:\n${runtimeErrors.join("\n")}`);
  assert.deepEqual(
    violations,
    [],
    `WCAG A/AA violations:\n${JSON.stringify(violations, null, 2)}`,
  );
  console.log(JSON.stringify({
    status: "ok",
    baseUrl,
    routes,
    viewports: ["desktop", "mobile"],
    wcagTags,
    violations: 0,
  }, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
