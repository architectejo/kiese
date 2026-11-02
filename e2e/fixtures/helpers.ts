import { Page, expect } from '@playwright/test';

/**
 * Connecte un utilisateur via le formulaire `/login`.
 *
 * Note sélecteurs : `Login.tsx` place les `<label>` en frères des `<input>`
 * (pas de `htmlFor`/`id`), donc `getByLabel` ne fonctionne pas. On utilise le
 * `placeholder` en attendant un `data-testid` dédié — voir ticket BUG ouvert
 * dans le rapport de cette session pour en demander l'ajout à dev-frontend.
 */
export async function seConnecter(page: Page, username: string, password: string) {
  await page.goto('/login');
  await page.getByPlaceholder('Ex: pierre').fill(username);
  await page.getByPlaceholder('••••••••').fill(password);
  await page.getByRole('button', { name: /se connecter/i }).click();
  await expect(page).toHaveURL(/\/dashboard/, { timeout: 15_000 });
}

/**
 * Sur les largeurs POS/téléphone (≤768px, cf. CLAUDE.md §4 responsive), le menu
 * latéral est un tiroir hors-écran (`.dashboard-sidebar { left: -100% }`,
 * `frontend/src/styles/index.css`) ouvert par le bouton hamburger
 * (`title="Menu de navigation"`). Playwright considère ce tiroir « visible »
 * (il n'est pas `display:none`) mais un `.click()` y échoue car l'élément reste
 * hors du viewport réel — il faut ouvrir le tiroir avant d'interagir avec son
 * contenu.
 */
async function ouvrirMenuMobileSiNecessaire(page: Page) {
  const hamburger = page.getByTitle('Menu de navigation');
  if (await hamburger.isVisible().catch(() => false)) {
    await hamburger.click();
  }
}

export async function seDeconnecter(page: Page) {
  await ouvrirMenuMobileSiNecessaire(page);
  await page.getByRole('button', { name: /déconnexion/i }).click();
  await expect(page).toHaveURL(/\/login/, { timeout: 10_000 });
}
