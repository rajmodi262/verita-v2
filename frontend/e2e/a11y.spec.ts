import { expect, test } from "@playwright/test";

import { expectNoAxeViolations, login } from "./helpers";

test("public pages have no accessibility violations", async ({ page }) => {
  for (const path of ["/", "/login"]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expectNoAxeViolations(page);
  }
});

test("every workspace screen has no accessibility violations, in both themes", async ({ page }) => {
  await login(page, "validator");
  const firstAlert = await page.locator("tbody tr").first().getByRole("link").getAttribute("href");
  const screens = ["/queue", firstAlert ?? "/queue", "/capacity", "/cases", "/evidence-room"];
  for (const theme of ["paper", "night"]) {
    for (const path of screens) {
      await page.goto(path);
      await page.evaluate((t) => {
        document.documentElement.dataset.theme = t;
      }, theme);
      await expect(page.getByRole("heading", { level: 1 })).toBeVisible({ timeout: 20_000 });
      await page.waitForLoadState("networkidle");
      await expectNoAxeViolations(page);
    }
  }
});

test("a case file has no accessibility violations", async ({ page }) => {
  await login(page, "analyst2");
  await page.locator("tbody tr").first().getByRole("link").click();
  await page.getByRole("button", { name: "Open a case file" }).click();
  await page.getByRole("button", { name: "Draft narrative" }).click();
  await expect(page.getByText("Verified").first()).toBeVisible({ timeout: 30_000 });
  await expectNoAxeViolations(page);
});

test("the skip link moves focus to the main content", async ({ page }) => {
  await login(page, "validator");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to content" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#main")).toBeFocused();
});
