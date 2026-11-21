import { test, expect, type Page, type Locator } from '@playwright/test';
import { seConnecter } from '../fixtures/helpers';

/**
 * Parcours Clients en lecture seule (demande de C, message #11) : liste, recherche, fiche detaillee et historique.
 * Aucune ecriture. Concu pour la largeur POS (360 px) mais valable sur toutes les tailles.
 * Compte : gerant K4 du seed e2e (zz_clients_gerant, mot de passe = identifiant).
 */
// Largeur POS imposee quel que soit le projet Playwright (preuve du 360 px, demande de C).
test.use({ viewport: { width: 360, height: 740 } });

/** Aucun defilement horizontal de la page (tolerance 1 px). */
async function sansDefilementHorizontal(page: Page, ecran: string) {
  const { scroll, client } = await page.evaluate(() => ({ scroll: document.body.scrollWidth, client: document.body.clientWidth }));
  expect(scroll, `defilement horizontal sur ${ecran} (scrollWidth ${scroll} > clientWidth ${client})`).toBeLessThanOrEqual(client + 1);
}

test('Clients (lecture seule) : liste, recherche, fiche et historique', async ({ page }) => {
  test.slow(); // la page Clients charge tout le fichier groupe avant filtrage (BUG-061)
  await seConnecter(page, 'zz_clients_gerant');
  await page.goto('/clients', { waitUntil: 'domcontentloaded' });

  // Liste : le compteur de fiches doit devenir non nul, sans attente fixe.
  await expect(page.getByText(/\d+ fiches/)).not.toHaveText('0 fiches', { timeout: 60_000 });
  const lignes = page.locator('tbody tr');
  await expect(lignes.first()).toBeVisible();
  expect(page.viewportSize()?.width).toBe(360);
  await sansDefilementHorizontal(page, 'la liste Clients');
  const total = await lignes.count();
  expect(total).toBeGreaterThan(0);

  // Recherche : on reprend le nom du premier client affiche, la liste filtree le contient.
  const nom = ((await lignes.first().locator('td').nth(1).innerText()).split('\n')[0] || '').trim();
  expect(nom.length).toBeGreaterThan(1);
  const recherche = page.getByPlaceholder('Rechercher par nom, commerce ou ID...');
  await recherche.fill(nom.slice(0, Math.max(3, Math.min(6, nom.length))));
  await expect(lignes.first()).toContainText(nom.slice(0, 3), { ignoreCase: true });

  // Fiche detaillee (bouton oeil), puis fermeture sans modification.
  const oeil = lignes.first().getByTitle('Voir la fiche détaillée');
  await oeil.click(); // Playwright fait defiler le tableau si besoin (voir le test BUG-415 pour l'accessibilite sans defilement)
  await expect(page.getByRole('heading', { name: nom, exact: false }).first()).toBeVisible();
  await sansDefilementHorizontal(page, 'la fiche detaillee');
  await page.keyboard.press('Escape');
  await expect(page.locator('.modal-backdrop')).toHaveCount(0);

  // Historique des achats et depots (visible si le role peut lire la caisse sociale).
  const histo = lignes.first().getByTitle("Voir l'historique des achats et dépôts");
  await expect(histo, "bouton d'historique absent pour ce compte").toHaveCount(1);
  await histo.click();
  await expect(page.getByText('Historique du client').first()).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole('status')).toHaveCount(0, { timeout: 15_000 }); // fin du chargement
  await sansDefilementHorizontal(page, "l'historique client");
});

/** Ramene la ligne a l'ecran par defilement VERTICAL de la page uniquement (jamais de defilement horizontal du tableau). */
async function amenerVerticalement(loc: Locator) {
  await loc.evaluate(el => window.scrollBy(0, el.getBoundingClientRect().top - window.innerHeight / 2));
}

test('Clients a 360 px : bouton historique et bouton fiche visibles sans defilement horizontal du tableau', async ({ page }) => {
  test.slow();
  test.fixme(!process.env.E2E_BUG415, 'BUG-415 (E2E_BUG415=1 pour rejouer) : la colonne Actions (oeil) du tableau Clients depasse a droite du viewport 360 px (defilement horizontal interne au tableau)');
  await seConnecter(page, 'zz_clients_gerant');
  await page.goto('/clients', { waitUntil: 'domcontentloaded' });
  await expect(page.getByText(/\d+ fiches/)).not.toHaveText('0 fiches', { timeout: 60_000 });
  const ligne = page.locator('tbody tr').first();
  await expect(ligne).toBeVisible();
  await expect(async () => {
    await amenerVerticalement(ligne);
    await expect(ligne.getByTitle("Voir l'historique des achats et dépôts")).toBeInViewport({ ratio: 1 });
    await expect(ligne.getByTitle('Voir la fiche détaillée')).toBeInViewport({ ratio: 1 });
  }).toPass({ timeout: 15_000 });
});
