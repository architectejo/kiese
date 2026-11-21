import { test, expect } from '@playwright/test';
import { seConnecter } from '../fixtures/helpers';

/**
 * Parcours Clients en lecture seule (demande de C, message #11) : liste, recherche, fiche detaillee et historique.
 * Aucune ecriture. Concu pour la largeur POS (360 px) mais valable sur toutes les tailles.
 * Compte : gerant K4 du seed e2e (zz_clients_gerant, mot de passe = identifiant).
 */
test('Clients (lecture seule) : liste, recherche, fiche et historique', async ({ page }) => {
  test.slow(); // la page Clients charge tout le fichier groupe avant filtrage (BUG-061)
  await seConnecter(page, 'zz_clients_gerant');
  await page.goto('/clients', { waitUntil: 'domcontentloaded' });

  // Liste : le compteur de fiches doit devenir non nul, sans attente fixe.
  await expect(page.getByText(/\d+ fiches/)).not.toHaveText('0 fiches', { timeout: 60_000 });
  const lignes = page.locator('tbody tr');
  await expect(lignes.first()).toBeVisible();
  const total = await lignes.count();
  expect(total).toBeGreaterThan(0);

  // Recherche : on reprend le nom du premier client affiche, la liste filtree le contient.
  const nom = ((await lignes.first().locator('td').nth(1).innerText()).split('\n')[0] || '').trim();
  expect(nom.length).toBeGreaterThan(1);
  const recherche = page.getByPlaceholder('Rechercher par nom, commerce ou ID...');
  await recherche.fill(nom.slice(0, Math.max(3, Math.min(6, nom.length))));
  await expect(lignes.first()).toContainText(nom.slice(0, 3), { ignoreCase: true });

  // Fiche detaillee (bouton oeil), puis fermeture sans modification.
  await lignes.first().getByTitle('Voir la fiche détaillée').click();
  await expect(page.getByRole('heading', { name: nom, exact: false }).first()).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.locator('.modal-backdrop')).toHaveCount(0);

  // Historique des achats et depots (visible si le role peut lire la caisse sociale).
  const histo = lignes.first().getByTitle("Voir l'historique des achats et dépôts");
  if (await histo.count()) {
    await histo.click();
    await expect(page.getByText('Historique du client').first()).toBeVisible({ timeout: 15_000 });
    await expect(page.getByRole('status')).toHaveCount(0, { timeout: 15_000 }); // fin du chargement
  }
});
