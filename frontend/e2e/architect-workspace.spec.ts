import { expect, test } from "@playwright/test";


test("architect can move from release intelligence to deployment planning", async ({ page }) => {
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

  await page.getByRole("link", { name: "Deployment planner" }).click();
  await expect(
    page.getByRole("heading", { name: "Turn evidence into an executable topology" }),
  ).toBeVisible();
  await expect(
    page.getByText("The plan will inherit its devices and policies."),
  ).toBeVisible();
});


test("workspace setup has no login or identity fields", async ({ page }) => {
  await page.goto("/#/workspaces");
  await expect(
    page.getByRole("heading", { name: "Describe the estate, not identities" }),
  ).toBeVisible();
  await expect(page.getByLabel(/email|password|username/i)).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Save workspace" })).toBeVisible();
});
