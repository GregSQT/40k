import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright E2E — Couche C.
 *
 * Variables d'environnement attendues :
 *   PW_FRONTEND_URL  URL du front déjà démarré (défaut http://localhost:5175)
 *   PW_BASE_URL      URL du backend (défaut http://localhost:5001)
 *
 * Le backend et le frontend sont spawné par scripts/front_test_all.sh (T13).
 * La config ne démarre rien elle-même pour rester utilisable seule (dev local).
 */
export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 60_000,
  retries: 0,
  workers: 1,
  fullyParallel: false,

  use: {
    baseURL: process.env.PW_FRONTEND_URL ?? "http://localhost:5175",
    headless: true,
    viewport: { width: 1280, height: 800 },
    deviceScaleFactor: 1,
    locale: "fr-FR",
    // Screenshots des échecs dans playwright-report/
    screenshot: "only-on-failure",
    video: "off",
  },

  globalSetup: "./tests/e2e/global-setup.ts",

  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        storageState: ".auth/session.json",
      },
    },
  ],

  reporter: [
    ["list"],
    ["html", { outputFolder: "playwright-report", open: "never" }],
  ],
});
