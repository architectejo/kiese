import { test, expect } from '@playwright/test';

/**
 * Passe finale sur la base réelle (testeur-e2e, 2026-11-12) — parties publiques uniquement :
 * aucun compte e2e n'a pu être créé (pas d'accès administrateur accordé).
 * Lecture seule : aucune écriture en base.
 */
const API = process.env.E2E_API_URL || 'http://localhost:8000';

test('vitrine publique selon on_line, sans formulaire de connexion', async ({ page, request }) => {
  test.setTimeout(180_000);
  const cfg = await request.get(`${API}/api/core/config/`, { timeout: 120_000 });
  expect(cfg.ok()).toBeTruthy();
  const onLine = (await cfg.json()).on_line as boolean;
  await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 150_000 });
  if (onLine) {
    await expect(page).toHaveURL(/\/$/, { timeout: 60_000 });
    await expect(page.getByPlaceholder('Ex: pierre')).toHaveCount(0);
    await expect(page.locator('body')).toContainText(/KIESE/i, { timeout: 120_000 });
  } else {
    await expect(page).toHaveURL(/\/login/, { timeout: 120_000 });
  }
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

for (const route of ['/treasury', '/clients', '/production', '/commissions', '/sales', '/cloture-journaliere']) {
  test(`anonyme : ${route} redirige hors du tableau de bord`, async ({ page }) => {
    test.setTimeout(180_000);
    await page.goto(route, { waitUntil: 'domcontentloaded', timeout: 150_000 });
    await expect(page).not.toHaveURL(new RegExp(`${route}$`), { timeout: 120_000 });
  });
}
