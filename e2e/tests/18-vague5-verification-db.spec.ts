import { test, expect, Page } from '@playwright/test';

/**
 * Vague 5 (testeur-e2e, 2026-11-12) - rejeu UI sur db.sqlite3 des tickets CORRIGE.
 * Comptes zz_* uniquement (autorisation de l'utilisateur pour ce rejeu). Lecture seule :
 * aucune facture, aucun versement, aucune ecriture en base.
 * BUG-242 (garde de route /treasury), BUG-274 (file de livraisons, facture PENDING retro-datee),
 * BUG-276 (message francais de billetage), BUG-281 (libelle equipe de la periode),
 * BUG-282 (vitrine sans debordement, 320/360/768/1440).
 * Lancer : npx playwright test tests/18-vague5-verification-db.spec.ts --project=pos --project=bureau --output=<dossier perso>
 */
const CAP = '../docs/qa/captures';
const API = process.env.E2E_API_URL || 'http://localhost:8000';

async function seConnecter(page: Page, user: string) {
  await page.goto('/login', { waitUntil: 'domcontentloaded', timeout: 240_000 });
  await page.getByPlaceholder('Ex: pierre').fill(user, { timeout: 60_000 });
  await page.getByPlaceholder('••••••••').fill(user);
  await page.getByRole('button', { name: /se connecter/i }).click();
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 120_000 });
}
async function reporterModale(page: Page) {
  const plusTard = page.getByRole('button', { name: /plus tard/i });
  await plusTard.waitFor({ state: 'visible', timeout: 8_000 }).then(() => plusTard.click()).catch(() => undefined);
}
async function ecart(page: Page) {
  return page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
}

test('BUG-282 : vitrine sans debordement a 320/360/768/1440', async ({ page, request }, info) => {
  test.setTimeout(240_000);
  const cfg = await request.get(`${API}/api/core/config/`, { timeout: 120_000 });
  const onLine = (await cfg.json()).on_line as boolean;
  test.skip(!onLine, 'on_line = False : la racine redirige vers /login (pas de vitrine)');
  await page.goto('/', { waitUntil: 'domcontentloaded', timeout: 150_000 });
  await expect(page.locator('body')).toContainText(/KIESE/i, { timeout: 120_000 });
  for (const w of [320, 360, 768, 1440]) {
    await page.setViewportSize({ width: w, height: 800 });
    await page.waitForTimeout(300);
    const e = await ecart(page);
    await page.screenshot({ path: `${CAP}/vague5-vitrine-${w}.png` });
    info.annotations.push({ type: `ecart-${w}`, description: String(e) });
    expect(e, `ecart a ${w}px`).toBe(0);
  }
});

test('BUG-242 : /treasury refuse au facturier et au livreur, ouvert au gerant', async ({ page }) => {
  test.setTimeout(600_000);
  for (const u of ['zz_treso_facturier_a', 'zz_treso_livreur']) {
    await page.context().clearCookies();
    await page.goto('/login', { waitUntil: 'domcontentloaded', timeout: 240_000 });
    await page.evaluate(() => localStorage.clear());
    const appels: string[] = [];
    page.on('request', r => { if (r.url().includes('/api/treasury/')) appels.push(r.url()); });
    await seConnecter(page, u);
    await reporterModale(page);
    await page.goto('/treasury', { waitUntil: 'domcontentloaded', timeout: 240_000 });
    await expect(page.getByText('Accès refusé')).toBeVisible({ timeout: 60_000 });
    expect(appels, `appels /api/treasury/ pour ${u}`).toHaveLength(0);
    expect(await ecart(page)).toBeLessThanOrEqual(1);
    page.removeAllListeners('request');
  }
  await page.goto('/login');
  await page.evaluate(() => localStorage.clear());
  await seConnecter(page, 'zz_clients_gerant');
  await reporterModale(page);
  await page.goto('/treasury', { waitUntil: 'domcontentloaded', timeout: 240_000 });
  await expect(page.getByText('Accès refusé')).toHaveCount(0);
  await expect(page.getByText(/Saisir le nombre de coupures/)).toBeVisible({ timeout: 90_000 });
  expect(await ecart(page)).toBeLessThanOrEqual(1);
});

test('BUG-276 : billetage hors borne -> message francais, aucune requete POST', async ({ page }) => {
  test.setTimeout(600_000);
  await seConnecter(page, 'zz_clients_gerant');
  await reporterModale(page);
  await page.goto('/treasury', { waitUntil: 'domcontentloaded', timeout: 240_000 });
  await expect(page.getByText(/Saisir le nombre de coupures/)).toBeVisible({ timeout: 90_000 });
  // la modale « Stock de depart » peut arriver tardivement : la reporter tant qu'elle est la
  const plusTard = page.getByRole('button', { name: /plus tard/i });
  await plusTard.waitFor({ state: 'visible', timeout: 25_000 }).then(() => plusTard.click()).catch(() => undefined);
  await expect(page.locator('.modal-backdrop')).toHaveCount(0, { timeout: 15_000 });
  const posts: string[] = [];
  page.on('request', r => { if (r.method() === 'POST' && r.url().includes('/api/treasury/closures')) posts.push(r.url()); });
  const form = page.locator('form[novalidate]').filter({ hasText: /Valeur Faciale/ });
  const champ = form.locator('input[type="number"]').first();
  const valider = form.locator('button[type="submit"]').first();
  for (const v of ['100001', '-3', '2.5']) {
    await champ.fill(v);
    await valider.click();
    // espaces insecables fines (toLocaleString fr-FR) : \s les couvre
    await expect(form.getByText(/^Coupure 20\s000 FC : entier entre 0 et 100\s000 billets\.$/)).toBeVisible({ timeout: 10_000 });
  }
  expect(posts, 'aucune requete POST de cloture').toHaveLength(0);
  expect(await ecart(page)).toBeLessThanOrEqual(1);
  await page.screenshot({ path: `${CAP}/vague5-billetage-${test.info().project.name}.png` });
});

test('BUG-283 (UI de BUG-274) : la file de livraisons de l ecran affiche les PENDING retro-datees (K4, facturier)', async ({ page }) => {
  test.setTimeout(600_000);
  const appels: string[] = [];
  page.on('request', r => { if (r.url().includes('/api/sales/invoices/')) appels.push(r.url()); });
  await seConnecter(page, 'zz_clients_facturier');
  await reporterModale(page);
  await page.goto('/sales', { waitUntil: 'domcontentloaded', timeout: 240_000 });
  await expect(page.getByText(/File des Livraisons/)).toBeVisible({ timeout: 90_000 });
  await expect(page.getByText(/factures chargées/)).toHaveCount(0, { timeout: 120_000 });
  // 1) contrat backend : la liste API contient des PENDING datees hors du jour courant
  const api = await page.evaluate(async (base) => {
    const t = localStorage.getItem('kiese_access_token');
    const r = await fetch(`${base}/api/sales/invoices/pending_deliveries/`, { headers: { Authorization: `Bearer ${t}` } });
    const j = await r.json();
    const l = Array.isArray(j) ? j : j.results ?? [];
    return { status: r.status, items: l.map((i: { receipt_number?: string; invoice_date: string }) => ({ n: i.receipt_number ?? '', d: i.invoice_date })) };
  }, API);
  const aujourdhui = new Date().toLocaleDateString('en-CA');
  const retro = api.items.filter(i => i.d !== aujourdhui);
  test.info().annotations.push({ type: 'api', description: `HTTP ${api.status}, ${api.items.length} PENDING dont ${retro.length} hors jour courant` });
  expect(api.status).toBe(200);
  expect(retro.length, 'API : PENDING retro-datee listee').toBeGreaterThan(0);
  // 2) l'ecran doit exposer ces memes factures dans la file
  test.info().annotations.push({ type: 'ecran', description: `appels : ${appels.map(a => a.replace(/^.*\/api\//, '')).join(' | ')}` });
  const recu = retro[0].n;
  await reporterModale(page);
  const voirPlus = page.getByRole('button', { name: /voir plus/i });
  if (await voirPlus.isVisible().catch(() => false)) await voirPlus.click();
  if (recu) await expect(page.locator('body'), `l'ecran liste ${recu}`).toContainText(recu, { timeout: 10_000 });
  await page.screenshot({ path: `${CAP}/vague5-livraisons-${test.info().project.name}.png` });
});

test('BUG-281 : libelle « Equipe de service de la periode » (necessite un gerant de boulangerie en rotation, K3)', async ({ page }) => {
  test.setTimeout(600_000);
  await seConnecter(page, 'zz_clients_gerant');
  const titre = page.getByText(/Stock de départ de la relève/);
  const visible = await titre.waitFor({ state: 'visible', timeout: 30_000 }).then(() => true).catch(() => false);
  test.skip(!visible, 'La modale « Stock de depart de la releve » n\'apparait pas (deja confirmee) : non verifiable en UI');
  await expect(page.getByText(/Équipe de service de la période : [AB]/)).toBeVisible();
  await expect(page.getByText(/Équipe de service du jour/)).toHaveCount(0);
  await page.screenshot({ path: `${CAP}/vague5-stock-releve-${test.info().project.name}.png` });
});
