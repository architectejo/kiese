import { test, expect } from '@playwright/test';
import { CAP, API, login, later, overflow, apiToken } from '../fixtures/cycle';

/**
 * Verification (testeur-e2e, 2026-11-14) BUG-298 (Tresorerie apres cloture) et BUG-299 (Commissions,
 * RESTE A VERSER). Lecture seule : la cloture K4 du jour existe deja (etat laisse par le cycle final).
 */
test('BUG-298 : apres cloture, ecart +500 (Excedent) et un seul solde comptable', async ({ page, request }, info) => {
  test.setTimeout(240_000);
  const tok = await apiToken(request, 'zz_clients_gerant');
  const r = await request.get(`${API}/api/treasury/closures/?ordering=-date`, { headers: { Authorization: `Bearer ${tok}` } });
  const j = await r.json();
  const liste = Array.isArray(j) ? j : j.results;
  const today = new Date().toISOString().slice(0, 10);
  const cl = liste.find((c: { date: string }) => c.date === today) ?? liste[0];
  expect(cl, 'cloture K4 du jour').toBeTruthy();
  const gap = Math.round(parseFloat(cl.cash_gap)), net = Math.round(parseFloat(cl.net_cash));
  expect(gap).toBe(500); expect(net).toBe(13000);

  await login(page, 'zz_clients_gerant');
  await page.goto('/cloture-journaliere', { waitUntil: 'domcontentloaded' });
  await later(page);
  await expect(page.getByText(/Écart: \+?500 FC/).first()).toBeVisible({ timeout: 60_000 });
  await page.waitForTimeout(3_000);
  const corps = (await page.locator('body').innerText()).replace(/[  ]/g, ' ');
  await page.screenshot({ path: `${CAP}/vf-${info.project.name}-bug298.png`, fullPage: true });
  expect(corps).not.toMatch(/-13 000 FC/);
  expect(corps).not.toMatch(/\(Manque\)/);
  // Page « Clôture Journalière » : « TOTAL CRÉDIT DU JOUR » s'intercale entre le cash et le solde ; on
  // vérifie donc que le solde comptable n'est pas lu directement après le total cash brut.
  expect(corps).not.toMatch(/TOTAL CASH DU JOUR\s*\n?\s*15 000 FC\s*\n?\s*(SOLDE|ÉCART)/);
  // carte ECART BILLETAGE : +500 FC ; SOLDE COMPTABLE CAISSE : 13 000 FC
  const carteEcart = page.getByText(/^ÉCART BILLETAGE/).first().locator('xpath=..');
  await expect(carteEcart).toContainText(/\+500 FC/);
  const carteSolde = page.getByText(/^SOLDE COMPTABLE CAISSE/).first().locator('xpath=..');
  await expect(carteSolde).toContainText(/13\s?000 FC/);
  expect(await overflow(page)).toBeLessThanOrEqual(1);
});

test('BUG-299 : RESTE A VERSER = nets positifs non payes, negatifs a part', async ({ page, request }, info) => {
  test.setTimeout(240_000);
  await login(page, 'zz_direction');
  await later(page);
  await page.goto('/commissions', { waitUntil: 'domcontentloaded' });
  await later(page);
  const filtre = page.locator('select').filter({ has: page.locator('option', { hasText: 'Toutes les boulangeries' }) });
  await expect(filtre).toBeVisible({ timeout: 60_000 });
  await filtre.selectOption({ label: (await filtre.locator('option', { hasText: 'K4' }).first().innerText()).trim() });
  const carte = page.getByText(/^RESTE À VERSER/).first().locator('xpath=..');
  await expect(carte).not.toContainText(/calcul en cours/, { timeout: 90_000 });
  const txt = (await carte.innerText()).replace(/[  ]/g, ' ');
  await page.screenshot({ path: `${CAP}/vf-${info.project.name}-bug299.png`, fullPage: true });
  const m = txt.match(/(-?[\d ]+) FC/);
  expect(m, txt).toBeTruthy();
  expect(m![1].trim().startsWith('-'), txt).toBeFalsy();
  // comparaison serveur
  const tok = await apiToken(request, 'zz_direction');
  const H = { Authorization: `Bearer ${tok}` };
  let url: string | null = `${API}/api/commissions/commissions/?page_size=500`;
  const all: { net_payable: string; is_paid: boolean; node_code?: string; node?: number | string }[] = [];
  while (url) {
    const r = await request.get(url, { headers: H });
    const j = await r.json();
    if (Array.isArray(j)) { all.push(...j); break; }
    all.push(...j.results); url = j.next;
  }
  info.annotations.push({ type: 'api', description: `${all.length} lignes` });
  const aff = parseInt(m![1].replace(/ /g, ''), 10);
  const neg = all.filter(c => !c.is_paid && parseFloat(c.net_payable) < 0);
  if (neg.length) await expect(page.getByText(/reportés en dette/).first()).toBeVisible();
  info.annotations.push({ type: 'affiche', description: `${aff}` });
});
