import { test, expect, Page } from '@playwright/test';

/**
 * Vague 4 (testeur-ventes, 2026-11-12) — VRAIE base, K1 (rotation activée le temps du test),
 * comptes zz_ventes_*, clients « ZZTEST Ventes n ». Décision client : jour calendaire (BUG-271/272).
 * Lancer : npx playwright test tests/15-ventes-vague4-calendaire-db.spec.ts --project=pos --project=bureau --output=<dossier perso>
 */
const FACTURIER = 'zz_ventes_facturier';

async function seConnecter(page: Page) {
  await page.goto('/login', { waitUntil: 'domcontentloaded', timeout: 240_000 });
  await page.getByPlaceholder('Ex: pierre').fill(FACTURIER, { timeout: 60_000 });
  await page.getByPlaceholder('••••••••').fill(FACTURIER);
  await page.getByRole('button', { name: /se connecter/i }).click();
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 60_000 });
}
async function reporterModale(page: Page) {
  const plusTard = page.getByRole('button', { name: /plus tard/i });
  await plusTard.waitFor({ state: 'visible', timeout: 40_000 }).then(() => plusTard.click()).catch(() => undefined);
}
async function sansDebordement(page: Page) {
  const ecart = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(ecart, 'débordement horizontal (px)').toBeLessThanOrEqual(1);
}

test('reçu : date du jour calendaire, équipe désignée, mentions légales, sans débordement', async ({ page }) => {
  test.setTimeout(600_000);
  await seConnecter(page);
  await page.goto('/sales/create', { waitUntil: 'domcontentloaded', timeout: 240_000 });
  await reporterModale(page);
  await page.getByPlaceholder('Ex: K1-0045 ou KANZA Albert...').waitFor({ state: 'visible', timeout: 240_000 });
  await page.getByPlaceholder('Ex: K1-0045 ou KANZA Albert...').fill('K1-0079');
  const suggestion = page.locator('text=/BP:/').first();
  await expect(suggestion).toBeVisible({ timeout: 240_000 });
  await page.screenshot({ path: `../docs/qa/captures/ventes-vague4-stock-depart-releve-${test.info().project.name}.png`, fullPage: true });
  await reporterModale(page);
  await suggestion.click();
  await sansDebordement(page);
  await page.locator('input[type="number"]').first().fill('1');
  await page.locator('input[type="number"]').last().fill('200');
  await page.getByRole('button', { name: /facturer & mettre en attente/i }).click();
  await expect(page.locator('text=/BP avant/').first()).toBeVisible({ timeout: 120_000 });
  await page.getByRole('button', { name: /imprimer le reçu/i }).first().click();
  await expect(page.getByText('Confirmer la livraison')).toBeVisible({ timeout: 10_000 });
  await page.getByRole('button', { name: /confirmer & imprimer/i }).click();
  await expect(page.getByText(/BON DE LIVRAISON/)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/RCCM:\s*021-A-650/)).toBeVisible();
  await expect(page.getByText(/A1902266K/)).toBeVisible();
  await expect(page.getByText(/Éq\.\s*[AB]/)).toBeVisible();
  await expect(page.getByText('Solde arrêté ce jour')).toBeVisible();
  const d = new Date();
  const jj = String(d.getDate()).padStart(2, '0');
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  await expect(page.getByText(new RegExp(`${jj}/${mm}/${d.getFullYear()}`)).first()).toBeVisible();
  await page.screenshot({ path: `../docs/qa/captures/ventes-vague4-recu-${test.info().project.name}.png`, fullPage: true });
  await sansDebordement(page);
});

test('désignation d\'équipe (réponse simulée « non désignée ») : sous-titre « Service du … (relève de … ») sans débordement', async ({ page }) => {
  test.setTimeout(400_000);
  // Seule la LECTURE de la désignation est simulée ; aucune écriture n'est envoyée.
  await page.route('**/api/production/team-assignment/**', async (route) => {
    if (route.request().method() !== 'GET') return route.abort();
    await route.fulfill({
      status: 200, contentType: 'application/json',
      body: JSON.stringify({
        work_date: new Date().toISOString().slice(0, 10), shift_date: new Date().toISOString().slice(0, 10),
        handover_time: '12:00', team: null, suggested: 'B', assigned_by: null, server_now: new Date().toISOString(),
      }),
    });
  });
  await seConnecter(page);
  await page.goto('/sales/create', { waitUntil: 'domcontentloaded', timeout: 240_000 });
  await expect(page.getByText(/Service du .* \(relève de 12h00\)|Service du .*relève de/)).toBeVisible({ timeout: 240_000 });
  await expect(page.getByText(/Journée de travail du/)).toHaveCount(0);
  await page.screenshot({ path: `../docs/qa/captures/ventes-vague4-designation-${test.info().project.name}.png`, fullPage: true });
  await sansDebordement(page);
});
