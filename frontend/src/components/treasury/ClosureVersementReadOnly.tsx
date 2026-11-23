import React, { useCallback, useEffect, useState } from 'react';
import { FiDollarSign, FiRefreshCw } from 'react-icons/fi';
import { treasuryApi, VersementStatus, VersementsResponse } from '@/api/services';
import { getErrorDetail } from '@/api/errors';
import { BILLS, fmt } from '@/components/treasury/treasuryShared';

interface Props {
  /** Identifiant (pk) de la boulangerie filtrée ; '' = toutes. */
  nodeFilter: string;
  nodeLabel: string | null;
  /** Jour calendaire courant (valeur par défaut du filtre de date). */
  today: string;
  /** Change quand une clôture est créée/confirmée/infirmée : recharge le tableau. */
  refreshKey: string;
  style?: React.CSSProperties;
}

const STATUS_LABEL: Record<VersementStatus, { label: string; badge: string }> = {
  NON_VERSE: { label: 'NON VERSÉ', badge: 'badge-danger' },
  EN_ATTENTE: { label: 'EN ATTENTE', badge: 'badge-warning' },
  VALIDE: { label: 'CONFIRMÉ', badge: 'badge-success' },
  INFIRME: { label: 'INFIRMÉ', badge: 'badge-danger' },
};

const fc = (v: string | number | undefined) => `${fmt(v)} FC`;

/**
 * Section « Versement » en lecture seule pour la direction centrale (remarque.md) :
 * une ligne par boulangerie (versé / non versé, billetage, écart) avec totaux, filtrable
 * par date et par boulangerie (filtre de succursale de l'écran). Source : BUG-381
 * (`GET /api/treasury/closures/versements/`). Aucune saisie : le versement reste celui du gérant.
 */
export const ClosureVersementReadOnly: React.FC<Props> = ({ nodeFilter, nodeLabel, today, refreshKey, style }) => {
  const [date, setDate] = useState(today);
  const [data, setData] = useState<VersementsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await treasuryApi.closures.versements({
        date,
        ...(nodeFilter ? { node: nodeFilter } : {}),
      });
      setData(res.data);
    } catch (err: unknown) {
      setError(getErrorDetail(err, 'Impossible de charger les versements.'));
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [date, nodeFilter]);

  useEffect(() => { void load(); }, [load, refreshKey]);

  const rows = data?.results ?? [];
  const totals = data?.totals;
  const gapColor = (v: string) => (parseFloat(v || '0') === 0 ? 'hsl(var(--color-success))' : 'hsl(var(--color-danger))');

  return (
    <div className="glass-card" style={{ padding: '16px', minWidth: 0, ...style }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px', marginBottom: '4px' }}>
        <h2 style={{ fontSize: '0.9rem', fontWeight: 800, display: 'flex', alignItems: 'center', gap: '6px' }}>
          <FiDollarSign style={{ color: 'hsl(var(--accent-color))' }} />
          Versement
          <span className="badge badge-info" style={{ fontSize: '0.56rem' }}>Lecture seule</span>
        </h2>
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
          <input
            type="date"
            max={today}
            value={date}
            onChange={e => setDate(e.target.value || today)}
            aria-label="Date du versement"
            className="form-input"
            style={{ height: '28px', fontSize: '0.68rem', padding: '0 6px', width: '132px' }}
          />
          <button onClick={() => void load()} disabled={loading} className="btn btn-secondary" style={{ padding: '4px 8px', fontSize: '0.65rem', display: 'flex', alignItems: 'center', gap: '4px' }}>
            <FiRefreshCw style={{ animation: loading ? 'spin 1s linear infinite' : 'none' }} /> Actualiser
          </button>
        </div>
      </div>
      <p style={{ fontSize: '0.68rem', color: 'hsl(var(--text-secondary))', marginBottom: '12px' }}>
        Billetage physique déclaré par le gérant de chaque boulangerie{nodeLabel ? ` — ${nodeLabel}` : ' (choisissez une succursale pour filtrer)'}.
      </p>

      {error && (
        <div role="alert" style={{ fontSize: '0.7rem', color: 'hsl(var(--color-danger))', backgroundColor: 'hsl(var(--color-danger) / 0.08)', padding: '6px 10px', borderRadius: 'var(--radius-sm)', marginBottom: '8px' }}>
          {error}
        </div>
      )}

      {loading && !data ? (
        <div style={{ textAlign: 'center', fontSize: '0.72rem', color: 'hsl(var(--text-muted))', padding: '10px' }}>Chargement des versements…</div>
      ) : !error && rows.length === 0 ? (
        <div style={{ textAlign: 'center', fontSize: '0.72rem', color: 'hsl(var(--text-muted))', padding: '10px' }}>
          Aucune boulangerie à afficher pour le {new Date(date).toLocaleDateString('fr-FR')}.
        </div>
      ) : rows.length > 0 && (
        <>
          <div style={{ overflowX: 'auto' }}>
            <table className="premium-table" style={{ fontSize: '0.68rem', minWidth: '640px' }}>
              <thead>
                <tr style={{ textTransform: 'uppercase', fontSize: '0.6rem' }}>
                  <th>Boulangerie</th>
                  <th style={{ textAlign: 'center' }}>Statut</th>
                  <th style={{ textAlign: 'right' }}>Entrées cash</th>
                  <th style={{ textAlign: 'right' }}>Dépenses</th>
                  <th style={{ textAlign: 'right' }}>Caisse nette</th>
                  <th style={{ textAlign: 'right' }}>Espèces physiques</th>
                  <th style={{ textAlign: 'right' }}>Écart</th>
                </tr>
              </thead>
              <tbody>
                {rows.map(r => {
                  const st = STATUS_LABEL[r.status];
                  const versed = r.status !== 'NON_VERSE';
                  return (
                    <tr key={`${r.node}`}>
                      <td style={{ fontWeight: 700 }}>{r.node_display || r.node_code}</td>
                      <td style={{ textAlign: 'center' }}>
                        <span className={`badge ${st.badge}`} style={{ fontSize: '0.52rem' }}>{st.label}</span>
                      </td>
                      <td style={{ textAlign: 'right' }}>{versed ? fc(r.total_entries) : '—'}</td>
                      <td style={{ textAlign: 'right' }}>{versed ? fc(r.total_expenses) : '—'}</td>
                      <td style={{ textAlign: 'right' }}>{versed ? fc(r.net_cash) : '—'}</td>
                      <td style={{ textAlign: 'right', fontWeight: 700 }}>{versed ? fc(r.physical_cash_total) : '—'}</td>
                      <td style={{ textAlign: 'right', fontWeight: 700, color: versed ? gapColor(r.cash_gap) : undefined }}>
                        {versed ? `${parseFloat(r.cash_gap) > 0 ? '+' : ''}${fc(r.cash_gap)}` : '—'}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
              {totals && (
                <tfoot>
                  <tr style={{ fontWeight: 800, borderTop: '2px solid hsl(var(--border-color))' }}>
                    <td>TOTAL ({totals.versed_count}/{data?.count ?? rows.length} versé{totals.versed_count > 1 ? 's' : ''})</td>
                    <td />
                    <td style={{ textAlign: 'right' }}>{fc(totals.total_entries)}</td>
                    <td style={{ textAlign: 'right' }}>{fc(totals.total_expenses)}</td>
                    <td style={{ textAlign: 'right' }}>{fc(totals.net_cash)}</td>
                    <td style={{ textAlign: 'right' }}>{fc(totals.physical_cash_total)}</td>
                    <td style={{ textAlign: 'right', color: gapColor(totals.cash_gap) }}>{`${parseFloat(totals.cash_gap) > 0 ? '+' : ''}${fc(totals.cash_gap)}`}</td>
                  </tr>
                </tfoot>
              )}
            </table>
          </div>
          {totals && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginTop: '10px', fontSize: '0.66rem' }}>
              <strong style={{ color: 'hsl(var(--text-secondary))' }}>Billets versés :</strong>
              {BILLS.map(b => (
                <span key={b.key} style={{ padding: '2px 6px', backgroundColor: 'hsl(var(--bg-tertiary))', borderRadius: 'var(--radius-sm)', whiteSpace: 'nowrap' }}>
                  {b.label} × {(totals.bills[b.key] ?? 0).toLocaleString('fr-FR')}
                </span>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
};
