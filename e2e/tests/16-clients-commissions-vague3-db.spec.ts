import { test, expect, Page } from '@playwright/test';

/**
 * Vague 3 (testeur-clients-commissions, 2026-11-12) - VRAIE base, K4, comptes zz_clients_*.
 * BUG-269 : KPI de Clients.tsx (« ... » pendant le chargement puis totaux definitifs).
 * BUG-270 : Commissions.tsx (COMPTABLE sans « Regler » / « Ajustement manuel » ; ADMIN/DIRECTION les voient ;
 *           banniere d'erreur avec le message `detail` de l'API).
 * Aucun compte DIRECTION/ADMIN utilisable (mots de passe inconnus) : le role DIRECTION est SIMULE cote
 * navigateur en reecrivant le champ `role` des reponses /auth/login/ et /auth/me/ du compte comptable ;
 * l'API, elle, reste appelee avec le jeton COMPTABLE (donc 403 reel au clic sur Confirmer).
 * Lancer : npx playwright test tests/16-clients-commissions-vague3-db.spec.ts --project=pos --project=bureau --output=<dossier perso>
 */
const CAP = '../docs/qa/captures';

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
async function sansDebordement(page: Page) {
  const ecart = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(ecart, 'debordement horizontal (px)').toBeLessThanOrEqual(1);
}
async function simulerRole(page: Page, role: string) {
  const patch = async (route: import('@playwright/test').Route) => {
    const resp = await route.fetch();
    const body = await resp.json();
    if (body.user) body.user.role = role; else if (body.role) body.role = role;
    await route.fulfill({ response: resp, json: body });
  };
  await page.route('**/api/core/auth/login/', patch);
  await page.route('**/api/core/auth/me/', patch);
}

test('BUG-269 : KPI Clients (gerant K4) : « ... » pendant le chargement puis totaux definitifs', async ({ page }) => {
  test.setTimeout(900_000);
  await seConnecter(page, 'zz_clients_gerant');
  // Ralentit les pages 2+ de la liste pour observer l'etat partiel de facon deterministe.
  await page.route(/\/api\/clients\/clients\/\?.*page=[2-9]/, async route => {
    await new Promise(r => setTimeout(r, 6_000));
    await route.continue();
  });
  await page.goto('/clients', { waitUntil: 'domcontentloaded', timeout: 240_000 });
  await reporterModale(page);
  const actifs = page.getByText(/Actifs : /).first();
  const alertes = page.getByText(/\d+ alertes|… alertes/).first();
  await expect(actifs).toBeVisible({ timeout: 300_000 });
  const vus: string[] = [];
  const debut = await actifs.innerText();
  vus.push(debut);
  expect(debut, 'KPI Actifs doit etre « ... » tant que la liste est incomplete').toContain('…');
  expect(await alertes.innerText()).toContain('…');
  await page.screenshot({ path: `${CAP}/clients-vague3-kpi-chargement-${test.info().project.name}.png` });
  await expect.poll(async () => (await actifs.innerText()).includes('…'), { timeout: 600_000, intervals: [2_000] }).toBe(false);
  const fin = await actifs.innerText();
  expect(fin).toMatch(/Actifs : \d+/);
  await expect(page.getByText(/\d+ fiches/).first()).toBeVisible();
  const fiches = await page.getByText(/\d+ fiches/).first().innerText();
  const encours = await page.getByText(/\d[\d\s  ]* FC$/).first().innerText().catch(() => '');
  await page.screenshot({ path: `${CAP}/clients-vague3-kpi-final-${test.info().project.name}.png` });
  console.log(`KPI debut=[${debut}] fin=[${fin}] fiches=[${fiches}] encours=[${encours}]`);
  await sansDebordement(page);
});

test('BUG-270 : COMPTABLE ne voit ni « Regler » ni « Ajustement manuel »', async ({ page }) => {
  test.setTimeout(900_000);
  await seConnecter(page, 'zz_clients_comptable');
  await page.goto('/commissions', { waitUntil: 'domcontentloaded', timeout: 240_000 });
  await reporterModale(page);
  await expect(page.getByRole('heading', { name: /Commissions des Revendeurs/ })).toBeVisible({ timeout: 300_000 });
  await page.getByPlaceholder('Rechercher un client...').fill('ZZTEST');
  const ligne = page.getByRole('row').filter({ hasText: 'EN ATTENTE' }).first();
  await expect(ligne).toBeVisible({ timeout: 300_000 });
  await expect(page.getByRole('button', { name: /régler/i })).toHaveCount(0);
  await page.screenshot({ path: `${CAP}/commissions-vague3-comptable-${test.info().project.name}.png`, fullPage: true });
  await ligne.click();
  await expect(page.getByRole('dialog').getByText(/NET À PAYER/)).toBeVisible();
  await expect(page.getByRole('button', { name: /ajustement manuel/i })).toHaveCount(0);
  await expect(page.getByRole('button', { name: /régler cette commission/i })).toHaveCount(0);
  await page.screenshot({ path: `${CAP}/commissions-vague3-comptable-fiche-${test.info().project.name}.png` });
  await sansDebordement(page);
});

test('BUG-270 : role DIRECTION (simule) voit « Regler » et « Ajustement manuel » ; banniere avec le detail de l\'API', async ({ page }) => {
  test.setTimeout(900_000);
  await simulerRole(page, 'DIRECTION');
  await seConnecter(page, 'zz_clients_comptable');
  await page.goto('/commissions', { waitUntil: 'domcontentloaded', timeout: 240_000 });
  await reporterModale(page);
  await expect(page.getByRole('heading', { name: /Commissions des Revendeurs/ })).toBeVisible({ timeout: 300_000 });
  await page.getByPlaceholder('Rechercher un client...').fill('ZZTEST');
  const ligne = page.getByRole('row').filter({ hasText: 'EN ATTENTE' }).first();
  await expect(ligne).toBeVisible({ timeout: 300_000 });
  await expect(page.getByRole('button', { name: /régler/i }).first()).toBeVisible();
  await page.screenshot({ path: `${CAP}/commissions-vague3-direction-simule-${test.info().project.name}.png`, fullPage: true });
  // Fiche : Ajustement manuel visible
  await ligne.click();
  await expect(page.getByRole('button', { name: /ajustement manuel/i })).toBeVisible();
  await page.screenshot({ path: `${CAP}/commissions-vague3-direction-fiche-${test.info().project.name}.png` });
  // 1) Ajustement manuel : l'API reelle repond 403 (jeton COMPTABLE) -> banniere avec le detail
  await page.getByRole('button', { name: /ajustement manuel/i }).click();
  await page.getByPlaceholder(/Net calculé/).fill('100');
  await page.getByRole('button', { name: /enregistrer|valider|confirmer/i }).first().click();
  const banniere = page.getByRole('alert');
  await expect(banniere).toBeVisible({ timeout: 120_000 });
  const msg = await banniere.innerText();
  console.log('banniere set_manuel (reel, 403) =', msg);
  expect(msg).toContain("Vous n'avez pas la permission");
  await page.screenshot({ path: `${CAP}/commissions-vague3-banniere-403-${test.info().project.name}.png` });
  // BUG-280 corrige : la fiche est fermee, la banniere est visible et cliquable (aucun dialogue au-dessus).
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.locator('.modal-backdrop')).toHaveCount(0);
  await page.screenshot({ path: `${CAP}/commissions-vague3-banniere-403-visible-${test.info().project.name}.png` });
  await banniere.getByRole('button', { name: /fermer/i }).click();
  await expect(banniere).toHaveCount(0);
  // 2) Regler : 400 simule (commission payee) -> message detail francais affiche tel quel
  await page.route('**/api/commissions/commissions/*/mark_paid/', route =>
    route.fulfill({ status: 400, contentType: 'application/json', json: { detail: 'Commission déjà payée : modification impossible.' } }));
  await page.getByRole('button', { name: /régler/i }).first().click();
  await page.getByRole('button', { name: /^confirmer$/i }).click();
  await expect(page.getByRole('alert')).toContainText('Commission déjà payée', { timeout: 120_000 });
  await page.screenshot({ path: `${CAP}/commissions-vague3-banniere-400-${test.info().project.name}.png` });
  await sansDebordement(page);
});
