import { test, expect, Page, APIRequestContext } from '@playwright/test';
import { CAP, API, login, later, overflow, idx, apiToken } from '../fixtures/cycle';

/**
 * Verification (testeur-e2e, 2026-11-15) de BUG-301 (frontend) et du volet frontend de BUG-290.
 * Comptes zz_e301_* (B2, mot de passe = identifiant) et clients « ZZE301 ... » fictifs, crees a part.
 * Un jeu de clients par largeur : POS (360), TAB (768), BUR (1440). Le projet « tv » est ignore.
 */
const SUF = ['POS', 'TAB', 'BUR', 'BUR'];
const NEG = /[-−]\s?/;

test.describe.configure({ mode: 'serial' });

async function menuMobile(page: Page) {
  const h = page.getByTitle('Menu de navigation');
  if (await h.isVisible().catch(() => false)) await h.click();
}

async function choisir(page: Page, nom: string) {
  await later(page);
  await page.getByPlaceholder('Ex: K1-0045 ou KANZA Albert...').fill(nom);
  await page.locator('text=/BP:|Solde OK/').first().click();
  await expect(page.getByText(/Balance antérieure/i).first()).toBeVisible();
}

async function recuOuvert(page: Page) {
  await expect(page.getByText(/BON DE LIVRAISON/)).toBeVisible({ timeout: 30_000 });
}

test.beforeEach(({}, info) => {
  test.skip(info.project.name === 'tv', 'largeurs demandees : 360, 768, 1440');
});

test('(1a) facturier : commande + paiement negatif + Motif, recu', async ({ page }, info) => {
  test.setTimeout(240_000);
  const s = SUF[idx(info.project.name)];
  await login(page, 'zz_e301_fact');
  await later(page);
  await page.goto('/sales/create', { waitUntil: 'domcontentloaded' });
  await choisir(page, `Retrait${s}`);
  await page.locator('input[type="number"]').nth(2).fill('1'); // Pain 500 FC
  await page.getByLabel(/Versement du jour/i).fill('-5000');
  await expect(page.getByText(/Versement négatif : sortie de caisse/)).toBeVisible();
  await expect(page.getByText(/Nouvelle BP ≈ 5\s?500 FC/)).toBeVisible();
  await page.locator('select').filter({ has: page.locator('option', { hasText: "Retrait d'épargne" }) })
    .selectOption({ label: "Retrait d'épargne" });
  expect(await overflow(page)).toBeLessThanOrEqual(1);
  await page.screenshot({ path: `${CAP}/b301-${info.project.name}-1a-form.png`, fullPage: true });
  await page.getByRole('button', { name: /facturer & mettre en attente/i }).click();
  await expect(page.getByText(/BP avant/).first()).toBeVisible({ timeout: 30_000 });
  await page.getByRole('button', { name: /imprimer le reçu/i }).first().click();
  await page.getByRole('button', { name: /confirmer & imprimer/i }).click();
  await recuOuvert(page);
  const recu = page.locator('body');
  await expect(recu.getByText(/VERSEMENT DU JOUR/)).toBeVisible();
  const ligne = recu.locator('tr', { hasText: 'VERSEMENT DU JOUR' });
  await expect(ligne).toContainText(/[-−]\s?5\s?000/);
  await expect(recu.getByText('Solde arrêté ce jour')).toBeVisible();
  await expect(recu.locator('tr', { hasText: /NOUVELLE/ }).first()).toContainText(/5\s?500/);
  await page.screenshot({ path: `${CAP}/b301-${info.project.name}-1a-recu.png`, fullPage: true });
  expect(await overflow(page)).toBeLessThanOrEqual(1);
});

test('(1b) facturier : versement sans commande negatif + Motif, recu', async ({ page, request }, info) => {
  test.setTimeout(240_000);
  const s = SUF[idx(info.project.name)];
  await login(page, 'zz_e301_fact');
  await later(page);
  await page.goto('/sales/create', { waitUntil: 'domcontentloaded' });
  await choisir(page, `Epargne${s}`);
  await page.getByRole('button', { name: /Remboursement \/ Dépôt sans commande/ }).click();
  const modal = page.getByRole('dialog').or(page.locator('form', { hasText: 'Montant versé' })).first();
  await page.getByPlaceholder('Ex: 10000 ou -5000').fill('-4000');
  await expect(page.getByText(/Nouvelle BP après versement/).locator('xpath=..')).toContainText(/-\s?6\s?000/);
  await page.locator('select').filter({ has: page.locator('option', { hasText: "Retrait d'épargne" }) }).last()
    .selectOption({ label: "Retrait d'épargne" });
  expect(await overflow(page)).toBeLessThanOrEqual(1);
  await page.screenshot({ path: `${CAP}/b301-${info.project.name}-1b-modal.png`, fullPage: true });
  void modal;
  await page.getByRole('button', { name: /confirmer le versement/i }).click();
  await recuOuvert(page);
  await expect(page.locator('tr', { hasText: 'VERSEMENT DU JOUR' })).toContainText(/[-−]\s?4\s?000/);
  await expect(page.locator('tr', { hasText: /NOUVELLE/ }).first()).toContainText(/[-−]\s?6\s?000/);
  await page.screenshot({ path: `${CAP}/b301-${info.project.name}-1b-recu.png`, fullPage: true });
  expect(await overflow(page)).toBeLessThanOrEqual(1);
  // coherence serveur : BP = -10000 + 0 - (-4000) = -6000
  const tok = await apiToken(request, 'zz_e301_gerant');
  const r = await request.get(`${API}/api/clients/clients/?search=Epargne${s}`, { headers: { Authorization: `Bearer ${tok}` } });
  const j = await r.json();
  const c = (Array.isArray(j) ? j : j.results).find((x: { last_name: string }) => x.last_name === `Epargne${s}`);
  expect(Math.round(parseFloat(c.current_debt))).toBe(-6000);
});

test('(1c) facturier : blocage au plafond, message affiche (vente puis versement negatif)', async ({ page }, info) => {
  test.setTimeout(240_000);
  const s = SUF[idx(info.project.name)];
  await login(page, 'zz_e301_fact');
  await later(page);
  await page.goto('/sales/create', { waitUntil: 'domcontentloaded' });
  await choisir(page, `Plafond${s}`);
  await page.locator('input[type="number"]').nth(2).fill('1');
  await page.getByLabel(/Versement du jour/i).fill('0');
  await page.getByRole('button', { name: /facturer & mettre en attente/i }).click();
  const msg = page.getByText(/plafond|bloqu/i).first();
  await expect(msg).toBeVisible({ timeout: 30_000 });
  info.annotations.push({ type: 'message-blocage-vente', description: (await msg.innerText()).slice(0, 300) });
  await page.screenshot({ path: `${CAP}/b301-${info.project.name}-1c-blocage.png`, fullPage: true });
  expect(await overflow(page)).toBeLessThanOrEqual(1);
  // versement sans commande negatif sur le meme client : 403 affiche dans la modale
  await page.getByRole('button', { name: /Remboursement \/ Dépôt sans commande/ }).click();
  await page.getByPlaceholder('Ex: 10000 ou -5000').fill('-1000');
  await page.getByRole('button', { name: /confirmer le versement/i }).click();
  const m2 = page.getByText(/plafond|bloqu/i).last();
  await expect(m2).toBeVisible({ timeout: 30_000 });
  info.annotations.push({ type: 'message-blocage-versement', description: (await m2.innerText()).slice(0, 300) });
  await page.screenshot({ path: `${CAP}/b301-${info.project.name}-1c-blocage-versement.png`, fullPage: true });
  expect(await overflow(page)).toBeLessThanOrEqual(1);
});

async function preparerCommission(request: APIRequestContext, s: string) {
  const tf = await apiToken(request, 'zz_e301_fact');
  const HF = { Authorization: `Bearer ${tf}` };
  const cl = await (await request.get(`${API}/api/clients/clients/?search=Credit${s}`, { headers: HF })).json();
  const client = (Array.isArray(cl) ? cl : cl.results).find((x: { last_name: string }) => x.last_name === `Credit${s}`);
  const prix = await (await request.get(`${API}/api/core/bread-prices/`, { headers: HF })).json();
  const p500 = (Array.isArray(prix) ? prix : prix.results).find((p: { unit_price: number }) => p.unit_price === 500).id;
  const inv = await request.post(`${API}/api/sales/invoices/`, {
    headers: HF, data: { client: client.id, payment_type: 'CASH', payment_amount: '10000', lines: [{ bread_price: p500, quantity: 20 }] },
  });
  expect(inv.ok(), await inv.text()).toBeTruthy();
  const id = (await inv.json()).id;
  const dl = await request.post(`${API}/api/sales/invoices/${id}/deliver/`, { headers: HF });
  expect(dl.ok(), await dl.text()).toBeTruthy();
  const td = await apiToken(request, 'zz_e301_dir');
  const HD = { Authorization: `Bearer ${td}` };
  const nodes = await (await request.get(`${API}/api/core/nodes/`, { headers: HD })).json();
  const b2 = (Array.isArray(nodes) ? nodes : nodes.results).find((n: { code: string }) => n.code === 'B2');
  const d = new Date();
  const g = await request.post(`${API}/api/commissions/periods/generate/`, {
    headers: HD, data: { node: b2.id, month: d.getMonth() + 1, year: d.getFullYear() },
  });
  expect(g.ok(), await g.text()).toBeTruthy();
}

async function verifCommissions(page: Page, s: string, info: { project: { name: string } }, direction: boolean) {
  await page.goto('/commissions', { waitUntil: 'domcontentloaded' });
  await later(page);
  await expect(page.getByRole('heading', { name: /Commissions des Revendeurs/ })).toBeVisible({ timeout: 60_000 });
  if (direction) {
    const filtre = page.locator('select').filter({ has: page.locator('option', { hasText: 'Toutes les boulangeries' }) });
    await filtre.selectOption({ label: (await filtre.locator('option', { hasText: 'B2' }).first().innerText()).trim() });
  }
  await page.getByPlaceholder('Rechercher un client...').fill(`Credit${s}`);
  const row = page.locator('tbody tr', { hasText: `Credit${s}` }).first();
  await expect(row).toBeVisible({ timeout: 60_000 });
  await expect(page.locator('thead th', { hasText: /CARTE/i })).toHaveCount(0);
  await expect(page.locator('thead th', { hasText: /NET\/ORDI/ })).toHaveCount(1);
  expect(await overflow(page)).toBeLessThanOrEqual(1);
  await page.screenshot({ path: `${CAP}/b301-${info.project.name}-2-${direction ? 'dir' : 'gerant'}-liste.png`, fullPage: true });
  await row.click();
  await expect(page.getByText(/Fiche de Paie CM/)).toBeVisible();
  await expect(page.getByText('(+) Crédit client (BP créditrice)')).toBeVisible();
  await expect(page.locator('div', { hasText: /^\(\+\) Crédit client/ }).last()).toContainText(/\+1\s?500 FC/);
  await expect(page.getByText(/Remise \(0,25 % de la commande, non déduite\)/)).toBeVisible();
  await expect(page.getByText(/\bcarte\b/i)).toHaveCount(0);
  await page.screenshot({ path: `${CAP}/b301-${info.project.name}-2-${direction ? 'dir' : 'gerant'}-fiche.png`, fullPage: true });
  expect(await overflow(page)).toBeLessThanOrEqual(1);
}

test('(2a) gerant : Commissions refusees (BUG-253, route reservee ADMIN/DIRECTION/COMPTABLE)', async ({ page }) => {
  test.setTimeout(120_000);
  await login(page, 'zz_e301_gerant');
  await later(page);
  await page.goto('/commissions', { waitUntil: 'domcontentloaded' });
  await expect(page.getByText('Accès refusé')).toBeVisible({ timeout: 30_000 });
  expect(await overflow(page)).toBeLessThanOrEqual(1);
});

test('(2b) direction : Commissions sans CARTE, credit client, remise, export CSV sans CARTE', async ({ page, request }, info) => {
  test.setTimeout(300_000);
  const s = SUF[idx(info.project.name)];
  await preparerCommission(request, s);
  await login(page, 'zz_e301_dir');
  await later(page);
  await verifCommissions(page, s, info, true);
  await page.keyboard.press('Escape');
  const btn = page.getByRole('button', { name: /^Excel$/ });
  if (await btn.isEnabled().catch(() => false)) {
    const [dl] = await Promise.all([page.waitForEvent('download'), btn.click()]);
    const fs = await import('fs');
    const txt = fs.readFileSync(await dl.path(), 'utf-8');
    expect(txt).not.toMatch(/CARTE/i);
    expect(txt).toMatch(/NET\/ORDI/);
  }
});

test('(3a) gerant : Clients, cotisation facultative et valeur effective', async ({ page }, info) => {
  test.setTimeout(300_000);
  const s = SUF[idx(info.project.name)];
  await login(page, 'zz_e301_gerant');
  await later(page);
  await page.goto('/clients', { waitUntil: 'domcontentloaded' });
  await later(page);
  for (const [nom, cot, attendu] of [[`ZZE301 CotDefaut${s}`, '', /2\s?000 FC\/mois/], [`ZZE301 CotPropre${s}`, '500', /500 FC\/mois/]] as const) {
    const recherche = page.getByPlaceholder('Rechercher par nom, commerce ou ID...');
    const row = page.locator('tbody tr', { hasText: nom.split(' ')[1] }).first();
    await recherche.fill(nom.split(' ')[1]);
    await page.waitForTimeout(1500); // reponse de la recherche (debounce)
    if (await row.count() === 0) {
      await page.getByRole('button', { name: /Nouvelle vente/ }).click();
      await page.getByRole('button', { name: /Nouveau client/ }).click();
      await page.getByPlaceholder('Ex: Dieudonné Kabeya').fill(nom);
      const champ = page.locator('xpath=//label[contains(.,"Cotisation Sociale")]/following::input[1]');
      await expect(champ).toBeVisible();
      await page.screenshot({ path: `${CAP}/b301-${info.project.name}-3a-form-${cot || 'vide'}.png`, fullPage: true });
      if (cot) await champ.fill(cot);
      await page.getByRole('button', { name: /Enregistrer l'Abonné/ }).click();
      await expect(page.getByRole('button', { name: /Enregistrer l'Abonné/ })).toHaveCount(0, { timeout: 30_000 });
      await recherche.fill('');
      await recherche.fill(nom.split(' ')[1]);
    }
    await expect(row).toBeVisible({ timeout: 30_000 });
    await expect(async () => {
      await row.getByTitle('Voir la fiche détaillée').click({ timeout: 3_000 });
      await expect(page.getByText(/Cotisation sociale :/)).toBeVisible({ timeout: 3_000 });
    }).toPass({ timeout: 30_000 });
    await expect(page.getByText(/Cotisation sociale :/)).toContainText(attendu);
    await page.screenshot({ path: `${CAP}/b301-${info.project.name}-3a-fiche-${cot || 'vide'}.png`, fullPage: true });
    expect(await overflow(page)).toBeLessThanOrEqual(1);
    await page.keyboard.press('Escape');
    await page.reload({ waitUntil: 'domcontentloaded' });
    await later(page);
  }
});

test('(3b) direction : Nodes cotisation par boulangerie, caisse sociale tarif et Recalculer', async ({ page }, info) => {
  test.setTimeout(300_000);
  await login(page, 'zz_e301_dir');
  await later(page);
  await page.goto('/admin/nodes', { waitUntil: 'domcontentloaded' });
  await later(page);
  const b2 = page.getByRole('row', { name: /^B2 MPETE/ });
  await expect(b2).toBeVisible({ timeout: 60_000 });
  await b2.getByTitle('Modifier la succursale').click();
  const champ = page.locator('xpath=//label[contains(.,"Cotisation sociale mensuelle")]/following::input[1]');
  await expect(champ).toBeVisible();
  await expect(champ).toHaveValue(/^2000(\.00)?$/);
  await page.screenshot({ path: `${CAP}/b301-${info.project.name}-3b-node.png`, fullPage: true });
  expect(await overflow(page)).toBeLessThanOrEqual(1);
  await page.keyboard.press('Escape');

  await page.goto('/clients', { waitUntil: 'domcontentloaded' });
  await later(page);
  await expect(page.getByText(/§6 — Caisse Sociale/)).toBeVisible({ timeout: 60_000 });
  const sel = page.locator('xpath=(//label[normalize-space(.)="Succursale"])[last()]/following::select[1]');
  await sel.selectOption({ label: (await sel.locator('option', { hasText: 'B2' }).first().innerText()).trim() });
  await page.getByRole('button', { name: /Distribution Annuelle/ }).click();
  const creer = page.getByRole('button', { name: /Nouvelle distribution/ });
  await expect(creer).toBeVisible({ timeout: 30_000 });
  if (await page.getByText(/^Distribution \d{4}$/).count() === 0) await creer.click();
  await expect(page.getByText(/^Distribution \d{4}$/).first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/INDICE × TARIF \+ MÉRITE/).first()).toBeVisible();
  await expect(page.getByText(/Tarif \(FC\/indice\)/).first()).toBeVisible();
  await expect(page.getByText(/0,025/)).toHaveCount(0);
  await page.getByRole('button', { name: /Recalculer les indices/ }).first().click();
  await expect(page.getByText(/ligne\(s\) recalculée\(s\)/)).toBeVisible({ timeout: 30_000 });
  await page.screenshot({ path: `${CAP}/b301-${info.project.name}-3b-caisse.png`, fullPage: true });
  expect(await overflow(page)).toBeLessThanOrEqual(1);
});

test('(4) menu facturier sans debordement', async ({ page }, info) => {
  await login(page, 'zz_e301_fact');
  await later(page);
  await menuMobile(page);
  expect(await overflow(page)).toBeLessThanOrEqual(1);
  await page.screenshot({ path: `${CAP}/b301-${info.project.name}-4-menu.png` });
});
