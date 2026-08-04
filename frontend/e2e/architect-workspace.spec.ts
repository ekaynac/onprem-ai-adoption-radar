import { expect, test } from "@playwright/test";


test("architect can move from release intelligence to hardware planning", async ({ page }) => {
  await page.goto("/");
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
    page.getByText("Accelerators, memory topology, and deployment-fit evidence."),
  ).toBeVisible();
});


test("static command center exposes no workspace mutation controls", async ({ page }) => {
  await page.goto("/#/workspaces");
  await expect(page).toHaveURL(/#\/overview$/);
  await expect(page.getByLabel(/email|password|username/i)).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Workspace profiles" })).toHaveCount(0);
  // The planner is read-only (precomputed fit grid) and ships in static mode.
  await expect(
    page.getByRole("link", { name: "Deployment planner" }),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Save workspace" })).toHaveCount(0);
});
