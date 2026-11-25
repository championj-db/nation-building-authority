import { expect, test } from '@playwright/test';

// Pre-demo smoke check: run against `npm run dev` (or a deployed URL via BASE_URL).
// Walks the demo path without writing anything, so it is safe to run before a demo.
test('spatial service planner demo path', async ({ page }) => {
  await page.goto('/?scope=NSW&geo=sa4&service=public_hospital&t=45');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Plan equitable access to essential services.');
  await expect(page.getByText('People beyond threshold')).toBeVisible({ timeout: 120_000 });

  // the map renders regions and the evidence queue lists them
  await expect(page.locator('[data-region]').first()).toBeAttached({ timeout: 120_000 });
  const firstRegion = page.getByRole('region', { name: 'Evidence queue' }).locator('tbody tr').first();
  await expect(firstRegion).toBeVisible();

  // policy settings are a draft until Run analysis
  await page.getByLabel('Reasonable access threshold').fill('60');
  await expect(page.getByRole('complementary', { name: 'Policy settings' }).getByText('Draft')).toBeVisible();
  await page.getByRole('button', { name: 'Run analysis' }).click();
  await expect(page.getByText('Threshold tested')).toBeVisible();
  await expect(page).toHaveURL(/t=60/);

  // selecting a region opens its detail card
  await firstRegion.click();
  await expect(page.getByRole('button', { name: 'Add review note' }).first()).toBeEnabled();

  // the H3 layer loads hexagons
  await page.getByRole('button', { name: 'H3 grid' }).click();
  await expect(page.locator('[data-hex]').first()).toBeAttached({ timeout: 120_000 });

  // the other tabs render real pipeline and assurance state
  await page.getByRole('tab', { name: 'Data pipeline' }).click();
  await expect(page.getByText('H3 pruning for nearest-service search')).toBeVisible({ timeout: 60_000 });
  await page.getByRole('tab', { name: 'Assurance' }).click();
  await expect(page.getByRole('heading', { name: 'Before publication' })).toBeVisible();
});
