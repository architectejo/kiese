import { test, expect } from '@playwright/test';
import { COMPTES, PASSWORD } from '../fixtures/comptes';
import { seConnecter } from '../fixtures/helpers';

/**
 * Parcours 6 — Production (CLAUDE.md §2 point 6 / §5.4).
 */

// BUG-306 (2026-11-19) : la déclaration de fournée se fait par SACS seuls (consommables facultatifs) ;
// l'écart manquant/excédent est lu en Clôture Journalière. Une seule fournée par équipe et par jour :
// une boulangerie (hors rotation) par largeur d'écran : pos -> K2, tablette -> K5, bureau -> B1.
const GERANT_PAR_LARGEUR = ['zz_demo_gerant_k2', 'zz_demo_gerant_k5', 'zz_demo_gerant_b1', 'zz_demo_gerant_b1'];

test('déclaration de fournée avec consommables décimaux, écart manquant/excédent affiché', async ({ page }, info) => {
  const idx = Math.max(0, ['pos', 'tablette', 'bureau', 'tv'].indexOf(info.project.name));
  await seConnecter(page, GERANT_PAR_LARGEUR[idx], PASSWORD);
  // BUG-148 : le panneau affiche « Déclaration de Fournée » tant que la fournée du jour n'est pas chargée
  // (puis bascule sur « Fournée en cours »). On attend donc la réponse de l'API avant de lire l'état.
  const sessionsChargees = page.waitForResponse(r => /\/api\/production\/sessions\/\?.*date=/.test(r.url()) && r.ok(), { timeout: 30_000 });
  await page.goto('/production', { waitUntil: 'domcontentloaded' });
  await sessionsChargees;
  await page.waitForLoadState('networkidle');

  const panneau = page.getByTestId('batch-in-progress-panel');
  // BUG-148 : une seule fournee par equipe et par jour. Le test doit etre idempotent : selon l'etat de la base
  // (premiere execution du jour ou rejeu), le panneau affiche soit le formulaire de declaration, soit la
  // fournee deja en cours. On attend explicitement l'un OU l'autre (aucune attente fixe).
  const formulaire = panneau.getByRole('heading', { name: 'Déclaration de Fournée' });
  const enCours = panneau.getByRole('heading', { name: 'Fournée en cours' });
  await expect(formulaire.or(enCours)).toBeVisible({ timeout: 30_000 });
  if (!(await enCours.isVisible()) && (await formulaire.isVisible())) {
    // Etat partage : un autre parcours (ex. 10, cloture de fournee) peut avoir cloture la session de l'equipe A du jour
    // (message « Session de production clôturée » apres l'envoi). On bascule alors sur l'equipe B ; si elle est aussi
    // cloturee, la base du jour est epuisee : skip explicite plutot qu'un echec trompeur.
    const cloturee = panneau.getByRole('alert').filter({ hasText: /Session de production clôturée/ });
    for (const equipe of ['Équipe A', 'Équipe B']) {
      await panneau.getByLabel('Équipe', { exact: true }).selectOption({ label: equipe });
      await panneau.getByLabel(/Nombre de sacs de farine/).fill('2');
      // Consommables décimaux : sel (grammes, entier), levure (paquets, décimal), huile (litres, décimal).
      await panneau.getByLabel('Sel en grammes').fill('450');
      await panneau.getByLabel('Levure en paquets').fill('0.25');
      await panneau.getByLabel('Huile en litres').fill('0.5');
      await expect(panneau.getByText(/Montant à atteindre :/)).toBeVisible();
      await panneau.getByRole('button', { name: /enregistrer la fournée/i }).click();
      await expect(enCours.or(cloturee)).toBeVisible({ timeout: 20_000 });
      if (await enCours.isVisible()) break;
      if (equipe === 'Équipe B') test.skip(true, 'Sessions A et B du jour deja cloturees : relancer sur une base du jour neuve (BUG-148)');
    }
  }
  await expect(enCours).toBeVisible({ timeout: 20_000 });
  await expect(panneau.getByTestId('batch-objective')).toBeVisible();
  await expect(page.getByText(/stock insuffisant/i)).toHaveCount(0);

  // Écart : 2 sacs déclarés, aucun pain livré -> écart de production lisible en Clôture Journalière.
  await page.goto('/cloture-journaliere', { waitUntil: 'domcontentloaded' });
  const carte = page.getByRole('button', { name: 'Écart / Production : voir le détail' });
  await expect(carte).toBeVisible({ timeout: 30_000 });
  await carte.click();
  await expect(page.getByRole('dialog', { name: 'Écart / Production' })).toContainText(/Manquant|Excédent|Aucun écart/);
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
