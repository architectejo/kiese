import React, { useState } from 'react';
import { FiAlertTriangle, FiCheckCircle, FiArrowRight } from 'react-icons/fi';
import { productionApi, BreadTransfer, DisputeResolution } from '@/api/services';
import { getErrorDetail } from '@/api/errors';

// BUG-232 (volet frontend de BUG-223/224) : carte d'un transfert en litige (DISPUTED).
// - état du litige : badge, quantités envoyée / reçue / écart par catégorie ;
// - récepteur : recomptage possible (`confirm_reception` accepte DISPUTED) ;
// - gérant de la boulangerie ÉMETTRICE et siège/direction : « Résoudre le litige »
//   (`resolve_dispute`, motif obligatoire). Jamais proposé au récepteur : le serveur refuse (403).
// Composant extrait de Production.tsx (CLAUDE.md §4).

export interface TransferDisputeCardProps {
  transfer: BreadTransfer;
  /** Boulangerie de l'utilisateur (null pour le siège). */
  userNode: string | null | undefined;
  userRole: string | undefined;
  canAccessAllNodes: boolean;
  /** Recharge les données ; reçoit un message de succès à afficher. */
  onChanged: (message: string) => void | Promise<void>;
}

const RESOLUTION_LABELS: Record<DisputeResolution, string> = {
  ALIGN_ON_RECEIVED: 'Aligner sur la quantité reçue',
  ALIGN_ON_SENT: 'Aligner sur la quantité envoyée',
};

export const TransferDisputeCard: React.FC<TransferDisputeCardProps> = ({
  transfer: t, userNode, userRole, canAccessAllNodes, onChanged,
}) => {
  const [mode, setMode] = useState<'none' | 'resolve' | 'recount'>('none');
  const [resolution, setResolution] = useState<DisputeResolution>('ALIGN_ON_RECEIVED');
  const [reason, setReason] = useState('');
  const [recount, setRecount] = useState<Record<number, number>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isReceiver = !!userNode && userNode === t.to_node;
  const canResolve = canAccessAllNodes
    || (userRole === 'GERANT' && !!userNode && userNode === t.from_node);
  const totalGap = (t.lines || []).reduce((sum, l) => sum + (l.quantity_gap ?? 0), 0);

  const handleResolve = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setError(null);
    if (!reason.trim()) { setError('Le motif de résolution est obligatoire.'); return; }
    setBusy(true);
    try {
      await productionApi.transfers.resolveDispute(t.id, { resolution, reason: reason.trim() });
      await onChanged('Litige résolu : les stocks sont alignés et le blocage de clôture de caisse est levé.');
    } catch (err: unknown) {
      setError(getErrorDetail(err, 'Impossible de résoudre le litige.'));
    } finally {
      setBusy(false);
    }
  };

  const handleRecount = async () => {
    if (busy) return;
    setError(null);
    const lines = (t.lines || []).map(l => ({
      bread_price: l.bread_price,
      quantity_received: recount[l.bread_price] ?? l.quantity_received ?? l.quantity_sent,
    }));
    if (lines.some(l => !Number.isInteger(l.quantity_received) || l.quantity_received < 0)) {
      setError('Les quantités recomptées doivent être des nombres entiers positifs ou nuls.');
      return;
    }
    setBusy(true);
    try {
      await productionApi.transfers.confirm(t.id, lines);
      await onChanged('Recomptage enregistré. Si les quantités concordent, le litige est levé ; sinon il reste ouvert.');
    } catch (err: unknown) {
      setError(getErrorDetail(err, 'Impossible d\'enregistrer le recomptage.'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ backgroundColor: 'hsl(var(--color-danger) / 0.06)', border: '1px solid hsl(var(--color-danger) / 0.4)', borderRadius: 'var(--radius-sm)', padding: '8px 12px', fontSize: '0.68rem' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '4px', flexWrap: 'wrap' }}>
        <FiAlertTriangle style={{ color: 'hsl(var(--color-danger))' }} />
        <strong style={{ color: 'hsl(var(--color-danger))' }}>LITIGE D'ÉCART — Signalé à la Direction</strong>
        <span className="badge badge-danger" style={{ fontSize: '0.52rem' }}>EN LITIGE</span>
        <span className="badge badge-warning" style={{ fontSize: '0.52rem' }}>Clôture de caisse bloquée</span>
      </div>
      <div style={{ fontWeight: 700, marginBottom: '4px' }}>
        {t.from_node_display || t.from_node} <FiArrowRight style={{ verticalAlign: 'middle' }} /> {t.to_node_display || t.to_node}
        <span style={{ marginLeft: '6px', color: 'hsl(var(--color-danger))' }}>écart total {totalGap > 0 ? `+${totalGap}` : totalGap}</span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '3px', color: 'hsl(var(--text-secondary))' }}>
        {(t.lines || []).map(l => {
          const gap = l.quantity_gap ?? 0;
          return (
            <div key={l.bread_price} style={{ display: 'grid', gridTemplateColumns: 'minmax(80px,1fr) auto auto', gap: '8px', alignItems: 'center' }}>
              <span>{l.bread_price_display || `Pain ${l.unit_price} FC`}</span>
              <span>envoyé {l.quantity_sent} → reçu {l.quantity_received ?? '?'}</span>
              <span style={{ fontWeight: 700, color: gap !== 0 ? 'hsl(var(--color-danger))' : 'hsl(var(--color-success))' }}>
                {gap !== 0 ? `écart ${gap > 0 ? '+' : ''}${gap}` : 'conforme'}
              </span>
            </div>
          );
        })}
      </div>
      {t.notes && <div style={{ marginTop: '4px', fontStyle: 'italic', color: 'hsl(var(--text-muted))' }}>{t.notes}</div>}

      {error && <div role="alert" style={{ marginTop: '6px', color: 'hsl(var(--color-danger))', fontWeight: 700 }}>{error}</div>}

      {(isReceiver || canResolve) && mode === 'none' && (
        <div style={{ display: 'flex', gap: '6px', marginTop: '8px', flexWrap: 'wrap' }}>
          {isReceiver && (
            <button type="button" className="btn btn-secondary" style={{ padding: '6px 10px', fontSize: '0.68rem', minHeight: '36px' }} onClick={() => setMode('recount')}>
              Recompter la réception
            </button>
          )}
          {canResolve && (
            <button type="button" className="btn btn-primary" style={{ padding: '6px 10px', fontSize: '0.68rem', minHeight: '36px' }} onClick={() => setMode('resolve')}>
              <FiCheckCircle /> Résoudre le litige
            </button>
          )}
        </div>
      )}

      {mode === 'recount' && (
        <div style={{ marginTop: '8px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
          {(t.lines || []).map(l => (
            <label key={l.bread_price} style={{ display: 'grid', gridTemplateColumns: '1fr 80px', gap: '6px', alignItems: 'center' }}>
              <span>{l.bread_price_display || `Pain ${l.unit_price} FC`} (envoyé {l.quantity_sent})</span>
              <input
                type="number" min={0} step={1} inputMode="numeric"
                className="form-input"
                value={recount[l.bread_price] ?? l.quantity_received ?? l.quantity_sent}
                onChange={ev => setRecount(prev => ({ ...prev, [l.bread_price]: Number(ev.target.value) }))}
                style={{ height: '32px', textAlign: 'right', fontWeight: 800 }}
              />
            </label>
          ))}
          <div style={{ display: 'flex', gap: '6px' }}>
            <button type="button" className="btn btn-primary" disabled={busy} onClick={handleRecount} style={{ flex: 1, minHeight: '36px', fontSize: '0.68rem' }}>
              {busy ? 'Envoi…' : 'Enregistrer le recomptage'}
            </button>
            <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => { setMode('none'); setError(null); }} style={{ minHeight: '36px', fontSize: '0.68rem' }}>Annuler</button>
          </div>
        </div>
      )}

      {mode === 'resolve' && (
        <form onSubmit={handleResolve} style={{ marginTop: '8px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
          <select className="form-input" value={resolution} onChange={ev => setResolution(ev.target.value as DisputeResolution)} style={{ minHeight: '36px', fontSize: '0.7rem' }}>
            {(Object.keys(RESOLUTION_LABELS) as DisputeResolution[]).map(k => (
              <option key={k} value={k}>{RESOLUTION_LABELS[k]}</option>
            ))}
          </select>
          <textarea
            className="form-input" rows={2} required
            placeholder="Motif de la résolution (obligatoire)"
            value={reason}
            onChange={ev => setReason(ev.target.value)}
            style={{ fontSize: '0.7rem' }}
          />
          <div style={{ display: 'flex', gap: '6px' }}>
            <button type="submit" className="btn btn-primary" disabled={busy} style={{ flex: 1, minHeight: '36px', fontSize: '0.68rem' }}>
              {busy ? 'Envoi…' : 'Confirmer la résolution'}
            </button>
            <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => { setMode('none'); setError(null); }} style={{ minHeight: '36px', fontSize: '0.68rem' }}>Annuler</button>
          </div>
        </form>
      )}
    </div>
  );
};
