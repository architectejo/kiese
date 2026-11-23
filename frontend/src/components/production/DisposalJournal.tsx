import React, { useEffect, useState } from 'react';
import { productionApi } from '@/api/services';
import type { BreadDisposal } from '@/api/services';
import { getErrorDetail } from '@/api/errors';
import { DISPOSAL_COLORS } from './productionHelpers';

interface DisposalJournalProps {
  /** Liste par défaut (jour de travail) fournie par la page. */
  defaultDisposals: BreadDisposal[];
  workDate: string;
  effectiveNode: string;
}

/** Journal des Sorties Non Valorisées avec sélecteur de date (BUG-674). */
export const DisposalJournal: React.FC<DisposalJournalProps> = ({ defaultDisposals, workDate, effectiveNode }) => {
  const [date, setDate] = useState('');
  const [rows, setRows] = useState<BreadDisposal[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!date) { setRows(null); setError(null); return; }
    let cancelled = false;
    setLoading(true);
    setError(null);
    const params: Record<string, string> = { date };
    if (effectiveNode) params.node = effectiveNode;
    productionApi.disposals.list(params)
      .then(list => { if (!cancelled) setRows(list.data); })
      .catch((err: unknown) => { if (!cancelled) setError(getErrorDetail(err, 'Chargement du journal impossible.')); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [date, effectiveNode]);

  const shown = rows ?? defaultDisposals;

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px', marginBottom: '8px' }}>
        <h3 style={{ fontSize: '0.75rem', fontWeight: 700, color: 'hsl(var(--text-secondary))' }}>Journal des Sorties Non Valorisées</h3>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <input
            type="date"
            value={date}
            max={workDate}
            onChange={e => setDate(e.target.value)}
            className="form-input"
            aria-label="Date du journal"
            style={{ height: '30px', fontSize: '0.72rem', padding: '0 6px' }}
          />
          {date && (
            <button type="button" className="btn btn-secondary" style={{ padding: '4px 8px', fontSize: '0.68rem' }} onClick={() => setDate('')}>
              Récentes
            </button>
          )}
        </div>
      </div>
      {loading ? (
        <div style={{ textAlign: 'center', padding: '20px', color: 'hsl(var(--text-muted))', fontSize: '0.7rem' }}>Chargement…</div>
      ) : error ? (
        <div style={{ fontSize: '0.7rem', color: 'hsl(var(--color-danger))', padding: '8px' }}>{error}</div>
      ) : shown.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '20px', color: 'hsl(var(--text-muted))', fontSize: '0.7rem' }}>
          {date ? `Aucune sortie enregistrée le ${new Date(date).toLocaleDateString('fr-FR')}.` : 'Aucune sortie enregistrée.'}
        </div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table className="premium-table">
            <thead>
              <tr style={{ fontSize: '0.6rem', textTransform: 'uppercase' }}>
                <th>Type</th><th>Catégorie</th><th style={{ textAlign: 'right' }}>Qté</th><th style={{ textAlign: 'right' }}>Valeur FC</th><th>Date</th>
              </tr>
            </thead>
            <tbody style={{ fontSize: '0.68rem' }}>
              {shown.map(d => (
                <tr key={d.id}>
                  <td>
                    <span style={{ fontSize: '0.58rem', fontWeight: 700, color: `hsl(${DISPOSAL_COLORS[d.disposal_type]})` }}>
                      {d.disposal_type.replace('_', ' ')}
                    </span>
                  </td>
                  <td style={{ color: 'hsl(var(--text-secondary))' }}>{d.bread_price_display || '—'}</td>
                  <td style={{ textAlign: 'right', fontWeight: 800 }}>{d.quantity}</td>
                  <td style={{ textAlign: 'right', color: parseFloat(d.total_value) > 0 ? 'hsl(var(--color-success))' : 'hsl(var(--text-muted))' }}>
                    {parseFloat(d.total_value) > 0 ? `${parseFloat(d.total_value).toLocaleString('fr-FR')}` : '—'}
                  </td>
                  <td style={{ color: 'hsl(var(--text-muted))', fontSize: '0.6rem' }}>{d.created_at?.split('T')[0]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
