import { test, expect, Page } from "@playwright/test";
async function chooseSynthetic(page: Page) {
  await expect(
    page.getByRole("button", { name: "Reveal the overlooked" }),
  ).toBeEnabled();
  if (
    !(await page.locator(".data-mode").filter({ hasText: "SYNTHETIC" }).count())
  ) {
    await page.locator(".region-button").click();
    await page
      .locator(".region-dropdown button")
      .filter({ hasText: "synthetic data" })
      .click();
    await expect(page.locator(".data-mode")).toContainText("SYNTHETIC");
    await expect(page.locator(".loading-screen")).toHaveCount(0);
  }
}

test("complete discovery, evidence, simulation and durable investigation workflow", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (message) => {
    if (message.type() === "error" && message.text().includes("Worker"))
      errors.push(message.text());
  });
  await page.goto("/");
  await chooseSynthetic(page);
  await expect(
    page.getByRole("heading", { name: "Look beyond what’s mapped." }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Reveal the overlooked" }),
  ).toBeEnabled();
  await page.screenshot({
    path: "../../screenshots/01-overview.png",
    animations: "disabled",
  });
  await page.getByRole("button", { name: "Reveal the overlooked" }).click();
  await expect(page.locator(".evidence-heading h2")).toBeVisible();
  await expect(page.getByText("A changing settlement signal")).toBeVisible();
  await expect(page.locator(".growth-chart")).toBeVisible();
  await page.screenshot({
    path: "../../screenshots/02-evidence.png",
    animations: "disabled",
  });
  await page
    .getByRole("button", { name: "How the AI works", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "How the intelligence works." }),
  ).toBeVisible();
  await page.getByRole("button", { name: /Anomaly detection/ }).click();
  await expect(
    page.getByText("Regional anomaly percentile:", { exact: false }),
  ).toBeVisible();
  await page.screenshot({
    path: "../../screenshots/03-methodology.png",
    animations: "disabled",
  });
  await page.getByRole("button", { name: "Close dialog" }).click();
  await page
    .getByRole("button", { name: "What if care went to them?" })
    .click();
  await expect(
    page.getByText("HYPOTHETICAL INCREMENTAL COVERAGE"),
  ).toBeVisible();
  await expect(page.locator(".outreach-marker")).toHaveCount(1);
  await expect(page.locator(".outreach-marker")).toBeInViewport();
  await page.screenshot({
    path: "../../screenshots/04-outreach.png",
    animations: "disabled",
  });
  const stop = await page.locator(".outreach-marker").first().boundingBox();
  expect(stop).not.toBeNull();
  expect(stop!.width).toBeLessThan(50);
  if (stop) {
    const response = page.waitForResponse(
      (r) =>
        r.url().endsWith("/api/outreach/simulate") &&
        Boolean(r.request().postDataJSON()?.fixed_location),
    );
    await page.mouse.move(stop.x + 18, stop.y + 18);
    await page.mouse.down();
    await page.mouse.move(stop.x + 45, stop.y + 24, { steps: 8 });
    await page.mouse.up();
    const manual = await (await response).json();
    expect(manual.locations[0].manual).toBe(true);
    await expect(page.getByRole("status")).toContainText(
      "Alternative stop evaluated",
    );
  }

  await page.getByRole("button", { name: "Create investigation task" }).click();
  await page
    .getByPlaceholder("Context, questions, or local knowledge…")
    .fill("Browser integration test: verify records with local partners.");
  await page.getByRole("button", { name: "Save investigation task" }).click();
  await expect(page.getByRole("status")).toContainText(
    "Investigation task saved",
  );
  await page
    .getByRole("button", { name: "Investigation tasks", exact: true })
    .click();

  await expect(page.locator(".saved-task")).not.toHaveCount(0);
  const last = page.locator(".saved-task").first();
  await last.locator("select").selectOption("assigned");
  await expect(last.locator("select")).toHaveValue("assigned");
  await page.getByRole("button", { name: "Close dialog" }).click();
  await page.getByRole("button", { name: "Reset to original map" }).click();
  await expect(
    page.getByRole("button", { name: "Reveal the overlooked" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Start discovery" }).click();
  await expect(
    page.getByRole("heading", { name: "The world we think we know" }),
  ).toBeVisible();
  for (let i = 0; i < 3; i++)
    await page.getByRole("button", { name: "Next scene" }).click();
  await expect(
    page.getByRole("heading", { name: "Flip the script" }),
  ).toBeVisible();
  await expect(
    page.getByText("HYPOTHETICAL INCREMENTAL COVERAGE"),
  ).toBeVisible();
  await page.keyboard.press("ArrowLeft");
  await expect(
    page.getByRole("heading", { name: "The possible gap" }),
  ).toBeVisible();
  expect(errors).toEqual([]);
});
test("mobile layout keeps primary actions accessible", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await chooseSynthetic(page);
  await expect(
    page.getByRole("button", { name: "Reveal the overlooked" }),
  ).toBeEnabled();
  await page.getByRole("button", { name: "Reveal the overlooked" }).click();
  await expect(page.locator(".evidence-heading h2")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
  await page.screenshot({
    path: "../../screenshots/05-mobile.png",
    fullPage: true,
    animations: "disabled",
  });
});

test("acquired real source package preserves endpoint years and small-sample uncertainty", async ({
  page,
  request,
}) => {
  const data = await (await request.get("/api/regions")).json();
  const real = data.regions.find((r: any) => r.data_mode === "real");
  test.skip(!real, "Real source pack is not prepared in this installation");
  await page.goto("/");
  await expect(page.locator(".loading-screen")).toHaveCount(0);
  if (!(await page.locator(".data-mode").filter({ hasText: "REAL" }).count())) {
    await page.locator(".region-button").click();
    await page
      .locator(".region-dropdown button")
      .filter({ hasText: "real data" })
      .click();
  }
  await expect(page.locator(".data-mode")).toContainText("REAL DATA PACKAGE");
  await page.getByRole("button", { name: "Reveal the overlooked" }).click();
  await expect(page.locator(".evidence-heading h2")).toBeVisible();
  await expect(page.getByText("WorldPop model estimate, 2023")).toBeVisible();
  await expect(page.locator(".timeline-years button")).toHaveCount(2);
  await expect(page.locator(".chart-column")).toHaveCount(2);
  await expect(page.locator(".anomaly-row")).toContainText("Not evaluated");
  await page.screenshot({
    path: "../../screenshots/06-real-evidence.png",
    animations: "disabled",
  });
  // Turkana sample: at least one real candidate carries a gap category from the
  // settlement-registry comparison; the evidence panel shows it as a badge.
  await expect(page.locator(".gap-badge").first()).toBeVisible();
  await page
    .getByRole("button", { name: "How the AI works", exact: true })
    .click();
  await page.getByRole("button", { name: /Anomaly detection/ }).click();
  await expect(
    page.getByText("Anomaly model disabled:", { exact: false }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Close dialog" }).click();
  // Turkana candidates sit far beyond the 30-minute threshold, so a hypothetical
  // stop inside the network genuinely adds coverage; assert the positive result
  // honestly and its marker.
  const scenario = page.waitForResponse(r => r.url().endsWith("/api/outreach/simulate"));
  await page.getByRole("button", { name: "What if care went to them?" }).click();
  const result = await (await scenario).json();
  expect(result.summary.incremental_covered_population).toBeGreaterThan(0);
  await expect(page.getByRole("heading", { name: "Care, a little closer." })).toBeVisible();
  await expect(page.locator(".outreach-marker")).toHaveCount(1);
  await expect(page.locator(".outreach-marker")).toBeInViewport();
  await page.screenshot({ path: "../../screenshots/07-real-outreach.png", animations: "disabled" });
  // The satellite imagery basemap is a real raster layer on the same map.
  await expect(page.getByText("Imagery © Esri, Maxar, Earthstar Geographics")).toBeVisible();
  await page.getByRole("button", { name: /^Candidates/ }).click();
  await page.locator(".candidate-card").nth(1).click();
  const second = page.waitForResponse(r => r.url().endsWith("/api/outreach/simulate"));
  await page.getByRole("button", { name: "What if care went to them?" }).click();
  const secondResult = await (await second).json();
  expect(secondResult.summary.incremental_covered_population).toBeGreaterThan(0);
  await page.screenshot({ path: "../../screenshots/08-real-second-outreach.png", animations: "disabled" });
});
