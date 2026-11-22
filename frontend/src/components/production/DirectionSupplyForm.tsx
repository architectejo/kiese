import React, { useState } from 'react';
import { productionApi } from '@/api/services';
import type { GlobalConsumableType } from '@/api/consumablesDirection';
import { getErrorDetail } from '@/api/errors';
import { formatQty, parseDecimalInput, unitLabel } from './consumableFormat';
import { displayStock } from './productionHelpers';

interface Props {
  types: GlobalConsumableType[];
  /** Id du nœud technique direction (SIEGE) et stock actuel par consommable. */
  direction: { node: number; code: string; stocks: Record<string, string> };
  /** Rappelé après un approvisionnement réussi (rafraîchit le tableau). */
  onDone: () => Promise<void> | void;
}

/** Prix unitaire : entier ou 2 décimales max, virgule ou point. */
function parsePrice(raw: string): string | null {
  const s = raw.trim().replace(',', '.');
  if (s === '') return '0';
  return /^\d+(\.\d{1,2})?$/.test(s) ? s : null;
}

// BUG-388 : approvisionnement du stock direction (ENTRY sur le stock du nœud SIEGE) via
// POST /api/production/movements/. Le prix unitaire alimente le CUMP du stock direction.
export const DirectionSupplyForm: React.FC<Props> = ({ types, direction, onDone }) => {
  const [type, setType] = useState(types[0]?.code ?? '');
  const [qty, setQty] = useState('');
  const [price, setPrice] = useState('');
  const [note, setNote] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  const sel = types.find(t => t.code === type) ?? types[0];

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setOk(null);
    if (!sel) { setError('Choisissez un consommable.'); return; }
    const q = parseDecimalInput(qty);
    if (q === null || Number(q) <= 0) {
      setError('Quantité invalide : nombre strictement positif, 3 décimales au maximum.');
      return;
    }
    const p = parsePrice(price);
    if (p === null) {
      setError('Prix unitaire invalide : nombre positif, 2 décimales au maximum.');
      return;
    }
    setSending(true);
    try {
      // Le stock direction est identifié côté serveur par (nœud, type) : on le retrouve.
      const stocks = await productionApi.stocks.list({ node: String(direction.node), consumable_type: sel.code });
      const stock = stocks.data.find(s => s.consumable_type === sel.code);
      if (!stock) {
        setError('Compte de stock direction introuvable pour ce consommable.');
        return;
      }
      await productionApi.movements.create({
        node: String(direction.node),
        stock: stock.id,
        movement_type: 'ENTRY',
        quantity: q,
        unit_price: p,
        description: note.trim() || 'Approvisionnement stock direction',
      });
      setOk(`${formatQty(q)} ${unitLabel(sel.unit)} ajouté(s) au stock direction.`);
      setQty('');
      setPrice('');
      setNote('');
      await onDone();
    } catch (err) {
      setError(getErrorDetail(err, "Impossible d'approvisionner le stock direction."));
    } finally {
      setSending(false);
    }
  };

  return (
    <form onSubmit={submit} style={{ marginTop: '14px', borderTop: '1px solid hsl(var(--border-color))', paddingTop: '12px' }} data-testid="supply-form">
      <div style={{ fontSize: '0.7rem', fontWeight: 800, textTransform: 'uppercase', color: 'hsl(var(--text-secondary))', marginBottom: '8px' }}>
        Approvisionner le stock direction
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '8px', marginBottom: '8px' }}>
        <label style={{ display: 'flex', flexDirection: 'column', gap: '2px', fontSize: '0.66rem', fontWeight: 700 }}>
          Consommable
          <select value={type} onChange={e => setType(e.target.value)} className="form-input" style={{ height: '36px', fontSize: '0.8rem', width: '100%', boxSizing: 'border-box' }}>
            {types.map(t => <option key={t.code} value={t.code}>{displayStock(t.label)} ({unitLabel(t.unit)})</option>)}
          </select>
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: '2px', fontSize: '0.66rem', fontWeight: 700 }}>
          Quantité{sel ? ` (${unitLabel(sel.unit)})` : ''}
          <input type="text" inputMode="decimal" value={qty} onChange={e => setQty(e.target.value)} placeholder="ex. 0,25" aria-label="Quantité à ajouter" className="form-input" style={{ height: '36px', fontSize: '0.8rem', padding: '0 8px', width: '100%', boxSizing: 'border-box' }} />
        </label>
        <label style={{ display: 'flex', flexDirection: 'column', gap: '2px', fontSize: '0.66rem', fontWeight: 700 }}>
          Prix unitaire (FC)
          <input type="text" inputMode="decimal" value={price} onChange={e => setPrice(e.target.value)} placeholder="0" aria-label="Prix unitaire en FC" className="form-input" style={{ height: '36px', fontSize: '0.8rem', padding: '0 8px', width: '100%', boxSizing: 'border-box' }} />
        </label>
      </div>
      {sel && (
        <div style={{ fontSize: '0.68rem', color: 'hsl(var(--text-secondary))', marginBottom: '6px' }}>
          Stock direction actuel : <strong>{formatQty(direction.stocks[sel.code])} {unitLabel(sel.unit)}</strong>.
          Le prix unitaire sert au coût moyen pondéré ; laissé vide, il vaut 0 FC.
        </div>
      )}
      <input type="text" value={note} onChange={e => setNote(e.target.value)} maxLength={255} placeholder="Note / référence (facultative)" aria-label="Note ou référence" className="form-input" style={{ height: '36px', fontSize: '0.78rem', padding: '0 10px', width: '100%', boxSizing: 'border-box', marginBottom: '8px' }} />
      {error && <div role="alert" style={{ color: 'hsl(var(--color-danger))', fontSize: '0.74rem', marginBottom: '6px' }}>{error}</div>}
      {ok && <div role="status" style={{ color: 'hsl(var(--color-success))', fontSize: '0.74rem', marginBottom: '6px' }}>{ok}</div>}
      <button type="submit" disabled={sending || types.length === 0} className="btn btn-primary" style={{ padding: '10px 14px', fontSize: '0.8rem', width: '100%', opacity: sending ? 0.6 : 1 }}>
        {sending ? 'Enregistrement...' : 'Approvisionner le stock direction'}
      </button>
    </form>
  );
};
