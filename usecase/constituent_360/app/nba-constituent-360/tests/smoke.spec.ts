import { expect, test } from '@playwright/test';

test('navigates the governed workspace', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Constituent service overview' })).toBeVisible();
  const menu = page.getByRole('button', { name: 'Open navigation' });
  if (await menu.isVisible()) await menu.click();
  await page.getByRole('link', { name: 'Constituents' }).click();
  await expect(page.getByRole('heading', { name: 'Constituents' })).toBeVisible();
  if (await menu.isVisible()) await menu.click();
  await page.getByRole('link', { name: 'Consent & access' }).click();
  await expect(page.getByRole('heading', { name: 'Consent & access' })).toBeVisible();
});
