# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: 10-regression-remarque-2026-10-30.spec.ts >> Clôture de fournée automatisée (BUG-093/108) : l'action "Clôturer" déclenche le recoupement et verrouille la saisie
- Location: tests\10-regression-remarque-2026-10-30.spec.ts:152:5

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByTestId('batch-in-progress-panel').getByTestId('batch-objective')
Expected: visible
Timeout: 30000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" getByTestId('batch-in-progress-panel').getByTestId('batch-objective') with timeout 30000ms
  - waiting for getByTestId('batch-in-progress-panel').getByTestId('batch-objective')

```

```yaml
- complementary:
  - text: ETS. KIESE Système Boulangeries
  - navigation:
    - link "Tableau de Bord":
      - /url: /dashboard
      - img
      - text: Tableau de Bord
    - link "Gestion Clientèle":
      - /url: /clients
      - img
      - text: Gestion Clientèle
    - link "Facturation (Facturier)":
      - /url: /sales/create
      - img
      - text: Facturation (Facturier)
    - link "Production & Stocks":
      - /url: /production
      - img
      - text: Production & Stocks
    - link "Clôture & Caisse":
      - /url: /treasury
      - img
      - text: Clôture & Caisse
    - link "Clôture Journalière":
      - /url: /cloture-journaliere
      - img
      - text: Clôture Journalière
  - button "Modifier mon profil":
    - img
  - text: "Gérant de Boulangerie BOULANGERIE : K4 - LOMA"
  - button "Déconnexion":
    - img
    - text: Déconnexion
- main:
  - button "Menu de navigation":
    - img
  - heading "Production & Stocks" [level=2]
  - button "Messagerie"
  - button "25":
    - img
    - text: "25"
  - button "Thème Sombre":
    - img
  - button "Thème Clair":
    - img
  - button "Thème Classic (Boulangerie)":
    - img
  - heading "Production, Stocks & Transferts" [level=1]
  - paragraph: Déclaration fournée · Rendement théorique · Approvisionnements · Transferts inter-boulangeries · Réconciliation
  - img
  - button "Actualiser":
    - img
    - text: Actualiser
  - text: 🔥 FOURNÉES ENREGISTRÉES 1 💰 VALEUR FC PRODUITE 0 FC 🚚 TRANSFERTS EN ATTENTE 0 📦 PAINS NON VALORISÉS 0
  - button "Fournées":
    - img
    - text: Fournées
  - button "Intrants":
    - img
    - text: Intrants
    - img
  - button "Transferts":
    - img
    - text: Transferts
  - button "Réconciliation":
    - img
    - text: Réconciliation
  - heading "Déclaration de Fournée" [level=2]:
    - img
    - text: Déclaration de Fournée
  - button "Actualiser la fournée en cours":
    - img
    - text: Actualiser
  - paragraph: "Aucune fournée en cours. Indiquez seulement le nombre de sacs : le montant à atteindre est calculé(1 sac = 210 000 FC) et les pains par catégorie se remplissent à chaque livraison."
  - text: Équipe
  - combobox "Équipe":
    - option "Équipe A"
    - option "Équipe B" [selected]
  - text: Nombre de sacs de farine *
  - spinbutton "Nombre de sacs de farine *": "1"
  - text: "Montant à atteindre :"
  - strong: 210 000 FC
  - text: Consommables utilisés (facultatif)
  - spinbutton "Sel en grammes"
  - spinbutton "Levure en paquets"
  - spinbutton "Huile en litres"
  - button "Enregistrer la Fournée"
  - alert:
    - img
    - text: Session de production clôturée pour l'Équipe B le 2026-11-20 à la boulangerie K4 — déclaration impossible.
  - heading "Confirmer le reste d'hier d'une autre équipe" [level=3]
  - paragraph: La boîte automatique ne se réaffiche qu'une fois par jour. Utilisez ce bouton pour confirmer volontairement le stock de départ d'une équipe qui ne l'a pas encore été.
  - button "Confirmer le reste d'hier — Équipe A"
  - button "Confirmer le reste d'hier — Équipe B"
  - heading "Stock Pains du Jour— 20 novembre 2026" [level=3]
  - button "Choisir un jour":
    - img
    - text: Choisir un jour
  - text: "Pain 200 FC — 200 FCproduits: 0 · reçus: 1 · sortis: 0 · disposés: 0 1 dispo voir détail Pain 500 FC — 500 FCproduits: 400 · reçus: 0 · sortis: 743 · disposés: 0 -343 dispo voir détail"
  - heading "Historique des Fournées" [level=3]
  - text: K4 - LOMA2026-11-20 — Éq.B Clôturée 0 pains · 1.00 sacs · 0 FC 0% -210 000 FC
```

# Test source

```ts
  71  | 
  72  |   // Sélecteur précis : NE PAS utiliser `.first()`/`.last()` sur "Imprimer le
  73  |   // reçu" sans scope — la file peut contenir d'autres factures "En attente"
  74  |   // laissées par d'autres parcours de la suite (ex. 08-facturation-serie.spec.ts,
  75  |   // qui crée 10 factures "Mettre en attente" jamais livrées) ou par une
  76  |   // exécution précédente de CE MÊME test resté en attente (ex. un échec
  77  |   // avant la confirmation de livraison) — un filtre générique sur le badge
  78  |   // "SOLDÉE" peut alors matcher PLUSIEURS cartes (l'ancienne ET la nouvelle),
  79  |   // avec un ordre non garanti. On cible donc sans ambiguïté la carte portant
  80  |   // le numéro de reçu exact retourné par le serveur pour CETTE facture.
  81  |   const carteSoldee = page.locator('div')
  82  |     .filter({ hasText: numeroRecu })
  83  |     .filter({ has: page.getByRole('button', { name: /imprimer le reçu/i }) })
  84  |     .last();
  85  |   await carteSoldee.getByRole('button', { name: /imprimer le reçu/i }).click();
  86  |   await expect(page.getByText('Confirmer la livraison')).toBeVisible({ timeout: 10_000 });
  87  |   await page.getByRole('button', { name: /confirmer & imprimer/i }).click();
  88  |   await expect(page.getByText(/BON DE LIVRAISON/)).toBeVisible({ timeout: 10_000 });
  89  | 
  90  |   // BUG-111 : le total général du reçu (lu du serveur, `order_total`) doit
  91  |   // être EXACTEMENT celui déjà annoncé à l'écran avant soumission — pas le
  92  |   // prix catalogue plein. Scopé à la ligne "TOTAL (FC)" du reçu (plusieurs
  93  |   // autres éléments de l'écran — ex. le KPI "TOTAL FACTURÉ" — peuvent
  94  |   // afficher coïncidentellement le même montant).
  95  |   const ligneTotalRecu = page.locator('tr', { hasText: 'TOTAL (FC)' });
  96  |   await expect(ligneTotalRecu.getByText(totalAffiche.replace(/\s*FC$/, ''), { exact: false })).toBeVisible();
  97  | 
  98  |   await page.getByRole('button', { name: /fermer/i }).last().click();
  99  | });
  100 | 
  101 | test('Vente sans commission + Vente Soldée (BUG-052) : les deux cases sont combinables sans confusion visuelle, et la requête porte bien les deux indicateurs', async ({ page }) => {
  102 |   await seConnecter(page, COMPTES.gerantK1.username, PASSWORD);
  103 |   await page.goto('/clients');
  104 | 
  105 |   const recherche = page.getByPlaceholder('Rechercher par nom, commerce ou ID...');
  106 |   await recherche.fill('CrossNodeE2E');
  107 |   const ligne = page.locator('tr', { hasText: 'K1-0078' });
  108 |   await expect(ligne).toBeVisible({ timeout: 10_000 });
  109 |   await ligne.getByTitle('Enregistrer un Achat / Vente').click();
  110 |   await expect(page.getByText('Enregistrer commande')).toBeVisible();
  111 | 
  112 |   const caseSansCommission = page.getByRole('checkbox', { name: /Vente sans commission/i });
  113 |   const caseVenteSoldee = page.getByRole('checkbox', { name: /Vente Soldée \/ Vente Cash/i });
  114 | 
  115 |   await caseSansCommission.check();
  116 |   await caseVenteSoldee.check();
  117 | 
  118 |   // Les deux cases restent cochées simultanément — aucune exclusion mutuelle
  119 |   // résiduelle (régression possible de l'ancien comportement avant BUG-052).
  120 |   await expect(caseSansCommission).toBeChecked();
  121 |   await expect(caseVenteSoldee).toBeChecked();
  122 | 
  123 |   // Message explicite de combinaison, sans contradiction visuelle.
  124 |   await expect(page.getByText(/Facture à la fois SOLDÉE.*ET sans commission.*CM=0 dans tous les cas/)).toBeVisible();
  125 | 
  126 |   const premiereQte = page.locator('#sale-form input[type="number"]').first();
  127 |   await premiereQte.fill('2');
  128 | 
  129 |   const [requeteCreation] = await Promise.all([
  130 |     page.waitForRequest(req =>
  131 |       req.method() === 'POST' &&
  132 |       req.url().includes('/api/sales/invoices/') &&
  133 |       !req.url().includes('/deliver/'),
  134 |     ),
  135 |     page.getByRole('button', { name: /confirmer la transaction/i }).click(),
  136 |   ]);
  137 |   const requeteFacture = requeteCreation.postDataJSON() as {
  138 |     is_soldee?: boolean; commission_exempt?: boolean; commission_rate?: number;
  139 |   };
  140 |   await expect(page.getByText('Enregistrer commande')).toHaveCount(0, { timeout: 15_000 });
  141 | 
  142 |   expect(requeteFacture.is_soldee).toBe(true);
  143 |   expect(requeteFacture.commission_exempt).toBe(true);
  144 |   // BUG-230 : `commission_rate` n'est plus envoye (le serveur applique le taux ; exoneree -> CM=0 cote serveur).
  145 |   expect(requeteFacture.commission_rate).toBeUndefined();
  146 | });
  147 | 
  148 | // BUG-306 : déclaration par sacs seuls. Équipe B (les parcours 05 utilisent l'équipe A) sur une boulangerie
  149 | // hors rotation par largeur d'écran : pos -> K2, tablette -> K5, bureau -> B1.
  150 | const GERANT_B = ['zz_demo_gerant_k2', 'zz_prod_gerant_k4', 'zz_e301_gerant', 'zz_e301_gerant']; // pos -> K2, tablette -> K4, bureau -> B2
  151 | 
  152 | test('Clôture de fournée automatisée (BUG-093/108) : l\'action "Clôturer" déclenche le recoupement et verrouille la saisie', async ({ page, request }, info) => {
  153 |   const i = Math.max(0, ['pos', 'tablette', 'bureau', 'tv'].indexOf(info.project.name));
  154 |   // Une seule fournée « en cours » par boulangerie : on clôture par l'API celle laissée par le parcours 05 (zz_* uniquement).
  155 |   const API = process.env.E2E_API_URL || 'http://localhost:8000';
  156 |   const tk = (await (await request.post(`${API}/api/core/auth/login/`, { data: { username: GERANT_B[i], password: GERANT_B[i] } })).json()).access as string;
  157 |   const H = { Authorization: `Bearer ${tk}` };
  158 |   const ouvertes = await (await request.get(`${API}/api/production/sessions/?is_closed=false&page_size=50`, { headers: H })).json();
  159 |   for (const sess of (ouvertes.results ?? ouvertes) as Array<{ id: string; is_closed: boolean }>) {
  160 |     if (!sess.is_closed) await request.post(`${API}/api/production/sessions/${sess.id}/close/`, { headers: H, data: { remaining: [] } });
  161 |   }
  162 |   await seConnecter(page, GERANT_B[i], PASSWORD);
  163 |   await page.goto('/production', { waitUntil: 'domcontentloaded' });
  164 | 
  165 |   const panneau = page.getByTestId('batch-in-progress-panel');
  166 |   await expect(panneau.getByText('Déclaration de Fournée')).toBeVisible({ timeout: 30_000 });
  167 |   await panneau.getByLabel('Équipe', { exact: true }).selectOption('B');
  168 |   await panneau.getByLabel(/Nombre de sacs de farine/).fill('1');
  169 |   await panneau.getByRole('button', { name: /enregistrer la fournée/i }).click();
  170 |   // (« Fournée en cours » seul serait vrai aussi dans la phrase d'aide « Aucune fournée en cours... » : on attend l'objectif)
> 171 |   await expect(panneau.getByTestId('batch-objective')).toBeVisible({ timeout: 30_000 });
      |                                                        ^ Error: expect(locator).toBeVisible() failed
  172 | 
  173 |   // BUG-315 : « Historique des Fournées » n'est pas rafraîchi après la déclaration (visible seulement après
  174 |   // rechargement) : on recharge pour retrouver la fournée (voir test.fixme BUG-315 ci-dessous).
  175 |   await page.reload({ waitUntil: 'domcontentloaded' });
  176 |   // Rouvre la fournée (équipe B, aujourd'hui) pour la clôturer.
  177 |   await page.getByText(/Éq\.B/).first().click();
  178 |   const detail = page.getByRole('dialog', { name: 'Détail Fournée' });
  179 |   await expect(detail).toBeVisible({ timeout: 10_000 });
  180 |   await detail.getByRole('button', { name: 'Clôturer la fournée' }).click();
  181 |   const m = page.getByRole('dialog', { name: 'Clôturer la Fournée' });
  182 |   await expect(m).toBeVisible();
  183 |   await m.getByRole('button', { name: 'Confirmer la clôture' }).click();
  184 |   await expect(m).toBeHidden({ timeout: 20_000 });
  185 | 
  186 |   await expect(page.getByText(/Fournée clôturée/)).toBeVisible({ timeout: 15_000 });
  187 |   await expect(page.getByText('Recoupement automatique à la clôture')).toBeVisible();
  188 |   // Saisie verrouillée : plus de bouton "Clôturer".
  189 |   await expect(page.getByRole('button', { name: /clôturer la fournée/i })).toHaveCount(0);
  190 | });
  191 | 
  192 | test.fixme("BUG-315 : après déclaration d'une fournée, « Historique des Fournées » l'affiche sans rechargement de la page", async () => {
  193 |   // Constat testeur-e2e 2026-11-20 (bureau 1440, gérant B1/K5) : déclaration par sacs, panneau « Fournée en cours »
  194 |   // affiché, mais aucune ligne « Éq.B » dans l'historique après 8 s ; elle apparaît après rechargement.
  195 |   // Cause : `onChanged` de BatchInProgressPanel ne recharge que `loadData()`, pas `historySessions` (Production.tsx l.340).
  196 | });
  197 | 
  198 | test('Journal de Caisse (BUG-091/105) : un écart avec la Clôture déclenche un avertissement, jamais un blocage', async ({ page }) => {
  199 |   await seConnecter(page, COMPTES.gerantK1.username, PASSWORD);
  200 |   await page.goto('/treasury');
  201 | 
  202 |   const sectionJournal = page.locator('text=§5.1.4 — Journal de Caisse par Boulangerie').locator('xpath=../..');
  203 |   const dateJournal = sectionJournal.locator('input[type="date"]').first();
  204 |   await dateJournal.fill('2020-02-02');
  205 | 
  206 |   // Imputation CA déjà sélectionnée par défaut — attend le pré-remplissage
  207 |   // automatique depuis la Clôture fixe du 2020-02-02 (12 345 FC, fixture dédiée).
  208 |   await expect(sectionJournal.getByText(/Rapproché à la Clôture \(12.?345/)).toBeVisible({ timeout: 10_000 });
  209 | 
  210 |   // Écrase volontairement la valeur pré-remplie pour créer un écart déclaré.
  211 |   // Sélecteur précis : le champ "Entrée (FC)" n'est PAS le premier
  212 |   // input[type=number] de la section — le sélecteur "Année" (navigation
  213 |   // mois/année du journal, au-dessus du formulaire) en est un, avant lui
  214 |   // dans le DOM, et `.first()` le ciblerait par erreur.
  215 |   const champEntree = sectionJournal.locator('text=Entrée (FC)').locator('xpath=following-sibling::input[@type="number"]');
  216 |   await champEntree.fill('20000');
  217 |   await expect(sectionJournal.getByText(/Écart avec la Clôture : \+/)).toBeVisible();
  218 | 
  219 |   await sectionJournal.getByRole('button', { name: /enregistrer/i }).click();
  220 | 
  221 |   // Jamais de blocage : message d'avertissement explicite, pas d'erreur.
  222 |   await expect(sectionJournal.getByText(/Écriture enregistrée — écart de \+.*FC avec la Clôture/)).toBeVisible({ timeout: 10_000 });
  223 |   await expect(page.getByText(/^Erreur/)).toHaveCount(0);
  224 | });
  225 | 
```