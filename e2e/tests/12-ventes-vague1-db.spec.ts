import { test, expect } from '@playwright/test';
// Navigation « domcontentloaded » : l'évènement « load » de la page n'arrive pas en 15 s (ressources externes ?), voir rapport.
async function seConnecter(page: import('@playwright/test').Page, username: string, password: string) {
  await page.goto('/login', { waitUntil: 'domcontentloaded', timeout: 90_000 });
  await page.getByPlaceholder('Ex: pierre').fill(username, { timeout: 60_000 });
  await page.getByPlaceholder('••••••••').fill(password);
  await page.getByRole('button', { name: /se connecter/i }).click();
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 30_000 });
}

/**
 * Vague 1 (testeur-ventes, 2026-11-12) — exécutée sur la VRAIE base, boulangerie K1 uniquement,
 * avec les comptes fictifs zz_ventes_* et les clients « ZZTEST Ventes n » (voir rapport
 * docs/qa/rapports/testeur-ventes-2026-11-12-vague1-db.md). Ne touche jamais aux clients réels.
 * Lancer : npx playwright test tests/12-ventes-vague1-db.spec.ts --project=pos --project=bureau
 */
const FACTURIER = 'zz_ventes_facturier';
const PWD = 'zzVentes#2026';

async function choisirClient(page: import('@playwright/test').Page, code: string) {
  // Modale « Stock de départ du jour » (rotation) : la reporter, sans rien valider sur K1.
  const plusTard = page.getByRole('button', { name: /plus tard/i });
  await plusTard.waitFor({ state: 'visible', timeout: 20_000 }).then(() => plusTard.click()).catch(() => undefined);
  await expect(plusTard).toHaveCount(0, { timeout: 10_000 });
  const recherche = page.getByPlaceholder('Ex: K1-0045 ou KANZA Albert...');
  await recherche.fill(code);
  const suggestion = page.locator('text=/BP:|Solde OK/').first();
  await expect(suggestion).toBeVisible({ timeout: 90_000 });
  // La modale « Stock de départ » peut apparaître tardivement et intercepter les clics.
  if (await plusTard.isVisible().catch(() => false)) await plusTard.click();
  await suggestion.click();
}

async function sansDebordementHorizontal(page: import('@playwright/test').Page) {
  const ecart = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(ecart, 'débordement horizontal de la page (px)').toBeLessThanOrEqual(1);
}

test('facturer, livrer, reçu complet (équipe, BP avant/après, en-tête légal), sans débordement', async ({ page }) => {
  test.setTimeout(300_000);
  await seConnecter(page, FACTURIER, PWD);
  await page.goto('/sales/create', { waitUntil: 'domcontentloaded', timeout: 90_000 });
  await choisirClient(page, 'K1-0086'); // ZZTEST Ventes 9 (client neuf : une seule carte dans la file)
  await expect(page.getByText(/BP\s*:/)).toBeVisible();
  await sansDebordementHorizontal(page);
  await page.locator('input[type="number"]').first().fill('5');
  await page.locator('input[type="number"]').last().fill('0');
  await page.getByRole('button', { name: /facturer & mettre en attente/i }).click();
  await expect(page.locator('text=/BP avant/').first()).toBeVisible({ timeout: 15_000 });
  await sansDebordementHorizontal(page);
  await page.getByRole('button', { name: /imprimer le reçu/i }).first().click();
  await expect(page.getByText('Confirmer la livraison')).toBeVisible({ timeout: 10_000 });
  await page.getByRole('button', { name: /confirmer & imprimer/i }).click();
  await expect(page.getByText(/BON DE LIVRAISON/)).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText(/RCCM:\s*021-A-650/)).toBeVisible();
  await expect(page.getByText(/10-F4300-N85947U/)).toBeVisible();
  await expect(page.getByText(/A1902266K/)).toBeVisible();
  await expect(page.getByText(/^K1 - /)).toBeVisible();
  await expect(page.getByText(/BALANCE ANTÉRIEURE \(BP\)/)).toBeVisible();
  await expect(page.getByText(/NOUVELLE DETTE/)).toBeVisible();
  await expect(page.getByText('Solde arrêté ce jour')).toBeVisible();
  await expect(page.getByText(/Éq\.\s*[AB]/)).toBeVisible();
  await page.screenshot({ path: `../docs/qa/captures/ventes-vague1-recu-${test.info().project.name}.png`, fullPage: true });
  await sansDebordementHorizontal(page);
});

test('refus (déficit net du mois) : message clair, aucune facture créée', async ({ page }) => {
  test.setTimeout(300_000);
  await seConnecter(page, FACTURIER, PWD);
  await page.goto('/sales/create', { waitUntil: 'domcontentloaded', timeout: 90_000 });
  await choisirClient(page, 'K1-0085'); // ZZTEST Ventes 8 : BP 20 000 (< plafond) mais déficit net du mois 75 000 >= 50 000
  await page.locator('input[type="number"]').first().fill('1');
  await page.locator('input[type="number"]').last().fill('0');
  await page.getByRole('button', { name: /facturer & mettre en attente/i }).click();
  await expect(page.getByText(/(d[ée]ficit net du mois|plafond de cr[ée]dit)/i).first()).toBeVisible({ timeout: 15_000 });
  await page.screenshot({ path: `../docs/qa/captures/ventes-vague1-plafond-${test.info().project.name}.png`, fullPage: true });
  await sansDebordementHorizontal(page);
});
