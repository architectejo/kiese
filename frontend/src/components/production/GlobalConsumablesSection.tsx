import React, { useCallback, useEffect, useState } from 'react';
import { productionApi } from '@/api/services';
import type { GlobalConsumables } from '@/api/consumablesDirection';
import { getErrorDetail } from '@/api/errors';
import { formatIsoDate, formatQty, parseDecimalInput, unitLabel } from './consumableFormat';
import { STOCK_ICONS, displayStock } from './productionHelpers';
import { NodeInventoryModal } from './NodeInventoryModal';

interface Props {
  role: 'ADMIN' | 'DIRECTION' | 'COMPTABLE';
}

const cellNum: React.CSSProperties = { textAlign: 'right', whiteSpace: 'nowrap' };

// BUG-387 : vue globale des consommables pour la direction (boulangeries x consommables,
// stock direction, totaux) + envoi du stock direction vers les boulangeries (ADMIN/DIRECTION).
export const GlobalConsumablesSection: React.FC<Props> = ({ role }) => {
  const canDispatch = role === 'ADMIN' || role === 'DIRECTION';
  const [data, setData] = useState<GlobalConsumables | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [dType, setDType] = useState('');
  const [dQty, setDQty] = useState<Record<number, string>>({});
  const [dNote, setDNote] = useState('');
  const [dError, setDError] = useState<string | null>(null);
  const [dOk, setDOk] = useState<string | null>(null);
  const [dSending, setDSending] = useState(false);

  const [openNode, setOpenNode] = useState<{ ref: string; label: string } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await productionApi.consumablesGlobal.get();
      setData(r.data);
      setDType(prev => prev || r.data.types[0]?.code || '');
    } catch (err) {
      setError(getErrorDetail(err, 'Impossible de charger la vue globale des consommables.'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const types = data?.types ?? [];
  const selType = types.find(t => t.code === dType);

  const submitDispatch = async (e: React.FormEvent) => {
    e.preventDefault();
    setDError(null);
    setDOk(null);
    if (!selType) { setDError('Choisissez un consommable.'); return; }
    const allocations: Array<{ node: number; quantity: string }> = [];
    for (const n of data?.nodes ?? []) {
      const raw = (dQty[n.node] ?? '').trim();
      if (raw === '') continue;
      const q = parseDecimalInput(raw);
      if (q === null || Number(q) <= 0) {
        setDError(`Quantité invalide pour ${n.code} : nombre positif, 3 décimales au maximum.`);
        return;
      }
      allocations.push({ node: n.node, quantity: q });
    }
    if (allocations.length === 0) { setDError('Saisissez une quantité pour au moins une boulangerie.'); return; }
    setDSending(true);
    try {
      const r = await productionApi.consumablesGlobal.dispatch({
        consumable_type: selType.code,
        note: dNote.trim() || undefined,
        allocations,
      });
      setDOk(`${formatQty(r.data.total_sent)} ${unitLabel(r.data.unit)} envoyé(s). Reste au stock direction : ${formatQty(r.data.direction_remaining)} ${unitLabel(r.data.unit)}.`);
      setDQty({});
      setDNote('');
      await load();
    } catch (err) {
      setDError(getErrorDetail(err, "Impossible d'envoyer le stock."));
    } finally {
      setDSending(false);
    }
  };

  return (
    <div className="glass-card" style={{ padding: '14px', marginBottom: '14px', minWidth: 0 }} data-testid="global-consumables">
      <h2 style={{ fontSize: '0.88rem', fontWeight: 800, marginBottom: '10px' }}>
        Vue globale des consommables — toutes boulangeries
        {role === 'COMPTABLE' && <span className="badge badge-info" style={{ fontSize: '0.6rem', marginLeft: '8px' }}>Lecture seule</span>}
      </h2>

      {loading && <div style={{ textAlign: 'center', padding: '12px', color: 'hsl(var(--text-muted))', fontSize: '0.72rem' }}>Chargement...</div>}
      {error && (
        <div role="alert" style={{ color: 'hsl(var(--color-danger))', fontSize: '0.75rem' }}>
          {error} <button type="button" className="btn btn-secondary" style={{ padding: '4px 10px', fontSize: '0.7rem' }} onClick={() => void load()}>Réessayer</button>
        </div>
      )}

      {data && (
        <>
          <div style={{ overflowX: 'auto' }}>
            <table className="premium-table" style={{ width: '100%' }}>
              <thead>
                <tr style={{ fontSize: '0.6rem', textTransform: 'uppercase' }}>
                  <th>Boulangerie</th>
                  {types.map(t => (
                    <th key={t.code} style={cellNum}>{STOCK_ICONS[t.code] || ''} {displayStock(t.label)} ({unitLabel(t.unit)})</th>
                  ))}
                  <th>Inventaire</th>
                </tr>
              </thead>
              <tbody style={{ fontSize: '0.72rem' }}>
                <tr style={{ background: 'hsl(var(--accent-color) / 0.08)' }} data-testid="global-row-direction">
                  <td style={{ fontWeight: 800 }}>Stock direction ({data.direction.code})</td>
                  {types.map(t => <td key={t.code} style={{ ...cellNum, fontWeight: 800 }}>{formatQty(data.direction.stocks[t.code])}</td>)}
                  <td style={{ color: 'hsl(var(--text-muted))' }}>—</td>
                </tr>
                {data.nodes.map(n => (
                  <tr key={n.node} data-testid={`global-row-${n.code}`}>
                    <td>
                      <button
                        type="button"
                        onClick={() => setOpenNode({ ref: String(n.node), label: `${n.code} ${n.name}`.trim() })}
                        style={{ background: 'none', border: 'none', padding: '6px 0', color: 'hsl(var(--accent-color))', fontWeight: 800, cursor: 'pointer', textAlign: 'left', fontSize: '0.72rem', minHeight: '32px' }}
                        title="Voir le dernier inventaire physique"
                      >
                        {n.code} <span style={{ fontWeight: 400, color: 'hsl(var(--text-secondary))' }}>{n.name}</span>
                      </button>
                    </td>
                    {types.map(t => <td key={t.code} style={cellNum}>{formatQty(n.stocks[t.code])}</td>)}
                    <td style={{ whiteSpace: 'nowrap', fontSize: '0.66rem' }}>
                      {n.last_inventory
                        ? <>{formatIsoDate(n.last_inventory.date)}{n.last_inventory.has_comment && <span className="badge badge-info" style={{ fontSize: '0.5rem', marginLeft: '4px' }}>commentaire</span>}</>
                        : <span style={{ color: 'hsl(var(--text-muted))' }}>Aucun</span>}
                    </td>
                  </tr>
                ))}
                {data.nodes.length === 0 && <tr><td colSpan={types.length + 2} style={{ textAlign: 'center', padding: '12px', color: 'hsl(var(--text-muted))' }}>Aucune boulangerie</td></tr>}
                <tr style={{ fontWeight: 800, borderTop: '2px solid hsl(var(--border-color))' }} data-testid="global-row-totals">
                  <td>Total boulangeries</td>
                  {types.map(t => <td key={t.code} style={cellNum}>{formatQty(data.totals_bakeries[t.code])}</td>)}
                  <td />
                </tr>
                <tr style={{ fontWeight: 800 }}>
                  <td>Total groupe (avec direction)</td>
                  {types.map(t => <td key={t.code} style={cellNum}>{formatQty(data.totals_group[t.code])}</td>)}
                  <td />
                </tr>
              </tbody>
            </table>
          </div>
          <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))', marginTop: '4px' }}>
            Cliquez sur une boulangerie pour voir son dernier Inventaire Physique.
          </div>

          {canDispatch && (
            <form onSubmit={submitDispatch} style={{ marginTop: '14px', borderTop: '1px solid hsl(var(--border-color))', paddingTop: '12px' }} data-testid="dispatch-form">
              <div style={{ fontSize: '0.7rem', fontWeight: 800, textTransform: 'uppercase', color: 'hsl(var(--text-secondary))', marginBottom: '8px' }}>
                Orienter / envoyer du stock direction vers les boulangeries
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', alignItems: 'center', marginBottom: '8px' }}>
                <select value={dType} onChange={e => setDType(e.target.value)} className="form-input" aria-label="Consommable à envoyer" style={{ height: '36px', fontSize: '0.8rem', minWidth: 0, flex: '1 1 160px' }}>
                  {types.map(t => <option key={t.code} value={t.code}>{displayStock(t.label)} ({unitLabel(t.unit)})</option>)}
                </select>
                {selType && (
                  <span style={{ fontSize: '0.72rem', color: 'hsl(var(--text-secondary))' }}>
                    Disponible : <strong>{formatQty(data.direction.stocks[selType.code])} {unitLabel(selType.unit)}</strong>
                  </span>
                )}
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: '6px', marginBottom: '8px' }}>
                {data.nodes.map(n => (
                  <label key={n.node} style={{ display: 'flex', flexDirection: 'column', gap: '2px', fontSize: '0.66rem', fontWeight: 700 }}>
                    {n.code} {n.name}
                    <input
                      type="text" inputMode="decimal"
                      value={dQty[n.node] ?? ''}
                      onChange={e => setDQty(prev => ({ ...prev, [n.node]: e.target.value }))}
                      placeholder={selType ? unitLabel(selType.unit) : ''}
                      aria-label={`Quantité pour ${n.code}`}
                      className="form-input"
                      style={{ height: '36px', fontSize: '0.8rem', padding: '0 8px', width: '100%', boxSizing: 'border-box' }}
                    />
                  </label>
                ))}
              </div>
              <input type="text" value={dNote} onChange={e => setDNote(e.target.value)} placeholder="Note (optionnelle)" className="form-input" style={{ height: '36px', fontSize: '0.78rem', padding: '0 10px', width: '100%', boxSizing: 'border-box', marginBottom: '8px' }} />
              {dError && <div role="alert" style={{ color: 'hsl(var(--color-danger))', fontSize: '0.74rem', marginBottom: '6px' }}>{dError}</div>}
              {dOk && <div role="status" style={{ color: 'hsl(var(--color-success))', fontSize: '0.74rem', marginBottom: '6px' }}>{dOk}</div>}
              <button type="submit" disabled={dSending} className="btn btn-primary" style={{ padding: '10px 14px', fontSize: '0.8rem', width: '100%', opacity: dSending ? 0.6 : 1 }}>
                {dSending ? 'Envoi...' : 'Envoyer aux boulangeries'}
              </button>
            </form>
          )}
        </>
      )}

      <NodeInventoryModal nodeRef={openNode?.ref ?? null} nodeLabel={openNode?.label ?? ''} onClose={() => setOpenNode(null)} />
    </div>
  );
};
