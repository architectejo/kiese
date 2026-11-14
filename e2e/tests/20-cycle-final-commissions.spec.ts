import { test, expect, Page } from '@playwright/test';
import { CAP, API, login, later, overflow, apiToken } from '../fixtures/cycle';

/**
 * Cycle final (testeur-e2e, 2026-11-14) : Commissions K4 apres les ventes de la vague (clients a
 * BP 50 000 / 49 500, donc net negatif). Direction : « Net negatif » sans « Regler », fiche sans
 * bouton, API mark_paid -> 400 en francais. Comptable : aucun bouton « Regler ».
 */
async function ouvrirCommissionsK4(page: Page, gerer: boolean) {
  await page.goto('/commissions', { waitUntil: 'domcontentloaded', timeout: 90_000 });
  await later(page);
  const gen = page.getByRole('button', { name: /générer commissions|générer maintenant/i }).first();
  await expect(gen).toBeVisible({ timeout: 60_000 });
  if (gerer) {
    await gen.click();
    const modale = page.getByRole('dialog').or(page.locator('form').filter({ hasText: /Boulangerie \*/ })).first();
    const sel = page.locator('select').filter({ has: page.locator('option', { hasText: 'K4' }) }).last();
    await sel.selectOption({ label: (await sel.locator('option', { hasText: 'K4' }).first().innerText()).trim() });
    await page.getByRole('button', { name: /^générer$/i }).click();
    await expect(page.getByText(/commission|période|généré|client/i).first()).toBeVisible({ timeout: 60_000 });
    await page.getByRole('button', { name: /^fermer$/i }).first().click().catch(() => undefined);
    void modale;
  }
  // filtre boulangerie K4
  const filtre = page.locator('select').filter({ has: page.locator('option', { hasText: 'Toutes les boulangeries' }) });
  if (await filtre.count()) {
    await filtre.selectOption({ label: (await filtre.locator('option', { hasText: 'K4' }).first().innerText()).trim() });
  }
}

test('Commissions direction : Net negatif sans Regler, message 400', async ({ page, request }, info) => {
  test.setTimeout(420_000);
  await login(page, 'zz_direction');
  await later(page);
  await ouvrirCommissionsK4(page, true);
  await page.getByPlaceholder('Rechercher un client...').fill('K4-001');
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${CAP}/cf-${info.project.name}-commissions-direction.png`, fullPage: true });
  expect(await overflow(page)).toBeLessThanOrEqual(1);
  const lignes = page.locator('tr').filter({ hasText: /Net négatif|Client:/ });
  expect(await lignes.count(), 'lignes a net negatif').toBeGreaterThan(0);
  await expect(page.getByText('Net négatif').first()).toBeVisible();
  // aucune ligne a net negatif ne porte « Regler »
  const n = await lignes.count();
  for (let k = 0; k < n; k++) {
    await expect(lignes.nth(k).getByRole('button', { name: /régler/i })).toHaveCount(0);
  }
  // fiche : message + pas de bouton
  await lignes.first().click();
  await expect(page.getByText(/paiement impossible/i)).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole('button', { name: /régler cette commission/i })).toHaveCount(0);
  await page.screenshot({ path: `${CAP}/cf-${info.project.name}-commissions-fiche-negative.png`, fullPage: true });

  // API : mark_paid sur une commission a net negatif -> 400 francais
  const tok = await apiToken(request, 'zz_direction');
  const H = { Authorization: `Bearer ${tok}` };
  const liste = await (await request.get(`${API}/api/commissions/commissions/?page_size=200&is_paid=false`, { headers: H })).json();
  const neg = (liste.results ?? liste).find((c: { net_payable: string; node?: unknown; client_code?: string }) => parseFloat(c.net_payable) < 0);
  expect(neg, 'une commission a net negatif existe').toBeTruthy();
  const r = await request.post(`${API}/api/commissions/commissions/${neg.id}/mark_paid/`, { headers: H });
  info.annotations.push({ type: 'mark_paid', description: `${r.status()} ${(await r.text()).slice(0, 200)}` });
  expect(r.status()).toBe(400);
  expect((await r.json()).detail).toMatch(/négatif|negatif/i);
});

test('Commissions comptable : aucun bouton Regler', async ({ page }, info) => {
  test.setTimeout(300_000);
  await login(page, 'zz_comptable');
  await later(page);
  await ouvrirCommissionsK4(page, false);
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${CAP}/cf-${info.project.name}-commissions-comptable.png`, fullPage: true });
  expect(await overflow(page)).toBeLessThanOrEqual(1);
  await expect(page.getByRole('button', { name: /régler/i })).toHaveCount(0);
});
