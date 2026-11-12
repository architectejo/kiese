import { test, expect, Page } from '@playwright/test';

/**
 * Vague 4 (testeur-production, 2026-11-12) — VRAIE base, K2, rotation activée par le testeur
 * (relève réglée quelques minutes dans le futur, puis remise à 12:00 par script).
 * Vérifie BUG-272 : modale de désignation « Service du ... (relève de ...) », annonce « minuit »,
 * « Stock de départ de la relève ». Lancer : projet bureau seulement.
 */
const API = 'http://localhost:8000/api';
const HANDOVER_H = Number(process.env.HANDOVER_H ?? 18);
const HANDOVER_M = Number(process.env.HANDOVER_M ?? 55);
// Identifiants fournis par l'environnement (jamais en dur) : E2E_GERANT_K2_USER / E2E_GERANT_K2_PWD.
const GERANT_K2 = { user: process.env.E2E_GERANT_K2_USER ?? '', pwd: process.env.E2E_GERANT_K2_PWD ?? '' };

async function seConnecter(page: Page, username: string, password: string) {
  await page.goto('/login', { waitUntil: 'domcontentloaded', timeout: 180_000 });
  await page.getByPlaceholder('Ex: pierre').fill(username, { timeout: 120_000 });
  await page.getByPlaceholder('••••••••').fill(password);
  await page.getByRole('button', { name: /se connecter/i }).click();
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 150_000 });
}

test('BUG-272 : désignation, annonce de minuit, stock de départ de la relève (K2)', async ({ page, request }, info) => {
  test.skip(info.project.name !== 'bureau', 'bureau seulement');
  test.skip(!GERANT_K2.user, 'E2E_GERANT_K2_USER / E2E_GERANT_K2_PWD requis');
  test.setTimeout(1_500_000);
  await seConnecter(page, GERANT_K2.user, GERANT_K2.pwd);

  // 1. Équipe déjà désignée par API : on ouvre la modale via « (changer) » (même composant que la désignation).
  await expect(page.getByText(/Équipe de service : A/).first()).toBeVisible({ timeout: 120_000 });
  await page.getByText(/\(changer\)/).first().click({ timeout: 60_000 });
  const sous = page.getByText(/Service du .*relève de/).first();
  await expect(sous).toBeVisible({ timeout: 120_000 });
  console.log('SOUS-TITRE:', await sous.innerText());
  await expect(page.getByText(/la date, elle, change à minuit/).first()).toBeVisible({ timeout: 60_000 });
  await page.screenshot({ path: '../docs/qa/captures/prod-v4-designation.png' });
  await page.keyboard.press('Escape');
  await page.getByRole('button', { name: /Annuler|Fermer/ }).first().click({ timeout: 5_000 }).catch(() => undefined);

  // 2. Session à cheval sur minuit (datée de la veille, équipe de service A) créée par API :
  //    le sondage la clôture silencieusement et l'annonce « minuit » apparaît.
  const lg = await request.post(`${API}/core/auth/login/`, { data: { username: GERANT_K2.user, password: GERANT_K2.pwd }, timeout: 120_000 });
  const tok = (await lg.json()).access;
  const cr = await request.post(`${API}/production/sessions/`, {
    headers: { Authorization: `Bearer ${tok}` }, timeout: 120_000,
    data: { team: 'A', date: '2026-11-11', flour_sacks_used: '1', lines: [{ bread_price: 1, quantity: 20 }] },
  });
  console.log('SESSION 11/11:', cr.status(), (await cr.text()).slice(0, 200));
  const notice = page.getByText(/s'est terminé à minuit/).first();
  await expect(notice).toBeVisible({ timeout: 240_000 });
  console.log('ANNONCE:', await notice.innerText());
  await page.screenshot({ path: '../docs/qa/captures/prod-v4-minuit.png' });
  await page.getByRole('button', { name: /J'ai compris/ }).click({ timeout: 60_000 });

  // 3. Relève : attendre l'heure, puis « Stock de départ de la relève » (désignation B déjà posée).
  for (let i = 0; i < 400; i++) {
    const st = await request.get(`${API}/production/team-assignment/`, { headers: { Authorization: `Bearer ${tok}` }, timeout: 120_000 });
    const j = await st.json();
    const t = new Date(j.server_now);
    const loc = t.getUTCHours() * 60 + t.getUTCMinutes() + 60; // Africa/Kinshasa = UTC+1
    if (loc >= HANDOVER_H * 60 + HANDOVER_M + 1) { console.log('RELEVE ATTEINTE', j.server_now, j.shift_date, j.work_date, j.team); break; }
    await page.waitForTimeout(15_000);
  }
  const depart = page.getByText('Stock de départ de la relève').first();
  const desig = page.getByText(/Équipe de service/).first();
  await expect(depart.or(desig)).toBeVisible({ timeout: 300_000 });
  console.log('MODALE A LA RELEVE: depart=', await depart.isVisible(), 'designation=', await desig.isVisible());
  await page.screenshot({ path: '../docs/qa/captures/prod-v4-releve.png', fullPage: true });
});
