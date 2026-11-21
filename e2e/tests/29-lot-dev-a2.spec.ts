import { test, expect, Page } from '@playwright/test';
import { seConnecter } from '../fixtures/helpers';
import { CAP, idx, overflow } from '../fixtures/cycle';

/**
 * BUG-355 (remarque.md, « Fournee en cours ») : le champ « Augmenter les sacs » AJOUTE la valeur saisie
 * au nombre de sacs declares (l'API PATCH recoit le total absolu = actuel + ajout, en centiemes exacts).
 * Test ecrit par dev-frontend, NON rejoue (serveurs arretes). Les reponses `sessions` sont simulees
 * (page.route) ; seule la connexion utilise le backend (comptes zz_*, base isolee).
 * Largeurs : 360, 768, 1440 (projet « tv » ignore). Une boulangerie par largeur comme le spec 28.
 */
test.describe.configure({ mode: 'serial' });
test.beforeEach(({}, info) => { test.skip(info.project.name === 'tv', 'largeurs demandees : 360, 768, 1440'); });

const GERANT = ['zz_demo_gerant_k2', 'zz_demo_gerant_k5', 'zz_demo_gerant_b1'];
const norm = (s: string) => s.replace(/[\s  ]+/g, ' ').trim();

async function ouvrirPanneau(page: Page, sacs: string, patchs: Array<Record<string, unknown>>, patchResponse?: { status: number; body: unknown }) {
  let courant = sacs;
  const session = () => ({
    id: 4242, team: 'A', auto_track: true, is_closed: false, date: new Date().toLocaleDateString('sv-SE'),
    flour_sacks_used: courant, objective_fc: Number(courant) * 200000, progress_value_fc: 0, progress_pct: '0', lines: [],
  });
  await page.route('**/api/production/sessions/**', async route => {
    const req = route.request();
    if (req.method() === 'PATCH') {
      const body = req.postDataJSON() as Record<string, unknown>;
      patchs.push(body);
      if (patchResponse) { await route.fulfill({ status: patchResponse.status, contentType: 'application/json', body: JSON.stringify(patchResponse.body) }); return; }
      courant = String(body.flour_sacks_used);
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(session()) });
      return;
    }
    if (req.method() === 'GET') { await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([session()]) }); return; }
    await route.continue();
  });
  await page.goto('/production', { waitUntil: 'domcontentloaded' });
  const panneau = page.getByTestId('batch-in-progress-panel');
  await expect(panneau.getByText('Fournée en cours')).toBeVisible({ timeout: 40_000 });
  return panneau;
}

test('BUG-355 : « Augmenter les sacs » ajoute au total, apercu, validations, pas de « nouveau total »', async ({ page }, info) => {
  test.setTimeout(180_000);
  const i = idx(info.project.name);
  await seConnecter(page, GERANT[i], '');
  const patchs: Array<Record<string, unknown>> = [];
  const panneau = await ouvrirPanneau(page, '3.00', patchs);

  // libelle : « Augmenter les sacs », jamais « nouveau total »
  const champ = panneau.getByLabel('Augmenter les sacs');
  await expect(champ).toBeVisible();
  expect(norm(await panneau.innerText()).toLowerCase()).not.toContain('nouveau total');

  // apercu « 3 sacs + 1,5 = 4,5 sacs » et objectif recalcule (valeur du sac si connue)
  await champ.fill('1,5');
  const apercu = panneau.getByTestId('batch-add-preview');
  await expect(apercu).toContainText(/3 sacs \+ 1,5 = 4,5 sacs/);
  await page.screenshot({ path: `${CAP}/b350-${info.project.name}-1-apercu.png` });

  // refus : vide, 0, negatif, texte, > 2 decimales, demesure -> message, aucun PATCH
  const refus: Array<[string, RegExp]> = [
    ['', /Indiquez le nombre de sacs/], ['0', /supérieur à 0/], ['-2', /négatif/], ['abc', /nombre valide/],
    ['1,234', /Deux décimales/], ['1e3', /nombre valide/], ['99999999999', /démesurée/],
  ];
  for (const [saisie, message] of refus) {
    await champ.fill(saisie);
    await panneau.getByRole('button', { name: 'Ajouter les sacs' }).click();
    await expect(panneau.getByRole('alert')).toContainText(message);
  }
  expect(patchs, 'aucune requete pour une saisie invalide').toHaveLength(0);

  // succes : PATCH = total absolu (3 + 1,5 = 4,50), champ vide ensuite, panneau a 4,5 sacs
  await champ.fill('1,5');
  await panneau.getByRole('button', { name: 'Ajouter les sacs' }).click();
  await expect(champ).toHaveValue('', { timeout: 15_000 });
  expect(patchs).toHaveLength(1);
  expect(patchs[0]).toEqual({ flour_sacks_used: '4.50' });
  await expect(panneau.getByText(/4,5 sacs de farine/)).toBeVisible();

  // pas de derive flottante : 4,5 + 0,1 -> 4,60 ; 4,6 + 0,2 -> 4,80
  for (const [ajout, attendu] of [['0,1', '4.60'], ['0.2', '4.80']]) {
    await champ.fill(ajout);
    await panneau.getByRole('button', { name: 'Ajouter les sacs' }).click();
    await expect(champ).toHaveValue('', { timeout: 15_000 });
    expect(patchs[patchs.length - 1]).toEqual({ flour_sacks_used: attendu });
  }

  expect(await overflow(page), 'pas de debordement horizontal').toBeLessThanOrEqual(1);
  await page.screenshot({ path: `${CAP}/b350-${info.project.name}-2-apres.png`, fullPage: true });
});

test('BUG-355 : erreur API (detail) affichee, saisie conservee ; bouton desactive pendant l\'envoi', async ({ page }, info) => {
  test.setTimeout(120_000);
  const i = idx(info.project.name);
  await seConnecter(page, GERANT[i], '');
  const patchs: Array<Record<string, unknown>> = [];
  const panneau = await ouvrirPanneau(page, '2.00', patchs, { status: 400, body: { detail: 'Fournée clôturée : modification impossible.' } });
  const champ = panneau.getByLabel('Augmenter les sacs');
  await champ.fill('1');
  const bouton = panneau.getByRole('button', { name: 'Ajouter les sacs' });
  await bouton.dblclick();
  await expect(panneau.getByRole('alert')).toContainText('Fournée clôturée : modification impossible.', { timeout: 15_000 });
  expect(patchs.length, 'un seul envoi malgre le double clic').toBe(1);
  await expect(champ).toHaveValue('1');
});

/**
 * BUG-356 (volet frontend) : la ligne « Non servi » de la Cloture journaliere cumule le code NS et les
 * factures au STATUT Non servi (non_servi_jour) ; total `non_servi_total_fc` affiche ; aide visible ;
 * le total du jour et le net produit ne sont PAS modifies. Reponse `daily-closure/` simulee (page.route).
 * Non rejoue (serveurs arretes).
 */
test('BUG-356 : Non servi = code NS + statut, total et aide affiches, total du jour inchange', async ({ page }, info) => {
  test.setTimeout(120_000);
  const i = idx(info.project.name);
  await seConnecter(page, GERANT[i], '');
  const q = (quantity: number, fc: string) => ({ quantity, fc });
  const cat = {
    bread_price: 1, label: 'Pain 200 FC', unit_price: 200, produit: q(100, '20000.00'), facture_jr: q(80, '16000.00'),
    commission_jr: { fc: '0.00' }, reste_du_jour: {}, reste_du_hier: {}, reste_du_hier_jour: 0, reste_du_jour_jour: 5,
    appro_effectue: q(0, '0.00'), appro_recu: q(0, '0.00'),
    non_servi: { ...q(5, '1000.00'), fc_signe: '-1000.00' }, non_servi_jour: q(10, '2000.00'),
    regularisation: q(0, '0.00'), vente_cash_soldee: { ...q(0, '0.00'), perte_fc: '0.00' },
    facture_mvm_interne: { fc: '15000.00' }, non_vendu_nv: q(0, '0.00'), declasses: q(0, '0.00'), sorties_gratuites: q(0, '0.00'),
  };
  const rapport = {
    node: 'K2', date: new Date().toLocaleDateString('sv-SE'), categories: [cat],
    totals: {
      total_du_jour_fc: '15000.00', net_produit_fc: '20000.00', ecart_facture_fc: '0.00', nombre_sacs_produits: '1.00',
      moyenne_produit_par_sac_fc: '20000.00', tarif_vente_fc: '200000.00', ecart_production_fc: '0.00',
      total_breads_produced: 100, total_breads_billed: 80, non_servi_fc: '2000.00', non_servi_quantity: 10,
      non_servi_total_fc: '3000.00', repartition_pct_par_quantite: [], repartition_pct_par_valeur: [],
    },
  };
  await page.route(/\/api\/production\/daily-closure\/(\?.*)?$/, route =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(rapport) }));
  await page.goto('/cloture-journaliere', { waitUntil: 'domcontentloaded' });
  const ligne = page.locator('tbody tr', { hasText: 'Pain 200 FC' }).first();
  await expect(ligne).toBeVisible({ timeout: 40_000 });
  const texte = norm(await ligne.innerText());
  expect(texte).toMatch(/3 000 FC/);           // 1 000 (NS) + 2 000 (statut)
  expect(texte).toMatch(/15 pain\(s\)/);       // 5 + 10
  expect(texte).toMatch(/dont statut : 2 000 FC/);
  const page_ = norm(await page.locator('body').innerText());
  expect(page_).toMatch(/Total Non servi \(code NS \+ factures déclarées Non servi\) : 3 000 FC/);
  expect(page_).toContain('elles ne comptent pas dans les ventes');
  // ni total du jour ni net produit ne sont majores
  expect(page_).toMatch(/Total du Jour\s*15 000 FC/i);
  expect(page_).toMatch(/Net Produit\s*20 000 FC/i);
  expect(await overflow(page), 'pas de debordement horizontal de la page').toBeLessThanOrEqual(1);
  await page.screenshot({ path: `${CAP}/b356-${info.project.name}-non-servi.png`, fullPage: true });
});
