import React from 'react';
import { FiBook, FiRefreshCw } from 'react-icons/fi';
import type { CashClosure } from '@/api/services';
import { BILLS, fmt } from '@/components/treasury/treasuryShared';

interface SummaryProps {
  today: string;
  closures: CashClosure[];
  isLoading: boolean;
  isComplete: boolean;
  progress: string;
}

/** Synthèse globale — billetage de toutes les boulangeries (siège). */
export const BilletageSummaryTable: React.FC<SummaryProps> = ({ today, closures, isLoading, isComplete, progress }) => (
  <div className="glass-card" style={{ padding: '14px', overflowX: 'auto' }}>
    <h2 style={{ fontSize: '0.85rem', fontWeight: 800, marginBottom: '10px' }}>
      Synthèse Globale — Billetage de Toutes les Boulangeries ({today})
    </h2>
    {isLoading ? (
      <div style={{ textAlign: 'center', fontSize: '0.7rem', color: 'hsl(var(--text-muted))', padding: '10px' }}>Chargement des clôtures…</div>
    ) : closures.length === 0 ? (
      <div style={{ textAlign: 'center', fontSize: '0.7rem', color: 'hsl(var(--text-muted))', padding: '10px' }}>Aucune clôture aujourd'hui.</div>
    ) : (
      <table className="premium-table" style={{ fontSize: '0.66rem', minWidth: '720px' }}>
        <thead>
          <tr style={{ textTransform: 'uppercase', fontSize: '0.6rem' }}>
            <th style={{ textAlign: 'left' }}>Boulangerie</th>
            {BILLS.map(b => (
              <th key={b.key} style={{ textAlign: 'right' }}>{b.label}</th>
            ))}
            <th style={{ textAlign: 'right' }}>Total Physique</th>
            <th style={{ textAlign: 'right' }}>Écart</th>
          </tr>
        </thead>
        <tbody>
          {closures.map(c => (
            <tr key={c.id}>
              <td style={{ fontWeight: 700 }}>{c.node_display || c.node}</td>
              {BILLS.map(b => (
                <td key={b.key} style={{ textAlign: 'right' }}>{c[b.key] || 0}</td>
              ))}
              <td style={{ textAlign: 'right', fontWeight: 700 }}>{fmt(c.physical_cash_total)}</td>
              <td style={{ textAlign: 'right', color: parseFloat(c.cash_gap) === 0 ? 'hsl(var(--color-success))' : 'hsl(var(--color-danger))' }}>{fmt(c.cash_gap)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr style={{ fontWeight: 800, borderTop: '2px solid hsl(var(--border-color))' }}>
            <td>TOTAL</td>
            {isComplete ? (
              <>
                {BILLS.map(b => (
                  <td key={b.key} style={{ textAlign: 'right' }}>
                    {closures.reduce((s, c) => s + (c[b.key] || 0), 0)}
                  </td>
                ))}
                <td style={{ textAlign: 'right' }}>{fmt(closures.reduce((s, c) => s + parseFloat(String(c.physical_cash_total || '0')), 0))}</td>
                <td style={{ textAlign: 'right' }}>{fmt(closures.reduce((s, c) => s + parseFloat(String(c.cash_gap || '0')), 0))}</td>
              </>
            ) : (
              <td colSpan={BILLS.length + 2} style={{ textAlign: 'right', fontWeight: 600, color: 'hsl(var(--text-muted))' }}>{progress}</td>
            )}
          </tr>
        </tfoot>
      </table>
    )}
  </div>
);

interface ListProps {
  closures: CashClosure[];
  isLoading: boolean;
  error: string | null;
  canConfirm: boolean;
  canAccessAllNodes: boolean;
  onOpenDetail: (c: CashClosure) => void;
  onEdit: (c: CashClosure) => void;
  onPushToCashbook: (id: string) => void;
}

/** Clôtures du jour — confirmer / infirmer (modale de détail), correction, inscription au livre de caisse. */
export const ClosuresList: React.FC<ListProps> = ({
  closures, isLoading, error, canConfirm, canAccessAllNodes, onOpenDetail, onEdit, onPushToCashbook,
}) => (
  <div className="glass-card" style={{ padding: '14px' }}>
    <h2 style={{ fontSize: '0.85rem', fontWeight: 800, marginBottom: '10px' }}>Clôtures du Jour</h2>
    {isLoading ? (
      <div style={{ textAlign: 'center', fontSize: '0.7rem', color: 'hsl(var(--text-muted))', padding: '10px' }}>Chargement des clôtures…</div>
    ) : error ? (
      <div role="alert" style={{ textAlign: 'center', fontSize: '0.7rem', color: 'hsl(var(--color-danger))', padding: '10px' }}>{error}</div>
    ) : closures.length === 0 ? (
      <div style={{ textAlign: 'center', fontSize: '0.7rem', color: 'hsl(var(--text-muted))', padding: '10px' }}>Aucune clôture créée</div>
    ) : (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
        {closures.map(c => (
          <div
            key={c.id}
            onClick={() => onOpenDetail(c)}
            style={{ padding: '8px 10px', border: `1px solid hsl(var(--${c.is_validated ? 'color-success' : 'border-color'}) / 0.4)`, borderRadius: 'var(--radius-sm)', backgroundColor: c.is_validated ? 'hsl(var(--color-success) / 0.04)' : 'hsl(var(--bg-secondary))', cursor: 'pointer' }}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
              <div style={{ fontSize: '0.7rem' }}>
                <strong>{c.node_display || c.node}</strong>
                <span style={{ marginLeft: '6px', color: 'hsl(var(--text-muted))' }}>{c.date}</span>
              </div>
              <span className={`badge ${c.is_validated ? 'badge-success' : c.is_rejected ? 'badge-danger' : 'badge-warning'}`} style={{ fontSize: '0.52rem' }}>
                {c.is_validated ? 'CONFIRMÉE' : c.is_rejected ? 'INFIRMÉE' : 'EN ATTENTE'}
              </span>
            </div>
            <div style={{ fontSize: '0.65rem', color: 'hsl(var(--text-secondary))', marginBottom: '6px' }}>
              Espèces physiques: <strong>{fmt(c.physical_cash_total)} FC</strong> · Écart: <strong style={{ color: parseFloat(c.cash_gap) === 0 ? 'hsl(var(--color-success))' : 'hsl(var(--color-danger))' }}>{fmt(c.cash_gap)} FC</strong>
            </div>
            {c.is_rejected && !c.is_validated && (
              <div style={{ fontSize: '0.62rem', color: 'hsl(var(--color-danger))', margin: '4px 0', padding: '4px 8px', backgroundColor: 'hsl(var(--color-danger) / 0.08)', borderRadius: 'var(--radius-sm)', border: '1px solid hsl(var(--color-danger) / 0.25)' }}>
                Motif : {c.rejection_reason || 'Non précisé'}
              </div>
            )}
            {canConfirm && !c.is_validated && (
              <div style={{ fontSize: '0.62rem', textAlign: 'center', color: 'hsl(var(--text-muted))' }}>
                Cliquez pour confirmer / infirmer
              </div>
            )}
            <div style={{ display: 'flex', gap: '6px' }} onClick={e => e.stopPropagation()}>
              {c.is_rejected && !c.is_validated && !canAccessAllNodes && (
                <button
                  onClick={() => onEdit(c)}
                  className="btn btn-primary"
                  style={{ flex: 1, padding: '4px', fontSize: '0.65rem', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '4px', backgroundColor: 'hsl(var(--color-warning))', borderColor: 'hsl(var(--color-warning))' }}
                >
                  <FiRefreshCw size={11} /> Corriger et re-soumettre
                </button>
              )}
              {c.is_validated && canConfirm && !c.has_cashbook_entry && (
                <button onClick={() => onPushToCashbook(c.id)} className="btn btn-secondary" style={{ flex: 1, padding: '4px', fontSize: '0.65rem', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '4px' }}>
                  <FiBook /> Inscrire au Livre de Caisse
                </button>
              )}
              {c.has_cashbook_entry && (
                <div style={{ flex: 1, padding: '4px', fontSize: '0.65rem', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '4px', color: 'hsl(var(--color-success))', fontWeight: 600 }}>
                  <FiBook size={11} /> Inscrit au grand livre
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    )}
  </div>
);
