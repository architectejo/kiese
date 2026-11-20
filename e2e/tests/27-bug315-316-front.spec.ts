import { test, expect, Page } from '@playwright/test';
import { CAP, API, login, later, overflow, idx, apiToken } from '../fixtures/cycle';

/**
 * Verification (testeur-e2e, 2026-11-20) : BUG-315 (historique des fournees rafraichi sans rechargement)
 * et BUG-316 volet frontend (TARIF de la caisse sociale en lecture seule hors direction/admin).
 * Equipes non consommees le 2026-11-20 : pos -> K6 A, tablette -> K3 B (reprise), bureau -> B2 A (reprise).
 * Distribution sociale existante : B2 / 2026 (tarif 700, ouverte). Donnees fictives uniquement.
 * Etat des donnees : les reprises (tablette K3 B, bureau B2 A) ne sont rejouables que sur une base neuve (fournees deja cloturees le 2026-11-20).
 */
test.describe.configure({ mode: 'serial' });
test.beforeEach(({}, info) => { test.skip(info.project.name === 'tv', 'largeurs demandees : 360, 768, 1440'); });

const GERANT = ['zz_e307_ger6', 'zz_prod_gerant_k3', 'zz_e301_gerant'];
const EQUIPE = ['A', 'B', 'A'];
// Equipes non consommees : une premiere passe a deja declare K3 B (tablette) et B2 A (bureau) ; on reprend a l'etape 2.
const REPRISE = [false, true, true];

test('BUG-315 : historique rafraichi apres declaration, modification des sacs et cloture (sans reload)', async ({ page, request }, info) => {
  test.setTimeout(240_000);
  const i = idx(info.project.name);
  const eq = EQUIPE[i];
  const tk = await apiToken(request, GERANT[i]);
  const ouvertes = await (await request.get(`${API}/api/production/sessions/?is_closed=false&page_size=50`, { headers: { Authorization: `Bearer ${tk}` } })).json();
  expect((ouvertes.results ?? ouvertes).length, 'etat de depart').toBe(REPRISE[i] ? 1 : 0);

  await login(page, GERANT[i]);
  await later(page);
  await page.goto('/production', { waitUntil: 'domcontentloaded' });
  await later(page);
  const panneau = page.getByTestId('batch-in-progress-panel');
  const historique = page.locator('div.glass-card').filter({ has: page.getByRole('heading', { name: /Historique des Fournées/ }) });
  const ligne = historique.locator('div').filter({ hasText: new RegExp(`Éq\.${eq}`) }).filter({ hasText: /sacs/ }).last();
  await expect(historique).toBeVisible({ timeout: 60_000 });
  await expect(historique.getByText('Chargement...')).toHaveCount(0, { timeout: 60_000 });

  if (REPRISE[i]) {
    await expect(panneau.getByTestId('batch-objective')).toBeVisible({ timeout: 60_000 });
    await expect(ligne).toBeVisible();
  } else {
    await expect(panneau.getByText('Déclaration de Fournée')).toBeVisible({ timeout: 60_000 });
    await expect(historique.getByText(new RegExp(`Éq\.${eq}`))).toHaveCount(0);
    const select = panneau.getByLabel('Équipe', { exact: true });
    if (await select.count()) await select.selectOption(eq);
    await panneau.getByLabel(/Nombre de sacs de farine/).fill('1');
    const t0 = Date.now();
    await panneau.getByRole('button', { name: /enregistrer la fournée/i }).click();
    await expect(panneau.getByTestId('batch-objective')).toBeVisible({ timeout: 30_000 });
    // 1) declaration : la ligne apparait sans reload
    await expect(historique.getByText(new RegExp(`Éq\.${eq}`))).toBeVisible({ timeout: 30_000 });
    console.log(`DELAI ${info.project.name} declaration -> ligne historique : ${Date.now() - t0} ms`);
    await expect(ligne).toContainText(/\b1(\.00)? sacs/);
    await page.screenshot({ path: `${CAP}/b315-${info.project.name}-1-declaration.png`, fullPage: true });
  }

  // 2) modification des sacs
  const t1 = Date.now();
  await panneau.getByLabel(/Augmenter les sacs/).fill('2');
  await panneau.getByRole('button', { name: /mettre à jour les sacs/i }).click();
  await expect(ligne).toContainText(/\b2(\.00)? sacs/, { timeout: 30_000 });
  console.log(`DELAI ${info.project.name} sacs -> historique : ${Date.now() - t1} ms`);
  await page.screenshot({ path: `${CAP}/b315-${info.project.name}-2-sacs.png`, fullPage: true });

  // 3) cloture
  const t2 = Date.now();
  await historique.getByText(new RegExp(`Éq\.${eq}`)).first().click();
  const detail = page.getByRole('dialog', { name: 'Détail Fournée' });
  await expect(detail).toBeVisible({ timeout: 10_000 });
  await detail.getByRole('button', { name: 'Clôturer la fournée' }).click();
  const m = page.getByRole('dialog', { name: 'Clôturer la Fournée' });
  await expect(m).toBeVisible();
  await m.getByRole('button', { name: 'Confirmer la clôture' }).click();
  await expect(m).toBeHidden({ timeout: 20_000 });
  await expect(ligne).toContainText(/Clôturée/i, { timeout: 30_000 });
  console.log(`DELAI ${info.project.name} cloture -> historique : ${Date.now() - t2} ms`);
  await page.screenshot({ path: `${CAP}/b315-${info.project.name}-3-cloture.png`, fullPage: true });
  expect(await overflow(page)).toBeLessThanOrEqual(1);
});

async function ouvrirDistribution(page: Page, user: string, choisirB2: boolean) {
  await login(page, user);
  await later(page);
  await page.goto('/clients', { waitUntil: 'domcontentloaded' });
  await later(page);
  await expect(page.getByText(/§6 — Caisse Sociale/)).toBeVisible({ timeout: 60_000 });
  if (choisirB2) {
    const sel = page.locator('xpath=(//label[normalize-space(.)="Succursale"])[last()]/following::select[1]');
    await sel.selectOption({ label: (await sel.locator('option', { hasText: 'B2' }).first().innerText()).trim() });
  }
  await page.getByRole('button', { name: /Distribution Annuelle/ }).click();
  await expect(page.getByText(/^Distribution 2026$/)).toBeVisible({ timeout: 30_000 });
}

test('BUG-316 front : gerant B2 voit le TARIF en lecture seule (sans input ni OK) ; l API refuse (403)', async ({ page, request }, info) => {
  test.setTimeout(240_000);
  await ouvrirDistribution(page, 'zz_e301_gerant', false);
  const bloc = page.locator('label').filter({ hasText: /Tarif \(FC\/indice\)/ });
  await expect(bloc).toBeVisible();
  await expect(bloc.locator('strong')).toContainText(/700/);
  await expect(bloc.locator('input')).toHaveCount(0);
  await expect(bloc.getByRole('button', { name: 'OK' })).toHaveCount(0);
  await expect(page.getByRole('spinbutton')).toHaveCount(0); // aucun champ numerique de tarif dans le panneau
  await page.screenshot({ path: `${CAP}/b316-${info.project.name}-gerant.png`, fullPage: true });
  expect(await overflow(page)).toBeLessThanOrEqual(1);

  // backend (correctif BUG-316) : 403 sur le tarif pour le gerant
  const tk = await apiToken(request, 'zz_e301_gerant');
  const lst = await (await request.get(`${API}/api/clients/distributions/`, { headers: { Authorization: `Bearer ${tk}` } })).json();
  const id = (lst.results ?? lst)[0].id;
  const r = await request.patch(`${API}/api/clients/distributions/${id}/`, { headers: { Authorization: `Bearer ${tk}` }, data: { tarif: '99999' } });
  expect(r.status()).toBe(403);
  expect((await r.json()).detail).toMatch(/réservés à la direction/);
});

for (const [user, libelle] of [['zz_direction', 'direction'], ['zz_demo_admin', 'admin']] as const) {
  test(`BUG-316 front : ${libelle} voit input + OK et enregistre le tarif`, async ({ page, request }, info) => {
    test.setTimeout(240_000);
    await ouvrirDistribution(page, user, true);
    const bloc = page.locator('label').filter({ hasText: /Tarif \(FC\/indice\)/ });
    const champ = bloc.locator('input');
    await expect(champ).toBeVisible();
    await expect(bloc.getByRole('button', { name: 'OK' })).toBeVisible();
    await page.screenshot({ path: `${CAP}/b316-${info.project.name}-${libelle}.png`, fullPage: true });
    expect(await overflow(page)).toBeLessThanOrEqual(1);
    try {
      await champ.fill('710');
      await bloc.getByRole('button', { name: 'OK' }).click();
      await expect(page.getByText('Tarif enregistré, remises recalculées.')).toBeVisible({ timeout: 20_000 });
      await expect(page.getByText(/^Distribution 2026$/)).toBeVisible();
      const tk = await apiToken(request, user);
      const lst = await (await request.get(`${API}/api/clients/distributions/?year=2026`, { headers: { Authorization: `Bearer ${tk}` } })).json();
      const d = (lst.results ?? lst).find((x: { node: number }) => x.node === 2);
      expect(parseFloat(d.tarif)).toBe(710);
    } finally {
      // restauration du tarif initial (700) par l'API
      const tk = await apiToken(request, 'zz_direction');
      const lst = await (await request.get(`${API}/api/clients/distributions/?year=2026`, { headers: { Authorization: `Bearer ${tk}` } })).json();
      const d = (lst.results ?? lst).find((x: { node: number }) => x.node === 2);
      if (d) await request.patch(`${API}/api/clients/distributions/${d.id}/`, { headers: { Authorization: `Bearer ${tk}` }, data: { tarif: '700' } });
    }
  });
}
