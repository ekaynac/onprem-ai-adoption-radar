import { expect, test } from "@playwright/test";
import axe from "axe-core";


const routes = [
  "/#/overview",
  "/#/releases",
  "/#/catalog",
  "/#/projects",
  "/#/platforms",
  "/#/hardware",
  "/#/research",
  "/#/compare",
  "/#/planner",
  "/#/trending",
  "/#/newsroom",
  "/#/advisor",
  "/#/desk",
  "/#/workspaces",
  "/#/operations",
  "/#/operations/reviews",
  "/#/watchlists",
  "/#/integrations",
];


for (const route of routes) {
  test(`no serious accessibility violations on ${route}`, async ({ page }) => {
    await page.goto(route);
    await page.locator("main").waitFor();
    await page.addScriptTag({ content: axe.source });
    const violations = await page.evaluate(async () => {
      const result = await window.axe.run(document, {
        resultTypes: ["violations"],
      });
      return result.violations.filter(
        (item) => item.impact === "serious" || item.impact === "critical",
      );
    });
    expect(violations).toEqual([]);
  });
}


test("primary navigation is keyboard reachable with visible focus", async ({ page }) => {
  await page.goto("/#/overview");
  await page.keyboard.press("Tab");
  const focused = page.locator(":focus");
  await expect(focused).toBeVisible();
  await expect(focused).not.toHaveCSS("box-shadow", "none");
});


declare global {
  interface Window {
    axe: {
      run: (
        root: Document,
        options: Record<string, unknown>,
      ) => Promise<{
        violations: Array<{ impact: string | null; id: string; nodes: unknown[] }>;
      }>;
    };
  }
}
