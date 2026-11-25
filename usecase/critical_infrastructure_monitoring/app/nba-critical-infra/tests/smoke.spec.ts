import { expect, test } from '@playwright/test';

// Pre-demo smoke check: run against `npm run dev` (or a deployed URL via BASE_URL).
// Walks the demo path without writing a decision, so it is safe to run before a demo.
test('operations centre demo path', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { level: 1 })).toContainText(/Good (morning|afternoon|evening)/);
  await expect(page.getByRole('heading', { name: 'Alerts requiring review' })).toBeVisible();

  const firstReview = page.getByRole('button', { name: 'Review alert' }).first();
  await expect(firstReview).toBeVisible({ timeout: 60_000 });

  await page.getByLabel('Filter by risk type').selectOption('mass');
  await expect(page.getByText(/\d+ alerts? shown/)).toBeVisible();
  await page.getByLabel('Filter by risk type').selectOption('all');

  await firstReview.click();
  const dialog = page.getByRole('dialog', { name: /risk/ });
  await expect(dialog.getByRole('heading', { name: 'Why this was flagged' })).toBeVisible();
  await expect(dialog.getByRole('heading', { name: 'Recent movement' })).toBeVisible();
  await expect(dialog.getByRole('button', { name: 'Route to field queue' })).toBeEnabled();
  await dialog.getByRole('button', { name: 'Close review' }).click();
  await expect(dialog).toBeHidden();

  await page.getByRole('button', { name: 'Shift handover' }).click();
  await expect(page.getByRole('heading', { name: 'Decision record' })).toBeVisible();
});
