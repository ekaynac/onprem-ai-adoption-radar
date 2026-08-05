import { expect, test } from "@playwright/test";


test("architect can move from release intelligence to hardware planning", async ({ page }) => {
  await page.goto("/#/overview");
  await expect(page.getByText("Architect Workspace")).toBeVisible();

  await page.getByRole("link", { name: "Release stream", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Every signal, with its trust state" }),
  ).toBeVisible();

  const firstRelease = page.locator(".release-table tbody a").first();
  if (await firstRelease.count()) {
    await firstRelease.click();
    await expect(page.getByText("Lifecycle timeline")).toBeVisible();
    await expect(page.getByText("Decision evidence")).toBeVisible();
  }

  await page.getByRole("link", { name: "Hardware" }).click();
  await expect(
    page.getByRole("heading", { name: "Infrastructure capacity catalog" }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Platforms you can buy and rack" }),
  ).toBeVisible();
});


test("static command center exposes no workspace mutation controls", async ({ page }) => {
  // Static mode ships the read-only demo stack profile — the alert
  // mechanism is demonstrable, but nothing is creatable or editable.
  await page.goto("/#/workspaces");
  await expect(
    page.getByRole("heading", { name: "Alerts are diffed against a stack" }),
  ).toBeVisible();
  await expect(page.getByText("Mega reference stack (demo)")).toBeVisible();
  await expect(page.getByLabel(/email|password|username/i)).toHaveCount(0);
  // The planner is read-only (precomputed fit grid) and ships in static mode.
  await expect(
    page.getByRole("link", { name: "Deployment planner" }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Save profile" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Save workspace" })).toHaveCount(0);
});
