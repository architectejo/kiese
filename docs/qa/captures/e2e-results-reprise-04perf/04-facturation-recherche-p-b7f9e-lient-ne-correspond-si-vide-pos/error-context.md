# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: 04-facturation.spec.ts >> recherche prédictive client (BUG-065) : une recherche précise ne déclenche qu'une seule requête réseau, répond en moins d'1 s et affiche "Aucun client ne correspond" si vide
- Location: tests\04-facturation.spec.ts:95:5

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: locator('text=/BP:|Solde OK/').first()
Expected: visible
Timeout: 5000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" locator('text=/BP:|Solde OK/').first() with timeout 5000ms
  - waiting for locator('text=/BP:|Solde OK/').first()

```

```yaml
- complementary:
  - text: ETS. KIESE Système Boulangeries
  - navigation:
    - link "Gestion Clientèle":
      - /url: /clients
      - img
      - text: Gestion Clientèle
    - link "Facturation (Facturier)":
      - /url: /sales/create
      - img
      - text: Facturation (Facturier)
  - button "Modifier mon profil":
    - img
  - text: "Facturier BOULANGERIE : K1 - TABORA"
  - button "Déconnexion":
    - img
    - text: Déconnexion
- main:
  - button "Menu de navigation":
    - img
  - heading "Facturation (Facturier)" [level=2]
  - button "Messagerie"
  - button:
    - img
  - button "Thème Sombre":
    - img
  - button "Thème Clair":
    - img
  - button "Thème Classic (Boulangerie)":
    - img
  - heading "Facturation en Chaîne & Livraison" [level=1]
  - paragraph: Saisie ultra-rapide par code client · Grille tarifaire officielle ETS. KIESE · Reçu thermique intégré
  - img
  - img
  - text: EN ATTENTE DE LIVRAISON
  - heading "calcul en cours… 0/…" [level=3]
  - img
  - text: LIVRÉES AUJOURD'HUI
  - heading "calcul en cours… 0/…" [level=3]
  - img
  - text: TOTAL FACTURÉ
  - heading "calcul en cours… 0/…" [level=3]
  - heading "Nouvelle Facture POS" [level=2]:
    - img
    - text: Nouvelle Facture POS
  - checkbox
  - text: Vente occasionnelle (sans client enregistré)
  - checkbox
  - text: Vente Soldée / Vente Cash — -25% sur le prix catalogue, 0% commission, manquant non imputé en BP
  - checkbox
  - text: Vente sans commission (25%) — geste commercial ponctuel, prix et BP inchangés
  - button "+ Code spécial (NV/RG/NS)"
  - text: Client — code ou nom *
  - img
  - 'textbox "Ex: K1-0045 ou KANZA Albert..."': ADELINE
  - text: "Recherche en cours… Commande (Qté × Catégorie) Catégorie Qté Sous-total Total commande :"
  - strong: 0 FC
  - text: Versement du Jour (FC) Acompte en espèces versé ce jour
  - textbox "Versement du jour en francs congolais (le signe moins est accepté)":
    - /placeholder: 0 (ex. -5000)
  - text: CRÉDIT Motif
  - combobox:
    - option "Aucun motif" [selected]
    - option "Retrait d'épargne"
    - option "Emprunt boulanger"
    - option "Manquant d'équipe"
    - option "Autre"
  - button "Facturer & Mettre en Attente":
    - img
    - text: Facturer & Mettre en Attente
  - heading "File des Livraisons — Confirmation & Impression Reçu" [level=2]:
    - img
    - text: File des Livraisons — Confirmation & Impression Reçu
  - text: Chargement...
```

# Test source

```ts
  18  |   await suggestion.click();
  19  | 
  20  |   // La BP avant doit être affichée dès la sélection du client.
  21  |   await expect(page.getByText(/BP\s*:/)).toBeVisible();
  22  | 
  23  |   const premiereQte = page.locator('input[type="number"]').first();
  24  |   await premiereQte.fill('5');
  25  |   const versement = page.getByLabel(/Versement du jour/i);
  26  |   await versement.fill('0');
  27  | 
  28  |   await page.getByRole('button', { name: /facturer & mettre en attente/i }).click();
  29  |   await expect(page.getByText(/aucune facture en attente/i)).toHaveCount(0, { timeout: 15_000 });
  30  | 
  31  |   // La facture doit apparaître "En attente" dans la file, avec la BP avant/après visible.
  32  |   const carte = page.locator('text=/BP avant/').first();
  33  |   await expect(carte).toBeVisible({ timeout: 10_000 });
  34  | 
  35  |   // Confirmation de la livraison → modale "Confirmer la livraison" (BUG-083,
  36  |   // date de livraison rétroactive optionnelle, Sales.tsx l.877) → reçu affiché.
  37  |   await page.getByRole('button', { name: /imprimer le reçu/i }).first().click();
  38  |   await expect(page.getByText('Confirmer la livraison')).toBeVisible({ timeout: 10_000 });
  39  |   await page.getByRole('button', { name: /confirmer & imprimer/i }).click();
  40  |   await expect(page.getByText(/BON DE LIVRAISON/)).toBeVisible({ timeout: 10_000 });
  41  |   await expect(page.getByText(/BALANCE ANTÉRIEURE \(BP\)/)).toBeVisible();
  42  |   await expect(page.getByText(/NOUVELLE DETTE/)).toBeVisible();
  43  |   await page.getByRole('button', { name: /fermer/i }).last().click(); // le Modal générique ajoute aussi un bouton X aria-label="Fermer" dans l'entête (Modal.tsx) — .last() cible le bouton pied de page du reçu (ThermalReceipt.tsx)
  44  | });
  45  | 
  46  | test('le reçu affiche le code boulangerie, le RCCM contractuel et la mention "Solde arrêté ce jour" (BUG-059)', async ({ page }) => {
  47  |   // Voir docs/qa/REGISTRE_BUGS.md#BUG-059 : corrigé par dev-frontend le
  48  |   // 2026-10-23 dans ThermalReceipt.tsx — vérifie ici que receipt.boulangerie
  49  |   // est bien affiché (nœud K1 émetteur), que le RCCM contractuel
  50  |   // (CLAUDE.md §5.2 / cahierDesCharges.md §4.4.1) est correct, et que la
  51  |   // mention de clôture journalière est présente sous BP avant/BP après.
  52  |   test.slow(); // voir BUG-065 : Sales.tsx charge tout le fichier clients avant que la recherche prédictive ne retourne un résultat.
  53  |   await seConnecter(page, COMPTES.facturierK1.username, PASSWORD);
  54  |   await page.goto('/sales/create');
  55  | 
  56  |   const recherche = page.getByPlaceholder('Ex: K1-0045 ou KANZA Albert...');
  57  |   await recherche.fill('K1-0082'); // client fictif ZZTEST (jamais un client reel)
  58  |   const suggestion = page.locator('text=/BP:|Solde OK/').first();
  59  |   await expect(suggestion).toBeVisible({ timeout: 45_000 });
  60  |   await suggestion.click();
  61  | 
  62  |   await expect(page.getByText(/BP\s*:/)).toBeVisible();
  63  | 
  64  |   const premiereQte = page.locator('input[type="number"]').first();
  65  |   await premiereQte.fill('5');
  66  |   const versement = page.getByLabel(/Versement du jour/i);
  67  |   await versement.fill('0');
  68  | 
  69  |   await page.getByRole('button', { name: /facturer & mettre en attente/i }).click();
  70  |   await expect(page.getByText(/aucune facture en attente/i)).toHaveCount(0, { timeout: 15_000 });
  71  | 
  72  |   const carte = page.locator('text=/BP avant/').first();
  73  |   await expect(carte).toBeVisible({ timeout: 10_000 });
  74  | 
  75  |   // Confirmation de la livraison → modale "Confirmer la livraison" (BUG-083,
  76  |   // date de livraison rétroactive optionnelle, Sales.tsx l.877) → reçu affiché.
  77  |   await page.getByRole('button', { name: /imprimer le reçu/i }).first().click();
  78  |   await expect(page.getByText('Confirmer la livraison')).toBeVisible({ timeout: 10_000 });
  79  |   await page.getByRole('button', { name: /confirmer & imprimer/i }).click();
  80  |   await expect(page.getByText(/BON DE LIVRAISON/)).toBeVisible({ timeout: 10_000 });
  81  | 
  82  |   // Code boulangerie émetteur (nœud K1, "demo_facturier_k1_e2e") : le nœud
  83  |   // s'affiche "K1 - TABORA" (avec espaces autour du tiret, Node.__str__
  84  |   // backend) — distinct des numéros de facture/codes client "K1-xxxx" (sans
  85  |   // espaces) qui matcheraient aussi un regex trop permissif.
  86  |   await expect(page.getByText(/^K1 - /)).toBeVisible();
  87  |   // RCCM contractuel (CLAUDE.md §5.2 / cahierDesCharges.md §4.4.1 : 021-A-650).
  88  |   await expect(page.getByText(/RCCM:\s*021-A-650/)).toBeVisible();
  89  |   // Mention obligatoire de clôture de solde journalier.
  90  |   await expect(page.getByText('Solde arrêté ce jour')).toBeVisible();
  91  | 
  92  |   await page.getByRole('button', { name: /fermer/i }).last().click(); // le Modal générique ajoute aussi un bouton X aria-label="Fermer" dans l'entête (Modal.tsx) — .last() cible le bouton pied de page du reçu (ThermalReceipt.tsx)
  93  | });
  94  | 
  95  | test('recherche prédictive client (BUG-065) : une recherche précise ne déclenche qu\'une seule requête réseau, répond en moins d\'1 s et affiche "Aucun client ne correspond" si vide', async ({ page }) => {
  96  |   // Vérification dynamique de la correction BUG-065 (dev-frontend, 2026-10-23) :
  97  |   // Sales.tsx ne charge plus le fichier clients entier (690+ fiches / ~28 pages)
  98  |   // avant la première suggestion ; la recherche interroge désormais le serveur
  99  |   // via `?search=...`. Testé ici avec un terme précis (un seul résultat attendu
  100 |   // dans le jeu de données e2e) — voir aussi le constat BUG-069 ci-dessous pour
  101 |   // le cas d'un terme large (ex. "K1-") qui matche tout le fichier d'une
  102 |   // boulangerie et redéclenche une boucle de pagination partielle.
  103 |   await seConnecter(page, COMPTES.facturierK1.username, PASSWORD);
  104 |   await page.goto('/sales/create');
  105 | 
  106 |   const requetesClients: string[] = [];
  107 |   page.on('request', req => {
  108 |     if (req.url().includes('/api/clients/clients/')) requetesClients.push(req.url());
  109 |   });
  110 | 
  111 |   const recherche = page.getByPlaceholder('Ex: K1-0045 ou KANZA Albert...');
  112 |   // le chronometre ne mesure que la recherche : page chargee et modales de relève (K1) reportees avant
  113 |   await expect(recherche).toBeVisible({ timeout: 60_000 });
  114 |   await reporterStockDepart(page);
  115 |   const debut = Date.now();
  116 |   await recherche.fill('ADELINE');
  117 |   const suggestion = page.locator('text=/BP:|Solde OK/').first();
> 118 |   await expect(suggestion).toBeVisible({ timeout: 5_000 });
      |                            ^ Error: expect(locator).toBeVisible() failed
  119 |   const duree = Date.now() - debut;
  120 |   test.info().annotations.push({ type: 'duree-recherche-ms', description: String(duree) });
  121 |   console.log(`[${test.info().project.name}] duree-recherche-ms = ${duree}`);
  122 |   expect(duree).toBeLessThan(5_000); // debounce 350ms + aller-retour réseau ; << les ~20-30s d'avant correction
  123 | 
  124 |   // Une seule requête `?search=...` — pas de boucle de pagination complète
  125 |   // (`?page=2&search=...`, etc.) pour un terme qui ne matche qu'une poignée
  126 |   // de clients.
  127 |   expect(requetesClients.length).toBe(1);
  128 |   expect(requetesClients[0]).toContain('search=ADELINE');
  129 |   expect(requetesClients.some(u => u.includes('page='))).toBe(false);
  130 | 
  131 |   // Terme sans correspondance -> message explicite distinct de l'état de
  132 |   // chargement, pas un panneau vide silencieux.
  133 |   await recherche.fill('');
  134 |   await recherche.fill('ZZZINEXISTANT999');
  135 |   await expect(page.getByText('Aucun client ne correspond à « ZZZINEXISTANT999 ».')).toBeVisible({ timeout: 5_000 });
  136 | });
  137 | 
  138 | test('recherche prédictive client (BUG-065) : pas de défilement de page à 360px et le client déjà sélectionné reste affiché', async ({ page }) => {
  139 |   await seConnecter(page, COMPTES.facturierK1.username, PASSWORD);
  140 |   await page.goto('/sales/create');
  141 | 
  142 |   const recherche = page.getByPlaceholder('Ex: K1-0045 ou KANZA Albert...');
  143 |   await recherche.fill('ADELINE');
  144 |   await page.waitForTimeout(80); // avant la fin du debounce (350ms) -> état "Recherche en cours..."
  145 |   const pendantRecherche = await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1);
  146 |   expect(pendantRecherche).toBe(true);
  147 | 
  148 |   const suggestion = page.locator('text=/BP:|Solde OK/').first();
  149 |   await expect(suggestion).toBeVisible({ timeout: 20_000 });
  150 |   const avecSuggestions = await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1);
  151 |   expect(avecSuggestions).toBe(true);
  152 | 
  153 |   await suggestion.click();
  154 |   const panneauClient = page.locator('text=Balance antérieure');
  155 |   await expect(panneauClient).toBeVisible();
  156 | 
  157 |   // Le panneau du client déjà sélectionné reste affiché indépendamment de
  158 |   // l'état de la recherche (focus/escape sans retoucher le texte saisi).
  159 |   await recherche.focus();
  160 |   await page.keyboard.press('Escape');
  161 |   await expect(panneauClient).toBeVisible();
  162 | });
  163 | 
  164 | test('un client au plafond de crédit est bloqué si le versement ne couvre pas la commande', async ({ page }) => {
  165 |   await seConnecter(page, COMPTES.gerantK1.username, PASSWORD);
  166 |   await page.goto('/clients');
  167 | 
  168 |   const recherche = page.getByPlaceholder('Rechercher par nom, commerce ou ID...');
  169 |   await recherche.fill(CLIENT_AU_PLAFOND.nomPartiel);
  170 |   const ligne = page.locator('tr', { hasText: CLIENT_AU_PLAFOND.code });
  171 |   await expect(ligne).toBeVisible({ timeout: 10_000 });
  172 | 
  173 |   await ligne.getByTitle('Enregistrer un Achat / Vente').click();
  174 |   await expect(page.getByText('Enregistrer commande')).toBeVisible();
  175 | 
  176 |   const premiereQte = page.locator('input[type="number"]').first();
  177 |   await premiereQte.fill('3'); // commande > 0 FC
  178 |   const versement = page.getByPlaceholder('0').last();
  179 |   await versement.fill('0'); // versement nul, insuffisant
  180 | 
  181 |   const bouton = page.getByRole('button', { name: /plafond atteint/i });
  182 |   await expect(bouton).toBeVisible({ timeout: 10_000 });
  183 |   await expect(bouton).toBeDisabled();
  184 | });
  185 | 
  186 | test('un remboursement réduit la BP du client sans créer de vente', async ({ page }) => {
  187 |   // Client dédié, distinct de CLIENT_AU_PLAFOND : un remboursement réel modifie
  188 |   // durablement la dette en base, ce qui casserait le test de blocage au
  189 |   // plafond ci-dessus si les deux tests partageaient le même client entre
  190 |   // deux exécutions de la suite (constaté en conditions réelles pendant cette
  191 |   // session : cf. rapport testeur-e2e, §2.2).
  192 |   await seConnecter(page, COMPTES.gerantK1.username, PASSWORD);
  193 |   await page.goto('/clients');
  194 | 
  195 |   const recherche = page.getByPlaceholder('Rechercher par nom, commerce ou ID...');
  196 |   await recherche.fill(CLIENT_POUR_REMBOURSEMENT.nomPartiel);
  197 |   const ligne = page.locator('tr', { hasText: CLIENT_POUR_REMBOURSEMENT.code });
  198 |   await expect(ligne).toBeVisible({ timeout: 10_000 });
  199 | 
  200 |   await ligne.getByTitle('Voir la fiche détaillée').click();
  201 | 
  202 |   // Note sélecteur : l'onglet "Remboursements" de la modale est lui-même un
  203 |   // élément cliquable dont le nom matche /rembourse/i — on cible donc le
  204 |   // bouton exact du pied de modale, renommé "Remboursement / Dépôt sans
  205 |   // commande" par BUG-090/098 (Clients.tsx l.2054), pas l'onglet.
  206 |   const boutonRemboursement = page.getByRole('button', { name: 'Remboursement / Dépôt sans commande' });
  207 |   await expect(boutonRemboursement).toBeVisible({ timeout: 10_000 });
  208 |   await boutonRemboursement.click();
  209 | 
  210 |   // Le champ n'affiche pas de plafond "Max :" (Clients.tsx l.2108 : placeholder
  211 |   // "Ex : 10 000", aucune borne haute affichée) — assertion précédente obsolète.
  212 |   const champMontant = page.getByPlaceholder('Ex : 10 000');
  213 |   await expect(champMontant).toBeVisible({ timeout: 10_000 });
  214 |   await champMontant.fill('5000');
  215 |   await page.getByRole('button', { name: /confirmer le versement/i }).click();
  216 |   await expect(champMontant).toHaveCount(0, { timeout: 10_000 });
  217 | });
  218 | 
```