import React from 'react';
import { FiRefreshCw } from 'react-icons/fi';
import type { FlourHistoryEntry } from '@/api/services';
import { productionApi } from '@/api/services';

export interface FlourHistoryCardProps {
  viewNode: string;
  flourHistory: FlourHistoryEntry[];
  setFlourHistory: React.Dispatch<React.SetStateAction<FlourHistoryEntry[]>>;
  flourLoading: boolean;
  setFlourLoading: React.Dispatch<React.SetStateAction<boolean>>;
}

export const FlourHistoryCard: React.FC<FlourHistoryCardProps> = ({ viewNode, flourHistory, setFlourHistory, flourLoading, setFlourLoading }) => {
  return (
        <div className="glass-card" style={{ padding: '16px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px', flexWrap: 'wrap', gap: '8px' }}>
            <h2 style={{ fontSize: '0.88rem', fontWeight: 800, display: 'flex', alignItems: 'center', gap: '6px' }}>
              🌾 §3.2b — Historique Achats Farine
            </h2>
            <button
              onClick={() => {
                setFlourLoading(true);
                const nf = viewNode || undefined;
                productionApi.movements.flourHistory(nf ? { node: nf } : undefined)
                  .then(r => setFlourHistory(Array.isArray(r.data) ? r.data : []))
                  .catch(() => {})
                  .finally(() => setFlourLoading(false));
              }}
              className="btn btn-secondary"
              style={{ padding: '4px 10px', fontSize: '0.68rem', display: 'flex', alignItems: 'center', gap: '4px' }}
            >
              <FiRefreshCw size={11} /> Actualiser
            </button>
          </div>
          {flourLoading ? (
            <p style={{ textAlign: 'center', padding: '16px', color: 'hsl(var(--text-secondary))', fontSize: '0.8rem' }}>Chargement...</p>
          ) : flourHistory.length === 0 ? (
            <p style={{ textAlign: 'center', padding: '16px', color: 'hsl(var(--text-secondary))', fontSize: '0.8rem' }}>Aucun achat de farine enregistré.</p>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table className="premium-table">
                <thead>
                  <tr style={{ fontSize: '0.62rem', textTransform: 'uppercase' }}>
                    <th style={{ width: '90px' }}>Date</th>
                    <th style={{ width: '60px' }}>Site</th>
                    <th style={{ width: '90px' }}>Fournisseur</th>
                    <th style={{ textAlign: 'right', width: '80px' }}>Sacs</th>
                    <th style={{ textAlign: 'right', width: '110px' }}>PU (FC/sac)</th>
                    <th style={{ textAlign: 'right', width: '120px' }}>Total FC</th>
                    <th>Description</th>
                  </tr>
                </thead>
                <tbody>
                  {flourHistory.map(h => (
                    <tr key={h.id} style={{ fontSize: '0.72rem' }}>
                      <td>{new Date(h.date).toLocaleDateString('fr-FR', { day: '2-digit', month: 'short', year: '2-digit' })}</td>
                      <td><span className="badge badge-info" style={{ fontSize: '0.55rem' }}>{h.node}</span></td>
                      <td style={{ fontWeight: 700 }}>
                        {h.supplier ? <span style={{ color: 'hsl(var(--accent-color))' }}>{h.supplier}</span> : <span style={{ color: 'hsl(var(--text-muted))', fontStyle: 'italic' }}>—</span>}
                      </td>
                      <td style={{ textAlign: 'right', fontWeight: 700 }}>{parseFloat(h.quantity)}</td>
                      <td style={{ textAlign: 'right' }}>{parseFloat(h.unit_price) > 0 ? parseFloat(h.unit_price).toLocaleString('fr-FR') : '—'}</td>
                      <td style={{ textAlign: 'right', fontWeight: 800, color: 'hsl(var(--color-success))' }}>
                        {parseFloat(h.total_cost) > 0 ? parseFloat(h.total_cost).toLocaleString('fr-FR') : '—'}
                      </td>
                      <td style={{ color: 'hsl(var(--text-secondary))' }}>{h.description || '—'}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr style={{ fontSize: '0.68rem', fontWeight: 800, backgroundColor: 'hsl(var(--bg-tertiary))' }}>
                    <td colSpan={3} style={{ padding: '8px 10px', textAlign: 'right', color: 'hsl(var(--text-secondary))' }}>TOTAUX</td>
                    <td style={{ textAlign: 'right', padding: '8px 10px' }}>
                      {flourHistory.reduce((a, h) => a + parseFloat(h.quantity), 0)} sacs
                    </td>
                    <td />
                    <td style={{ textAlign: 'right', padding: '8px 10px', color: 'hsl(var(--color-success))' }}>
                      {flourHistory.reduce((a, h) => a + parseFloat(h.total_cost || '0'), 0).toLocaleString('fr-FR')} FC
                    </td>
                    <td />
                  </tr>
                </tfoot>
              </table>
            </div>
          )}
        </div>
  );
};
