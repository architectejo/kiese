import { test, expect } from '@playwright/test';
import { CAP, login, later, overflow } from '../fixtures/cycle';

/**
 * Cycle final (testeur-e2e, 2026-11-14) - lecture seule de la tresorerie K4 apres cloture (toutes tailles) :
 * pas de debordement horizontal, cloture confirmee et inscrite visible pour le gerant, billetage lisible.
 */
test('Gerant K4 : tresorerie apres cloture, sans debordement', async ({ page }, info) => {
  test.setTimeout(300_000);
  await login(page, 'zz_clients_gerant');
  await page.goto('/treasury', { waitUntil: 'domcontentloaded' });
  await later(page);
  await expect(page.getByText(/Saisir le nombre de coupures/)).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText('CONFIRMÉE').first()).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(/Inscrit au grand livre/).first()).toBeVisible();
  await expect(page.getByText(/Espèces physiques:\s*13\s?500 FC/)).toBeVisible();
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${CAP}/cf-${info.project.name}-treso-apres-cloture.png`, fullPage: true });
  expect(await overflow(page)).toBeLessThanOrEqual(1);
});
