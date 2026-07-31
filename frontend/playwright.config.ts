import { defineConfig } from "@playwright/test";


export default defineConfig({
  testDir: "./e2e",
  use: {
    baseURL: "http://127.0.0.1:4173",
    channel: "chromium",
    trace: "retain-on-failure",
  },
  webServer: {
    command: "python3 -m http.server 4173 --directory ../_site",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: true,
  },
});
