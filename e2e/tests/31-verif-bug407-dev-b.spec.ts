import { test, expect } from '@playwright/test';
import { seConnecter } from '../fixtures/helpers';

/**
 * BUG-407 (testeur-permissions B, 2026-11-21d) : URL directe des routes d'administration.
 * ECRIT MAIS NON EXECUTE (Chromium/Playwright non installes sur ce poste). Comptes `zz_demo_*` du seed e2e
 * (mot de passe : fixture par defaut de `seConnecter`) ; adapter les identifiants si besoin.
 */
const ROUTES = ['/admin/nodes', '/admin/users', '/settings', '/activities'];
// role -> routes autorisees
const COMPTES: Record<string, string[]> = {
  zz_demo_facturier_k2: [],
  zz_demo_gerant_k2: [],
  zz_demo_comptable: ['/activities'],
  zz_demo_direction: ROUTES,
};

for (const [compte, ok] of Object.entries(COMPTES)) {
  for (const route of ROUTES) {
    test(`${compte} -> ${route} : ${ok.includes(route) ? 'autorisee' : 'Acces refuse'}`, async ({ page }) => {
      await seConnecter(page, compte);
      await page.goto(route);
      const refus = page.getByRole('heading', { name: 'Accès refusé' });
      if (ok.includes(route)) await expect(refus).toHaveCount(0);
      else await expect(refus).toBeVisible();
    });
  }
}
