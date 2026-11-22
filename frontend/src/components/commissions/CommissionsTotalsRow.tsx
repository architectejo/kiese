import React from 'react';

/** Format monétaire FC : « 2 000 FC » (sans décimales). */
export const formatFc = (value: string | number | null | undefined): string => {
  const n = typeof value === 'number' ? value : parseFloat(value ?? '0');
  return `${(Number.isFinite(n) ? n : 0).toLocaleString('fr-FR', { maximumFractionDigits: 0 })} FC`;
};

export interface CommissionTotals {
  orders: number;
  cm: number;
  cotisation: number;
  carte: number;
  net: number;
}

interface Props {
  /** `null` = totaux pas encore disponibles (chargement). */
  totals: CommissionTotals | null;
  label: string;
}

const cell: React.CSSProperties = { padding: '8px 10px', fontWeight: 800, whiteSpace: 'nowrap' };

/** BUG-417 : ligne de totaux verticaux du tableau « Situation des Ristournes & Rémunérations ». */
export const CommissionsTotalsRow: React.FC<Props> = ({ totals, label }) => (
  <tfoot>
    <tr data-testid="cm-totals-row" style={{ backgroundColor: 'hsl(var(--bg-tertiary))', borderTop: '2px solid hsl(var(--border-color))' }}>
      <td style={cell}>{label}</td>
      <td style={cell}>{totals ? formatFc(totals.orders) : '…'}</td>
      <td style={cell}></td>
      <td style={cell}>{totals ? formatFc(totals.cm) : '…'}</td>
      <td style={cell}></td>
      <td style={{ ...cell, color: 'hsl(var(--color-danger))' }} data-testid="cm-total-cotisation">{totals ? formatFc(totals.cotisation) : '…'}</td>
      <td style={{ ...cell, color: 'hsl(var(--color-danger))' }} data-testid="cm-total-carte">{totals ? formatFc(totals.carte) : '…'}</td>
      <td style={{ ...cell, color: 'hsl(var(--color-success))' }}>{totals ? formatFc(totals.net) : '…'}</td>
      <td style={cell} colSpan={2}></td>
    </tr>
  </tfoot>
);
