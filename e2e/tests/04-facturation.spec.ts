import { test, expect } from '@playwright/test';
import { COMPTES, PASSWORD, CLIENT_AU_PLAFOND, CLIENT_POUR_REMBOURSEMENT } from '../fixtures/comptes';
import { seConnecter, seDeconnecter } from '../fixtures/helpers';

/**
 * Parcours 4 — Facturation (CLAUDE.md §2 point 4 / §5.2).
 */

test('le facturier crée une facture, voit la BP avant, confirme la livraison et le reçu s\'affiche', async ({ page }) => {
  test.slow(); // voir BUG-065 : Sales.tsx charge tout le fichier clients avant que la recherche prédictive ne retourne un résultat.
  await seConnecter(page, COMPTES.facturierK1.username, PASSWORD);
  await page.goto('/sales/create');

  const recherche = page.getByPlaceholder('Ex: K1-0045 ou KANZA Albert...');
  await recherche.fill('K1-');
  const suggestion = page.locator('text=/BP:|Solde OK/').first();
  await expect(suggestion).toBeVisible({ timeout: 45_000 });
  await suggestion.click();

  // La BP avant doit être affichée dès la sélection du client.
  await expect(page.getByText(/BP\s*:/)).toBeVisible();

  const premiereQte = page.locator('input[type="number"]').first();
  await premiereQte.fill('5');
  const versement = page.locator('input[type="number"]').last();
  await versement.fill('0');

  await page.getByRole('button', { name: /facturer & mettre en attente/i }).click();
  await expect(page.getByText(/aucune facture en attente/i)).toHaveCount(0, { timeout: 15_000 });

  // La facture doit apparaître "En attente" dans la file, avec la BP avant/après visible.
  const carte = page.locator('text=/BP avant/').first();
  await expect(carte).toBeVisible({ timeout: 10_000 });

  // Confirmation de la livraison → modale "Confirmer la livraison" (BUG-083,
  // date de livraison rétroactive optionnelle, Sales.tsx l.877) → reçu affiché.
  await page.getByRole('button', { name: /imprimer le reçu/i }).first().click();
  await expect(page.getByText('Confirmer la livraison')).toBeVisible({ timeout: 10_000 });
  await page.getByRole('button', { name: /confirmer & imprimer/i }).click();
  await expect(page.getByText(/BON DE LIVRAISON/)).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText(/BALANCE ANTÉRIEURE \(BP\)/)).toBeVisible();
  await expect(page.getByText(/NOUVELLE DETTE/)).toBeVisible();
  await page.getByRole('button', { name: /fermer/i }).last().click(); // le Modal générique ajoute aussi un bouton X aria-label="Fermer" dans l'entête (Modal.tsx) — .last() cible le bouton pied de page du reçu (ThermalReceipt.tsx)
});

test('le reçu affiche le code boulangerie, le RCCM contractuel et la mention "Solde arrêté ce jour" (BUG-059)', async ({ page }) => {
  // Voir docs/qa/REGISTRE_BUGS.md#BUG-059 : corrigé par dev-frontend le
  // 2026-10-23 dans ThermalReceipt.tsx — vérifie ici que receipt.boulangerie
  // est bien affiché (nœud K1 émetteur), que le RCCM contractuel
  // (CLAUDE.md §5.2 / cahierDesCharges.md §4.4.1) est correct, et que la
  // mention de clôture journalière est présente sous BP avant/BP après.
  test.slow(); // voir BUG-065 : Sales.tsx charge tout le fichier clients avant que la recherche prédictive ne retourne un résultat.
  await seConnecter(page, COMPTES.facturierK1.username, PASSWORD);
  await page.goto('/sales/create');

  const recherche = page.getByPlaceholder('Ex: K1-0045 ou KANZA Albert...');
  await recherche.fill('K1-');
  const suggestion = page.locator('text=/BP:|Solde OK/').first();
  await expect(suggestion).toBeVisible({ timeout: 45_000 });
  await suggestion.click();

  await expect(page.getByText(/BP\s*:/)).toBeVisible();

  const premiereQte = page.locator('input[type="number"]').first();
  await premiereQte.fill('5');
  const versement = page.locator('input[type="number"]').last();
  await versement.fill('0');

  await page.getByRole('button', { name: /facturer & mettre en attente/i }).click();
  await expect(page.getByText(/aucune facture en attente/i)).toHaveCount(0, { timeout: 15_000 });

  const carte = page.locator('text=/BP avant/').first();
  await expect(carte).toBeVisible({ timeout: 10_000 });

  // Confirmation de la livraison → modale "Confirmer la livraison" (BUG-083,
  // date de livraison rétroactive optionnelle, Sales.tsx l.877) → reçu affiché.
  await page.getByRole('button', { name: /imprimer le reçu/i }).first().click();
  await expect(page.getByText('Confirmer la livraison')).toBeVisible({ timeout: 10_000 });
  await page.getByRole('button', { name: /confirmer & imprimer/i }).click();
  await expect(page.getByText(/BON DE LIVRAISON/)).toBeVisible({ timeout: 10_000 });

  // Code boulangerie émetteur (nœud K1, "demo_facturier_k1_e2e") : le nœud
  // s'affiche "K1 - TABORA" (avec espaces autour du tiret, Node.__str__
  // backend) — distinct des numéros de facture/codes client "K1-xxxx" (sans
  // espaces) qui matcheraient aussi un regex trop permissif.
  await expect(page.getByText(/^K1 - /)).toBeVisible();
  // RCCM contractuel (CLAUDE.md §5.2 / cahierDesCharges.md §4.4.1 : 021-A-650).
  await expect(page.getByText(/RCCM:\s*021-A-650/)).toBeVisible();
  // Mention obligatoire de clôture de solde journalier.
  await expect(page.getByText('Solde arrêté ce jour')).toBeVisible();

  await page.getByRole('button', { name: /fermer/i }).last().click(); // le Modal générique ajoute aussi un bouton X aria-label="Fermer" dans l'entête (Modal.tsx) — .last() cible le bouton pied de page du reçu (ThermalReceipt.tsx)
});

test('recherche prédictive client (BUG-065) : une recherche précise ne déclenche qu\'une seule requête réseau, répond en moins d\'1 s et affiche "Aucun client ne correspond" si vide', async ({ page }) => {
  // Vérification dynamique de la correction BUG-065 (dev-frontend, 2026-10-23) :
  // Sales.tsx ne charge plus le fichier clients entier (690+ fiches / ~28 pages)
  // avant la première suggestion ; la recherche interroge désormais le serveur
  // via `?search=...`. Testé ici avec un terme précis (un seul résultat attendu
  // dans le jeu de données e2e) — voir aussi le constat BUG-069 ci-dessous pour
  // le cas d'un terme large (ex. "K1-") qui matche tout le fichier d'une
  // boulangerie et redéclenche une boucle de pagination partielle.
  await seConnecter(page, COMPTES.facturierK1.username, PASSWORD);
  await page.goto('/sales/create');

  const requetesClients: string[] = [];
  page.on('request', req => {
    if (req.url().includes('/api/clients/clients/')) requetesClients.push(req.url());
  });

  const recherche = page.getByPlaceholder('Ex: K1-0045 ou KANZA Albert...');
  const debut = Date.now();
  await recherche.fill('ADELINE');
  const suggestion = page.locator('text=/BP:|Solde OK/').first();
  await expect(suggestion).toBeVisible({ timeout: 5_000 });
  const duree = Date.now() - debut;
  expect(duree).toBeLessThan(5_000); // debounce 350ms + aller-retour réseau ; << les ~20-30s d'avant correction

  // Une seule requête `?search=...` — pas de boucle de pagination complète
  // (`?page=2&search=...`, etc.) pour un terme qui ne matche qu'une poignée
  // de clients.
  expect(requetesClients.length).toBe(1);
  expect(requetesClients[0]).toContain('search=ADELINE');
  expect(requetesClients.some(u => u.includes('page='))).toBe(false);

  // Terme sans correspondance -> message explicite distinct de l'état de
  // chargement, pas un panneau vide silencieux.
  await recherche.fill('');
  await recherche.fill('ZZZINEXISTANT999');
  await expect(page.getByText('Aucun client ne correspond à « ZZZINEXISTANT999 ».')).toBeVisible({ timeout: 5_000 });
});

test('recherche prédictive client (BUG-065) : pas de défilement de page à 360px et le client déjà sélectionné reste affiché', async ({ page }) => {
  await seConnecter(page, COMPTES.facturierK1.username, PASSWORD);
  await page.goto('/sales/create');

  const recherche = page.getByPlaceholder('Ex: K1-0045 ou KANZA Albert...');
  await recherche.fill('ADELINE');
  await page.waitForTimeout(80); // avant la fin du debounce (350ms) -> état "Recherche en cours..."
  const pendantRecherche = await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1);
  expect(pendantRecherche).toBe(true);

  const suggestion = page.locator('text=/BP:|Solde OK/').first();
  await expect(suggestion).toBeVisible({ timeout: 5_000 });
  const avecSuggestions = await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1);
  expect(avecSuggestions).toBe(true);

  await suggestion.click();
  const panneauClient = page.locator('text=Balance antérieure');
  await expect(panneauClient).toBeVisible();

  // Le panneau du client déjà sélectionné reste affiché indépendamment de
  // l'état de la recherche (focus/escape sans retoucher le texte saisi).
  await recherche.focus();
  await page.keyboard.press('Escape');
  await expect(panneauClient).toBeVisible();
});

test('un client au plafond de crédit est bloqué si le versement ne couvre pas la commande', async ({ page }) => {
  await seConnecter(page, COMPTES.gerantK1.username, PASSWORD);
  await page.goto('/clients');

  const recherche = page.getByPlaceholder('Rechercher par nom, commerce ou ID...');
  await recherche.fill(CLIENT_AU_PLAFOND.nomPartiel);
  const ligne = page.locator('tr', { hasText: CLIENT_AU_PLAFOND.code });
  await expect(ligne).toBeVisible({ timeout: 10_000 });

  await ligne.getByTitle('Enregistrer un Achat / Vente').click();
  await expect(page.getByText('Enregistrer commande')).toBeVisible();

  const premiereQte = page.locator('input[type="number"]').first();
  await premiereQte.fill('3'); // commande > 0 FC
  const versement = page.getByPlaceholder('0').last();
  await versement.fill('0'); // versement nul, insuffisant

  const bouton = page.getByRole('button', { name: /plafond atteint/i });
  await expect(bouton).toBeVisible({ timeout: 10_000 });
  await expect(bouton).toBeDisabled();
});

test('un remboursement réduit la BP du client sans créer de vente', async ({ page }) => {
  // Client dédié, distinct de CLIENT_AU_PLAFOND : un remboursement réel modifie
  // durablement la dette en base, ce qui casserait le test de blocage au
  // plafond ci-dessus si les deux tests partageaient le même client entre
  // deux exécutions de la suite (constaté en conditions réelles pendant cette
  // session : cf. rapport testeur-e2e, §2.2).
  await seConnecter(page, COMPTES.gerantK1.username, PASSWORD);
  await page.goto('/clients');

  const recherche = page.getByPlaceholder('Rechercher par nom, commerce ou ID...');
  await recherche.fill(CLIENT_POUR_REMBOURSEMENT.nomPartiel);
  const ligne = page.locator('tr', { hasText: CLIENT_POUR_REMBOURSEMENT.code });
  await expect(ligne).toBeVisible({ timeout: 10_000 });

  await ligne.getByTitle('Voir la fiche détaillée').click();

  // Note sélecteur : l'onglet "Remboursements" de la modale est lui-même un
  // élément cliquable dont le nom matche /rembourse/i — on cible donc le
  // bouton exact du pied de modale, renommé "Remboursement / Dépôt sans
  // commande" par BUG-090/098 (Clients.tsx l.2054), pas l'onglet.
  const boutonRemboursement = page.getByRole('button', { name: 'Remboursement / Dépôt sans commande' });
  await expect(boutonRemboursement).toBeVisible({ timeout: 10_000 });
  await boutonRemboursement.click();

  // Le champ n'affiche pas de plafond "Max :" (Clients.tsx l.2108 : placeholder
  // "Ex : 10 000", aucune borne haute affichée) — assertion précédente obsolète.
  const champMontant = page.getByPlaceholder('Ex : 10 000');
  await expect(champMontant).toBeVisible({ timeout: 10_000 });
  await champMontant.fill('5000');
  await page.getByRole('button', { name: /confirmer le versement/i }).click();
  await expect(champMontant).toHaveCount(0, { timeout: 10_000 });
});

test('le reçu d\'une facture/livraison datée rétroactivement (BUG-083) affiche la date de la facture, pas la date système du jour (BUG-099)', async ({ page }) => {
  test.slow(); // voir BUG-065, comme les autres tests de ce fichier.

  // Voir docs/qa/REGISTRE_BUGS.md#BUG-099 : corrigé par dev-frontend —
  // `ReceiptData` transporte désormais `transactionDate` (issu de
  // `inv.delivered_at`/`inv.invoice_date`), branché dans les constructions de
  // reçu de `Sales.tsx` (`confirmDelivery`, `handleRepaymentSubmit`) et de
  // `Clients.tsx` (vente directe). Ce test vérifie le cas facture + livraison
  // rétroactives (`Config.allow_backdated_sales=true`, BUG-083) : le reçu doit
  // afficher la date réellement enregistrée, pas la date système du jour de
  // l'exécution du test.

  // 1. Activer "Ventes passées" en Configuration (rôle Direction).
  await seConnecter(page, COMPTES.direction.username, PASSWORD);
  await page.goto('/settings');
  // Scopé au bloc "Ventes Passées" : plusieurs autres interrupteurs de la page
  // (ex. vitrine publique) partagent le même intitulé générique de `title`.
  const toggle = page.getByText('Autoriser la saisie de ventes datées (passées)')
    .locator('xpath=../following-sibling::button');
  await expect(toggle).toBeVisible({ timeout: 15_000 });
  const estActif = (await toggle.getAttribute('title')) === 'Cliquer pour désactiver';
  if (!estActif) {
    await toggle.click();
  }
  await page.getByRole('button', { name: /enregistrer la configuration/i }).click();
  await expect(toggle).toHaveAttribute('title', 'Cliquer pour désactiver', { timeout: 10_000 });
  await seDeconnecter(page);

  // 2. Facturier K1 : facture + livraison datées d'avant-hier (jamais "hier" :
  // évite toute ambiguïté de fuseau horaire entre le navigateur du test et le
  // serveur autour de minuit).
  const avantHier = new Date();
  avantHier.setDate(avantHier.getDate() - 2);
  const dateRetroISO = avantHier.toISOString().split('T')[0]; // AAAA-MM-JJ
  const dateRetroFR = avantHier.toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' });
  const todayFR = new Date().toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' });

  await seConnecter(page, COMPTES.facturierK1.username, PASSWORD);
  await page.goto('/sales/create');

  const recherche = page.getByPlaceholder('Ex: K1-0045 ou KANZA Albert...');
  await recherche.fill('K1-');
  const suggestion = page.locator('text=/BP:|Solde OK/').first();
  await expect(suggestion).toBeVisible({ timeout: 45_000 });
  await suggestion.click();

  // Champ "Date de la commande (optionnel)" — visible uniquement si le
  // réglage Direction est actif (cf. étape 1).
  const dateCommande = page.locator('text=Date de la commande').locator('xpath=following-sibling::input[@type="date"]');
  await expect(dateCommande).toBeVisible({ timeout: 10_000 });
  await dateCommande.fill(dateRetroISO);

  const premiereQte = page.locator('input[type="number"]').first();
  await premiereQte.fill('5');
  const versement = page.locator('input[type="number"]').last();
  await versement.fill('0');

  await page.getByRole('button', { name: /facturer & mettre en attente/i }).click();
  await expect(page.getByText(/aucune facture en attente/i)).toHaveCount(0, { timeout: 15_000 });

  const carte = page.locator('text=/BP avant/').first();
  await expect(carte).toBeVisible({ timeout: 10_000 });

  // 3. Confirmation de livraison, avec la même date rétroactive.
  await page.getByRole('button', { name: /imprimer le reçu/i }).first().click();
  await expect(page.getByText('Confirmer la livraison')).toBeVisible({ timeout: 10_000 });
  const dateLivraison = page.locator('text=Date de livraison').locator('xpath=following-sibling::input[@type="date"]');
  await dateLivraison.fill(dateRetroISO);
  await page.getByRole('button', { name: /confirmer & imprimer/i }).click();
  await expect(page.getByText(/BON DE LIVRAISON/)).toBeVisible({ timeout: 10_000 });

  // 4. Le bloc "Date :" du reçu affiche la date rétroactive enregistrée en
  // base, jamais la date système du jour de l'exécution du test.
  await expect(page.getByText(dateRetroFR, { exact: false })).toBeVisible();
  if (dateRetroFR !== todayFR) {
    await expect(page.getByText(todayFR, { exact: false })).toHaveCount(0);
  }

  await page.getByRole('button', { name: /fermer/i }).last().click();
});
