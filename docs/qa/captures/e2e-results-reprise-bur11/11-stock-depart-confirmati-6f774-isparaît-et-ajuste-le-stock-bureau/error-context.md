# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: 11-stock-depart-confirmation.spec.ts >> la boîte modale réapparaît à chaque navigation tant qu'aucune équipe n'est confirmée, puis disparaît et ajuste le stock
- Location: tests\11-stock-depart-confirmation.spec.ts:23:5

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByText('19').first()
Expected: visible
Timeout: 10000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" getByText('19').first() with timeout 10000ms
  - waiting for getByText('19').first()

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
  - text: "Gérant de Boulangerie BOULANGERIE : K5 - MPIANGU"
  - button "Déconnexion":
    - img
    - text: Déconnexion
- main:
  - heading "Production & Stocks" [level=2]
  - button "Messagerie"
  - button "25":
    - img
    - text: "25"
  - button "Dark":
    - img
    - text: Dark
  - button "Light":
    - img
    - text: Light
  - button "Classic":
    - img
    - text: Classic
  - text: Nœud Central Cloud
  - heading "Production, Stocks & Transferts" [level=1]
  - paragraph: Déclaration fournée · Rendement théorique · Approvisionnements · Transferts inter-boulangeries · Réconciliation
  - img
  - button "Actualiser":
    - img
    - text: Actualiser
  - text: 🔥 FOURNÉES ENREGISTRÉES 2 💰 VALEUR FC PRODUITE 30 000 FC 🚚 TRANSFERTS EN ATTENTE 0 📦 PAINS NON VALORISÉS 0
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
  - heading "Fournée en cours" [level=2]:
    - img
    - text: Fournée en cours
  - button "Actualiser la fournée en cours":
    - img
    - text: Actualiser
  - text: Équipe A 2 sacs de farine Montant à atteindre 420 000 FC
  - progressbar "Avancement de la fournée"
  - text: 0 % 0 FC / 420 000 FC Pains par catégorie (mis à jour automatiquement à chaque livraison) Augmenter les sacs (nouveau total)
  - spinbutton "Augmenter les sacs (nouveau total)"
  - button "Mettre à jour les sacs"
  - heading "Confirmer le reste d'hier d'une autre équipe" [level=3]
  - paragraph: La boîte automatique ne se réaffiche qu'une fois par jour. Utilisez ce bouton pour confirmer volontairement le stock de départ d'une équipe qui ne l'a pas encore été.
  - button "Confirmer le reste d'hier — Équipe B"
  - heading "Stock Pains du Jour— 20 novembre 2026" [level=3]
  - button "Choisir un jour":
    - img
    - text: Choisir un jour
  - text: "Pain 200 FC — 200 FCproduits: 20 · reçus: 1 · sortis: 0 · disposés: 0 20 dispo voir détail Pain 300 FC — 300 FCproduits: 20 · reçus: 0 · sortis: 0 · disposés: 0 20 dispo voir détail Pain 500 FC — 500 FCproduits: 80 · reçus: 0 · sortis: 60 · disposés: 0 20 dispo voir détail Pain 1000 FC — 1000 FCproduits: 20 · reçus: 0 · sortis: 0 · disposés: 0 20 dispo voir détail"
  - heading "Historique des Fournées" [level=3]
  - text: K5 - MPIANGU2026-11-20 — Éq.A 80 pains · 2.00 sacs · 0 FC 0% -420 000 FC K5 - MPIANGU2026-11-20 — Éq.B 60 pains · 1.00 sacs · 30 000 FC 14% -180 000 FC
```

# Test source

```ts
  1   | import { test, expect } from '@playwright/test';
  2   | import { COMPTES, PASSWORD } from '../fixtures/comptes';
  3   | import { seConnecter } from '../fixtures/helpers';
  4   | 
  5   | /**
  6   |  * Parcours 11 — Boîte modale « Stock de départ du jour » (BUG-133/134/135/136,
  7   |  * docs/qa/REGISTRE_BUGS.md, CORRIGÉ au 2026-11-09, vérification testeur-production).
  8   |  *
  9   |  * Attention base partagée : ce parcours écrit une confirmation réelle pour
  10  |  * (node=K1, équipe choisie, date=aujourd'hui) et ajuste réellement
  11  |  * `BreadStock.qty_adjusted` de K1 (BUG-136, décision client explicite —
  12  |  * toujours synchroniser, y compris en no-op). Comme le reste de la suite
  13  |  * (`05-production.spec.ts` déclare déjà une fournée réelle pour K1), c'est
  14  |  * cohérent avec la convention déjà établie du dossier `e2e/` : écrire des
  15  |  * données fictives dans la base de dev partagée, jamais la détruire.
  16  |  *
  17  |  * Si l'équipe A et/ou B de K1 a déjà été confirmée aujourd'hui par une
  18  |  * exécution précédente de cette suite (ou par le gérant réel), la boîte
  19  |  * modale n'apparaît plus — ce n'est pas un échec du test, documenté dans les
  20  |  * `test.skip` conditionnels ci-dessous plutôt que de fausser un résultat.
  21  |  */
  22  | 
  23  | test("la boîte modale réapparaît à chaque navigation tant qu'aucune équipe n'est confirmée, puis disparaît et ajuste le stock", async ({ page }) => {
  24  |   // K1 est en rotation (modale « Stock de départ de la relève », autre libellé) : parcours « du jour » joué sur K5 (hors rotation).
  25  |   await seConnecter(page, 'zz_demo_gerant_k5', '', { reporterStockDepart: false });
  26  | 
  27  |   const modaleTitre = page.getByText('Stock de départ du jour');
  28  | 
  29  |   // 1) Doit apparaître dès le tableau de bord si aucune équipe n'est
  30  |   // confirmée aujourd'hui pour K1.
  31  |   const dejaConfirmeeAuDepart = await modaleTitre.waitFor({ state: 'visible', timeout: 25_000 }).then(() => true).catch(() => false);
  32  |   if (!dejaConfirmeeAuDepart) {
  33  |     test.skip(true, 'Les deux équipes K1 sont déjà confirmées aujourd\'hui (exécution précédente) — rien à vérifier ici, voir note du fichier.');
  34  |   }
  35  |   await expect(modaleTitre).toBeVisible({ timeout: 10_000 });
  36  | 
  37  |   // 2) Fermeture temporaire (« Plus tard »), navigation vers une autre page :
  38  |   // la modale doit réapparaître (BUG-134, demande client remarque.md l.396).
  39  |   await page.getByRole('button', { name: /plus tard/i }).click();
  40  |   await expect(modaleTitre).toBeHidden();
  41  |   await page.goto('/clients');
  42  |   await expect(modaleTitre).toBeVisible({ timeout: 10_000 });
  43  | 
  44  |   // 3) Deuxième navigation vers une page différente : toujours visible.
  45  |   await page.goto('/production');
  46  |   await expect(modaleTitre).toBeVisible({ timeout: 10_000 });
  47  | 
  48  |   // 4) Lire la première quantité proposée, la corriger, puis valider pour
  49  |   // l'équipe présélectionnée.
  50  |   const premierChamp = page.locator('.modal, [role="dialog"]').filter({ hasText: 'Stock de départ du jour' })
  51  |     .locator('input:not([type="checkbox"]):not([type="radio"])').first();
  52  |   await expect(premierChamp).toBeVisible();
  53  |   const valeurProposee = await premierChamp.inputValue();
  54  |   const valeurCorrigee = String(Math.max(0, parseInt(valeurProposee || '0', 10) - 1));
  55  |   await premierChamp.fill(valeurCorrigee);
  56  | 
  57  |   const boutonValider = page.getByRole('button', { name: /^valider pour l'équipe/i });
  58  |   await boutonValider.click();
  59  | 
  60  |   // 5) Soit l'autre équipe reste à confirmer (modale reste ouverte,
  61  |   // présélectionne l'équipe restante) soit tout est confirmé (modale se
  62  |   // ferme). Dans les deux cas, naviguer à nouveau ne doit PAS réafficher la
  63  |   // modale si tout est désormais confirmé.
  64  |   await page.waitForTimeout(4_000); // laisse le statut de confirmation se rafraichir (la modale se ferme seule si tout est confirme)
  65  |   const encoreOuverte = await modaleTitre.isVisible().catch(() => false);
  66  |   if (encoreOuverte) {
  67  |     const deuxiemeChamp = page.locator('.modal, [role="dialog"]').filter({ hasText: 'Stock de départ du jour' })
  68  |       .locator('input:not([type="checkbox"]):not([type="radio"])').first();
  69  |     await expect(deuxiemeChamp).toBeVisible();
  70  |     await page.getByRole('button', { name: /^valider pour l'équipe/i }).click();
  71  |     await page.waitForTimeout(500);
  72  |   }
  73  |   await expect(modaleTitre).toBeHidden({ timeout: 10_000 });
  74  | 
  75  |   await page.goto('/dashboard');
  76  |   await expect(modaleTitre).toBeHidden();
  77  |   await page.goto('/clients');
  78  |   await expect(modaleTitre).toBeHidden();
  79  | 
  80  |   // 6) BUG-136 : le stock affiché dans « Production & Stocks » doit
  81  |   // refléter la valeur validée (pas la valeur proposée avant correction).
  82  |   await page.goto('/production');
> 83  |   await expect(page.getByText(valeurCorrigee, { exact: false }).first()).toBeVisible({ timeout: 10_000 });
      |                                                                          ^ Error: expect(locator).toBeVisible() failed
  84  | });
  85  | 
  86  | test('un compte DIRECTION (HQ) ne voit jamais la boîte modale « stock de départ »', async ({ page }) => {
  87  |   await seConnecter(page, COMPTES.direction.username, PASSWORD);
  88  |   await page.goto('/dashboard');
  89  |   await expect(page.getByText('Stock de départ du jour')).toHaveCount(0);
  90  |   await page.goto('/clients');
  91  |   await expect(page.getByText('Stock de départ du jour')).toHaveCount(0);
  92  | });
  93  | 
  94  | test('un compte ADMIN (HQ) ne voit jamais la boîte modale « stock de départ »', async ({ page }) => {
  95  |   await seConnecter(page, COMPTES.admin.username, PASSWORD);
  96  |   await page.goto('/dashboard');
  97  |   await expect(page.getByText('Stock de départ du jour')).toHaveCount(0);
  98  | });
  99  | 
  100 | /**
  101 |  * BUG-138/139/140 (docs/qa/REGISTRE_BUGS.md, CORRIGÉ au 2026-11-09, vérification
  102 |  * finale testeur-production) : un FACTURIER voit désormais la boîte modale
  103 |  * (BUG-138) et UNE SEULE confirmation (pas une par équipe) suffit à la faire
  104 |  * disparaître pour le reste de la journée (BUG-139/140). Ce test utilise le
  105 |  * facturier de K2 (pas K1) pour ne jamais dépendre de l'état déjà laissé par
  106 |  * le test gérant ci-dessus sur K1 — deux nœuds distincts, aucune collision
  107 |  * possible dans la base de dev partagée.
  108 |  */
  109 | test("un FACTURIER voit la boîte modale, peut confirmer, et une seule confirmation suffit (pas par équipe) — le bandeau d'ajustement de stock s'affiche (BUG-137)", async ({ page }) => {
  110 |   await seConnecter(page, COMPTES.facturierK2.username, PASSWORD, { reporterStockDepart: false });
  111 | 
  112 |   const modaleTitre = page.getByText('Stock de départ du jour');
  113 | 
  114 |   const dejaConfirmeeAuDepart = await modaleTitre.waitFor({ state: 'visible', timeout: 25_000 }).then(() => true).catch(() => false);
  115 |   if (!dejaConfirmeeAuDepart) {
  116 |     test.skip(true, 'K2 est déjà confirmé aujourd\'hui (exécution précédente) — BUG-138/139 déjà couverts, rien à refaire.');
  117 |   }
  118 |   await expect(modaleTitre).toBeVisible({ timeout: 10_000 });
  119 | 
  120 |   // BUG-138 : le FACTURIER voit bien le formulaire de saisie (pas un 403
  121 |   // silencieux, pas une modale vide).
  122 |   const premierChamp = page.locator('.modal, [role="dialog"]').filter({ hasText: 'Stock de départ du jour' })
  123 |     .locator('input:not([type="checkbox"]):not([type="radio"])').first();
  124 |   await expect(premierChamp).toBeVisible();
  125 | 
  126 |   // Corriger la quantité proposée pour déclencher un ajustement réel
  127 |   // (BUG-136/137 : le bandeau ne s'affiche que si le delta est non nul).
  128 |   // On ajoute toujours +1 (jamais -1) : K2 peut légitimement avoir un stock
  129 |   // à 0 pour cette catégorie (aucune fournée du jour), auquel cas une
  130 |   // décrémentation resterait clampée à 0 (delta nul, aucun bandeau) — un
  131 |   // incrément garantit un delta non nul quelle que soit la valeur proposée.
  132 |   const valeurProposee = await premierChamp.inputValue();
  133 |   const valeurCorrigee = String(parseInt(valeurProposee || '0', 10) + 1);
  134 |   await premierChamp.fill(valeurCorrigee);
  135 | 
  136 |   const boutonValider = page.getByRole('button', { name: /^valider pour l'équipe/i });
  137 |   await boutonValider.click();
  138 | 
  139 |   // BUG-137 : bandeau vert listant l'ajustement réel appliqué.
  140 |   await expect(page.getByText(/ajusté de/i)).toBeVisible({ timeout: 10_000 });
  141 | 
  142 |   // BUG-139/140 : UNE SEULE confirmation suffit — la modale ne doit PAS
  143 |   // redemander une deuxième équipe. Elle finit par se fermer (après le délai
  144 |   // d'affichage du bandeau), et ne réapparaît plus en changeant de page.
  145 |   await expect(modaleTitre).toBeHidden({ timeout: 10_000 });
  146 |   await page.goto('/clients');
  147 |   await expect(modaleTitre).toBeHidden();
  148 |   await page.goto('/dashboard');
  149 |   await expect(modaleTitre).toBeHidden();
  150 | });
  151 | 
```