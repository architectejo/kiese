import { test, expect } from '@playwright/test';
import { COMPTES, PASSWORD } from '../fixtures/comptes';
import { seConnecter } from '../fixtures/helpers';

/**
 * Parcours de non-régression ciblé — passe E2E du 2026-10-30 (coordinateur).
 *
 * Couvre explicitement les tickets récemment corrigés et listés comme
 * "déjà vérifiés" dans docs/qa/REGISTRE_BUGS.md, avec un angle E2E que la
 * suite unitaire backend ne peut pas voir (rendu réel du formulaire +
 * cohérence écran-à-écran) :
 *  - BUG-107/111 : aperçu "Vente Soldée" (-25%) cohérent avec le reçu imprimé
 *    final après livraison (Sales.tsx, flux facturier).
 *  - BUG-052 : "Vente sans commission" combinable avec "Vente Soldée", sans
 *    confusion visuelle, requête serveur portant bien les deux indicateurs
 *    (Clients.tsx, flux vente directe gérant).
 *  - BUG-093/108 : clôture de fournée automatisée — action "Clôturer" et
 *    recoupement affiché (Production.tsx).
 *  - BUG-091/105 : Journal de Caisse — un écart avec la Clôture déclenche un
 *    avertissement visuel, jamais un blocage de la saisie (Treasury.tsx).
 *
 * Préalable pour le dernier test (Journal) : une `CashClosure` fixe au
 * 2020-02-02 pour K1 (total_entries = 12 345 FC), créée une fois via
 * `manage.py shell` (voir docs/qa/rapports/testeur-e2e-2026-10-30-passe-complete.md
 * pour le script exact) — ne modifie aucun code applicatif, seulement une
 * donnée de test fixe, hors de toute plage de date utilisée par les autres
 * specs de ce dossier.
 */

test('Vente Soldée (BUG-107/111) : l\'aperçu à -25% avant soumission est cohérent avec le reçu imprimé après livraison', async ({ page }) => {
  test.slow(); // recherche prédictive, voir BUG-065 commenté dans 04-facturation.spec.ts.
  await seConnecter(page, COMPTES.facturierK1.username, PASSWORD);
  await page.goto('/sales/create');

  const recherche = page.getByPlaceholder('Ex: K1-0045 ou KANZA Albert...');
  await recherche.fill('K1-0082'); // client fictif ZZTEST (jamais un client reel)
  const suggestion = page.locator('text=/BP:|Solde OK/').first();
  await expect(suggestion).toBeVisible({ timeout: 45_000 });
  await suggestion.click();

  // Coche "Vente Soldée / Vente Cash".
  const venteSoldee = page.getByText(/Vente Soldée \/ Vente Cash/).first();
  await venteSoldee.click();

  const premiereQte = page.locator('input[type="number"]').first();
  await premiereQte.fill('4');

  // Aperçu : mention explicite de la remise, prix catalogue plein donné pour
  // comparaison (jamais ce qui sera facturé) — cf. Sales.tsx l.1058-1064.
  await expect(page.getByText(/Remise de 25% déjà appliquée \(prix catalogue plein/)).toBeVisible();

  // Capture le total réellement affiché à l'écran (celui qui doit se
  // retrouver, identique, sur le reçu imprimé après livraison).
  const totalAffiche = await page.locator('text=Total commande :').locator('xpath=following-sibling::strong').innerText();

  const versement = page.locator('input[type="number"]').last();
  await versement.fill('0');

  // Capture le numéro de reçu attribué par le serveur à CETTE facture
  // précise — nécessaire pour cibler sans ambiguïté sa carte dans la file
  // d'attente ci-dessous (voir note juste en dessous).
  const [reponseCreation] = await Promise.all([
    page.waitForResponse(res => res.request().method() === 'POST' && res.url().includes('/api/sales/invoices/') && !res.url().includes('/deliver/')),
    page.getByRole('button', { name: /facturer & mettre en attente/i }).click(),
  ]);
  const { receipt_number: numeroRecu } = await reponseCreation.json();
  await expect(page.getByText(/aucune facture en attente/i)).toHaveCount(0, { timeout: 15_000 });

  const carte = page.locator('text=/BP avant/').first();
  await expect(carte).toBeVisible({ timeout: 10_000 });

  // Sélecteur précis : NE PAS utiliser `.first()`/`.last()` sur "Imprimer le
  // reçu" sans scope — la file peut contenir d'autres factures "En attente"
  // laissées par d'autres parcours de la suite (ex. 08-facturation-serie.spec.ts,
  // qui crée 10 factures "Mettre en attente" jamais livrées) ou par une
  // exécution précédente de CE MÊME test resté en attente (ex. un échec
  // avant la confirmation de livraison) — un filtre générique sur le badge
  // "SOLDÉE" peut alors matcher PLUSIEURS cartes (l'ancienne ET la nouvelle),
  // avec un ordre non garanti. On cible donc sans ambiguïté la carte portant
  // le numéro de reçu exact retourné par le serveur pour CETTE facture.
  const carteSoldee = page.locator('div')
    .filter({ hasText: numeroRecu })
    .filter({ has: page.getByRole('button', { name: /imprimer le reçu/i }) })
    .last();
  await carteSoldee.getByRole('button', { name: /imprimer le reçu/i }).click();
  await expect(page.getByText('Confirmer la livraison')).toBeVisible({ timeout: 10_000 });
  await page.getByRole('button', { name: /confirmer & imprimer/i }).click();
  await expect(page.getByText(/BON DE LIVRAISON/)).toBeVisible({ timeout: 10_000 });

  // BUG-111 : le total général du reçu (lu du serveur, `order_total`) doit
  // être EXACTEMENT celui déjà annoncé à l'écran avant soumission — pas le
  // prix catalogue plein. Scopé à la ligne "TOTAL (FC)" du reçu (plusieurs
  // autres éléments de l'écran — ex. le KPI "TOTAL FACTURÉ" — peuvent
  // afficher coïncidentellement le même montant).
  const ligneTotalRecu = page.locator('tr', { hasText: 'TOTAL (FC)' });
  await expect(ligneTotalRecu.getByText(totalAffiche.replace(/\s*FC$/, ''), { exact: false })).toBeVisible();

  await page.getByRole('button', { name: /fermer/i }).last().click();
});

test('Vente sans commission + Vente Soldée (BUG-052) : les deux cases sont combinables sans confusion visuelle, et la requête porte bien les deux indicateurs', async ({ page }) => {
  await seConnecter(page, COMPTES.gerantK1.username, PASSWORD);
  await page.goto('/clients');

  const recherche = page.getByPlaceholder('Rechercher par nom, commerce ou ID...');
  await recherche.fill('CrossNodeE2E');
  const ligne = page.locator('tr', { hasText: 'K1-0078' });
  await expect(ligne).toBeVisible({ timeout: 10_000 });
  await ligne.getByTitle('Enregistrer un Achat / Vente').click();
  await expect(page.getByText('Enregistrer commande')).toBeVisible();

  const caseSansCommission = page.getByRole('checkbox', { name: /Vente sans commission/i });
  const caseVenteSoldee = page.getByRole('checkbox', { name: /Vente Soldée \/ Vente Cash/i });

  await caseSansCommission.check();
  await caseVenteSoldee.check();

  // Les deux cases restent cochées simultanément — aucune exclusion mutuelle
  // résiduelle (régression possible de l'ancien comportement avant BUG-052).
  await expect(caseSansCommission).toBeChecked();
  await expect(caseVenteSoldee).toBeChecked();

  // Message explicite de combinaison, sans contradiction visuelle.
  await expect(page.getByText(/Facture à la fois SOLDÉE.*ET sans commission.*CM=0 dans tous les cas/)).toBeVisible();

  const premiereQte = page.locator('#sale-form input[type="number"]').first();
  await premiereQte.fill('2');

  const [requeteCreation] = await Promise.all([
    page.waitForRequest(req =>
      req.method() === 'POST' &&
      req.url().includes('/api/sales/invoices/') &&
      !req.url().includes('/deliver/'),
    ),
    page.getByRole('button', { name: /confirmer la transaction/i }).click(),
  ]);
  const requeteFacture = requeteCreation.postDataJSON() as {
    is_soldee?: boolean; commission_exempt?: boolean; commission_rate?: number;
  };
  await expect(page.getByText('Enregistrer commande')).toHaveCount(0, { timeout: 15_000 });

  expect(requeteFacture.is_soldee).toBe(true);
  expect(requeteFacture.commission_exempt).toBe(true);
  // BUG-230 : `commission_rate` n'est plus envoye (le serveur applique le taux ; exoneree -> CM=0 cote serveur).
  expect(requeteFacture.commission_rate).toBeUndefined();
});

// BUG-306 : déclaration par sacs seuls. Équipe B (les parcours 05 utilisent l'équipe A) sur une boulangerie
// hors rotation par largeur d'écran : pos -> K2, tablette -> K5, bureau -> B1.
const GERANT_B = ['zz_demo_gerant_k2', 'zz_prod_gerant_k4', 'zz_e301_gerant', 'zz_e301_gerant']; // pos -> K2, tablette -> K4, bureau -> B2

test('Clôture de fournée automatisée (BUG-093/108) : l\'action "Clôturer" déclenche le recoupement et verrouille la saisie', async ({ page, request }, info) => {
  const i = Math.max(0, ['pos', 'tablette', 'bureau', 'tv'].indexOf(info.project.name));
  // Une seule fournée « en cours » par boulangerie : on clôture par l'API celle laissée par le parcours 05 (zz_* uniquement).
  const API = process.env.E2E_API_URL || 'http://localhost:8000';
  const tk = (await (await request.post(`${API}/api/core/auth/login/`, { data: { username: GERANT_B[i], password: GERANT_B[i] } })).json()).access as string;
  const H = { Authorization: `Bearer ${tk}` };
  const ouvertes = await (await request.get(`${API}/api/production/sessions/?is_closed=false&page_size=50`, { headers: H })).json();
  for (const sess of (ouvertes.results ?? ouvertes) as Array<{ id: string; is_closed: boolean }>) {
    if (!sess.is_closed) await request.post(`${API}/api/production/sessions/${sess.id}/close/`, { headers: H, data: { remaining: [] } });
  }
  await seConnecter(page, GERANT_B[i], PASSWORD);
  await page.goto('/production', { waitUntil: 'domcontentloaded' });

  const panneau = page.getByTestId('batch-in-progress-panel');
  await expect(panneau.getByText('Déclaration de Fournée')).toBeVisible({ timeout: 30_000 });
  await panneau.getByLabel('Équipe', { exact: true }).selectOption('B');
  await panneau.getByLabel(/Nombre de sacs de farine/).fill('1');
  await panneau.getByRole('button', { name: /enregistrer la fournée/i }).click();
  // (« Fournée en cours » seul serait vrai aussi dans la phrase d'aide « Aucune fournée en cours... » : on attend l'objectif)
  await expect(panneau.getByTestId('batch-objective')).toBeVisible({ timeout: 30_000 });

  // BUG-315 : l'historique se rafraîchit seul après la déclaration (plus de rechargement de page).
  // Rouvre la fournée (équipe B, aujourd'hui) pour la clôturer.
  await page.getByText(/Éq\.B/).first().click();
  const detail = page.getByRole('dialog', { name: 'Détail Fournée' });
  await expect(detail).toBeVisible({ timeout: 10_000 });
  await detail.getByRole('button', { name: 'Clôturer la fournée' }).click();
  const m = page.getByRole('dialog', { name: 'Clôturer la Fournée' });
  await expect(m).toBeVisible();
  await m.getByRole('button', { name: 'Confirmer la clôture' }).click();
  await expect(m).toBeHidden({ timeout: 20_000 });

  await expect(page.getByText(/Fournée clôturée/)).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText('Recoupement automatique à la clôture')).toBeVisible();
  // Saisie verrouillée : plus de bouton "Clôturer".
  await expect(page.getByRole('button', { name: /clôturer la fournée/i })).toHaveCount(0);
});

test("BUG-315 : après déclaration d'une fournée, « Historique des Fournées » l'affiche sans rechargement de la page", async ({ page, request }, info) => {
  const i = Math.max(0, ['pos', 'tablette', 'bureau', 'tv'].indexOf(info.project.name));
  const API = process.env.E2E_API_URL || 'http://localhost:8000';
  const tk = (await (await request.post(`${API}/api/core/auth/login/`, { data: { username: GERANT_B[i], password: GERANT_B[i] } })).json()).access as string;
  const H = { Authorization: `Bearer ${tk}` };
  const ouvertes = await (await request.get(`${API}/api/production/sessions/?is_closed=false&page_size=50`, { headers: H })).json();
  for (const sess of (ouvertes.results ?? ouvertes) as Array<{ id: string; is_closed: boolean }>) {
    if (!sess.is_closed) await request.post(`${API}/api/production/sessions/${sess.id}/close/`, { headers: H, data: { remaining: [] } });
  }
  await seConnecter(page, GERANT_B[i], PASSWORD);
  await page.goto('/production', { waitUntil: 'domcontentloaded' });
  const panneau = page.getByTestId('batch-in-progress-panel');
  await expect(panneau.getByText('Déclaration de Fournée')).toBeVisible({ timeout: 30_000 });
  await panneau.getByLabel('Équipe', { exact: true }).selectOption('B');
  await panneau.getByLabel(/Nombre de sacs de farine/).fill('1');
  await panneau.getByRole('button', { name: /enregistrer la fournée/i }).click();
  await expect(panneau.getByTestId('batch-objective')).toBeVisible({ timeout: 30_000 });
  // Sans rechargement : la ligne « Éq.B » apparaît dans l'historique.
  await expect(page.getByText(/Éq\.B/).first()).toBeVisible({ timeout: 10_000 });
});

test('Journal de Caisse (BUG-091/105) : un écart avec la Clôture déclenche un avertissement, jamais un blocage', async ({ page }) => {
  await seConnecter(page, COMPTES.gerantK1.username, PASSWORD);
  await page.goto('/treasury');

  const sectionJournal = page.locator('text=§5.1.4 — Journal de Caisse par Boulangerie').locator('xpath=../..');
  const dateJournal = sectionJournal.locator('input[type="date"]').first();
  await dateJournal.fill('2020-02-02');

  // Imputation CA déjà sélectionnée par défaut — attend le pré-remplissage
  // automatique depuis la Clôture fixe du 2020-02-02 (12 345 FC, fixture dédiée).
  await expect(sectionJournal.getByText(/Rapproché à la Clôture \(12.?345/)).toBeVisible({ timeout: 10_000 });

  // Écrase volontairement la valeur pré-remplie pour créer un écart déclaré.
  // Sélecteur précis : le champ "Entrée (FC)" n'est PAS le premier
  // input[type=number] de la section — le sélecteur "Année" (navigation
  // mois/année du journal, au-dessus du formulaire) en est un, avant lui
  // dans le DOM, et `.first()` le ciblerait par erreur.
  const champEntree = sectionJournal.locator('text=Entrée (FC)').locator('xpath=following-sibling::input[@type="number"]');
  await champEntree.fill('20000');
  await expect(sectionJournal.getByText(/Écart avec la Clôture : \+/)).toBeVisible();

  await sectionJournal.getByRole('button', { name: /enregistrer/i }).click();

  // Jamais de blocage : message d'avertissement explicite, pas d'erreur.
  await expect(sectionJournal.getByText(/Écriture enregistrée — écart de \+.*FC avec la Clôture/)).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText(/^Erreur/)).toHaveCount(0);
});
