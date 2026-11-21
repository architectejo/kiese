import { test, expect, Page, APIRequestContext } from '@playwright/test';
import { seConnecter } from '../fixtures/helpers';
import { CAP, API, apiToken, idx, overflow } from '../fixtures/cycle';

/**
 * Verification frontend du lot dev-a (testeur-e2e, 2026-11-21) : BUG-317 (modale « Stock de depart »),
 * BUG-318 (File des Livraisons : Non servi / livraison partielle), BUG-319 (Stock Pains du Jour, Cloture
 * Journaliere), BUG-327 (liste du jour des clients), et BUG-330 cote API.
 * Une boulangerie par largeur (actions uniques par jour) : pos -> K2, tablette -> K5, bureau -> B1.
 * Donnees : base isolee preparee par le script prep28 (clients ZZ28 <nom><noeud>, stock, ventes du jour, facture expiree).
 * Non rejouable sur la meme base (confirmation du stock de depart et cloture de fournee uniques par jour).
 */
test.describe.configure({ mode: 'serial' });
test.beforeEach(({}, info) => { test.skip(info.project.name === 'tv', 'largeurs demandees : 360, 768, 1440'); });

const NODE = ['K2', 'K5', 'B1'];
const GERANT = ['zz_demo_gerant_k2', 'zz_demo_gerant_k5', 'zz_demo_gerant_b1'];
const FACT_A = ['zz_demo_facturier_k2', 'zz_demo_facturier_k5a', 'zz_demo_facturier_b1'];
const BP_ID: Record<number, number> = { 200: 1, 300: 2, 500: 3, 1000: 4 };
const NOMS = ['Alpha', 'Bravo', 'Charlie', 'Delta', 'Echo', 'Foxtrot', 'Golf', 'Hotel', 'India', 'Juliet', 'Kilo', 'Lima', 'Mike', 'Nova'];

const norm = (s: string) => s.replace(/[\s  ]+/g, ' ').trim();
const auth = (tk: string) => ({ Authorization: `Bearer ${tk}` });
const rows = (j: any) => (Array.isArray(j) ? j : j.results ?? []);

async function clientId(request: APIRequestContext, tk: string, code: string) {
  const r = await request.get(`${API}/api/clients/clients/?search=${code}`, { headers: auth(tk) });
  const j = await r.json();
  const c = rows(j).find((x: any) => x.code === code);
  expect(c, `client ${code}`).toBeTruthy();
  return c.id as string;
}

async function creerFacture(request: APIRequestContext, tk: string, code: string, lignes: [number, number][], paye: number) {
  const id = await clientId(request, tk, code);
  const r = await request.post(`${API}/api/sales/invoices/`, {
    headers: auth(tk),
    data: { client: id, payment_type: paye ? 'CASH' : 'CREDIT', payment_amount: String(paye), lines: lignes.map(([p, q]) => ({ bread_price: BP_ID[p], quantity: q })) },
  });
  expect(r.status(), await r.text()).toBe(201);
  return (await r.json()) as any;
}

/* ───────────────────────── BUG-336 : lisibilite des champs de la modale Stock de depart (themes) ───────────────────────── */
for (const theme of ['light', 'dark', 'classic'] as const) {
  test(`BUG-336 : champs de la modale Stock de depart lisibles, theme ${theme}`, async ({ page }, info) => {
    test.setTimeout(120_000);
    const i = idx(info.project.name);
    await page.addInitScript(t => localStorage.setItem('kiese_theme', t), theme);
    await seConnecter(page, GERANT[i], '', { reporterStockDepart: false });
    expect(await page.evaluate(() => document.documentElement.className)).toBe(`theme-${theme}`);
    const dlg = page.getByRole('dialog', { name: /Stock de départ/ });
    await expect(dlg).toBeVisible({ timeout: 40_000 });
    const champs = dlg.locator('input[type="number"]');
    const n = await champs.count();
    expect(n).toBeGreaterThan(0);
    await expect(champs.first()).toHaveClass(/form-input/);

    // Couleurs calculees : fond effectif (premier ancetre non transparent) et texte, rapport de contraste WCAG
    const mesure = (el: Element) => {
      const parse = (s: string) => (s.match(/[\d.]+/g) || []).map(Number);
      const lum = (c: number[]) => { const f = (v: number) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); };
      const cs = getComputedStyle(el);
      let bg = parse(cs.backgroundColor); let node: Element | null = el;
      while (node && (bg.length < 3 || (bg.length === 4 && bg[3] === 0))) { node = node.parentElement; if (node) bg = parse(getComputedStyle(node).backgroundColor); }
      if (!bg || bg.length < 3) bg = [255, 255, 255];
      const fg = parse(cs.color);
      const [a, b] = [lum(fg), lum(bg)];
      return { ratio: (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05), bg: cs.backgroundColor, fg: cs.color, border: cs.borderTopColor, borderW: cs.borderTopWidth, radius: cs.borderTopLeftRadius, h: el.getBoundingClientRect().height };
    };
    // La modale s'anime a l'ouverture (echelle) et la bordure a une transition : on attend des mesures stables.
    const stable = async (loc: any, cle: 'h' | 'border') => {
      let prev = '';
      await expect.poll(async () => { const v = String((await loc.evaluate(mesure))[cle]); const ok = v === prev; prev = v; return ok; }, { timeout: 10_000, intervals: [300] }).toBe(true);
    };
    await stable(champs.first(), 'h');
    const normal = await champs.first().evaluate(mesure);
    console.log(`CHAMP ${theme} ${info.project.name} normal : ${JSON.stringify(normal)}`);
    expect(normal.ratio, 'contraste texte/fond du champ >= 4.5').toBeGreaterThanOrEqual(4.5);
    expect(parseFloat(normal.borderW), 'champ avec bordure visible').toBeGreaterThan(0);
    expect(normal.h, 'cible tactile >= 44 px').toBeGreaterThanOrEqual(44);
    await champs.first().focus();
    await page.screenshot({ path: `${CAP}/b336-${info.project.name}-${theme}-1-normal.png` });

    // Invalide : champ vide -> aria-invalid + bordure rouge (differente de la bordure normale)
    await champs.first().fill('');
    await expect(champs.first()).toHaveAttribute('aria-invalid', 'true');
    await champs.nth(n > 1 ? 1 : 0).focus(); // sort le focus du champ invalide (le focus modifierait la bordure)
    await stable(champs.first(), 'border');
    const inval = await champs.first().evaluate(mesure);
    console.log(`CHAMP ${theme} ${info.project.name} invalide : ${JSON.stringify(inval)}`);
    const [r, g, b] = (inval.border.match(/[\d.]+/g) || []).map(Number);
    expect(r > 150 && r > g + 60 && r > b + 60, `bordure rouge (${inval.border})`).toBeTruthy();
    expect(inval.border).not.toBe(normal.border);
    expect(inval.ratio).toBeGreaterThanOrEqual(4.5);
    await page.screenshot({ path: `${CAP}/b336-${info.project.name}-${theme}-2-invalide.png` });
    expect(await overflow(page)).toBeLessThanOrEqual(1);
    // On reporte pour laisser la confirmation aux tests suivants
    await dlg.getByRole('button', { name: /plus tard|annuler/i }).first().click();
    await expect(dlg).toHaveCount(0);
  });
}

/* ───────────────────────── BUG-330 (API) + BUG-317 (modale) ───────────────────────── */
test('BUG-330 API puis BUG-317 : modale Stock de depart sans negatif', async ({ page, request }, info) => {
  test.setTimeout(240_000);
  const i = idx(info.project.name);
  const tk = await apiToken(request, GERANT[i]);

  // BUG-330 : le stock reel de la categorie 1000 est negatif (-20) mais la proposition de l'API ne l'est jamais.
  const bs = await (await request.get(`${API}/api/production/bread-stocks/`, { headers: auth(tk) })).json();
  const neg = rows(bs).filter((s: any) => Number(s.qty_available) < 0);
  expect(neg.length, 'precondition : un stock reel negatif').toBeGreaterThan(0);
  const oc = await (await request.get(`${API}/api/production/opening-confirmation/`, { headers: auth(tk) })).json();
  expect(oc.categories.length).toBeGreaterThan(0);
  for (const c of oc.categories) expect(Number(c.qty_proposed), `qty_proposed ${c.label}`).toBeGreaterThanOrEqual(0);
  // BUG-317 (API) : un negatif est toujours refuse avec detail en francais.
  const neg400 = await request.post(`${API}/api/production/opening-confirmation/`, {
    headers: auth(tk), data: { team: 'A', lines: [{ bread_price: oc.categories[0].bread_price, qty: -1 }] },
  });
  expect(neg400.status()).toBe(400);
  expect((await neg400.json()).detail).toMatch(/négatif/i);

  // Simulation d'une reponse serveur ancienne (qty_proposed negatif) : l'ecran doit ramener a 0.
  const mockGet = async (route: any) => {
    if (route.request().method() !== 'GET') return route.fallback();
    const resp = await route.fetch();
    const j = await resp.json();
    j.categories[j.categories.length - 1].qty_proposed = -20;
    await route.fulfill({ response: resp, json: j });
  };
  await page.route('**/api/production/opening-confirmation/', mockGet);
  await seConnecter(page, GERANT[i], '', { reporterStockDepart: false });
  const dlg = page.getByRole('dialog', { name: /Stock de départ/ });
  await expect(dlg).toBeVisible({ timeout: 40_000 });
  const lbl = (re: RegExp) => dlg.getByLabel(re);
  const dernier = oc.categories[oc.categories.length - 1].label as string;
  await expect(dlg.getByLabel(`Stock de départ — ${dernier}`)).toHaveValue('0');
  await page.unroute('**/api/production/opening-confirmation/', mockGet);

  const in500 = lbl(/Stock de départ — Pain 500/);
  const valider = dlg.getByRole('button', { name: /^Valider/ });
  const initial500 = await in500.inputValue();
  expect(Number(initial500)).toBeGreaterThanOrEqual(0);

  // Touches interdites : rien ne s'ecrit
  await in500.click();
  await page.keyboard.press('Control+a');
  await page.keyboard.press('Backspace');
  for (const k of ['-', ',', '.', 'e', '+']) await page.keyboard.press(k);
  await expect(in500).toHaveValue('');
  // Champ vide : bordure/aria-invalid, message, Valider grise
  await expect(in500).toHaveAttribute('aria-invalid', 'true');
  await expect(dlg.getByText(/Chaque quantité doit être un nombre entier/)).toBeVisible();
  await expect(valider).toBeDisabled();

  // Collage nettoye
  const coller = (t: string) => in500.evaluate((el, txt) => {
    const dt = new DataTransfer(); dt.setData('text/plain', txt);
    el.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true }));
  }, t);
  await coller('-5');
  await expect(in500).toHaveValue('5');
  await coller('12,5');
  await expect(in500).toHaveValue('125');
  // Depassement du plafond serveur
  await coller('99999999999');
  await expect(in500).toHaveAttribute('aria-invalid', 'true');
  await expect(valider).toBeDisabled();

  // Valeurs valides
  await in500.fill(initial500 || '10');
  await expect(valider).toBeEnabled();
  await lbl(/Stock de départ — Pain 1000/).fill('12');

  // Mise en page : pas de debordement de page, bouton Valider dans la fenetre
  expect(await overflow(page)).toBeLessThanOrEqual(1);
  const box = await valider.boundingBox();
  const vp = page.viewportSize()!;
  expect(box && box.y >= 0 && box.y + box.height <= vp.height, 'Valider visible sans defilement de page').toBeTruthy();
  await page.screenshot({ path: `${CAP}/b317-${info.project.name}-1-modale.png` });

  // 400 force : le detail serveur s'affiche
  const mockPost = async (route: any) => {
    if (route.request().method() !== 'POST') return route.fallback();
    await route.fulfill({ status: 400, json: { detail: 'Le stock de départ ne peut pas être négatif.' } });
  };
  await page.route('**/api/production/opening-confirmation/', mockPost);
  await valider.click();
  await expect(dlg.getByText('Le stock de départ ne peut pas être négatif.')).toBeVisible();
  await page.unroute('**/api/production/opening-confirmation/', mockPost);

  // Succes
  await valider.click();
  await expect.poll(async () => (await (await request.get(`${API}/api/production/opening-confirmation/`, { headers: auth(tk) })).json()).needs_confirmation, { timeout: 30_000 }).toBe(false);
  await page.screenshot({ path: `${CAP}/b317-${info.project.name}-2-apres-validation.png` });
  const fermer = page.getByRole('dialog', { name: /Stock de départ/ }).getByRole('button', { name: 'Fermer' });
  if (await fermer.isVisible().catch(() => false)) await fermer.click();
});

/* ───────────────────────── BUG-318 : File des Livraisons ───────────────────────── */
async function ouvrirSales(page: Page) {
  await page.goto('/sales', { waitUntil: 'domcontentloaded' });
  await expect(page.getByText('File des Livraisons', { exact: false }).first()).toBeVisible({ timeout: 60_000 });
}
async function totalFacture(page: Page) {
  await expect(page.getByText(/factures chargées/)).toHaveCount(0, { timeout: 60_000 });
  const t = norm(await page.locator('body').innerText());
  const m = t.match(/TOTAL FACTURÉ\s*([\d ]+) FC/);
  expect(m, 'carte TOTAL FACTURE').toBeTruthy();
  return Number(m![1].replace(/ /g, ''));
}

test('BUG-318 : livraison partielle, total recalcule, recu avec commande initial', async ({ page, request }, info) => {
  test.setTimeout(240_000);
  const i = idx(info.project.name);
  const tk = await apiToken(request, FACT_A[i]);
  const inv = await creerFacture(request, tk, `${NODE[i]}-0809`, [[300, 10], [500, 4]], 2000);
  await seConnecter(page, FACT_A[i]);
  await ouvrirSales(page);
  const q300 = page.getByLabel(/Quantité servie.*300/);
  const q500 = page.getByLabel(/Quantité servie.*500/);
  await expect(q300).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText('servi 10 sur 10')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Confirmer livraison', exact: true })).toBeVisible();
  // borne au commande
  await q300.fill('99');
  await expect(q300).toHaveValue('10');
  await q300.fill('7');
  await expect(page.getByText('servi 7 sur 10')).toBeVisible();
  await expect(page.getByText(/Total servi/)).toContainText(/4\s?100 FC/);
  await expect(page.getByText(/commandé : 5\s?000 FC/)).toBeVisible();
  await expect(q500).toHaveValue('4');
  const partielle = page.getByRole('button', { name: 'Confirmer livraison partielle' });
  await expect(partielle).toBeVisible();
  expect(await overflow(page)).toBeLessThanOrEqual(1);
  await page.screenshot({ path: `${CAP}/b318-${info.project.name}-1-partielle.png` });
  await partielle.click();
  const imprimer = page.getByRole('button', { name: /Confirmer & imprimer/ });
  if (await imprimer.isVisible({ timeout: 2_000 }).catch(() => false)) await imprimer.click();
  // Recu thermique : quantites servies + commande initial
  const recu = page.locator('table').filter({ hasText: 'COMMANDÉ INITIAL' });
  await expect(recu).toBeVisible({ timeout: 30_000 });
  const txt = norm(await recu.innerText());
  console.log(`RECU ${info.project.name} :: ${txt}`);
  expect(txt).toMatch(/COMMANDÉ INITIAL \(livraison partielle\) 5 000/);
  expect(txt).toMatch(/Pain 300 FC\s*7\b|\b7\b.*Pain 300|Pain 300.*\b7\b/);
  expect(txt).toMatch(/4 100/);
  await page.screenshot({ path: `${CAP}/b318-${info.project.name}-2-recu.png`, fullPage: true });
  // Cote serveur : le servi suit
  const d = await (await request.get(`${API}/api/sales/invoices/${inv.id}/`, { headers: auth(tk) })).json();
  expect(d.status).toBe('DELIVERED');
  expect(Number(d.order_total)).toBe(4100);
  expect(Number(d.initial_order_total)).toBe(5000);
  await page.getByRole('button', { name: 'Fermer' }).first().click();
});

test('BUG-318 : tout a 0 -> orientation vers Non servi, motif, badge, total facture', async ({ page, request }, info) => {
  test.setTimeout(240_000);
  const i = idx(info.project.name);
  const tk = await apiToken(request, FACT_A[i]);
  await creerFacture(request, tk, `${NODE[i]}-0810`, [[300, 5]], 0);
  await seConnecter(page, FACT_A[i]);
  await ouvrirSales(page);
  const q = page.getByLabel(/Quantité servie.*300/);
  await expect(q).toBeVisible({ timeout: 30_000 });
  const avant = await totalFacture(page);
  await q.fill('0');
  const livrer = page.getByRole('button', { name: /^Confirmer livraison/ });
  await expect(livrer).toBeDisabled();
  await expect(page.getByText(/Aucun pain servi : utilisez « Non servi »/)).toBeVisible();
  expect(await overflow(page)).toBeLessThanOrEqual(1);
  await page.screenshot({ path: `${CAP}/b318-${info.project.name}-3-tout-zero.png` });
  await page.getByRole('button', { name: 'Non servi', exact: true }).click();
  await expect(page.getByText(/Déclarer la facture .* « Non servi » \?/)).toBeVisible();
  const motif = page.getByLabel('Motif non servi');
  await expect(motif).toHaveAttribute('maxlength', '200');
  await motif.fill('Client absent (test e2e)');
  await page.screenshot({ path: `${CAP}/b318-${info.project.name}-4-motif.png` });
  await page.getByRole('button', { name: /Confirmer « Non servi »/ }).click();
  await expect(page.getByText('NON SERVI').first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/motif : Client absent \(test e2e\)/)).toBeVisible();
  await expect(page.getByText(/aucun pain remis/i).first()).toBeVisible();
  await expect(page.getByRole('button', { name: /Confirmer livraison/ })).toHaveCount(0);
  const apres = await totalFacture(page);
  console.log(`TOTAL FACTURE ${info.project.name} : avant=${avant} apres=${apres}`);
  expect(apres, 'la valeur non servie (1 500 FC) sort de TOTAL FACTURE').toBe(avant - 1500);
  expect(await overflow(page)).toBeLessThanOrEqual(1);
  await page.screenshot({ path: `${CAP}/b318-${info.project.name}-5-non-servi.png` });
});

test('BUG-318 : double action (409) et expiration (Expiree -> non servie, jamais supprimee)', async ({ page, request, context }, info) => {
  test.setTimeout(240_000);
  const i = idx(info.project.name);
  const tk = await apiToken(request, FACT_A[i]);
  const inv = await creerFacture(request, tk, `${NODE[i]}-0811`, [[300, 4]], 0);
  await seConnecter(page, FACT_A[i]);
  await ouvrirSales(page);
  await expect(page.getByLabel(/Quantité servie.*300/)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/Expire dans \d+h\d{2}/)).toBeVisible();
  // 2e onglet : Non servi
  const p2 = await context.newPage();
  await p2.setViewportSize(page.viewportSize()!);
  await ouvrirSales(p2);
  await p2.getByRole('button', { name: 'Non servi', exact: true }).click();
  await p2.getByRole('button', { name: /Confirmer « Non servi »/ }).click();
  await expect(p2.getByText('NON SERVI').first()).toBeVisible({ timeout: 30_000 });
  await p2.close();
  // 1er onglet (carte perimee) : livraison -> 409
  const r409 = page.waitForResponse(r => r.url().includes(`/invoices/${inv.id}/deliver`));
  await page.getByRole('button', { name: 'Confirmer livraison', exact: true }).click();
  const imp409 = page.getByRole('button', { name: /Confirmer & imprimer/ });
  if (await imp409.isVisible({ timeout: 3_000 }).catch(() => false)) await imp409.click();
  expect((await r409).status()).toBe(409);
  const detail = (await (await r409).json()).detail as string;
  console.log(`409 ${info.project.name} detail serveur : ${detail}`);
  await expect(page.getByText('NON SERVI').first()).toBeVisible({ timeout: 30_000 });
  const visible = await page.getByText(detail, { exact: false }).count();
  console.log(`409 ${info.project.name} detail affiche a l'ecran : ${visible > 0}`);
  test.info().annotations.push({ type: 'BUG-335', description: `detail du 409 affiche a l'ecran : ${visible > 0}` });
  // BUG-335 : le detail serveur du 409 reste affiche (bandeau persistant sur la carte)
  expect(visible, "detail du 409 affiche a l'ecran").toBeGreaterThan(0);
  await page.screenshot({ path: `${CAP}/b318-${info.project.name}-6-409.png` });
  // BUG-334 : une carte NON SERVI ne doit pas porter « Distribue »
  const carteNs = page.locator('div').filter({ hasText: 'Non servi — aucun pain remis' }).filter({ hasText: `Kilo${NODE[i]}` }).last();
  test.info().annotations.push({ type: 'BUG-334', description: `« Distribue » sur carte NON SERVI : ${(await carteNs.innerText()).includes('Distribué')}` });
  expect(await carteNs.innerText()).not.toContain('Distribué');

  // Expiration affichee : reponse simulee (facture creee il y a 11 h 59 min 56 s) -> compte a rebours ecoule apres quelques secondes.
  // (Une facture deja > 12 h est retiree de la file par le client, `keepInvoice` : le texte ne peut s'afficher que sur ce cas.)
  const inv2 = await creerFacture(request, tk, `${NODE[i]}-0812`, [[300, 2]], 0);
  const vieux = async (route: any) => {
    const resp = await route.fetch();
    const body = await resp.text();
    let j: any; try { j = JSON.parse(body); } catch { return route.fulfill({ response: resp, body }); }
    const old = new Date(Date.now() - (12 * 3600 - 4) * 1000).toISOString();
    const patch = (x: any) => { if (x && x.id === inv2.id) x.created_at = old; };
    if (Array.isArray(j)) j.forEach(patch); else if (j.results) j.results.forEach(patch);
    await route.fulfill({ response: resp, json: j });
  };
  await page.route(/\/api\/sales\/invoices\/(\?.*)?$|pending_deliveries/, vieux);
  await ouvrirSales(page);
  await expect(page.getByText(/Expire dans 0h0\d/)).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(6_000); // compte a rebours : delai reel de 4 s a ecouler (pas une attente de synchronisation)
  await page.getByRole('button', { name: /Diminuer/ }).click(); // provoque un nouveau rendu
  await expect(page.getByText('Expirée — sera déclarée non servie')).toBeVisible({ timeout: 30_000 });
  await page.screenshot({ path: `${CAP}/b318-${info.project.name}-7-expiree.png` });
  await page.unroute(/\/api\/sales\/invoices\/(\?.*)?$|pending_deliveries/, vieux);
  // nettoyage : on la declare non servie (la facture n'est pas reellement expiree)
  await ouvrirSales(page);
  await page.getByRole('button', { name: 'Non servi', exact: true }).click();
  await page.getByRole('button', { name: /Confirmer « Non servi »/ }).click();
  await expect(page.getByText('NON SERVI').first()).toBeVisible({ timeout: 30_000 });

  // Expiration reelle (facture creee puis datee de 13 h par le script de preparation) : non servie, jamais supprimee
  const liste = await (await request.get(`${API}/api/sales/invoices/?page_size=100`, { headers: auth(tk) })).json();
  const mike = rows(liste).find((x: any) => String(x.client_display ?? '').includes(`Mike${NODE[i]}`));
  expect(mike, 'facture expiree conservee').toBeTruthy();
  expect(mike.status).toBe('NOT_SERVED');
});

/* ───────────────────────── BUG-327 : liste du jour ───────────────────────── */
async function ouvrirListe(page: Page) {
  await page.goto('/cloture-journaliere', { waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: /Liste du jour \(clients\)/ }).click();
  const dlg = page.getByRole('dialog', { name: /Liste du jour/ });
  await expect(dlg).toBeVisible({ timeout: 30_000 });
  await expect(dlg.getByText('Chargement de la liste du jour…')).toHaveCount(0, { timeout: 30_000 });
  return dlg;
}
const ligne = (dlg: any, nom: string) => dlg.locator('tbody tr').filter({ hasText: nom });

test('BUG-327 : liste du jour (modale, totaux, non servis, equipe, recherche, tri, BP credit)', async ({ page, request, context }, info) => {
  test.setTimeout(300_000);
  const i = idx(info.project.name);
  const n = NODE[i];
  const tk = await apiToken(request, GERANT[i]);
  const oc = await (await request.get(`${API}/api/production/opening-confirmation/`, { headers: auth(tk) })).json();
  const date = oc.work_date ?? oc.date;
  const apiList = async (team = '') => (await (await request.get(`${API}/api/production/daily-closure/clients/?date=${date}${team ? `&team=${team}` : ''}`, { headers: auth(tk) })).json()) as any;
  const ref = await apiList();
  page.on('pageerror', e => console.log('PAGEERROR', e.message));
  page.on('console', m => { if (m.type() === 'error') console.log('CONSOLE', m.text().slice(0, 300)); });

  await seConnecter(page, GERANT[i]);
  const dlg = await ouvrirListe(page);
  await expect(dlg.getByText(/Totaux — \d+ client\(s\)/)).toBeVisible();
  expect(await overflow(page), 'pas de debordement horizontal de la page').toBeLessThanOrEqual(1);
  await page.screenshot({ path: `${CAP}/b327-${info.project.name}-1-modale.png` });

  // Valeurs (ventes preparees : Alpha 3 tours 7 500 / 5 500 / CM 1 875 ; BP avant 0, actuelle 2 000)
  const alpha = ligne(dlg, `Alpha${n}`);
  const ta = norm(await alpha.innerText());
  console.log(`LIGNE ${info.project.name} ${ta}`);
  expect(ta).toMatch(/\b3\b.*7 500 FC.*5 500 FC.*1 875 FC.*0 FC.*2 000 FC.*Régulier/i);
  // BP negative en credit (Golf : -27 000)
  const golf = norm(await ligne(dlg, `Golf${n}`).innerText());
  expect(golf).toMatch(/-?27 000 FC \(crédit\)/);
  await expect(ligne(dlg, `Golf${n}`).getByTitle('Crédit en faveur du client').first()).toBeVisible();
  // Types
  expect(norm(await ligne(dlg, `Bravo${n}`).innerText())).toMatch(/Solde/i);
  expect(norm(await ligne(dlg, `Charlie${n}`).innerText())).toMatch(/Cash/i);
  expect(norm(await ligne(dlg, `Foxtrot${n}`).innerText())).toMatch(/Remboursement/i);
  // Non servis a part (Delta = NS par code), pas dans le tableau principal
  await expect(dlg.getByRole('heading', { name: /Non servis/ })).toBeVisible();
  expect(await ligne(dlg, `Delta${n}`).count()).toBe(1); // une seule ligne : celle de la section Non servis
  const nsTable = dlg.locator('table').nth(1);
  await expect(nsTable).toContainText(`Delta${n}`);
  // Totaux de pied = API et = somme des lignes
  const pied = norm(await dlg.locator('tfoot tr').first().innerText());
  const f = (v: number) => Math.round(v).toLocaleString('fr-FR');
  expect(pied).toContain(`Totaux — ${ref.totals.clients} client(s)`);
  expect(pied).toContain(norm(`${f(ref.totals.order_value)} FC`));
  expect(pied).toContain(norm(`${f(ref.totals.paid)} FC`));
  expect(pied).toContain(norm(`${f(ref.totals.commission)} FC`));
  const nbLignes = await dlg.locator('table').first().locator('tbody tr').count();
  expect(nbLignes).toBe(ref.totals.clients);

  // Filtre equipe B : Bravo (equipe A) disparait, Alpha n'a plus qu'un tour
  const refB = await apiList('B');
  await dlg.getByLabel('Filtrer par équipe').selectOption('B');
  await expect(ligne(dlg, `Bravo${n}`)).toHaveCount(0, { timeout: 20_000 });
  await expect(dlg.getByText(`Totaux — ${refB.totals.clients} client(s)`)).toBeVisible();
  const alphaB = norm(await ligne(dlg, `Alpha${n}`).innerText());
  expect(alphaB).toMatch(/\b1\b.*1 500 FC/);
  await dlg.getByLabel('Filtrer par équipe').selectOption('A');
  await expect(ligne(dlg, `Bravo${n}`)).toHaveCount(1, { timeout: 20_000 });
  await dlg.getByLabel('Filtrer par équipe').selectOption('');
  await expect(ligne(dlg, `Golf${n}`)).toHaveCount(1, { timeout: 20_000 });

  // Recherche locale (nom partiel, code)
  const rech = dlg.getByPlaceholder(/Rechercher par nom ou code/);
  await rech.fill('golf');
  await expect(dlg.locator('table').first().locator('tbody tr')).toHaveCount(1);
  await rech.fill(`${n}-0801`);
  await expect(ligne(dlg, `Alpha${n}`)).toHaveCount(1);
  await expect(dlg.locator('table').first().locator('tbody tr')).toHaveCount(1);
  await rech.fill('zzzzinconnu');
  await expect(dlg.getByText('Aucun client ne correspond à la recherche.')).toBeVisible();
  await rech.fill('');

  // Tri par colonne (Verse)
  const th = dlg.getByRole('columnheader', { name: /^Versé/ });
  await th.click();
  await expect(th).toHaveAttribute('aria-sort', 'descending');
  const premier = norm(await dlg.locator('table').first().locator('tbody tr').first().innerText());
  expect(premier).toContain(`Alpha${n}`); // 5 500 FC = le plus eleve
  await th.click();
  await expect(th).toHaveAttribute('aria-sort', 'ascending');
  expect(norm(await dlg.locator('table').first().locator('tbody tr').last().innerText())).toContain(`Alpha${n}`);

  // Excel
  const dl = page.waitForEvent('download');
  await dlg.getByRole('button', { name: /Excel/ }).click();
  const fichier = await dl;
  expect(fichier.suggestedFilename()).toMatch(/^liste-du-jour-.*\.xlsx$/);
  // Impression (fenetre d'impression ouverte avec la liste)
  const popup = context.waitForEvent('page');
  await dlg.getByRole('button', { name: /Imprimer/ }).click();
  const pp = await popup;
  await pp.waitForLoadState('domcontentloaded');
  await expect(pp.locator('h1')).toHaveText(/LISTE DU JOUR/);
  await expect(pp.locator('body')).toContainText(`Alpha${n}`);
  await pp.close();
  await page.screenshot({ path: `${CAP}/b327-${info.project.name}-2-filtres.png` });

  // « Voir plus » : reponses simulees (count 600, 2e page) -- le vrai cas > 500 clients n'est pas constituable ici
  await page.keyboard.press('Escape');
  const voirPlus = async (route: any) => {
    const u = new URL(route.request().url());
    const resp = await route.fetch();
    const j = await resp.json();
    j.count = 600;
    if (u.searchParams.get('page') === '2') {
      j.page = 2; j.results = [{ client: 'zz-sim', client_code: `${n}-0999`, client_name: 'ZZ28 SimulePage2', tours: 1, order_value: 100, paid: 100, commission: 25, bp_before: 0, bp_current: 0, sale_types: ['REGULIER'] }];
    }
    await route.fulfill({ response: resp, json: j });
  };
  await page.route('**/api/production/daily-closure/clients/**', voirPlus);
  const dlg2 = await ouvrirListe(page);
  const plus = dlg2.getByRole('button', { name: /Voir plus \(\d+ \/ 600\)/ });
  await expect(plus).toBeVisible();
  await plus.click();
  await expect(dlg2.getByText('ZZ28 SimulePage2')).toBeVisible({ timeout: 20_000 });
  await page.screenshot({ path: `${CAP}/b327-${info.project.name}-3-voir-plus.png` });
  await page.unroute('**/api/production/daily-closure/clients/**', voirPlus);

  // Etats vide et erreur (reponses simulees)
  await page.keyboard.press('Escape');
  const vide = async (route: any) => {
    const resp = await route.fetch(); const j = await resp.json();
    j.results = []; j.count = 0; j.non_servis = { count: 0, results: [] };
    j.totals = { clients: 0, tours: 0, order_value: 0, paid: 0, commission: 0 };
    await route.fulfill({ response: resp, json: j });
  };
  await page.route('**/api/production/daily-closure/clients/**', vide);
  const dlg3 = await ouvrirListe(page);
  await expect(dlg3.getByText('Aucun client servi pour ce jour.')).toBeVisible();
  await expect(dlg3.getByText('Aucun non servi pour ce jour.')).toBeVisible();
  await page.unroute('**/api/production/daily-closure/clients/**', vide);
  await page.keyboard.press('Escape');
  const erreur = async (route: any) => route.fulfill({ status: 400, json: { detail: 'Date invalide (test simulé).' } });
  await page.route('**/api/production/daily-closure/clients/**', erreur);
  await page.getByRole('button', { name: /Liste du jour \(clients\)/ }).click();
  await expect(page.getByRole('dialog', { name: /Liste du jour/ }).getByText('Date invalide (test simulé).')).toBeVisible({ timeout: 20_000 });
  await page.unroute('**/api/production/daily-closure/clients/**', erreur);
});

test('BUG-327 : facturier sans bouton, API 403', async ({ page, request }, info) => {
  const i = idx(info.project.name);
  const tk = await apiToken(request, FACT_A[i]);
  const r = await request.get(`${API}/api/production/daily-closure/clients/?node=${NODE[i]}`, { headers: auth(tk) });
  expect(r.status()).toBe(403);
  await seConnecter(page, FACT_A[i]);
  await page.goto('/cloture-journaliere', { waitUntil: 'domcontentloaded' });
  await page.waitForLoadState('networkidle').catch(() => undefined);
  await expect(page.getByRole('button', { name: /Liste du jour \(clients\)/ })).toHaveCount(0);
});

/* ───────────────────────── BUG-319 : Stock Pains du Jour / Cloture Journaliere ───────────────────────── */
test('BUG-319 : Vendu seul avant cloture, Restes + Total produit + ecart apres ; Produit = « — » avant', async ({ page, request }, info) => {
  test.setTimeout(300_000);
  const i = idx(info.project.name);
  const tk = await apiToken(request, GERANT[i]);
  const oc = await (await request.get(`${API}/api/production/opening-confirmation/`, { headers: auth(tk) })).json();
  const date = oc.work_date ?? oc.date;
  // Fournee par sacs (1 sac = 210 000 FC theorique). Reprise : fournee deja declaree/cloturee par une passe precedente
  // (la cloture est unique par jour) -> on ne rejoue que la verification apres cloture.
  const s = await request.post(`${API}/api/production/sessions/`, { headers: auth(tk), data: { team: 'A', date, flour_sacks_used: '1.00' } });
  const reprise = s.status() !== 201;
  if (!reprise) expect(s.status(), await s.text()).toBe(201);
  const sid = reprise ? '' : ((await s.json()).id as string);

  await seConnecter(page, GERANT[i]);
  const section = page.locator('div.glass-card').filter({ has: page.getByRole('heading', { name: /Stock Pains du Jour/ }) });
  const th = page.getByRole('columnheader', { name: /^Produit$/i });
  const colonne = async () => {
    const k = await th.evaluate(el => Array.from(el.parentElement!.children).indexOf(el));
    return page.locator('table').filter({ has: th }).locator('tbody tr').evaluateAll((trs, ix) => trs.map(tr => (tr.children[ix] as HTMLElement).innerText.trim()), k);
  };
  const stocks = async () => rows(await (await request.get(`${API}/api/production/bread-stocks/`, { headers: auth(tk) })).json());

  if (!reprise) {
    await page.goto('/production', { waitUntil: 'domcontentloaded' });
    await expect(section).toBeVisible({ timeout: 60_000 });
    await expect(section.getByText(/Pendant la journée on compte les pains vendus/)).toBeVisible();
    const head = section.locator('thead th');
    await expect(head.filter({ hasText: /Vendu/i })).toBeVisible({ timeout: 30_000 });
    await expect(head.filter({ hasText: /Restes déclarés/i })).toHaveCount(0);
    await expect(head.filter({ hasText: /Total produit/i })).toHaveCount(0);
    expect(norm(await section.innerText())).not.toMatch(/\d+ dispo/i);
    const v = await stocks();
    const sold300 = v.find((b: any) => String(b.bread_price_display).includes('300')).sold_qty as number;
    expect(sold300).toBeGreaterThan(0);
    expect(norm(await section.locator('tbody tr').filter({ hasText: /300/ }).innerText())).toContain(String(sold300));
    expect(await overflow(page)).toBeLessThanOrEqual(1);
    await page.screenshot({ path: `${CAP}/b319-${info.project.name}-1-stock-avant.png`, fullPage: true });

    await page.goto('/cloture-journaliere', { waitUntil: 'domcontentloaded' });
    await expect(th).toBeVisible({ timeout: 60_000 });
    const avant = await colonne();
    console.log(`PRODUIT avant ${info.project.name} : ${JSON.stringify(avant)}`);
    expect(avant.length).toBeGreaterThan(0);
    for (const c of avant) expect(c).toBe('—');
    await page.screenshot({ path: `${CAP}/b319-${info.project.name}-2-cloture-avant.png`, fullPage: true });

    const cats = v.map((b: any) => ({ bread_price: b.bread_price, quantity: String(b.bread_price_display).includes('1000') ? 12 : 3000 }));
    const c = await request.post(`${API}/api/production/sessions/${sid}/close/`, { headers: auth(tk), data: { remaining: cats } });
    expect(c.status(), await c.text()).toBe(200);
  }

  const apres = await stocks();
  const rapport = await (await request.get(`${API}/api/production/daily-closure/?date=${date}`, { headers: auth(tk) })).json();
  const ecart = Number(rapport.totals.ecart_production_fc);
  console.log(`API apres cloture ${info.project.name} : ${JSON.stringify(apres.map((b: any) => [b.bread_price_display, b.sold_qty, b.remaining_qty, b.produced_total, b.closed]))} ecart=${ecart}`);

  await page.goto('/production', { waitUntil: 'domcontentloaded' });
  await expect(section).toBeVisible({ timeout: 60_000 });
  await expect(section.locator('thead th').filter({ hasText: /Restes déclarés/i })).toBeVisible({ timeout: 30_000 });
  await expect(section.locator('thead th').filter({ hasText: /Total produit/i })).toBeVisible();
  const ths = await section.locator('thead th').allInnerTexts();
  const ixV = ths.findIndex(t => /Vendu/i.test(t)), ixR = ths.findIndex(t => /Restes/i.test(t)), ixT = ths.findIndex(t => /Total produit/i.test(t));
  const fmt = (v: number) => v.toLocaleString('fr-FR').replace(/[\s\u202f\u00a0]/g, ' ');
  for (const b of apres) {
    const tr = section.locator('tbody tr').filter({ hasText: String(b.bread_price_display) }).first();
    const cells = (await tr.locator('td').allInnerTexts()).map(norm);
    expect(cells[ixV], `Vendu ${b.bread_price_display}`).toContain(fmt(b.sold_qty));
    expect(cells[ixR], `Restes ${b.bread_price_display}`).toContain(fmt(b.remaining_qty));
    expect(cells[ixT], `Total produit ${b.bread_price_display}`).toContain(fmt(b.produced_total));
  }
  const libelle = ecart === 0 ? 'aucun écart' : `${ecart < 0 ? 'manquant' : 'excédent'} de`;
  await expect(section.getByText(/Écart sacs :/)).toContainText(libelle, { timeout: 30_000 });
  expect(norm(await section.innerText())).not.toMatch(/\d+ dispo/i);
  expect(await overflow(page)).toBeLessThanOrEqual(1);
  await page.screenshot({ path: `${CAP}/b319-${info.project.name}-3-stock-apres.png`, fullPage: true });

  await page.goto('/cloture-journaliere', { waitUntil: 'domcontentloaded' });
  await expect(th).toBeVisible({ timeout: 60_000 });
  await expect.poll(async () => (await colonne()).every(c => c !== '—'), { timeout: 30_000 }).toBe(true);
  console.log(`PRODUIT apres ${info.project.name} : ${JSON.stringify(await colonne())}`);
  await page.screenshot({ path: `${CAP}/b319-${info.project.name}-4-cloture-apres.png`, fullPage: true });
});

// BUG-334 / BUG-335 : assertions activees dans le test 409 ci-dessus (corrections a rejouer par testeur-e2e).
