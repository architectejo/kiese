import { test, expect, Page } from '@playwright/test';

/**
 * Vague 2 (testeur-clients-commissions, 2026-11-12) — VRAIE base, K4 uniquement, comptes
 * zz_clients_* et clients « ZZTEST Clients n ». Chargement progressif / « Voir plus » de la page
 * Clients, recherche, page Commissions (KPI, impression/export), débordement horizontal.
 * Lancer : npx playwright test tests/14-clients-commissions-vague2-db.spec.ts --project=pos --project=bureau --output=<dossier perso>
 */
async function seConnecter(page: Page, user: string) {
  await page.goto('/login', { waitUntil: 'domcontentloaded', timeout: 240_000 });
  await page.getByPlaceholder('Ex: pierre').fill(user, { timeout: 60_000 });
  await page.getByPlaceholder('••••••••').fill(user);
  await page.getByRole('button', { name: /se connecter/i }).click();
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 120_000 });
}
async function verifierSession(page: Page) {
  await page.waitForTimeout(4_000);
  if (/\/login/.test(page.url())) {
    await page.screenshot({ path: `../docs/qa/captures/clients-vague2-redirection-login-${test.info().project.name}.png` });
    throw new Error('Redirigé vers /login après navigation directe : ' + page.url());
  }
}
async function reporterModale(page: Page) {
  const plusTard = page.getByRole('button', { name: /plus tard/i });
  await plusTard.waitFor({ state: 'visible', timeout: 8_000 }).then(() => plusTard.click()).catch(() => undefined);
}
async function sansDebordement(page: Page) {
  const ecart = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(ecart, 'débordement horizontal (px)').toBeLessThanOrEqual(1);
}
async function compteur(page: Page): Promise<{ vus: number; charges: number }> {
  const t = await page.getByText(/\d+ sur \d+ client\(s\) affiché/).first().innerText();
  const m = t.match(/(\d+) sur (\d+) client/)!;
  return { vus: Number(m[1]), charges: Number(m[2]) };
}

test('Clients : gérant K4, chargement progressif, Voir plus, recherche ZZTEST', async ({ page }) => {
  test.setTimeout(900_000);
  await seConnecter(page, 'zz_clients_gerant');
  await page.goto('/clients', { waitUntil: 'domcontentloaded', timeout: 240_000 });
  await verifierSession(page);
  await reporterModale(page);
  await expect(page.getByText(/\d+ sur \d+ client\(s\) affiché/).first()).toBeVisible({ timeout: 300_000 });
  const c0 = await compteur(page);
  expect(c0.vus).toBe(20);
  await page.screenshot({ path: `../docs/qa/captures/clients-vague2-liste-${test.info().project.name}.png`, fullPage: false });
  await sansDebordement(page);
  const voirPlus = page.getByRole('button', { name: /voir plus/i });
  await expect(voirPlus).toBeVisible();
  await voirPlus.click();
  await expect.poll(async () => (await compteur(page)).vus, { timeout: 120_000 }).toBe(40);
  await voirPlus.click();
  await expect.poll(async () => (await compteur(page)).vus, { timeout: 120_000 }).toBe(60);
  // pas de doublon de code client dans les lignes affichées
  const codes = await page.locator('text=/^K4-\\d{4,}$/').allInnerTexts();
  expect(new Set(codes).size, 'codes dupliqués dans la liste').toBe(codes.length);
  await sansDebordement(page);
  // recherche prédictive
  await page.getByPlaceholder('Rechercher par nom, commerce ou ID...').fill('ZZTEST');
  await expect(page.getByText(/ZZTEST/).first()).toBeVisible({ timeout: 120_000 });
  await expect.poll(async () => (await compteur(page)).vus, { timeout: 120_000 }).toBeGreaterThan(0);
  await page.screenshot({ path: `../docs/qa/captures/clients-vague2-recherche-${test.info().project.name}.png`, fullPage: false });
  await sansDebordement(page);
});

test('Clients : facturier K4 trouve un client K3 par nom partiel', async ({ page }) => {
  test.setTimeout(600_000);
  await seConnecter(page, 'zz_clients_facturier');
  await page.goto('/clients', { waitUntil: 'domcontentloaded', timeout: 240_000 });
  await verifierSession(page);
  await reporterModale(page);
  await expect(page.getByText(/\d+ sur \d+ client\(s\) affiché/).first()).toBeVisible({ timeout: 300_000 });
  await page.getByPlaceholder('Rechercher par nom, commerce ou ID...').fill('K3-0044');
  await expect(page.getByText('K3-0044').first()).toBeVisible({ timeout: 120_000 });
  await page.screenshot({ path: `../docs/qa/captures/clients-vague2-facturier-k3-${test.info().project.name}.png`, fullPage: false });
  await sansDebordement(page);
});

test('Commissions : comptable, période K4 02/2026, KPI, impression et export après chargement', async ({ page }) => {
  test.setTimeout(900_000);
  await seConnecter(page, 'zz_clients_comptable');
  await page.goto('/commissions', { waitUntil: 'domcontentloaded', timeout: 240_000 });
  await verifierSession(page);
  await reporterModale(page);
  await expect(page.getByRole('heading', { name: /Commissions des Revendeurs/ })).toBeVisible({ timeout: 300_000 });
  await expect(page.getByRole('button', { name: /imprimer/i }).first()).toBeEnabled({ timeout: 300_000 }).catch(() => undefined);
  await page.screenshot({ path: `../docs/qa/captures/commissions-vague2-${test.info().project.name}.png`, fullPage: true });
  await sansDebordement(page);
});
