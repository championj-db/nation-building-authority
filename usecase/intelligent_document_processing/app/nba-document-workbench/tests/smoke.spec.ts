import { expect, test } from '@playwright/test';

// Pre-demo smoke check: run against `npm run dev` (or a deployed URL via BASE_URL).
// Walks the AP officer's path without recording a decision, so it is safe before a demo.
test('document assurance workbench demo path', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { level: 1 })).toContainText(/Good (morning|afternoon|evening)/);
  await expect(page.getByText(/synthetic demonstration data/i).first()).toBeVisible();

  // the queue loads, ordered by the payment clock
  const rows = page.locator('.queue-row');
  await expect(rows.first()).toBeVisible({ timeout: 120_000 });

  // a filter narrows the queue to held invoices
  await page.getByRole('button', { name: /^Needs review/ }).first().click();
  await expect(page.locator('.queue-row .status.needs_review').first()).toBeVisible();

  // opening one shows the page, the fields and the checks
  await rows.first().click();
  await expect(page).toHaveURL(/doc=DOC-\d{6}/);
  await expect(page.getByRole('heading', { name: 'Extracted fields' })).toBeVisible({ timeout: 60_000 });
  await expect(page.getByRole('heading', { name: 'Correctly rendered checks' })).toBeVisible();
  await expect(page.locator('.paper img')).toBeVisible({ timeout: 60_000 });

  // selecting a held field draws its evidence on the page; accept stays locked until it is resolved
  const held = page.locator('.field-row.held .field-hit').first();
  if (await held.count()) {
    await held.click();
    await expect(page.locator('.evidence-box.selected').first()).toBeAttached();
    await expect(page.getByRole('button', { name: /Accept/ })).toBeDisabled();
  }

  // the return form names the failed criteria and drafts the supplier notice, then cancels
  await page.getByRole('button', { name: /^Return/ }).click();
  await expect(page.getByText('Notice that will accompany the return')).toBeVisible();
  await page.getByRole('button', { name: 'Cancel' }).click();

  // back to the queue
  await page.getByRole('button', { name: 'Back to queue' }).click();
  await expect(rows.first()).toBeVisible();
});
