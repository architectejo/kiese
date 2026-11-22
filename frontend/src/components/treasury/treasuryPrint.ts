import { treasuryApi } from '@/api/services';
import type { DailySavings } from '@/api/services';
import { fmt } from '@/components/treasury/treasuryShared';

// Impression de l'épargne d'un jour du mois (liste déjà chargée en entier).
export const printSavingsDay = (savingsEntries: DailySavings[], day: string): void => {
    const entries = savingsEntries.filter(s => s.date.split('-')[2] === day);
    if (entries.length === 0) return;
    const dateLabel = new Date(entries[0].date).toLocaleDateString('fr-FR', { day: '2-digit', month: 'long', year: 'numeric' });
    const totalRevenue = entries.reduce((a, s) => a + parseFloat(s.daily_revenue || '0'), 0);
    const totalSavings = entries.reduce((a, s) => a + parseFloat(s.savings_amount || '0'), 0);
    const rows = entries.map(s => `
      <tr>
        <td>${s.node_display || s.node}</td>
        <td style="text-align:right">${fmt(s.flour_sacks)}</td>
        <td style="text-align:right">${fmt(s.daily_revenue)} FC</td>
        <td style="text-align:right">${(parseFloat(s.savings_rate) * 100).toFixed(2)}%</td>
        <td style="text-align:right;font-weight:700">${fmt(s.savings_amount)} FC</td>
      </tr>`).join('');
    const html = `
      <html><head><title>Épargne Journalière — ${dateLabel}</title>
      <style>
        body { font-family: Arial, sans-serif; padding: 24px; color: #111; }
        h1 { font-size: 18px; border-bottom: 2px solid #000; padding-bottom: 8px; }
        table { width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 12px; }
        th, td { border: 1px solid #999; padding: 6px 8px; }
        th { background: #eee; text-align: left; }
        tfoot td { font-weight: bold; background: #f3f4f6; }
      </style></head>
      <body>
        <h1>ÉPARGNE JOURNALIÈRE — ETS. KIESE</h1>
        <p>Date : ${dateLabel}</p>
        <table>
          <thead><tr><th>Boulangerie</th><th style="text-align:right">Sacs PROD</th><th style="text-align:right">Revenu</th><th style="text-align:right">Taux</th><th style="text-align:right">Épargne</th></tr></thead>
          <tbody>${rows}</tbody>
          <tfoot><tr><td colspan="2">TOTAL</td><td style="text-align:right">${fmt(totalRevenue)} FC</td><td></td><td style="text-align:right">${fmt(totalSavings)} FC</td></tr></tfoot>
        </table>
        <script>window.onload = () => window.print();</script>
      </body></html>`;
    const w = window.open('', '_blank', 'width=700,height=900');
    if (w) { w.document.write(html); w.document.close(); }
};

// Bordereau final de versement : lit le rapport serveur puis ouvre la fenêtre d'impression.
// L'erreur d'API est relancée à l'appelant (affichage du `detail`).
export const printFinalVoucherReport = async (dateFrom: string, dateTo: string): Promise<void> => {
      const res = await treasuryApi.vouchers.finalReport({ date_from: dateFrom, date_to: dateTo });
      const { vouchers: periodVouchers, total_disbursed, remaining_balance } = res.data;
      const rows = periodVouchers.map(v => `
        <tr>
          <td>${new Date(v.date).toLocaleDateString('fr-FR')}</td>
          <td>${v.piece_number}</td>
          <td>${v.motif}${v.beneficiary ? ' — ' + v.beneficiary : ''}</td>
          <td style="text-align:right">${fmt(v.physical_cash_total)} FC</td>
        </tr>`).join('');
      const html = `
        <html><head><title>Bordereau Final de Versement</title>
        <style>
          body { font-family: Arial, sans-serif; padding: 24px; color: #111; }
          h1 { font-size: 18px; border-bottom: 2px solid #000; padding-bottom: 8px; }
          table { width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 12px; }
          th, td { border: 1px solid #999; padding: 6px 8px; }
          th { background: #eee; text-align: left; }
          tfoot td { font-weight: bold; background: #f3f4f6; }
          .summary { margin-top: 16px; font-size: 13px; }
          .summary div { display: flex; justify-content: space-between; padding: 4px 0; }
          .sign { margin-top: 60px; display: flex; justify-content: space-between; font-size: 12px; }
          .sign div { width: 40%; border-top: 1px solid #000; text-align: center; padding-top: 6px; }
        </style></head>
        <body>
          <h1>BORDEREAU FINAL DE VERSEMENT — ETS. KIESE</h1>
          <p>Période : ${dateFrom} au ${dateTo}</p>
          <table>
            <thead><tr><th>Date</th><th>N° Pièce</th><th>Motif</th><th style="text-align:right">Montant</th></tr></thead>
            <tbody>${rows || '<tr><td colspan="4" style="text-align:center">Aucun bordereau sur la période</td></tr>'}</tbody>
            <tfoot><tr><td colspan="3">TOTAL DÉCAISSÉ</td><td style="text-align:right">${fmt(total_disbursed)} FC</td></tr></tfoot>
          </table>
          <div class="summary">
            <div><span>Solde restant (Livre de Caisse Direction)</span><strong>${fmt(remaining_balance)} FC</strong></div>
          </div>
          <div class="sign">
            <div>Le Comptable</div>
            <div>La Direction</div>
          </div>
          <script>window.onload = () => window.print();</script>
        </body></html>`;
      const w = window.open('', '_blank', 'width=800,height=1000');
      if (w) { w.document.write(html); w.document.close(); }
};
