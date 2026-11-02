import { test, expect, request as pwRequest } from '@playwright/test';

/**
 * Parcours 1 — Vitrine et bascule (CLAUDE.md §2 point 1).
 *
 * `Config.on_line` est un singleton global partagé par toute la base de dev
 * (règle PLAN_2026-10-22 §0.1 : plusieurs agents tournent en parallèle sur
 * `db.sqlite3`). On lit sa valeur de départ via l'API publique (GET est
 * `AllowAny`) et on restaure systématiquement l'état d'origine via l'UI
 * Settings (PATCH exige IsDirection) pour ne pas perturber les autres
 * sessions. Ce test ne s'exécute qu'en série (`workers: 1`).
 */

test.describe('Vitrine et bascule on_line', () => {
  test('on_line=True affiche la vitrine publique sur "/"', async ({ page }) => {
    const apiBase = process.env.E2E_API_URL || 'http://localhost:8000';
    const api = await pwRequest.newContext();
    const initialOnLine = (await (await api.get(`${apiBase}/api/core/config/`)).json()).on_line as boolean;
    await api.dispose();

    test.skip(!initialOnLine, 'Config on_line actuellement à False — couvert par le test de bascule ci-dessous.');

    await page.goto('/');
    await expect(page).toHaveURL('/');
    // La vitrine publique ne doit pas montrer le formulaire de connexion.
    await expect(page.getByPlaceholder('Ex: pierre')).toHaveCount(0);
  });

  test("bascule via Settings (ADMIN/DIRECTION) : la racine '/' suit l'état on_line", async ({ page, browser }) => {
    const apiBase = process.env.E2E_API_URL || 'http://localhost:8000';
    const api = await pwRequest.newContext();
    const initialOnLine = (await (await api.get(`${apiBase}/api/core/config/`)).json()).on_line as boolean;
    await api.dispose();

    await page.goto('/login');
    await page.getByPlaceholder('Ex: pierre').fill('demo_admin_e2e');
    await page.getByPlaceholder('••••••••').fill('DemoE2E2026!');
    await page.getByRole('button', { name: /se connecter/i }).click();
    await expect(page).toHaveURL(/\/dashboard/);

    await page.goto('/settings');
    const toggle = page.getByTitle(/désactiver la vitrine|activer la vitrine/i);
    await expect(toggle).toBeVisible();

    try {
      // Force on_line = False, vérifie la redirection anonyme vers /login.
      if (initialOnLine) await toggle.click();
      await expect(page.getByText('🔒 DASHBOARD UNIQUEMENT')).toBeVisible();

      const ctxOff = await browser.newContext();
      const pageOff = await ctxOff.newPage();
      await pageOff.goto('/');
      await expect(pageOff).toHaveURL(/\/login/);
      await ctxOff.close();

      // Force on_line = True, vérifie que la vitrine redevient visible.
      await toggle.click();
      await expect(page.getByText('🌐 VITRINE EN LIGNE')).toBeVisible();

      const ctxOn = await browser.newContext();
      const pageOn = await ctxOn.newPage();
      await pageOn.goto('/');
      await expect(pageOn).toHaveURL('/');
      await ctxOn.close();
    } finally {
      // Restauration stricte de l'état d'origine (lu au début du test).
      const apiCheck = await pwRequest.newContext();
      const current = (await (await apiCheck.get(`${apiBase}/api/core/config/`)).json()).on_line as boolean;
      await apiCheck.dispose();
      if (current !== initialOnLine) {
        await page.goto('/settings');
        const t = page.getByTitle(/désactiver la vitrine|activer la vitrine/i);
        if (await t.isVisible()) await t.click();
      }
    }
  });
});
