import { test, expect } from '@playwright/test';
import { CAP, API, login, later, overflow, apiToken } from '../fixtures/cycle';

/**
 * Cycle final (testeur-e2e, 2026-11-14) : BUG-284 (ecran bloquant de changement de mot de passe)
 * et BUG-281 (libelle de l'equipe en rotation). Comptes zz_*. Aucun mot de passe n'est consigne :
 * le mot de passe temporaire reste en memoire du test, le nouveau est genere aleatoirement.
 */
test('BUG-284 : ecran bloquant apres reset_password, ancien faux, succes, /sales sans 403', async ({ page, request }, info) => {
  test.setTimeout(420_000);
  const tokDir = await apiToken(request, 'zz_direction');
  const H = { Authorization: `Bearer ${tokDir}` };
  const liste = await (await request.get(`${API}/api/core/users/?search=zz_facturier_k3`, { headers: H })).json();
  const cible = (liste.results ?? liste).find((u: { username: string }) => u.username === 'zz_facturier_k3');
  expect(cible, 'compte zz_facturier_k3').toBeTruthy();
  const rp = await request.post(`${API}/api/core/users/${cible.id}/reset_password/`, { headers: H });
  expect(rp.ok()).toBeTruthy();
  const temporaire = (await rp.json()).temporary_password as string;
  expect(temporaire).toBeTruthy();

  await login(page, 'zz_facturier_k3', temporaire);
  const dlg = page.getByRole('dialog', { name: /changement du mot de passe obligatoire/i });
  await expect(dlg).toBeVisible({ timeout: 30_000 });
  await page.screenshot({ path: `${CAP}/cf-${info.project.name}-bug284-ecran.png` });
  expect(await overflow(page)).toBeLessThanOrEqual(1);
  // le formulaire tient dans la fenetre : le bouton de validation est atteignable
  const champs = dlg.locator('input[type="password"]');
  await expect(champs).toHaveCount(3);
  const bouton = dlg.getByRole('button', { name: /changer le mot de passe/i });
  await bouton.scrollIntoViewIfNeeded();
  await expect(bouton).toBeVisible();

  // bloquant : navigation vers /sales -> l'ecran reste
  await page.goto('/sales/create', { waitUntil: 'domcontentloaded' });
  await later(page);
  await expect(dlg).toBeVisible({ timeout: 30_000 });

  // mauvais ancien mot de passe
  const nouveau = `Kz-${Math.random().toString(36).slice(2, 8)}-${Date.now().toString(36)}!Q9`;
  await champs.nth(0).fill('mauvais-ancien-mdp-1');
  await champs.nth(1).fill(nouveau);
  await champs.nth(2).fill(nouveau);
  await bouton.click();
  await expect(dlg.getByText(/actuel incorrect/i)).toBeVisible({ timeout: 30_000 });
  await expect(dlg).toBeVisible();
  await page.screenshot({ path: `${CAP}/cf-${info.project.name}-bug284-ancien-faux.png` });

  // confirmation differente
  await champs.nth(0).fill(temporaire);
  await champs.nth(2).fill(nouveau + 'x');
  await bouton.click();
  await expect(dlg.getByRole('alert')).toContainText(/ne correspond pas/i);

  // succes
  const codes403: string[] = [];
  await champs.nth(2).fill(nouveau);
  await bouton.click();
  await expect(dlg).toHaveCount(0, { timeout: 30_000 });
  await page.waitForTimeout(3_000); // laisse finir les requetes parties pendant l'ecran bloquant
  page.on('response', rs => { if (rs.status() === 403) codes403.push(rs.url()); });
  await page.goto('/sales/create', { waitUntil: 'domcontentloaded' });
  await later(page);
  await expect(page.getByText(/Facturation en Chaîne/i)).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(2_000);
  await page.screenshot({ path: `${CAP}/cf-${info.project.name}-bug284-debloque-sales.png`, fullPage: true });
  info.annotations.push({ type: '403-apres-deblocage', description: codes403.join(' | ') || 'aucun' });
  expect(codes403, '403 apres deblocage').toHaveLength(0);
  // l'ecran ne revient pas apres rechargement
  await page.reload({ waitUntil: 'domcontentloaded' });
  await later(page);
  await expect(dlg).toHaveCount(0);
});

test('BUG-281 : libelle de l\'equipe de la periode en rotation (gerant K3)', async ({ page }, info) => {
  test.setTimeout(300_000);
  await login(page, 'zz_prod_gerant_k3');
  const designer = page.getByRole('button', { name: /confirmer l'équipe/i });
  if (await designer.waitFor({ state: 'visible', timeout: 45_000 }).then(() => true).catch(() => false)) {
    await page.screenshot({ path: `${CAP}/cf-${info.project.name}-bug281-designation.png` });
    await designer.click();
  }
  const lib = page.getByText(/Équipe de service (de la période|du jour)/i).first();
  await lib.waitFor({ state: 'visible', timeout: 60_000 }).catch(() => undefined);
  // la modale « Stock de depart de la releve » s'ouvre a la connexion ou sur /production
  if (!(await lib.isVisible({ timeout: 15_000 }).catch(() => false))) {
    await page.goto('/production', { waitUntil: 'domcontentloaded' });
    await lib.waitFor({ state: 'visible', timeout: 60_000 }).catch(() => undefined);
  }
  await page.screenshot({ path: `${CAP}/cf-${info.project.name}-bug281.png`, fullPage: true });
  const texte = await page.locator('body').innerText();
  info.annotations.push({ type: 'texte', description: (texte.match(/Équipe de service[^\n]*/i) ?? ['absent'])[0] });
  await expect(page.getByText(/relève/i).first()).toBeVisible();
  await expect(page.getByText(/Équipe de service de la période : [AB]/)).toBeVisible();
  await expect(page.getByText(/Équipe de service du jour/)).toHaveCount(0);
  expect(await overflow(page)).toBeLessThanOrEqual(1);
});
