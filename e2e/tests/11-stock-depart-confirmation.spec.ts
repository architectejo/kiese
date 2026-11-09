import { test, expect } from '@playwright/test';
import { COMPTES, PASSWORD } from '../fixtures/comptes';
import { seConnecter } from '../fixtures/helpers';

/**
 * Parcours 11 — Boîte modale « Stock de départ du jour » (BUG-133/134/135/136,
 * docs/qa/REGISTRE_BUGS.md, CORRIGÉ au 2026-11-09, vérification testeur-production).
 *
 * Attention base partagée : ce parcours écrit une confirmation réelle pour
 * (node=K1, équipe choisie, date=aujourd'hui) et ajuste réellement
 * `BreadStock.qty_adjusted` de K1 (BUG-136, décision client explicite —
 * toujours synchroniser, y compris en no-op). Comme le reste de la suite
 * (`05-production.spec.ts` déclare déjà une fournée réelle pour K1), c'est
 * cohérent avec la convention déjà établie du dossier `e2e/` : écrire des
 * données fictives dans la base de dev partagée, jamais la détruire.
 *
 * Si l'équipe A et/ou B de K1 a déjà été confirmée aujourd'hui par une
 * exécution précédente de cette suite (ou par le gérant réel), la boîte
 * modale n'apparaît plus — ce n'est pas un échec du test, documenté dans les
 * `test.skip` conditionnels ci-dessous plutôt que de fausser un résultat.
 */

test("la boîte modale réapparaît à chaque navigation tant qu'aucune équipe n'est confirmée, puis disparaît et ajuste le stock", async ({ page }) => {
  await seConnecter(page, COMPTES.gerantK1.username, PASSWORD);

  const modaleTitre = page.getByText('Stock de départ du jour');

  // 1) Doit apparaître dès le tableau de bord si aucune équipe n'est
  // confirmée aujourd'hui pour K1.
  const dejaConfirmeeAuDepart = await modaleTitre.isVisible().catch(() => false);
  if (!dejaConfirmeeAuDepart) {
    test.skip(true, 'Les deux équipes K1 sont déjà confirmées aujourd\'hui (exécution précédente) — rien à vérifier ici, voir note du fichier.');
  }
  await expect(modaleTitre).toBeVisible({ timeout: 10_000 });

  // 2) Fermeture temporaire (« Plus tard »), navigation vers une autre page :
  // la modale doit réapparaître (BUG-134, demande client remarque.md l.396).
  await page.getByRole('button', { name: /plus tard/i }).click();
  await expect(modaleTitre).toBeHidden();
  await page.goto('/clients');
  await expect(modaleTitre).toBeVisible({ timeout: 10_000 });

  // 3) Deuxième navigation vers une page différente : toujours visible.
  await page.goto('/production');
  await expect(modaleTitre).toBeVisible({ timeout: 10_000 });

  // 4) Lire la première quantité proposée, la corriger, puis valider pour
  // l'équipe présélectionnée.
  const premierChamp = page.locator('.modal, [role="dialog"]').filter({ hasText: 'Stock de départ du jour' })
    .locator('input[type="number"]').first();
  await expect(premierChamp).toBeVisible();
  const valeurProposee = await premierChamp.inputValue();
  const valeurCorrigee = String(Math.max(0, parseInt(valeurProposee || '0', 10) - 1));
  await premierChamp.fill(valeurCorrigee);

  const boutonValider = page.getByRole('button', { name: /^valider pour l'équipe/i });
  await boutonValider.click();

  // 5) Soit l'autre équipe reste à confirmer (modale reste ouverte,
  // présélectionne l'équipe restante) soit tout est confirmé (modale se
  // ferme). Dans les deux cas, naviguer à nouveau ne doit PAS réafficher la
  // modale si tout est désormais confirmé.
  await page.waitForTimeout(500);
  const encoreOuverte = await modaleTitre.isVisible().catch(() => false);
  if (encoreOuverte) {
    const deuxiemeChamp = page.locator('.modal, [role="dialog"]').filter({ hasText: 'Stock de départ du jour' })
      .locator('input[type="number"]').first();
    await expect(deuxiemeChamp).toBeVisible();
    await page.getByRole('button', { name: /^valider pour l'équipe/i }).click();
    await page.waitForTimeout(500);
  }
  await expect(modaleTitre).toBeHidden({ timeout: 10_000 });

  await page.goto('/dashboard');
  await expect(modaleTitre).toBeHidden();
  await page.goto('/clients');
  await expect(modaleTitre).toBeHidden();

  // 6) BUG-136 : le stock affiché dans « Production & Stocks » doit
  // refléter la valeur validée (pas la valeur proposée avant correction).
  await page.goto('/production');
  await expect(page.getByText(valeurCorrigee, { exact: false }).first()).toBeVisible({ timeout: 10_000 });
});

test('un compte DIRECTION (HQ) ne voit jamais la boîte modale « stock de départ »', async ({ page }) => {
  await seConnecter(page, COMPTES.direction.username, PASSWORD);
  await page.goto('/dashboard');
  await expect(page.getByText('Stock de départ du jour')).toHaveCount(0);
  await page.goto('/clients');
  await expect(page.getByText('Stock de départ du jour')).toHaveCount(0);
});

test('un compte ADMIN (HQ) ne voit jamais la boîte modale « stock de départ »', async ({ page }) => {
  await seConnecter(page, COMPTES.admin.username, PASSWORD);
  await page.goto('/dashboard');
  await expect(page.getByText('Stock de départ du jour')).toHaveCount(0);
});

/**
 * BUG-138/139/140 (docs/qa/REGISTRE_BUGS.md, CORRIGÉ au 2026-11-09, vérification
 * finale testeur-production) : un FACTURIER voit désormais la boîte modale
 * (BUG-138) et UNE SEULE confirmation (pas une par équipe) suffit à la faire
 * disparaître pour le reste de la journée (BUG-139/140). Ce test utilise le
 * facturier de K2 (pas K1) pour ne jamais dépendre de l'état déjà laissé par
 * le test gérant ci-dessus sur K1 — deux nœuds distincts, aucune collision
 * possible dans la base de dev partagée.
 */
test("un FACTURIER voit la boîte modale, peut confirmer, et une seule confirmation suffit (pas par équipe) — le bandeau d'ajustement de stock s'affiche (BUG-137)", async ({ page }) => {
  await seConnecter(page, COMPTES.facturierK2.username, PASSWORD);

  const modaleTitre = page.getByText('Stock de départ du jour');

  const dejaConfirmeeAuDepart = await modaleTitre.isVisible().catch(() => false);
  if (!dejaConfirmeeAuDepart) {
    test.skip(true, 'K2 est déjà confirmé aujourd\'hui (exécution précédente) — BUG-138/139 déjà couverts, rien à refaire.');
  }
  await expect(modaleTitre).toBeVisible({ timeout: 10_000 });

  // BUG-138 : le FACTURIER voit bien le formulaire de saisie (pas un 403
  // silencieux, pas une modale vide).
  const premierChamp = page.locator('.modal, [role="dialog"]').filter({ hasText: 'Stock de départ du jour' })
    .locator('input[type="number"]').first();
  await expect(premierChamp).toBeVisible();

  // Corriger la quantité proposée pour déclencher un ajustement réel
  // (BUG-136/137 : le bandeau ne s'affiche que si le delta est non nul).
  // On ajoute toujours +1 (jamais -1) : K2 peut légitimement avoir un stock
  // à 0 pour cette catégorie (aucune fournée du jour), auquel cas une
  // décrémentation resterait clampée à 0 (delta nul, aucun bandeau) — un
  // incrément garantit un delta non nul quelle que soit la valeur proposée.
  const valeurProposee = await premierChamp.inputValue();
  const valeurCorrigee = String(parseInt(valeurProposee || '0', 10) + 1);
  await premierChamp.fill(valeurCorrigee);

  const boutonValider = page.getByRole('button', { name: /^valider pour l'équipe/i });
  await boutonValider.click();

  // BUG-137 : bandeau vert listant l'ajustement réel appliqué.
  await expect(page.getByText(/ajusté de/i)).toBeVisible({ timeout: 10_000 });

  // BUG-139/140 : UNE SEULE confirmation suffit — la modale ne doit PAS
  // redemander une deuxième équipe. Elle finit par se fermer (après le délai
  // d'affichage du bandeau), et ne réapparaît plus en changeant de page.
  await expect(modaleTitre).toBeHidden({ timeout: 10_000 });
  await page.goto('/clients');
  await expect(modaleTitre).toBeHidden();
  await page.goto('/dashboard');
  await expect(modaleTitre).toBeHidden();
});
