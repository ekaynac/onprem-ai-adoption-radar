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
  expect(await rss.text()).toContain("<rss");

  const firstRelease = page.locator(".release-table tbody a").first();
  if (await firstRelease.count()) {
    await firstRelease.click();
    await expect(page.getByText("Lifecycle timeline")).toBeVisible();
  }
});
