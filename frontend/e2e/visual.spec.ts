import { expect, test } from "@playwright/test";


const viewports = [
  { name: "desktop", width: 1440, height: 1000 },
  { name: "tablet", width: 1024, height: 768 },
  { name: "mobile", width: 390, height: 844 },
];


for (const viewport of viewports) {
  for (const scheme of ["light", "dark"] as const) {
    test(`${viewport.name} ${scheme} renders without horizontal overflow`, async ({
      page,
    }) => {
      await page.setViewportSize(viewport);
      await page.emulateMedia({ colorScheme: scheme });
      await page.goto("/#/overview");
      await page.locator("main").waitFor();
      const dimensions = await page.evaluate(() => ({
        body: document.body.scrollWidth,
        viewport: document.documentElement.clientWidth,
      }));
      expect(dimensions.body).toBeLessThanOrEqual(dimensions.viewport + 1);
      await expect(page.getByRole("heading", {
        name: "What changed since your last visit",
      })).toBeVisible();
    });
  }
}
