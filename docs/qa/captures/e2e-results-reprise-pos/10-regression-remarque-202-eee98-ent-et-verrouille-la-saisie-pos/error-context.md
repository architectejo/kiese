# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: 10-regression-remarque-2026-10-30.spec.ts >> Clôture de fournée automatisée (BUG-093/108) : l'action "Clôturer" déclenche le recoupement et verrouille la saisie
- Location: tests\10-regression-remarque-2026-10-30.spec.ts:152:5

# Error details

```
TimeoutError: locator.click: Timeout 30000ms exceeded.
Call log:
  - waiting for getByText(/Éq\.B/).first()

```

# Page snapshot

```yaml
- generic [ref=f2e3]:
  - complementary [ref=f2e4]:
    - generic [ref=f2e5]:
      - generic [ref=f2e6]: ETS. KIESE
      - generic [ref=f2e7]: Système Boulangeries
    - navigation [ref=f2e8]:
      - link "Tableau de Bord" [ref=f2e10] [cursor=pointer]:
        - /url: /dashboard
      - link "Gestion Clientèle" [ref=f2e16] [cursor=pointer]:
        - /url: /clients
      - link "Facturation (Facturier)" [ref=f2e24] [cursor=pointer]:
        - /url: /sales/create
      - link "Production & Stocks" [ref=f2e30] [cursor=pointer]:
        - /url: /production
      - link "Clôture & Caisse" [ref=f2e37] [cursor=pointer]:
        - /url: /treasury
      - link "Clôture Journalière" [ref=f2e42] [cursor=pointer]:
        - /url: /cloture-journaliere
    - generic [ref=f2e46]:
      - generic [ref=f2e47]:
        - button "Modifier mon profil" [ref=f2e48] [cursor=pointer]
        - generic [ref=f2e52]: Gérant de Boulangerie
      - generic [ref=f2e54]: "BOULANGERIE : K2 - COQ"
      - button "Déconnexion" [ref=f2e55] [cursor=pointer]
  - main [ref=f2e60]:
    - generic [ref=f2e61]:
      - generic [ref=f2e62]:
        - button "Menu de navigation" [ref=f2e63] [cursor=pointer]
        - heading "Production & Stocks" [level=2] [ref=f2e65]
      - generic [ref=f2e66]:
        - button "Messagerie" [ref=f2e67] [cursor=pointer]
        - button "25" [ref=f2e71] [cursor=pointer]
        - generic [ref=f2e76]:
          - button "Thème Sombre" [ref=f2e77] [cursor=pointer]
          - button "Thème Clair" [ref=f2e80] [cursor=pointer]
          - button "Thème Classic (Boulangerie)" [ref=f2e87] [cursor=pointer]
    - generic [ref=f2e93]:
      - generic [ref=f2e95]:
        - generic [ref=f2e96]:
          - heading "Production, Stocks & Transferts" [level=1] [ref=f2e97]
          - paragraph [ref=f2e98]: Déclaration fournée · Rendement théorique · Approvisionnements · Transferts inter-boulangeries · Réconciliation
        - button "Actualiser" [ref=f2e102] [cursor=pointer]
      - generic [ref=f2e108]:
        - generic [ref=f2e109]:
          - generic [ref=f2e110]: 🔥
          - generic [ref=f2e111]:
            - generic [ref=f2e112]: FOURNÉES ENREGISTRÉES
            - generic [ref=f2e113]: "17"
        - generic [ref=f2e114]:
          - generic [ref=f2e115]: 💰
          - generic [ref=f2e116]:
            - generic [ref=f2e117]: VALEUR FC PRODUITE
            - generic [ref=f2e118]: 0 FC
        - generic [ref=f2e119]:
          - generic [ref=f2e120]: 🚚
          - generic [ref=f2e121]:
            - generic [ref=f2e122]: TRANSFERTS EN ATTENTE
            - generic [ref=f2e123]: "0"
        - generic [ref=f2e124]:
          - generic [ref=f2e125]: 📦
          - generic [ref=f2e126]:
            - generic [ref=f2e127]: PAINS NON VALORISÉS
            - generic [ref=f2e128]: "23"
      - generic [ref=f2e129]:
        - button "Fournées" [ref=f2e130] [cursor=pointer]
        - button "Intrants" [ref=f2e137] [cursor=pointer]
        - button "Transferts" [ref=f2e145] [cursor=pointer]
        - button "Réconciliation" [ref=f2e152] [cursor=pointer]
      - generic [ref=f2e157]:
        - generic [ref=f2e158]:
          - generic [ref=f2e159]:
            - heading "Déclaration de Fournée" [level=2] [ref=f2e160]
            - button "Actualiser la fournée en cours" [ref=f2e166] [cursor=pointer]: Actualiser
          - generic [ref=f2e171]:
            - paragraph [ref=f2e172]: "Aucune fournée en cours. Indiquez seulement le nombre de sacs : le montant à atteindre est calculé(1 sac = 210 000 FC) et les pains par catégorie se remplissent à chaque livraison."
            - generic [ref=f2e173]:
              - generic [ref=f2e174]:
                - generic [ref=f2e175]: Équipe
                - combobox "Équipe" [ref=f2e176] [cursor=pointer]:
                  - option "Équipe A" [selected]
                  - option "Équipe B"
              - generic [ref=f2e177]:
                - generic [ref=f2e178]: Nombre de sacs de farine *
                - spinbutton "Nombre de sacs de farine *" [ref=f2e179]
            - generic [ref=f2e180]:
              - generic [ref=f2e181]: Consommables utilisés (facultatif)
              - generic [ref=f2e182]:
                - spinbutton "Sel en grammes" [ref=f2e183]
                - spinbutton "Levure en paquets" [ref=f2e184]
                - spinbutton "Huile en litres" [ref=f2e185]
            - button "Enregistrer la Fournée" [ref=f2e186] [cursor=pointer]
        - generic [ref=f2e187]:
          - heading "Confirmer le reste d'hier d'une autre équipe" [level=3] [ref=f2e188]
          - paragraph [ref=f2e189]: La boîte automatique ne se réaffiche qu'une fois par jour. Utilisez ce bouton pour confirmer volontairement le stock de départ d'une équipe qui ne l'a pas encore été.
          - button "Confirmer le reste d'hier — Équipe B" [ref=f2e191] [cursor=pointer]
        - generic [ref=f2e192]:
          - generic [ref=f2e193]:
            - heading "Stock Pains du Jour— 20 novembre 2026" [level=3] [ref=f2e194]:
              - text: Stock Pains du Jour
              - generic [ref=f2e195]: — 20 novembre 2026
            - button "Choisir un jour" [ref=f2e196] [cursor=pointer]
          - generic [ref=f2e200]:
            - generic [ref=f2e201] [cursor=pointer]:
              - generic [ref=f2e202]:
                - text: Pain 200 FC — 200 FC
                - generic [ref=f2e203]: "produits: 20 · reçus: 0 · sortis: 0 · disposés: 0"
              - generic [ref=f2e204]:
                - generic [ref=f2e205]: 21 dispo
                - generic [ref=f2e206]: voir détail
            - generic [ref=f2e207] [cursor=pointer]:
              - generic [ref=f2e208]:
                - text: Pain 300 FC — 300 FC
                - generic [ref=f2e209]: "produits: 20 · reçus: 0 · sortis: 0 · disposés: 0"
              - generic [ref=f2e210]:
                - generic [ref=f2e211]: 20 dispo
                - generic [ref=f2e212]: voir détail
            - generic [ref=f2e213] [cursor=pointer]:
              - generic [ref=f2e214]:
                - text: Pain 500 FC — 500 FC
                - generic [ref=f2e215]: "produits: 3000 · reçus: 32 · sortis: 0 · disposés: 0"
              - generic [ref=f2e216]:
                - generic [ref=f2e217]: 3032 dispo
                - generic [ref=f2e218]: voir détail
            - generic [ref=f2e219] [cursor=pointer]:
              - generic [ref=f2e220]:
                - text: Pain 1000 FC — 1000 FC
                - generic [ref=f2e221]: "produits: 20 · reçus: 0 · sortis: 0 · disposés: 0"
              - generic [ref=f2e222]:
                - generic [ref=f2e223]: 20 dispo
                - generic [ref=f2e224]: voir détail
        - generic [ref=f2e225]:
          - heading "Historique des Fournées" [level=3] [ref=f2e226]
          - generic [ref=f2e228] [cursor=pointer]:
            - generic [ref=f2e229]:
              - text: K2 - COQ
              - generic [ref=f2e230]: 2026-11-20 — Éq.A
              - generic [ref=f2e231]: Clôturée
              - generic [ref=f2e232]: 113 pains · 2.00 sacs · 0 FC
            - generic [ref=f2e233]:
              - generic [ref=f2e234]: 0%
              - generic [ref=f2e235]: "-420 000 FC"
```

# Test source

```ts
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
  170 |   await expect(panneau.getByText('Fournée en cours')).toBeVisible({ timeout: 20_000 });
  171 | 
  172 |   // BUG-315 : « Historique des Fournées » n'est pas rafraîchi après la déclaration (visible seulement après
  173 |   // rechargement) : on recharge pour retrouver la fournée (voir test.fixme BUG-315 ci-dessous).
  174 |   await page.reload({ waitUntil: 'domcontentloaded' });
  175 |   // Rouvre la fournée (équipe B, aujourd'hui) pour la clôturer.
> 176 |   await page.getByText(/Éq\.B/).first().click();
      |                                         ^ TimeoutError: locator.click: Timeout 30000ms exceeded.
  177 |   const detail = page.getByRole('dialog', { name: 'Détail Fournée' });
  178 |   await expect(detail).toBeVisible({ timeout: 10_000 });
  179 |   await detail.getByRole('button', { name: 'Clôturer la fournée' }).click();
  180 |   const m = page.getByRole('dialog', { name: 'Clôturer la Fournée' });
  181 |   await expect(m).toBeVisible();
  182 |   await m.getByRole('button', { name: 'Confirmer la clôture' }).click();
  183 |   await expect(m).toBeHidden({ timeout: 20_000 });
  184 | 
  185 |   await expect(page.getByText(/Fournée clôturée/)).toBeVisible({ timeout: 15_000 });
  186 |   await expect(page.getByText('Recoupement automatique à la clôture')).toBeVisible();
  187 |   // Saisie verrouillée : plus de bouton "Clôturer".
  188 |   await expect(page.getByRole('button', { name: /clôturer la fournée/i })).toHaveCount(0);
  189 | });
  190 | 
  191 | test.fixme("BUG-315 : après déclaration d'une fournée, « Historique des Fournées » l'affiche sans rechargement de la page", async () => {
  192 |   // Constat testeur-e2e 2026-11-20 (bureau 1440, gérant B1/K5) : déclaration par sacs, panneau « Fournée en cours »
  193 |   // affiché, mais aucune ligne « Éq.B » dans l'historique après 8 s ; elle apparaît après rechargement.
  194 |   // Cause : `onChanged` de BatchInProgressPanel ne recharge que `loadData()`, pas `historySessions` (Production.tsx l.340).
  195 | });
  196 | 
  197 | test('Journal de Caisse (BUG-091/105) : un écart avec la Clôture déclenche un avertissement, jamais un blocage', async ({ page }) => {
  198 |   await seConnecter(page, COMPTES.gerantK1.username, PASSWORD);
  199 |   await page.goto('/treasury');
  200 | 
  201 |   const sectionJournal = page.locator('text=§5.1.4 — Journal de Caisse par Boulangerie').locator('xpath=../..');
  202 |   const dateJournal = sectionJournal.locator('input[type="date"]').first();
  203 |   await dateJournal.fill('2020-02-02');
  204 | 
  205 |   // Imputation CA déjà sélectionnée par défaut — attend le pré-remplissage
  206 |   // automatique depuis la Clôture fixe du 2020-02-02 (12 345 FC, fixture dédiée).
  207 |   await expect(sectionJournal.getByText(/Rapproché à la Clôture \(12.?345/)).toBeVisible({ timeout: 10_000 });
  208 | 
  209 |   // Écrase volontairement la valeur pré-remplie pour créer un écart déclaré.
  210 |   // Sélecteur précis : le champ "Entrée (FC)" n'est PAS le premier
  211 |   // input[type=number] de la section — le sélecteur "Année" (navigation
  212 |   // mois/année du journal, au-dessus du formulaire) en est un, avant lui
  213 |   // dans le DOM, et `.first()` le ciblerait par erreur.
  214 |   const champEntree = sectionJournal.locator('text=Entrée (FC)').locator('xpath=following-sibling::input[@type="number"]');
  215 |   await champEntree.fill('20000');
  216 |   await expect(sectionJournal.getByText(/Écart avec la Clôture : \+/)).toBeVisible();
  217 | 
  218 |   await sectionJournal.getByRole('button', { name: /enregistrer/i }).click();
  219 | 
  220 |   // Jamais de blocage : message d'avertissement explicite, pas d'erreur.
  221 |   await expect(sectionJournal.getByText(/Écriture enregistrée — écart de \+.*FC avec la Clôture/)).toBeVisible({ timeout: 10_000 });
  222 |   await expect(page.getByText(/^Erreur/)).toHaveCount(0);
  223 | });
  224 | 
```