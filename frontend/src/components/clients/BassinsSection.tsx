import React from 'react';
import { FiPrinter, FiDownload } from 'react-icons/fi';
import type { BakeryNode, BassinRow } from '@/api/services';

interface BassinsSectionProps {
  nodesList: BakeryNode[];
  bassinNode: string;
  setBassinNode: (v: string) => void;
  bassinMonth: number;
  setBassinMonth: (v: number) => void;
  bassinYear: number;
  setBassinYear: (v: number) => void;
  bassinRows: BassinRow[];
  bassinThresholds: Record<string, number>;
  bassinLoading: boolean;
  bassinMsg: string | null;
  loadBassins: () => void | Promise<void>;
}

/** §7 — Classement BASSINS (Direction centrale) : filtres, tableau par catégorie, impression et export CSV. */
export const BassinsSection: React.FC<BassinsSectionProps> = ({
  nodesList, bassinNode, setBassinNode, bassinMonth, setBassinMonth, bassinYear, setBassinYear,
  bassinRows, bassinThresholds, bassinLoading, bassinMsg, loadBassins,
}) => {
  const handleBassinPrint = () => {
    const nodeName = nodesList.find(n => n.id === bassinNode)?.code || '';
    const monthLabel = new Date(2000, bassinMonth - 1).toLocaleString('fr-FR', { month: 'long' });
    const dateStr = new Date().toLocaleDateString('fr-FR', { day: '2-digit', month: 'long', year: 'numeric' });
    const CATS = ['GRAND FORMAT', 'INTER G&M', 'INTER M&PT', 'MOYEN', 'PETIT'];
    const CAT_COLORS = ['#b45309','#1d4ed8','#059669','#7c3aed','#6b7280'];
    const totCmd = bassinRows.reduce((s, r) => s + parseFloat(r.order_value), 0);
    const totBp  = bassinRows.reduce((s, r) => s + parseFloat(r.bp), 0);
    const totCm  = bassinRows.reduce((s, r) => s + parseFloat(r.cm), 0);
    const totNet = bassinRows.reduce((s, r) => s + parseFloat(r.net_payable), 0);
    const catSections = CATS.map((cat, ci) => {
      const rows = bassinRows.filter(r => r.category === cat);
      if (!rows.length) return '';
      const trs = rows.map(r => `<tr>
        <td style="text-align:center;font-weight:bold;color:${CAT_COLORS[ci]}">${r.rank}</td>
        <td style="font-weight:bold;color:#1e40af">${r.client_code}</td>
        <td>${r.client_name}</td>
        <td style="text-align:right">${parseFloat(r.order_value).toLocaleString('fr-FR')}</td>
        <td style="text-align:right;color:${parseFloat(r.bp)>0?'#d97706':'#059669'}">${parseFloat(r.bp).toLocaleString('fr-FR')}</td>
        <td style="text-align:right;color:#2563eb">${parseFloat(r.cm).toLocaleString('fr-FR')}</td>
        <td style="text-align:right;font-weight:bold;color:${parseFloat(r.net_payable)<0?'#dc2626':'#111'}">${parseFloat(r.net_payable).toLocaleString('fr-FR')}</td>
      </tr>`).join('');
      return `<tr><td colspan="7" style="padding:5px 8px;background:${CAT_COLORS[ci]}18;border-top:2px solid ${CAT_COLORS[ci]}88;font-weight:800;font-size:11px;color:${CAT_COLORS[ci]};letter-spacing:0.05em">${cat} — ${rows.length} client(s)</td></tr>${trs}`;
    }).join('');
    const html = `<!DOCTYPE html><html lang="fr"><head><meta charset="UTF-8"><title>Classement BASSINS — ${nodeName}</title>
      <style>*{box-sizing:border-box}body{font-family:Arial,sans-serif;font-size:10.5px;padding:20px;color:#111}
      h1{font-size:14px;margin:0 0 2px}.sub{font-size:10px;color:#666;margin-bottom:14px}
      table{width:100%;border-collapse:collapse}th{background:#f3f4f6;font-weight:bold;padding:5px 7px;border:1px solid #d1d5db;font-size:9.5px;text-transform:uppercase}
      td{padding:4px 7px;border:1px solid #e5e7eb}tr:nth-child(even) td{background:#fafafa}
      tfoot td{font-weight:bold;background:#f3f4f6;border-top:2px solid #9ca3af}
      @media print{body{padding:10px}}</style></head><body>
      <h1>§7 — Classement BASSINS — ${nodeName}</h1>
      <div class="sub">Période : ${monthLabel} ${bassinYear} · Imprimé le ${dateStr} · ${bassinRows.length} client(s)</div>
      <table><thead><tr>
        <th style="text-align:center">Rang</th><th>Code</th><th>Client</th>
        <th style="text-align:right">Commande (FC)</th><th style="text-align:right">BP (FC)</th>
        <th style="text-align:right">CM (FC)</th><th style="text-align:right">Net à Payer (FC)</th>
      </tr></thead><tbody>${catSections}</tbody>
      <tfoot><tr>
        <td colspan="3">${bassinRows.length} client(s)</td>
        <td style="text-align:right">${totCmd.toLocaleString('fr-FR')}</td>
        <td style="text-align:right">${totBp.toLocaleString('fr-FR')}</td>
        <td style="text-align:right;color:#2563eb">${totCm.toLocaleString('fr-FR')}</td>
        <td style="text-align:right">${totNet.toLocaleString('fr-FR')}</td>
      </tr></tfoot></table></body></html>`;
    const win = window.open('', '_blank', 'width=1050,height=750');
    if (!win) return;
    win.document.write(html);
    win.document.close();
    win.focus();
    setTimeout(() => { win.print(); }, 400);
  };

  const handleBassinExport = () => {
    const nodeName = nodesList.find(n => n.id === bassinNode)?.code || '';
    const monthLabel = new Date(2000, bassinMonth - 1).toLocaleString('fr-FR', { month: 'long' });
    const headers = ['Catégorie', 'Rang', 'Code', 'Client', 'Commande (FC)', 'BP (FC)', 'CM (FC)', 'Net à Payer (FC)'];
    const rows = bassinRows.map(r => [
      r.category, r.rank, r.client_code, r.client_name,
      parseFloat(r.order_value), parseFloat(r.bp), parseFloat(r.cm), parseFloat(r.net_payable),
    ]);
    const csv = [headers, ...rows]
      .map(row => row.map(cell => `"${String(cell).replace(/"/g, '""')}"`).join(';'))
      .join('\r\n');
    const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `bassins_${nodeName}_${monthLabel}_${bassinYear}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  return (
        <div style={{ background: 'hsl(var(--bg-secondary))', border: '1px solid hsl(var(--border-color))', borderRadius: 12, padding: 24 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, flexWrap: 'wrap', gap: 8 }}>
            <h3 style={{ margin: 0, fontWeight: 700, fontSize: '1rem', color: 'hsl(var(--text-primary))' }}>
              §7 — Classement BASSINS
            </h3>
            {bassinRows.length > 0 && (
              <div style={{ display: 'flex', gap: 8 }}>
                <button
                  onClick={handleBassinPrint}
                  style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '5px 12px', borderRadius: 6, border: '1px solid hsl(var(--border-color))', background: 'hsl(var(--bg-primary))', color: 'hsl(var(--text-primary))', cursor: 'pointer', fontSize: '0.75rem', fontWeight: 600 }}
                  title="Imprimer le tableau"
                >
                  <FiPrinter size={13} />
                  <span>Imprimer</span>
                </button>
                <button
                  onClick={handleBassinExport}
                  style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '5px 12px', borderRadius: 6, border: '1px solid hsl(var(--border-color))', background: 'hsl(var(--bg-primary))', color: 'hsl(var(--text-primary))', cursor: 'pointer', fontSize: '0.75rem', fontWeight: 600 }}
                  title="Exporter en Excel (CSV)"
                >
                  <FiDownload size={13} />
                  <span>Excel</span>
                </button>
              </div>
            )}
          </div>

          {/* Filters */}
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 14, alignItems: 'flex-end' }}>
            {nodesList.length > 0 && (
              <div>
                <label style={{ fontSize: '0.72rem', color: 'hsl(var(--text-secondary))', display: 'block', marginBottom: 3 }}>Succursale</label>
                <select value={bassinNode} onChange={e => setBassinNode(e.target.value)}
                  style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid hsl(var(--border-color))', background: 'hsl(var(--bg-primary))', color: 'hsl(var(--text-primary))', fontSize: '0.875rem' }}>
                  <option value="">— Choisir —</option>
                  {nodesList.map(n => <option key={n.id} value={n.id}>{n.code} — {n.name}</option>)}
                </select>
              </div>
            )}
            <div>
              <label style={{ fontSize: '0.72rem', color: 'hsl(var(--text-secondary))', display: 'block', marginBottom: 3 }}>Mois</label>
              <select value={bassinMonth} onChange={e => setBassinMonth(Number(e.target.value))}
                style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid hsl(var(--border-color))', background: 'hsl(var(--bg-primary))', color: 'hsl(var(--text-primary))', fontSize: '0.875rem' }}>
                {Array.from({ length: 12 }, (_, i) => i + 1).map(m => (
                  <option key={m} value={m}>{new Date(2000, m - 1).toLocaleString('fr-FR', { month: 'long' })}</option>
                ))}
              </select>
            </div>
            <div>
              <label style={{ fontSize: '0.72rem', color: 'hsl(var(--text-secondary))', display: 'block', marginBottom: 3 }}>Année</label>
              <select value={bassinYear} onChange={e => setBassinYear(Number(e.target.value))}
                style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid hsl(var(--border-color))', background: 'hsl(var(--bg-primary))', color: 'hsl(var(--text-primary))', fontSize: '0.875rem' }}>
                {[2024, 2025, 2026, 2027].map(y => <option key={y} value={y}>{y}</option>)}
              </select>
            </div>
            <button onClick={loadBassins} disabled={!bassinNode || bassinLoading}
              style={{ padding: '7px 18px', borderRadius: 6, border: 'none', background: 'hsl(var(--accent-color))', color: '#fff', fontWeight: 600, cursor: 'pointer', fontSize: '0.875rem', opacity: !bassinNode ? 0.5 : 1 }}>
              {bassinLoading ? 'Chargement…' : 'Charger'}
            </button>
            {bassinMsg && <span style={{ fontSize: '0.8rem', color: 'hsl(var(--color-warning))' }}>{bassinMsg}</span>}
          </div>

          {/* Thresholds legend */}
          {Object.keys(bassinThresholds).length > 0 && (
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 14 }}>
              {['GRAND FORMAT', 'INTER G&M', 'INTER M&PT', 'MOYEN', 'PETIT'].map((cat, i) => {
                const colors = ['hsl(45,90%,40%)','hsl(200,80%,40%)','hsl(160,60%,40%)','hsl(280,50%,45%)','hsl(0,0%,50%)'];
                const thresh = bassinThresholds[cat];
                return (
                  <div key={cat} style={{ padding: '4px 10px', borderRadius: 10, background: colors[i] + '22', border: `1px solid ${colors[i]}55`, fontSize: '0.72rem', fontWeight: 700, color: colors[i] }}>
                    {cat}{thresh ? ` ≥ ${thresh.toLocaleString('fr-FR')} FC` : ' < seuil'}
                  </div>
                );
              })}
            </div>
          )}

          {/* Table grouped by category */}
          {bassinRows.length > 0 && (() => {
            const CATS = ['GRAND FORMAT', 'INTER G&M', 'INTER M&PT', 'MOYEN', 'PETIT'];
            const COLORS = ['hsl(45,90%,40%)','hsl(200,80%,40%)','hsl(160,60%,40%)','hsl(280,50%,45%)','hsl(0,0%,50%)'];
            return (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem' }}>
                  <thead>
                    <tr style={{ background: 'hsl(var(--bg-tertiary))', borderBottom: '2px solid hsl(var(--border-color))' }}>
                      {['Rang', 'Code', 'Client', 'Commande (FC)', 'BP (FC)', 'CM (FC)', 'Net à Payer (FC)'].map(h => (
                        <th key={h} style={{ padding: '7px 10px', textAlign: ['Rang'].includes(h) ? 'center' : ['Commande (FC)','BP (FC)','CM (FC)','Net à Payer (FC)'].includes(h) ? 'right' : 'left', fontWeight: 600, color: 'hsl(var(--text-secondary))', fontSize: '0.72rem', textTransform: 'uppercase', letterSpacing: '0.04em' }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {CATS.map((cat, ci) => {
                      const catRows = bassinRows.filter(r => r.category === cat);
                      if (catRows.length === 0) return null;
                      return [
                        <tr key={`cat-${cat}`}>
                          <td colSpan={7} style={{ padding: '6px 10px', background: COLORS[ci] + '18', borderTop: '2px solid ' + COLORS[ci] + '66', borderBottom: '1px solid ' + COLORS[ci] + '44', fontWeight: 800, fontSize: '0.78rem', color: COLORS[ci], letterSpacing: '0.05em' }}>
                            {cat} — {catRows.length} client(s)
                          </td>
                        </tr>,
                        ...catRows.map(r => (
                          <tr key={r.client_code} style={{ borderBottom: '1px solid hsl(var(--border-color))' }}>
                            <td style={{ padding: '6px 10px', textAlign: 'center', fontWeight: 800, color: COLORS[ci] }}>{r.rank}</td>
                            <td style={{ padding: '6px 10px', fontWeight: 700, color: 'hsl(var(--accent-color))' }}>{r.client_code}</td>
                            <td style={{ padding: '6px 10px' }}>{r.client_name}</td>
                            <td style={{ padding: '6px 10px', textAlign: 'right', fontWeight: 600 }}>{parseFloat(r.order_value).toLocaleString('fr-FR')}</td>
                            <td style={{ padding: '6px 10px', textAlign: 'right', color: parseFloat(r.bp) > 0 ? 'hsl(var(--color-warning))' : 'hsl(var(--color-success))' }}>{parseFloat(r.bp).toLocaleString('fr-FR')}</td>
                            <td style={{ padding: '6px 10px', textAlign: 'right', color: 'hsl(var(--color-info))' }}>{parseFloat(r.cm).toLocaleString('fr-FR')}</td>
                            <td style={{ padding: '6px 10px', textAlign: 'right', fontWeight: 700, color: parseFloat(r.net_payable) < 0 ? 'hsl(var(--color-danger))' : 'hsl(var(--text-primary))' }}>{parseFloat(r.net_payable).toLocaleString('fr-FR')}</td>
                          </tr>
                        )),
                      ];
                    })}
                  </tbody>
                  <tfoot>
                    <tr style={{ background: 'hsl(var(--bg-tertiary))', borderTop: '2px solid hsl(var(--border-color))', fontWeight: 800 }}>
                      <td colSpan={3} style={{ padding: '7px 10px' }}>{bassinRows.length} client(s)</td>
                      <td style={{ padding: '7px 10px', textAlign: 'right' }}>{bassinRows.reduce((s, r) => s + parseFloat(r.order_value), 0).toLocaleString('fr-FR')}</td>
                      <td style={{ padding: '7px 10px', textAlign: 'right' }}>{bassinRows.reduce((s, r) => s + parseFloat(r.bp), 0).toLocaleString('fr-FR')}</td>
                      <td style={{ padding: '7px 10px', textAlign: 'right', color: 'hsl(var(--color-info))' }}>{bassinRows.reduce((s, r) => s + parseFloat(r.cm), 0).toLocaleString('fr-FR')}</td>
                      <td style={{ padding: '7px 10px', textAlign: 'right' }}>{bassinRows.reduce((s, r) => s + parseFloat(r.net_payable), 0).toLocaleString('fr-FR')}</td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            );
          })()}
        </div>
  );
};
