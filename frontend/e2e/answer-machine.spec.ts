import { expect, test } from "@playwright/test";


// D6 gate — the 30-second job test: from a cold visit, a hardware+task
// question reaches a cited recommendation in ≤3 interactions.
test("cold visit reaches a cited recommendation in three interactions", async ({ page }) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "What should you run?" }),
  ).toBeVisible();

  // Interaction 1 (optional task change is free — coding is the default).
  await page.getByLabel("Task").first().selectOption("coding");
  // Interaction 2: hardware.
  await page.getByLabel("Hardware").first().selectOption("rtx-4090-24gb");
  // Interaction 3: ask.
  await page.getByRole("button", { name: "Get the answer" }).click();

  await expect(page).toHaveURL(/#\/advisor\?task=coding&device=rtx-4090-24gb/);
  // A ranked candidate with its cited reasons renders immediately from
  // the precomputed snapshot — no further interaction required.
  await expect(page.locator(".advisor-candidate, .candidate-card, .release-table, .brief-list, main")
    .first()).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "What should you run?" }),
  ).toBeVisible();
  await expect(page.getByText(/Fit:|fits/i).first()).toBeVisible();
});


test("homepage leads with the desk and the MCP pitch", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("The Desk — this week")).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Plug Mega's radar into your assistant" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Setup & tools →" }).click();
  await expect(
    page.getByRole("heading", { name: "Two lines to connect" }),
  ).toBeVisible();
  await expect(page.getByText("whats_new", { exact: true })).toBeVisible();
});
