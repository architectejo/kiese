import type { FacturierReport, ProductionSession } from '@/api/services';

/** Résumé des ventes de pains par catégorie (réponse de `salesApi.breadSummary`). */
export interface BreadSoldSummary {
  by_category: Array<{ unit_price: number; total_qty: number; total_fc: number }>;
  grand_total_qty: number;
  grand_total_fc: number;
}

/** Récapitulatif de production du jour (§5.1.1) : sacs, valeur théorique, ventes par catégorie. */
export interface ProductionRecap {
  totalSacs: number;
  totalTheorFC: number;
  prodMap: Record<number, number>;
  soldMap: Record<number, { qty: number; fc: number }>;
  cats: number[];
  actualSalesFC: number;
  ecart: number;
}

export const computeProductionRecap = (
  sessions: ProductionSession[],
  breadSold: BreadSoldSummary | null,
): ProductionRecap => {
  const totalSacs = sessions.reduce((s, sess) => s + parseFloat(sess.flour_sacks_used || '0'), 0);
  const totalTheorFC = sessions.reduce((s, sess) => s + (sess.theoretical_yield || 0), 0);
  const prodMap: Record<number, number> = {};
  sessions.forEach(sess => (sess.lines || []).forEach(ln => {
    const up = ln.unit_price ?? 0;
    prodMap[up] = (prodMap[up] || 0) + (ln.quantity || 0);
  }));
  const soldMap: Record<number, { qty: number; fc: number }> = {};
  (breadSold?.by_category || []).forEach(c => { soldMap[c.unit_price] = { qty: c.total_qty, fc: c.total_fc }; });
  const cats = Array.from(new Set([...Object.keys(prodMap).map(Number), ...Object.keys(soldMap).map(Number)])).sort((a, b) => a - b);
  const actualSalesFC = breadSold?.grand_total_fc ?? 0;
  return { totalSacs, totalTheorFC, prodMap, soldMap, cats, actualSalesFC, ecart: actualSalesFC - totalTheorFC };
};

/** Impression individuelle d'un rapport rétroactif (BUG-175). */
export const printPastReport = (r: FacturierReport): void => {
  const n = (v: string) => Math.round(parseFloat(v || '0')).toLocaleString('fr-FR');
  const html = `<!DOCTYPE html><html lang="fr"><head><meta charset="UTF-8">
      <title>Rapport facturier ${r.date}</title>
      <style>body{font-family:Arial,sans-serif;font-size:12px;margin:20px}td,th{border:1px solid #ddd;padding:4px 8px}table{border-collapse:collapse}</style></head><body>
      <h1 style="font-size:14px">Rapport facturier — ${new Date(r.date).toLocaleDateString('fr-FR')} (date rétroactive)</h1>
      <table><thead><tr><th>Boulangerie</th><th>Équipe</th><th>Cash</th><th>Crédit</th><th>Théorique</th><th>Statut</th></tr></thead>
      <tbody><tr><td>${r.node_display || r.node_origin || '—'}</td><td>Éq. ${r.team}</td><td>${n(r.total_cash_sales)} FC</td><td>${n(r.total_credit_sales)} FC</td><td>${n(r.theoretical_cash)} FC</td><td>${r.is_validated ? 'Validé' : 'En attente'}</td></tr></tbody></table>
      <script>window.onload=()=>{ window.print(); window.onafterprint=()=>window.close(); }</script></body></html>`;
  const w = window.open('', '_blank', 'width=800,height=600');
  if (w) { w.document.write(html); w.document.close(); }
};

/** Impression §5.1.1 — Rapport journalier des facturiers. */
export const print511 = (args: {
  today: string;
  nodeLabel: string;
  recap: ProductionRecap;
  effectiveSacValueFc: number;
  reports: FacturierReport[];
}): void => {
  const { today, nodeLabel, recap, effectiveSacValueFc, reports } = args;
  const { totalSacs, totalTheorFC, prodMap, soldMap, cats, actualSalesFC: actualFC, ecart } = recap;
  const fmtN = (n: number) => Math.round(n).toLocaleString('fr-FR');

  const reportRows = reports.map(r => `
      <tr>
        <td>${r.node_display || r.node_origin || '—'}</td>
        <td>Éq. ${r.team}</td>
        <td style="text-align:right;font-weight:700">${fmtN(parseFloat(r.total_cash_sales || '0'))} FC</td>
        <td style="text-align:right">${fmtN(parseFloat(r.total_credit_sales || '0'))} FC</td>
        <td style="text-align:right;font-weight:700">${fmtN(parseFloat(r.theoretical_cash || '0'))} FC</td>
        <td style="text-align:center">${r.is_validated ? '✓ Validé' : 'En attente'}</td>
      </tr>`).join('');

  const catRows = cats.map(cat => {
    const prod = prodMap[cat] ?? 0;
    const s    = soldMap[cat] ?? { qty: 0, fc: 0 };
    const rest = prod - s.qty;
    return `<tr>
        <td style="font-weight:700">${fmtN(cat)} FC</td>
        <td style="text-align:right">${fmtN(s.qty)} × ${fmtN(cat)} FC = <strong>${fmtN(s.fc)} FC</strong></td>
        <td style="text-align:right">${prod > 0 ? fmtN(prod) : '—'}</td>
        <td style="text-align:right;font-weight:700;color:${rest < 0 ? '#dc2626' : rest > 0 ? '#374151' : '#16a34a'}">${rest > 0 ? '+' : ''}${fmtN(rest)}</td>
      </tr>`;
  }).join('');

  const html = `<!DOCTYPE html><html lang="fr"><head>
      <meta charset="UTF-8"><title>§5.1.1 — Rapport Facturier ${today}</title>
      <style>
        body { font-family: Arial, sans-serif; font-size: 11px; color: #111; margin: 20px; }
        h1 { font-size: 14px; margin: 0 0 4px; }
        .sub { font-size: 10px; color: #666; margin-bottom: 16px; }
        .section { border: 1px solid #ddd; border-radius: 4px; padding: 10px 12px; margin-bottom: 14px; }
        .section-title { font-size: 9px; text-transform: uppercase; letter-spacing: .05em; color: #888; font-weight: 700; margin-bottom: 6px; }
        .formula { font-size: 14px; font-weight: 700; }
        table { width: 100%; border-collapse: collapse; margin-top: 6px; }
        th { background: #f3f4f6; font-size: 9px; text-transform: uppercase; padding: 4px 6px; border: 1px solid #ddd; }
        td { padding: 4px 6px; border: 1px solid #e5e7eb; font-size: 10px; }
        .balance { padding: 10px 14px; border-radius: 4px; display: flex; justify-content: space-between; align-items: center;
          border: 1px solid ${ecart === 0 ? '#16a34a' : Math.abs(ecart) < 10000 ? '#d97706' : '#dc2626'};
          background: ${ecart === 0 ? '#f0fdf4' : Math.abs(ecart) < 10000 ? '#fffbeb' : '#fef2f2'}; }
        @media print { body { margin: 10px; } }
      </style></head><body>
      <h1>§5.1.1 — Rapport Journalier des Facturiers</h1>
      <div class="sub">Date : ${today} &nbsp;|&nbsp; Succursale : ${nodeLabel} &nbsp;|&nbsp; Imprimé le ${new Date().toLocaleString('fr-FR')}</div>

      ${totalSacs > 0 ? `<div class="section">
        <div class="section-title">Facturier — Montant Attendu (Sacs)</div>
        <div class="formula">${fmtN(totalSacs)} sac${totalSacs > 1 ? 's' : ''} × ${fmtN(totalSacs > 0 ? totalTheorFC / totalSacs : effectiveSacValueFc)} FC = <span style="color:#b45309">${fmtN(totalTheorFC)} FC</span></div>
      </div>` : ''}

      ${cats.length > 0 ? `<div class="section">
        <div class="section-title">Ventes du Jour — Résultat</div>
        <table>
          <thead><tr><th>Catégorie</th><th>Ventes (qté × prix = total)</th><th style="text-align:right">Produits</th><th style="text-align:right">Restant</th></tr></thead>
          <tbody>${catRows}</tbody>
          <tfoot><tr style="background:#f3f4f6;font-weight:700">
            <td>TOTAL VENTES</td><td style="text-align:right;font-size:12px;color:#16a34a">${fmtN(actualFC)} FC</td><td></td><td></td>
          </tr></tfoot>
        </table>
      </div>` : ''}

      <div class="balance">
        <div><strong>Attendu :</strong> ${fmtN(totalTheorFC)} FC &nbsp;&nbsp; <strong>Obtenu :</strong> ${fmtN(actualFC)} FC</div>
        <div style="font-size:14px;font-weight:700;color:${ecart === 0 ? '#16a34a' : Math.abs(ecart) < 10000 ? '#d97706' : '#dc2626'}">
          ${ecart === 0 ? 'ÉQUILIBRÉ — PCC' : `Écart : ${ecart > 0 ? '+' : ''}${fmtN(ecart)} FC`}
        </div>
      </div>

      ${reports.length > 0 ? `<div class="section" style="margin-top:14px">
        <div class="section-title">Rapports par Facturier</div>
        <table>
          <thead><tr><th>Boulangerie</th><th>Équipe</th><th style="text-align:right">Cash</th><th style="text-align:right">Crédit</th><th style="text-align:right">Théorique</th><th style="text-align:center">Statut</th></tr></thead>
          <tbody>${reportRows}</tbody>
        </table>
      </div>` : ''}
      <script>window.onload=()=>{ window.print(); window.onafterprint=()=>window.close(); }</script>
    </body></html>`;

  const w = window.open('', '_blank', 'width=800,height=600');
  if (w) { w.document.write(html); w.document.close(); }
};
