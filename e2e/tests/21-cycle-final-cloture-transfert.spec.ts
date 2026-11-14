import { test, expect, Page, APIRequestContext } from '@playwright/test';
import { CAP, API, login, later, overflow, apiToken } from '../fixtures/cycle';

/**
 * Cycle final (testeur-e2e, 2026-11-14) - a lancer sur UNE seule taille d'ecran (bureau) : une seule
 * cloture K4 par jour.
 * (2) gerant K4 : ventes cash livrees, depense locale, billetage avec ecart, creation de la cloture.
 * (4) BUG-277 : transfert K3 -> K4 en litige, la direction ne peut pas confirmer la cloture ; apres
 *     resolution par l'emettrice (K3), confirmation puis inscription au livre de caisse.
 */
test.describe.configure({ mode: 'serial' });

async function creerVenteCash(request: APIRequestContext, facturier: string, codeClient: string, qte500: number, verse: number) {
  const tok = await apiToken(request, facturier);
  const H = { Authorization: `Bearer ${tok}` };
  const cl = await (await request.get(`${API}/api/clients/clients/?search=${codeClient}`, { headers: H })).json();
  const prix = await (await request.get(`${API}/api/core/bread-prices/`, { headers: H })).json();
  const p500 = prix.results.find((p: { unit_price: number }) => p.unit_price === 500).id;
  const c = await request.post(`${API}/api/sales/invoices/`, {
    headers: H,
    data: { client: cl.results[0].id, payment_type: verse > 0 ? 'CASH' : 'CREDIT', payment_amount: String(verse), lines: [{ bread_price: p500, quantity: qte500 }] },
  });
  expect(c.status(), await c.text()).toBe(201);
  const inv = await c.json();
  const d = await request.post(`${API}/api/sales/invoices/${inv.id}/deliver/`, { headers: H });
  expect(d.ok(), await d.text()).toBeTruthy();
}

async function allerTreso(page: Page) {
  await page.goto('/treasury', { waitUntil: 'domcontentloaded' });
  await later(page);
}

async function filtrerK4(page: Page) {
  const f = page.locator('select').filter({ has: page.locator('option', { hasText: /K4/ }) }).first();
  if (await f.count()) await f.selectOption({ label: (await f.locator('option', { hasText: /K4/ }).first().innerText()).trim() });
}

test('Gerant K4 : cloture avec billetage et ecart', async ({ page, request }, info) => {
  test.setTimeout(480_000);
  // 10 000 FC cash integral + 5 000 FC verses sur 20 000 : cash du jour = 15 000 FC
  if (!process.env.E2E_SKIP_SETUP) { // rejeu : les rapports du jour existent deja (livraison bloquee apres rapport)
  await creerVenteCash(request, 'zz_treso_facturier_a', 'K4-0050', 20, 10_000); // equipe A
  await creerVenteCash(request, 'zz_clients_facturier', 'K4-0051', 40, 5_000); // equipe B
  }

  await login(page, 'zz_clients_gerant');
  await allerTreso(page);
  await page.getByRole('button', { name: /générer rapport du jour/i }).click();
  await expect(page.getByText(/TOTAL CASH DU JOUR/)).toBeVisible();
  await expect(page.getByText('15 000 FC').first()).toBeVisible({ timeout: 30_000 });

  // depense locale 2 000 FC
  await page.getByRole('button', { name: /^ajouter$/i }).click();
  await page.locator('form').filter({ hasText: /Enregistrer la Dépense/ }).locator('input[type="number"]').fill('2000');
  await page.getByPlaceholder('Nature de la dépense...').fill('Transport test E2E');
  await page.getByRole('button', { name: /enregistrer la dépense/i }).click();
  await expect(page.getByText(/Transport test E2E/)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/-2\s?000 FC/)).toBeVisible();

  // validation du rapport facturier
  await page.getByRole('button', { name: /confirmer & clôturer/i }).click();
  await expect(page.getByText(/rapport\(s\) validé\(s\)/)).toBeVisible({ timeout: 30_000 });

  // billetage : 10 000 + 3 x 1 000 + 500 = 13 500 (net theorique 13 000, ecart +500)
  const champs = page.locator('form').filter({ hasText: /Valeur Faciale/i }).locator('input[type="number"]');
  await champs.nth(1).fill('1');   // 10 000
  await champs.nth(3).fill('3');   // 1 000
  await champs.nth(4).fill('1');   // 500
  await expect(page.getByText(/TOTAL GÉNÉRAL ESPÈCES/)).toBeVisible();
  await expect(page.getByText(/13\s?500 FC/).first()).toBeVisible();
  await expect(page.getByText(/\+500 FC \(Excédent\)/)).toBeVisible();
  await page.screenshot({ path: `${CAP}/cf-${info.project.name}-cloture-billetage.png`, fullPage: true });
  expect(await overflow(page)).toBeLessThanOrEqual(1);
  await page.getByRole('button', { name: /valider la clôture de caisse du jour/i }).click();
  await expect(page.getByText(/Clôture créée/)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText('EN ATTENTE').first()).toBeVisible();
  await page.screenshot({ path: `${CAP}/cf-${info.project.name}-cloture-creee.png`, fullPage: true });
  // la clôture est deja la : plus de saisie possible pour le jour, ecart journalise (+500)
  await expect(page.getByText(/Écart: \+?500 FC/).first()).toBeVisible();
});

test('BUG-277 : transfert en litige -> confirmation de cloture bloquee, puis resolue et inscrite', async ({ page }, info) => {
  test.setTimeout(900_000);
  if (!process.env.E2E_SKIP_TRANSFER_SETUP) {
  // 1) K4 demande 2 pains de 200 FC a K3
  await login(page, 'zz_clients_gerant');
  await page.goto('/production', { waitUntil: 'domcontentloaded' });
  await later(page);
  await page.getByRole('button', { name: /transferts/i }).first().click();
  await page.locator('select').filter({ has: page.locator('option', { hasText: /K3/ }) }).first().selectOption({ label: /K3/ as unknown as string }).catch(async () => {
    const s = page.locator('select').filter({ has: page.locator('option', { hasText: /K3/ }) }).first();
    await s.selectOption({ label: (await s.locator('option', { hasText: /K3/ }).first().innerText()).trim() });
  });
  await page.locator('form').filter({ hasText: /Quantités demandées/i }).locator('input[type="number"]').first().fill('2');
  await page.locator('form').filter({ hasText: /Quantités demandées/i }).getByPlaceholder('Motif, urgence...').fill('Test E2E BUG-277');
  await page.getByRole('button', { name: /envoyer la demande/i }).click();
  await expect(page.getByRole('status').filter({ hasText: /demande|envoy/i }).first()).toBeVisible({ timeout: 30_000 });

  // 2) K3 envoie
  await login(page, 'zz_prod_gerant_k3');
  await page.goto('/production', { waitUntil: 'domcontentloaded' });
  await later(page);
  const equipe = page.getByRole('button', { name: /confirmer l'équipe/i });
  if (await equipe.waitFor({ state: 'visible', timeout: 10_000 }).then(() => true).catch(() => false)) await equipe.click();
  await later(page);
  await page.getByRole('button', { name: /transferts/i }).first().click();
  await page.getByRole('button', { name: /envoyer les pains/i }).first().click();
  await expect(page.getByText(/RÉCEPTIONNÉ|Réceptions à Confirmer|envoy/i).first()).toBeVisible({ timeout: 30_000 });

  }

  // 3) K4 recoit 1 sur 2 -> litige
  await login(page, 'zz_clients_gerant');
  await page.goto('/production', { waitUntil: 'domcontentloaded' });
  await later(page);
  await page.getByRole('button', { name: /transferts/i }).first().click();
  await expect(page.getByText('Réceptions à Confirmer')).toBeVisible({ timeout: 30_000 });
  await page.getByText(/envoyé: 2/).first().locator('xpath=ancestor::div[1]').locator('input').fill('1');
  await page.getByRole('button', { name: /confirmer la réception/i }).first().click();
  await expect(page.getByText(/LITIGE D'ÉCART/).first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/Clôture de caisse bloquée/).first()).toBeVisible();
  await page.screenshot({ path: `${CAP}/cf-${info.project.name}-bug277-litige.png`, fullPage: true });

  // 4) direction : confirmation de la cloture K4 refusee
  await login(page, 'zz_direction');
  await allerTreso(page);
  await filtrerK4(page);
  const dialogues: string[] = [];
  page.on('dialog', async d => { dialogues.push(d.message()); await d.dismiss(); });
  await page.getByText('Cliquez pour confirmer / infirmer').first().click();
  await page.getByRole('button', { name: /^confirmer$/i }).first().click();
  await page.getByRole('button', { name: /confirmer la clôture/i }).click();
  await expect.poll(() => dialogues.length, { timeout: 30_000 }).toBeGreaterThan(0);
  info.annotations.push({ type: 'message-validate-bloque', description: dialogues[0].slice(0, 300) });
  expect(dialogues[0]).toMatch(/transfert|écart/i);
  await page.screenshot({ path: `${CAP}/cf-${info.project.name}-bug277-confirmation-bloquee.png`, fullPage: true });

  // 5) K3 (emettrice) resout le litige
  await login(page, 'zz_prod_gerant_k3');
  await page.goto('/production', { waitUntil: 'domcontentloaded' });
  await later(page);
  await page.getByRole('button', { name: /transferts/i }).first().click();
  await page.getByRole('button', { name: /résoudre le litige/i }).first().click();
  await page.getByPlaceholder('Motif de la résolution (obligatoire)').fill('Recomptage physique constate, test E2E');
  await page.getByRole('button', { name: /confirmer la résolution/i }).click();
  await expect(page.getByText(/Litige résolu/)).toBeVisible({ timeout: 30_000 });

  // 6) direction : confirmation OK puis inscription au livre de caisse
  await login(page, 'zz_direction');
  await allerTreso(page);
  await filtrerK4(page);
  await page.getByText('Cliquez pour confirmer / infirmer').first().click();
  await page.getByRole('button', { name: /^confirmer$/i }).first().click();
  await page.getByRole('button', { name: /confirmer la clôture/i }).click();
  await expect(page.getByText('CONFIRMÉE').first()).toBeVisible({ timeout: 30_000 });
  await page.getByRole('button', { name: /inscrire au livre de caisse/i }).first().click();
  await expect(page.getByText(/Inscrit au grand livre/).first()).toBeVisible({ timeout: 30_000 });
  await page.screenshot({ path: `${CAP}/cf-${info.project.name}-bug277-inscrit.png`, fullPage: true });
});

test('Livre de caisse : solde progressif et verification d\'integrite verte (direction)', async ({ page }, info) => {
  test.setTimeout(240_000);
  await login(page, 'zz_direction');
  await allerTreso(page);
  await filtrerK4(page);
  await expect(page.getByText(/Versement Journalier K4/).first()).toBeVisible({ timeout: 60_000 });
  const dialogues: string[] = [];
  page.on('dialog', async d => { dialogues.push(d.message()); await d.dismiss(); });
  await page.getByRole('button', { name: /vérifier intégrité/i }).click();
  await expect(page.getByText(/Chaîne intègre/)).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(1500);
  await page.screenshot({ path: `${CAP}/cf-${info.project.name}-livre-integrite.png`, fullPage: true });
  info.annotations.push({ type: 'dialogues', description: dialogues.join(' | ').slice(0, 300) || 'aucun' });
  await expect(page.getByText(/Chaîne (rompue|corrompue|invalide)|falsifi/i)).toHaveCount(0);
});
