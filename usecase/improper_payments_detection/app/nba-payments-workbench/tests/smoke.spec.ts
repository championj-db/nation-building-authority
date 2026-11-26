import { expect, test } from '@playwright/test';

// Pre-demo smoke check: run against `npm run dev` (or a deployed URL via BASE_URL).
// Walks the investigator path without recording an outcome, so it is safe before a demo.
test('improper payments workbench demo path', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Payment review queue');
  await expect(page.getByText('Synthetic demonstration data')).toBeVisible();

  const rows = page.locator('tbody tr[data-case]');
  await expect(rows.first()).toBeVisible({ timeout: 120_000 });

  // filters narrow the queue and clear restores it
  const total = await rows.count();
  await page.getByLabel('Risk band').selectOption('high');
  await expect(page.locator('tbody tr[data-case] .risk.medium')).toHaveCount(0);
  await page.getByRole('button', { name: 'Clear filters' }).click();
  await expect(rows).toHaveCount(total);

  // opening a case shows its explanation, links and payments
  const firstId = await rows.first().getAttribute('data-case');
  await rows.first().click();
  const drawer = page.getByRole('dialog');
  await expect(drawer).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`case=${firstId}`));
  await expect(drawer.getByRole('heading', { name: 'Why this case was prioritised' })).toBeVisible();
  await expect(drawer.locator('.evidence-item').first()).toBeVisible({ timeout: 60_000 });
  await expect(drawer.getByRole('img', { name: /Relationship graph/ })).toBeVisible({ timeout: 60_000 });
  await expect(drawer.getByText('Decision support only.')).toBeVisible();

  // notes are required before an outcome is recorded
  const submit = drawer.getByRole('button', { name: /Record outcome|Clear indicator|Escalate/ });
  if (await submit.isEnabled()) {
    await drawer.getByLabel('Escalate for assessment').check();
    await submit.click();
    await expect(drawer.getByLabel('Investigator notes')).toHaveAttribute('aria-invalid', 'true');
  }

  // Escape closes the drawer and the URL forgets the case
  await page.keyboard.press('Escape');
  await expect(drawer).toBeHidden();
  await expect(page).not.toHaveURL(/case=/);

  // precision view renders history and model evaluation
  await page.getByRole('link', { name: 'Precision', exact: true }).click();
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Precision monitoring');
  await expect(page.getByRole('heading', { name: 'By primary signal' })).toBeVisible();
  await expect(page.locator('.meter-row').first()).toBeVisible({ timeout: 120_000 });
});
