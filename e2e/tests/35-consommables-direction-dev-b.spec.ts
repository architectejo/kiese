import { test, expect, Page } from '@playwright/test';
import { seConnecter } from '../fixtures/helpers';

/**
 * BUG-387 — Vue globale des consommables (direction) + Inventaire Physique (gérant).
 * Non exécuté à l'écriture (ports 8000/5173 possiblement occupés par un autre agent).
 * Lancer : npx playwright test tests/35-consommables-direction-dev-b.spec.ts --project=pos --project=bureau
 */
async function ouvrirIntrants(page: Page) {
  await page.goto('/production', { waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: /Intrants/ }).click();
  await expect(page.getByText(/Stocks? Consommables/i).first()).toBeVisible({ timeout: 60_000 });
}
async function sansDebordement(page: Page) {
  const ecart = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(ecart).toBeLessThanOrEqual(1);
}

test('direction : tableau global, formulaire d\'envoi, détail inventaire d\'une boulangerie', async ({ page }) => {
  test.setTimeout(300_000);
  await seConnecter(page, 'zz_demo_direction');
  await ouvrirIntrants(page);
  const global = page.getByTestId('global-consumables');
  await expect(global).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('global-row-direction')).toBeVisible();
  await expect(page.getByTestId('global-row-totals')).toBeVisible();
  await expect(page.getByTestId('dispatch-form')).toBeVisible();
  await sansDebordement(page);

  // Erreur serveur affichée : aucune quantité saisie -> message clair.
  await page.getByRole('button', { name: /Envoyer aux boulangeries/ }).click();
  await expect(page.getByRole('alert').filter({ hasText: /au moins une boulangerie/ })).toBeVisible();

  // Quantité énorme -> 400 « stock insuffisant » renvoyé par le serveur et affiché.
  await page.getByLabel(/Quantité pour K1/).fill('999999');
  await page.getByRole('button', { name: /Envoyer aux boulangeries/ }).click();
  await expect(page.getByRole('alert').filter({ hasText: /insuffisant/i })).toBeVisible({ timeout: 20_000 });

  // Détail inventaire d'une boulangerie.
  await page.getByTestId('global-row-K1').getByRole('button').first().click();
  await expect(page.getByRole('dialog', { name: /Inventaire Physique/ })).toBeVisible();
});

test('comptable : vue globale en lecture seule (pas de formulaire d\'envoi)', async ({ page }) => {
  test.setTimeout(300_000);
  await seConnecter(page, 'zz_demo_comptable');
  await ouvrirIntrants(page);
  await expect(page.getByTestId('global-consumables')).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId('dispatch-form')).toHaveCount(0);
});

test('gérant : formulaire Inventaire Physique du jour (une saisie par jour)', async ({ page }) => {
  test.setTimeout(300_000);
  await seConnecter(page, 'zz_demo_gerant_k1');
  await ouvrirIntrants(page);
  await expect(page.getByTestId('global-consumables')).toHaveCount(0);
  const bloc = page.getByTestId('physical-inventory');
  await expect(bloc).toBeVisible({ timeout: 30_000 });
  const fait = bloc.getByTestId('inventory-done');
  const formulaire = bloc.getByTestId('inventory-form');
  await expect(fait.or(formulaire)).toBeVisible({ timeout: 30_000 });
  if (await formulaire.isVisible()) {
    for (const champ of await formulaire.getByRole('textbox', { name: /Quantité physique/ }).all()) await champ.fill('1');
    await formulaire.getByRole('textbox').last().fill('Inventaire e2e');
    await formulaire.getByRole('button', { name: /Enregistrer l'inventaire du jour/ }).click();
  }
  await expect(fait).toBeVisible({ timeout: 20_000 });
  await expect(fait.getByText(/déjà saisi aujourd'hui/)).toBeVisible();
  await fait.getByRole('textbox').fill('Commentaire modifié e2e');
  await fait.getByRole('button', { name: /Enregistrer le commentaire/ }).click();
  await expect(fait.getByText(/Commentaire enregistré/)).toBeVisible({ timeout: 20_000 });
  await sansDebordement(page);
});

test('facturier : aucune vue globale ni inventaire physique', async ({ page }) => {
  test.setTimeout(300_000);
  await seConnecter(page, 'zz_demo_facturier_k1');
  await page.goto('/production', { waitUntil: 'domcontentloaded' });
  await expect(page.getByTestId('global-consumables')).toHaveCount(0);
  await expect(page.getByTestId('physical-inventory')).toHaveCount(0);
});
