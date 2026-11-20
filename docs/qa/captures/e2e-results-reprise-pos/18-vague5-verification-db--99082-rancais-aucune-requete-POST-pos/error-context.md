# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: 18-vague5-verification-db.spec.ts >> BUG-276 : billetage hors borne -> message francais, aucune requete POST
- Location: tests\18-vague5-verification-db.spec.ts:73:5

# Error details

```
TimeoutError: locator.click: Timeout 30000ms exceeded.
Call log:
  - waiting for locator('form[novalidate]').filter({ hasText: /Valeur Faciale/ }).locator('button[type="submit"]').first()

```

# Page snapshot

```yaml
- generic [ref=f1e3]:
  - complementary [ref=f1e4]:
    - generic [ref=f1e5]:
      - generic [ref=f1e6]: ETS. KIESE
      - generic [ref=f1e7]: Système Boulangeries
    - navigation [ref=f1e8]:
      - link "Tableau de Bord" [ref=f1e10] [cursor=pointer]:
        - /url: /dashboard
      - link "Gestion Clientèle" [ref=f1e16] [cursor=pointer]:
        - /url: /clients
      - link "Facturation (Facturier)" [ref=f1e24] [cursor=pointer]:
        - /url: /sales/create
      - link "Production & Stocks" [ref=f1e30] [cursor=pointer]:
        - /url: /production
      - link "Clôture & Caisse" [ref=f1e37] [cursor=pointer]:
        - /url: /treasury
      - link "Clôture Journalière" [ref=f1e42] [cursor=pointer]:
        - /url: /cloture-journaliere
    - generic [ref=f1e46]:
      - generic [ref=f1e47]:
        - button "Modifier mon profil" [ref=f1e48] [cursor=pointer]
        - generic [ref=f1e52]: Gérant de Boulangerie
      - generic [ref=f1e54]: "BOULANGERIE : K4 - LOMA"
      - button "Déconnexion" [ref=f1e55] [cursor=pointer]
  - main [ref=f1e60]:
    - generic [ref=f1e61]:
      - generic [ref=f1e62]:
        - button "Menu de navigation" [ref=f1e63] [cursor=pointer]
        - heading "Clôture & Caisse" [level=2] [ref=f1e65]
      - generic [ref=f1e66]:
        - button "Messagerie" [ref=f1e67] [cursor=pointer]
        - button "25" [ref=f1e71] [cursor=pointer]
        - generic [ref=f1e76]:
          - button "Thème Sombre" [ref=f1e77] [cursor=pointer]
          - button "Thème Clair" [ref=f1e80] [cursor=pointer]
          - button "Thème Classic (Boulangerie)" [ref=f1e87] [cursor=pointer]
    - generic [ref=f1e93]:
      - generic [ref=f1e95]:
        - generic [ref=f1e96]:
          - heading "Clôture & Caisse — 3 Niveaux" [level=1] [ref=f1e97]
          - paragraph [ref=f1e98]: §5.1 Rapports journaliers · §5.2 Versement · §5.3 Livre de Caisse Direction
        - button "Actualiser" [ref=f1e100] [cursor=pointer]
      - generic [ref=f1e109]:
        - generic [ref=f1e114]:
          - generic [ref=f1e115]: TOTAL CASH DU JOUR
          - generic [ref=f1e116]: 15 000 FC
        - generic [ref=f1e122]:
          - generic [ref=f1e123]: TOTAL CRÉDIT DU JOUR
          - generic [ref=f1e124]: 66 500 FC
        - generic [ref=f1e130]:
          - generic [ref=f1e131]: SOLDE COMPTABLE CAISSE
          - generic [ref=f1e132]: 13 000 FC
        - generic [ref=f1e137]:
          - generic [ref=f1e138]: ÉCART BILLETAGE
          - generic [ref=f1e139]: +500 FC
      - generic [ref=f1e140]:
        - generic [ref=f1e141]:
          - heading "§5.1.1 — Niveau 1 · Rapports Journaliers des Facturiers" [level=2] [ref=f1e142]
          - generic [ref=f1e146]:
            - generic [ref=f1e147]: "Aujourd'hui : 2026-11-20"
            - textbox "Date du rapport (optionnel — vide = aujourd'hui, jamais une date future)" [ref=f1e148]
            - button "Imprimer" [ref=f1e149] [cursor=pointer]
            - button "Générer Rapport du Jour" [ref=f1e154] [cursor=pointer]
        - generic [ref=f1e159]:
          - generic [ref=f1e160]:
            - generic [ref=f1e161]: Rapport Journalier · Clôture du Jour
            - generic [ref=f1e162]: Tous les rapports validés
          - generic [ref=f1e166]:
            - generic [ref=f1e167]: Facturier — Montant Attendu (Sacs)
            - generic [ref=f1e168]:
              - generic [ref=f1e169]: 1 sac
              - generic [ref=f1e170]: ×
              - generic [ref=f1e171]: 210 000 FC
              - generic [ref=f1e172]: =
              - generic [ref=f1e173]: 210 000 FC
          - generic [ref=f1e174]:
            - generic [ref=f1e175]: Ventes du Jour — Résultat
            - generic [ref=f1e176]:
              - generic [ref=f1e178]:
                - generic [ref=f1e179]: "163"
                - generic [ref=f1e180]: ×
                - generic [ref=f1e181]: 500 FC
                - generic [ref=f1e182]: =
                - generic [ref=f1e183]: 81 500 FC
              - generic [ref=f1e184]:
                - generic [ref=f1e185]: Total Ventes
                - generic [ref=f1e186]: 81 500 FC
          - generic [ref=f1e187]:
            - generic [ref=f1e188]:
              - generic [ref=f1e189]: Résultat
              - generic [ref=f1e190]:
                - generic [ref=f1e191]: 210 000 FC
                - text: =
                - generic [ref=f1e192]: 81 500 FC
            - generic [ref=f1e193]:
              - generic [ref=f1e194]: Écart Significatif
              - generic [ref=f1e195]: "-128 500 FC"
        - table [ref=f1e197]:
          - rowgroup [ref=f1e198]:
            - row [ref=f1e199]:
              - columnheader "Boulangerie" [ref=f1e200]
              - columnheader "Équipe" [ref=f1e201]
              - columnheader "Cash FC" [ref=f1e202]
              - columnheader "Crédit FC" [ref=f1e203]
              - columnheader "Théorique Caisse" [ref=f1e204]
              - columnheader "Statut" [ref=f1e205]
              - columnheader "Action" [ref=f1e206]
          - rowgroup [ref=f1e207]:
            - row [ref=f1e208]:
              - cell "K4 - LOMA" [ref=f1e209]
              - cell "Équipe B" [ref=f1e210]
              - cell "5 000" [ref=f1e212]
              - cell "16 000" [ref=f1e213]
              - cell "5 000" [ref=f1e214]
              - cell "VALIDÉ" [ref=f1e215]
              - cell [ref=f1e217]
            - row [ref=f1e218]:
              - 'cell "Sacs consommés : 0 Pains par catégorie — produits / vendus : Pain 500 FC : 0 / 42 Écart valeur sacs / ventes : +21 000 FC (excédent)" [ref=f1e219]':
                - generic [ref=f1e220]:
                  - generic [ref=f1e221]:
                    - strong [ref=f1e222]: "Sacs consommés :"
                    - text: "0"
                  - generic [ref=f1e223]:
                    - strong [ref=f1e224]: "Pains par catégorie — produits / vendus :"
                    - generic [ref=f1e225]: "Pain 500 FC : 0 / 42"
                  - generic [ref=f1e227]:
                    - strong [ref=f1e228]: "Écart valeur sacs / ventes :"
                    - generic [ref=f1e229]: +21 000 FC (excédent)
            - row [ref=f1e230]:
              - cell "K4 - LOMA" [ref=f1e231]
              - cell "Équipe A" [ref=f1e232]
              - cell "10 000" [ref=f1e234]
              - cell "50 500" [ref=f1e235]
              - cell "10 000" [ref=f1e236]
              - cell "VALIDÉ" [ref=f1e237]
              - cell [ref=f1e239]
            - row [ref=f1e240]:
              - 'cell "Sacs consommés : 0 Pains par catégorie — produits / vendus : Pain 500 FC : 0 / 121 Écart valeur sacs / ventes : +60 500 FC (excédent)" [ref=f1e241]':
                - generic [ref=f1e242]:
                  - generic [ref=f1e243]:
                    - strong [ref=f1e244]: "Sacs consommés :"
                    - text: "0"
                  - generic [ref=f1e245]:
                    - strong [ref=f1e246]: "Pains par catégorie — produits / vendus :"
                    - generic [ref=f1e247]: "Pain 500 FC : 0 / 121"
                  - generic [ref=f1e249]:
                    - strong [ref=f1e250]: "Écart valeur sacs / ventes :"
                    - generic [ref=f1e251]: +60 500 FC (excédent)
            - row [ref=f1e252]:
              - cell "TOTAUX DU JOUR" [ref=f1e253]
              - cell "15 000 FC" [ref=f1e254]
              - cell "66 500 FC" [ref=f1e255]
              - cell "15 000 FC" [ref=f1e256]
              - cell [ref=f1e257]
      - generic [ref=f1e258]:
        - generic [ref=f1e259]:
          - heading "Versement" [level=2] [ref=f1e260]
          - generic [ref=f1e263]: K4 - LOMA
          - paragraph [ref=f1e267]: Saisir le nombre de coupures physiques — le système calcule et compare au solde théorique.
          - generic [ref=f1e268]:
            - generic [ref=f1e269]:
              - generic [ref=f1e270]: Valeur Faciale
              - generic [ref=f1e271]: Quantité
              - generic [ref=f1e272]: Sous-Total FC
            - generic [ref=f1e273]:
              - generic [ref=f1e274]: 20 000 FC
              - spinbutton "0" [active] [invalid] [ref=f1e275]: "100001"
              - generic [ref=f1e276]: 2 000 020 000
            - generic [ref=f1e277]:
              - generic [ref=f1e278]: 10 000 FC
              - spinbutton "0" [ref=f1e279]
              - generic [ref=f1e280]: —
            - generic [ref=f1e281]:
              - generic [ref=f1e282]: 5 000 FC
              - spinbutton "0" [ref=f1e283]
              - generic [ref=f1e284]: —
            - generic [ref=f1e285]:
              - generic [ref=f1e286]: 1 000 FC
              - spinbutton "0" [ref=f1e287]
              - generic [ref=f1e288]: —
            - generic [ref=f1e289]:
              - generic [ref=f1e290]: 500 FC
              - spinbutton "0" [ref=f1e291]
              - generic [ref=f1e292]: —
            - generic [ref=f1e293]:
              - generic [ref=f1e294]: 200 FC
              - spinbutton "0" [ref=f1e295]
              - generic [ref=f1e296]: —
            - generic [ref=f1e297]:
              - generic [ref=f1e298]: 100 FC
              - spinbutton "0" [ref=f1e299]
              - generic [ref=f1e300]: —
            - generic [ref=f1e301]:
              - generic [ref=f1e302]: 50 FC
              - spinbutton "0" [ref=f1e303]
              - generic [ref=f1e304]: —
            - generic [ref=f1e305]:
              - generic [ref=f1e306]:
                - generic [ref=f1e307]: "TOTAL GÉNÉRAL ESPÈCES :"
                - generic [ref=f1e308]: 13 500 FC
              - generic [ref=f1e309]:
                - generic [ref=f1e310]: Recette / Paiement :(§5.1.1 · 2 rapport(s))
                - generic [ref=f1e311]: 15 000 FC
              - generic [ref=f1e312]:
                - generic [ref=f1e313]: "— Dépenses Locales :"
                - generic [ref=f1e314]: −2 000 FC
              - generic [ref=f1e315]:
                - generic [ref=f1e316]: "Solde comptable caisse :"
                - generic [ref=f1e317]: 13 000 FC
              - generic [ref=f1e318]:
                - generic [ref=f1e319]: "ÉCART DE CAISSE :"
                - generic [ref=f1e320]: +500 FC (Excédent)
            - generic [ref=f1e321]:
              - generic [ref=f1e322]: Date de la clôture (optionnel)
              - generic [ref=f1e323]: Laisser vide = aujourd'hui. Jamais une date future.
              - textbox [ref=f1e324]
            - generic [ref=f1e325]:
              - generic [ref=f1e326]: Notes (optionnel)
              - textbox "Observations, écart justifié..." [ref=f1e327]
            - generic [ref=f1e328]: "Clôture créée — Physical total: 13 500 FC · Écart: 500 FC"
        - generic [ref=f1e332]:
          - generic [ref=f1e333]:
            - generic [ref=f1e334]:
              - heading "§5.1.2 — Dépenses Locales· K4 - LOMA" [level=2] [ref=f1e335]:
                - text: §5.1.2 — Dépenses Locales
                - generic [ref=f1e336]: · K4 - LOMA
              - generic [ref=f1e337]:
                - button "Historique" [ref=f1e338] [cursor=pointer]
                - button "Ajouter" [ref=f1e341] [cursor=pointer]
            - generic [ref=f1e344]:
              - generic [ref=f1e345]:
                - text: Transport test E2E
                - emphasis [ref=f1e346]: (Achat de Bois / Combustible)
              - strong [ref=f1e347]: "-2 000 FC"
            - generic [ref=f1e348]:
              - generic [ref=f1e349]: "Caisse Nette Boulangerie :"
              - generic [ref=f1e350]: 13 000 FC
          - generic [ref=f1e351]:
            - heading "Clôtures du Jour" [level=2] [ref=f1e352]
            - generic [ref=f1e354] [cursor=pointer]:
              - generic [ref=f1e355]:
                - generic [ref=f1e356]:
                  - strong [ref=f1e357]: K4 - LOMA
                  - text: 2026-11-20
                - generic [ref=f1e358]: CONFIRMÉE
              - generic [ref=f1e359]:
                - text: "Espèces physiques:"
                - strong [ref=f1e360]: 13 500 FC
                - text: "· Écart:"
                - strong [ref=f1e361]: 500 FC
              - generic [ref=f1e362]: Inscrit au grand livre
      - generic [ref=f1e367]:
        - generic [ref=f1e368]:
          - heading "§5.1.4 — Journal de Caisse par Boulangerie" [level=2] [ref=f1e369]
          - generic [ref=f1e373]:
            - generic [ref=f1e374]: Mois
            - combobox [ref=f1e375] [cursor=pointer]:
              - option "Janvier"
              - option "Février"
              - option "Mars"
              - option "Avril"
              - option "Mai"
              - option "Juin"
              - option "Juillet"
              - option "Août"
              - option "Septembre"
              - option "Octobre"
              - option "Novembre" [selected]
              - option "Décembre"
            - spinbutton [ref=f1e376]: "2026"
            - button "Actualiser" [ref=f1e377] [cursor=pointer]
        - generic [ref=f1e382]:
          - generic [ref=f1e383]:
            - text: "Report mois précédent :"
            - generic [ref=f1e384]: 0 FC
          - generic [ref=f1e385]:
            - text: "Total Entrées :"
            - generic [ref=f1e386]: 0 FC
          - generic [ref=f1e387]:
            - text: "Total Sorties :"
            - generic [ref=f1e388]: 0 FC
          - generic [ref=f1e389]:
            - text: "Solde Final :"
            - generic [ref=f1e390]: 0 FC
        - generic [ref=f1e391]:
          - generic [ref=f1e392]:
            - generic [ref=f1e393]: Date
            - textbox [ref=f1e394]: 2026-11-20
          - generic [ref=f1e395]:
            - generic [ref=f1e396]: Imputation
            - combobox [ref=f1e397] [cursor=pointer]:
              - option "Recettes du jour (CA)" [selected]
              - option "Paye boulangers"
              - option "Ration boulangers"
              - option "Livraison inter-site"
              - option "Eau"
              - option "Frais d'appro"
              - option "Dépôt rapport direction"
              - option "Transport"
              - option "Crédit personnel"
              - option "Prime personnel"
              - option "Essence / Mazout"
              - option "Achat matériel / fourniture"
              - option "Autre"
          - generic [ref=f1e398]:
            - generic [ref=f1e399]: Libellé
            - textbox "Description (optionnel)" [ref=f1e400]
          - generic [ref=f1e401]:
            - generic [ref=f1e402]: Entrée (FC)
            - spinbutton "0" [ref=f1e403]: "15000"
            - generic [ref=f1e404]: ✓ Rapproché à la Clôture (15 000 FC)
          - generic [ref=f1e406]:
            - generic [ref=f1e407]: Sortie (FC)
            - spinbutton "0" [ref=f1e408]
          - button "Enregistrer" [ref=f1e409] [cursor=pointer]
        - paragraph [ref=f1e411]: Aucune écriture pour ce mois.
      - generic [ref=f1e412]:
        - generic [ref=f1e413]:
          - heading "§5.1.5 — Épargne Journalière" [level=3] [ref=f1e414]
          - generic [ref=f1e415]:
            - button "◀" [ref=f1e416] [cursor=pointer]
            - generic [ref=f1e417]: novembre 2026
            - button "▶" [ref=f1e418] [cursor=pointer]
            - combobox [ref=f1e419]:
              - option "Tous les jours" [selected]
        - generic [ref=f1e420]:
          - generic [ref=f1e421]:
            - generic [ref=f1e422]: Total Sacs Farine
            - generic [ref=f1e423]: 0 sacs
          - generic [ref=f1e424]:
            - generic [ref=f1e425]: Total Revenu
            - generic [ref=f1e426]: 0 FC
          - generic [ref=f1e427]:
            - generic [ref=f1e428]: Total Épargne
            - generic [ref=f1e429]: 0 FC
        - generic [ref=f1e430]:
          - generic [ref=f1e431]:
            - generic [ref=f1e432]: Date
            - textbox [ref=f1e433]: 2026-11-20
          - generic [ref=f1e434]:
            - generic [ref=f1e435]: Sacs farine (PROD)
            - spinbutton "0" [ref=f1e436]
          - generic [ref=f1e437]:
            - generic [ref=f1e438]: Revenu du jour (FC) *
            - spinbutton "0" [ref=f1e439]
          - generic [ref=f1e440]:
            - generic [ref=f1e441]: Taux épargne
            - spinbutton [ref=f1e442]: "0.1580"
          - generic [ref=f1e443]:
            - generic [ref=f1e444]: Épargne calculée
            - generic [ref=f1e445]: —
          - button "+ Enregistrer" [ref=f1e446] [cursor=pointer]
        - generic [ref=f1e447]: Aucune épargne enregistrée pour ce mois.
```

# Test source

```ts
  1   | import { test, expect, Page, request as pwRequest } from '@playwright/test';
  2   | 
  3   | /**
  4   |  * Vague 5 (testeur-e2e, 2026-11-12) - rejeu UI sur db.sqlite3 des tickets CORRIGE.
  5   |  * Comptes zz_* uniquement (autorisation de l'utilisateur pour ce rejeu). Lecture seule :
  6   |  * aucune facture, aucun versement, aucune ecriture en base.
  7   |  * BUG-242 (garde de route /treasury), BUG-274 (file de livraisons, facture PENDING retro-datee),
  8   |  * BUG-276 (message francais de billetage), BUG-281 (libelle equipe de la periode),
  9   |  * BUG-282 (vitrine sans debordement, 320/360/768/1440).
  10  |  * Lancer : npx playwright test tests/18-vague5-verification-db.spec.ts --project=pos --project=bureau --output=<dossier perso>
  11  |  */
  12  | const CAP = '../docs/qa/captures';
  13  | const API = process.env.E2E_API_URL || 'http://localhost:8000';
  14  | 
  15  | async function seConnecter(page: Page, user: string) {
  16  |   await page.goto('/login', { waitUntil: 'domcontentloaded', timeout: 240_000 });
  17  |   await page.getByPlaceholder('Ex: pierre').fill(user, { timeout: 60_000 });
  18  |   await page.getByPlaceholder('••••••••').fill(user);
  19  |   await page.getByRole('button', { name: /se connecter/i }).click();
  20  |   await expect(page).toHaveURL(/\/dashboard/, { timeout: 120_000 });
  21  | }
  22  | async function reporterModale(page: Page) {
  23  |   const plusTard = page.getByRole('button', { name: /plus tard/i });
  24  |   await plusTard.waitFor({ state: 'visible', timeout: 8_000 }).then(() => plusTard.click()).catch(() => undefined);
  25  | }
  26  | async function ecart(page: Page) {
  27  |   return page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  28  | }
  29  | 
  30  | test('BUG-282 : vitrine sans debordement a 320/360/768/1440', async ({ page, request }, info) => {
  31  |   test.setTimeout(240_000);
  32  |   const cfg = await request.get(`${API}/api/core/config/`, { timeout: 120_000 });
  33  |   const onLine = (await cfg.json()).on_line as boolean;
  34  |   test.skip(!onLine, 'on_line = False : la racine redirige vers /login (pas de vitrine)');
  35  |   await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 150_000 });
  36  |   await expect(page.locator('body')).toContainText(/KIESE/i, { timeout: 120_000 });
  37  |   for (const w of [320, 360, 768, 1440]) {
  38  |     await page.setViewportSize({ width: w, height: 800 });
  39  |     await page.waitForTimeout(300);
  40  |     const e = await ecart(page);
  41  |     await page.screenshot({ path: `${CAP}/vague5-vitrine-${w}.png` });
  42  |     info.annotations.push({ type: `ecart-${w}`, description: String(e) });
  43  |     expect(e, `ecart a ${w}px`).toBe(0);
  44  |   }
  45  | });
  46  | 
  47  | test('BUG-242 : /treasury refuse au facturier et au livreur, ouvert au gerant', async ({ page }) => {
  48  |   test.setTimeout(600_000);
  49  |   for (const u of ['zz_treso_facturier_a', 'zz_treso_livreur']) {
  50  |     await page.context().clearCookies();
  51  |     await page.goto('/login', { waitUntil: 'domcontentloaded', timeout: 240_000 });
  52  |     await page.evaluate(() => localStorage.clear());
  53  |     const appels: string[] = [];
  54  |     page.on('request', r => { if (r.url().includes('/api/treasury/')) appels.push(r.url()); });
  55  |     await seConnecter(page, u);
  56  |     await reporterModale(page);
  57  |     await page.goto('/treasury', { waitUntil: 'domcontentloaded', timeout: 240_000 });
  58  |     await expect(page.getByText('Accès refusé')).toBeVisible({ timeout: 60_000 });
  59  |     expect(appels, `appels /api/treasury/ pour ${u}`).toHaveLength(0);
  60  |     expect(await ecart(page)).toBeLessThanOrEqual(1);
  61  |     page.removeAllListeners('request');
  62  |   }
  63  |   await page.goto('/login');
  64  |   await page.evaluate(() => localStorage.clear());
  65  |   await seConnecter(page, 'zz_clients_gerant');
  66  |   await reporterModale(page);
  67  |   await page.goto('/treasury', { waitUntil: 'domcontentloaded', timeout: 240_000 });
  68  |   await expect(page.getByText('Accès refusé')).toHaveCount(0);
  69  |   await expect(page.getByText(/Saisir le nombre de coupures/)).toBeVisible({ timeout: 90_000 });
  70  |   expect(await ecart(page)).toBeLessThanOrEqual(1);
  71  | });
  72  | 
  73  | test('BUG-276 : billetage hors borne -> message francais, aucune requete POST', async ({ page }) => {
  74  |   test.setTimeout(600_000);
  75  |   await seConnecter(page, 'zz_clients_gerant');
  76  |   await reporterModale(page);
  77  |   await page.goto('/treasury', { waitUntil: 'domcontentloaded', timeout: 240_000 });
  78  |   await expect(page.getByText(/Saisir le nombre de coupures/)).toBeVisible({ timeout: 90_000 });
  79  |   // la modale « Stock de depart » peut arriver tardivement : la reporter tant qu'elle est la
  80  |   const plusTard = page.getByRole('button', { name: /plus tard/i });
  81  |   await plusTard.waitFor({ state: 'visible', timeout: 25_000 }).then(() => plusTard.click()).catch(() => undefined);
  82  |   await expect(page.locator('.modal-backdrop')).toHaveCount(0, { timeout: 15_000 });
  83  |   const posts: string[] = [];
  84  |   page.on('request', r => { if (r.method() === 'POST' && r.url().includes('/api/treasury/closures')) posts.push(r.url()); });
  85  |   const form = page.locator('form[novalidate]').filter({ hasText: /Valeur Faciale/ });
  86  |   const champ = form.locator('input[type="number"]').first();
  87  |   const valider = form.locator('button[type="submit"]').first();
  88  |   for (const v of ['100001', '-3', '2.5']) {
  89  |     await champ.fill(v);
> 90  |     await valider.click();
      |                   ^ TimeoutError: locator.click: Timeout 30000ms exceeded.
  91  |     // espaces insecables fines (toLocaleString fr-FR) : \s les couvre
  92  |     await expect(form.getByText(/^Coupure 20\s000 FC : entier entre 0 et 100\s000 billets\.$/)).toBeVisible({ timeout: 10_000 });
  93  |   }
  94  |   expect(posts, 'aucune requete POST de cloture').toHaveLength(0);
  95  |   expect(await ecart(page)).toBeLessThanOrEqual(1);
  96  |   await page.screenshot({ path: `${CAP}/vague5-billetage-${test.info().project.name}.png` });
  97  | });
  98  | 
  99  | test('BUG-283 (UI de BUG-274) : la file de livraisons de l ecran affiche les PENDING retro-datees (K4, facturier)', async ({ page }) => {
  100 |   test.setTimeout(600_000);
  101 |   const appels: string[] = [];
  102 |   page.on('request', r => { if (r.url().includes('/api/sales/invoices/')) appels.push(r.url()); });
  103 |   // Donnee propre au test : une facture PENDING retro-datee (le livreur du parcours 19 vide la file de livraisons).
  104 |   const apiReq = await pwRequest.newContext();
  105 |   const lg = await apiReq.post(`${API}/api/core/auth/login/`, { data: { username: 'zz_clients_facturier', password: 'zz_clients_facturier' } });
  106 |   const HA = { Authorization: `Bearer ${(await lg.json()).access}` };
  107 |   const cl = await (await apiReq.get(`${API}/api/clients/clients/?search=K4-0964`, { headers: HA })).json();
  108 |   const retroDate = new Date(Date.now() - 6 * 86400_000).toLocaleDateString('sv-SE');
  109 |   const cr = await apiReq.post(`${API}/api/sales/invoices/`, { headers: HA, data: { client: cl.results[0].id, payment_type: 'CREDIT', payment_amount: '0', lines: [{ bread_price: 3, quantity: 1 }], invoice_date: retroDate } });
  110 |   expect(cr.status(), await cr.text()).toBe(201);
  111 |   await apiReq.dispose();
  112 |   await seConnecter(page, 'zz_clients_facturier');
  113 |   await reporterModale(page);
  114 |   await page.goto('/sales', { waitUntil: 'domcontentloaded', timeout: 240_000 });
  115 |   await expect(page.getByText(/File des Livraisons/)).toBeVisible({ timeout: 90_000 });
  116 |   await expect(page.getByText(/factures chargées/)).toHaveCount(0, { timeout: 120_000 });
  117 |   // 1) contrat backend : la liste API contient des PENDING datees hors du jour courant
  118 |   const api = await page.evaluate(async (base) => {
  119 |     const t = localStorage.getItem('kiese_access_token');
  120 |     const r = await fetch(`${base}/api/sales/invoices/pending_deliveries/`, { headers: { Authorization: `Bearer ${t}` } });
  121 |     const j = await r.json();
  122 |     const l = Array.isArray(j) ? j : j.results ?? [];
  123 |     return { status: r.status, items: l.map((i: { receipt_number?: string; invoice_date: string }) => ({ n: i.receipt_number ?? '', d: i.invoice_date })) };
  124 |   }, API);
  125 |   const aujourdhui = new Date().toLocaleDateString('en-CA');
  126 |   const retro = api.items.filter(i => i.d !== aujourdhui);
  127 |   test.info().annotations.push({ type: 'api', description: `HTTP ${api.status}, ${api.items.length} PENDING dont ${retro.length} hors jour courant` });
  128 |   expect(api.status).toBe(200);
  129 |   expect(retro.length, 'API : PENDING retro-datee listee').toBeGreaterThan(0);
  130 |   // 2) l'ecran doit exposer ces memes factures dans la file
  131 |   test.info().annotations.push({ type: 'ecran', description: `appels : ${appels.map(a => a.replace(/^.*\/api\//, '')).join(' | ')}` });
  132 |   const recu = retro[0].n;
  133 |   await reporterModale(page);
  134 |   const voirPlus = page.getByRole('button', { name: /voir plus/i });
  135 |   if (await voirPlus.isVisible().catch(() => false)) await voirPlus.click();
  136 |   if (recu) await expect(page.locator('body'), `l'ecran liste ${recu}`).toContainText(recu, { timeout: 10_000 });
  137 |   await page.screenshot({ path: `${CAP}/vague5-livraisons-${test.info().project.name}.png` });
  138 | });
  139 | 
  140 | test('BUG-281 : libelle « Equipe de service de la periode » (necessite un gerant de boulangerie en rotation, K3)', async ({ page }) => {
  141 |   test.setTimeout(600_000);
  142 |   await seConnecter(page, 'zz_prod_gerant_k3'); // K3 : rotation activee (K4 ne l'est pas dans cette base)
  143 |   const designer = page.getByRole('button', { name: /confirmer l.équipe/i });
  144 |   if (await designer.waitFor({ state: 'visible', timeout: 30_000 }).then(() => true).catch(() => false)) await designer.click();
  145 |   const titre = page.getByText(/Stock de départ de la relève/);
  146 |   const visible = await titre.waitFor({ state: 'visible', timeout: 30_000 }).then(() => true).catch(() => false);
  147 |   test.skip(!visible, 'La modale « Stock de depart de la releve » n\'apparait pas (deja confirmee) : non verifiable en UI');
  148 |   await expect(page.getByText(/Équipe de service de la période : [AB]/)).toBeVisible();
  149 |   await expect(page.getByText(/Équipe de service du jour/)).toHaveCount(0);
  150 |   await page.screenshot({ path: `${CAP}/vague5-stock-releve-${test.info().project.name}.png` });
  151 | });
  152 | 
```