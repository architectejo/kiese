import { test, expect, Page } from '@playwright/test';

/**
 * Vague 2 (testeur-ventes, 2026-11-12) — VRAIE base, K1 uniquement, comptes zz_ventes_* et clients
 * « ZZTEST Ventes n ». BUG-229 (client à risque proposé), BUG-230 (vente occasionnelle au comptant,
 * message d'erreur serveur), reçu complet.
 * Lancer : npx playwright test tests/13-ventes-vague2-db.spec.ts --project=pos --project=bureau
 */
const FACTURIER = 'zz_ventes_facturier';
const PWD = 'zz_ventes_facturier';

async function seConnecter(page: Page) {
  await page.goto('/login', { waitUntil: 'domcontentloaded', timeout: 240_000 });
  await page.getByPlaceholder('Ex: pierre').fill(FACTURIER, { timeout: 60_000 });
  await page.getByPlaceholder('••••••••').fill(PWD);
  await page.getByRole('button', { name: /se connecter/i }).click();
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 30_000 });
}
async function reporterModale(page: Page) {
  const plusTard = page.getByRole('button', { name: /plus tard/i });
  await plusTard.waitFor({ state: 'visible', timeout: 8_000 }).then(() => plusTard.click()).catch(() => undefined);
}
async function sansDebordement(page: Page) {
  const ecart = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(ecart, 'débordement horizontal (px)').toBeLessThanOrEqual(1);
}

test('BUG-229/230 : client à risque proposé, refus plafond affiché, puis règlement intégral accepté, livraison, reçu', async ({ page }) => {
  test.setTimeout(600_000);
  await seConnecter(page);
  await page.goto('/sales/create', { waitUntil: 'domcontentloaded', timeout: 240_000 });
  await reporterModale(page);
  await page.getByPlaceholder('Ex: K1-0045 ou KANZA Albert...').waitFor({ state: 'visible', timeout: 240_000 });
  await page.getByPlaceholder('Ex: K1-0045 ou KANZA Albert...').fill('K1-0081'); // ZZTEST Ventes 4, BP = plafond
  const suggestion = page.locator('text=/BP:/').first();
  await expect(suggestion).toBeVisible({ timeout: 240_000 });
  await expect(page.getByText(/risque/i).first()).toBeVisible();
  await suggestion.click();
  await expect(page.getByText(/Client à risque — BP/)).toBeVisible();
  await sansDebordement(page);
  await page.locator('input[type="number"]').first().fill('1');
  await page.locator('input[type="number"]').last().fill('0');
  await page.getByRole('button', { name: /facturer & mettre en attente/i }).click();
  await expect(page.getByText(/plafond de cr[ée]dit atteint/i).first()).toBeVisible({ timeout: 120_000 });
  await page.screenshot({ path: `../docs/qa/captures/ventes-vague2-refus-${test.info().project.name}.png`, fullPage: true });
  await sansDebordement(page);
  // règlement intégral (1 pain de la 1re catégorie = 200 FC) : doit être accepté
  await page.locator('input[type="number"]').last().fill('200');
  await page.getByRole('button', { name: /facturer & mettre en attente/i }).click();
  await expect(page.locator('text=/BP avant/').first()).toBeVisible({ timeout: 120_000 });
  await sansDebordement(page);
  await page.getByRole('button', { name: /imprimer le reçu/i }).first().click();
  await expect(page.getByText('Confirmer la livraison')).toBeVisible({ timeout: 10_000 });
  await page.getByRole('button', { name: /confirmer & imprimer/i }).click();
  await expect(page.getByText(/BON DE LIVRAISON/)).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText(/RCCM:\s*021-A-650/)).toBeVisible();
  await expect(page.getByText(/10-F4300-N85947U/)).toBeVisible();
  await expect(page.getByText(/A1902266K/)).toBeVisible();
  await expect(page.getByText(/^K1 - /)).toBeVisible();
  await expect(page.getByText(/BALANCE ANTÉRIEURE \(BP\)/)).toBeVisible();
  await expect(page.getByText('Solde arrêté ce jour')).toBeVisible();
  await expect(page.getByText(/Éq\.\s*[AB]/)).toBeVisible();
  await page.screenshot({ path: `../docs/qa/captures/ventes-vague2-recu-${test.info().project.name}.png`, fullPage: true });
  await sansDebordement(page);
});

test('BUG-230 : vente occasionnelle forcée au comptant (versement = commande), facture créée', async ({ page }) => {
  test.setTimeout(500_000);
  await seConnecter(page);
  await page.goto('/sales/create', { waitUntil: 'domcontentloaded', timeout: 240_000 });
  await reporterModale(page);
  await page.getByPlaceholder('Ex: K1-0045 ou KANZA Albert...').waitFor({ state: 'visible', timeout: 240_000 });
  await page.getByText('Vente occasionnelle (sans client enregistré)').click();
  await expect(page.locator('input[type="number"]').first()).toBeEnabled({ timeout: 240_000 });
  await page.locator('input[type="number"]').first().fill('2');
  await expect(page.locator('input[type="number"]').last()).toBeDisabled();
  await expect(page.locator('input[type="number"]').last()).toHaveValue('400');
  await page.getByRole('button', { name: /facturer & mettre en attente/i }).click();
  await expect(page.locator('text=/BP avant|CLIENT DIVERS|Imprimer le reçu/i').first()).toBeVisible({ timeout: 120_000 });
  await sansDebordement(page);
  await page.screenshot({ path: `../docs/qa/captures/ventes-vague2-occasionnelle-${test.info().project.name}.png`, fullPage: true });
});
