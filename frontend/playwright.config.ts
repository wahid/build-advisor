import { defineConfig, devices } from "@playwright/test";

// Browser tests of the built app (npm run build first) against e2e/mock-server.mjs.
export default defineConfig({
  testDir: "e2e",
  timeout: 30_000,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: { baseURL: "http://localhost:4321", trace: "retain-on-failure" },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"] }, testIgnore: /phone\.spec\.ts/ },
    { name: "phone", use: { ...devices["Pixel 7"] }, testMatch: /phone\.spec\.ts/ },
  ],
  webServer: { command: "node e2e/mock-server.mjs 4321", port: 4321, reuseExistingServer: !process.env.CI },
});
