import React, { useState } from 'react';
import { FiAlertCircle, FiClock, FiMinus, FiPlus, FiPrinter, FiSlash, FiX } from 'react-icons/fi';
import type { ServedLinePayload } from '@/api/services';

/** BUG-318 : ligne d'une facture en attente, avec identifiant serveur et prix figé. */
export interface PendingDeliveryLine {
  id?: string | number;
  label: string;
  qty: number;
  unitPrice: number;
}

export interface PendingDeliveryItem {
  _apiId: string;
  id: string;
  lines: PendingDeliveryLine[];
  totalValue: number;
  createdAt: string;
}

interface Props {
  item: PendingDeliveryItem;
  /** Message d'erreur renvoyé par l'API (`detail`) pour cette facture. */
  errorMessage: string | null;
  onCancel: () => void;
  /** `lines` défini uniquement si au moins une quantité servie diffère du commandé. */
  onDeliver: (lines?: ServedLinePayload[]) => void;
  onNotServed: (reason: string) => Promise<void>;
}

const EXPIRY_MS = 12 * 3600 * 1000;
const REASON_MAX = 200;

const fmtFc = (n: number): string => `${Math.round(n).toLocaleString('fr-FR')} FC`;

/**
 * Pied d'une carte « En attente de livraison » : délai d'expiration, quantité servie par
 * ligne (livraison partielle), « Non servi » avec motif, annulation et confirmation.
 * Les règles (bornes, statuts, 409) sont appliquées côté serveur ; l'écran les affiche.
 */
export const PendingDeliveryActions: React.FC<Props> = ({ item, errorMessage, onCancel, onDeliver, onNotServed }) => {
  const [served, setServed] = useState<number[]>(() => item.lines.map(l => l.qty));
  const [confirmingNS, setConfirmingNS] = useState(false);
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);

  const msLeft = EXPIRY_MS - (Date.now() - new Date(item.createdAt).getTime());
  const hLeft = Math.floor(msLeft / 3600000);
  const mLeft = Math.floor((msLeft % 3600000) / 60000);
  const isUrgent = msLeft < 3600000;

  const setQty = (i: number, raw: string | number) => {
    const max = item.lines[i].qty;
    const n = typeof raw === 'number' ? raw : parseInt(raw, 10);
    const v = Number.isFinite(n) ? Math.min(max, Math.max(0, Math.trunc(n))) : 0;
    setServed(prev => prev.map((q, k) => (k === i ? v : q)));
  };

  const changed = item.lines.some((l, i) => served[i] !== l.qty);
  const servedTotal = item.lines.reduce((a, l, i) => a + served[i] * l.unitPrice, 0);
  const allZero = item.lines.length > 0 && served.every(q => q === 0);

  const deliver = () => {
    if (allZero) return;
    if (!changed) { onDeliver(); return; }
    const payload: ServedLinePayload[] = [];
    item.lines.forEach((l, i) => { if (l.id != null) payload.push({ id: l.id, quantity: served[i] }); });
    onDeliver(payload);
  };

  const declareNotServed = async () => {
    setBusy(true);
    try { await onNotServed(reason.trim()); } finally { setBusy(false); }
  };

  const stepBtn: React.CSSProperties = {
    width: '34px', height: '34px', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 0, flexShrink: 0,
  };

  return (
    <div style={{ padding: '8px 12px', borderTop: '1px solid hsl(var(--color-warning) / 0.2)', backgroundColor: 'hsl(var(--color-warning) / 0.04)', display: 'flex', flexDirection: 'column', gap: '8px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '5px', fontSize: '0.6rem', color: isUrgent ? 'hsl(var(--color-danger))' : 'hsl(var(--text-muted))', fontWeight: isUrgent ? 700 : 400 }}>
        <FiClock style={{ fontSize: '0.68rem', flexShrink: 0 }} />
        <span>
          {msLeft > 0
            ? `Expire dans ${hLeft}h${String(mLeft).padStart(2, '0')}`
            : 'Expirée — sera déclarée non servie'}
        </span>
      </div>

      {/* Quantité servie par ligne */}
      {item.lines.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          <span style={{ fontSize: '0.6rem', fontWeight: 700, textTransform: 'uppercase', color: 'hsl(var(--text-muted))' }}>
            Quantité servie
          </span>
          {item.lines.map((l, i) => (
            <div key={l.id ?? i} style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
              <span style={{ flex: '1 1 110px', minWidth: 0, fontSize: '0.72rem', color: 'hsl(var(--text-secondary))' }}>{l.label}</span>
              <button type="button" className="btn btn-secondary" style={stepBtn} aria-label={`Diminuer ${l.label}`}
                disabled={served[i] <= 0} onClick={() => setQty(i, served[i] - 1)}><FiMinus /></button>
              <input
                type="number" inputMode="numeric" min={0} max={l.qty} step={1}
                value={served[i]}
                aria-label={`Quantité servie ${l.label}`}
                onChange={e => setQty(i, e.target.value)}
                className="form-input"
                style={{ width: '56px', height: '34px', textAlign: 'center', fontWeight: 800, padding: '0 4px' }}
              />
              <button type="button" className="btn btn-secondary" style={stepBtn} aria-label={`Augmenter ${l.label}`}
                disabled={served[i] >= l.qty} onClick={() => setQty(i, served[i] + 1)}><FiPlus /></button>
              <span style={{ fontSize: '0.64rem', color: served[i] < l.qty ? 'hsl(var(--color-warning))' : 'hsl(var(--text-muted))', fontWeight: 700, whiteSpace: 'nowrap' }}>
                servi {served[i]} sur {l.qty}
              </span>
            </div>
          ))}
          <div style={{ fontSize: '0.7rem', color: 'hsl(var(--text-secondary))' }}>
            Total servi : <strong style={{ color: 'hsl(var(--accent-color))' }}>{fmtFc(servedTotal)}</strong>
            {changed && <span style={{ color: 'hsl(var(--text-muted))' }}> (commandé : {fmtFc(item.totalValue)})</span>}
          </div>
          {allZero && (
            <div style={{ fontSize: '0.68rem', color: 'hsl(var(--color-warning))' }}>
              Aucun pain servi : utilisez « Non servi » pour cette facture.
            </div>
          )}
        </div>
      )}

      {errorMessage && (
        <div role="alert" style={{ backgroundColor: 'hsl(var(--color-danger) / 0.1)', border: '1px solid hsl(var(--color-danger) / 0.3)', borderRadius: 'var(--radius-sm)', padding: '6px 9px', fontSize: '0.68rem', color: 'hsl(var(--color-danger))', display: 'flex', alignItems: 'flex-start', gap: '6px' }}>
          <FiAlertCircle style={{ flexShrink: 0, marginTop: '1px' }} />
          <span>{errorMessage}</span>
        </div>
      )}

      {confirmingNS ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', border: '1px solid hsl(var(--border-color))', borderRadius: 'var(--radius-sm)', padding: '8px' }}>
          <span style={{ fontSize: '0.72rem', fontWeight: 700 }}>
            Déclarer la facture {item.id} « Non servi » ? Aucun pain ne sera remis ; la valeur de la commande est annulée.
          </span>
          <input
            type="text" maxLength={REASON_MAX} value={reason}
            onChange={e => setReason(e.target.value)}
            placeholder="Motif (optionnel, 200 caractères max)"
            aria-label="Motif non servi"
            className="form-input" style={{ fontSize: '0.75rem', height: '34px' }}
          />
          <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
            <button type="button" className="btn btn-secondary" style={{ flex: '1 1 100px', padding: '8px' }} disabled={busy}
              onClick={() => { setConfirmingNS(false); setReason(''); }}>Retour</button>
            <button type="button" className="btn btn-primary" style={{ flex: '2 1 160px', padding: '8px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}
              disabled={busy} onClick={declareNotServed}>
              <FiSlash /> <span>{busy ? 'Enregistrement…' : 'Confirmer « Non servi »'}</span>
            </button>
          </div>
        </div>
      ) : (
        <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
          <button type="button" onClick={onCancel} className="btn btn-secondary"
            style={{ flex: '1 1 90px', minHeight: '40px', padding: '7px 10px', fontSize: '0.72rem', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '5px', color: 'hsl(var(--color-danger))', borderColor: 'hsl(var(--color-danger) / 0.4)' }}
            title="Annuler la commande — restitue le stock et la balance client">
            <FiX /><span>Annuler</span>
          </button>
          <button type="button" onClick={() => setConfirmingNS(true)} className="btn btn-secondary"
            style={{ flex: '1 1 90px', minHeight: '40px', padding: '7px 10px', fontSize: '0.72rem', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '5px' }}
            title="Déclarer la facture non servie (aucun pain remis)">
            <FiSlash /><span>Non servi</span>
          </button>
          <button type="button" onClick={deliver} disabled={allZero} className="btn btn-primary"
            style={{ flex: '2 1 150px', minHeight: '40px', padding: '7px', fontSize: '0.78rem', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}
            title="Confirmer la livraison et imprimer le reçu">
            <FiPrinter /><span>{changed ? 'Confirmer livraison partielle' : 'Confirmer livraison'}</span>
          </button>
        </div>
      )}
    </div>
  );
};
