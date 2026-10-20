import { expect, test } from "@playwright/test";

import { login } from "./helpers";

test("the analysts slider answers within 150 ms, then the exact plan arrives", async ({ page }) => {
  await login(page, "mlro", "/capacity");
  const reviewed = page.getByRole("group", { name: "Alerts reviewed" });
  await expect(reviewed).toContainText(/Exact plan/, { timeout: 20_000 });
  const slider = page.getByRole("slider", { name: "Analysts on duty" });
  const before = await page.getByRole("group", { name: "Expected recall" }).textContent();

  await slider.focus();
  // Start watching the Expected recall figure, then move the slider like a user (arrow key).
  await page.evaluate(() => {
    const recall = [...document.querySelectorAll('[role="group"]')].find((g) =>
      g.textContent.startsWith("Expected recall"),
    );
    const w = window as unknown as { __changed: Promise<number>; __t0: number };
    w.__changed = new Promise<number>((resolve) => {
      const observer = new MutationObserver(() => {
        observer.disconnect();
        resolve(performance.now() - w.__t0);
      });
      if (recall) observer.observe(recall, { subtree: true, characterData: true, childList: true });
    });
    document.addEventListener(
      "keydown",
      () => {
        w.__t0 = performance.now();
      },
      { capture: true, once: true },
    );
  });
  await page.keyboard.press("ArrowRight");
  const elapsed = await page.evaluate(
    () => (window as unknown as { __changed: Promise<number> }).__changed,
  );
  expect(elapsed).toBeLessThan(150);
  await expect(page.getByRole("group", { name: "Expected recall" })).not.toHaveText(before ?? "");
  await expect(reviewed).toContainText(/Exact plan/, { timeout: 20_000 });

  // the MLRO saves the plan; it is audited and shown in the queue for that day
  await page.getByRole("button", { name: "Save plan" }).click();
  await expect(page.getByText(/Saved as plan #\d+/)).toBeVisible();
  const day = new URL(page.url()).searchParams.get("date");
  await page.goto(`/queue${day ? `?date=${day}` : ""}`);
  if (day) await expect(page.getByText(/analysts reviewing the top/)).toBeVisible();
});

test("every capacity figure explains how it is computed", async ({ page }) => {
  await login(page, "analyst2", "/capacity");
  const stats = page.locator('[role="group"]').filter({ has: page.getByText("How computed") });
  await expect(stats.first()).toBeVisible({ timeout: 20_000 });
  const count = await stats.count();
  expect(count).toBeGreaterThanOrEqual(6);
  for (let i = 0; i < count; i++) {
    await stats.nth(i).getByText("How computed").click();
    await expect(stats.nth(i).getByText("Source")).toBeVisible();
  }
});
