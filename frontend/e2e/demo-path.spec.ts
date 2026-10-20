import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

import { login } from "./helpers";

/**
 * The whole demo story (PIVOT §20): alert → case → fault caught → submit → maker-checker sign →
 * tamper detected in the browser.
 */
test("alert to signed, verifiable case file", async ({ page }) => {
  // the analyst opens a case from the riskiest open alert
  await login(page, "analyst");
  await page.locator("tbody tr").first().getByRole("link").click();
  await page.getByRole("button", { name: "Open a case file" }).click();
  await expect(page).toHaveURL(/\/cases\/\d+/);
  const caseUrl = page.url();

  // drafting is a real job; the verifier runs on the result
  await page.getByRole("button", { name: "Draft narrative" }).click();
  await expect(page.getByText("Verified").first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("button", { name: "Submit for approval" })).toBeEnabled();

  // a planted fault is caught, highlighted and blocks submission
  await page.getByRole("button", { name: "Inject a fault (demo)" }).click();
  await expect(page.getByText(/Injected a fault/)).toBeVisible();
  await expect(page.locator("mark").first()).toContainText("does not match the evidence");
  await expect(page.getByRole("button", { name: "Submit for approval" })).toBeDisabled();
  await expect(page.getByText(/Submission is blocked/)).toBeVisible();

  // redraft clean, submit
  await page.getByRole("button", { name: "Redraft narrative" }).click();
  await expect(page.getByRole("button", { name: "Submit for approval" })).toBeEnabled({
    timeout: 30_000,
  });
  await page.getByRole("button", { name: "Submit for approval" }).click();
  await expect(page.getByText("Awaiting approval")).toBeVisible();

  // the MLRO (not the maker) approves and signs
  await login(page, "mlro", new URL(caseUrl).pathname);
  await page.getByRole("button", { name: "Approve and sign" }).click();
  await expect(page.getByText("Signed case file")).toBeVisible();
  await expect(page.getByText(/signature, root and ledger verified/)).toBeVisible();
  await expect(page.getByText("Chain intact")).toBeVisible();

  // the signed export verifies in the browser; the tampered copy names the changed leaf
  const good = page.waitForEvent("download");
  await page.getByRole("link", { name: "Download signed JSON" }).click();
  const goodPath = await (await good).path();
  const bad = page.waitForEvent("download");
  await page.getByRole("link", { name: /tampered copy/ }).click();
  const badPath = await (await bad).path();

  const input = page.getByLabel(/Drop a case-file JSON here/);
  await expect(page.getByText(/published key \(loaded\)/)).toBeVisible();
  await input.setInputFiles({
    name: "case.json",
    mimeType: "application/json",
    buffer: readFileSync(goodPath),
  });
  await expect(page.getByText("Valid", { exact: true })).toBeVisible();
  await input.setInputFiles({
    name: "case-TAMPERED.json",
    mimeType: "application/json",
    buffer: readFileSync(badPath),
  });
  await expect(page.getByText("Invalid", { exact: true })).toBeVisible();
  const changed = page.locator("li", { hasText: "changed since signing" });
  await expect(changed).toHaveCount(1);
  await expect(changed.locator("code")).toHaveText(/^EV-TXN-\d+$/);
});

test("the maker cannot approve their own case", async ({ page }) => {
  await login(page, "mlro");
  await page.locator("tbody tr").first().getByRole("link").click();
  await page.getByRole("button", { name: "Open a case file" }).click();
  await page.getByRole("button", { name: "Draft narrative" }).click();
  await expect(page.getByRole("button", { name: "Submit for approval" })).toBeEnabled({
    timeout: 30_000,
  });
  await page.getByRole("button", { name: "Submit for approval" }).click();
  await expect(page.getByRole("button", { name: "Approve and sign" })).toBeDisabled();
  await expect(page.getByText(/Maker-checker: you created this case/)).toBeVisible();
});
