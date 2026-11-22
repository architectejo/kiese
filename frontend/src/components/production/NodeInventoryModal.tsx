import React, { useEffect, useState } from 'react';
import { Modal } from '@/components/shared/Modal';
import { productionApi } from '@/api/services';
import type { NodeInventoryDetail } from '@/api/consumablesDirection';
import { getErrorDetail } from '@/api/errors';
import { formatGap, formatIsoDate, formatQty, unitLabel } from './consumableFormat';
import { displayStock } from './productionHelpers';

interface Props {
  /** Id ou code de la boulangerie ; null = modale fermée. */
  nodeRef: string | null;
  nodeLabel: string;
  onClose: () => void;
}

// BUG-387 : détail du dernier « Inventaire Physique » d'une boulangerie (direction, lecture seule).
export const NodeInventoryModal: React.FC<Props> = ({ nodeRef, nodeLabel, onClose }) => {
  const [detail, setDetail] = useState<NodeInventoryDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [date, setDate] = useState<string | undefined>(undefined);

  useEffect(() => { setDate(undefined); setDetail(null); setError(null); }, [nodeRef]);

  useEffect(() => {
    if (!nodeRef) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    productionApi.inventories.forNode(nodeRef, date)
      .then(r => { if (!cancelled) setDetail(r.data); })
      .catch(err => { if (!cancelled) setError(getErrorDetail(err, "Impossible de charger l'inventaire physique.")); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [nodeRef, date]);

  const inv = detail?.inventory ?? null;

  return (
    <Modal isOpen={nodeRef !== null} onClose={onClose} title={`Inventaire Physique — ${nodeLabel}`} maxWidth="640px">
      <div style={{ padding: '4px', fontSize: '0.78rem' }}>
        {loading && <div style={{ textAlign: 'center', padding: '12px', color: 'hsl(var(--text-muted))' }}>Chargement...</div>}
        {error && <div role="alert" style={{ color: 'hsl(var(--color-danger))', marginBottom: '8px' }}>{error}</div>}
        {!loading && !error && detail && !inv && (
          <div style={{ textAlign: 'center', padding: '12px', color: 'hsl(var(--text-muted))' }}>
            Aucun inventaire physique saisi par cette boulangerie.
          </div>
        )}
        {inv && (
          <>
            <div style={{ marginBottom: '8px', color: 'hsl(var(--text-secondary))' }}>
              Inventaire du <strong>{formatIsoDate(inv.inventory_date)}</strong>
              {inv.recorded_by_display ? <> — saisi par {inv.recorded_by_display}</> : null}
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table className="premium-table" style={{ width: '100%' }}>
                <thead>
                  <tr style={{ fontSize: '0.62rem', textTransform: 'uppercase' }}>
                    <th>Consommable</th>
                    <th style={{ textAlign: 'right' }}>Théorique</th>
                    <th style={{ textAlign: 'right' }}>Physique</th>
                    <th style={{ textAlign: 'right' }}>Écart</th>
                  </tr>
                </thead>
                <tbody>
                  {(inv.lines ?? []).map(l => {
                    const gap = Number(l.gap);
                    return (
                      <tr key={l.id}>
                        <td style={{ fontWeight: 700 }}>
                          {displayStock(l.consumable_type_display)} <span style={{ color: 'hsl(var(--text-muted))', fontWeight: 400 }}>({unitLabel(l.unit)})</span>
                          {l.notes && <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-muted))', fontWeight: 400 }}>{l.notes}</div>}
                        </td>
                        <td style={{ textAlign: 'right' }}>{formatQty(l.system_quantity)}</td>
                        <td style={{ textAlign: 'right', fontWeight: 700 }}>{formatQty(l.physical_quantity)}</td>
                        <td style={{ textAlign: 'right', fontWeight: 800, color: gap < 0 ? 'hsl(var(--color-danger))' : gap > 0 ? 'hsl(var(--color-warning))' : 'hsl(var(--color-success))' }}>
                          {formatGap(l.gap)}
                        </td>
                      </tr>
                    );
                  })}
                  {(inv.lines ?? []).length === 0 && (
                    <tr><td colSpan={4} style={{ textAlign: 'center', color: 'hsl(var(--text-muted))' }}>Aucune ligne</td></tr>
                  )}
                </tbody>
              </table>
            </div>
            <div style={{ marginTop: '10px' }}>
              <div style={{ fontSize: '0.65rem', fontWeight: 800, textTransform: 'uppercase', color: 'hsl(var(--text-secondary))' }}>Commentaire du gérant</div>
              <div style={{ whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
                {inv.comment?.trim() ? inv.comment : <span style={{ color: 'hsl(var(--text-muted))' }}>Aucun commentaire.</span>}
              </div>
            </div>
          </>
        )}
        {detail && detail.history_dates.length > 0 && (
          <div style={{ marginTop: '12px', borderTop: '1px solid hsl(var(--border-color))', paddingTop: '8px' }}>
            <div style={{ fontSize: '0.65rem', fontWeight: 800, textTransform: 'uppercase', color: 'hsl(var(--text-secondary))', marginBottom: '6px' }}>Historique</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
              {detail.history_dates.map(d => (
                <button
                  key={d}
                  type="button"
                  onClick={() => setDate(d)}
                  className={`btn ${inv?.inventory_date === d ? 'btn-primary' : 'btn-secondary'}`}
                  style={{ padding: '6px 10px', fontSize: '0.7rem' }}
                >
                  {formatIsoDate(d)}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </Modal>
  );
};
