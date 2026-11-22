import { test, expect, Page } from '@playwright/test';
import { seConnecter } from '../fixtures/helpers';

/**
 * BUG-387 — Vue globale des consommables (direction) + Inventaire Physique (gérant).
 * BUG-388 : approvisionnement du stock direction puis envoi à une boulangerie.
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

/** Lit un nombre affiché par formatQty (espaces insécables, virgule décimale). */
function nombre(texte: string): number {
  return Number(texte.replace(/[\s  ]/g, '').replace(',', '.'));
}

test('BUG-388 direction : approvisionner le stock direction puis envoyer une partie à une boulangerie', async ({ page }) => {
  test.setTimeout(300_000);
  await seConnecter(page, 'zz_demo_direction');
  await ouvrirIntrants(page);
  await expect(page.getByTestId('global-consumables')).toBeVisible({ timeout: 30_000 });
  const formAppro = page.getByTestId('supply-form');
  await expect(formAppro).toBeVisible();
  await expect(formAppro.getByRole('button', { name: 'Approvisionner le stock direction' })).toBeVisible();
  // 1re colonne de consommable (celle des deux formulaires par défaut) = cellule n° 1 de chaque ligne.
  const celluleDirection = page.getByTestId('global-row-direction').locator('td').nth(1);
  const celluleK1 = page.getByTestId('global-row-K1').locator('td').nth(1);
  const d0 = nombre(await celluleDirection.innerText());
  const k0 = nombre(await celluleK1.innerText());

  // Erreur : quantité vide -> message clair, aucune écriture.
  await formAppro.getByRole('button', { name: 'Approvisionner le stock direction' }).click();
  await expect(formAppro.getByRole('alert').filter({ hasText: /Quantité invalide/ })).toBeVisible();
  expect(nombre(await celluleDirection.innerText())).toBe(d0);

  // Entrée de 2,5 sur le stock direction (prix unitaire 1 000 FC).
  await formAppro.getByLabel('Quantité à ajouter').fill('2,5');
  await formAppro.getByLabel('Prix unitaire en FC').fill('1000');
  await formAppro.getByLabel('Note ou référence').fill('Approvisionnement e2e BUG-388');
  await formAppro.getByRole('button', { name: 'Approvisionner le stock direction' }).click();
  await expect(formAppro.getByRole('status').filter({ hasText: /ajouté\(s\) au stock direction/ })).toBeVisible({ timeout: 20_000 });
  await expect.poll(async () => nombre(await celluleDirection.innerText()), { timeout: 20_000 }).toBeCloseTo(d0 + 2.5, 3);

  // Envoi d'1 unité à K1 : le stock direction diminue, celui de K1 augmente (somme nulle).
  const envoi = page.getByTestId('dispatch-form');
  await envoi.getByLabel(/Quantité pour K1/).fill('1');
  await envoi.getByRole('button', { name: /Envoyer aux boulangeries/ }).click();
  await expect(envoi.getByRole('status').filter({ hasText: /envoyé\(s\)/ })).toBeVisible({ timeout: 20_000 });
  await expect.poll(async () => nombre(await celluleDirection.innerText()), { timeout: 20_000 }).toBeCloseTo(d0 + 1.5, 3);
  await expect.poll(async () => nombre(await celluleK1.innerText()), { timeout: 20_000 }).toBeCloseTo(k0 + 1, 3);
  await sansDebordement(page);
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
  await fait.getByRole('textbox').fill(`Commentaire modifié e2e ${Date.now()}`) // unique : le bouton reste inactif si le texte est inchangé (rejouable);
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
