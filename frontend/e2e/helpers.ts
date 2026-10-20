import AxeBuilder from "@axe-core/playwright";
import { expect } from "@playwright/test";
import type { Page } from "@playwright/test";

import { E2E_PASSWORD } from "../playwright.config";

/** Sign in through the real login form, keyboard only. */
export async function login(page: Page, username: string, next = "/queue"): Promise<void> {
  await page.context().clearCookies();
  await page.goto(`/login?next=${encodeURIComponent(next)}`);
  await page.getByLabel("Username").fill(username);
  await page.getByLabel("Password").fill(E2E_PASSWORD);
  await page.getByLabel("Password").press("Enter");
  await expect(page).toHaveURL(new RegExp(next.replace(/[?]/g, "\\?")));
}

/** WCAG 2.2 A/AA rules; contrast is checked at AAA by the unit test on the tokens. */
export async function expectNoAxeViolations(page: Page): Promise<void> {
  // @axe-core/playwright types its own copy of Playwright's Page; the runtime object is the same.
  const axePage = page as unknown as ConstructorParameters<typeof AxeBuilder>[0]["page"];
  const results = await new AxeBuilder({ page: axePage })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
    .analyze();
  const summary = results.violations.map(
    (v) => `${v.id} (${v.impact ?? "?"}): ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`,
  );
  expect(summary).toEqual([]);
}
