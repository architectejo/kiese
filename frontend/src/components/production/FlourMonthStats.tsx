import React, { useEffect, useState } from 'react';
import { productionApi } from '@/api/services';
import type { FlourMonthStats as FlourMonthStatsData } from '@/api/services';
import { getErrorDetail } from '@/api/errors';

/** Statistiques du mois — Farine (BUG-1110, lot I-3). */
const fmtSacks = (v: string | undefined | null): string =>
  v == null ? '—' : parseFloat(v).toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmtFc = (v: string | undefined | null): string =>
  v == null ? '—' : `${Math.round(parseFloat(v)).toLocaleString('fr-FR')} FC`;

const currentMonth = (): string => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
};

const th: React.CSSProperties = { textAlign: 'right', whiteSpace: 'nowrap' };
const td: React.CSSProperties = { textAlign: 'right', whiteSpace: 'nowrap' };

export const FlourMonthStats: React.FC<{ canPickNode: boolean }> = ({ canPickNode }) => {
  const [month, setMonth] = useState<string>(currentMonth());
  const [node, setNode] = useState<string>('');
  const [data, setData] = useState<FlourMonthStatsData | null>(null);
  const [allBakeries, setAllBakeries] = useState<Array<{ code: string; name: string }>>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!/^\d{4}-\d{2}$/.test(month)) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    productionApi.flourMonthStats
      .get({ month, ...(canPickNode && node ? { node } : {}) })
      .then(res => {
        if (cancelled) return;
        setData(res.data);
        if (!node) setAllBakeries(res.data.bakeries);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setData(null);
        setError(getErrorDetail(err, 'Impossible de charger les statistiques de la farine.'));
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [month, node, canPickNode]);

  const dir = data?.direction_visible === true;
  const bakeries = data?.bakeries ?? [];

  return (
    <div style={{ minWidth: 0 }}>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', alignItems: 'center', marginBottom: '10px' }}>
        <label style={{ fontSize: '0.7rem', fontWeight: 700 }}>
          Mois{' '}
          <input type="month" value={month} onChange={e => setMonth(e.target.value)} className="form-input"
            style={{ height: '28px', fontSize: '0.72rem', padding: '0 6px' }} />
        </label>
        {canPickNode && (
          <label style={{ fontSize: '0.7rem', fontWeight: 700 }}>
            Boulangerie{' '}
            <select value={node} onChange={e => setNode(e.target.value)} className="form-input"
              style={{ height: '28px', fontSize: '0.72rem', padding: '0 6px' }}>
              <option value="">Toutes</option>
              {allBakeries.map(b => <option key={b.code} value={b.code}>{b.code} — {b.name}</option>)}
            </select>
          </label>
        )}
      </div>

      {loading && <div style={{ textAlign: 'center', padding: '12px', color: 'hsl(var(--text-muted))', fontSize: '0.72rem' }}>Chargement...</div>}
      {error && !loading && <div role="alert" style={{ color: 'hsl(var(--color-danger))', fontSize: '0.72rem', padding: '8px 0' }}>{error}</div>}
      {!loading && !error && data && data.rows.length === 0 && (
        <div style={{ textAlign: 'center', padding: '12px', color: 'hsl(var(--text-muted))', fontSize: '0.72rem' }}>Aucune donnée pour ce mois.</div>
      )}

      {!loading && !error && data && data.rows.length > 0 && (
        <>
          <div style={{ overflowX: 'auto', maxWidth: '100%' }}>
            <table className="premium-table" style={{ minWidth: 'max-content' }}>
              <thead>
                <tr style={{ fontSize: '0.6rem', textTransform: 'uppercase' }}>
                  <th>Jour</th>
                  {bakeries.map(b => <th key={b.code} style={th} title={b.name}>{b.code}</th>)}
                  <th style={th}>Total</th>
                  {dir && <><th style={th}>Entrée</th><th style={th}>PU</th><th style={th}>Prix total</th><th style={th}>Solde</th></>}
                </tr>
              </thead>
              <tbody style={{ fontSize: '0.72rem' }}>
                {data.rows.map(r => (
                  <tr key={r.date}>
                    <td style={{ whiteSpace: 'nowrap' }}>
                      {r.date.slice(8, 10)}/{r.date.slice(5, 7)}
                      {r.open_sessions > 0 && <span title="Fournée ouverte : consommation provisoire" style={{ color: 'hsl(var(--color-warning))' }}> *</span>}
                    </td>
                    {bakeries.map(b => <td key={b.code} style={td}>{fmtSacks(r.consumption[b.code])}</td>)}
                    <td style={{ ...td, fontWeight: 800 }}>{fmtSacks(r.total)}</td>
                    {dir && <>
                      <td style={td}>{fmtSacks(r.entry_quantity)}</td>
                      <td style={td}>{fmtFc(r.unit_price)}</td>
                      <td style={td}>{fmtFc(r.total_price)}</td>
                      <td style={{ ...td, fontWeight: 700 }}>{fmtSacks(r.balance)}</td>
                    </>}
                  </tr>
                ))}
              </tbody>
              <tfoot style={{ fontSize: '0.72rem', fontWeight: 800 }}>
                <tr>
                  <td>Total du mois</td>
                  {bakeries.map(b => <td key={b.code} style={td}>{fmtSacks(data.summary.total[b.code])}</td>)}
                  <td style={td}>{fmtSacks(data.summary.total.total)}</td>
                  {dir && <><td style={td}>{fmtSacks(data.purchases?.quantity)}</td><td style={td}>{fmtFc(data.purchases?.average_unit_price)}</td><td style={td}>{fmtFc(data.purchases?.total_price)}</td><td /></>}
                </tr>
                <tr>
                  <td title="Moyenne sur les jours avec consommation">Moy./jour actif</td>
                  {bakeries.map(b => <td key={b.code} style={td}>{fmtSacks(data.summary.average_per_day[b.code])}</td>)}
                  <td style={td}>{fmtSacks(data.summary.average_per_day.total)}</td>
                  {dir && <td colSpan={4} />}
                </tr>
                <tr style={{ color: 'hsl(var(--text-muted))', fontWeight: 600 }}>
                  <td title={`Total ÷ ${data.days_in_month} jours du mois`}>Moy./jour calendaire</td>
                  {bakeries.map(b => <td key={b.code} style={td}>{fmtSacks(data.summary.average_per_calendar_day[b.code])}</td>)}
                  <td style={td}>{fmtSacks(data.summary.average_per_calendar_day.total)}</td>
                  {dir && <td colSpan={4} />}
                </tr>
              </tfoot>
            </table>
          </div>
          <div style={{ marginTop: '8px', fontSize: '0.64rem', color: 'hsl(var(--text-muted))' }}>
            Moyenne principale : sur les jours avec consommation. Quantités en sacs. * fournée encore ouverte.
          </div>
          {dir && (
            <div style={{ marginTop: '8px', display: 'flex', flexWrap: 'wrap', gap: '12px', fontSize: '0.72rem', fontWeight: 700 }}>
              <span>Solde d'ouverture : {fmtSacks(data.opening_balance)} sacs</span>
              <span>Solde de clôture : {fmtSacks(data.closing_balance)} sacs</span>
              <span>Achats : {fmtSacks(data.purchases?.quantity)} sacs / {fmtFc(data.purchases?.total_price)}</span>
            </div>
          )}
        </>
      )}
    </div>
  );
};
