import { expect, Page, Locator, APIRequestContext } from '@playwright/test';

export const CAP = '../docs/qa/captures';
export const API = process.env.E2E_API_URL || 'http://localhost:8000';

/** Connexion UI avec relance : le premier essai echoue parfois (serveur de dev lent). */
export async function login(page: Page, user: string, pwd?: string) {
  const mdp = pwd ?? user; // comptes zz_* : mot de passe = identifiant (jamais consigne)
  for (let essai = 0; essai < 3; essai++) {
    await page.goto('/login', { waitUntil: 'domcontentloaded', timeout: 90_000 });
    // Purge systematique de la session precedente (sinon /login redirige vers /dashboard apres un instant
    // de rendu et le champ disparait en cours de saisie ; la modale « Stock de depart » masque alors la page).
    await page.evaluate(() => { localStorage.clear(); sessionStorage.clear(); }).catch(() => undefined);
    await page.goto('/login', { waitUntil: 'domcontentloaded', timeout: 90_000 });
    await page.getByPlaceholder('Ex: pierre').fill(user);
    await page.getByPlaceholder('••••••••').fill(mdp);
    await page.getByRole('button', { name: /se connecter/i }).click();
    try {
      await expect(page).toHaveURL(/\/dashboard|\/sales|\/clients|\/production/, { timeout: 40_000 });
      return;
    } catch (e) {
      if (essai === 2) throw e;
    }
  }
}

export async function later(page: Page) {
  const b = page.getByRole('button', { name: /plus tard/i });
  await b.waitFor({ state: 'visible', timeout: 12_000 }).then(() => b.click()).catch(() => undefined);
}

export async function overflow(page: Page) {
  return page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
}

export async function apiToken(request: APIRequestContext, user: string, pwd?: string) {
  const r = await request.post(`${API}/api/core/auth/login/`, { data: { username: user, password: pwd ?? user } });
  expect(r.ok(), `login API ${user}`).toBeTruthy();
  return (await r.json()).access as string;
}

export function idx(projectName: string) {
  return Math.max(0, ['pos', 'tablette', 'bureau', 'tv'].indexOf(projectName));
}

/**
 * Flux reel facture -> livraison -> recu (CLAUDE.md 5.2) : le bouton de la file est « Confirmer livraison »
 * (« Confirmer livraison partielle » si une quantite servie a ete reduite). Si le reglage « ventes passees »
 * est actif, une modale « Confirmer la livraison » (date optionnelle) demande en plus « Confirmer & imprimer ».
 * Le recu (« BON DE LIVRAISON ») s'ouvre ensuite. `carte` restreint la recherche du bouton a une facture.
 */
export async function confirmerLivraison(page: Page, carte?: Locator) {
  const portee = carte ?? page;
  await portee.getByRole('button', { name: /^confirmer livraison( partielle)?$/i }).first().click();
  const recu = page.getByText(/BON DE LIVRAISON/);
  const modale = page.getByRole('button', { name: /confirmer & imprimer/i });
  await expect(recu.or(modale).first()).toBeVisible({ timeout: 30_000 });
  if (await modale.isVisible().catch(() => false)) await modale.click();
  await expect(recu).toBeVisible({ timeout: 30_000 });
}
