# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: 13-ventes-vague2-db.spec.ts >> BUG-229/230 : client à risque proposé, refus plafond affiché, puis règlement intégral accepté, livraison, reçu
- Location: tests\13-ventes-vague2-db.spec.ts:28:5

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: locator('text=/BP:/').first()
Expected: visible
Timeout: 240000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" locator('text=/BP:/').first() with timeout 240000ms
  - waiting for locator('text=/BP:/').first()

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
  - 'button "Équipe de service : B (changer)"':
    - img
    - text: "Équipe de service : B (changer)"
  - button "Déconnexion":
    - img
    - text: Déconnexion
- main:
  - heading "Facturation (Facturier)" [level=2]
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
  - heading "Facturation en Chaîne & Livraison" [level=1]
  - paragraph: Saisie ultra-rapide par code client · Grille tarifaire officielle ETS. KIESE · Reçu thermique intégré
  - img
  - img
  - text: EN ATTENTE DE LIVRAISON
  - heading "7" [level=3]
  - img
  - text: LIVRÉES AUJOURD'HUI
  - heading "42" [level=3]
  - img
  - text: TOTAL FACTURÉ
  - heading "1 909 600 FC" [level=3]
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
  - text: Date de la commande (optionnel) Laisser vide = aujourd'hui. Jamais une date future.
  - textbox
  - text: Client — code ou nom *
  - img
  - 'textbox "Ex: K1-0045 ou KANZA Albert..."': K1-0081
  - text: Commande (Qté × Catégorie) Catégorie Qté Sous-total Pain 200 FC
  - spinbutton "0"
  - text: — Pain 300 FC
  - spinbutton "0"
  - text: — Pain 500 FC
  - spinbutton "0"
  - text: — Pain 1000 FC
  - spinbutton "0"
  - text: "— Total commande :"
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
  - button "Voir plus":
    - text: Voir plus
    - img
  - text: "K1-20261120-0049 CASH 04:59 EN ATTENTE CD PAS DE PHOTO DIVERSCLIENT DIVERS 2× Pain 200 FC 400 FC Total:"
  - strong: 400 FC
  - text: "Versé:"
  - strong: 400 FC
  - text: "BP avant:"
  - strong: 0 FC
  - img
  - text: Expire dans 11h39
  - button "Annuler":
    - img
    - text: Annuler
  - button "Imprimer le reçu":
    - img
    - text: Imprimer le reçu
  - text: "K1-20261120-0048 CASH 04:59 LIVRÉ [V PAS DE PHOTO K1-0081[K1-0081] Ventes 4 ZZTEST 1× Pain 200 FC 200 FC Total:"
  - strong: 200 FC
  - text: "Versé:"
  - strong: 200 FC
  - text: "BP avant:"
  - strong: 50 000 FC
  - img
  - text: "Distribué K1-20261120-0047 SOLDÉE 04:57 LIVRÉ [D PAS DE PHOTO K1-0078[K1-0078] DEMO CrossNodeE2E 2× Pain 200 FC 400 FC Total:"
  - strong: 300 FC
  - text: "Versé:"
  - strong: 0 FC
  - text: "BP avant:"
  - strong: 0 FC
  - text: "Perte (soldée):"
  - strong: "-100 FC"
  - img
  - text: Distribué
- dialog "Stock de départ de la relève":
  - heading "Stock de départ de la relève" [level=2]
  - paragraph: "Équipe de service : B — relève de 12:00. Confirmez ou corrigez le reste de l'équipe précédente pour démarrer ce service."
  - button "Fermer":
    - img
  - strong: "Équipe de service de la période : B (relève de 12:00)"
  - text: Les quantités proposées sont le reste de l'équipe précédente. Pains restants par catégorie Pain 200 FC
  - button "Changer le signe — Stock de départ — Pain 200 FC": ±
  - textbox "Stock de départ — Pain 200 FC": "0"
  - text: Pain 300 FC
  - button "Changer le signe — Stock de départ — Pain 300 FC": ±
  - textbox "Stock de départ — Pain 300 FC": "0"
  - text: Pain 500 FC
  - button "Changer le signe — Stock de départ — Pain 500 FC": ±
  - textbox "Stock de départ — Pain 500 FC": "0"
  - text: Pain 1000 FC
  - button "Changer le signe — Stock de départ — Pain 1000 FC": ±
  - textbox "Stock de départ — Pain 1000 FC": "13"
  - button "Plus tard"
  - button "Valider le stock de départ"
```

# Test source

```ts
  1  | import { test, expect, Page } from '@playwright/test';
  2  | 
  3  | /**
  4  |  * Vague 2 (testeur-ventes, 2026-11-12) — VRAIE base, K1 uniquement, comptes zz_ventes_* et clients
  5  |  * « ZZTEST Ventes n ». BUG-229 (client à risque proposé), BUG-230 (vente occasionnelle au comptant,
  6  |  * message d'erreur serveur), reçu complet.
  7  |  * Lancer : npx playwright test tests/13-ventes-vague2-db.spec.ts --project=pos --project=bureau
  8  |  */
  9  | const FACTURIER = 'zz_ventes_facturier';
  10 | const PWD = 'zz_ventes_facturier';
  11 | 
  12 | async function seConnecter(page: Page) {
  13 |   await page.goto('/login', { waitUntil: 'domcontentloaded', timeout: 240_000 });
  14 |   await page.getByPlaceholder('Ex: pierre').fill(FACTURIER, { timeout: 60_000 });
  15 |   await page.getByPlaceholder('••••••••').fill(PWD);
  16 |   await page.getByRole('button', { name: /se connecter/i }).click();
  17 |   await expect(page).toHaveURL(/\/dashboard/, { timeout: 30_000 });
  18 | }
  19 | async function reporterModale(page: Page) {
  20 |   const plusTard = page.getByRole('button', { name: /plus tard/i });
  21 |   await plusTard.waitFor({ state: 'visible', timeout: 8_000 }).then(() => plusTard.click()).catch(() => undefined);
  22 | }
  23 | async function sansDebordement(page: Page) {
  24 |   const ecart = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  25 |   expect(ecart, 'débordement horizontal (px)').toBeLessThanOrEqual(1);
  26 | }
  27 | 
  28 | test('BUG-229/230 : client à risque proposé, refus plafond affiché, puis règlement intégral accepté, livraison, reçu', async ({ page }) => {
  29 |   test.setTimeout(600_000);
  30 |   await seConnecter(page);
  31 |   await page.goto('/sales/create', { waitUntil: 'domcontentloaded', timeout: 240_000 });
  32 |   await reporterModale(page);
  33 |   await page.getByPlaceholder('Ex: K1-0045 ou KANZA Albert...').waitFor({ state: 'visible', timeout: 240_000 });
  34 |   await page.getByPlaceholder('Ex: K1-0045 ou KANZA Albert...').fill('K1-0081'); // ZZTEST Ventes 4, BP = plafond
  35 |   const suggestion = page.locator('text=/BP:/').first();
> 36 |   await expect(suggestion).toBeVisible({ timeout: 240_000 });
     |                            ^ Error: expect(locator).toBeVisible() failed
  37 |   await expect(page.getByText(/risque/i).first()).toBeVisible();
  38 |   await suggestion.click();
  39 |   await expect(page.getByText(/Client à risque — BP/)).toBeVisible();
  40 |   await sansDebordement(page);
  41 |   await page.locator('input[type="number"]').first().fill('1');
  42 |   await page.getByLabel(/Versement du jour/i).fill('0');
  43 |   await page.getByRole('button', { name: /facturer & mettre en attente/i }).click();
  44 |   await expect(page.getByText(/plafond de cr[ée]dit atteint/i).first()).toBeVisible({ timeout: 120_000 });
  45 |   await page.screenshot({ path: `../docs/qa/captures/ventes-vague2-refus-${test.info().project.name}.png`, fullPage: true });
  46 |   await sansDebordement(page);
  47 |   // règlement intégral (1 pain de la 1re catégorie = 200 FC) : doit être accepté
  48 |   await page.getByLabel(/Versement du jour/i).fill('200');
  49 |   await page.getByRole('button', { name: /facturer & mettre en attente/i }).click();
  50 |   await expect(page.locator('text=/BP avant/').first()).toBeVisible({ timeout: 120_000 });
  51 |   await sansDebordement(page);
  52 |   await page.getByRole('button', { name: /imprimer le reçu/i }).first().click();
  53 |   await expect(page.getByText('Confirmer la livraison')).toBeVisible({ timeout: 10_000 });
  54 |   await page.getByRole('button', { name: /confirmer & imprimer/i }).click();
  55 |   await expect(page.getByText(/BON DE LIVRAISON/)).toBeVisible({ timeout: 15_000 });
  56 |   await expect(page.getByText(/RCCM:\s*021-A-650/)).toBeVisible();
  57 |   await expect(page.getByText(/10-F4300-N85947U/)).toBeVisible();
  58 |   await expect(page.getByText(/A1902266K/)).toBeVisible();
  59 |   await expect(page.getByText(/^K1 - /)).toBeVisible();
  60 |   await expect(page.getByText(/BALANCE ANTÉRIEURE \(BP\)/)).toBeVisible();
  61 |   await expect(page.getByText('Solde arrêté ce jour')).toBeVisible();
  62 |   await expect(page.getByText(/Éq\.\s*[AB]/)).toBeVisible();
  63 |   await page.screenshot({ path: `../docs/qa/captures/ventes-vague2-recu-${test.info().project.name}.png`, fullPage: true });
  64 |   await sansDebordement(page);
  65 | });
  66 | 
  67 | test('BUG-230 : vente occasionnelle forcée au comptant (versement = commande), facture créée', async ({ page }) => {
  68 |   test.setTimeout(500_000);
  69 |   await seConnecter(page);
  70 |   await page.goto('/sales/create', { waitUntil: 'domcontentloaded', timeout: 240_000 });
  71 |   await reporterModale(page);
  72 |   await page.getByPlaceholder('Ex: K1-0045 ou KANZA Albert...').waitFor({ state: 'visible', timeout: 240_000 });
  73 |   await page.getByText('Vente occasionnelle (sans client enregistré)').click();
  74 |   await expect(page.locator('input[type="number"]').first()).toBeEnabled({ timeout: 240_000 });
  75 |   await page.locator('input[type="number"]').first().fill('2');
  76 |   await expect(page.getByLabel(/Versement du jour/i)).toBeDisabled();
  77 |   await expect(page.getByLabel(/Versement du jour/i)).toHaveValue('400');
  78 |   await page.getByRole('button', { name: /facturer & mettre en attente/i }).click();
  79 |   await expect(page.locator('text=/BP avant|CLIENT DIVERS|Imprimer le reçu/i').first()).toBeVisible({ timeout: 120_000 });
  80 |   await sansDebordement(page);
  81 |   await page.screenshot({ path: `../docs/qa/captures/ventes-vague2-occasionnelle-${test.info().project.name}.png`, fullPage: true });
  82 | });
  83 | 
```