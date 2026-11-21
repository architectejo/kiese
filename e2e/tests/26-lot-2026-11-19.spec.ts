import { test, expect, Page, Locator, APIRequestContext, Browser } from '@playwright/test';
import { CAP, API, login as loginBase, later, overflow, idx, apiToken } from '../fixtures/cycle';

/**
 * Verification (testeur-e2e, 2026-11-19) des tickets frontend BUG-302, 303, 304, 305, 306, 307.
 * Comptes zz_e307_* (mot de passe = identifiant), boulangeries K6 (gerant/facturier/livreur) et K5.
 * Largeurs : POS 360, tablette 768, bureau 1440 (le projet « tv » est ignore).
 * Donnees fictives uniquement (clients « ZZE307 ... »).
 */
test.describe.configure({ mode: 'serial' });

const SUF = ['pos', 'tab', 'bur', 'bur'];
const REST = [11, 12, 13, 13]; // reste du jour declare a la cloture, par largeur
const SAC = ['1.11', '1.12', '1.13', '1.13'];
const nb = (s: string) => s.replace(/[\s  ]/g, '').replace(/−/g, '-');
const P = { p300: 2, p500: 3, p1000: 4 };

test.beforeEach(({}, info) => {
  test.skip(info.project.name === 'tv', 'largeurs demandees : 360, 768, 1440');
});

async function login(page: Page, user: string) {
  // l'ecran de connexion met parfois > 10 s a s'afficher (serveur de dev a froid)
  await page.goto('/login', { waitUntil: 'domcontentloaded', timeout: 90_000 });
  await page.getByPlaceholder('Ex: pierre').waitFor({ state: 'visible', timeout: 60_000 }).catch(() => undefined);
  await loginBase(page, user);
}

const aujourdhui = () => new Date().toLocaleDateString('sv-SE'); // AAAA-MM-JJ local
const hier = () => new Date(Date.now() - 86400_000).toLocaleDateString('sv-SE');

type Rec = Record<string, unknown>;
const H = (t: string) => ({ Authorization: `Bearer ${t}` });
const liste = (j: unknown): Rec[] => (Array.isArray(j) ? j : ((j as { results: Rec[] }).results ?? []));

async function fermerOuvertes(request: APIRequestContext, tg: string) {
  const r = await request.get(`${API}/api/production/sessions/?page_size=200`, { headers: H(tg) });
  for (const s of liste(await r.json())) {
    if (s.is_closed) continue;
    if (!/ZZ$/.test(String(s.declared_by_display ?? '')) && !String(s.notes ?? '').includes('ZZE307')) continue; // jamais les donnees des autres
    const c = await request.post(`${API}/api/production/sessions/${s.id}/close/`, { headers: H(tg), data: { remaining: [] } });
    expect(c.ok(), `fermeture ${s.id} : ${await c.text()}`).toBeTruthy();
  }
}

const PROD = [ // une seule fournee par equipe et par jour en rotation : K1 equipe B sert aux trois largeurs, dans l'ordre pos -> tablette -> bureau
  { k: 'K1', g: 'zz_e307_ger1', f: 'zz_e307_fac1', team: 'B' },
  { k: 'K1', g: 'zz_e307_ger1', f: 'zz_e307_fac1', team: 'B' },
  { k: 'K1', g: 'zz_e307_ger1', f: 'zz_e307_fac1', team: 'B' },
  { k: 'K1', g: 'zz_e307_ger1', f: 'zz_e307_fac1', team: 'B' },
];

async function designer(request: APIRequestContext, t: string, k: string, team: string) {
  const r = await request.post(`${API}/api/production/team-assignment/`, { headers: H(t), data: { node: k, team } });
  expect(r.ok(), await r.text()).toBeTruthy();
}

async function creerClient(request: APIRequestContext, tg: string, prenom: string, nom: string) {
  const r = await request.post(`${API}/api/clients/clients/`, { headers: H(tg), data: { first_name: prenom, last_name: nom } });
  expect(r.ok(), await r.text()).toBeTruthy();
  return (await r.json()) as { id: string; code: string };
}

async function vendre(request: APIRequestContext, tf: string, client: string, prix: number, qte: number) {
  const val = qte * (prix === P.p1000 ? 1000 : prix === P.p500 ? 500 : 300);
  const c = await request.post(`${API}/api/sales/invoices/`, {
    headers: H(tf), data: { client, payment_type: 'CASH', payment_amount: String(val), lines: [{ bread_price: prix, quantity: qte }] },
  });
  expect(c.status(), await c.text()).toBe(201);
  const inv = await c.json();
  const d = await request.post(`${API}/api/sales/invoices/${inv.id}/deliver/`, { headers: H(tf) });
  expect(d.ok(), await d.text()).toBeTruthy();
}

async function sansDebordement(page: Page, info: { project: { name: string } }, quoi: string) {
  expect(await overflow(page), `debordement horizontal : ${quoi} (${info.project.name})`).toBeLessThanOrEqual(1);
}

async function annonces(page: Page) {
  // annonce de cloture automatique (K6 : creneaux hors rotation depasses a cette heure)
  const b = page.getByRole('button', { name: /J'ai compris/ });
  while (await b.first().isVisible().catch(() => false)) { await b.first().click(); await page.waitForTimeout(300); }
}

async function allerProduction(page: Page) {
  await page.goto('/production', { waitUntil: 'domcontentloaded' });
  await later(page);
  await page.getByRole('button', { name: /J'ai compris/ }).first().waitFor({ state: 'visible', timeout: 6_000 }).catch(() => undefined);
  await annonces(page);
  await expect(page.getByTestId('batch-in-progress-panel')).toBeVisible({ timeout: 30_000 });
}

/* ------------------------------------------------------------------ */
/* Donnees communes                                                    */
/* ------------------------------------------------------------------ */
test('(0) preparation : session d\'hier cloturee avec reste du jour 7, sessions ouvertes fermees', async ({ request }) => {
  const tg = await apiToken(request, 'zz_e307_ger6');
  await fermerOuvertes(request, tg);
  const r = await request.get(`${API}/api/production/sessions/?date=${hier()}&page_size=50`, { headers: H(tg) });
  let deHier = liste(await r.json()).find(s => String(s.notes ?? '').includes('ZZE307'));
  if (!deHier) {
    const c = await request.post(`${API}/api/production/sessions/`, {
      headers: H(tg), data: { date: hier(), team: 'A', flour_sacks_used: '1.5', notes: 'ZZE307 hier' },
    });
    expect(c.ok(), await c.text()).toBeTruthy();
    deHier = await c.json();
    const f = await request.post(`${API}/api/production/sessions/${deHier!.id}/close/`, { headers: H(tg), data: { remaining: [{ bread_price: P.p500, quantity: 7 }] } });
    expect(f.ok(), await f.text()).toBeTruthy();
  }
  // le reste du jour de la veille (7 pains a 500 FC) est un instantane cree hors test (ORM, K6, equipe A)
  const q = await request.get(`${API}/api/production/daily-closure/?node=K6&date=${hier()}`, { headers: H(tg) });
  const cat = ((await q.json()).categories as Rec[]).find(c => c.bread_price === P.p500)!;
  expect(cat.reste_du_jour_jour, 'precondition : reste du jour de la veille = 7').toBe(7);
});

/* ------------------------------------------------------------------ */
/* BUG-305 : Detail Fournee sans categories repetees                   */
/* ------------------------------------------------------------------ */
test('(305) Detail Fournee : une seule ligne par categorie, total inchange', async ({ page, request }, info) => {
  test.setTimeout(180_000);
  const tg = await apiToken(request, 'zz_e307_ger6');
  // Fournee K6 du jour preparee hors test (ORM) : 500 FC x10 (DECLARED) + 500 FC x5 (CARRYOVER) + 300 FC x4
  const sess = liste(await (await request.get(`${API}/api/production/sessions/?date=${aujourdhui()}&page_size=50`, { headers: H(tg) })).json())
    .find(x => String(x.notes ?? '').includes('ZZE307 dup'))!;
  expect(sess, 'fournee ZZE307 dup presente').toBeTruthy();
  const lignes500 = (sess.lines as Rec[]).filter(l => l.bread_price === P.p500);
  expect(lignes500.length, 'precondition : 2 lignes serveur pour 500 FC').toBe(2);
  const total = (sess.total_fc_produced as number) || 0;
  test.info().annotations.push({ type: 'api', description: `lignes 500 FC cote serveur : ${lignes500.map(l => `${l.quantity} ${l.source}`).join(' + ')} ; total_fc_produced=${total}` });

  await login(page, 'zz_e307_ger6');
  await allerProduction(page);
  await page.getByText(/Éq\.B/).filter({ hasText: aujourdhui() }).first().click();
  const modal = page.getByRole('dialog', { name: 'Détail Fournée' });
  await expect(modal).toBeVisible();
  await expect(modal.getByText('Production par Catégorie')).toBeVisible();
  const lignes = modal.locator('tbody tr');
  expect(await lignes.filter({ hasText: 'Pain 500 FC' }).count(), 'lignes affichees « Pain 500 FC »').toBe(1);
  expect(await lignes.count()).toBe(2); // 500 FC et 300 FC
  const l500 = (await lignes.filter({ hasText: 'Pain 500 FC' }).innerText()).replace(/\s+/g, ' ');
  test.info().annotations.push({ type: 'ligne-500', description: l500 });
  // BUG-310 : le reste d'hier (CARRYOVER) n'est plus additionne au tableau : 10 declares, pas 15
  expect(nb(l500)).toContain('10');
  expect(nb(l500)).not.toMatch(/(^|[^0-9])15([^0-9]|$)/);
  const pied = nb(await modal.locator('tfoot').innerText());
  test.info().annotations.push({ type: 'pied', description: `${pied} (API total_fc_produced=${total})` });
  expect(pied).toContain(String(total));
  // somme des lignes du tableau = total du pied (BUG-310)
  let somme = 0; let pains = 0;
  for (const tr of await lignes.all()) {
    const tds = await tr.locator('td').allInnerTexts();
    pains += Number(nb(tds[1])); somme += Number(nb(tds[3]).replace(/FC/, ''));
  }
  expect(somme, 'somme des lignes (FC) = total du pied').toBe(total);
  expect(pains, 'somme des quantites = pains produits').toBe(14);
  expect(total).toBe(6200);
  // le reste d'hier est liste a part, hors tableau
  await expect(modal.getByText(/Reste d.hier confirmé \(non compté dans le total\)/)).toBeVisible();
  expect(nb(await modal.getByText(/Reste d.hier confirmé/).innerText())).toMatch(/5×/);
  await expect(modal.locator('table').getByText(/Reste d.hier/)).toHaveCount(0);
  await sansDebordement(page, info, 'detail fournee');
  await page.screenshot({ path: `${CAP}/e307-${info.project.name}-305-detail.png`, fullPage: true });
});

/* ------------------------------------------------------------------ */
/* BUG-304 : Reste d'Hier / Reste du Jour par jour                     */
/* ------------------------------------------------------------------ */
test('(304) Cloture Journaliere : colonnes Reste du Jour / Reste d Hier, tiret si non declare, export, impression', async ({ page, request }, info) => {
  test.setTimeout(240_000);
  const tg = await apiToken(request, 'zz_e307_ger6');
  const rapport = async (date: string) => {
    const r = await request.get(`${API}/api/production/daily-closure/?node=K6&date=${date}`, { headers: H(tg) });
    expect(r.ok(), await r.text()).toBeTruthy();
    const cat = ((await r.json()).categories as Rec[]).find(c => c.bread_price === P.p500)!;
    return { jour: cat.reste_du_jour_jour as number | null, hier: cat.reste_du_hier_jour as number | null };
  };
  const apiAjd = await rapport(aujourdhui());
  const apiHier = await rapport(hier());
  const jm2 = new Date(Date.now() - 2 * 86400_000).toLocaleDateString('sv-SE');
  const apiJm2 = await rapport(jm2);
  test.info().annotations.push({ type: 'api', description: `aujourd'hui ${JSON.stringify(apiAjd)} ; hier ${JSON.stringify(apiHier)} ; J-2 ${JSON.stringify(apiJm2)}` });
  expect(apiHier.jour, 'reste du jour de la veille declare = 7').toBe(7);
  expect(apiAjd.hier, 'reste d hier d aujourd hui = -7 (oppose du reste de la veille)').toBe(-7);
  expect(apiJm2.jour, 'J-2 sans declaration').toBeNull();

  await login(page, 'zz_e307_ger6');
  await page.goto('/cloture-journaliere', { waitUntil: 'domcontentloaded' });
  await later(page);
  await annonces(page);
  const th = page.locator('table thead th');
  await expect(th.filter({ hasText: /^Reste du Jour$/ })).toHaveCount(1, { timeout: 30_000 });
  await expect(th.filter({ hasText: /^Reste d'Hier$/ })).toHaveCount(1);
  expect(await th.filter({ hasText: /Reste.*(Éq|Équipe|\bA\b|\bB\b)|(Éq|Équipe).*Reste/ }).count()).toBe(0);
  const cellules = async () => {
    const tbl = page.locator('table').filter({ has: page.locator('th', { hasText: /^Reste du Jour$/ }) });
    const heads = (await tbl.locator('thead th').allTextContents()).map(h => h.trim());
    const jour = heads.findIndex(h => h === 'Reste du Jour');
    const hierI = heads.findIndex(h => h === "Reste d'Hier");
    const lig = tbl.locator('tbody tr').filter({ has: page.locator('td', { hasText: /^Pain 500 FC$/ }) }).first();
    await expect(lig).toBeVisible();
    const tds = await lig.locator('td').allInnerTexts();
    return { jour: nb(tds[jour]), hier: nb(tds[hierI]) };
  };
  const attendu = (n: number | null) => (n === null ? '—' : String(n));
  let c = await cellules();
  expect(c.jour, 'reste du jour (aujourd hui, API)').toBe(attendu(apiAjd.jour));
  expect(c.hier, 'reste d hier (aujourd hui, API)').toBe(String(apiAjd.hier).replace('-', '-'));
  await sansDebordement(page, info, 'cloture journaliere');
  await page.screenshot({ path: `${CAP}/e307-${info.project.name}-304-jour.png`, fullPage: true });

  // export Excel et impression (jour courant)
  const [dl] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: /exporter en excel/i }).click()]);
  await dl.saveAs(`${CAP}/e307-${info.project.name}-304-export.xlsx`);
  test.info().annotations.push({ type: 'export', description: dl.suggestedFilename() });
  const [popup] = await Promise.all([page.waitForEvent('popup'), page.getByRole('button', { name: /imprimer/i }).first().click()]);
  await popup.waitForLoadState('domcontentloaded');
  const html = await popup.content();
  expect(html).toContain('Reste du Jour');
  expect(html).toContain("Reste d'Hier");
  expect(html).not.toMatch(/Reste[^<]{0,20}(Éq|Équipe)/);
  await popup.close();

  // veille : reste du jour 7 ; J-2 : tiret (non declare)
  const aller = async (iso: string) => {
    await page.getByRole('button', { name: /\d{2}\/\d{2}\/\d{4}/ }).first().click();
    const cal = page.getByRole('dialog', { name: 'Choisir une date' });
    await expect(cal).toBeVisible();
    await cal.getByRole('button', { name: new RegExp(`^${Number(iso.slice(8))}$`) }).click();
    await expect(cal).toBeHidden();
    await expect(page.getByRole('button', { name: /exporter en excel/i })).toBeEnabled();
  };
  await aller(hier());
  await expect.poll(async () => (await cellules()).jour, { timeout: 20_000 }).toBe('7');
  await aller(jm2);
  await expect.poll(async () => (await cellules()).jour, { timeout: 20_000 }).toBe('—');
  c = await cellules();
  expect(c.jour).toBe('—');
  await sansDebordement(page, info, 'cloture journaliere J-2');
  await page.screenshot({ path: `${CAP}/e307-${info.project.name}-304-jm2.png`, fullPage: true });
});

/* ------------------------------------------------------------------ */
/* BUG-302 : 8 cartes -> modale de details                             */
/* ------------------------------------------------------------------ */
const CARTES = [
  'Total du Jour', 'Net Produit', 'Écart / Facture', 'Nombre de Sacs Produits',
  'Moyenne Produit / Sac', 'Tarif Vente (fixe)', 'Écart / Production', 'Pains Produits / Facturés',
];

test('(302) Cloture Journaliere : 8 cartes ouvrent une modale (clic, clavier, Echap)', async ({ page }, info) => {
  test.setTimeout(240_000);
  await login(page, 'zz_e307_ger6');
  await page.goto('/cloture-journaliere', { waitUntil: 'domcontentloaded' });
  await later(page);
  await expect(page.getByRole('button', { name: 'Total du Jour : voir le détail' })).toBeVisible({ timeout: 30_000 });
  expect(await page.getByRole('button', { name: /: voir le détail/ }).count()).toBe(8);
  for (let k = 0; k < CARTES.length; k++) {
    const nom = CARTES[k];
    const carte = page.getByRole('button', { name: `${nom} : voir le détail` });
    if (k % 2 === 0) await carte.click();
    else { await carte.focus(); await page.keyboard.press(k % 4 === 1 ? 'Enter' : 'Space'); }
    const d = page.getByRole('dialog', { name: nom });
    await expect(d, `modale ${nom}`).toBeVisible();
    const box = await d.boundingBox();
    const vw = page.viewportSize()!.width;
    expect(box!.x).toBeGreaterThanOrEqual(-1);
    expect(box!.x + box!.width, `modale ${nom} dans l'ecran`).toBeLessThanOrEqual(vw + 1);
    await sansDebordement(page, info, `modale ${nom}`);
    if (k === 0 || k === 6) await page.screenshot({ path: `${CAP}/e307-${info.project.name}-302-${k}.png` });
    await page.keyboard.press('Escape');
    await expect(d).toBeHidden();
  }
  // bouton Fermer
  await page.getByRole('button', { name: 'Net Produit : voir le détail' }).click();
  await page.getByRole('dialog', { name: 'Net Produit' }).getByRole('button', { name: 'Fermer', exact: true }).last().click();
  await expect(page.getByRole('dialog', { name: 'Net Produit' })).toBeHidden();
  // atteignable au clavier (Tab depuis la premiere carte)
  await page.getByRole('button', { name: 'Total du Jour : voir le détail' }).focus();
  await page.keyboard.press('Tab');
  await expect(page.getByRole('button', { name: 'Net Produit : voir le détail' })).toBeFocused();
});

/* ------------------------------------------------------------------ */
/* BUG-306 : declaration par sacs, objectif, progression, vente        */
/* ------------------------------------------------------------------ */
function hslVersRgb(h: number, s: number, l: number) {
  s /= 100; l /= 100;
  const k = (n: number) => (n + h / 30) % 12;
  const a = s * Math.min(l, 1 - l);
  const f = (n: number) => l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
  return [Math.round(255 * f(0)), Math.round(255 * f(8)), Math.round(255 * f(4))];
}
const TEINTES: Record<string, number[]> = {
  rouge: hslVersRgb(0, 72, 51), orange: hslVersRgb(25, 95, 53), jaune: hslVersRgb(48, 96, 46), vert: hslVersRgb(142, 71, 38),
};

async function lireBarre(page: Page) {
  const bar = page.getByRole('progressbar', { name: 'Avancement de la fournée' });
  const texte = (await bar.getAttribute('aria-valuetext')) ?? '';
  const rgb = await bar.locator('div').first().evaluate(el => getComputedStyle(el).backgroundColor);
  const m = rgb.match(/\d+/g)!.map(Number);
  return { texte, rgb: m.slice(0, 3) };
}
function teinte(rgb: number[]) {
  let best = ''; let d = 1e9;
  for (const [nom, t] of Object.entries(TEINTES)) {
    const dd = Math.abs(t[0] - rgb[0]) + Math.abs(t[1] - rgb[1]) + Math.abs(t[2] - rgb[2]);
    if (dd < d) { d = dd; best = nom; }
  }
  return d <= 12 ? best : `inconnue(${rgb})`;
}

test('(306a) formulaire de declaration par sacs seuls (K6, tous ecrans) : apercu de l objectif, validation', async ({ page, request }, info) => {
  test.setTimeout(180_000);
  const tg = await apiToken(request, 'zz_e307_ger6');
  const noeud = liste(await (await request.get(`${API}/api/core/nodes/`, { headers: H(tg) })).json()).find(n => n.code === 'K6')!;
  const valeurSac = Number(noeud.sac_value_fc);
  await login(page, 'zz_e307_ger6');
  await allerProduction(page);
  const panneau = page.getByTestId('batch-in-progress-panel');
  await expect(panneau.getByText('Déclaration de Fournée')).toBeVisible();
  await expect(panneau.getByText(/Aucune fournée en cours/)).toBeVisible();
  // la valeur du sac demarre a 200 000 FC le temps du chargement de la config : on attend la valeur du serveur
  await expect.poll(async () => nb(await panneau.innerText()), { timeout: 20_000 }).toContain(nb(`1 sac = ${valeurSac.toLocaleString('fr-FR')} FC`));
  // les sacs sont la seule saisie obligatoire (le reste est facultatif) : aucun champ « pains par categorie »
  await expect(panneau.getByLabel(/Nombre de sacs de farine/)).toBeVisible();
  await expect(panneau.getByText(/Consommables utilisés \(facultatif\)/)).toBeVisible();
  await panneau.getByRole('button', { name: 'Enregistrer la Fournée' }).click();
  await expect(panneau.getByRole('alert')).toContainText(/nombre de sacs/i);
  // apercu « Montant a atteindre » = sacs x valeur du sac, y compris decimal
  for (const sacs of ['2', '0.25', '1.5']) {
    await panneau.getByLabel(/Nombre de sacs de farine/).fill(sacs);
    const attendu = Math.round(parseFloat(sacs) * valeurSac);
    await expect(panneau.getByText(/Montant à atteindre :/)).toBeVisible();
    expect(nb(await panneau.getByText(/Montant à atteindre :/).innerText())).toContain(nb(attendu.toLocaleString('fr-FR')));
  }
  await panneau.getByLabel('Levure en paquets').fill('0.25');
  await panneau.getByLabel('Huile en litres').fill('1.5');
  await panneau.getByLabel('Sel en grammes').fill('500');
  await sansDebordement(page, info, 'declaration');
  await page.screenshot({ path: `${CAP}/e307-${info.project.name}-306a-declaration.png`, fullPage: true });
  // on ne soumet pas : K6 est hors rotation, le serveur cloturerait la fournee des l'heure de creneau depassee
});

const unite = 1000; // pains de 1000 FC

/** Livre `qte` pains de 1000 FC (vente CASH + livraison) puis actualise et attend la teinte attendue. */
async function livrerEtVerifier(
  page: Page, request: APIRequestContext, tf: string, client: string, panneau: Locator,
  qte: number, attendu: string, pct: RegExp, shot: string, auto = false,
) {
  if (qte > 0) await vendre(request, tf, client, P.p1000, qte);
  if (!auto) await panneau.getByRole('button', { name: 'Actualiser la fournée en cours' }).click();
  await expect.poll(async () => teinte((await lireBarre(page)).rgb), { timeout: auto ? 40_000 : 15_000, message: `teinte attendue ${attendu}` }).toBe(attendu);
  const b = await lireBarre(page);
  expect(b.texte).toMatch(pct);
  expect(b.texte).toContain(`(${attendu})`);
  await page.screenshot({ path: shot });
}

async function etatK1(request: APIRequestContext, tg: string) {
  const l = liste(await (await request.get(`${API}/api/production/sessions/?date=${aujourdhui()}&page_size=50`, { headers: H(tg) })).json());
  return l.find(s => s.team === 'B' && !s.is_closed && s.auto_track) ?? null;
}

test('(306) fournee en cours (K1, rotation, equipe B) : objectif, progression rouge/orange/jaune/verte, augmentation, rafraichissement', async ({ page, request }, info) => {
  test.setTimeout(420_000);
  const i = idx(info.project.name);
  const pr = PROD[i];
  const tg = await apiToken(request, pr.g);
  const tf = await apiToken(request, pr.f);
  const noeud = liste(await (await request.get(`${API}/api/core/nodes/`, { headers: H(tg) })).json()).find(n => n.code === pr.k)!;
  const valeurSac = Number(noeud.sac_value_fc);
  const rx = (n: number) => new RegExp(nb(n.toLocaleString('fr-FR')).replace(/(\d)(?=(\d{3})+$)/g, '$1[\\s\\u202f\\u00a0]?') + '[\\s\\u202f\\u00a0]FC');
  const cl = await creerClient(request, tg, 'ZZE307', `Prog${SUF[i]}`);

  if (i === 0) { // 360 px : declaration par l'ecran puis progression par les ventes
    await fermerOuvertes(request, tg);
    await designer(request, tg, pr.k, pr.team);
    await login(page, pr.g);
    await allerProduction(page);
    const panneau = page.getByTestId('batch-in-progress-panel');
    await expect(panneau.getByText('Déclaration de Fournée')).toBeVisible();
    await expect(panneau.getByTestId('service-team-locked')).toContainText(`Équipe de service : ${pr.team}`);
    await panneau.getByLabel(/Nombre de sacs de farine/).fill('2');
    expect(nb(await panneau.getByText(/Montant à atteindre :/).innerText())).toContain(nb((2 * valeurSac).toLocaleString('fr-FR')));
    await panneau.getByRole('button', { name: 'Enregistrer la Fournée' }).click();
    await expect(panneau.getByText('Fournée en cours')).toBeVisible({ timeout: 20_000 });
    await expect(panneau.getByTestId('batch-objective')).toHaveText(rx(2 * valeurSac));
    expect(nb(await panneau.innerText())).toContain('2sacsdefarine');
    await expect(panneau.getByText(/Aucune vente livrée pour le moment/)).toBeVisible();
    const b = await lireBarre(page);
    expect(teinte(b.rgb), `0 % : ${b.texte}`).toBe('rouge');
    await sansDebordement(page, info, 'fournee en cours');
    await page.screenshot({ path: `${CAP}/e307-${info.project.name}-306-0pct.png`, fullPage: true });
    // augmentation invalide (<= sacs declares)
    await panneau.getByLabel(/Augmenter les sacs/).fill('0'); // BUG-355 : le champ AJOUTE des sacs
    await panneau.getByRole('button', { name: 'Ajouter les sacs' }).click();
    await expect(panneau.getByRole('alert')).toContainText(/supérieur à 0/);
    await panneau.getByLabel(/Augmenter les sacs/).fill('');

    const obj = 2 * valeurSac;
    const q1 = Math.floor(obj * 0.24 / unite);
    await livrerEtVerifier(page, request, tf, cl.id, panneau, q1, 'rouge', /à 24 %/, `${CAP}/e307-pos-306-rouge.png`);
    await expect(panneau.getByText(`${q1.toLocaleString('fr-FR')} pains`)).toBeVisible();
    const q2 = Math.ceil(obj * 0.25 / unite) - q1; // 25 % pile : orange, rafraichissement automatique (sans clic)
    await livrerEtVerifier(page, request, tf, cl.id, panneau, q2, 'orange', /à 25 %/, `${CAP}/e307-pos-306-orange.png`, true);
    const q3 = Math.floor(obj * 0.5 / unite) - q1 - q2;
    await livrerEtVerifier(page, request, tf, cl.id, panneau, q3, 'jaune', /à 50 %/, `${CAP}/e307-pos-306-jaune.png`);
    const q4 = Math.floor(obj * 0.99 / unite) - q1 - q2 - q3;
    await livrerEtVerifier(page, request, tf, cl.id, panneau, q4, 'jaune', /à 99 %/, `${CAP}/e307-pos-306-jaune99.png`);
    const q5 = Math.ceil(obj / unite) - q1 - q2 - q3 - q4;
    await livrerEtVerifier(page, request, tf, cl.id, panneau, q5, 'vert', /à 100 %/, `${CAP}/e307-pos-306-vert.png`);
    await expect(panneau.getByText(`${(q1 + q2 + q3 + q4 + q5).toLocaleString('fr-FR')} pains`)).toBeVisible();
    await sansDebordement(page, info, 'fournee a 100 %');
    return;
  }

  // 768 et 1440 px : la fournee ouverte par le passage 360 px est reprise
  const s0 = await etatK1(request, tg);
  expect(s0, 'fournee K1 equipe B ouverte par le passage 360 px').toBeTruthy();
  await login(page, pr.g);
  await allerProduction(page);
  const panneau = page.getByTestId('batch-in-progress-panel');
  await expect(panneau.getByText('Fournée en cours')).toBeVisible({ timeout: 30_000 });
  await sansDebordement(page, info, 'fournee en cours');
  const sacsAvant = Number(s0!.flour_sacks_used);
  const livre = Number(s0!.progress_value_fc);
  test.info().annotations.push({ type: 'etat-initial', description: `${sacsAvant} sacs, livre ${livre} FC, progress ${String(s0!.progress_pct)} %` });

  if (i === 1) { // 768 px : l'augmentation des sacs recalcule objectif et teinte (vert -> jaune -> orange -> rouge)
    await expect(panneau.getByTestId('batch-objective')).toHaveText(rx(sacsAvant * valeurSac));
    expect(teinte((await lireBarre(page)).rgb)).toBe('vert');
    let totalSacs = sacsAvant;
    const augmenter = async (n: number, teinteAttendue: string, pct: RegExp) => {
      await panneau.getByLabel(/Augmenter les sacs/).fill(String(n - totalSacs)); // BUG-355 : on saisit l'AJOUT
      totalSacs = n;
      await panneau.getByRole('button', { name: 'Ajouter les sacs' }).click();
      await expect(panneau.getByTestId('batch-objective')).toHaveText(rx(n * valeurSac), { timeout: 20_000 });
      await expect.poll(async () => teinte((await lireBarre(page)).rgb), { timeout: 15_000 }).toBe(teinteAttendue);
      expect((await lireBarre(page)).texte).toMatch(pct);
      await page.screenshot({ path: `${CAP}/e307-tab-306-${n}sacs-${teinteAttendue}.png`, fullPage: true });
    };
    await augmenter(3, 'jaune', /à 67 %/);
    await augmenter(5, 'orange', /à 40 %/);
    await augmenter(9, 'rouge', /à 22 %/);
    await sansDebordement(page, info, 'fournee a 9 sacs');
    return;
  }

  // 1440 px : remontee par les ventes depuis 9 sacs (rouge) puis cloture (test 303)
  const obj = sacsAvant * valeurSac;
  const dejaPains = Math.round(livre / unite);
  expect(teinte((await lireBarre(page)).rgb), `etat initial ${sacsAvant} sacs`).toBe('rouge');
  const cibles: Array<[number, string, RegExp]> = [[0.25, 'orange', /à 25 %/], [0.5, 'jaune', /à 50 %/], [1, 'vert', /à 100 %/]];
  let cumul = dejaPains;
  for (const [f, t, re] of cibles) {
    const q = Math.ceil(obj * f / unite) - cumul;
    cumul += q;
    await livrerEtVerifier(page, request, tf, cl.id, panneau, q, t, re, `${CAP}/e307-bur-306-${t}.png`, f === 0.5);
  }
  const sF = (await etatK1(request, tg))!;
  // pains de 1000 FC affiches = lignes serveur de la fournee (d'autres livraisons K1 de la meme periode, ex. pains de 200 FC, n'y comptent pas)
  const q1000 = (sF.lines as Rec[]).filter(l => l.bread_price === P.p1000).reduce((a, l) => a + Number(l.quantity), 0);
  await expect(panneau.getByText(`${q1000.toLocaleString('fr-FR')} pains`)).toBeVisible();
  await sansDebordement(page, info, 'fournee a 100 % (9 sacs)');
  expect(Number(sF.flour_sacks_used)).toBe(sacsAvant);
  expect(Number(sF.objective_fc ?? sF.theoretical_yield)).toBe(obj);
});

/* ------------------------------------------------------------------ */
/* BUG-303 : negatifs refuses a « Cloturer la Fournee » (sur la fournee en cours laissee par le test 306) */
/* ------------------------------------------------------------------ */
test('(303) cloture : saisie negative impossible, refus serveur en francais, cloture valide', async ({ page, request }, info) => {
  test.setTimeout(240_000);
  const i = idx(info.project.name);
  const pr = PROD[i];
  await login(page, pr.g);
  await allerProduction(page);
  await page.getByText(new RegExp(`Éq\.${pr.team}`)).filter({ hasText: aujourdhui() }).first().click();
  await page.getByRole('dialog', { name: 'Détail Fournée' }).getByRole('button', { name: 'Clôturer la fournée' }).click();
  const m = page.getByRole('dialog', { name: 'Clôturer la Fournée' });
  await expect(m).toBeVisible();
  const champ = m.getByLabel(/Reste du jour — Pain 1000 FC/);
  await expect(champ).toBeVisible();
  // pas de bouton « ± »
  await expect(m.getByRole('button', { name: /Changer le signe/ })).toHaveCount(0);
  // saisie « -3 » : le signe est ecarte (jamais de valeur negative a l'ecran)
  await champ.fill('');
  await champ.pressSequentially('-3');
  const v = await champ.inputValue();
  expect(v.includes('-'), `valeur saisie « -3 » devenue « ${v} »`).toBeFalsy();
  test.info().annotations.push({ type: 'observation', description: `saisie « -3 » -> champ affiche « ${v} »` });
  await champ.fill('');
  await champ.pressSequentially('-');
  expect((await champ.inputValue()).includes('-')).toBeFalsy();
  // refus serveur : on force un negatif dans la requete, le message francais du serveur doit s'afficher
  await champ.fill('5');
  let corps = '';
  await page.route('**/api/production/sessions/*/close/', async route => {
    corps = route.request().postData() ?? '';
    await route.continue({ postData: JSON.stringify({ remaining: [{ bread_price: P.p1000, quantity: -3 }] }) });
  });
  await m.getByRole('button', { name: 'Confirmer la clôture' }).click();
  const alerte = m.getByText(/Le reste du jour ne peut pas être négatif/i); // (le texte d'aide « Le reste ne peut pas être négatif » est un autre element)
  await expect(alerte).toBeVisible({ timeout: 15_000 });
  const msg = (await alerte.innerText()).trim();
  test.info().annotations.push({ type: 'message-refus', description: msg });
  expect(msg).toMatch(/négati/i);
  expect(msg).not.toMatch(/must|cannot|invalid|negative/i);
  // BUG-310 : aucun nom de champ technique dans le message
  expect(msg, 'nom de champ technique visible').not.toMatch(/remaining|«|»/i);
  expect(msg).toMatch(/Le reste du jour ne peut pas être négatif/i);
  expect(corps).toContain('remaining');
  await page.unroute('**/api/production/sessions/*/close/');
  await expect(m).toBeVisible(); // la fournee n'est pas cloturee
  await sansDebordement(page, info, 'modale cloture');
  await page.screenshot({ path: `${CAP}/e307-${info.project.name}-303-refus.png`, fullPage: true });
  // la fournee K1 equipe B sert aux trois largeurs : seule la derniere (bureau) la cloture vraiment
  if (i < 2) {
    await m.getByRole('button', { name: 'Annuler' }).click();
    await expect(m).toBeHidden();
    await expect(page.getByRole('dialog', { name: 'Détail Fournée' }).getByText(/Fournée clôturée/)).toHaveCount(0);
    return;
  }
  // cloture valide avec un reste positif
  await champ.fill(String(REST[i]));
  await m.getByRole('button', { name: 'Confirmer la clôture' }).click();
  await expect(m).toBeHidden({ timeout: 20_000 });
  await expect(page.getByRole('dialog', { name: 'Détail Fournée' }).getByText(/Fournée clôturée/)).toBeVisible();
});

/* ------------------------------------------------------------------ */
/* BUG-307 : messagerie                                                */
/* ------------------------------------------------------------------ */
async function contexte(browser: Browser, info: { project: { use: { viewport?: { width: number; height: number } | null } } }, user: string) {
  const ctx = await browser.newContext({ viewport: info.project.use.viewport ?? undefined });
  const page = await ctx.newPage();
  await login(page, user);
  await later(page);
  return { ctx, page };
}
const iconeChat = (page: Page) => page.getByRole('button', { name: /^Messagerie/ });
async function ouvrirChat(page: Page) {
  await later(page);
  await iconeChat(page).click();
  await expect(page.getByRole('dialog', { name: 'Messagerie' })).toBeVisible();
}
async function verifPleinEcran(page: Page, info: { project: { name: string } }) {
  const vp = page.viewportSize()!;
  const box = (await page.getByRole('dialog', { name: 'Messagerie' }).boundingBox())!;
  if (vp.width <= 768) {
    expect(Math.round(box.width), 'messagerie pleine largeur').toBe(vp.width);
    expect(Math.round(box.height), 'messagerie pleine hauteur').toBe(vp.height);
    expect(Math.round(box.x)).toBe(0);
  } else {
    expect(box.width).toBeLessThanOrEqual(vp.width);
  }
  await sansDebordement(page, info, 'messagerie');
}
async function ecrire(page: Page, texte: string) {
  const zone = page.getByLabel('Votre message');
  await zone.fill(texte);
  await page.getByRole('button', { name: 'Envoyer' }).click();
}

test('(307a) icone + badge, conversation 1-a-1 entre deux comptes, plein ecran 360', async ({ browser, request }, info) => {
  test.setTimeout(240_000);
  const i = idx(info.project.name);
  const A = await contexte(browser, info as never, 'zz_e307_fac6');
  const B = await contexte(browser, info as never, 'zz_e307_ger6');
  try {
    await expect(iconeChat(A.page)).toBeVisible({ timeout: 30_000 });
    await expect(iconeChat(B.page)).toBeVisible();
    await sansDebordement(A.page, info, 'en-tete avec icone');
    const tb = await apiToken(request, 'zz_e307_ger6');
    const avant = (await (await request.get(`${API}/api/chat/unread-count/`, { headers: H(tb) })).json()).unread_count as number;
    // A ecrit a B
    await ouvrirChat(A.page);
    await verifPleinEcran(A.page, info);
    await A.page.getByRole('button', { name: /Nouvelle/ }).click();
    await A.page.getByLabel('Rechercher un utilisateur').fill('e307_ger6');
    await A.page.getByRole('button', { name: /e307_ger6/ }).first().click();
    await expect(A.page.getByRole('heading', { name: /e307_ger6/ })).toBeVisible();
    const m1 = `Bonjour gerant ${SUF[i]} ${Date.now() % 100000}`;
    await ecrire(A.page, m1);
    await expect(A.page.getByRole('log', { name: 'Messages' })).toContainText(m1);
    await verifPleinEcran(A.page, info);
    await A.page.screenshot({ path: `${CAP}/e307-${info.project.name}-307a-fil.png` });
    // badge chez B (sondage 8 s) : il doit passer a `avant + 1`
    const apres = (await (await request.get(`${API}/api/chat/unread-count/`, { headers: H(tb) })).json()).unread_count as number;
    expect(apres).toBe(avant + 1);
    const badge = B.page.getByRole('button', { name: `Messagerie, ${apres} message(s) non lu(s)` });
    await expect(badge).toBeVisible({ timeout: 40_000 });
    expect((await badge.innerText()).trim()).toBe(String(apres > 99 ? '99+' : apres));
    await B.page.screenshot({ path: `${CAP}/e307-${info.project.name}-307a-badge.png` });
    // B ouvre, voit la conversation, lit, repond
    await ouvrirChat(B.page);
    await verifPleinEcran(B.page, info);
    await B.page.getByRole('button', { name: new RegExp('e307_fac6') }).first().click();
    await expect(B.page.getByRole('log', { name: 'Messages' })).toContainText(m1);
    const m2 = `Recu, merci ${SUF[i]} ${Date.now() % 100000}`;
    await ecrire(B.page, m2);
    await expect(B.page.getByRole('log', { name: 'Messages' })).toContainText(m2);
    // le badge de B retombe a sa valeur d'avant (les messages de cette conversation sont marques lus ; les autres conversations gardent leurs non-lus)
    await expect.poll(async () => (await (await request.get(`${API}/api/chat/unread-count/`, { headers: H(tb) })).json()).unread_count, { timeout: 30_000 }).toBe(avant);
    const nomApres = avant > 0 ? `Messagerie, ${avant} message(s) non lu(s)` : 'Messagerie';
    await expect(B.page.getByRole('button', { name: nomApres, exact: true })).toBeVisible({ timeout: 30_000 });
    // A voit la reponse (sondage)
    await expect(A.page.getByRole('log', { name: 'Messages' })).toContainText(m2, { timeout: 30_000 });
    // Echap ferme, bouton retour OK
    await A.page.keyboard.press('Escape');
    await expect(A.page.getByRole('dialog', { name: 'Messagerie' })).toBeHidden();
  } finally {
    await A.ctx.close(); await B.ctx.close();
  }
});

test('(307b) fil boulangerie (isolation K5/K6) et fil Direction masque hors roles autorises', async ({ browser, request }, info) => {
  test.setTimeout(240_000);
  const i = idx(info.project.name);
  const F = await contexte(browser, info as never, 'zz_e307_fac6');
  const G6 = await contexte(browser, info as never, 'zz_e307_ger6');
  const G5 = await contexte(browser, info as never, 'zz_e307_ger5');
  const D = await contexte(browser, info as never, 'zz_e307_dir');
  try {
    const txt = `Fil K6 ${SUF[i]} ${Date.now() % 100000}`;
    await ouvrirChat(F.page);
    await expect(F.page.getByRole('button', { name: /Ma boulangerie/ })).toBeVisible();
    await expect(F.page.getByRole('button', { name: /^Direction/ })).toHaveCount(0);
    await F.page.getByRole('button', { name: /Ma boulangerie/ }).click();
    await ecrire(F.page, txt);
    await expect(F.page.getByRole('log', { name: 'Messages' })).toContainText(txt);
    await verifPleinEcran(F.page, info);
    // gerant K6 le voit, avec le nom de l'expediteur
    await ouvrirChat(G6.page);
    await expect(G6.page.getByRole('button', { name: /^Direction/ })).toHaveCount(0);
    await G6.page.getByRole('button', { name: /Ma boulangerie/ }).click();
    await expect(G6.page.getByRole('log', { name: 'Messages' })).toContainText(txt, { timeout: 30_000 });
    await expect(G6.page.getByRole('log', { name: 'Messages' })).toContainText('e307_fac6');
    // gerant K5 : son fil boulangerie ne contient pas le message de K6
    await ouvrirChat(G5.page);
    await expect(G5.page.getByRole('button', { name: /^Direction/ })).toHaveCount(0);
    await G5.page.getByRole('button', { name: /Ma boulangerie/ }).click();
    await expect(G5.page.getByRole('log', { name: 'Messages' })).not.toContainText(txt);
    await G5.page.waitForTimeout(500);
    // direction : fil Direction visible et utilisable
    await ouvrirChat(D.page);
    await expect(D.page.getByRole('button', { name: 'Direction', exact: true })).toBeVisible();
    await D.page.getByRole('button', { name: 'Direction', exact: true }).click();
    const td = `Direction ${SUF[i]} ${Date.now() % 100000}`;
    await ecrire(D.page, td);
    await expect(D.page.getByRole('log', { name: 'Messages' })).toContainText(td);
    await D.page.screenshot({ path: `${CAP}/e307-${info.project.name}-307b-direction.png` });
    // cote API : le facturier et le gerant recoivent 403 sur le fil Direction
    for (const u of ['zz_e307_fac6', 'zz_e307_ger6', 'zz_e307_ger5']) {
      const r = await request.get(`${API}/api/chat/conversations/direction/`, { headers: H(await apiToken(request, u)) });
      expect(r.status(), u).toBe(403);
    }
  } finally {
    await F.ctx.close(); await G6.ctx.close(); await G5.ctx.close(); await D.ctx.close();
  }
});

test('(307c) « Voir plus » (35 messages, pages de 30)', async ({ browser }, info) => {
  test.setTimeout(180_000);
  const U = await contexte(browser, info as never, 'zz_e307_fac5');
  try {
    await ouvrirChat(U.page);
    await U.page.getByRole('button', { name: /e307_ger5/ }).first().click();
    const log = U.page.getByRole('log', { name: 'Messages' });
    await expect(log).toContainText('SEED-35');
    await expect(log.getByText(/^SEED-\d\d$/)).toHaveCount(30);
    await expect(log).not.toContainText('SEED-01');
    const plus = log.getByRole('button', { name: 'Voir plus' });
    await expect(plus).toBeVisible();
    await verifPleinEcran(U.page, info);
    await plus.click();
    await expect(log.getByText(/^SEED-\d\d$/)).toHaveCount(35);
    await expect(log).toContainText('SEED-01');
    await expect(plus).toHaveCount(0);
    // ordre chronologique conserve
    const textes = await log.getByText(/^SEED-\d\d$/).allInnerTexts();
    expect(textes).toEqual([...textes].sort());
    await U.page.screenshot({ path: `${CAP}/e307-${info.project.name}-307c-voirplus.png` });
  } finally { await U.ctx.close(); }
});

test('(307d) limites : 2000/2001 caracteres, texte HTML litteral, 429 en francais', async ({ browser, request }, info) => {
  test.setTimeout(240_000);
  const i = idx(info.project.name);
  const user = `zz_e307_flo_${SUF[i]}`;
  const U = await contexte(browser, info as never, user);
  const R = await contexte(browser, info as never, 'zz_e307_ger6');
  try {
    await ouvrirChat(U.page);
    await U.page.getByRole('button', { name: /Nouvelle/ }).click();
    await U.page.getByLabel('Rechercher un utilisateur').fill('e307_ger6');
    await U.page.getByRole('button', { name: /e307_ger6/ }).first().click();
    const log = U.page.getByRole('log', { name: 'Messages' });
    const envoyer = U.page.getByRole('button', { name: 'Envoyer' });
    const zone = U.page.getByLabel('Votre message');
    // 2001 : compteur rouge, envoi bloque
    await zone.fill('x'.repeat(2001));
    await expect(U.page.getByText('2 001 / 2 000')).toBeVisible();
    await expect(envoyer).toBeDisabled();
    await verifPleinEcran(U.page, info);
    await U.page.screenshot({ path: `${CAP}/e307-${info.project.name}-307d-2001.png` });
    // 2000 sans espace : accepte, ne deborde pas
    await zone.fill('y'.repeat(2000));
    await expect(U.page.getByText('2 000 / 2 000')).toBeVisible();
    await expect(envoyer).toBeEnabled();
    await envoyer.click();
    await expect(log).toContainText('y'.repeat(50));
    await sansDebordement(U.page, info, 'message de 2000 caracteres');
    // HTML : affiche litteralement, jamais interprete
    const html = `<b>gras</b><img src=x onerror="window.__xss307=1"><script>window.__xss307=2</script>`;
    await U.page.evaluate(() => { (window as unknown as Rec).__xss307 = undefined; });
    await zone.fill(html);
    await envoyer.click();
    await expect(log).toContainText(html);
    expect(await log.locator('b, img, script').count()).toBe(0);
    expect(await U.page.evaluate(() => (window as unknown as Rec).__xss307)).toBeUndefined();
    // meme rendu chez le destinataire et dans l'aperçu de la liste
    await ouvrirChat(R.page);
    await expect(R.page.getByRole('dialog', { name: 'Messagerie' })).toContainText(`<b>gras</b>`, { timeout: 30_000 });
    expect(await R.page.getByRole('dialog', { name: 'Messagerie' }).locator('b, img, script').count()).toBe(0);
    expect(await R.page.evaluate(() => (window as unknown as Rec).__xss307)).toBeUndefined();
    await U.page.screenshot({ path: `${CAP}/e307-${info.project.name}-307d-html.png` });
    // 429 : on sature le quota (10 messages / 30 s) par l'API puis on envoie par l'ecran
    const tu = await apiToken(request, user);
    const conv = await (await request.get(`${API}/api/chat/conversations/`, { headers: H(tu) })).json();
    const cid = (conv as Rec[]).find(c => (c.other_user as Rec | null)?.name?.toString().includes('e307_ger6'))!.id;
    let refus = 0;
    for (let k = 0; k < 14 && refus === 0; k++) {
      const r = await request.post(`${API}/api/chat/conversations/${cid}/messages/`, { headers: H(tu), data: { body: `rafale ${k}` } });
      if (r.status() === 429) refus++;
    }
    expect(refus, 'le serveur finit par repondre 429').toBeGreaterThan(0);
    await zone.fill('trop vite');
    await envoyer.click();
    const al = U.page.getByRole('alert').filter({ hasText: /trop de messages/i });
    await expect(al).toBeVisible({ timeout: 15_000 });
    const msg = (await al.innerText()).trim();
    test.info().annotations.push({ type: 'message-429', description: msg });
    expect(msg).not.toMatch(/Request failed|status code|Too Many/i);
    await sansDebordement(U.page, info, 'message 429');
    await U.page.screenshot({ path: `${CAP}/e307-${info.project.name}-307d-429.png` });
  } finally { await U.ctx.close(); await R.ctx.close(); }
});

/* (place en dernier : le mode serie interrompt les tests suivants en cas d'echec) */
/* BUG-311 : la valeur du sac n'est jamais affichee avant le chargement de la config */
test('(311) valeur du sac : ni « 1 sac = » ni 200 000 FC avant le chargement, puis la valeur de la boulangerie', async ({ page, request }, info) => {
  test.setTimeout(180_000);
  const tg = await apiToken(request, 'zz_e307_ger6');
  const noeud = liste(await (await request.get(`${API}/api/core/nodes/`, { headers: H(tg) })).json()).find(n => n.code === 'K6')!;
  const valeurSac = Number(noeud.sac_value_fc);
  expect(valeurSac, 'precondition : la valeur du sac de K6 differe de 200 000').not.toBe(200000);
  await login(page, 'zz_e307_ger6');
  await later(page);
  await annonces(page);
  let libere!: () => void;
  const porte = new Promise<void>(r => { libere = r; });
  // la valeur du sac de Production vient de la liste des boulangeries + config (Promise.all) : retenir /nodes/ suffit
  // (retenir /config/ bloque aussi l'ecran de connexion au serveur central du gabarit)
  await page.route('**/api/core/nodes/**', async route => { await porte; await route.continue(); });
  await page.goto('/production', { waitUntil: 'domcontentloaded' });
  const panneau = page.getByTestId('batch-in-progress-panel');
  await expect(panneau).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(2_500); // config et noeuds retenus : le panneau est rendu sans la valeur
  const avant = nb(await page.locator('body').innerText());
  test.info().annotations.push({ type: 'avant-chargement', description: /1sac=/.test(avant) ? 'valeur affichee' : 'aucune valeur du sac affichee' });
  expect(avant, 'valeur du sac affichee avant chargement').not.toMatch(/1sac=/);
  expect(avant, '200 000 FC affiche avant chargement').not.toContain('200000FC');
  expect(avant).not.toMatch(/Montantàatteindre/);
  await page.screenshot({ path: `${CAP}/e307-${info.project.name}-311-avant.png` });
  libere();
  await expect.poll(async () => nb(await panneau.innerText()), { timeout: 20_000 }).toContain(nb(`1 sac = ${valeurSac.toLocaleString('fr-FR')} FC`));
  expect(nb(await page.locator('body').innerText())).not.toContain('1sac=200000FC');
  await sansDebordement(page, info, 'valeur du sac');
  await page.screenshot({ path: `${CAP}/e307-${info.project.name}-311-apres.png` });
});

