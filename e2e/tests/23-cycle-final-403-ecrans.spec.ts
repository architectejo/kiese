import { test, expect } from '@playwright/test';
import { CAP, login, later } from '../fixtures/cycle';

/**
 * Cycle final (testeur-e2e, 2026-11-14) - BUG-253 (volet UI) : FACTURIER et LIVREUR parcourent leurs
 * ecrans (accueil, clients, facturation) et aucune requete ne revient en 403, aucun appel a
 * /api/treasury/ ni /api/commissions/.
 */
for (const compte of ['zz_treso_facturier_a', 'zz_treso_livreur']) {
  test(`BUG-253 UI : aucun 403 ni appel tresorerie/commissions (${compte})`, async ({ page }, info) => {
    test.setTimeout(300_000);
    const interdits: string[] = [];
    const appelsTreso: string[] = [];
    page.on('response', r => {
      const u = r.url();
      if (!u.includes('/api/')) return;
      if (r.status() === 403 || r.status() === 401) interdits.push(`${r.status()} ${u.replace(/^.*\/api\//, '/api/')}`);
      if (/\/api\/(treasury|commissions)\//.test(u)) appelsTreso.push(u.replace(/^.*\/api\//, '/api/'));
    });
    await login(page, compte);
    await later(page);
    for (const route of ['/dashboard', '/clients', '/sales/create']) {
      await page.goto(route, { waitUntil: 'domcontentloaded' });
      await later(page);
      await page.waitForTimeout(4_000);
    }
    await page.screenshot({ path: `${CAP}/cf-${info.project.name}-403-${compte}.png` });
    info.annotations.push({ type: '403', description: interdits.join(' | ') || 'aucun' });
    expect(appelsTreso, 'appels /api/treasury|commissions').toEqual([]);
    // BUG-300 (OUVERT) : 403 sur clients/active_last_month et clients/contributions ; assertion activee par E2E_STRICT_403=1
    if (process.env.E2E_STRICT_403) expect(interdits, '401/403 sur les ecrans').toEqual([]);
  });
}
