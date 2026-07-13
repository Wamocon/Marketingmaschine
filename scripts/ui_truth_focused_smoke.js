"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function main() {
  const baseUrl = process.env.MARKETING_MACHINE_BASE_URL || "http://127.0.0.1:18120";
  const token = process.env.MARKETING_MACHINE_MUTATION_TOKEN || "";
  const actor = process.env.MARKETING_MACHINE_QA_ACTOR || "";
  const attestation = process.env.MARKETING_MACHINE_EDGE_ATTESTATION || "";
  assert(token && actor && attestation, "QA authentication environment is required");

  const outputDir = path.resolve(process.env.MARKETING_MACHINE_QA_OUTPUT || "qa_output");
  fs.mkdirSync(outputDir, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1280, height: 900 },
    extraHTTPHeaders: {
      "X-WAMOCON-Mutation-Token": token,
      "X-WAMOCON-Actor": actor,
      "X-WAMOCON-Edge-Attestation": attestation,
    },
  });
  const page = await context.newPage();
  const pageErrors = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));

  try {
    await page.goto(`${baseUrl}/ui#studio`, { waitUntil: "networkidle" });
    await page.locator('[data-pick-campaign="k1"]').click();
    const campaignSummary = page.locator("#studioCampaignSummary");
    await campaignSummary.waitFor({ state: "visible" });
    assert((await campaignSummary.innerText()).includes("K1"), "selected campaign is not visible in Studio");

    await page.locator('input[name="trendPlatform"]').evaluateAll((checkboxes) => {
      checkboxes.forEach((checkbox) => {
        checkbox.checked = false;
        checkbox.dispatchEvent(new Event("change", { bubbles: true }));
      });
    });
    assert(await page.locator("#runTrendScan").isDisabled(), "empty source selection did not block research");
    assert(
      (await page.locator("#trendSourceGate").innerText()).includes("Mindestens eine"),
      "empty source selection did not show a business-readable explanation",
    );

    await page.keyboard.press("Tab");
    const focusedControl = page.locator(":focus-visible");
    assert(await focusedControl.count(), "keyboard navigation did not create a visible focus target");
    const focusStyle = await focusedControl.first().evaluate((element) => ({
      outline: getComputedStyle(element).outlineStyle,
      shadow: getComputedStyle(element).boxShadow,
    }));
    assert(focusStyle.outline !== "none" && focusStyle.shadow !== "none", "keyboard focus is not visibly styled");
    await page.screenshot({ path: path.join(outputDir, "ui_truth_studio.png"), fullPage: true });

    await page.route("**/workflows/states?limit=100", (route) => route.abort("failed"));
    await page.locator('[data-route="approvals"]').first().click();
    await page.waitForFunction(() => document.querySelector("#reviewCount")?.textContent === "–");
    assert((await page.locator("#reviewCount").innerText()) === "–", "failed approval load was presented as a numeric count");
    assert(
      (await page.locator("#reviewDetail").innerText()).includes("Arbeitsstand unbekannt"),
      "failed approval load did not present an unknown state",
    );
    assert(pageErrors.length === 0, `browser reported errors: ${pageErrors.join("; ")}`);
  } finally {
    await browser.close();
  }
}

main().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
