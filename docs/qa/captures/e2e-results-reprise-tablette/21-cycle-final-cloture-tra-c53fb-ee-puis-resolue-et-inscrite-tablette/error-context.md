# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: 21-cycle-final-cloture-transfert.spec.ts >> BUG-277 : transfert en litige -> confirmation de cloture bloquee, puis resolue et inscrite
- Location: tests\21-cycle-final-cloture-transfert.spec.ts:97:5

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByText('Réceptions à Confirmer')
Expected: visible
Timeout: 30000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" getByText('Réceptions à Confirmer') with timeout 30000ms
  - waiting for getByText('Réceptions à Confirmer')

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
  - text: "Gérant de Boulangerie BOULANGERIE : K6 - ZADIM"
  - button "Déconnexion":
    - img
    - text: Déconnexion
- main:
  - button "Menu de navigation":
    - img
  - heading "Production & Stocks" [level=2]
  - button "Messagerie, 10 message(s) non lu(s)"
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
  - button "Actualiser" [disabled]:
    - img
    - text: Actualiser
  - text: 🔥 FOURNÉES ENREGISTRÉES … 💰 VALEUR FC PRODUITE … 🚚 TRANSFERTS EN ATTENTE 0 📦 PAINS NON VALORISÉS 0
  - button "Fournées":
    - img
    - text: Fournées
  - button "Intrants":
    - img
    - text: Intrants
  - button "Transferts":
    - img
    - text: Transferts
  - button "Réconciliation":
    - img
    - text: Réconciliation
  - heading "§3.3 — Transferts Inter-Boulangeries (Règle d'Or Comptable)" [level=2]:
    - img
    - text: §3.3 — Transferts Inter-Boulangeries (Règle d'Or Comptable)
  - heading "Faire une Demande de Pains" [level=3]
  - paragraph: Sélectionnez la boulangerie qui vous enverra les pains et indiquez les quantités souhaitées.
  - text: Demander à *
  - combobox:
    - option "— Boulangerie source —" [selected]
  - text: Quantités demandées par catégorie * Notes
  - textbox "Motif, urgence..."
  - button "Envoyer la demande":
    - img
    - text: Envoyer la demande
  - img
  - text: Aucune action en attente.
```

# Test source

```ts
  33  |     data: { client: cl.results[0].id, payment_type: verse > 0 ? 'CASH' : 'CREDIT', payment_amount: String(verse), lines: [{ bread_price: p500, quantity: qte500 }] },
  34  |   });
  35  |   expect(c.status(), await c.text()).toBe(201);
  36  |   const inv = await c.json();
  37  |   const d = await request.post(`${API}/api/sales/invoices/${inv.id}/deliver/`, { headers: H });
  38  |   expect(d.ok(), await d.text()).toBeTruthy();
  39  | }
  40  | 
  41  | async function allerTreso(page: Page) {
  42  |   await page.goto('/treasury', { waitUntil: 'domcontentloaded' });
  43  |   await later(page);
  44  | }
  45  | 
  46  | async function filtrerK4(page: Page, node = 'K4') {
  47  |   const re = new RegExp(node);
  48  |   const f = page.locator('select').filter({ has: page.locator('option', { hasText: re }) }).first();
  49  |   if (await f.count()) await f.selectOption({ label: (await f.locator('option', { hasText: re }).first().innerText()).trim() });
  50  | }
  51  | 
  52  | test('Gerant K4 : cloture avec billetage et ecart', async ({ page, request }, info) => {
  53  |   const C = cfg(info);
  54  |   test.setTimeout(480_000);
  55  |   // 10 000 FC cash integral + 5 000 FC verses sur 20 000 : cash du jour = 15 000 FC
  56  |   if (!process.env.E2E_SKIP_SETUP) { // rejeu : les rapports du jour existent deja (livraison bloquee apres rapport)
  57  |   await creerVenteCash(request, C.facA, C.cliA, 20, 10_000); // equipe A
  58  |   await creerVenteCash(request, C.facB, C.cliB, 40, 5_000); // equipe B
  59  |   }
  60  | 
  61  |   await login(page, C.ger);
  62  |   await allerTreso(page);
  63  |   await page.getByRole('button', { name: /générer rapport du jour/i }).click();
  64  |   await expect(page.getByText(/TOTAL CASH DU JOUR/)).toBeVisible();
  65  |   await expect(page.getByText('15 000 FC').first()).toBeVisible({ timeout: 30_000 });
  66  | 
  67  |   // depense locale 2 000 FC
  68  |   await page.getByRole('button', { name: /^ajouter$/i }).click();
  69  |   await page.locator('form').filter({ hasText: /Enregistrer la Dépense/ }).locator('input[type="number"]').fill('2000');
  70  |   await page.getByPlaceholder('Nature de la dépense...').fill('Transport test E2E');
  71  |   await page.getByRole('button', { name: /enregistrer la dépense/i }).click();
  72  |   await expect(page.getByText(/Transport test E2E/)).toBeVisible({ timeout: 30_000 });
  73  |   await expect(page.getByText(/-2\s?000 FC/)).toBeVisible();
  74  | 
  75  |   // validation du rapport facturier
  76  |   await page.getByRole('button', { name: /confirmer & clôturer/i }).click();
  77  |   await expect(page.getByText(/rapport\(s\) validé\(s\)/)).toBeVisible({ timeout: 30_000 });
  78  | 
  79  |   // billetage : 10 000 + 3 x 1 000 + 500 = 13 500 (net theorique 13 000, ecart +500)
  80  |   const champs = page.locator('form').filter({ hasText: /Valeur Faciale/i }).locator('input[type="number"]');
  81  |   await champs.nth(1).fill('1');   // 10 000
  82  |   await champs.nth(3).fill('3');   // 1 000
  83  |   await champs.nth(4).fill('1');   // 500
  84  |   await expect(page.getByText(/TOTAL GÉNÉRAL ESPÈCES/)).toBeVisible();
  85  |   await expect(page.getByText(/13\s?500 FC/).first()).toBeVisible();
  86  |   await expect(page.getByText(/\+500 FC \(Excédent\)/)).toBeVisible();
  87  |   await page.screenshot({ path: `${CAP}/cf-${info.project.name}-cloture-billetage.png`, fullPage: true });
  88  |   expect(await overflow(page)).toBeLessThanOrEqual(1);
  89  |   await page.getByRole('button', { name: /valider la clôture de caisse du jour/i }).click();
  90  |   await expect(page.getByText(/Clôture créée/)).toBeVisible({ timeout: 30_000 });
  91  |   await expect(page.getByText('EN ATTENTE').first()).toBeVisible();
  92  |   await page.screenshot({ path: `${CAP}/cf-${info.project.name}-cloture-creee.png`, fullPage: true });
  93  |   // la clôture est deja la : plus de saisie possible pour le jour, ecart journalise (+500)
  94  |   await expect(page.getByText(/Écart: \+?500 FC/).first()).toBeVisible();
  95  | });
  96  | 
  97  | test('BUG-277 : transfert en litige -> confirmation de cloture bloquee, puis resolue et inscrite', async ({ page }, info) => {
  98  |   const C = cfg(info);
  99  |   test.setTimeout(900_000);
  100 |   if (!process.env.E2E_SKIP_TRANSFER_SETUP) {
  101 |   // 1) K4 demande 2 pains de 200 FC a K3
  102 |   await login(page, C.ger);
  103 |   await page.goto('/production', { waitUntil: 'domcontentloaded' });
  104 |   await later(page);
  105 |   await page.getByRole('button', { name: /transferts/i }).first().click();
  106 |   await page.locator('select').filter({ has: page.locator('option', { hasText: /K3/ }) }).first().selectOption({ label: /K3/ as unknown as string }).catch(async () => {
  107 |     const s = page.locator('select').filter({ has: page.locator('option', { hasText: /K3/ }) }).first();
  108 |     await s.selectOption({ label: (await s.locator('option', { hasText: /K3/ }).first().innerText()).trim() });
  109 |   });
  110 |   await page.locator('form').filter({ hasText: /Quantités demandées/i }).locator('input[type="number"]').first().fill('2');
  111 |   await page.locator('form').filter({ hasText: /Quantités demandées/i }).getByPlaceholder('Motif, urgence...').fill('Test E2E BUG-277');
  112 |   await page.getByRole('button', { name: /envoyer la demande/i }).click();
  113 |   await expect(page.getByRole('status').filter({ hasText: /demande|envoy/i }).first()).toBeVisible({ timeout: 30_000 });
  114 | 
  115 |   // 2) K3 envoie
  116 |   await login(page, 'zz_prod_gerant_k3');
  117 |   await page.goto('/production', { waitUntil: 'domcontentloaded' });
  118 |   await later(page);
  119 |   const equipe = page.getByRole('button', { name: /confirmer l'équipe/i });
  120 |   if (await equipe.waitFor({ state: 'visible', timeout: 10_000 }).then(() => true).catch(() => false)) await equipe.click();
  121 |   await later(page);
  122 |   await page.getByRole('button', { name: /transferts/i }).first().click();
  123 |   await page.getByRole('button', { name: /envoyer les pains/i }).first().click();
  124 |   await expect(page.getByText(/RÉCEPTIONNÉ|Réceptions à Confirmer|envoy/i).first()).toBeVisible({ timeout: 30_000 });
  125 | 
  126 |   }
  127 | 
  128 |   // 3) K4 recoit 1 sur 2 -> litige
  129 |   await login(page, C.ger);
  130 |   await page.goto('/production', { waitUntil: 'domcontentloaded' });
  131 |   await later(page);
  132 |   await page.getByRole('button', { name: /transferts/i }).first().click();
> 133 |   await expect(page.getByText('Réceptions à Confirmer')).toBeVisible({ timeout: 30_000 });
      |                                                          ^ Error: expect(locator).toBeVisible() failed
  134 |   await page.getByText(/envoyé: 2/).first().locator('xpath=ancestor::div[1]').locator('input').fill('1');
  135 |   await page.getByRole('button', { name: /confirmer la réception/i }).first().click();
  136 |   await expect(page.getByText(/LITIGE D'ÉCART/).first()).toBeVisible({ timeout: 30_000 });
  137 |   await expect(page.getByText(/Clôture de caisse bloquée/).first()).toBeVisible();
  138 |   await page.screenshot({ path: `${CAP}/cf-${info.project.name}-bug277-litige.png`, fullPage: true });
  139 | 
  140 |   // 4) direction : confirmation de la cloture K4 refusee
  141 |   await login(page, 'zz_direction');
  142 |   await allerTreso(page);
  143 |   await filtrerK4(page, C.node);
  144 |   const dialogues: string[] = [];
  145 |   page.on('dialog', async d => { dialogues.push(d.message()); await d.dismiss(); });
  146 |   await page.getByText('Cliquez pour confirmer / infirmer').first().click();
  147 |   await page.getByRole('button', { name: /^confirmer$/i }).first().click();
  148 |   await page.getByRole('button', { name: /confirmer la clôture/i }).click();
  149 |   await expect.poll(() => dialogues.length, { timeout: 30_000 }).toBeGreaterThan(0);
  150 |   info.annotations.push({ type: 'message-validate-bloque', description: dialogues[0].slice(0, 300) });
  151 |   expect(dialogues[0]).toMatch(/transfert|écart/i);
  152 |   await page.screenshot({ path: `${CAP}/cf-${info.project.name}-bug277-confirmation-bloquee.png`, fullPage: true });
  153 | 
  154 |   // 5) K3 (emettrice) resout le litige
  155 |   await login(page, 'zz_prod_gerant_k3');
  156 |   await page.goto('/production', { waitUntil: 'domcontentloaded' });
  157 |   await later(page);
  158 |   await page.getByRole('button', { name: /transferts/i }).first().click();
  159 |   await page.getByRole('button', { name: /résoudre le litige/i }).first().click();
  160 |   await page.getByPlaceholder('Motif de la résolution (obligatoire)').fill('Recomptage physique constate, test E2E');
  161 |   await page.getByRole('button', { name: /confirmer la résolution/i }).click();
  162 |   await expect(page.getByText(/Litige résolu/)).toBeVisible({ timeout: 30_000 });
  163 | 
  164 |   // 6) direction : confirmation OK puis inscription au livre de caisse
  165 |   await login(page, 'zz_direction');
  166 |   await allerTreso(page);
  167 |   await filtrerK4(page, C.node);
  168 |   await page.getByText('Cliquez pour confirmer / infirmer').first().click();
  169 |   await page.getByRole('button', { name: /^confirmer$/i }).first().click();
  170 |   await page.getByRole('button', { name: /confirmer la clôture/i }).click();
  171 |   await expect(page.getByText('CONFIRMÉE').first()).toBeVisible({ timeout: 30_000 });
  172 |   await page.getByRole('button', { name: /inscrire au livre de caisse/i }).first().click();
  173 |   await expect(page.getByText(/Inscrit au grand livre/).first()).toBeVisible({ timeout: 30_000 });
  174 |   await page.screenshot({ path: `${CAP}/cf-${info.project.name}-bug277-inscrit.png`, fullPage: true });
  175 | });
  176 | 
  177 | test('Livre de caisse : solde progressif et verification d\'integrite verte (direction)', async ({ page }, info) => {
  178 |   const C = cfg(info);
  179 |   test.setTimeout(240_000);
  180 |   await login(page, 'zz_direction');
  181 |   await allerTreso(page);
  182 |   await filtrerK4(page, C.node);
  183 |   await expect(page.getByText(new RegExp(`Versement Journalier ${C.node}`)).first()).toBeVisible({ timeout: 60_000 });
  184 |   const dialogues: string[] = [];
  185 |   page.on('dialog', async d => { dialogues.push(d.message()); await d.dismiss(); });
  186 |   await page.getByRole('button', { name: /vérifier intégrité/i }).click();
  187 |   await expect(page.getByText(/Chaîne intègre/)).toBeVisible({ timeout: 30_000 });
  188 |   await page.waitForTimeout(1500);
  189 |   await page.screenshot({ path: `${CAP}/cf-${info.project.name}-livre-integrite.png`, fullPage: true });
  190 |   info.annotations.push({ type: 'dialogues', description: dialogues.join(' | ').slice(0, 300) || 'aucun' });
  191 |   await expect(page.getByText(/Chaîne (rompue|corrompue|invalide)|falsifi/i)).toHaveCount(0);
  192 | });
  193 | 
```