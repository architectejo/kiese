import { test, expect, type APIRequestContext } from '@playwright/test';
import { seConnecter } from '../fixtures/helpers';

/**
 * Envoi direct de pains entre boulangeries (remarque.md, Production §3.3 « Transferts Inter-Boulangeries » :
 * le gerant envoie des pains a une autre boulangerie SANS demande prealable ; BUG-380/382).
 *
 * Parcours : gerant K4 (emettrice) -> onglet Transferts -> « Envoyer des pains » -> validations du formulaire
 * (destinataire manquant, quantite decimale/negative, stock insuffisant) -> recapitulatif -> envoi ; le stock K4
 * baisse tout de suite ; le gerant K3 (receptrice) voit « Envoi direct de K4 », confirme la reception ; le stock K3
 * augmente du meme nombre, le transfert passe CONFIRMED (aucun litige : la cloture de K3 n'est pas bloquee).
 *
 * Prerequis (base jetable, seed e2e `e2e/fixtures/seed/setup9.py` : K4 = 400 pains de 500 FC) : comptes
 * zz_clients_gerant (K4) et zz_prod_gerant_k3 (K3), mot de passe = identifiant. Chaque projet (pos, tablette,
 * bureau, tv) envoie 2 pains ; la note du transfert est unique par execution (rejouable).
 */
test.describe.configure({ mode: 'serial' });

const API = process.env.E2E_API_URL || 'http://localhost:8000';
const EMETTRICE = { user: 'zz_clients_gerant', code: 'K4' };
const RECEPTRICE = { user: 'zz_prod_gerant_k3', code: 'K3' };
const QTE = 2;

interface StockApi { bread_price: number; unit_price: number; qty_available: number }
interface TransferApi { id: string; flow: string; transfer_status: string; notes: string; total_sent: number; from_node_display?: string; to_node_display?: string }

const auth = (t: string) => ({ Authorization: `Bearer ${t}` });
async function token(request: APIRequestContext, username: string): Promise<string> {
  const r = await request.post(`${API}/api/core/auth/login/`, { data: { username, password: username } });
  expect(r.ok(), `connexion API ${username}`).toBeTruthy();
  return (await r.json()).access as string;
}
async function liste<T>(request: APIRequestContext, t: string, url: string): Promise<T[]> {
  const r = await request.get(`${API}${url}`, { headers: auth(t) });
  expect(r.ok(), `${url} : ${r.status()}`).toBeTruthy();
  const j = await r.json();
  return (Array.isArray(j) ? j : j.results) as T[];
}
async function stockDe(request: APIRequestContext, t: string, breadPrice: number): Promise<number> {
  const stocks = await liste<StockApi>(request, t, '/api/production/bread-stocks/?page_size=200');
  return stocks.find(s => s.bread_price === breadPrice)?.qty_available ?? 0;
}

test('envoi direct K4 -> K3 : formulaire, stock deduit, reception confirmee par K3', async ({ page, request }, info) => {
  test.setTimeout(300_000);
  const note = `E2E-ENVOI-DIRECT-${info.project.name}-${Date.now()}`;

  // --- Preparation (API) : categorie de pain avec assez de stock chez l'emettrice -------------------------
  const tokEm = await token(request, EMETTRICE.user);
  const tokRe = await token(request, RECEPTRICE.user);
  const stocksEm = await liste<StockApi>(request, tokEm, '/api/production/bread-stocks/?page_size=200');
  const choix = stocksEm.find(s => s.qty_available >= QTE + 5);
  test.skip(!choix, `Aucune categorie de pain avec au moins ${QTE + 5} pains en stock a ${EMETTRICE.code} : lancer le seed e2e (setup9)`);
  const bp = choix!.bread_price;
  const stockEmAvant = choix!.qty_available;
  const stockReAvant = await stockDe(request, tokRe, bp);

  // --- Emettrice (UI) --------------------------------------------------------------------------------------
  await seConnecter(page, EMETTRICE.user, EMETTRICE.user);
  await page.goto('/production', { waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: /transferts/i }).first().click();
  await expect(page.getByRole('heading', { name: /Transferts Inter-Boulangeries/ })).toBeVisible({ timeout: 30_000 });
  await page.getByRole('button', { name: /^envoyer des pains$/i }).click();

  const modale = page.getByRole('dialog', { name: 'Envoyer des pains' });
  await expect(modale).toBeVisible();
  // Modale visible sans defilement de page : entierement dans la fenetre.
  const boite = await modale.boundingBox();
  const vue = page.viewportSize()!;
  expect(boite, 'boite de la modale').toBeTruthy();
  expect(boite!.y, 'haut de la modale dans la fenetre').toBeGreaterThanOrEqual(0);
  expect(boite!.y + boite!.height, `bas de la modale (${vue.height}px de haut)`).toBeLessThanOrEqual(vue.height + 1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth), 'debordement horizontal').toBeLessThanOrEqual(1);

  const verifier = modale.getByRole('button', { name: /vérifier l'envoi/i });
  const champQte = modale.locator(`#direct-send-q-${bp}`);

  // Validation 1 : pas de destinataire.
  await champQte.fill(String(QTE));
  await verifier.click();
  await expect(modale.getByRole('alert')).toContainText('Sélectionnez la boulangerie destinataire');
  await modale.getByLabel(/envoyer à/i).selectOption({ label: (await modale.locator('option', { hasText: RECEPTRICE.code }).first().innerText()).trim() });
  // L'emettrice ne figure pas dans la liste des destinataires.
  await expect(modale.locator('option', { hasText: new RegExp(`^${EMETTRICE.code} `) })).toHaveCount(0);

  // Validation 2 : quantite decimale ou negative -> bloquee par le champ numerique (min 1, pas 1) :
  // le formulaire ne passe pas au recapitulatif ; puis quantite superieure au stock -> message serveur-like.
  for (const invalide of ['1.5', '-3']) {
    await champQte.fill(invalide);
    await verifier.click();
    expect(await champQte.evaluate((el: HTMLInputElement) => el.checkValidity()), `${invalide} refuse par le champ`).toBe(false);
    await expect(modale.getByText('Total')).toHaveCount(0);
    await expect(verifier).toBeVisible();
  }
  await champQte.fill(String(stockEmAvant + 1));
  await verifier.click();
  await expect(modale.getByRole('alert')).toContainText(/Stock insuffisant/);

  // Envoi valide : recapitulatif puis confirmation.
  await champQte.fill(String(QTE));
  await modale.getByLabel(/note/i).fill(note);
  await verifier.click();
  await expect(modale.getByText(/Envoi à/)).toContainText(RECEPTRICE.code);
  await expect(modale.getByText(/Total/).locator('xpath=..')).toContainText(new RegExp(`${QTE}\\s+pains`));
  await modale.getByRole('button', { name: /confirmer l.envoi/i }).click();
  await expect(modale).toHaveCount(0, { timeout: 30_000 });
  await expect(page.getByRole('status').filter({ hasText: /envoyés à/ })).toContainText(RECEPTRICE.code);
  // L'envoi apparait chez l'emettrice comme « en attente de validation » (lecture seule).
  await expect(page.getByText('Envois directs en attente de validation')).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(note).first()).toBeVisible();

  // Serveur : stock emettrice deduit tout de suite, transfert DIRECT en attente (RESPONDED).
  expect(await stockDe(request, tokEm, bp), 'stock emettrice apres envoi').toBe(stockEmAvant - QTE);
  const transferts = await liste<TransferApi>(request, tokEm, '/api/production/transfers/?page_size=200');
  const t = transferts.find(x => x.notes === note);
  expect(t, 'transfert cree').toBeTruthy();
  expect(t!.flow).toBe('DIRECT');
  expect(t!.transfer_status).toBe('RESPONDED');
  expect(t!.total_sent).toBe(QTE);
  expect(await stockDe(request, tokRe, bp), 'stock receptrice avant validation').toBe(stockReAvant);

  // --- Receptrice (UI) -------------------------------------------------------------------------------------
  await page.evaluate(() => { localStorage.clear(); sessionStorage.clear(); });
  await seConnecter(page, RECEPTRICE.user, RECEPTRICE.user);
  await page.goto('/production', { waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: /transferts/i }).first().click();
  await expect(page.getByText('Réceptions à Confirmer')).toBeVisible({ timeout: 30_000 });
  const carte = page.locator('div').filter({ hasText: note }).filter({ has: page.getByRole('button', { name: /confirmer la réception/i }) }).last();
  await expect(carte).toContainText('Envoi direct de');
  await expect(carte).toContainText('À CONFIRMER');
  await expect(carte).toContainText(/Envoyé spontanément/);
  await expect(carte).toContainText(new RegExp(`envoyé:\\s*${QTE}`));
  await carte.getByRole('button', { name: /confirmer la réception/i }).click();

  // Serveur : confirme sans ecart, stock receptrice +QTE, somme nulle sur le groupe.
  await expect.poll(async () => {
    const l = await liste<TransferApi>(request, tokRe, '/api/production/transfers/?page_size=200');
    return l.find(x => x.id === t!.id)?.transfer_status;
  }, { timeout: 30_000 }).toBe('CONFIRMED');
  expect(await stockDe(request, tokRe, bp), 'stock receptrice apres confirmation').toBe(stockReAvant + QTE);
  expect(await stockDe(request, tokEm, bp), 'stock emettrice inchange apres confirmation').toBe(stockEmAvant - QTE);
});

test('envoi direct : un facturier n\'a pas le bouton et le serveur refuse (403)', async ({ page, request }) => {
  test.setTimeout(180_000);
  const tok = await token(request, 'zz_clients_facturier');
  const r = await request.post(`${API}/api/production/transfers/send/`, {
    headers: auth(tok), data: { to_node: RECEPTRICE.code, lines: [{ bread_price: 1, quantity_sent: 1 }] },
  });
  expect(r.status(), await r.text()).toBe(403);
  expect((await r.json()).detail).toBeTruthy();
  // Cote ecran : pas de page Production pour ce role (menu) ou, si accessible, pas de bouton d'envoi.
  await seConnecter(page, 'zz_clients_facturier', 'zz_clients_facturier');
  await page.goto('/production', { waitUntil: 'domcontentloaded' });
  await expect(page.getByRole('button', { name: /^envoyer des pains$/i })).toHaveCount(0);
});
