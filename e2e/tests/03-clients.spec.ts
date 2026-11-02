import { test, expect } from '@playwright/test';
import { COMPTES, PASSWORD, CLIENT_CROSS_NODE } from '../fixtures/comptes';
import { seConnecter } from '../fixtures/helpers';

/**
 * Parcours 3 — Clients (CLAUDE.md §2 point 3 / §5.1).
 */

test('le gérant crée un client puis le retrouve par nom partiel et par code', async ({ page }) => {
  await seConnecter(page, COMPTES.gerantK1.username, PASSWORD);
  await page.goto('/clients');

  // Note : `Clients.tsx::handleAddClient` découpe le nom saisi en
  // `first_name` (1er mot) / `last_name` (reste), et `Client.full_name`
  // (backend) l'affiche dans l'ordre "last_name first_name" — donc le nom
  // affiché n'est PAS la chaîne saisie telle quelle. On utilise un suffixe
  // numérique unique comme repère stable plutôt que la chaîne complète.
  const suffixeUnique = `${Date.now()}`;
  const nomUnique = `DEMO E2E${suffixeUnique}`;
  await page.getByRole('button', { name: /nouvelle vente/i }).click();
  await page.getByRole('button', { name: /nouveau client/i }).click();
  await page.getByPlaceholder('Ex: Dieudonné Kabeya').fill(nomUnique);
  await page.getByRole('button', { name: /enregistrer l'abonné/i }).click();
  await expect(page.getByRole('button', { name: /enregistrer l'abonné/i })).toHaveCount(0, { timeout: 15_000 });

  // Retrouvé par nom partiel.
  const recherche = page.getByPlaceholder('Rechercher par nom, commerce ou ID...');
  await recherche.fill(suffixeUnique);
  const ligne = page.locator('tr', { hasText: suffixeUnique });
  await expect(ligne).toBeVisible({ timeout: 10_000 });
  const codeAffiche = (await ligne.locator('td').first().textContent())?.trim();
  expect(codeAffiche).toMatch(/^K1-\d{4}$/);

  // Retrouvé par code exact.
  await recherche.fill('');
  await recherche.fill(codeAffiche!);
  await expect(page.locator('tr', { hasText: suffixeUnique })).toBeVisible({ timeout: 10_000 });
});

test('le gérant peut joindre une photo à la création d\'un client (BUG-060, corrigé)', async ({ page }) => {
  // Voir docs/qa/REGISTRE_BUGS.md#BUG-060 : corrigé par dev-frontend le
  // 2026-10-23 — `Clients.tsx` ("Créer une Fiche Client") contient désormais
  // un <input type="file" accept="image/*"> dédié (distinct de l'input de
  // l'import Excel en masse) avec aperçu après sélection.
  await seConnecter(page, COMPTES.gerantK1.username, PASSWORD);
  await page.goto('/clients');
  await page.getByRole('button', { name: /nouvelle vente/i }).click();
  await page.getByRole('button', { name: /nouveau client/i }).click();

  const champPhoto = page.locator('input[type="file"][accept="image/*"]');
  await expect(champPhoto).toHaveCount(1);

  // PNG 1x1 minimal, fictif, généré en mémoire (aucun fichier sur disque).
  const pngUnPixel = Buffer.from(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
    'base64'
  );
  await champPhoto.setInputFiles({ name: 'demo-client-e2e.png', mimeType: 'image/png', buffer: pngUnPixel });

  // Un aperçu (image ou bouton « Retirer ») confirme la sélection prise en compte.
  await expect(page.getByRole('button', { name: /retirer/i })).toBeVisible({ timeout: 5_000 });

  const suffixeUniquePhoto = `PHOTO${Date.now()}`;
  await page.getByPlaceholder('Ex: Dieudonné Kabeya').fill(`DEMO E2E${suffixeUniquePhoto}`);
  await page.getByRole('button', { name: /enregistrer l'abonné/i }).click();
  await expect(page.getByRole('button', { name: /enregistrer l'abonné/i })).toHaveCount(0, { timeout: 15_000 });
});

test('un facturier de K2 retrouve un client rattaché à K1 (remarque.md l.10-12)', async ({ page }) => {
  test.slow(); // voir BUG-061 : la page Clients charge tout le fichier groupe (pagination séquentielle) avant tout filtrage côté client.
  await seConnecter(page, COMPTES.facturierK2.username, PASSWORD);
  await page.goto('/clients');

  // Attend la fin du chargement complet du fichier clients (BUG-061) avant de
  // chercher — sinon le filtre s'applique à un tableau encore vide.
  await expect(page.getByText(/\d+ fiches/)).not.toHaveText('0 fiches', { timeout: 60_000 });

  const recherche = page.getByPlaceholder('Rechercher par nom, commerce ou ID...');
  await recherche.fill(CLIENT_CROSS_NODE.nomPartiel);
  await expect(page.locator('tr', { hasText: CLIENT_CROSS_NODE.code })).toBeVisible({ timeout: 15_000 });
});
