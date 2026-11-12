import { test, expect, Page } from '@playwright/test';
import * as fs from 'fs';
import * as path from 'path';

/**
 * Vague 2 (testeur-production, 2026-11-12) — VRAIE base, boulangerie K2 uniquement.
 * Comptes : @gerant-k2 (gérant récepteur), @pierre (direction). Aucun client réel touché.
 * Lancer : npx playwright test tests/13-production-vague2-db.spec.ts --project=pos --project=bureau
 */
async function seConnecter(page: Page, username: string, password: string) {
  // Modale « Stock de départ du jour » : apparaît tardivement et intercepte les clics -> fermée dès qu'elle apparaît.
  await page.addLocatorHandler(page.getByRole('button', { name: /plus tard/i }), async (btn) => { await btn.click(); });
  await page.goto('/login', { waitUntil: 'domcontentloaded', timeout: 180_000 });
  await page.getByPlaceholder('Ex: pierre').fill(username, { timeout: 120_000 });
  await page.getByPlaceholder('••••••••').fill(password);
  await page.getByRole('button', { name: /se connecter/i }).click();
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 150_000 });
}
async function fermerModalesDepart(page: Page) {
  const plusTard = page.getByRole('button', { name: /plus tard/i });
  await plusTard.waitFor({ state: 'visible', timeout: 8_000 }).then(() => plusTard.click()).catch(() => undefined);
}
async function sansDebordement(page: Page, ou: string) {
  const ecart = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(ecart, `débordement horizontal (${ou})`).toBeLessThanOrEqual(1);
}

test('gérant K2 : onglets Production sans débordement, litige visible, recomptage seulement', async ({ page }, info) => {
  test.setTimeout(600_000);
  await seConnecter(page, '@gerant-k2', '@gerant-k2');
  await page.goto('/production', { waitUntil: 'domcontentloaded', timeout: 180_000 });
  await fermerModalesDepart(page);
  await expect(page.getByText(/Déclaration de Fournée/)).toBeVisible({ timeout: 120_000 });
  await sansDebordement(page, 'fournées');
  await page.screenshot({ path: `../docs/qa/captures/prod-v2-${info.project.name}-fournees.png`, fullPage: true });
  await page.getByRole('button', { name: /Intrants/ }).click();
  await expect(page.getByText(/Stocks? Consommables/i).first()).toBeVisible({ timeout: 90_000 });
  await sansDebordement(page, 'intrants');
  await page.screenshot({ path: `../docs/qa/captures/prod-v2-${info.project.name}-intrants.png`, fullPage: true });
  await page.getByRole('button', { name: /Transferts/ }).click();
  await expect(page.getByText(/Transferts Inter-Boulangeries/)).toBeVisible({ timeout: 90_000 });
  await expect(page.getByText(/EN LITIGE/).first()).toBeVisible({ timeout: 90_000 });
  await expect(page.getByText(/Clôture de caisse bloquée/i).first()).toBeVisible();
  await expect(page.getByRole('button', { name: /Recompter la réception/i }).first()).toBeVisible();
  await expect(page.getByRole('button', { name: /Résoudre le litige/i })).toHaveCount(0);
  await sansDebordement(page, 'transferts');
  await page.screenshot({ path: `../docs/qa/captures/prod-v2-${info.project.name}-transferts-recepteur.png`, fullPage: true });
  await page.getByRole('button', { name: /Réconciliation/ }).click();
  await sansDebordement(page, 'réconciliation');
});

test('BUG-246 : fournée UI, sacs décimaux (1,13) acceptés par le champ, manquant/excédent affiché', async ({ page }, info) => {
  test.setTimeout(600_000);
  await seConnecter(page, '@gerant-k2', '@gerant-k2');
  await page.goto('/production', { waitUntil: 'domcontentloaded', timeout: 180_000 });
  await fermerModalesDepart(page);
  await expect(page.getByText(/Déclaration de Fournée/)).toBeVisible({ timeout: 120_000 });
  const sacs = page.locator('input[type="number"][min="0.01"][step="0.01"]').first();
  await sacs.fill('1.13');
  const valide = await sacs.evaluate((el: HTMLInputElement) => el.validity.valid);
  console.log(`[${info.project.name}] sacs 1.13 valide (step) = ${valide}`);
  expect(valide, 'sacs 1.13 doit être saisissable').toBe(true);
  await sacs.fill('1.5');
  const qtyInputs = page.locator('input[type="number"][min="0"]:not([step])');
  await qtyInputs.first().fill('100', { timeout: 120_000 });
  await expect(page.getByText(/MANQUANT|EXCÉDENT/)).toBeVisible({ timeout: 60_000 });
  await page.screenshot({ path: `../docs/qa/captures/prod-v2-${info.project.name}-fournee-rendement.png`, fullPage: true });
});

test('BUG-243 : la direction voit le litige K2 après avoir choisi K2 dans le sélecteur', async ({ page }, info) => {
  test.skip(info.project.name !== 'bureau', 'bureau seulement');
  test.setTimeout(600_000);
  await seConnecter(page, '@pierre', '@pierre');
  await page.goto('/production', { waitUntil: 'domcontentloaded', timeout: 180_000 });
  await expect(page.locator('select').first().locator('option')).toHaveCount(8, { timeout: 120_000 });
  await page.waitForTimeout(15_000); // laisser finir le chargement initial (sinon le sélecteur revient sur B1)
  await page.locator('select').first().selectOption({ label: 'K2 — COQ' });
  await page.getByRole('button', { name: /Transferts/ }).click();
  await expect(page.getByText(/EN LITIGE/).first()).toBeVisible({ timeout: 120_000 });
});

test('gérant K4 (émetteur) : Résoudre le litige, motif obligatoire puis succès', async ({ page }, info) => {
  test.skip(info.project.name !== 'bureau', 'résolution jouée une seule fois (bureau)');
  test.setTimeout(600_000);
  await seConnecter(page, 'zz_prod_gerant_k4', 'ZzProd-2026!');
  await page.goto('/production', { waitUntil: 'domcontentloaded', timeout: 180_000 });
  await page.getByRole('button', { name: /Transferts/ }).click();
  await expect(page.getByText(/EN LITIGE/).first()).toBeVisible({ timeout: 120_000 });
  await page.screenshot({ path: `../docs/qa/captures/prod-v2-${info.project.name}-litige-emetteur.png`, fullPage: true });
  await page.getByRole('button', { name: /Résoudre le litige/i }).first().click();
  await page.screenshot({ path: `../docs/qa/captures/prod-v2-${info.project.name}-litige-resolution.png`, fullPage: true });
  const valider = page.getByRole('button', { name: /Confirmer la résolution/i });
  await valider.click();
  await expect(page.locator('textarea:invalid')).toHaveCount(1); // motif obligatoire (validation native)
  await page.locator('textarea').last().fill('ZZTEST vague 2 - recomptage physique');
  await valider.click();
  await expect(page.getByText(/Litige résolu/i).first()).toBeVisible({ timeout: 60_000 });
});

test('Clôture Journalière : export Excel et impression (K2)', async ({ page }, info) => {
  test.skip(info.project.name !== 'bureau', 'export testé sur bureau');
  test.setTimeout(600_000);
  await seConnecter(page, '@gerant-k2', '@gerant-k2');
  await page.goto('/cloture-journaliere', { waitUntil: 'domcontentloaded', timeout: 180_000 });
  await fermerModalesDepart(page);
  await expect(page.getByText(/Décomposition/i).first()).toBeVisible({ timeout: 120_000 });
  const [dl] = await Promise.all([
    page.waitForEvent('download', { timeout: 30_000 }),
    page.getByRole('button', { name: /Exporter en Excel/i }).click(),
  ]);
  const dest = path.resolve(__dirname, '../../docs/qa/captures/prod-v2-cloture.xlsx');
  await dl.saveAs(dest);
  console.log('XLSX', dl.suggestedFilename(), fs.statSync(dest).size);
  const [popup] = await Promise.all([
    page.waitForEvent('popup', { timeout: 20_000 }),
    page.getByRole('button', { name: /Imprimer/i }).click(),
  ]);
  await popup.waitForLoadState('domcontentloaded');
  const html = await popup.content();
  console.log('PRINT contient KPI', /Indicateurs du jour/.test(html), /Sorties Grat/.test(html));
  fs.writeFileSync(path.resolve(__dirname, '../../docs/qa/captures/prod-v2-cloture-print.html'), html);
});

test('Clôture Journalière : lisible à 360 px, sans débordement de page', async ({ page }, info) => {
  test.setTimeout(600_000);
  await seConnecter(page, '@gerant-k2', '@gerant-k2');
  await page.goto('/cloture-journaliere', { waitUntil: 'domcontentloaded', timeout: 180_000 });
  await fermerModalesDepart(page);
  await expect(page.getByText(/Décomposition/i).first()).toBeVisible({ timeout: 120_000 });
  await sansDebordement(page, 'clôture journalière');
  await page.screenshot({ path: `../docs/qa/captures/prod-v2-${info.project.name}-cloture-journaliere.png`, fullPage: true });
});

test('BUG-244 : KPI « Fournées enregistrées » = total réel (17), jamais partiel (15 chargées)', async ({ page }, info) => {
  test.skip(info.project.name !== 'bureau', 'bureau seulement');
  test.setTimeout(600_000);
  await seConnecter(page, '@gerant-k2', '@gerant-k2');
  await page.goto('/production', { waitUntil: 'domcontentloaded', timeout: 180_000 });
  const kpi = page.locator('div', { hasText: /^FOURNÉES ENREGISTRÉES$/ }).first().locator('xpath=following-sibling::div[1]');
  await expect(kpi).toBeVisible({ timeout: 120_000 });
  await expect(kpi).not.toHaveText('0', { timeout: 120_000 }); // données chargées
  console.log('KPI fournées =', (await kpi.textContent())?.trim());
  await expect(kpi).toHaveText('17', { timeout: 120_000 });
});

test('BUG-245 : KPI « Pains non valorisés » exclut le « reste à vendre » (attendu 23 = 8 déclassés + 12 gratuits + 3 invendus)', async ({ page }, info) => {
  test.skip(info.project.name !== 'bureau', 'bureau seulement');
  test.setTimeout(600_000);
  await seConnecter(page, '@gerant-k2', '@gerant-k2');
  await page.goto('/production', { waitUntil: 'domcontentloaded', timeout: 180_000 });
  const kpi = page.locator('div', { hasText: /^PAINS NON VALORISÉS$/ }).first().locator('xpath=following-sibling::div[1]');
  await expect(kpi).toBeVisible({ timeout: 120_000 });
  await expect(kpi).not.toHaveText('0', { timeout: 120_000 }); // données chargées
  console.log('KPI non valorisés =', (await kpi.textContent())?.trim());
  await expect(kpi).toHaveText('23', { timeout: 120_000 });
});
