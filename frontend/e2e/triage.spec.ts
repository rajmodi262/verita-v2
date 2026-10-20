import { expect, test } from "@playwright/test";

import { login } from "./helpers";

test("an analyst triages the queue with the keyboard alone", async ({ page }) => {
  await login(page, "analyst2");
  await expect(page.getByText(/riskiest first/)).toBeVisible();

  // J moves down the queue, Enter opens the investigation
  await page.keyboard.press("j");
  await page.keyboard.press("j");
  const second = page.locator("tbody tr").nth(2).getByRole("link");
  await expect(second).toBeFocused();
  const alertId = (await second.textContent())?.match(/\d+/)?.[0];
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/alerts\/\d+/);
  await expect(page.getByRole("heading", { name: "Why this is an alert" })).toBeVisible();
  await expect(page.getByText(/EV-REASON-/).first()).toBeVisible();

  // back to the queue and dismiss the current alert with D
  await page.goBack();
  await expect(page.getByText(/riskiest first/)).toBeVisible();
  await page.keyboard.press("k");
  await page.keyboard.press("d");
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.getByLabel("Reason").selectOption({ index: 1 });
  await dialog.getByRole("button", { name: /Dismiss/ }).click();
  await expect(dialog).toBeHidden();
  expect(alertId).toBeTruthy();
});

test("the ? key shows the shortcut map", async ({ page }) => {
  await login(page, "analyst2");
  await expect(page.getByText(/riskiest first/)).toBeVisible();
  await page.keyboard.press("?");
  await expect(page.getByRole("dialog", { name: /shortcuts/i })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toBeHidden();
});
