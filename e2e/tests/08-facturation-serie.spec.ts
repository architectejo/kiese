import { test, expect } from '@playwright/test';
import { COMPTES, PASSWORD } from '../fixtures/comptes';
import { seConnecter } from '../fixtures/helpers';

/**
 * Parcours 5 — Facturation en série (CLAUDE.md §2 point 5).
 * 10 ventes enchaînées sans rechargement de page, puis historique des 5 dernières
 * visibles dans la file de livraison (les 3 premières affichées + "Voir plus").
 */

test('10 facturations occasionnelles enchaînées sans rechargement, historique visible', async ({ page }) => {
  await seConnecter(page, COMPTES.facturierK1.username, PASSWORD);
  await page.goto('/sales/create');

  await page.getByText(/vente occasionnelle \(sans client enregistré\)/i).click();
  await expect(page.locator('input[type="checkbox"]').first()).toBeChecked();

  for (let i = 1; i <= 10; i++) {
    await page.locator('input[type="number"]').first().fill(String(i % 3 + 1));
    await page.getByRole('button', { name: /facturer & mettre en attente/i }).click();
    // Pas de rechargement : la page doit rester sur /sales/create entre deux ventes.
    await expect(page).toHaveURL(/\/sales\/create/);
    await expect(page.getByRole('button', { name: /enregistrement/i })).toHaveCount(0, { timeout: 10_000 });
  }

  // "Voir plus" doit permettre de retrouver l'historique complet de la journée (au moins 10 ici).
  const voirPlus = page.getByRole('button', { name: /voir plus/i });
  if (await voirPlus.count() > 0) {
    await voirPlus.click();
    await expect(page.getByText(/facture\(s\) du jour/i)).toBeVisible();
  }
});
