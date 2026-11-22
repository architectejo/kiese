import { test, expect, Page } from '@playwright/test';
import { CAP, API, login, later, overflow, idx, apiToken, confirmerLivraison } from '../fixtures/cycle';

/**
 * Une fois le rapport facturier (niveau 1) genere par le parcours 21, la livraison de la vacation est bloquee
 * (regle metier) : une boulangerie par largeur d'ecran. pos -> K2, tablette -> B1, bureau (et tv) -> K4.
 */
const CFG19 = [
  { node: 'K2', fac: 'zz_demo_facturier_k2', liv: 'zz_demo_livreur_k2' },
  { node: 'B1', fac: 'zz_demo_facturier_b1', liv: 'zz_demo_livreur_b1' },
  { node: 'K4', fac: 'zz_treso_facturier_a', liv: 'zz_treso_livreur' },
  { node: 'K4', fac: 'zz_treso_facturier_a', liv: 'zz_treso_livreur' },
];

/**
 * Cycle final (testeur-e2e, 2026-11-14) - facturier et livreur K4 sur db.sqlite3, plafond 50 000 FC.
 * Comptes zz_* (autorises par l'utilisateur). Une paire de clients par taille d'ecran.
 */
const BASE = Number(process.env.E2E_CLIENT_BASE || 900); // fenetre de clients K4 (rejeu : changer la base)
const QTE_500 = 2; // index de la ligne « Pain 500 FC » dans les champs numeriques

async function menuMobile(page: Page) {
  const h = page.getByTitle('Menu de navigation');
  if (await h.isVisible().catch(() => false)) await h.click();
}

async function choisirClient(page: Page, code: string) {
  await later(page); // la modale « Stock de depart » peut se rouvrir apres un rechargement
  const r = page.getByPlaceholder('Ex: K1-0045 ou KANZA Albert...');
  await r.fill(code);
  await page.locator('text=/BP:|Solde OK/').first().click();
  await expect(page.getByText(/Balance antérieure/i).first()).toBeVisible();
}

async function facturer(page: Page, code: string, qte500: number, verse: number) {
  await choisirClient(page, code);
  const nb = page.locator('input[type="number"]');
  await nb.nth(QTE_500).fill(String(qte500));
  await page.getByLabel(/Versement du jour/i).fill(String(verse));
  await page.getByRole('button', { name: /facturer & mettre en attente/i }).click();
}

test.describe('FACTURIER K4', () => {
  test('menu, routes refusees, facturation, livraison, recu, plafond 50 000', async ({ page, request }, info) => {
    test.setTimeout(420_000);
    const i = idx(info.project.name);
    const C = CFG19[i];
    const cExact = `${C.node}-${String(BASE + i).padStart(4, '0')}`;   // BP = 50 000 pile apres livraison
    const cSous = `${C.node}-${String(BASE + 10 + i).padStart(4, '0')}`;    // BP = 49 500 (< plafond)
    await login(page, C.fac);
    await later(page);

    await menuMobile(page);
    await expect(page.locator('a[href="/treasury"]')).toHaveCount(0);
    await expect(page.locator('a[href="/cloture-journaliere"]')).toHaveCount(0);
    await expect(page.locator('a[href="/commissions"]')).toHaveCount(0);
    await expect(page.locator('a[href="/sales/create"]')).toHaveCount(1);
    await page.screenshot({ path: `${CAP}/cf-${info.project.name}-facturier-menu.png` });
    for (const r of ['/treasury', '/cloture-journaliere', '/commissions']) {
      await page.goto(r, { waitUntil: 'domcontentloaded' });
      await expect(page.getByText('Accès refusé')).toBeVisible({ timeout: 30_000 });
      expect(await overflow(page)).toBeLessThanOrEqual(1);
    }

    await page.goto('/sales/create', { waitUntil: 'domcontentloaded' });
    await later(page);
    await facturer(page, cExact, 100, 0);
    await expect(page.getByText(/BP avant/).first()).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(/aucune facture en attente/i)).toHaveCount(0);
    await page.screenshot({ path: `${CAP}/cf-${info.project.name}-facturier-file.png`, fullPage: true });
    expect(await overflow(page)).toBeLessThanOrEqual(1);

    await confirmerLivraison(page);
    const recu = page.locator('body');
    await expect(recu.getByText(/RCCM:?\s*021-A-650/)).toBeVisible();
    await expect(recu.getByText(/10-F4300-N85947U/)).toBeVisible();
    await expect(recu.getByText(/A1902266K/)).toBeVisible();
    await expect(recu.getByText(new RegExp(`^${C.node} - `)).first()).toBeVisible();
    await expect(recu.getByText(/BALANCE ANTÉRIEURE \(BP\)/)).toBeVisible();
    await expect(recu.getByText(/NOUVELLE DETTE|NOUVELLE BP|BALANCE/).first()).toBeVisible();
    await expect(recu.getByText('Solde arrêté ce jour')).toBeVisible();
    await expect(recu.getByText(/25\s*%/).first()).toBeVisible();
    await expect(recu.getByText(/50\s?000/).first()).toBeVisible();
    await page.screenshot({ path: `${CAP}/cf-${info.project.name}-facturier-recu.png`, fullPage: true });
    await page.getByRole('button', { name: /fermer/i }).last().click();

    // BP = 50 000 = plafond : 2e facture sans versement -> blocage
    await facturer(page, cExact, 1, 0);
    const msg = page.getByText(/plafond|bloqu/i).first();
    await expect(msg).toBeVisible({ timeout: 30_000 });
    await page.screenshot({ path: `${CAP}/cf-${info.project.name}-facturier-blocage.png`, fullPage: true });
    info.annotations.push({ type: 'message-blocage', description: (await msg.innerText()).slice(0, 300) });
    expect(await overflow(page)).toBeLessThanOrEqual(1);

    // Refus cote serveur (403 + message francais), independamment de l'ecran
    const tok = await apiToken(request, C.fac);
    const H = { Authorization: `Bearer ${tok}` };
    const cl = await (await request.get(`${API}/api/clients/clients/?search=${cExact}`, { headers: H })).json();
    const prix = await (await request.get(`${API}/api/core/bread-prices/`, { headers: H })).json();
    const p500 = prix.results.find((p: { unit_price: number }) => p.unit_price === 500).id;
    const refus = await request.post(`${API}/api/sales/invoices/`, {
      headers: H,
      data: { client: cl.results[0].id, payment_type: 'CREDIT', payment_amount: '0', lines: [{ bread_price: p500, quantity: 1 }] },
    });
    info.annotations.push({ type: 'api-blocage', description: `${refus.status()} ${(await refus.text()).slice(0, 250)}` });
    expect(refus.status()).toBe(403);
    expect((await refus.json()).detail).toMatch(/plafond|bloqu/i);

    // Client a 49 500 (< plafond) : pas de blocage a la 2e facture
    await page.reload({ waitUntil: 'domcontentloaded' });
    await later(page);
    await facturer(page, cSous, 99, 0);
    await expect(page.getByText(/BP avant/).first()).toBeVisible({ timeout: 30_000 });
    await confirmerLivraison(page);
    await page.getByRole('button', { name: /fermer/i }).last().click();
    await facturer(page, cSous, 1, 0);
    await expect(page.getByText(/plafond|bloqu/i)).toHaveCount(0);
    await expect(page.getByText(/en attente/i).first()).toBeVisible();
    await page.screenshot({ path: `${CAP}/cf-${info.project.name}-facturier-sous-plafond.png`, fullPage: true });
  });
});

test.describe('LIVREUR K4', () => {
  test('menu, routes refusees, livraison de la file, recu', async ({ page }, info) => {
    test.setTimeout(300_000);
    await login(page, CFG19[idx(info.project.name)].liv);
    await later(page);
    await menuMobile(page);
    await expect(page.locator('a[href="/treasury"]')).toHaveCount(0);
    await expect(page.locator('a[href="/cloture-journaliere"]')).toHaveCount(0);
    await expect(page.locator('a[href="/commissions"]')).toHaveCount(0);
    await page.screenshot({ path: `${CAP}/cf-${info.project.name}-livreur-menu.png` });
    for (const r of ['/treasury', '/cloture-journaliere', '/commissions']) {
      await page.goto(r, { waitUntil: 'domcontentloaded' });
      await expect(page.getByText('Accès refusé')).toBeVisible({ timeout: 30_000 });
    }
    const codes403: string[] = [];
    page.on('response', rs => { if (rs.status() === 403) codes403.push(rs.url()); });
    await page.goto('/sales/create', { waitUntil: 'domcontentloaded' });
    await later(page);
    await expect(page.getByText(/File des Livraisons/i)).toBeVisible({ timeout: 30_000 });
    await page.screenshot({ path: `${CAP}/cf-${info.project.name}-livreur-file.png`, fullPage: true });
    expect(await overflow(page)).toBeLessThanOrEqual(1);
    await confirmerLivraison(page);
    await expect(page.getByText(/RCCM:?\s*021-A-650/)).toBeVisible();
    await expect(page.getByText('Solde arrêté ce jour')).toBeVisible();
    await page.screenshot({ path: `${CAP}/cf-${info.project.name}-livreur-recu.png`, fullPage: true });
    info.annotations.push({ type: '403-livreur', description: codes403.join(' | ') || 'aucun' });
  });
});
