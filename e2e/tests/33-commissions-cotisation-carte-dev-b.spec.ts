import { test, expect, type APIRequestContext, type Page } from '@playwright/test';
import { seConnecter } from '../fixtures/helpers';

/**
 * BUG-417 (volet frontend) : cotisation sociale et carte / frais d'imprime en FC, propres a chaque boulangerie.
 * Ecran Commissions CM : colonnes « Cotisation sociale (FC) » et « Carte / Frais d'imprime (FC) » par client,
 * ligne de totaux, format « 2 000 FC », et absence de debordement horizontal de la page a 360 px.
 *
 * A lancer sur une BASE JETABLE (le test modifie cotisation/carte de K5 et B1, puis les restaure).
 * Comptes du seed e2e : zz_demo_direction (mot de passe = identifiant), zz_demo_facturier_k5a, zz_demo_facturier_b1.
 * Donnees creees par l'API (fictives) : un client « ZZE417 » par boulangerie et une facture livree du jour.
 * Le test est rejouable : le client est reutilise ; les montants de commission sont releves dans la base, pas codes en dur.
 */
test.use({ viewport: { width: 360, height: 740 } });
test.describe.configure({ mode: 'serial' });

const API = process.env.E2E_API_URL || 'http://localhost:8000';

// Valeurs imposees aux deux boulangeries (differentes pour prouver que la valeur est propre a chacune).
const BOULANGERIES = [
  { code: 'K5', facturier: 'zz_demo_facturier_k5a', cotisation: '2000', carte: '1000', cotFmt: /^2\s000\sFC$/, carteFmt: /^1\s000\sFC$/ },
  { code: 'B1', facturier: 'zz_demo_facturier_b1', cotisation: '3000', carte: '1500', cotFmt: /^3\s000\sFC$/, carteFmt: /^1\s500\sFC$/ },
] as const;

interface NodeApi { id: number; code: string; monthly_social_contribution: string; card_fee_fc: string }
const sauvegarde: Record<string, { cot: string; carte: string; id: number }> = {};

async function token(request: APIRequestContext, username: string): Promise<string> {
  const r = await request.post(`${API}/api/core/auth/login/`, { data: { username, password: username } });
  expect(r.ok(), `connexion API ${username}`).toBeTruthy();
  return (await r.json()).access as string;
}
const auth = (t: string) => ({ Authorization: `Bearer ${t}` });

/** Aucun defilement horizontal de la PAGE (le tableau, lui, defile dans son conteneur). */
async function sansDebordementPage(page: Page, ecran: string) {
  const { scroll, inner } = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, inner: window.innerWidth }));
  expect(scroll, `debordement horizontal sur ${ecran} (scrollWidth ${scroll} > innerWidth ${inner})`).toBeLessThanOrEqual(inner);
}

const nombre = (s: string) => parseInt(s.replace(/[^\d-]/g, ''), 10) || 0;

test('prepare : cotisation/carte differentes par boulangerie, un client et une facture livree par boulangerie', async ({ request }) => {
  test.setTimeout(240_000);
  const direction = await token(request, 'zz_demo_direction');
  const nodes = ((await (await request.get(`${API}/api/core/nodes/`, { headers: auth(direction) })).json()).results ?? []) as NodeApi[];
  const prix = ((await (await request.get(`${API}/api/core/bread-prices/`, { headers: auth(direction) })).json()).results ?? []) as { id: number }[];
  expect(prix.length).toBeGreaterThan(0);

  for (const b of BOULANGERIES) {
    const node = nodes.find(n => n.code === b.code);
    expect(node, `boulangerie ${b.code} absente du seed`).toBeTruthy();
    sauvegarde[b.code] = { id: node!.id, cot: node!.monthly_social_contribution, carte: node!.card_fee_fc };
    const patch = await request.patch(`${API}/api/core/nodes/${node!.id}/`, {
      headers: auth(direction), data: { monthly_social_contribution: b.cotisation, card_fee_fc: b.carte },
    });
    expect(patch.ok(), `PATCH ${b.code} : ${await patch.text()}`).toBeTruthy();

    // Client fictif reutilise d'une execution a l'autre.
    const tF = await token(request, b.facturier);
    const recherche = await (await request.get(`${API}/api/clients/clients/?search=ZZE417`, { headers: auth(tF) })).json();
    let clientId: string | undefined = (recherche.results ?? []).find((c: { node: number }) => c.node === node!.id)?.id;
    if (!clientId) {
      const cree = await request.post(`${API}/api/clients/clients/`, {
        headers: auth(direction),
        data: { first_name: 'ZZE417', last_name: b.code, node: node!.id, commission_rate: '0.25', credit_limit: '50000', cotisation_sociale: null },
      });
      expect(cree.ok(), `creation client ${b.code} : ${await cree.text()}`).toBeTruthy();
      clientId = (await cree.json()).id as string;
    }
    // Facture du jour, payee comptant, puis livraison (genere la base de la commission du mois courant).
    const f = await request.post(`${API}/api/sales/invoices/`, {
      headers: auth(tF),
      data: { client: clientId, payment_type: 'CASH', payment_amount: '20000', lines: [{ bread_price: prix[0].id, quantity: 100 }] },
    });
    expect(f.ok(), `facture ${b.code} : ${await f.text()}`).toBeTruthy();
    const inv = await f.json();
    const l = await request.post(`${API}/api/sales/invoices/${inv.id}/deliver/`, { headers: auth(tF), data: {} });
    expect(l.ok(), `livraison ${b.code} : ${await l.text()}`).toBeTruthy();
  }
});

test('Commissions CM a 360 px : colonnes cotisation et carte par client, totaux, format FC, sans debordement', async ({ page }) => {
  test.setTimeout(240_000);
  await seConnecter(page, 'zz_demo_direction');
  await page.goto('/commissions', { waitUntil: 'domcontentloaded' });
  await expect(page.getByRole('heading', { name: 'Commissions des Revendeurs (CM)' })).toBeVisible();
  await sansDebordementPage(page, 'Commissions (avant generation)');

  const selNoeud = page.locator('select.form-input').filter({ has: page.locator('option', { hasText: 'Toutes les boulangeries' }) });
  const totaux = page.getByTestId('cm-totals-row');

  for (const b of BOULANGERIES) {
    // Generation par l'ecran (modale), pour la boulangerie b.
    await page.getByRole('button', { name: /générer commissions/i }).click();
    const modale = page.locator('.modal-content, [role="dialog"]').filter({ hasText: 'Générer une Période de Commissions' }).first();
    await expect(modale).toBeVisible();
    await modale.locator('select').first().selectOption({ label: (await modale.locator('option', { hasText: new RegExp(`^${b.code} `) }).first().innerText()).trim() });
    await modale.getByRole('button', { name: /^générer$/i }).click();
    await expect(modale.getByText(/commission\(s\) générée\(s\)/)).toBeVisible({ timeout: 30_000 });
    await modale.locator('button.btn-secondary', { hasText: 'Fermer' }).click();
    await expect(modale).toHaveCount(0);

    // Filtre par boulangerie : les lignes du client ZZE417 apparaissent.
    await selNoeud.selectOption({ label: (await selNoeud.locator('option', { hasText: new RegExp(`^${b.code} `) }).first().innerText()).trim() });
    const ligne = page.locator('tbody tr').filter({ hasText: `${b.code} ZZE417` }).first();
    await expect(ligne).toBeVisible({ timeout: 30_000 });
    const cellules = ligne.locator('td');
    // Colonnes : Client, Cmd, Tx, CM Brute, NET/ORDI, Cotisation, Carte, NET A PAYER, Statut, Action.
    const cot = (await cellules.nth(5).innerText()).trim();
    const carte = (await cellules.nth(6).innerText()).trim();
    expect(cot.replace(/\s/g, ' '), `cotisation ${b.code}`).toMatch(b.cotFmt);
    expect(carte.replace(/\s/g, ' '), `carte ${b.code}`).toMatch(b.carteFmt);

    // En-tetes presents.
    await expect(page.getByRole('columnheader', { name: 'Cotisation sociale (FC)' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: "Carte / Frais d'imprimé (FC)" })).toBeVisible();

    // Ligne de totaux : somme verticale des colonnes de TOUTES les lignes affichees (pas de filtre de recherche actif).
    await expect(totaux).toBeVisible();
    await expect(totaux).not.toContainText('…', { timeout: 20_000 });
    const lignes = page.locator('tbody tr').filter({ has: page.locator('td:nth-child(10)') });
    const n = await lignes.count();
    let sCot = 0; let sCarte = 0;
    for (let i = 0; i < n; i++) {
      sCot += nombre(await lignes.nth(i).locator('td').nth(5).innerText());
      sCarte += nombre(await lignes.nth(i).locator('td').nth(6).innerText());
    }
    const totCot = (await page.getByTestId('cm-total-cotisation').innerText()).trim();
    const totCarte = (await page.getByTestId('cm-total-carte').innerText()).trim();
    expect(totCot).toMatch(/FC$/);
    expect(totCarte).toMatch(/FC$/);
    expect(nombre(totCot), `total cotisation ${b.code}`).toBe(sCot);
    expect(nombre(totCarte), `total carte ${b.code}`).toBe(sCarte);

    await sansDebordementPage(page, `Commissions ${b.code}`);
  }

  // Les deux boulangeries ont des valeurs differentes (cotisation et carte propres a chacune).
  expect(BOULANGERIES[0].carte).not.toBe(BOULANGERIES[1].carte);
});

// Restauration des valeurs d'origine, meme si un test a echoue.
test.afterAll(async ({ playwright }) => {
  const request = await playwright.request.newContext();
  try {
    const direction = await token(request, 'zz_demo_direction');
    for (const [code, s] of Object.entries(sauvegarde)) {
      const r = await request.patch(`${API}/api/core/nodes/${s.id}/`, {
        headers: auth(direction), data: { monthly_social_contribution: s.cot, card_fee_fc: s.carte },
      });
      expect(r.ok(), `restauration ${code}`).toBeTruthy();
    }
  } finally {
    await request.dispose();
  }
});
