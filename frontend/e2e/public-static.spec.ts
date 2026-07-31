import { expect, test } from "@playwright/test";


test("public static command center navigates without a backend", async ({ page }) => {
  await page.goto("/");

  await expect(
    page.getByRole("heading", { name: "What changed since your last visit" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Catalog" }).click();
  await expect(
    page.getByRole("heading", {
      name: "Models, evidence, and deployment posture",
    }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Release stream" }).click();
  await expect(
    page.getByRole("heading", { name: "Every signal, with its trust state" }),
  ).toBeVisible();

  const rss = await page.request.get("/changes.rss");
  expect(rss.ok()).toBeTruthy();
  const rssText = await rss.text();
  expect(rssText).toContain("<rss");
  expect(rssText).toContain("<item>");

  const jsonFeed = await page.request.get("/changes.json");
  expect(jsonFeed.ok()).toBeTruthy();
  expect((await jsonFeed.json()).items.length).toBeGreaterThan(0);

  for (const feed of [
    "/changes.xml",
    "/changes-models.xml",
    "/changes-research.xml",
    "/digests/digest.xml",
    "/digests/digest-rss.xml",
  ]) {
    expect((await page.request.get(feed)).ok(), feed).toBeTruthy();
  }

  const firstRelease = page.locator(".release-table tbody a").first();
  if (await firstRelease.count()) {
    await firstRelease.click();
    await expect(page.getByText("Lifecycle timeline")).toBeVisible();
  }
});


test("public static command center preserves deep project and evidence surfaces", async ({ page }) => {
  await page.goto("/#/projects");
  await expect(
    page.getByRole("heading", {
      name: "The open-source systems behind on-prem AI",
    }),
  ).toBeVisible();
  await expect(page.locator(".intelligence-card").first()).toBeVisible();
  await page.getByRole("link", { name: "Open intelligence" }).first().click();
  await expect(page.getByText("Why it matters")).toBeVisible();
  await expect(page.getByRole("link", { name: /Open GitHub repository/ })).toBeVisible();

  await page.getByRole("link", { name: "Research" }).click();
  await expect(
    page.getByRole("heading", { name: "Techniques with operational consequence" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Open research" }).first().click();
  await expect(page.getByRole("heading", { name: "Papers" })).toBeVisible();
  await expect(page.getByRole("link", { name: /arXiv:/ }).first()).toBeVisible();

  await page.getByRole("link", { name: "Hardware", exact: true }).click();
  await page.locator(".intelligence-card").first().click();
  await expect(page.getByRole("heading", { name: "Infrastructure specification" })).toBeVisible();
  await expect(page.locator("pre.record-view")).toHaveCount(0);
});
