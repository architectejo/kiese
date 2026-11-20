# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: 26-lot-2026-11-19.spec.ts >> (307c) « Voir plus » (35 messages, pages de 30)
- Location: tests\26-lot-2026-11-19.spec.ts:662:5

# Error details

```
TimeoutError: locator.click: Timeout 30000ms exceeded.
Call log:
  - waiting for getByRole('button', { name: /e307_ger5/ }).first()

```

# Test source

```ts
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
  580 |     await A.page.getByRole('button', { name: /e307_ger6/ }).first().click();
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
> 667 |     await U.page.getByRole('button', { name: /e307_ger5/ }).first().click();
      |                                                                     ^ TimeoutError: locator.click: Timeout 30000ms exceeded.
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
  681 |     expect(textes).toEqual([...textes].sort());
  682 |     await U.page.screenshot({ path: `${CAP}/e307-${info.project.name}-307c-voirplus.png` });
  683 |   } finally { await U.ctx.close(); }
  684 | });
  685 | 
  686 | test('(307d) limites : 2000/2001 caracteres, texte HTML litteral, 429 en francais', async ({ browser, request }, info) => {
  687 |   test.setTimeout(240_000);
  688 |   const i = idx(info.project.name);
  689 |   const user = `zz_e307_flo_${SUF[i]}`;
  690 |   const U = await contexte(browser, info as never, user);
  691 |   const R = await contexte(browser, info as never, 'zz_e307_ger6');
  692 |   try {
  693 |     await ouvrirChat(U.page);
  694 |     await U.page.getByRole('button', { name: /Nouvelle/ }).click();
  695 |     await U.page.getByLabel('Rechercher un utilisateur').fill('e307_ger6');
  696 |     await U.page.getByRole('button', { name: /e307_ger6/ }).first().click();
  697 |     const log = U.page.getByRole('log', { name: 'Messages' });
  698 |     const envoyer = U.page.getByRole('button', { name: 'Envoyer' });
  699 |     const zone = U.page.getByLabel('Votre message');
  700 |     // 2001 : compteur rouge, envoi bloque
  701 |     await zone.fill('x'.repeat(2001));
  702 |     await expect(U.page.getByText('2 001 / 2 000')).toBeVisible();
  703 |     await expect(envoyer).toBeDisabled();
  704 |     await verifPleinEcran(U.page, info);
  705 |     await U.page.screenshot({ path: `${CAP}/e307-${info.project.name}-307d-2001.png` });
  706 |     // 2000 sans espace : accepte, ne deborde pas
  707 |     await zone.fill('y'.repeat(2000));
  708 |     await expect(U.page.getByText('2 000 / 2 000')).toBeVisible();
  709 |     await expect(envoyer).toBeEnabled();
  710 |     await envoyer.click();
  711 |     await expect(log).toContainText('y'.repeat(50));
  712 |     await sansDebordement(U.page, info, 'message de 2000 caracteres');
  713 |     // HTML : affiche litteralement, jamais interprete
  714 |     const html = `<b>gras</b><img src=x onerror="window.__xss307=1"><script>window.__xss307=2</script>`;
  715 |     await U.page.evaluate(() => { (window as unknown as Rec).__xss307 = undefined; });
  716 |     await zone.fill(html);
  717 |     await envoyer.click();
  718 |     await expect(log).toContainText(html);
  719 |     expect(await log.locator('b, img, script').count()).toBe(0);
  720 |     expect(await U.page.evaluate(() => (window as unknown as Rec).__xss307)).toBeUndefined();
  721 |     // meme rendu chez le destinataire et dans l'aperçu de la liste
  722 |     await ouvrirChat(R.page);
  723 |     await expect(R.page.getByRole('dialog', { name: 'Messagerie' })).toContainText(`<b>gras</b>`, { timeout: 30_000 });
  724 |     expect(await R.page.getByRole('dialog', { name: 'Messagerie' }).locator('b, img, script').count()).toBe(0);
  725 |     expect(await R.page.evaluate(() => (window as unknown as Rec).__xss307)).toBeUndefined();
  726 |     await U.page.screenshot({ path: `${CAP}/e307-${info.project.name}-307d-html.png` });
  727 |     // 429 : on sature le quota (10 messages / 30 s) par l'API puis on envoie par l'ecran
  728 |     const tu = await apiToken(request, user);
  729 |     const conv = await (await request.get(`${API}/api/chat/conversations/`, { headers: H(tu) })).json();
  730 |     const cid = (conv as Rec[]).find(c => (c.other_user as Rec | null)?.name?.toString().includes('e307_ger6'))!.id;
  731 |     let refus = 0;
  732 |     for (let k = 0; k < 14 && refus === 0; k++) {
  733 |       const r = await request.post(`${API}/api/chat/conversations/${cid}/messages/`, { headers: H(tu), data: { body: `rafale ${k}` } });
  734 |       if (r.status() === 429) refus++;
  735 |     }
  736 |     expect(refus, 'le serveur finit par repondre 429').toBeGreaterThan(0);
  737 |     await zone.fill('trop vite');
  738 |     await envoyer.click();
  739 |     const al = U.page.getByRole('alert').filter({ hasText: /trop de messages/i });
  740 |     await expect(al).toBeVisible({ timeout: 15_000 });
  741 |     const msg = (await al.innerText()).trim();
  742 |     test.info().annotations.push({ type: 'message-429', description: msg });
  743 |     expect(msg).not.toMatch(/Request failed|status code|Too Many/i);
  744 |     await sansDebordement(U.page, info, 'message 429');
  745 |     await U.page.screenshot({ path: `${CAP}/e307-${info.project.name}-307d-429.png` });
  746 |   } finally { await U.ctx.close(); await R.ctx.close(); }
  747 | });
  748 | 
  749 | /* (place en dernier : le mode serie interrompt les tests suivants en cas d'echec) */
  750 | /* BUG-311 : la valeur du sac n'est jamais affichee avant le chargement de la config */
  751 | test('(311) valeur du sac : ni « 1 sac = » ni 200 000 FC avant le chargement, puis la valeur de la boulangerie', async ({ page, request }, info) => {
  752 |   test.setTimeout(180_000);
  753 |   const tg = await apiToken(request, 'zz_e307_ger6');
  754 |   const noeud = liste(await (await request.get(`${API}/api/core/nodes/`, { headers: H(tg) })).json()).find(n => n.code === 'K6')!;
  755 |   const valeurSac = Number(noeud.sac_value_fc);
  756 |   expect(valeurSac, 'precondition : la valeur du sac de K6 differe de 200 000').not.toBe(200000);
  757 |   await login(page, 'zz_e307_ger6');
  758 |   await later(page);
  759 |   await annonces(page);
  760 |   let libere!: () => void;
  761 |   const porte = new Promise<void>(r => { libere = r; });
  762 |   // la valeur du sac de Production vient de la liste des boulangeries + config (Promise.all) : retenir /nodes/ suffit
  763 |   // (retenir /config/ bloque aussi l'ecran de connexion au serveur central du gabarit)
  764 |   await page.route('**/api/core/nodes/**', async route => { await porte; await route.continue(); });
  765 |   await page.goto('/production', { waitUntil: 'domcontentloaded' });
  766 |   const panneau = page.getByTestId('batch-in-progress-panel');
  767 |   await expect(panneau).toBeVisible({ timeout: 30_000 });
```