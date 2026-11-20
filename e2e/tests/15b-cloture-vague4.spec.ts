import { test, expect } from '@playwright/test';

/** Vague 4 : Clôture Journalière K2 en rotation, colonne « Reste fin de journée » (BUG-272). Bureau et POS. */
test('Clôture Journalière : colonnes « Reste du Jour » / « Reste d\'Hier » (BUG-304) en rotation', async ({ page }, info) => {
  test.setTimeout(900_000);
  // K1 (rotation) : on reporte « Stock de départ » et on confirme l'équipe de service suggérée
  await page.addLocatorHandler(page.getByRole('button', { name: /plus tard/i }), async b => { await b.click(); });
  await page.addLocatorHandler(page.getByRole('button', { name: /confirmer l'équipe/i }), async b => { await b.click(); });
  await page.goto('/login', { waitUntil: 'domcontentloaded', timeout: 180_000 });
  await page.getByPlaceholder('Ex: pierre').fill('zz_demo_gerant_k1', { timeout: 120_000 });
  await page.getByPlaceholder('••••••••').fill('zz_demo_gerant_k1');
  await page.getByRole('button', { name: /se connecter/i }).click();
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 150_000 });
  await page.goto('/cloture-journaliere', { waitUntil: 'domcontentloaded', timeout: 180_000 });
  await expect(page.getByRole('heading', { name: 'Clôture Journalière' }).first()).toBeVisible({ timeout: 120_000 });
  await expect(page.getByRole('columnheader', { name: 'Reste du Jour' }).first()).toBeVisible({ timeout: 120_000 });
  const ecart = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  console.log(`[${info.project.name}] débordement horizontal = ${ecart}`);
  await page.screenshot({ path: `../docs/qa/captures/prod-v4-cloture-${info.project.name}.png`, fullPage: true });
});
