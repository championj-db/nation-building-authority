import { expect, test } from '@playwright/test';

// Pre-demo smoke check: run against `npm run dev` (or a deployed URL via BASE_URL).
// Walks the demo path without writing a decision, so it is safe to run before a demo.
test('infrastructure operations centre demo path', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { level: 1 })).toContainText(/Good (morning|afternoon|evening)/);

  // sector tiles filter the queue
  await page.getByRole('button', { name: /^Energy: \d+ open incidents/ }).click();
  await expect(page.getByLabel('Filter by sector')).toHaveValue('energy');
  await page.getByLabel('Filter by sector').selectOption('all');

  const firstReview = page.getByRole('button', { name: 'Review', exact: true }).first();
  await expect(firstReview).toBeVisible({ timeout: 60_000 });

  // the network map renders incidents and warnings
  await page.getByRole('button', { name: 'Network map' }).click();
  await expect(page.getByRole('heading', { name: 'Active warnings' })).toBeVisible();
  await page.getByRole('button', { name: 'NSW & ACT' }).click();

  // review an incident, then close without deciding
  await firstReview.click();
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByRole('heading', { name: 'Why this was flagged' })).toBeVisible();
  await expect(dialog.getByRole('heading', { name: 'If this fails' })).toBeVisible();
  await expect(dialog.getByRole('button', { name: 'Dispatch crew' })).toBeEnabled();
  await dialog.getByRole('button', { name: 'Close review' }).click();
  await expect(dialog).toBeHidden();

  await page.getByRole('button', { name: 'Shift handover' }).click();
  await expect(page.getByRole('heading', { name: 'Decision record' })).toBeVisible();
});
