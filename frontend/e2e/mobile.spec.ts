import { expect, test } from "@playwright/test";

import { login } from "./helpers";

// PIVOT §13.7: the queue and the case file must be usable at phone width (stacked panes).
for (const path of ["/queue", "/cases", "/capacity", "/evidence-room"]) {
  test(`${path} fits a phone screen without sideways scrolling`, async ({ page }) => {
    await login(page, "validator", path);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible({ timeout: 20_000 });
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
  });
}
