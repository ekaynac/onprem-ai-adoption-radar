import axe from "axe-core";
import { expect, test } from "@playwright/test";

// Runs against the exported site (`radar pulse export --out _site`).

test("the published site renders all four lanes from pulse.v1.json", async ({ page }) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "New models, papers, repositories and news" }),
  ).toBeVisible();
  for (const id of ["model", "paper", "repo", "news"]) {
    await expect(page.locator(`#pulse-lane-${id}`)).toBeVisible();
  }
  await expect(page.getByRole("contentinfo")).toContainText("Mega Bilgisayar");
});


test("every feed is valid RSS with items", async ({ page }) => {
  for (const feed of ["pulse.xml", "pulse-models.xml", "pulse-papers.xml", "pulse-repos.xml", "pulse-news.xml"]) {
    const response = await page.request.get(`/${feed}`);
    expect(response.ok(), feed).toBeTruthy();
    const text = await response.text();
    expect(text, feed).toContain("<rss");
  }
});


test("the page has no serious accessibility violations", async ({ page }) => {
  await page.goto("/");
  await page.locator("#pulse-lane-news").waitFor();
  await page.addScriptTag({ content: axe.source });
  const violations = await page.evaluate(async () => {
    // @ts-expect-error injected above
    const result = await window.axe.run(document, { resultTypes: ["violations"] });
    return result.violations
      .filter((v: { impact: string }) => v.impact === "serious" || v.impact === "critical")
      .map((v: { id: string }) => v.id);
  });
  expect(violations).toEqual([]);
});
