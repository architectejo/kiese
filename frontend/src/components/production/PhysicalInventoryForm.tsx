import React, { useCallback, useEffect, useState } from 'react';
import { productionApi } from '@/api/services';
import type { ConsumableStock } from '@/api/services';
import type { ConsumableInventory } from '@/api/consumablesDirection';
import { getErrorDetail } from '@/api/errors';
import { formatGap, formatIsoDate, formatQty, parseDecimalInput, unitLabel } from './consumableFormat';
import { STOCK_ICONS, displayStock } from './productionHelpers';

interface Props {
  stocks: ConsumableStock[];
  /** Appelé après une saisie réussie (rechargement éventuel des stocks). */
  onSaved?: () => void;
}

// BUG-387 : « Inventaire Physique » du gérant — une seule saisie par jour ; le commentaire
// reste modifiable ensuite (PATCH). Les règles (1 saisie/jour, quantités >= 0) sont appliquées par le serveur.
export const PhysicalInventoryForm: React.FC<Props> = ({ stocks, onSaved }) => {
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [inventory, setInventory] = useState<ConsumableInventory | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [comment, setComment] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const [editComment, setEditComment] = useState('');
  const [commentMsg, setCommentMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [commentSaving, setCommentSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const r = await productionApi.inventories.today();
      setInventory(r.data.done ? r.data.inventory : null);
      setEditComment(r.data.inventory?.comment ?? '');
    } catch (err) {
      setLoadError(getErrorDetail(err, "Impossible de charger l'inventaire du jour."));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void load(); }, [load]);

  const done = inventory !== null;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    const lines: Array<{ consumable_type: string; physical_quantity: string }> = [];
    for (const st of stocks) {
      const raw = (values[st.consumable_type] ?? '').trim();
      if (raw === '') {
        setError(`Saisissez la quantité physique de « ${displayStock(st.consumable_type_display || st.consumable_type)} » (0 si vide).`);
        return;
      }
      const q = parseDecimalInput(raw);
      if (q === null) {
        setError(`Quantité invalide pour « ${displayStock(st.consumable_type_display || st.consumable_type)} » : nombre positif, 3 décimales au maximum.`);
        return;
      }
      lines.push({ consumable_type: st.consumable_type, physical_quantity: q });
    }
    if (lines.length === 0) { setError('Aucun consommable à compter.'); return; }
    setSaving(true);
    try {
      const r = await productionApi.inventories.create({ comment: comment.trim() || undefined, lines });
      setInventory(r.data);
      setEditComment(r.data.comment ?? '');
      onSaved?.();
    } catch (err) {
      setError(getErrorDetail(err, "Impossible d'enregistrer l'inventaire physique."));
      // 400 « déjà saisi » : resynchroniser l'état du jour.
      void load();
    } finally {
      setSaving(false);
    }
  };

  const saveComment = async () => {
    if (!inventory) return;
    setCommentMsg(null);
    setCommentSaving(true);
    try {
      const r = await productionApi.inventories.updateComment(inventory.id, editComment.trim());
      setInventory(prev => (prev ? { ...prev, comment: r.data.comment, updated_at: r.data.updated_at } : prev));
      setCommentMsg({ ok: true, text: 'Commentaire enregistré.' });
    } catch (err) {
      setCommentMsg({ ok: false, text: getErrorDetail(err, "Impossible d'enregistrer le commentaire.") });
    } finally {
      setCommentSaving(false);
    }
  };

  return (
    <div style={{ marginTop: '14px', borderTop: '1px solid hsl(var(--border-color))', paddingTop: '12px', minWidth: 0 }} data-testid="physical-inventory">
      <div style={{ fontSize: '0.7rem', fontWeight: 800, color: 'hsl(var(--text-secondary))', textTransform: 'uppercase', marginBottom: '8px' }}>
        Inventaire Physique
      </div>

      {loading && <div style={{ fontSize: '0.72rem', color: 'hsl(var(--text-muted))' }}>Chargement...</div>}
      {loadError && (
        <div role="alert" style={{ color: 'hsl(var(--color-danger))', fontSize: '0.72rem' }}>
          {loadError} <button type="button" className="btn btn-secondary" style={{ padding: '4px 10px', fontSize: '0.7rem' }} onClick={() => void load()}>Réessayer</button>
        </div>
      )}

      {!loading && !loadError && done && inventory && (
        <div data-testid="inventory-done">
          <div role="status" style={{ background: 'hsl(var(--color-success) / 0.08)', border: '1px solid hsl(var(--color-success) / 0.3)', borderRadius: 'var(--radius-sm)', padding: '8px 10px', fontSize: '0.72rem', marginBottom: '8px' }}>
            Inventaire physique déjà saisi aujourd'hui ({formatIsoDate(inventory.inventory_date)}). Les quantités ne sont plus modifiables : prochaine saisie possible demain. Le commentaire reste modifiable.
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table className="premium-table" style={{ width: '100%' }}>
              <thead>
                <tr style={{ fontSize: '0.6rem', textTransform: 'uppercase' }}>
                  <th>Consommable</th><th style={{ textAlign: 'right' }}>Théorique</th><th style={{ textAlign: 'right' }}>Physique</th><th style={{ textAlign: 'right' }}>Écart</th>
                </tr>
              </thead>
              <tbody style={{ fontSize: '0.72rem' }}>
                {(inventory.lines ?? []).map(l => {
                  const gap = Number(l.gap);
                  return (
                    <tr key={l.id}>
                      <td style={{ fontWeight: 700 }}>{displayStock(l.consumable_type_display)} <span style={{ color: 'hsl(var(--text-muted))', fontWeight: 400 }}>({unitLabel(l.unit)})</span></td>
                      <td style={{ textAlign: 'right' }}>{formatQty(l.system_quantity)}</td>
                      <td style={{ textAlign: 'right', fontWeight: 700 }}>{formatQty(l.physical_quantity)}</td>
                      <td style={{ textAlign: 'right', fontWeight: 800, color: gap < 0 ? 'hsl(var(--color-danger))' : gap > 0 ? 'hsl(var(--color-warning))' : 'hsl(var(--color-success))' }}>{formatGap(l.gap)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <label style={{ display: 'block', marginTop: '10px', fontSize: '0.68rem', fontWeight: 700 }}>
            Commentaire
            <textarea
              value={editComment}
              onChange={e => setEditComment(e.target.value)}
              rows={3}
              className="form-input"
              style={{ width: '100%', boxSizing: 'border-box', fontSize: '0.78rem', padding: '8px', marginTop: '4px' }}
              placeholder="Observation sur l'inventaire (facultatif)"
            />
          </label>
          {commentMsg && <div role={commentMsg.ok ? 'status' : 'alert'} style={{ fontSize: '0.72rem', marginTop: '4px', color: commentMsg.ok ? 'hsl(var(--color-success))' : 'hsl(var(--color-danger))' }}>{commentMsg.text}</div>}
          <button type="button" onClick={saveComment} disabled={commentSaving || editComment.trim() === (inventory.comment ?? '').trim()} className="btn btn-secondary" style={{ marginTop: '6px', padding: '10px 14px', fontSize: '0.78rem', width: '100%' }}>
            {commentSaving ? 'Enregistrement...' : 'Enregistrer le commentaire'}
          </button>
        </div>
      )}

      {!loading && !loadError && !done && (
        <form onSubmit={submit} data-testid="inventory-form">
          {stocks.length === 0 && <div style={{ fontSize: '0.72rem', color: 'hsl(var(--text-muted))' }}>Aucun consommable à inventorier.</div>}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {stocks.map(st => (
              <label key={st.id} style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap', fontSize: '0.74rem' }}>
                <span style={{ flex: '1 1 120px', fontWeight: 700, minWidth: 0 }}>
                  {STOCK_ICONS[st.consumable_type] || '📦'} {displayStock(st.consumable_type_display || st.consumable_type)}
                  <span style={{ display: 'block', fontWeight: 400, fontSize: '0.62rem', color: 'hsl(var(--text-muted))' }}>Système : {formatQty(st.quantity)} {unitLabel(st.unit)}</span>
                </span>
                <input
                  type="text" inputMode="decimal"
                  value={values[st.consumable_type] ?? ''}
                  onChange={e => setValues(prev => ({ ...prev, [st.consumable_type]: e.target.value }))}
                  placeholder={unitLabel(st.unit)}
                  aria-label={`Quantité physique ${displayStock(st.consumable_type_display || st.consumable_type)}`}
                  className="form-input"
                  style={{ width: '120px', maxWidth: '100%', height: '38px', fontSize: '0.85rem', padding: '0 8px' }}
                />
                <span style={{ fontSize: '0.65rem', color: 'hsl(var(--text-muted))', width: '40px' }}>{unitLabel(st.unit)}</span>
              </label>
            ))}
          </div>
          <label style={{ display: 'block', marginTop: '10px', fontSize: '0.68rem', fontWeight: 700 }}>
            Commentaire (facultatif)
            <textarea
              value={comment}
              onChange={e => setComment(e.target.value)}
              rows={2}
              className="form-input"
              style={{ width: '100%', boxSizing: 'border-box', fontSize: '0.78rem', padding: '8px', marginTop: '4px' }}
            />
          </label>
          {error && <div role="alert" style={{ marginTop: '6px', fontSize: '0.72rem', color: 'hsl(var(--color-danger))' }}>{error}</div>}
          <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-muted))', marginTop: '6px' }}>
            Une seule saisie par jour. Le stock système n'est pas modifié : seul l'écart est enregistré.
          </div>
          <button type="submit" disabled={saving || stocks.length === 0} className="btn btn-primary" style={{ marginTop: '8px', padding: '10px 14px', fontSize: '0.8rem', width: '100%' }}>
            {saving ? 'Enregistrement...' : "Enregistrer l'inventaire du jour"}
          </button>
        </form>
      )}
    </div>
  );
};
