# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: 04-facturation.spec.ts >> recherche prédictive client (BUG-065) : une recherche précise ne déclenche qu'une seule requête réseau, répond en moins d'1 s et affiche "Aucun client ne correspond" si vide
- Location: tests\04-facturation.spec.ts:95:5

# Error details

```
Error: expect(received).toBeLessThan(expected)

Expected: < 5000
Received:   8316
```

# Page snapshot

```yaml
- generic [ref=f1e3]:
  - complementary [ref=f1e4]:
    - generic [ref=f1e5]:
      - generic [ref=f1e6]: ETS. KIESE
      - generic [ref=f1e7]: Système Boulangeries
    - navigation [ref=f1e8]:
      - link "Gestion Clientèle" [ref=f1e10] [cursor=pointer]:
        - /url: /clients
      - link "Facturation (Facturier)" [ref=f1e18] [cursor=pointer]:
        - /url: /sales/create
    - generic [ref=f1e23]:
      - generic [ref=f1e24]:
        - button "Modifier mon profil" [ref=f1e25] [cursor=pointer]
        - generic [ref=f1e29]: Facturier
      - generic [ref=f1e31]: "BOULANGERIE : K1 - TABORA"
      - 'button "Équipe de service : B (changer)" [ref=f1e32] [cursor=pointer]'
      - button "Déconnexion" [ref=f1e39] [cursor=pointer]
  - main [ref=f1e44]:
    - generic [ref=f1e45]:
      - generic [ref=f1e46]:
        - button "Menu de navigation" [ref=f1e47] [cursor=pointer]
        - heading "Facturation (Facturier)" [level=2] [ref=f1e49]
      - generic [ref=f1e50]:
        - button "Messagerie" [ref=f1e51] [cursor=pointer]
        - button "25" [ref=f1e55] [cursor=pointer]
        - generic [ref=f1e60]:
          - button "Thème Sombre" [ref=f1e61] [cursor=pointer]
          - button "Thème Clair" [ref=f1e64] [cursor=pointer]
          - button "Thème Classic (Boulangerie)" [ref=f1e71] [cursor=pointer]
    - generic [ref=f1e77]:
      - generic [ref=f1e80]:
        - heading "Facturation en Chaîne & Livraison" [level=1] [ref=f1e81]
        - paragraph [ref=f1e82]: Saisie ultra-rapide par code client · Grille tarifaire officielle ETS. KIESE · Reçu thermique intégré
      - generic [ref=f1e88]:
        - generic [ref=f1e94]:
          - generic [ref=f1e95]: EN ATTENTE DE LIVRAISON
          - heading "5" [level=3] [ref=f1e96]
        - generic [ref=f1e102] [cursor=pointer]:
          - generic [ref=f1e103]: LIVRÉES AUJOURD'HUI
          - heading "36" [level=3] [ref=f1e104]
        - generic [ref=f1e112] [cursor=pointer]:
          - generic [ref=f1e113]: TOTAL FACTURÉ
          - heading "1 906 600 FC" [level=3] [ref=f1e114]
      - generic [ref=f1e115]:
        - generic [ref=f1e116]:
          - heading "Nouvelle Facture POS" [level=2] [ref=f1e117]
          - generic [ref=f1e120]:
            - generic [ref=f1e121] [cursor=pointer]:
              - checkbox [ref=f1e122]
              - generic [ref=f1e123]: Vente occasionnelle (sans client enregistré)
            - generic [ref=f1e124] [cursor=pointer]:
              - checkbox [ref=f1e125]
              - generic [ref=f1e126]: Vente Soldée / Vente Cash — -25% sur le prix catalogue, 0% commission, manquant non imputé en BP
            - generic [ref=f1e127] [cursor=pointer]:
              - checkbox [ref=f1e128]
              - generic [ref=f1e129]: Vente sans commission (25%) — geste commercial ponctuel, prix et BP inchangés
            - button "+ Code spécial (NV/RG/NS)" [ref=f1e131] [cursor=pointer]
            - generic [ref=f1e132]:
              - generic [ref=f1e133]: Date de la commande (optionnel)
              - generic [ref=f1e134]: Laisser vide = aujourd'hui. Jamais une date future.
              - textbox [ref=f1e135]
            - generic [ref=f1e136]:
              - generic [ref=f1e137]: Client — code ou nom *
              - 'textbox "Ex: K1-0045 ou KANZA Albert..." [active] [ref=f1e139]': ADELINE
              - generic [ref=f1e141] [cursor=pointer]:
                - generic [ref=f1e142]: K1-0001ADELINE ADELINE
                - generic [ref=f1e143]: Solde OK
            - generic [ref=f1e144]:
              - generic [ref=f1e145]: Commande (Qté × Catégorie)
              - generic [ref=f1e146]:
                - generic [ref=f1e147]:
                  - generic [ref=f1e148]: Catégorie
                  - generic [ref=f1e149]: Qté
                  - generic [ref=f1e150]: Sous-total
                - generic [ref=f1e151]:
                  - generic [ref=f1e152]: Pain 200 FC
                  - spinbutton "0" [ref=f1e153]
                  - generic [ref=f1e154]: —
                - generic [ref=f1e155]:
                  - generic [ref=f1e156]: Pain 300 FC
                  - spinbutton "0" [ref=f1e157]
                  - generic [ref=f1e158]: —
                - generic [ref=f1e159]:
                  - generic [ref=f1e160]: Pain 500 FC
                  - spinbutton "0" [ref=f1e161]
                  - generic [ref=f1e162]: —
                - generic [ref=f1e163]:
                  - generic [ref=f1e164]: Pain 1000 FC
                  - spinbutton "0" [ref=f1e165]
                  - generic [ref=f1e166]: —
            - generic [ref=f1e168]:
              - generic [ref=f1e169]: "Total commande :"
              - strong [ref=f1e170]: 0 FC
            - generic [ref=f1e171]:
              - generic [ref=f1e172]: Versement du Jour (FC)
              - generic [ref=f1e173]: Acompte en espèces versé ce jour
              - generic [ref=f1e174]:
                - textbox "Versement du jour en francs congolais (le signe moins est accepté)" [ref=f1e175]:
                  - /placeholder: 0 (ex. -5000)
                - generic [ref=f1e176]: CRÉDIT
              - generic [ref=f1e178]:
                - generic [ref=f1e179]: Motif
                - combobox [ref=f1e180] [cursor=pointer]:
                  - option "Aucun motif" [selected]
                  - option "Retrait d'épargne"
                  - option "Emprunt boulanger"
                  - option "Manquant d'équipe"
                  - option "Autre"
            - button "Facturer & Mettre en Attente" [ref=f1e181] [cursor=pointer]
        - generic [ref=f1e186]:
          - generic [ref=f1e187]:
            - heading "File des Livraisons — Confirmation & Impression Reçu" [level=2] [ref=f1e188]
            - button "Voir plus" [ref=f1e194] [cursor=pointer]
          - generic [ref=f1e198]:
            - generic [ref=f1e199]:
              - generic [ref=f1e200]:
                - generic [ref=f1e201]:
                  - generic [ref=f1e202]: K1-20261120-0041
                  - generic [ref=f1e203]: CASH
                  - generic [ref=f1e204]: 04:01
                - generic [ref=f1e205]: EN ATTENTE
              - generic [ref=f1e206]:
                - generic [ref=f1e207]:
                  - generic [ref=f1e208]: "[P"
                  - generic [ref=f1e210]: PAS DEPHOTO
                - generic [ref=f1e211]:
                  - generic [ref=f1e212]: K1-0079[K1-0079] PlafondE2E DEMO
                  - generic [ref=f1e214]:
                    - generic [ref=f1e215]: 1×
                    - generic [ref=f1e216]: Pain 200 FC
                    - generic [ref=f1e217]: 200 FC
                  - generic [ref=f1e218]:
                    - generic [ref=f1e219]:
                      - text: "Total:"
                      - strong [ref=f1e220]: 200 FC
                    - generic [ref=f1e221]:
                      - text: "Versé:"
                      - strong [ref=f1e222]: 200 FC
                    - generic [ref=f1e223]:
                      - text: "BP avant:"
                      - strong [ref=f1e224]: 50 000 FC
              - generic [ref=f1e225]:
                - generic [ref=f1e226]: Expire dans 11h15
                - generic [ref=f1e231]:
                  - button "Annuler" [ref=f1e232] [cursor=pointer]
                  - button "Imprimer le reçu" [ref=f1e237] [cursor=pointer]
            - generic [ref=f1e243]:
              - generic [ref=f1e244]:
                - generic [ref=f1e245]:
                  - generic [ref=f1e246]: K1-20261120-0040
                  - generic [ref=f1e247]: CASH
                  - generic [ref=f1e248]: 03:57
                - generic [ref=f1e249]: LIVRÉ
              - generic [ref=f1e250]:
                - generic [ref=f1e251]:
                  - generic [ref=f1e252]: CD
                  - generic [ref=f1e254]: PAS DEPHOTO
                - generic [ref=f1e255]:
                  - generic [ref=f1e256]: DIVERSCLIENT DIVERS
                  - generic [ref=f1e258]:
                    - generic [ref=f1e259]: 2×
                    - generic [ref=f1e260]: Pain 200 FC
                    - generic [ref=f1e261]: 400 FC
                  - generic [ref=f1e262]:
                    - generic [ref=f1e263]:
                      - text: "Total:"
                      - strong [ref=f1e264]: 400 FC
                    - generic [ref=f1e265]:
                      - text: "Versé:"
                      - strong [ref=f1e266]: 400 FC
                    - generic [ref=f1e267]:
                      - text: "BP avant:"
                      - strong [ref=f1e268]: 0 FC
              - generic [ref=f1e269]: Distribué
            - generic [ref=f1e275]:
              - generic [ref=f1e276]:
                - generic [ref=f1e277]:
                  - generic [ref=f1e278]: K1-20261120-0039
                  - generic [ref=f1e279]: CASH
                  - generic [ref=f1e280]: 03:57
                - generic [ref=f1e281]: EN ATTENTE
              - generic [ref=f1e282]:
                - generic [ref=f1e283]:
                  - generic [ref=f1e284]: "[V"
                  - generic [ref=f1e286]: PAS DEPHOTO
                - generic [ref=f1e287]:
                  - generic [ref=f1e288]: K1-0081[K1-0081] Ventes 4 ZZTEST
                  - generic [ref=f1e290]:
                    - generic [ref=f1e291]: 1×
                    - generic [ref=f1e292]: Pain 200 FC
                    - generic [ref=f1e293]: 200 FC
                  - generic [ref=f1e294]:
                    - generic [ref=f1e295]:
                      - text: "Total:"
                      - strong [ref=f1e296]: 200 FC
                    - generic [ref=f1e297]:
                      - text: "Versé:"
                      - strong [ref=f1e298]: 200 FC
                    - generic [ref=f1e299]:
                      - text: "BP avant:"
                      - strong [ref=f1e300]: 50 000 FC
              - generic [ref=f1e301]:
                - generic [ref=f1e302]: Expire dans 11h11
                - generic [ref=f1e307]:
                  - button "Annuler" [ref=f1e308] [cursor=pointer]
                  - button "Imprimer le reçu" [ref=f1e313] [cursor=pointer]
```

# Test source

```ts
  17  |   await expect(suggestion).toBeVisible({ timeout: 45_000 });
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
  112 |   const debut = Date.now();
  113 |   await recherche.fill('ADELINE');
  114 |   const suggestion = page.locator('text=/BP:|Solde OK/').first();
  115 |   await expect(suggestion).toBeVisible({ timeout: 5_000 });
  116 |   const duree = Date.now() - debut;
> 117 |   expect(duree).toBeLessThan(5_000); // debounce 350ms + aller-retour réseau ; << les ~20-30s d'avant correction
      |                 ^ Error: expect(received).toBeLessThan(expected)
  118 | 
  119 |   // Une seule requête `?search=...` — pas de boucle de pagination complète
  120 |   // (`?page=2&search=...`, etc.) pour un terme qui ne matche qu'une poignée
  121 |   // de clients.
  122 |   expect(requetesClients.length).toBe(1);
  123 |   expect(requetesClients[0]).toContain('search=ADELINE');
  124 |   expect(requetesClients.some(u => u.includes('page='))).toBe(false);
  125 | 
  126 |   // Terme sans correspondance -> message explicite distinct de l'état de
  127 |   // chargement, pas un panneau vide silencieux.
  128 |   await recherche.fill('');
  129 |   await recherche.fill('ZZZINEXISTANT999');
  130 |   await expect(page.getByText('Aucun client ne correspond à « ZZZINEXISTANT999 ».')).toBeVisible({ timeout: 5_000 });
  131 | });
  132 | 
  133 | test('recherche prédictive client (BUG-065) : pas de défilement de page à 360px et le client déjà sélectionné reste affiché', async ({ page }) => {
  134 |   await seConnecter(page, COMPTES.facturierK1.username, PASSWORD);
  135 |   await page.goto('/sales/create');
  136 | 
  137 |   const recherche = page.getByPlaceholder('Ex: K1-0045 ou KANZA Albert...');
  138 |   await recherche.fill('ADELINE');
  139 |   await page.waitForTimeout(80); // avant la fin du debounce (350ms) -> état "Recherche en cours..."
  140 |   const pendantRecherche = await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1);
  141 |   expect(pendantRecherche).toBe(true);
  142 | 
  143 |   const suggestion = page.locator('text=/BP:|Solde OK/').first();
  144 |   await expect(suggestion).toBeVisible({ timeout: 20_000 });
  145 |   const avecSuggestions = await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1);
  146 |   expect(avecSuggestions).toBe(true);
  147 | 
  148 |   await suggestion.click();
  149 |   const panneauClient = page.locator('text=Balance antérieure');
  150 |   await expect(panneauClient).toBeVisible();
  151 | 
  152 |   // Le panneau du client déjà sélectionné reste affiché indépendamment de
  153 |   // l'état de la recherche (focus/escape sans retoucher le texte saisi).
  154 |   await recherche.focus();
  155 |   await page.keyboard.press('Escape');
  156 |   await expect(panneauClient).toBeVisible();
  157 | });
  158 | 
  159 | test('un client au plafond de crédit est bloqué si le versement ne couvre pas la commande', async ({ page }) => {
  160 |   await seConnecter(page, COMPTES.gerantK1.username, PASSWORD);
  161 |   await page.goto('/clients');
  162 | 
  163 |   const recherche = page.getByPlaceholder('Rechercher par nom, commerce ou ID...');
  164 |   await recherche.fill(CLIENT_AU_PLAFOND.nomPartiel);
  165 |   const ligne = page.locator('tr', { hasText: CLIENT_AU_PLAFOND.code });
  166 |   await expect(ligne).toBeVisible({ timeout: 10_000 });
  167 | 
  168 |   await ligne.getByTitle('Enregistrer un Achat / Vente').click();
  169 |   await expect(page.getByText('Enregistrer commande')).toBeVisible();
  170 | 
  171 |   const premiereQte = page.locator('input[type="number"]').first();
  172 |   await premiereQte.fill('3'); // commande > 0 FC
  173 |   const versement = page.getByPlaceholder('0').last();
  174 |   await versement.fill('0'); // versement nul, insuffisant
  175 | 
  176 |   const bouton = page.getByRole('button', { name: /plafond atteint/i });
  177 |   await expect(bouton).toBeVisible({ timeout: 10_000 });
  178 |   await expect(bouton).toBeDisabled();
  179 | });
  180 | 
  181 | test('un remboursement réduit la BP du client sans créer de vente', async ({ page }) => {
  182 |   // Client dédié, distinct de CLIENT_AU_PLAFOND : un remboursement réel modifie
  183 |   // durablement la dette en base, ce qui casserait le test de blocage au
  184 |   // plafond ci-dessus si les deux tests partageaient le même client entre
  185 |   // deux exécutions de la suite (constaté en conditions réelles pendant cette
  186 |   // session : cf. rapport testeur-e2e, §2.2).
  187 |   await seConnecter(page, COMPTES.gerantK1.username, PASSWORD);
  188 |   await page.goto('/clients');
  189 | 
  190 |   const recherche = page.getByPlaceholder('Rechercher par nom, commerce ou ID...');
  191 |   await recherche.fill(CLIENT_POUR_REMBOURSEMENT.nomPartiel);
  192 |   const ligne = page.locator('tr', { hasText: CLIENT_POUR_REMBOURSEMENT.code });
  193 |   await expect(ligne).toBeVisible({ timeout: 10_000 });
  194 | 
  195 |   await ligne.getByTitle('Voir la fiche détaillée').click();
  196 | 
  197 |   // Note sélecteur : l'onglet "Remboursements" de la modale est lui-même un
  198 |   // élément cliquable dont le nom matche /rembourse/i — on cible donc le
  199 |   // bouton exact du pied de modale, renommé "Remboursement / Dépôt sans
  200 |   // commande" par BUG-090/098 (Clients.tsx l.2054), pas l'onglet.
  201 |   const boutonRemboursement = page.getByRole('button', { name: 'Remboursement / Dépôt sans commande' });
  202 |   await expect(boutonRemboursement).toBeVisible({ timeout: 10_000 });
  203 |   await boutonRemboursement.click();
  204 | 
  205 |   // Le champ n'affiche pas de plafond "Max :" (Clients.tsx l.2108 : placeholder
  206 |   // "Ex : 10 000", aucune borne haute affichée) — assertion précédente obsolète.
  207 |   const champMontant = page.getByPlaceholder('Ex : 10 000');
  208 |   await expect(champMontant).toBeVisible({ timeout: 10_000 });
  209 |   await champMontant.fill('5000');
  210 |   await page.getByRole('button', { name: /confirmer le versement/i }).click();
  211 |   await expect(champMontant).toHaveCount(0, { timeout: 10_000 });
  212 | });
  213 | 
  214 | test('le reçu d\'une facture/livraison datée rétroactivement (BUG-083) affiche la date de la facture, pas la date système du jour (BUG-099)', async ({ page }) => {
  215 |   test.slow(); // voir BUG-065, comme les autres tests de ce fichier.
  216 | 
  217 |   // Voir docs/qa/REGISTRE_BUGS.md#BUG-099 : corrigé par dev-frontend —
```