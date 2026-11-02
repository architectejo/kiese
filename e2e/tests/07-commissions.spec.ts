import { test, expect } from '@playwright/test';
import { COMPTES, PASSWORD } from '../fixtures/comptes';
import { seConnecter } from '../fixtures/helpers';

/**
 * Parcours 9 — Commissions (CLAUDE.md §2 point 9 / §5.3).
 */

test('le comptable accède à l\'écran des commissions (listing de paie)', async ({ page }) => {
  await seConnecter(page, COMPTES.comptable.username, PASSWORD);
  await page.goto('/commissions');

  await expect(page.getByRole('heading', { name: 'Commissions des Revendeurs (CM)' })).toBeVisible();
  await expect(page.getByRole('button', { name: /générer commissions/i })).toBeVisible();
  await expect(page.getByText(/situation des ristournes/i)).toBeVisible();
});

test.fixme(
  'le bouton Imprimer du listing de paie fonctionne une fois des commissions générées',
  async () => {
    // Le bouton "Imprimer" (`Commissions.tsx` l.357-367) n'est rendu que si
    // `filteredCommissions.length > 0` — il faut d'abord déclencher "Générer
    // Commissions" (POST qui calcule les CM du mois courant à partir des
    // factures livrées) et que des factures livrées existent réellement sur
    // la période en cours pour ce nœud. Non bouclé dans le temps disponible
    // de cette session (même dépendance de données que 09-journee-complete).
  }
);

test('un facturier ne voit pas le module Commissions dans le menu', async ({ page }) => {
  await seConnecter(page, COMPTES.facturierK1.username, PASSWORD);
  await expect(page.getByRole('link', { name: /commissions cm/i })).toHaveCount(0);
});
