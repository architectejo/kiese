import { test, expect } from '@playwright/test';
import { COMPTES, PASSWORD } from '../fixtures/comptes';
import { seConnecter } from '../fixtures/helpers';

/**
 * Parcours 6 — Production (CLAUDE.md §2 point 6 / §5.4).
 */

test('déclaration de fournée avec consommables décimaux, écart manquant/excédent affiché', async ({ page }) => {
  await seConnecter(page, COMPTES.gerantK1.username, PASSWORD);
  await page.goto('/production');

  // Scope strict au formulaire "§3.1 — Déclaration de Fournée" (plusieurs
  // autres champs de la page partagent le placeholder "0").
  const formulaire = page.locator('form').filter({ has: page.getByRole('button', { name: /enregistrer la fournée/i }) });

  await formulaire.locator('input[type="number"][step="0.5"]').first().fill('2'); // sacs de farine

  // Quantité de pains produits (1ère catégorie de la grille "Projection coupe"),
  // volontairement basse pour générer un écart "manquant" visible.
  await formulaire.locator('input[placeholder="0"]').first().fill('10');

  // Consommables décimaux : sel (grammes, entier), levure (paquets, décimal), huile (litres, décimal).
  await formulaire.locator('input[placeholder="500"]').fill('450');
  await formulaire.locator('input[placeholder="0.50"]').fill('0.25');
  await formulaire.locator('input[placeholder="0.25"]').fill('0.5');

  await expect(page.getByText(/MANQUANT|EXCÉDENT/)).toBeVisible({ timeout: 10_000 });

  await formulaire.getByRole('button', { name: /enregistrer la fournée/i }).click();
  await expect(page.getByText(/stock insuffisant/i)).toHaveCount(0, { timeout: 10_000 });
});

test.fixme(
  'transfert K1 → K2 validé par K2, et transfert avec écart déclenche une alerte',
  async () => {
    // Nécessite : un stock de pains disponible côté K1 pour amorcer un
    // transfert réel (sortie en attente), puis une connexion en tant que
    // gérant K2 pour confirmer la réception avec une quantité différente de
    // la quantité envoyée. Scénario backend déjà couvert par
    // `backend/production/tests/test_transfers.py` (workflow en 3 étapes,
    // écart bloquant la clôture — voir BUG-037/048 dans le registre) ; la
    // dépendance sur un stock de pains réellement produit ET non déjà
    // transféré rend la préparation de données UI fragile dans le temps
    // disponible de cette session. À reprendre avec un script de seed dédié
    // (fournée réelle côté K1 puis transfert) plutôt qu'à la main en E2E.
  }
);
