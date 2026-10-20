import { defineConfig, devices } from "@playwright/test";

/**
 * Browser end-to-end tests against the real stack: the FastAPI backend on the generated fixture
 * dataset (prepared by `backend/scripts/e2e_prepare.py`) behind the Vite dev proxy.
 * Locally the installed Microsoft Edge is used; CI installs Playwright's Chromium.
 */
const API_PORT = 8011;
const WEB_PORT = 5190;
const e2eDir = "../backend/.e2e";

export const E2E_PASSWORD = process.env.VERITA_DEMO_PASSWORD ?? "e2e-only-password-0001";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false, // the stack has one database and one demo story
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : [["list"]],
  use: {
    baseURL: `http://localhost:${String(WEB_PORT)}`,
    trace: "retain-on-failure",
    ...(process.env.CI ? {} : { channel: "msedge" }),
  },
  projects: [
    {
      name: "desktop",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 1000 } },
    },
    { name: "phone", use: { ...devices["Pixel 7"] }, testMatch: /mobile\.spec\.ts/ },
  ],
  webServer: [
    {
      command: `uv --directory ../backend run --no-sync uvicorn verita.api.app:create_app --factory --port ${String(API_PORT)}`,
      url: `http://localhost:${String(API_PORT)}/api/v1/health/live`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: {
        VERITA_DATABASE_URL: `sqlite+pysqlite:///${e2eDir}/e2e.sqlite`,
        VERITA_DATASET: "fixture",
        VERITA_SIGNING_KEY_PATH: `${e2eDir}/signing.pem`,
        VERITA_PUBLIC_KEY_PATH: `${e2eDir}/pub.pem`,
        VERITA_LLM_PROVIDERS: "[]",
        VERITA_INLINE_JOBS: "true",
      },
    },
    {
      command: "npm run dev",
      url: `http://localhost:${String(WEB_PORT)}`,
      reuseExistingServer: !process.env.CI,
      timeout: 120_000,
      env: {
        VERITA_WEB_PORT: String(WEB_PORT),
        VERITA_API_URL: `http://localhost:${String(API_PORT)}`,
      },
    },
  ],
});
