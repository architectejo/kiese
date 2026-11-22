import { expect, Page, APIRequestContext } from '@playwright/test';

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
