import React, { useMemo, useState } from 'react';
import { FiArrowRight, FiSend } from 'react-icons/fi';
import { productionApi, BakeryNode, BreadPrice, BreadStock } from '@/api/services';
import { getErrorDetail } from '@/api/errors';
import { Modal } from '@/components/shared/Modal';

// BUG-382 (volet frontend de BUG-380, remarque.md : « donner à un gérant la possibilité
// d'envoyer les pains à une autre boulangerie sans avoir reçu la demande de cette autre
// boulangerie »). Contrat : docs/qa/rapports/dev-backend-2026-11-22-a6.md §1,
// `POST /api/production/transfers/send/`. Le serveur déstocke l'émettrice immédiatement ;
// la réceptrice valide ensuite (`confirm_reception`). Composant extrait de Production.tsx.

const fmt = (n: number): string => n.toLocaleString('fr-FR').replace(/ | /g, ' ');

export interface DirectSendModalProps {
  isOpen: boolean;
  onClose: () => void;
  /** Boulangeries (l'émettrice est exclue de la liste). */
  nodes: BakeryNode[];
  senderNodeId: string;
  breadPrices: BreadPrice[];
  /** Stocks de pains déjà chargés (ceux de l'émettrice sont affichés quand ils existent). */
  breadStocks: BreadStock[];
  /** Appelé après succès avec le message persistant à afficher ; la page recharge ses données. */
  onSent: (message: string) => void | Promise<void>;
}

const isPositiveInt = (raw: string): boolean => /^\d+$/.test(raw.trim()) && Number(raw) >= 1;

export const DirectSendModal: React.FC<DirectSendModalProps> = ({
  isOpen, onClose, nodes, senderNodeId, breadPrices, breadStocks, onSent,
}) => {
  const [toNode, setToNode] = useState('');
  const [qtys, setQtys] = useState<Record<number, string>>({});
  const [notes, setNotes] = useState('');
  const [step, setStep] = useState<'form' | 'recap'>('form');
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  const activePrices = useMemo(() => breadPrices.filter(bp => bp.is_active), [breadPrices]);
  const stockByPrice = useMemo(() => {
    const m = new Map<number, number>();
    breadStocks
      .filter(s => String(s.node) === senderNodeId)
      .forEach(s => m.set(s.bread_price, s.qty_available));
    return m;
  }, [breadStocks, senderNodeId]);

  const target = nodes.find(n => String(n.id) === toNode);

  const reset = () => {
    setToNode(''); setQtys({}); setNotes(''); setStep('form'); setError(null);
  };
  const close = () => { if (!sending) { reset(); onClose(); } };

  // Retourne les lignes valides ou affiche l'erreur et renvoie null.
  const validate = (): Array<{ bread_price: number; quantity_sent: number }> | null => {
    if (!senderNodeId) { setError('Compte non assigné à une boulangerie.'); return null; }
    if (!toNode) { setError('Sélectionnez la boulangerie destinataire.'); return null; }
    const lines: Array<{ bread_price: number; quantity_sent: number }> = [];
    for (const bp of activePrices) {
      const raw = (qtys[bp.id] ?? '').trim();
      if (raw === '') continue;
      if (!isPositiveInt(raw)) {
        setError(`Quantité invalide pour « ${bp.label} » : entrez un nombre entier supérieur ou égal à 1 (ni négatif, ni décimal).`);
        return null;
      }
      const q = Number(raw);
      const avail = stockByPrice.get(bp.id);
      if (avail !== undefined && q > avail) {
        setError(`Stock insuffisant pour « ${bp.label} » : ${fmt(avail)} disponible${avail > 1 ? 's' : ''}, ${fmt(q)} demandé${q > 1 ? 's' : ''}.`);
        return null;
      }
      lines.push({ bread_price: bp.id, quantity_sent: q });
    }
    if (lines.length === 0) { setError('Indiquez au moins une quantité de pains à envoyer.'); return null; }
    return lines;
  };

  const goRecap = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (validate()) setStep('recap');
  };

  const submit = async () => {
    if (sending) return;
    setError(null);
    const lines = validate();
    if (!lines) { setStep('form'); return; }
    setSending(true);
    try {
      await productionApi.transfers.send({ to_node: toNode, lines, notes: notes.trim() });
      const total = lines.reduce((sum, l) => sum + l.quantity_sent, 0);
      const label = target ? `${target.code} — ${target.name}` : 'la boulangerie destinataire';
      const msg = `${fmt(total)} pain${total > 1 ? 's' : ''} envoyé${total > 1 ? 's' : ''} à ${label}, en attente de validation par la boulangerie réceptrice.`;
      reset();
      onClose();
      await onSent(msg);
    } catch (err: unknown) {
      setError(getErrorDetail(err, "Impossible d'envoyer les pains."));
      setStep('form');
    } finally {
      setSending(false);
    }
  };

  const recapLines = step === 'recap'
    ? activePrices.filter(bp => isPositiveInt(qtys[bp.id] ?? '')).map(bp => ({ bp, q: Number(qtys[bp.id]) }))
    : [];
  const recapTotal = recapLines.reduce((s, l) => s + l.q, 0);

  const labelStyle: React.CSSProperties = {
    display: 'block', fontSize: '0.65rem', fontWeight: 700,
    color: 'hsl(var(--text-secondary))', marginBottom: '4px', textTransform: 'uppercase',
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={close}
      title="Envoyer des pains"
      subtitle="Envoi direct vers une autre boulangerie, sans demande préalable"
      maxWidth="460px"
      closeOnBackdropClick={!sending}
      footer={step === 'form' ? (
        <>
          <button type="button" className="btn btn-secondary" onClick={close} disabled={sending}>Annuler</button>
          <button type="submit" form="direct-send-form" className="btn btn-primary" style={{ minHeight: '40px' }}>
            Vérifier l'envoi <FiArrowRight />
          </button>
        </>
      ) : (
        <>
          <button type="button" className="btn btn-secondary" onClick={() => { setError(null); setStep('form'); }} disabled={sending}>Modifier</button>
          <button type="button" className="btn btn-primary" onClick={submit} disabled={sending} style={{ minHeight: '40px', opacity: sending ? 0.7 : 1 }}>
            <FiSend /> {sending ? 'Envoi en cours…' : 'Confirmer l’envoi'}
          </button>
        </>
      )}
    >
      {step === 'form' ? (
        <form id="direct-send-form" onSubmit={goRecap} style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
          <div>
            <label htmlFor="direct-send-to" style={labelStyle}>Envoyer à *</label>
            <select id="direct-send-to" value={toNode} onChange={e => { setToNode(e.target.value); setError(null); }} className="form-input" style={{ height: '36px' }}>
              <option value="">— Boulangerie destinataire —</option>
              {nodes.filter(n => String(n.id) !== senderNodeId).map(n => (
                <option key={n.id} value={n.id}>{n.code} — {n.name}</option>
              ))}
            </select>
          </div>
          <div>
            <span style={labelStyle}>Quantités à envoyer par catégorie *</span>
            {activePrices.length === 0 && (
              <div style={{ fontSize: '0.7rem', color: 'hsl(var(--text-muted))' }}>Aucune catégorie de pain active.</div>
            )}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              {activePrices.map(bp => {
                const avail = stockByPrice.get(bp.id);
                return (
                  <div key={bp.id} style={{ display: 'grid', gridTemplateColumns: '1fr 90px', gap: '8px', alignItems: 'center' }}>
                    <label htmlFor={`direct-send-q-${bp.id}`} style={{ fontSize: '0.75rem', color: 'hsl(var(--text-secondary))' }}>
                      {bp.label}
                      <span style={{ display: 'block', fontSize: '0.62rem', color: 'hsl(var(--text-muted))' }}>
                        {avail !== undefined ? `Disponible : ${fmt(avail)}` : 'Stock non renseigné'}
                      </span>
                    </label>
                    <input
                      id={`direct-send-q-${bp.id}`}
                      type="number" inputMode="numeric" min={1} step={1}
                      value={qtys[bp.id] ?? ''}
                      placeholder="0"
                      onChange={e => { setError(null); setQtys(prev => ({ ...prev, [bp.id]: e.target.value })); }}
                      className="form-input"
                      style={{ height: '36px', textAlign: 'right' }}
                    />
                  </div>
                );
              })}
            </div>
          </div>
          <div>
            <label htmlFor="direct-send-notes" style={labelStyle}>Note (facultative)</label>
            <input id="direct-send-notes" type="text" value={notes} onChange={e => setNotes(e.target.value)} placeholder="Motif, remarque…" className="form-input" style={{ height: '36px' }} />
          </div>
          {error && <div role="alert" style={{ fontSize: '0.72rem', color: 'hsl(var(--color-danger))', backgroundColor: 'hsl(var(--color-danger) / 0.08)', padding: '6px 8px', borderRadius: 'var(--radius-sm)' }}>{error}</div>}
        </form>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', fontSize: '0.8rem' }}>
          <div>
            Envoi à <strong>{target ? `${target.code} — ${target.name}` : toNode}</strong>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
            {recapLines.map(({ bp, q }) => (
              <div key={bp.id} style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span>{bp.label}</span><strong>{fmt(q)}</strong>
              </div>
            ))}
            <div style={{ display: 'flex', justifyContent: 'space-between', borderTop: '1px solid hsl(var(--border-color))', paddingTop: '4px' }}>
              <span>Total</span><strong>{fmt(recapTotal)} pain{recapTotal > 1 ? 's' : ''}</strong>
            </div>
          </div>
          {notes.trim() && <div style={{ fontStyle: 'italic', color: 'hsl(var(--text-muted))' }}>{notes.trim()}</div>}
          <div style={{ fontSize: '0.68rem', color: 'hsl(var(--text-muted))' }}>
            Ces pains seront retirés de votre stock dès l'envoi. La boulangerie réceptrice devra confirmer la quantité reçue.
          </div>
          {error && <div role="alert" style={{ fontSize: '0.72rem', color: 'hsl(var(--color-danger))', backgroundColor: 'hsl(var(--color-danger) / 0.08)', padding: '6px 8px', borderRadius: 'var(--radius-sm)' }}>{error}</div>}
        </div>
      )}
    </Modal>
  );
};
