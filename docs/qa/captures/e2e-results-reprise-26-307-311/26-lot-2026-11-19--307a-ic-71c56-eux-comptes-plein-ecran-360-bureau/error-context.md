# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: 26-lot-2026-11-19.spec.ts >> (307a) icone + badge, conversation 1-a-1 entre deux comptes, plein ecran 360
- Location: tests\26-lot-2026-11-19.spec.ts:564:5

# Error details

```
TimeoutError: locator.click: Timeout 30000ms exceeded.
Call log:
  - waiting for getByRole('button', { name: /e307_ger6/ }).first()

```

# Test source

```ts
  480 |   await expect(m).toBeVisible();
  481 |   const champ = m.getByLabel(/Reste du jour — Pain 1000 FC/);
  482 |   await expect(champ).toBeVisible();
  483 |   // pas de bouton « ± »
  484 |   await expect(m.getByRole('button', { name: /Changer le signe/ })).toHaveCount(0);
  485 |   // saisie « -3 » : le signe est ecarte (jamais de valeur negative a l'ecran)
  486 |   await champ.fill('');
  487 |   await champ.pressSequentially('-3');
  488 |   const v = await champ.inputValue();
  489 |   expect(v.includes('-'), `valeur saisie « -3 » devenue « ${v} »`).toBeFalsy();
  490 |   test.info().annotations.push({ type: 'observation', description: `saisie « -3 » -> champ affiche « ${v} »` });
  491 |   await champ.fill('');
  492 |   await champ.pressSequentially('-');
  493 |   expect((await champ.inputValue()).includes('-')).toBeFalsy();
  494 |   // refus serveur : on force un negatif dans la requete, le message francais du serveur doit s'afficher
  495 |   await champ.fill('5');
  496 |   let corps = '';
  497 |   await page.route('**/api/production/sessions/*/close/', async route => {
  498 |     corps = route.request().postData() ?? '';
  499 |     await route.continue({ postData: JSON.stringify({ remaining: [{ bread_price: P.p1000, quantity: -3 }] }) });
  500 |   });
  501 |   await m.getByRole('button', { name: 'Confirmer la clôture' }).click();
  502 |   const alerte = m.getByText(/Le reste du jour ne peut pas être négatif/i); // (le texte d'aide « Le reste ne peut pas être négatif » est un autre element)
  503 |   await expect(alerte).toBeVisible({ timeout: 15_000 });
  504 |   const msg = (await alerte.innerText()).trim();
  505 |   test.info().annotations.push({ type: 'message-refus', description: msg });
  506 |   expect(msg).toMatch(/négati/i);
  507 |   expect(msg).not.toMatch(/must|cannot|invalid|negative/i);
  508 |   // BUG-310 : aucun nom de champ technique dans le message
  509 |   expect(msg, 'nom de champ technique visible').not.toMatch(/remaining|«|»/i);
  510 |   expect(msg).toMatch(/Le reste du jour ne peut pas être négatif/i);
  511 |   expect(corps).toContain('remaining');
  512 |   await page.unroute('**/api/production/sessions/*/close/');
  513 |   await expect(m).toBeVisible(); // la fournee n'est pas cloturee
  514 |   await sansDebordement(page, info, 'modale cloture');
  515 |   await page.screenshot({ path: `${CAP}/e307-${info.project.name}-303-refus.png`, fullPage: true });
  516 |   // la fournee K1 equipe B sert aux trois largeurs : seule la derniere (bureau) la cloture vraiment
  517 |   if (i < 2) {
  518 |     await m.getByRole('button', { name: 'Annuler' }).click();
  519 |     await expect(m).toBeHidden();
  520 |     await expect(page.getByRole('dialog', { name: 'Détail Fournée' }).getByText(/Fournée clôturée/)).toHaveCount(0);
  521 |     return;
  522 |   }
  523 |   // cloture valide avec un reste positif
  524 |   await champ.fill(String(REST[i]));
  525 |   await m.getByRole('button', { name: 'Confirmer la clôture' }).click();
  526 |   await expect(m).toBeHidden({ timeout: 20_000 });
  527 |   await expect(page.getByRole('dialog', { name: 'Détail Fournée' }).getByText(/Fournée clôturée/)).toBeVisible();
  528 | });
  529 | 
  530 | /* ------------------------------------------------------------------ */
  531 | /* BUG-307 : messagerie                                                */
  532 | /* ------------------------------------------------------------------ */
  533 | async function contexte(browser: Browser, info: { project: { use: { viewport?: { width: number; height: number } | null } } }, user: string) {
  534 |   const ctx = await browser.newContext({ viewport: info.project.use.viewport ?? undefined });
  535 |   const page = await ctx.newPage();
  536 |   await login(page, user);
  537 |   await later(page);
  538 |   return { ctx, page };
  539 | }
  540 | const iconeChat = (page: Page) => page.getByRole('button', { name: /^Messagerie/ });
  541 | async function ouvrirChat(page: Page) {
  542 |   await later(page);
  543 |   await iconeChat(page).click();
  544 |   await expect(page.getByRole('dialog', { name: 'Messagerie' })).toBeVisible();
  545 | }
  546 | async function verifPleinEcran(page: Page, info: { project: { name: string } }) {
  547 |   const vp = page.viewportSize()!;
  548 |   const box = (await page.getByRole('dialog', { name: 'Messagerie' }).boundingBox())!;
  549 |   if (vp.width <= 768) {
  550 |     expect(Math.round(box.width), 'messagerie pleine largeur').toBe(vp.width);
  551 |     expect(Math.round(box.height), 'messagerie pleine hauteur').toBe(vp.height);
  552 |     expect(Math.round(box.x)).toBe(0);
  553 |   } else {
  554 |     expect(box.width).toBeLessThanOrEqual(vp.width);
  555 |   }
  556 |   await sansDebordement(page, info, 'messagerie');
  557 | }
  558 | async function ecrire(page: Page, texte: string) {
  559 |   const zone = page.getByLabel('Votre message');
  560 |   await zone.fill(texte);
  561 |   await page.getByRole('button', { name: 'Envoyer' }).click();
  562 | }
  563 | 
  564 | test('(307a) icone + badge, conversation 1-a-1 entre deux comptes, plein ecran 360', async ({ browser, request }, info) => {
  565 |   test.setTimeout(240_000);
  566 |   const i = idx(info.project.name);
  567 |   const A = await contexte(browser, info as never, 'zz_e307_fac6');
  568 |   const B = await contexte(browser, info as never, 'zz_e307_ger6');
  569 |   try {
  570 |     await expect(iconeChat(A.page)).toBeVisible({ timeout: 30_000 });
  571 |     await expect(iconeChat(B.page)).toBeVisible();
  572 |     await sansDebordement(A.page, info, 'en-tete avec icone');
  573 |     const tb = await apiToken(request, 'zz_e307_ger6');
  574 |     const avant = (await (await request.get(`${API}/api/chat/unread-count/`, { headers: H(tb) })).json()).unread_count as number;
  575 |     // A ecrit a B
  576 |     await ouvrirChat(A.page);
  577 |     await verifPleinEcran(A.page, info);
  578 |     await A.page.getByRole('button', { name: /Nouvelle/ }).click();
  579 |     await A.page.getByLabel('Rechercher un utilisateur').fill('e307_ger6');
> 580 |     await A.page.getByRole('button', { name: /e307_ger6/ }).first().click();
      |                                                                     ^ TimeoutError: locator.click: Timeout 30000ms exceeded.
  581 |     await expect(A.page.getByRole('heading', { name: /e307_ger6/ })).toBeVisible();
  582 |     const m1 = `Bonjour gerant ${SUF[i]} ${Date.now() % 100000}`;
  583 |     await ecrire(A.page, m1);
  584 |     await expect(A.page.getByRole('log', { name: 'Messages' })).toContainText(m1);
  585 |     await verifPleinEcran(A.page, info);
  586 |     await A.page.screenshot({ path: `${CAP}/e307-${info.project.name}-307a-fil.png` });
  587 |     // badge chez B (sondage 8 s) : il doit passer a `avant + 1`
  588 |     const apres = (await (await request.get(`${API}/api/chat/unread-count/`, { headers: H(tb) })).json()).unread_count as number;
  589 |     expect(apres).toBe(avant + 1);
  590 |     const badge = B.page.getByRole('button', { name: `Messagerie, ${apres} message(s) non lu(s)` });
  591 |     await expect(badge).toBeVisible({ timeout: 40_000 });
  592 |     expect((await badge.innerText()).trim()).toBe(String(apres > 99 ? '99+' : apres));
  593 |     await B.page.screenshot({ path: `${CAP}/e307-${info.project.name}-307a-badge.png` });
  594 |     // B ouvre, voit la conversation, lit, repond
  595 |     await ouvrirChat(B.page);
  596 |     await verifPleinEcran(B.page, info);
  597 |     await B.page.getByRole('button', { name: new RegExp('e307_fac6') }).first().click();
  598 |     await expect(B.page.getByRole('log', { name: 'Messages' })).toContainText(m1);
  599 |     const m2 = `Recu, merci ${SUF[i]} ${Date.now() % 100000}`;
  600 |     await ecrire(B.page, m2);
  601 |     await expect(B.page.getByRole('log', { name: 'Messages' })).toContainText(m2);
  602 |     // le badge de B retombe a sa valeur d'avant (les messages de cette conversation sont marques lus ; les autres conversations gardent leurs non-lus)
  603 |     await expect.poll(async () => (await (await request.get(`${API}/api/chat/unread-count/`, { headers: H(tb) })).json()).unread_count, { timeout: 30_000 }).toBe(avant);
  604 |     const nomApres = avant > 0 ? `Messagerie, ${avant} message(s) non lu(s)` : 'Messagerie';
  605 |     await expect(B.page.getByRole('button', { name: nomApres, exact: true })).toBeVisible({ timeout: 30_000 });
  606 |     // A voit la reponse (sondage)
  607 |     await expect(A.page.getByRole('log', { name: 'Messages' })).toContainText(m2, { timeout: 30_000 });
  608 |     // Echap ferme, bouton retour OK
  609 |     await A.page.keyboard.press('Escape');
  610 |     await expect(A.page.getByRole('dialog', { name: 'Messagerie' })).toBeHidden();
  611 |   } finally {
  612 |     await A.ctx.close(); await B.ctx.close();
  613 |   }
  614 | });
  615 | 
  616 | test('(307b) fil boulangerie (isolation K5/K6) et fil Direction masque hors roles autorises', async ({ browser, request }, info) => {
  617 |   test.setTimeout(240_000);
  618 |   const i = idx(info.project.name);
  619 |   const F = await contexte(browser, info as never, 'zz_e307_fac6');
  620 |   const G6 = await contexte(browser, info as never, 'zz_e307_ger6');
  621 |   const G5 = await contexte(browser, info as never, 'zz_e307_ger5');
  622 |   const D = await contexte(browser, info as never, 'zz_e307_dir');
  623 |   try {
  624 |     const txt = `Fil K6 ${SUF[i]} ${Date.now() % 100000}`;
  625 |     await ouvrirChat(F.page);
  626 |     await expect(F.page.getByRole('button', { name: /Ma boulangerie/ })).toBeVisible();
  627 |     await expect(F.page.getByRole('button', { name: /^Direction/ })).toHaveCount(0);
  628 |     await F.page.getByRole('button', { name: /Ma boulangerie/ }).click();
  629 |     await ecrire(F.page, txt);
  630 |     await expect(F.page.getByRole('log', { name: 'Messages' })).toContainText(txt);
  631 |     await verifPleinEcran(F.page, info);
  632 |     // gerant K6 le voit, avec le nom de l'expediteur
  633 |     await ouvrirChat(G6.page);
  634 |     await expect(G6.page.getByRole('button', { name: /^Direction/ })).toHaveCount(0);
  635 |     await G6.page.getByRole('button', { name: /Ma boulangerie/ }).click();
  636 |     await expect(G6.page.getByRole('log', { name: 'Messages' })).toContainText(txt, { timeout: 30_000 });
  637 |     await expect(G6.page.getByRole('log', { name: 'Messages' })).toContainText('e307_fac6');
  638 |     // gerant K5 : son fil boulangerie ne contient pas le message de K6
  639 |     await ouvrirChat(G5.page);
  640 |     await expect(G5.page.getByRole('button', { name: /^Direction/ })).toHaveCount(0);
  641 |     await G5.page.getByRole('button', { name: /Ma boulangerie/ }).click();
  642 |     await expect(G5.page.getByRole('log', { name: 'Messages' })).not.toContainText(txt);
  643 |     await G5.page.waitForTimeout(500);
  644 |     // direction : fil Direction visible et utilisable
  645 |     await ouvrirChat(D.page);
  646 |     await expect(D.page.getByRole('button', { name: 'Direction', exact: true })).toBeVisible();
  647 |     await D.page.getByRole('button', { name: 'Direction', exact: true }).click();
  648 |     const td = `Direction ${SUF[i]} ${Date.now() % 100000}`;
  649 |     await ecrire(D.page, td);
  650 |     await expect(D.page.getByRole('log', { name: 'Messages' })).toContainText(td);
  651 |     await D.page.screenshot({ path: `${CAP}/e307-${info.project.name}-307b-direction.png` });
  652 |     // cote API : le facturier et le gerant recoivent 403 sur le fil Direction
  653 |     for (const u of ['zz_e307_fac6', 'zz_e307_ger6', 'zz_e307_ger5']) {
  654 |       const r = await request.get(`${API}/api/chat/conversations/direction/`, { headers: H(await apiToken(request, u)) });
  655 |       expect(r.status(), u).toBe(403);
  656 |     }
  657 |   } finally {
  658 |     await F.ctx.close(); await G6.ctx.close(); await G5.ctx.close(); await D.ctx.close();
  659 |   }
  660 | });
  661 | 
  662 | test('(307c) « Voir plus » (35 messages, pages de 30)', async ({ browser }, info) => {
  663 |   test.setTimeout(180_000);
  664 |   const U = await contexte(browser, info as never, 'zz_e307_fac5');
  665 |   try {
  666 |     await ouvrirChat(U.page);
  667 |     await U.page.getByRole('button', { name: /e307_ger5/ }).first().click();
  668 |     const log = U.page.getByRole('log', { name: 'Messages' });
  669 |     await expect(log).toContainText('SEED-35');
  670 |     await expect(log.getByText(/^SEED-\d\d$/)).toHaveCount(30);
  671 |     await expect(log).not.toContainText('SEED-01');
  672 |     const plus = log.getByRole('button', { name: 'Voir plus' });
  673 |     await expect(plus).toBeVisible();
  674 |     await verifPleinEcran(U.page, info);
  675 |     await plus.click();
  676 |     await expect(log.getByText(/^SEED-\d\d$/)).toHaveCount(35);
  677 |     await expect(log).toContainText('SEED-01');
  678 |     await expect(plus).toHaveCount(0);
  679 |     // ordre chronologique conserve
  680 |     const textes = await log.getByText(/^SEED-\d\d$/).allInnerTexts();
```