import { test, expect, Page, APIRequestContext } from '@playwright/test';
import * as XLSX from '../../frontend/node_modules/xlsx';
import { seConnecter } from '../fixtures/helpers';
import { CAP, API, apiToken, idx, overflow } from '../fixtures/cycle';

/**
 * Verification EN NAVIGATEUR, sur le backend REEL (base isolee), de BUG-355 (« Augmenter les sacs » ajoute)
 * et BUG-356 volet frontend (« Non servi » cumule dans la Cloture Journaliere), testeur-e2e, 2026-11-21.
 * Donnees : seed zz_* + prep (session de 3 sacs en equipe A, clients ZZ355 <A|B|C><noeud> ; facture 0001 livree
 * 5 x 1000 cash, 0002 = 10 x 300 en attente, 0003 = code NS 4 x 500 en attente). Une boulangerie par largeur :
 * pos -> K2, tablette -> K5, bureau -> B1 (actions uniques par jour). Non rejouable sur la meme base.
 */
test.describe.configure({ mode: 'serial' });
test.beforeEach(({}, info) => { test.skip(info.project.name === 'tv', 'largeurs demandees : 360, 768, 1440'); });

const NODE = ['K2', 'K5', 'B1'];
const GERANT = ['zz_demo_gerant_k2', 'zz_demo_gerant_k5', 'zz_demo_gerant_b1'];
const FACT_A = ['zz_demo_facturier_k2', 'zz_demo_facturier_k5a', 'zz_demo_facturier_b1'];
const norm = (s: string) => s.replace(/[\s  ]+/g, ' ').trim();
const auth = (tk: string) => ({ Authorization: `Bearer ${tk}` });
const rows = (j: any) => (Array.isArray(j) ? j : j.results ?? []);
const today = () => new Date().toLocaleDateString('sv-SE');
const fc = (n: number) => `${Math.round(n).toLocaleString('fr-FR')} FC`;

async function annonces(page: Page) {
  await page.addLocatorHandler(page.getByRole('button', { name: /j'ai compris/i }), async b => { await b.click(); });
}
async function deconnecter(page: Page) {
  await page.evaluate(() => { localStorage.clear(); sessionStorage.clear(); }).catch(() => undefined);
}
async function rapport(request: APIRequestContext, tk: string) {
  const r = await request.get(`${API}/api/production/daily-closure/?date=${today()}`, { headers: auth(tk) });
  expect(r.status()).toBe(200);
  return await r.json();
}
async function sessionOuverte(request: APIRequestContext, tk: string) {
  const l = rows(await (await request.get(`${API}/api/production/sessions/?date=${today()}&page_size=50`, { headers: auth(tk) })).json());
  return l.find((s: any) => !s.is_closed);
}

/* ───────────────────────── BUG-356 : cas reel de bout en bout ───────────────────────── */
test('BUG-356 REEL : facture declaree Non servi dans la File des Livraisons -> Cloture Journaliere + liste du jour', async ({ page, request }, info) => {
  test.setTimeout(300_000);
  const i = idx(info.project.name);
  const nom = info.project.name;
  const tg = await apiToken(request, GERANT[i]);
  const avant = await rapport(request, tg);
  const T0 = avant.totals;
  console.log(`AVANT ${NODE[i]} : ${JSON.stringify({ tj: T0.total_du_jour_fc, np: T0.net_produit_fc, nst: T0.non_servi_total_fc, nsf: T0.non_servi_fc })}`);
  const numero = `${NODE[i]}-${today().replace(/-/g, '')}-0002`;
  const tf = await apiToken(request, FACT_A[i]);
  const statut = async () => rows(await (await request.get(`${API}/api/sales/invoices/?search=${numero}&page_size=50`, { headers: auth(tf) })).json()).find((x: any) => x.receipt_number === numero)?.status;
  const reprise = (await statut()) === 'NOT_SERVED'; // reprise apres un premier passage deja declare
  if (!reprise) { expect(Number(T0.non_servi_fc)).toBe(0); expect(Number(T0.non_servi_total_fc)).toBe(2000); }

  // 1) facturier : File des Livraisons, declarer la facture 0002 (10 x 300) « Non servi »
  if (!reprise) {
  await annonces(page);
  await seConnecter(page, FACT_A[i], '');
  await page.goto('/sales', { waitUntil: 'domcontentloaded' });
  const carte = page.locator('div').filter({ hasText: numero }).filter({ has: page.getByRole('button', { name: 'Non servi' }) }).last();
  await expect(carte).toBeVisible({ timeout: 60_000 });
  await carte.scrollIntoViewIfNeeded();
  await page.screenshot({ path: `${CAP}/b356r-${nom}-1-file-livraisons.png`, fullPage: true });
  await carte.getByRole('button', { name: 'Non servi' }).click();
  await carte.getByLabel('Motif non servi').fill('Client parti (test e2e)');
  await page.screenshot({ path: `${CAP}/b356r-${nom}-2-confirmation.png`, fullPage: true });
  await carte.getByRole('button', { name: /Confirmer « Non servi »/ }).click();
  await expect.poll(statut, { timeout: 30_000 }).toBe('NOT_SERVED');
  }

  // 2) API : cumul attendu, total du jour et net produit inchanges
  const apres = await rapport(request, tg);
  const T1 = apres.totals;
  console.log(`APRES ${NODE[i]} : ${JSON.stringify({ tj: T1.total_du_jour_fc, np: T1.net_produit_fc, nst: T1.non_servi_total_fc, nsf: T1.non_servi_fc, nsq: T1.non_servi_quantity })}`);
  expect(Number(T1.non_servi_fc)).toBe(3000);
  expect(T1.non_servi_quantity).toBe(10);
  expect(Number(T1.non_servi_total_fc)).toBe(5000);
  if (!reprise) { expect(T1.total_du_jour_fc).toBe(T0.total_du_jour_fc); expect(T1.net_produit_fc).toBe(T0.net_produit_fc); }

  // 3) gerant : Cloture Journaliere
  await deconnecter(page);
  await annonces(page);
  await seConnecter(page, GERANT[i], '');
  await page.goto('/cloture-journaliere', { waitUntil: 'domcontentloaded' });
  const tableau = page.locator('table').filter({ has: page.getByRole('columnheader', { name: /Non Servi/i }) }).first();
  const l300 = tableau.locator('tbody tr', { hasText: 'Pain 300 FC' }).first();
  const l500 = tableau.locator('tbody tr', { hasText: 'Pain 500 FC' }).first();
  await expect(l300).toBeVisible({ timeout: 60_000 });
  const t300 = norm(await l300.innerText());
  const t500 = norm(await l500.innerText());
  console.log(`LIGNE 300 : ${t300}\nLIGNE 500 : ${t500}`);
  expect(t300).toMatch(/3 000 FC/);
  expect(t300).toMatch(/10 pain\(s\)/);
  expect(t300).toMatch(/dont statut : 3 000 FC/);
  expect(t500).toMatch(/2 000 FC/);
  expect(t500).toMatch(/4 pain\(s\)/);
  expect(t500).not.toMatch(/dont statut/);
  const corps = norm(await page.locator('body').innerText());
  expect(corps).toMatch(/Total Non servi \(code NS \+ factures déclarées Non servi\) : 5 000 FC/);
  expect(corps).toContain('elles ne comptent pas dans les ventes');
  expect(corps).toContain(norm(fc(Number(T1.total_du_jour_fc)))); // total du jour inchange
  const th = page.getByRole('columnheader', { name: /Non Servi/i });
  const aide = await th.getAttribute('title');
  console.log(`INFO-BULLE : ${aide}`);
  expect(aide).toContain('factures déclarées Non servi');
  expect(aide).toContain('ne comptent pas dans les ventes');
  expect(await overflow(page), 'pas de debordement horizontal de la page').toBeLessThanOrEqual(1);
  await page.screenshot({ path: `${CAP}/b356r-${nom}-3-cloture.png`, fullPage: true });

  // Excel
  const [dl] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: /Exporter en Excel/ }).click()]);
  const wb = XLSX.readFile((await dl.path())!);
  console.log(`EXCEL feuilles : ${wb.SheetNames.join(', ')}`);
  const txt = JSON.stringify(wb.SheetNames.map(n => XLSX.utils.sheet_to_json(wb.Sheets[n], { header: 1 })));
  expect(txt).toContain('Non Servi (FC)');
  expect(txt).toContain('Total Non servi (code NS + statut) (FC)');
  let ok300 = false;
  for (const n of wb.SheetNames) {
    const g = XLSX.utils.sheet_to_json<any[]>(wb.Sheets[n], { header: 1 });
    const h = g.findIndex(r => Array.isArray(r) && r.includes('Non Servi (FC)'));
    if (h < 0) continue;
    const q = g[h].indexOf('Non Servi (qté)'); const v = g[h].indexOf('Non Servi (FC)');
    const r300 = g.slice(h + 1).find(r => Array.isArray(r) && String(r[0]).includes('300'));
    console.log(`EXCEL ligne 300 : ${JSON.stringify(r300)} (colonnes ${q}/${v})`);
    if (r300 && Number(r300[q]) === 10 && Number(r300[v]) === 3000) ok300 = true;
  }
  expect(ok300, 'Excel : ligne 300 cumulee (10 pains, 3000 FC)').toBeTruthy();
  expect(txt).toMatch(/5000/);

  // Impression (fenetre popup)
  const [popup] = await Promise.all([page.waitForEvent('popup'), page.getByRole('button', { name: /Imprimer/ }).click()]);
  await popup.waitForLoadState('domcontentloaded');
  const imp = norm(await popup.locator('body').innerText());
  const pos = imp.indexOf('Total Non servi');
  console.log(`IMPRESSION extrait : ${imp.slice(Math.max(0, pos - 20), pos + 120)}`);
  expect(imp).toMatch(/3 000 FC/);
  expect(imp).toMatch(/10 pain\(s\)/);
  expect(imp).toMatch(/Total Non servi \(code NS \+ statut\) : 5 000 FC/);
  await popup.close();

  // 4) modale « Liste du jour (clients) » : compteur coherent avec le cumul
  await page.getByRole('button', { name: /Liste du jour \(clients\)/ }).click();
  const dlg = page.getByRole('dialog', { name: /Liste du jour/ });
  await expect(dlg).toBeVisible({ timeout: 30_000 });
  await expect(dlg.getByText(/Non servis/).first()).toBeVisible({ timeout: 30_000 });
  const txtModale = norm(await dlg.innerText());
  const m = txtModale.match(/Non servis\s*(\d+)/);
  const compteur = m ? Number(m[1]) : -1;
  const api = await (await request.get(`${API}/api/production/daily-closure/clients/?date=${today()}&node=${NODE[i]}`, { headers: auth(tg) })).json();
  console.log(`MODALE compteur Non servis = ${compteur} ; API non_servis.count = ${api.non_servis?.count} ; resultats ${JSON.stringify(api.non_servis?.results ?? [])}`);
  console.log(`MODALE texte : ${txtModale.slice(0, 1200)}`);
  await page.screenshot({ path: `${CAP}/b356r-${nom}-4-liste-du-jour.png`, fullPage: true });
  expect(compteur, 'compteur « Non servis » de la modale = 2 (code NS + statut)').toBe(2);
  expect(await overflow(page)).toBeLessThanOrEqual(1);
});

/* ───────────────────────── BUG-355 : sur backend reel ───────────────────────── */
test('BUG-355 REEL : Augmenter les sacs ajoute, apercu, 7 refus, centiemes, un seul envoi, erreur API', async ({ page, request }, info) => {
  test.setTimeout(400_000);
  const i = idx(info.project.name);
  const nom = info.project.name;
  const tg = await apiToken(request, GERANT[i]);
  await deconnecter(page);
  await annonces(page);
  await seConnecter(page, GERANT[i], '');
  const patchs: string[] = [];
  page.on('request', r => { if (r.method() === 'PATCH' && /\/api\/production\/sessions\//.test(r.url())) patchs.push(r.postData() ?? ''); });
  await page.goto('/production', { waitUntil: 'domcontentloaded' });
  const panneau = page.getByTestId('batch-in-progress-panel');
  await expect(panneau.getByText('Fournée en cours')).toBeVisible({ timeout: 60_000 });
  await expect(panneau.getByText(/3 sacs de farine/)).toBeVisible();

  const champ = panneau.getByLabel('Augmenter les sacs');
  await expect(champ).toBeVisible();
  expect(norm(await panneau.innerText()).toLowerCase()).not.toContain('nouveau total');
  await expect(panneau.getByRole('button', { name: 'Ajouter les sacs' })).toBeVisible();
  const objectif = async () => Number(norm(await panneau.getByTestId('batch-objective').innerText()).replace(/[^\d]/g, ''));
  const o0 = await objectif();
  const valeurSac = o0 / 3;
  console.log(`OBJECTIF initial ${o0} (sac = ${valeurSac})`);
  expect(Number.isInteger(valeurSac)).toBeTruthy();
  const barre = panneau.getByRole('progressbar', { name: 'Avancement de la fournée' });
  const b0 = (await barre.getAttribute('aria-valuetext')) ?? '';
  const s0 = await sessionOuverte(request, tg);
  console.log(`BARRE avant : ${b0} ; API progress_pct=${s0.progress_pct} objective_fc=${s0.objective_fc} progress_value_fc=${s0.progress_value_fc}`);
  await page.screenshot({ path: `${CAP}/b355r-${nom}-1-avant.png`, fullPage: true });

  // apercu
  await champ.fill('1,5');
  const apercu = panneau.getByTestId('batch-add-preview');
  await expect(apercu).toContainText(/3 sacs \+ 1,5 = 4,5 sacs/);
  await expect.poll(async () => norm(await apercu.innerText()), { timeout: 15_000 }).toContain(norm(`Montant à atteindre : ${fc(4.5 * valeurSac)}`));
  expect(patchs).toHaveLength(0);
  expect(await overflow(page)).toBeLessThanOrEqual(1);
  await page.screenshot({ path: `${CAP}/b355r-${nom}-2-apercu.png`, fullPage: true });

  // 7 refus
  const refus: Array<[string, RegExp]> = [
    ['', /Indiquez le nombre de sacs/], ['0', /supérieur à 0/], ['-2', /négatif/], ['abc', /nombre valide/],
    ['1e3', /nombre valide/], ['1,234', /Deux décimales/], ['100001', /démesurée/],
  ];
  for (const [saisie, message] of refus) {
    await champ.fill(saisie);
    await panneau.getByRole('button', { name: 'Ajouter les sacs' }).click();
    await expect(panneau.getByRole('alert').first()).toContainText(message);
    console.log(`REFUS « ${saisie} » -> ${norm(await panneau.getByRole('alert').first().innerText())}`);
  }
  expect(patchs, 'aucune requete pour une saisie invalide').toHaveLength(0);
  expect(Number((await sessionOuverte(request, tg)).flour_sacks_used)).toBe(3);
  await page.screenshot({ path: `${CAP}/b355r-${nom}-3-refus.png`, fullPage: true });

  // succes 1,5
  await champ.fill('1,5');
  await panneau.getByRole('button', { name: 'Ajouter les sacs' }).click();
  await expect(champ).toHaveValue('', { timeout: 20_000 });
  expect(patchs).toHaveLength(1);
  expect(JSON.parse(patchs[0])).toEqual({ flour_sacks_used: '4.50' });
  await expect(panneau.getByText(/4,5 sacs de farine/)).toBeVisible();
  expect(Number((await sessionOuverte(request, tg)).flour_sacks_used)).toBe(4.5);
  await expect.poll(objectif, { timeout: 15_000 }).toBe(Math.round(4.5 * valeurSac));
  const s1 = await sessionOuverte(request, tg);
  const b1 = (await barre.getAttribute('aria-valuetext')) ?? '';
  console.log(`BARRE apres +1,5 : ${b1} ; API progress_pct=${s1.progress_pct} objective_fc=${s1.objective_fc}`);
  expect(Number(s1.objective_fc)).toBe(Math.round(4.5 * valeurSac));
  expect(b1).not.toBe(b0); // la barre suit le nouvel objectif
  await page.screenshot({ path: `${CAP}/b355r-${nom}-4-apres.png`, fullPage: true });

  // centiemes exacts : 4,5 + 0,1 = 4,60 ; 4,6 + 0,2 = 4,80
  for (const [ajout, attendu] of [['0,1', '4.60'], ['0.2', '4.80']]) {
    await champ.fill(ajout);
    await panneau.getByRole('button', { name: 'Ajouter les sacs' }).click();
    await expect(champ).toHaveValue('', { timeout: 20_000 });
    expect(JSON.parse(patchs[patchs.length - 1])).toEqual({ flour_sacks_used: attendu });
    expect(Number((await sessionOuverte(request, tg)).flour_sacks_used)).toBe(Number(attendu));
  }

  // double clic : un seul envoi
  const n0 = patchs.length;
  await champ.fill('0,2');
  await panneau.getByRole('button', { name: 'Ajouter les sacs' }).dblclick();
  await expect(champ).toHaveValue('', { timeout: 20_000 });
  await page.waitForTimeout(800);
  expect(patchs.length - n0, 'un seul PATCH malgre le double clic').toBe(1);
  expect(Number((await sessionOuverte(request, tg)).flour_sacks_used)).toBe(5);
  await expect(panneau.getByText(/5 sacs de farine/)).toBeVisible();
  expect(await overflow(page)).toBeLessThanOrEqual(1);

  // erreur API reelle : fournee cloturee cote serveur pendant que l'ecran reste ouvert
  const sid = (await sessionOuverte(request, tg)).id;
  await champ.fill('1');
  const c = await request.post(`${API}/api/production/sessions/${sid}/close/`, { headers: auth(tg), data: { remaining: [] } });
  console.log(`CLOTURE API ${c.status()} ${(await c.text()).slice(0, 200)}`);
  expect(c.status()).toBe(200);
  const nP = patchs.length;
  await panneau.getByRole('button', { name: 'Ajouter les sacs' }).click();
  await expect(panneau.getByRole('alert')).toBeVisible({ timeout: 15_000 });
  console.log(`ERREUR API affichee : ${norm(await panneau.getByRole('alert').first().innerText())} (PATCH envoyes : ${patchs.length - nP})`);
  await expect(champ).toHaveValue('1');
  await page.screenshot({ path: `${CAP}/b355r-${nom}-5-erreur-api.png`, fullPage: true });
  expect(await overflow(page)).toBeLessThanOrEqual(1);
});
